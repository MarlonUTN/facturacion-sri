from rest_framework import authentication, exceptions
from emisores.models import Emisor


class EmisorAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Autentica peticiones usando el header:
        Authorization: ApiKey <api_key_del_emisor>

    Si es válida, adjunta el Emisor correspondiente en request.emisor
    para que las vistas sepan de qué negocio/tenant es la petición.
    """

    keyword = 'ApiKey'

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request).split()

        if not auth_header or auth_header[0].decode() != self.keyword:
            return None  # deja que otro esquema de auth lo intente, o falle

        if len(auth_header) != 2:
            raise exceptions.AuthenticationFailed(
                'Header de autorización mal formado. Usa: Authorization: ApiKey <tu_api_key>'
            )

        api_key = auth_header[1].decode()

        try:
            emisor = Emisor.objects.get(api_key=api_key, activo=True)
        except Emisor.DoesNotExist:
            raise exceptions.AuthenticationFailed('API key inválida o emisor inactivo.')

        # DRF espera (user, auth). No usamos User de Django aquí, así que
        # devolvemos el propio Emisor como "user" para simplicidad, y las
        # vistas lo consumen desde request.user (o request.emisor, ver middleware si prefieres).
        return (emisor, None)
