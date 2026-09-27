import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'facturacion_sri.settings')
django.setup()

from datetime import date
from emisores.models import Emisor
from comprobantes.models import Comprobante, DetalleComprobante
from comprobantes.services.calculos import calcular_linea, calcular_totales
from comprobantes.services.clave_acceso import generar_clave_acceso
from comprobantes.services.xml_builder import construir_xml_factura
from core.crypto import descifrar_bytes, descifrar_texto
from comprobantes.services.firmador_xades import firmar_xades_bes
from comprobantes.services.sri_client import procesar_comprobante_completo

emisor = Emisor.objects.first()
print("Emisor:", emisor)

linea1 = calcular_linea(precio_unitario_final=0.75, cantidad=2, tiene_iva=True)
linea2 = calcular_linea(precio_unitario_final=0.15, cantidad=3, tiene_iva=False)
totales = calcular_totales([linea1, linea2])
print("Totales:", totales)

secuencial = emisor.siguiente_secuencial_factura()
clave = generar_clave_acceso(
    fecha_emision=date.today(), ruc=emisor.ruc, ambiente=emisor.ambiente,
    codigo_establecimiento=emisor.codigo_establecimiento,
    codigo_punto_emision=emisor.codigo_punto_emision, secuencial=secuencial,
)
print("Clave de acceso:", clave)

comprobante = Comprobante.objects.create(
    emisor=emisor, secuencial=str(secuencial).zfill(9), clave_acceso=clave,
    referencia_externa=f'VENTA-XADES-{secuencial}',
    total_sin_impuestos=totales['total_sin_impuestos'],
    total_iva=totales['total_iva'], importe_total=totales['importe_total'],
    payload_original={'lineas': 2},
)
DetalleComprobante.objects.create(
    comprobante=comprobante, codigo_principal='PROD01', descripcion='Producto con IVA',
    cantidad=2, precio_unitario_sin_impuesto=linea1['precio_unitario_sin_impuesto'],
    precio_total_sin_impuesto=linea1['precio_total_sin_impuesto'],
    codigo_porcentaje_iva=linea1['codigo_porcentaje_iva'], tarifa_iva=linea1['tarifa_iva'],
    valor_iva=linea1['valor_iva'],
)
DetalleComprobante.objects.create(
    comprobante=comprobante, codigo_principal='PROD02', descripcion='Producto sin IVA',
    cantidad=3, precio_unitario_sin_impuesto=linea2['precio_unitario_sin_impuesto'],
    precio_total_sin_impuesto=linea2['precio_total_sin_impuesto'],
    codigo_porcentaje_iva=linea2['codigo_porcentaje_iva'], tarifa_iva=linea2['tarifa_iva'],
    valor_iva=linea2['valor_iva'],
)
print("Comprobante creado:", comprobante.id)

xml_sin_firmar = construir_xml_factura(
    emisor=emisor, comprobante=comprobante, detalles=comprobante.detalles.all(),
    resumen_por_tarifa=totales['resumen_por_tarifa'],
    formas_pago=[{'codigo': '01', 'total': totales['importe_total']}],
)
print("XML sin firmar generado, longitud:", len(xml_sin_firmar))

p12 = descifrar_bytes(bytes(emisor.certificado_p12))
password = descifrar_texto(emisor.certificado_password_cifrada)

xml_firmado = firmar_xades_bes(xml_sin_firmar, p12, password)

with open('resultado_firmado.xml', 'w') as f:
    f.write(xml_firmado)

print("\n¡Listo! XML firmado guardado en resultado_firmado.xml")

print("\nEnviando al SRI (ambiente de pruebas)...")
resultado = procesar_comprobante_completo(
    xml_firmado=xml_firmado,
    clave_acceso=comprobante.clave_acceso,
    ambiente='1',  # 1 = pruebas
)
print("\nResultado final:", resultado)