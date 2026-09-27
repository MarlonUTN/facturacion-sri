from django.db import models
from django.core.serializers.json import DjangoJSONEncoder
from emisores.models import Emisor


class Comprobante(models.Model):
    """
    Un comprobante electronico (por ahora solo factura, codDoc='01').
    Cada venta del POS genera uno de estos.
    """

    ESTADO_CREADO = 'CREADO'
    ESTADO_FIRMADO = 'FIRMADO'
    ESTADO_ENVIADO = 'ENVIADO'
    ESTADO_RECIBIDA = 'RECIBIDA'
    ESTADO_AUTORIZADO = 'AUTORIZADO'
    ESTADO_NO_AUTORIZADO = 'NO_AUTORIZADO'
    ESTADO_ERROR = 'ERROR'
    ESTADO_CHOICES = [
        (ESTADO_CREADO, 'Creado'),
        (ESTADO_FIRMADO, 'Firmado'),
        (ESTADO_ENVIADO, 'Enviado al SRI'),
        (ESTADO_RECIBIDA, 'Recibida por el SRI'),
        (ESTADO_AUTORIZADO, 'Autorizado'),
        (ESTADO_NO_AUTORIZADO, 'No autorizado'),
        (ESTADO_ERROR, 'Error'),
    ]

    emisor = models.ForeignKey(Emisor, on_delete=models.PROTECT, related_name='comprobantes')

    secuencial = models.CharField(max_length=9)
    clave_acceso = models.CharField(max_length=49, unique=True)

    referencia_externa = models.CharField(max_length=100, blank=True, db_index=True)

    tipo_identificacion_comprador = models.CharField(max_length=2, default='07')
    identificacion_comprador = models.CharField(max_length=20, default='9999999999999')
    razon_social_comprador = models.CharField(max_length=300, default='CONSUMIDOR FINAL')
    direccion_comprador = models.CharField(max_length=300, blank=True)

    total_sin_impuestos = models.DecimalField(max_digits=12, decimal_places=2)
    total_iva = models.DecimalField(max_digits=12, decimal_places=2)
    importe_total = models.DecimalField(max_digits=12, decimal_places=2)

    payload_original = models.JSONField(encoder=DjangoJSONEncoder)

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_CREADO)
    xml_generado = models.TextField(blank=True)
    xml_firmado = models.TextField(blank=True)
    numero_autorizacion = models.CharField(max_length=49, blank=True)
    fecha_autorizacion = models.DateTimeField(null=True, blank=True)
    mensaje_error = models.TextField(blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creado_en']
        constraints = [
            models.UniqueConstraint(
                fields=['emisor', 'referencia_externa'],
                name='unico_por_emisor_y_referencia_externa',
                condition=models.Q(referencia_externa__gt=''),
            )
        ]

    def __str__(self):
        return f'Factura {self.secuencial} - {self.emisor.ruc} ({self.estado})'


class DetalleComprobante(models.Model):
    comprobante = models.ForeignKey(Comprobante, on_delete=models.CASCADE, related_name='detalles')
    codigo_principal = models.CharField(max_length=25)
    descripcion = models.CharField(max_length=300)
    cantidad = models.DecimalField(max_digits=12, decimal_places=6)
    precio_unitario_sin_impuesto = models.DecimalField(max_digits=12, decimal_places=6)
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    precio_total_sin_impuesto = models.DecimalField(max_digits=12, decimal_places=2)
    codigo_porcentaje_iva = models.CharField(max_length=1)
    tarifa_iva = models.DecimalField(max_digits=5, decimal_places=2)
    valor_iva = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f'{self.descripcion} x{self.cantidad}'
