from django.contrib import admin
from .models import Emisor


@admin.register(Emisor)
class EmisorAdmin(admin.ModelAdmin):
    list_display = ('razon_social', 'ruc', 'ambiente', 'activo', 'secuencial_factura')
    list_filter = ('ambiente', 'activo')
    search_fields = ('ruc', 'razon_social')
    readonly_fields = ('api_key', 'creado_en', 'actualizado_en')
