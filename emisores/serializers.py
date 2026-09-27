from rest_framework import serializers
from .models import Emisor


class EmisorRegistroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Emisor
        fields = [
            'id', 'ruc', 'razon_social', 'nombre_comercial',
            'direccion_matriz', 'direccion_establecimiento',
            'codigo_establecimiento', 'codigo_punto_emision',
            'obligado_contabilidad', 'contribuyente_especial',
            'ambiente', 'api_key',
        ]
        read_only_fields = ['id', 'api_key']

    def validate_ruc(self, value):
        if len(value) != 13 or not value.isdigit():
            raise serializers.ValidationError('El RUC debe tener 13 digitos numericos.')
        return value


class EmisorPerfilSerializer(serializers.ModelSerializer):
    tiene_certificado = serializers.SerializerMethodField()

    class Meta:
        model = Emisor
        fields = [
            'id', 'ruc', 'razon_social', 'nombre_comercial',
            'direccion_matriz', 'direccion_establecimiento',
            'codigo_establecimiento', 'codigo_punto_emision',
            'ambiente', 'secuencial_factura', 'activo', 'tiene_certificado',
        ]

    def get_tiene_certificado(self, obj):
        return bool(obj.certificado_p12)


class SubirCertificadoSerializer(serializers.Serializer):
    """
    Recibe el archivo .p12 (multipart) y su contrasena. NO es un
    ModelSerializer porque la contrasena no se guarda tal cual: se
    cifra antes de persistir (ver la vista).
    """
    archivo_p12 = serializers.FileField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_archivo_p12(self, archivo):
        if not archivo.name.lower().endswith(('.p12', '.pfx')):
            raise serializers.ValidationError('El archivo debe ser .p12 o .pfx')
        if archivo.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('El archivo es demasiado grande.')
        return archivo
