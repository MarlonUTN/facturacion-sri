# Microservicio de Facturación Electrónica SRI

Proyecto Django independiente para emitir comprobantes electrónicos ante el
SRI (Ecuador), pensado para ser consumido por múltiples instalaciones del
POS (multi-tenant vía modelo `Emisor`).

## Levantar en local

    python -m venv venv
    source venv/bin/activate  # En Windows: venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env      # y llena tus datos de Supabase
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver

## Endpoints implementados hasta ahora

- `POST /api/emisores/registro/` — registra un nuevo negocio (RUC, razón
  social, dirección, ambiente). Devuelve la `api_key` que el POS debe
  guardar y usar en el header `Authorization: ApiKey <key>`.
- `GET /api/emisores/mi-perfil/` — devuelve los datos del emisor autenticado.

## Siguiente paso

Endpoint para subir el archivo .p12 (cifrado), y el módulo de generación
y firma del XML de factura (`comprobantes/services/`).
