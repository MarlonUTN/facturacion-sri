import secrets
from django.db import models


class Emisor(models.Model):
    AMBIENTE_PRUEBAS = '1'
    AMBIENTE_PRODUCCION = '2'
    AMBIENTE_CHOICES = [(AMBIENTE_PRUEBAS, 'Pruebas'), (AMBIENTE_PRODUCCION, 'Producción')]

    ruc = models.CharField(max_length=13, unique=True)
    razon_social = models.CharField(max_length=300)
    nombre_comercial = models.CharField(max_length=300, blank=True)
    direccion_matriz = models.CharField(max_length=300)
    direccion_establecimiento = models.CharField(max_length=300)
    codigo_establecimiento = models.CharField(max_length=3, default='001')
    codigo_punto_emision = models.CharField(max_length=3, default='001')
    obligado_contabilidad = models.BooleanField(default=False)
    contribuyente_especial = models.CharField(max_length=20, blank=True)
    es_rimpe_emprendedor = models.BooleanField(default=False)
    ambiente = models.CharField(max_length=1, choices=AMBIENTE_CHOICES, default=AMBIENTE_PRUEBAS)
    certificado_p12 = models.BinaryField(null=True, blank=True)
    certificado_password_cifrada = models.CharField(max_length=500, blank=True)
    secuencial_factura = models.PositiveIntegerField(default=1)
    api_key = models.CharField(max_length=64, unique=True, editable=False)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.api_key:
            self.api_key = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.razon_social} ({self.ruc})'

    def siguiente_secuencial_factura(self):
        from django.db.models import F
        Emisor.objects.filter(pk=self.pk).update(secuencial_factura=F('secuencial_factura') + 1)
        self.refresh_from_db(fields=['secuencial_factura'])
        return self.secuencial_factura

    # DRF revisa request.user.is_authenticated con IsAuthenticated como
    # permission_class. Como usamos Emisor (no User de Django) como
    # request.user en EmisorAPIKeyAuthentication, necesita estos 3
    # atributos para que la autenticacion funcione correctamente.
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_active(self):
        return self.activo
