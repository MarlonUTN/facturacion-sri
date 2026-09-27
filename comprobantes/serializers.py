from rest_framework import serializers


class ClienteSerializer(serializers.Serializer):
    tipo_identificacion = serializers.CharField(max_length=2, default='07')
    identificacion = serializers.CharField(max_length=20, default='9999999999999')
    razon_social = serializers.CharField(max_length=300, default='CONSUMIDOR FINAL')
    direccion = serializers.CharField(max_length=300, required=False, allow_blank=True)


class ItemVentaSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=25)
    descripcion = serializers.CharField(max_length=300)
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=6)
    precio_unitario_sin_impuesto = serializers.DecimalField(max_digits=12, decimal_places=6)
    tiene_iva = serializers.BooleanField()
    descuento = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)


class PagoSerializer(serializers.Serializer):
    forma_pago = serializers.CharField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    plazo = serializers.IntegerField(required=False, allow_null=True)
    unidad_tiempo = serializers.ChoiceField(choices=['dias', 'meses'], required=False)


class EmitirComprobanteSerializer(serializers.Serializer):
    """
    Contrato generico que cualquier POS debe cumplir para pedirle a
    este microservicio que emita una factura. No conoce nada
    especifico de ningun sistema en particular -- por eso es
    reutilizable para vender el servicio a otros negocios despues.
    """
    referencia_externa = serializers.CharField(max_length=100, required=False, allow_blank=True)
    cliente = ClienteSerializer(required=False)
    items = ItemVentaSerializer(many=True)
    pagos = PagoSerializer(many=True)
