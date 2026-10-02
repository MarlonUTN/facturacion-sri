

from datetime import date
from decimal import Decimal
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

    # --- Idempotencia real: solo se "cortocircuita" si YA esta AUTORIZADO.
    # Cualquier otro estado (CREADO, FIRMADO, ENVIADO, ERROR, NO_AUTORIZADO)
    # significa que el intento anterior no se completo -- se reintenta en
    # vez de devolver para siempre el mismo fallo congelado.
    if referencia_externa:
        existente = Comprobante.objects.filter(
            emisor=emisor, referencia_externa=referencia_externa
        ).first()
        if existente:
            if existente.estado == Comprobante.ESTADO_AUTORIZADO:
                return _serializar_resultado(existente)
            return _reintentar_existente(existente)

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

    # Tolerancia: tu POS suma el IVA sin redondear por linea y redondea al
    # final, mientras el calculo fiscal redondea por linea (como el SRI).
    # Pueden diferir por 1-2 centavos. Se tolera y se ajusta el ultimo
    # pago para que el XML quede consistente: sum(pagos) == importeTotal.
    suma_pagos = sum((p['total'] for p in formas_pago_sri), Decimal('0'))
    diferencia = totales['importe_total'] - suma_pagos
    if abs(diferencia) > Decimal('0.02'):
        raise EmisionError(
            f"La suma de los pagos ({suma_pagos}) no coincide con el total de la venta ({totales['importe_total']}).",
            codigo='pagos_no_cuadran',
        )
    if diferencia != 0:
        formas_pago_sri[-1]['total'] = formas_pago_sri[-1]['total'] + diferencia

    # Lo que se guarda como respaldo debe reflejar los pagos ya ajustados
    payload_guardar = dict(payload)
    payload_guardar['pagos'] = [
        {**dict(orig), 'total': fp['total']}
        for orig, fp in zip(pagos_payload, formas_pago_sri)
    ]

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
                payload_original=payload_guardar,
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


def _reintentar_existente(comprobante: Comprobante) -> dict:
    """
    Retoma un comprobante que quedo sin autorizar. NUNCA genera un nuevo
    secuencial ni una nueva clave de acceso -- esos ya se "gastaron" en
    el intento anterior y deben conservarse para no dejar huecos ni
    duplicados ante el SRI.

    Casos cubiertos:
      - Nunca se firmo (p.ej. fallo FERNET_MASTER_KEY al momento de
        firmar): se firma ahora con el XML ya generado.
      - Se firmo pero el envio al SRI fallo o quedo EN_PROCESO: se
        reenvia el MISMO xml_firmado tal cual (no se reconstruye).
    """
    emisor = comprobante.emisor

    if not comprobante.xml_firmado:
        if not emisor.certificado_p12:
            raise EmisionError(
                'Este emisor todavia no tiene un certificado .p12 cargado.',
                codigo='sin_certificado',
            )

        xml_sin_firmar = comprobante.xml_generado
        if not xml_sin_firmar:
            # Caso extremo: ni siquiera el XML sin firmar quedo guardado.
            # Se reconstruye desde los Detalle ya persistidos, SIN volver
            # a calcular nada (los montos ya estan fijados en BD).
            detalles = list(comprobante.detalles.all())
            resumen_por_tarifa = _resumen_desde_detalles(detalles)
            formas_pago_sri = [
                {'codigo': FORMAS_PAGO_SRI.get(p.get('forma_pago'), '01'), 'total': p['total']}
                for p in comprobante.payload_original.get('pagos', [])
            ]
            xml_sin_firmar = construir_xml_factura(
                emisor=emisor, comprobante=comprobante, detalles=detalles,
                resumen_por_tarifa=resumen_por_tarifa, formas_pago=formas_pago_sri,
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
    else:
        xml_firmado = comprobante.xml_firmado

    resultado_sri = procesar_comprobante_completo(
        xml_firmado=xml_firmado,
        clave_acceso=comprobante.clave_acceso,
        ambiente=emisor.ambiente,
    )
    _aplicar_resultado_sri(comprobante, resultado_sri)
    return _serializar_resultado(comprobante)


def _resumen_desde_detalles(detalles):
    """Reconstruye el resumen por tarifa de IVA a partir de DetalleComprobante ya guardados."""
    resumen = {}
    for d in detalles:
        cod = d.codigo_porcentaje_iva
        if cod not in resumen:
            resumen[cod] = {
                'codigo_porcentaje': cod,
                'base_imponible': Decimal('0.00'),
                'valor': Decimal('0.00'),
            }
        resumen[cod]['base_imponible'] += d.precio_total_sin_impuesto
        resumen[cod]['valor'] += d.valor_iva
    return list(resumen.values())


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
