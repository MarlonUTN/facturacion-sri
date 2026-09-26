"""
Generacion de la clave de acceso (49 digitos) segun la ficha tecnica
del SRI para comprobantes electronicos.

Estructura (cada bloque en digitos):
    fecha emision (ddmmyyyy)        8
    tipo comprobante (01=factura)   2
    RUC del emisor                  13
    ambiente (1=pruebas, 2=prod)    1
    serie: establecimiento+ptoEmi   6
    numero secuencial               9
    codigo numerico (aleatorio)     8
    tipo de emision (1=normal)      1
    digito verificador (mod 11)     1
    -----------------------------------
    total                           49
"""

import random
from datetime import date


def _modulo11(clave_48_digitos):
    """Calcula el digito verificador segun el algoritmo modulo 11 del SRI."""
    factores = [2, 3, 4, 5, 6, 7]
    suma = 0
    for i, digito in enumerate(reversed(clave_48_digitos)):
        factor = factores[i % len(factores)]
        suma += int(digito) * factor

    residuo = suma % 11
    verificador = 11 - residuo

    if verificador == 11:
        return 0
    if verificador == 10:
        return 1
    return verificador


def generar_clave_acceso(
    fecha_emision: date,
    ruc: str,
    ambiente: str,
    codigo_establecimiento: str,
    codigo_punto_emision: str,
    secuencial: str,
    tipo_comprobante: str = '01',
    tipo_emision: str = '1',
):
    fecha_str = fecha_emision.strftime('%d%m%Y')
    serie = f'{codigo_establecimiento}{codigo_punto_emision}'
    secuencial_str = str(secuencial).zfill(9)
    codigo_numerico = str(random.randint(0, 99999999)).zfill(8)

    clave_sin_verificador = (
        f'{fecha_str}'
        f'{tipo_comprobante}'
        f'{ruc}'
        f'{ambiente}'
        f'{serie}'
        f'{secuencial_str}'
        f'{codigo_numerico}'
        f'{tipo_emision}'
    )

    if len(clave_sin_verificador) != 48:
        raise ValueError(
            f'La clave de acceso sin verificador debe tener 48 digitos, '
            f'tiene {len(clave_sin_verificador)}. Revisa el RUC (debe ser 13 digitos).'
        )

    digito_verificador = _modulo11(clave_sin_verificador)
    return f'{clave_sin_verificador}{digito_verificador}'
