from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from cryptography.hazmat.primitives.serialization import pkcs12
from core.crypto import cifrar_bytes, cifrar_texto
from .models import Emisor
from .serializers import (
    EmisorRegistroSerializer,
    EmisorPerfilSerializer,
    SubirCertificadoSerializer,
)


class RegistroEmisorView(generics.CreateAPIView):
    """
    POST /api/emisores/registro/
    Endpoint publico para que una instalacion nueva del POS registre
    los datos de su negocio. Devuelve la api_key a guardar localmente.
    """
    queryset = Emisor.objects.all()
    serializer_class = EmisorRegistroSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class MiPerfilEmisorView(APIView):
    """GET /api/emisores/mi-perfil/ -> datos del emisor autenticado."""

    def get(self, request):
        serializer = EmisorPerfilSerializer(request.user)
        return Response(serializer.data)


class SubirCertificadoView(APIView):
    """
    POST /api/emisores/certificado/   (multipart/form-data)
    Campos: archivo_p12, password

    Valida que el .p12 realmente se pueda abrir con esa contrasena
    ANTES de guardarlo (para no descubrir el error recien al firmar
    la primera factura), lo cifra, y lo guarda en el Emisor
    autenticado (identificado por su api_key).
    """
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = SubirCertificadoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        archivo = serializer.validated_data['archivo_p12']
        password = serializer.validated_data['password']
        contenido = archivo.read()

        try:
            pkcs12.load_key_and_certificates(contenido, password.encode())
        except Exception:
            return Response(
                {'detail': 'No se pudo abrir el certificado con la contrasena dada. Verifica el archivo y la contrasena.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        emisor = request.user
        emisor.certificado_p12 = cifrar_bytes(contenido)
        emisor.certificado_password_cifrada = cifrar_texto(password)
        emisor.save(update_fields=['certificado_p12', 'certificado_password_cifrada'])

        return Response({'detail': 'Certificado cargado y validado correctamente.'})
