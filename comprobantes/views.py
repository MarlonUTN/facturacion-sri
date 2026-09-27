from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from .models import Comprobante
from .serializers import EmitirComprobanteSerializer
from .services.emision import emitir_comprobante, EmisionError
from .services.ride_generator import generar_ride


class EmitirComprobanteView(APIView):
    """
    POST /api/comprobantes/emitir/

    El POS manda los datos de una venta (items, cliente opcional,
    pagos), y este endpoint hace TODO el trabajo: calcula IVA, arma
    el XML, lo firma, lo manda al SRI, y devuelve el resultado.

    Requiere autenticacion por ApiKey (el emisor identificado por su
    api_key es el que emite el comprobante).
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

        # Si el SRI todavia no dio un estado final concluyente, igual
        # devolvemos 200 (la peticion se proceso bien), pero el estado
        # en el body indica que hay que consultar despues.
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
