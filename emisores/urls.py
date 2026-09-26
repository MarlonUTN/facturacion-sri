from django.urls import path
from .views import RegistroEmisorView, MiPerfilEmisorView

urlpatterns = [
    path('registro/', RegistroEmisorView.as_view(), name='emisor-registro'),
    path('mi-perfil/', MiPerfilEmisorView.as_view(), name='emisor-mi-perfil'),
]
