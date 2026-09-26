from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Emisor
from .serializers import EmisorRegistroSerializer, EmisorPerfilSerializer


class RegistroEmisorView(generics.CreateAPIView):
    """
    POST /api/emisores/registro/

    Endpoint publico (sin API key aun, porque el emisor no la tiene todavia)
    para que una instalacion nueva del POS registre los datos de su negocio
    por primera vez. Devuelve la api_key que el POS debe guardar localmente
    y usar en todas las peticiones futuras (header Authorization: ApiKey <key>).

    En produccion, considera protegerlo con algo simple (ej. un codigo de
    activacion de un solo uso) para que no cualquiera registre RUCs.
    """
    queryset = Emisor.objects.all()
    serializer_class = EmisorRegistroSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # este endpoint no requiere ApiKey


class MiPerfilEmisorView(APIView):
    """
    GET  /api/emisores/mi-perfil/   -> datos del emisor autenticado
    """

    def get(self, request):
        # request.user es el Emisor gracias a EmisorAPIKeyAuthentication
        serializer = EmisorPerfilSerializer(request.user)
        return Response(serializer.data)
