from rest_framework import serializers
from .models import Emisor


class EmisorRegistroSerializer(serializers.ModelSerializer):
    """
    Usado en el endpoint de registro inicial: el POS envía los datos
    de la empresa (RUC, razón social, dirección, ambiente). El .p12
    se sube en un endpoint aparte (multipart), no aquí.
    """

    class Meta:
        model = Emisor
        fields = [
            'id',
            'ruc',
            'razon_social',
            'nombre_comercial',
            'direccion_matriz',
            'direccion_establecimiento',
            'codigo_establecimiento',
            'codigo_punto_emision',
            'obligado_contabilidad',
            'contribuyente_especial',
            'ambiente',
            'api_key',
        ]
        read_only_fields = ['id', 'api_key']

    def validate_ruc(self, value):
        if len(value) != 13 or not value.isdigit():
            raise serializers.ValidationError('El RUC debe tener 13 dígitos numéricos.')
        return value


class EmisorPerfilSerializer(serializers.ModelSerializer):
    """Vista de solo lectura de los datos del emisor autenticado (sin exponer api_key de nuevo)."""

    class Meta:
        model = Emisor
        fields = [
            'id', 'ruc', 'razon_social', 'nombre_comercial',
            'direccion_matriz', 'direccion_establecimiento',
            'codigo_establecimiento', 'codigo_punto_emision',
            'ambiente', 'secuencial_factura', 'activo',
        ]
