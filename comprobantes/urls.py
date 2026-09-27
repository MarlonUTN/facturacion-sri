from django.urls import path
from .views import EmitirComprobanteView, RideComprobanteView

urlpatterns = [
    path('emitir/', EmitirComprobanteView.as_view(), name='comprobante-emitir'),
    path('<int:comprobante_id>/ride/', RideComprobanteView.as_view(), name='comprobante-ride'),
]
