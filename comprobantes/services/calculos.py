"""
Calculos de linea de venta para el SRI.

CONTRATO: el POS manda el precio unitario SIN IVA (precio base, antes
de impuestos) -- que es como la mayoria de sistemas de punto de venta
en Ecuador guardan sus precios internamente (incluido el POS de
Marlon: Product.sale_price = "Precio base sin IVA"). El SRI tambien
pide la base imponible en el XML, asi que no hace falta ninguna
conversion: se toma el precio tal cual llega.

Si en el futuro este microservicio se conecta a un POS que SI guarda
precios con IVA incluido, la conversion (precio_final / 1.15) se hace
del lado del adaptador de ESE POS antes de llamar a este endpoint --
no aqui. Este modulo asume siempre precio base.

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


def _redondear(valor, exp=DOS_DECIMALES):
    return Decimal(valor).quantize(exp, rounding=ROUND_HALF_UP)


def calcular_linea(precio_unitario_sin_impuesto, cantidad, tiene_iva, descuento=0):
    """
    precio_unitario_sin_impuesto: precio BASE (sin IVA), tal como lo
        guarda el POS (ej. Product.sale_price).
    cantidad: cantidad vendida.
    tiene_iva: bool -- True si el producto grava 15%, False si es 0%.
    descuento: descuento en dinero aplicado a la linea (no porcentaje).

    Devuelve un dict listo para guardar en DetalleComprobante y para
    alimentar el XML builder.
    """
    precio_unitario_sin_impuesto = _redondear(Decimal(str(precio_unitario_sin_impuesto)), Decimal('0.000001'))
    cantidad = Decimal(str(cantidad))
    descuento = Decimal(str(descuento))

    codigo_porcentaje = CODIGO_PORCENTAJE_IVA_15 if tiene_iva else CODIGO_PORCENTAJE_IVA_0
    tarifa = TARIFA_IVA if tiene_iva else Decimal('0.00')

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
