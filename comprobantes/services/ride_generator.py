"""
Genera el RIDE (Representacion Impresa del Documento Electronico) en
PDF, a partir de un Comprobante ya AUTORIZADO. Esto es lo que se
imprime o se envia al cliente -- el XML es para el SRI, el RIDE es
para el humano.

Estructura basada en lo que exige la ficha tecnica del SRI para el
RIDE de factura: datos del emisor, numero de autorizacion, clave de
acceso (en texto Y en codigo de barras), datos del comprador, detalle
de items, totales, e informacion de pago.
"""

import io
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage,
)
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF


def _generar_barcode(clave_acceso: str, alto_mm=15):
    """Code128 es un Flowable de reportlab -- se usa directo en el story."""
    return code128.Code128(clave_acceso, barHeight=alto_mm * mm, barWidth=0.28)


def generar_ride(emisor, comprobante, detalles) -> bytes:
    """
    Devuelve los bytes del PDF del RIDE. detalles: iterable de
    DetalleComprobante (o similar) del comprobante.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=12 * mm, bottomMargin=12 * mm,
        leftMargin=12 * mm, rightMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    estilo_normal = styles['Normal']
    estilo_normal.fontSize = 8
    estilo_negrita = ParagraphStyle('negrita', parent=estilo_normal, fontName='Helvetica-Bold')
    estilo_titulo = ParagraphStyle('titulo', parent=estilo_normal, fontName='Helvetica-Bold', fontSize=12)
    estilo_pequeno = ParagraphStyle('pequeno', parent=estilo_normal, fontSize=7)

    elementos = []

    # ---- Encabezado: datos del emisor (izq) + caja de factura (der) ----
    ambiente_texto = 'PRUEBAS' if emisor.ambiente == '1' else 'PRODUCCIÓN'

    info_emisor = [
        Paragraph(emisor.razon_social, estilo_titulo),
        Paragraph(emisor.nombre_comercial or '', estilo_normal),
        Paragraph(f'Dirección Matriz: {emisor.direccion_matriz}', estilo_normal),
        Paragraph(f'Dirección Sucursal: {emisor.direccion_establecimiento}', estilo_normal),
        Paragraph(
            f"Obligado a llevar contabilidad: {'SI' if emisor.obligado_contabilidad else 'NO'}",
            estilo_normal,
        ),
    ]

    if comprobante.fecha_autorizacion:
        fecha_autorizacion_texto = timezone.localtime(comprobante.fecha_autorizacion).strftime('%d/%m/%Y %H:%M:%S')
    else:
        fecha_autorizacion_texto = 'No disponible'

    numero_factura = f'{emisor.codigo_establecimiento}-{emisor.codigo_punto_emision}-{comprobante.secuencial}'
    info_factura = [
        Paragraph(f'R.U.C.: {emisor.ruc}', estilo_negrita),
        Paragraph('FACTURA', estilo_titulo),
        Paragraph(f'No. {numero_factura}', estilo_negrita),
        Paragraph(f'NÚMERO DE AUTORIZACIÓN:', estilo_pequeno),
        Paragraph(comprobante.numero_autorizacion or '(pendiente)', estilo_pequeno),
        Paragraph(f'FECHA Y HORA DE AUTORIZACIÓN:', estilo_pequeno),
        Paragraph(fecha_autorizacion_texto, estilo_pequeno),
        Paragraph(f'AMBIENTE: {ambiente_texto}', estilo_pequeno),
        Paragraph('EMISIÓN: NORMAL', estilo_pequeno),
    ]

    tabla_encabezado = Table(
        [[info_emisor, info_factura]],
        colWidths=[110 * mm, 70 * mm],
    )
    tabla_encabezado.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
        ('BOX', (1, 0), (1, 0), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elementos.append(tabla_encabezado)
    elementos.append(Spacer(1, 4 * mm))

    # ---- Codigo de barras de la clave de acceso ----
    elementos.append(_generar_barcode(comprobante.clave_acceso))
    elementos.append(Paragraph(comprobante.clave_acceso, estilo_pequeno))
    elementos.append(Spacer(1, 4 * mm))

    # ---- Datos del comprador ----
    fecha_emision = timezone.localtime(comprobante.creado_en).strftime('%d/%m/%Y')
    datos_comprador = [
        [Paragraph(f'<b>Razón Social / Nombres y Apellidos:</b> {comprobante.razon_social_comprador}', estilo_normal)],
        [Paragraph(
            f'<b>Identificación:</b> {comprobante.identificacion_comprador}    '
            f'<b>Fecha Emisión:</b> {fecha_emision}',
            estilo_normal,
        )],
    ]
    if comprobante.direccion_comprador:
        datos_comprador.append([Paragraph(f'<b>Dirección:</b> {comprobante.direccion_comprador}', estilo_normal)])

    tabla_comprador = Table(datos_comprador, colWidths=[180 * mm])
    tabla_comprador.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabla_comprador)
    elementos.append(Spacer(1, 4 * mm))

    # ---- Detalle de items ----
    encabezados = ['Cód.', 'Descripción', 'Cant.', 'P. Unit.', 'Desc.', 'IVA', 'P. Total']
    filas = [encabezados]
    for d in detalles:
        filas.append([
            d.codigo_principal,
            d.descripcion,
            f'{d.cantidad:.2f}',
            f'{d.precio_unitario_sin_impuesto:.4f}',
            f'{d.descuento:.2f}',
            f'{d.tarifa_iva:.0f}%',
            f'{d.precio_total_sin_impuesto:.2f}',
        ])

    tabla_detalle = Table(
        filas,
        colWidths=[20 * mm, 65 * mm, 15 * mm, 22 * mm, 15 * mm, 13 * mm, 30 * mm],
        repeatRows=1,
    )
    tabla_detalle.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabla_detalle)
    elementos.append(Spacer(1, 4 * mm))

    # ---- Totales + forma de pago, lado a lado ----
    pagos = comprobante.payload_original.get('pagos', [])
    filas_pago = [[Paragraph('<b>Forma de Pago</b>', estilo_normal), Paragraph('<b>Valor</b>', estilo_normal)]]
    for p in pagos:
        filas_pago.append([p.get('forma_pago', ''), f"{float(p.get('total', 0)):.2f}"])
    tabla_pagos = Table(filas_pago, colWidths=[45 * mm, 30 * mm])
    tabla_pagos.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))

    filas_totales = [
        ['Subtotal sin impuestos:', f'{comprobante.total_sin_impuestos:.2f}'],
        ['IVA:', f'{comprobante.total_iva:.2f}'],
        ['VALOR TOTAL:', f'{comprobante.importe_total:.2f}'],
    ]
    tabla_totales = Table(filas_totales, colWidths=[45 * mm, 30 * mm])
    tabla_totales.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 2), (-1, 2), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#ecf0f1')),
    ]))

    tabla_pie = Table([[tabla_pagos, tabla_totales]], colWidths=[90 * mm, 90 * mm])
    tabla_pie.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elementos.append(tabla_pie)

    if emisor.es_rimpe_emprendedor:
        elementos.append(Spacer(1, 3 * mm))
        elementos.append(Paragraph('CONTRIBUYENTE RÉGIMEN RIMPE', estilo_negrita))

    doc.build(elementos)
    return buffer.getvalue()
