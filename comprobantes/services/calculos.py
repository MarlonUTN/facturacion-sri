"""
Calculos de linea de venta para el SRI.

Tu POS guarda el precio de cada producto YA CON el IVA incluido cuando
el producto tiene IVA (15%), y el precio "tal cual" cuando no tiene
(0%). El SRI, en cambio, pide en el XML el precio SIN impuesto y el
valor del IVA por separado. Por eso hay que "desarmar" el precio antes
de armar el detalle.

Tabla de codigoPorcentaje del SRI (ficha tecnica de comprobantes
electronicos, catalogo de IVA vigente desde la reforma de abril 2024):
    '0' -> tarifa 0%
    '4' -> tarifa 15%
Si en el futuro el SRI cambia las tarifas, este es el unico lugar que
hay que tocar.
"""

from decimal import Decimal, ROUND_HALF_UP

TARIFA_IVA = Decimal('15.00')
CODIGO_PORCENTAJE_IVA_15 = '4'
CODIGO_PORCENTAJE_IVA_0 = '0'

DOS_DECIMALES = Decimal('0.01')
SEIS_DECIMALES = Decimal('0.000001')


def _redondear(valor, exp=DOS_DECIMALES):
    return Decimal(valor).quantize(exp, rounding=ROUND_HALF_UP)


def calcular_linea(precio_unitario_final, cantidad, tiene_iva, descuento=0):
    """
    precio_unitario_final: precio tal como esta guardado en tu POS
        (ya incluye IVA si tiene_iva=True).
    cantidad: cantidad vendida.
    tiene_iva: bool, viene del campo que ya tienes en tu producto.
    descuento: descuento en dinero aplicado a la linea (no porcentaje).

    Devuelve un dict listo para guardar en DetalleComprobante y para
    alimentar el XML builder.
    """
    precio_unitario_final = Decimal(str(precio_unitario_final))
    cantidad = Decimal(str(cantidad))
    descuento = Decimal(str(descuento))

    if tiene_iva:
        # El precio final = base * 1.15  =>  base = final / 1.15
        precio_unitario_sin_impuesto = _redondear(
            precio_unitario_final / (Decimal('1') + TARIFA_IVA / Decimal('100')),
            SEIS_DECIMALES,
        )
        codigo_porcentaje = CODIGO_PORCENTAJE_IVA_15
        tarifa = TARIFA_IVA
    else:
        precio_unitario_sin_impuesto = precio_unitario_final
        codigo_porcentaje = CODIGO_PORCENTAJE_IVA_0
        tarifa = Decimal('0.00')

    precio_total_sin_impuesto = _redondear(
        precio_unitario_sin_impuesto * cantidad - descuento
    )
    valor_iva = _redondear(precio_total_sin_impuesto * tarifa / Decimal('100'))

    return {
        'precio_unitario_sin_impuesto': precio_unitario_sin_impuesto,
        'precio_total_sin_impuesto': precio_total_sin_impuesto,
        'codigo_porcentaje_iva': codigo_porcentaje,
        'tarifa_iva': tarifa,
        'valor_iva': valor_iva,
        'descuento': descuento,
    }


def calcular_totales(lineas_calculadas):
    """
    lineas_calculadas: lista de dicts devueltos por calcular_linea.
    Devuelve totales generales y el resumen agrupado por tarifa de IVA
    (el XML pide un totalImpuesto por cada codigoPorcentaje distinto).
    """
    total_sin_impuestos = sum(l['precio_total_sin_impuesto'] for l in lineas_calculadas)
    total_iva = sum(l['valor_iva'] for l in lineas_calculadas)
    importe_total = _redondear(total_sin_impuestos + total_iva)

    resumen_por_tarifa = {}
    for l in lineas_calculadas:
        cod = l['codigo_porcentaje_iva']
        if cod not in resumen_por_tarifa:
            resumen_por_tarifa[cod] = {
                'codigo_porcentaje': cod,
                'base_imponible': Decimal('0.00'),
                'valor': Decimal('0.00'),
            }
        resumen_por_tarifa[cod]['base_imponible'] += l['precio_total_sin_impuesto']
        resumen_por_tarifa[cod]['valor'] += l['valor_iva']

    return {
        'total_sin_impuestos': _redondear(total_sin_impuestos),
        'total_iva': _redondear(total_iva),
        'importe_total': importe_total,
        'resumen_por_tarifa': list(resumen_por_tarifa.values()),
    }
