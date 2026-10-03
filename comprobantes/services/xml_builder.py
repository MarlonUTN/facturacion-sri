"""
Construye el XML de una factura (codDoc=01, version 1.1.0) segun la
ficha tecnica del SRI, a partir de un Emisor y los datos ya calculados
de un Comprobante + sus DetalleComprobante.
"""

from lxml import etree
from django.utils import timezone


def _sub(parent, tag, texto=''):
    el = etree.SubElement(parent, tag)
    el.text = str(texto)
    return el


def construir_xml_factura(emisor, comprobante, detalles, resumen_por_tarifa, formas_pago):
    """
    emisor: instancia de Emisor
    comprobante: instancia de Comprobante (ya con clave_acceso, secuencial,
                 totales, comprador asignados)
    detalles: lista de DetalleComprobante (o dicts equivalentes)
    resumen_por_tarifa: lista de dicts {codigo_porcentaje, base_imponible, valor}
    formas_pago: lista de dicts {codigo, total} p.ej.
                 [{'codigo': '01', 'total': 25.50}]  # 01 = efectivo

    Devuelve el XML como string (utf-8, sin firmar todavia).
    """
    factura = etree.Element('factura', id='comprobante', version='1.1.0')

    # ---- infoTributaria ----
    info_trib = etree.SubElement(factura, 'infoTributaria')
    _sub(info_trib, 'ambiente', emisor.ambiente)
    _sub(info_trib, 'tipoEmision', '1')
    _sub(info_trib, 'razonSocial', emisor.razon_social)
    if emisor.nombre_comercial:
        _sub(info_trib, 'nombreComercial', emisor.nombre_comercial)
    _sub(info_trib, 'ruc', emisor.ruc)
    _sub(info_trib, 'claveAcceso', comprobante.clave_acceso)
    _sub(info_trib, 'codDoc', '01')
    _sub(info_trib, 'estab', emisor.codigo_establecimiento)
    _sub(info_trib, 'ptoEmi', emisor.codigo_punto_emision)
    _sub(info_trib, 'secuencial', str(comprobante.secuencial).zfill(9))
    _sub(info_trib, 'dirMatriz', emisor.direccion_matriz)
    if emisor.contribuyente_especial:
        _sub(info_trib, 'contribuyenteEspecial', emisor.contribuyente_especial)

    # ---- infoFactura ----
    info_factura = etree.SubElement(factura, 'infoFactura')
    _sub(info_factura, 'fechaEmision', timezone.localtime(comprobante.creado_en).strftime('%d/%m/%Y'))
    _sub(info_factura, 'dirEstablecimiento', emisor.direccion_establecimiento)
    if emisor.contribuyente_especial:
        _sub(info_factura, 'contribuyenteEspecial', emisor.contribuyente_especial)
    _sub(info_factura, 'obligadoContabilidad', 'SI' if emisor.obligado_contabilidad else 'NO')
    _sub(info_factura, 'tipoIdentificacionComprador', comprobante.tipo_identificacion_comprador)
    _sub(info_factura, 'razonSocialComprador', comprobante.razon_social_comprador)
    _sub(info_factura, 'identificacionComprador', comprobante.identificacion_comprador)
    _sub(info_factura, 'totalSinImpuestos', f'{comprobante.total_sin_impuestos:.2f}')
    _sub(info_factura, 'totalDescuento', '0.00')

    total_con_impuestos = etree.SubElement(info_factura, 'totalConImpuestos')
    for r in resumen_por_tarifa:
        ti = etree.SubElement(total_con_impuestos, 'totalImpuesto')
        _sub(ti, 'codigo', '2')  # 2 = IVA (catalogo de impuestos del SRI)
        _sub(ti, 'codigoPorcentaje', r['codigo_porcentaje'])
        _sub(ti, 'baseImponible', f"{r['base_imponible']:.2f}")
        _sub(ti, 'valor', f"{r['valor']:.2f}")

    _sub(info_factura, 'propina', '0.00')
    _sub(info_factura, 'importeTotal', f'{comprobante.importe_total:.2f}')
    _sub(info_factura, 'moneda', 'DOLAR')

    pagos = etree.SubElement(info_factura, 'pagos')
    for fp in formas_pago:
        pago = etree.SubElement(pagos, 'pago')
        _sub(pago, 'formaPago', fp['codigo'])
        _sub(pago, 'total', f"{float(fp['total']):.2f}")

    # ---- detalles ----
    detalles_el = etree.SubElement(factura, 'detalles')
    for d in detalles:
        detalle = etree.SubElement(detalles_el, 'detalle')
        _sub(detalle, 'codigoPrincipal', d.codigo_principal)
        _sub(detalle, 'descripcion', d.descripcion)
        _sub(detalle, 'cantidad', f'{d.cantidad:.6f}')
        _sub(detalle, 'precioUnitario', f'{d.precio_unitario_sin_impuesto:.6f}')
        _sub(detalle, 'descuento', f'{d.descuento:.2f}')
        _sub(detalle, 'precioTotalSinImpuesto', f'{d.precio_total_sin_impuesto:.2f}')

        impuestos = etree.SubElement(detalle, 'impuestos')
        impuesto = etree.SubElement(impuestos, 'impuesto')
        _sub(impuesto, 'codigo', '2')
        _sub(impuesto, 'codigoPorcentaje', d.codigo_porcentaje_iva)
        _sub(impuesto, 'tarifa', f'{d.tarifa_iva:.2f}')
        _sub(impuesto, 'baseImponible', f'{d.precio_total_sin_impuesto:.2f}')
        _sub(impuesto, 'valor', f'{d.valor_iva:.2f}')

    # ---- infoAdicional ----
    from django.conf import settings

    campos_adicionales = []
    if comprobante.referencia_externa:
        campos_adicionales.append(('ReferenciaPOS', comprobante.referencia_externa))

    # RUC del desarrollador/distribuidor del sistema (Resolucion
    # NAC-DGERCGC26-00000027): obligatorio en TODO comprobante,
    # independientemente del emisor.
    if settings.DISTRIBUIDOR_RUC:
        campos_adicionales.append(('RUC Proveedor Sistema', settings.DISTRIBUIDOR_RUC))

    # Leyenda RIMPE Emprendedor (solo si este emisor esta marcado como tal).
    if emisor.es_rimpe_emprendedor:
        campos_adicionales.append(('Regimen', 'CONTRIBUYENTE RÉGIMEN RIMPE'))

    if campos_adicionales:
        info_adicional = etree.SubElement(factura, 'infoAdicional')
        for nombre, valor in campos_adicionales:
            campo = etree.SubElement(info_adicional, 'campoAdicional', nombre=nombre)
            campo.text = valor

    return etree.tostring(
        factura, xml_declaration=True, encoding='UTF-8', standalone=True
    ).decode('utf-8')
