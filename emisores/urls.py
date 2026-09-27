from django.urls import path
from .views import RegistroEmisorView, MiPerfilEmisorView, SubirCertificadoView

urlpatterns = [
    path('registro/', RegistroEmisorView.as_view(), name='emisor-registro'),
    path('mi-perfil/', MiPerfilEmisorView.as_view(), name='emisor-mi-perfil'),
    path('certificado/', SubirCertificadoView.as_view(), name='emisor-certificado'),
]
