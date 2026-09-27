"""
Orquesta la emision completa de un comprobante a partir del contrato
generico que cualquier POS le manda a este microservicio:

    {
      "referencia_externa": "VENTA-000456",
      "cliente": {...opcional...},
      "items": [{"codigo", "descripcion", "cantidad",
                 "precio_unitario_sin_impuesto", "tiene_iva", "descuento"}],
      "pagos": [{"forma_pago": "efectivo", "total": 1.95,
                 "plazo": null, "unidad_tiempo": null}]
    }

Este es el UNICO lugar donde se conectan calculos + clave_acceso +
xml_builder + firmador_xades + sri_client. El endpoint (views.py) solo
valida el request y llama a esta funcion.
"""

from datetime import date
from django.db import transaction, IntegrityError

from comprobantes.models import Comprobante, DetalleComprobante
from comprobantes.services.calculos import calcular_linea, calcular_totales
from comprobantes.services.clave_acceso import generar_clave_acceso
from comprobantes.services.xml_builder import construir_xml_factura
from comprobantes.services.firmador_xades import firmar_xades_bes
from comprobantes.services.sri_client import procesar_comprobante_completo
from core.crypto import descifrar_bytes, descifrar_texto

# Catalogo de formas de pago del SRI. El "credito" (fiado) usa el mismo
# codigo que efectivo porque no interviene el sistema financiero -- lo
# que lo distingue es el plazo, no el codigo.
FORMAS_PAGO_SRI = {
    'efectivo': '01',
    'tarjeta_debito': '16',
    'tarjeta_credito': '19',
    'transferencia': '20',
    'credito': '01',
}


class EmisionError(Exception):
    """Error de validacion de negocio (no de infraestructura)."""
    def __init__(self, mensaje, codigo='error_emision'):
        self.mensaje = mensaje
        self.codigo = codigo
        super().__init__(mensaje)


def emitir_comprobante(emisor, payload: dict) -> dict:
    """
    Punto de entrada unico para emitir una factura. Devuelve un dict
    con el resultado, listo para serializar como respuesta HTTP.
    """
    referencia_externa = payload.get('referencia_externa', '')

    # --- Idempotencia: si esta venta ya se facturo, devuelve lo mismo ---
    if referencia_externa:
        existente = Comprobante.objects.filter(
            emisor=emisor, referencia_externa=referencia_externa
        ).first()
        if existente:
            return _serializar_resultado(existente)

    if not emisor.certificado_p12:
        raise EmisionError(
            'Este emisor todavia no tiene un certificado .p12 cargado.',
            codigo='sin_certificado',
        )

    items = payload.get('items') or []
    if not items:
        raise EmisionError('El comprobante debe tener al menos un item.', codigo='sin_items')

    pagos_payload = payload.get('pagos') or []
    if not pagos_payload:
        raise EmisionError('Debe indicar al menos una forma de pago.', codigo='sin_pagos')

    # --- 1. Calcular cada linea (desarma el precio con IVA incluido) ---
    lineas_calculadas = []
    for item in items:
        try:
            calculo = calcular_linea(
                precio_unitario_sin_impuesto=item['precio_unitario_sin_impuesto'],
                cantidad=item['cantidad'],
                tiene_iva=item['tiene_iva'],
                descuento=item.get('descuento', 0),
            )
        except KeyError as exc:
            raise EmisionError(f'Falta el campo {exc} en un item.', codigo='item_invalido')
        calculo['_original'] = item
        lineas_calculadas.append(calculo)

    totales = calcular_totales(lineas_calculadas)

    # --- 2. Formas de pago: traducir a codigos del SRI ---
    formas_pago_sri = []
    for pago in pagos_payload:
        codigo = FORMAS_PAGO_SRI.get(pago.get('forma_pago'))
        if not codigo:
            raise EmisionError(
                f"Forma de pago '{pago.get('forma_pago')}' no reconocida. "
                f"Usa una de: {', '.join(FORMAS_PAGO_SRI)}.",
                codigo='forma_pago_invalida',
            )
        fp = {'codigo': codigo, 'total': pago['total']}
        if pago.get('plazo'):
            fp['plazo'] = pago['plazo']
            fp['unidad_tiempo'] = pago.get('unidad_tiempo', 'dias')
        formas_pago_sri.append(fp)

    suma_pagos = sum(p['total'] for p in formas_pago_sri)
    if abs(float(suma_pagos) - float(totales['importe_total'])) > 0.01:
        raise EmisionError(
            f"La suma de los pagos ({suma_pagos}) no coincide con el total de la venta ({totales['importe_total']}).",
            codigo='pagos_no_cuadran',
        )

    # --- 3. Datos del comprador (opcional -> consumidor final) ---
    cliente = payload.get('cliente') or {}
    tipo_id = cliente.get('tipo_identificacion', '07')
    identificacion = cliente.get('identificacion', '9999999999999')
    razon_social = cliente.get('razon_social', 'CONSUMIDOR FINAL')
    direccion = cliente.get('direccion', '')

    # --- 4. Secuencial + clave de acceso (dentro de una transaccion para
    #         que el incremento del secuencial sea atomico) ---
    with transaction.atomic():
        secuencial = emisor.siguiente_secuencial_factura()
        clave_acceso = generar_clave_acceso(
            fecha_emision=date.today(),
            ruc=emisor.ruc,
            ambiente=emisor.ambiente,
            codigo_establecimiento=emisor.codigo_establecimiento,
            codigo_punto_emision=emisor.codigo_punto_emision,
            secuencial=secuencial,
        )

        try:
            comprobante = Comprobante.objects.create(
                emisor=emisor,
                secuencial=str(secuencial).zfill(9),
                clave_acceso=clave_acceso,
                referencia_externa=referencia_externa,
                tipo_identificacion_comprador=tipo_id,
                identificacion_comprador=identificacion,
                razon_social_comprador=razon_social,
                direccion_comprador=direccion,
                total_sin_impuestos=totales['total_sin_impuestos'],
                total_iva=totales['total_iva'],
                importe_total=totales['importe_total'],
                payload_original=payload,
            )
        except IntegrityError:
            # carrera: otra peticion con la misma referencia_externa gano
            existente = Comprobante.objects.get(emisor=emisor, referencia_externa=referencia_externa)
            return _serializar_resultado(existente)

        detalles_creados = []
        for calculo in lineas_calculadas:
            item = calculo['_original']
            detalle = DetalleComprobante.objects.create(
                comprobante=comprobante,
                codigo_principal=item['codigo'],
                descripcion=item['descripcion'],
                cantidad=item['cantidad'],
                precio_unitario_sin_impuesto=calculo['precio_unitario_sin_impuesto'],
                descuento=calculo['descuento'],
                precio_total_sin_impuesto=calculo['precio_total_sin_impuesto'],
                codigo_porcentaje_iva=calculo['codigo_porcentaje_iva'],
                tarifa_iva=calculo['tarifa_iva'],
                valor_iva=calculo['valor_iva'],
            )
            detalles_creados.append(detalle)

    # --- 5. Armar XML, firmar, enviar al SRI (fuera de la transaccion:
    #         son operaciones lentas de red, no deben bloquear la DB) ---
    xml_sin_firmar = construir_xml_factura(
        emisor=emisor,
        comprobante=comprobante,
        detalles=detalles_creados,
        resumen_por_tarifa=totales['resumen_por_tarifa'],
        formas_pago=formas_pago_sri,
    )
    comprobante.xml_generado = xml_sin_firmar

    try:
        p12_bytes = descifrar_bytes(bytes(emisor.certificado_p12))
        password = descifrar_texto(emisor.certificado_password_cifrada)
        xml_firmado = firmar_xades_bes(xml_sin_firmar, p12_bytes, password)
    except Exception as exc:
        comprobante.estado = Comprobante.ESTADO_ERROR
        comprobante.mensaje_error = f'Error al firmar: {exc}'
        comprobante.save()
        raise EmisionError(f'Error al firmar el comprobante: {exc}', codigo='error_firma')

    comprobante.xml_firmado = xml_firmado
    comprobante.estado = Comprobante.ESTADO_FIRMADO
    comprobante.save()

    resultado_sri = procesar_comprobante_completo(
        xml_firmado=xml_firmado,
        clave_acceso=clave_acceso,
        ambiente=emisor.ambiente,
    )

    _aplicar_resultado_sri(comprobante, resultado_sri)

    return _serializar_resultado(comprobante)


def _aplicar_resultado_sri(comprobante: Comprobante, resultado_sri: dict):
    from django.utils.dateparse import parse_datetime

    estado_final = resultado_sri.get('estado_final')

    if estado_final == 'AUTORIZADO':
        comprobante.estado = Comprobante.ESTADO_AUTORIZADO
        comprobante.numero_autorizacion = resultado_sri.get('numero_autorizacion', '')
        comprobante.xml_firmado = resultado_sri.get('comprobante_autorizado') or comprobante.xml_firmado

        fecha_texto = resultado_sri.get('fecha_autorizacion')
        if fecha_texto:
            fecha_parseada = parse_datetime(fecha_texto)
            if fecha_parseada:
                comprobante.fecha_autorizacion = fecha_parseada
    elif estado_final == 'NO_AUTORIZADO':
        comprobante.estado = Comprobante.ESTADO_NO_AUTORIZADO
        comprobante.mensaje_error = str(resultado_sri.get('mensajes', ''))
    elif estado_final == 'DEVUELTA':
        comprobante.estado = Comprobante.ESTADO_ERROR
        comprobante.mensaje_error = str(resultado_sri.get('mensajes', ''))
    else:  # EN_PROCESO, ERROR_CONEXION, etc.
        comprobante.estado = Comprobante.ESTADO_ENVIADO
        comprobante.mensaje_error = str(resultado_sri.get('mensajes', ''))

    comprobante.save()


def _serializar_resultado(comprobante: Comprobante) -> dict:
    return {
        'id': comprobante.id,
        'estado': comprobante.estado,
        'clave_acceso': comprobante.clave_acceso,
        'secuencial': comprobante.secuencial,
        'numero_autorizacion': comprobante.numero_autorizacion,
        'importe_total': str(comprobante.importe_total),
        'mensaje_error': comprobante.mensaje_error,
        'xml_firmado': comprobante.xml_firmado,
    }
