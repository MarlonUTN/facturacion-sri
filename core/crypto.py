"""
Cifrado simetrico (Fernet) para datos sensibles que hay que poder
recuperar en texto plano despues (el .p12 y su contrasena).

Fernet no es para contrasenas de usuarios (para eso se usa hash, no
cifrado reversible) -- aqui SI necesitamos poder descifrar, porque
hace falta el .p12 original para firmar cada factura.

La clave maestra (FERNET_MASTER_KEY) debe vivir SOLO como variable de
entorno, nunca en el codigo ni en el repositorio. Generala una vez con:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

y guardala en tu .env local y en las variables de entorno de Render.
"""

from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet():
    key = settings.FERNET_MASTER_KEY
    if not key:
        raise RuntimeError(
            'FERNET_MASTER_KEY no esta configurada. Define esa variable '
            'de entorno antes de cifrar o descifrar certificados.'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def cifrar_bytes(data: bytes) -> bytes:
    return _get_fernet().encrypt(data)


def descifrar_bytes(token: bytes) -> bytes:
    # bytes(token): Postgres/Supabase a veces entrega un memoryview en
    # BinaryField en vez de bytes puro, y Fernet exige bytes.
    return _get_fernet().decrypt(bytes(token))


def cifrar_texto(texto: str) -> str:
    return _get_fernet().encrypt(texto.encode()).decode()


def descifrar_texto(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
