from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from .models import Comprobante
from .serializers import EmitirComprobanteSerializer
from .services.emision import emitir_comprobante, EmisionError
from .services.ride_generator import generar_ride
import logging
import traceback

logger = logging.getLogger(__name__)

class EmitirComprobanteView(APIView):
    """
    POST /api/comprobantes/emitir/
    ...
    """

    def post(self, request):
        serializer = EmitirComprobanteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        emisor = request.user

        try:
            resultado = emitir_comprobante(emisor, serializer.validated_data)
        except EmisionError as exc:
            return Response(
                {'detail': exc.mensaje, 'codigo': exc.codigo},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Error no manejado en /emitir/: %s", tb)
            return Response(
                {
                    'detail': str(exc),
                    'tipo': type(exc).__name__,
                    'traceback': tb,
                },
                status=500,
            )

        return Response(resultado, status=status.HTTP_201_CREATED)


class RideComprobanteView(APIView):
    """
    GET /api/comprobantes/<id>/ride/

    Devuelve el PDF (RIDE) de un comprobante que pertenece al emisor
    autenticado. Solo tiene sentido pedirlo una vez que esta
    AUTORIZADO (antes de eso no hay numero de autorizacion valido).
    """

    def get(self, request, comprobante_id):
        comprobante = get_object_or_404(
            Comprobante, id=comprobante_id, emisor=request.user
        )

        if comprobante.estado != Comprobante.ESTADO_AUTORIZADO:
            return Response(
                {'detail': f'El comprobante todavia no esta autorizado (estado actual: {comprobante.estado}).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pdf_bytes = generar_ride(
            emisor=comprobante.emisor,
            comprobante=comprobante,
            detalles=comprobante.detalles.all(),
        )

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="factura_{comprobante.secuencial}.pdf"'
        return response
