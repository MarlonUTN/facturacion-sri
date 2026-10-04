

import base64
import time
import logging
from dataclasses import dataclass

import zeep
from zeep.transports import Transport
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

logger = logging.getLogger(__name__)

URLS = {
    '1': {  # Pruebas
        'recepcion': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
        'autorizacion': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
    },
    '2': {  # Produccion
        'recepcion': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
        'autorizacion': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
    },
}


@dataclass
class ResultadoRecepcion:
    estado: str  # 'RECIBIDA' o 'DEVUELTA'
    mensajes: list


@dataclass
class ResultadoAutorizacion:
    estado: str  # 'AUTORIZADO', 'NO AUTORIZADO', 'EN PROCESO', 'PROCESAMIENTO'
    numero_autorizacion: str = ''
    fecha_autorizacion: str = ''
    mensajes: list = None
    comprobante_autorizado: str = ''  # el XML devuelto por el SRI, ya con el sello de autorizacion
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(RequestsConnectionError),
    reraise=True,
)

def _get_client(wsdl_url, timeout=10):
  
    session = requests.Session()
    transport = Transport(session=session, timeout=timeout, operation_timeout=30)
    return zeep.Client(wsdl=wsdl_url, transport=transport)


def enviar_recepcion(xml_firmado: str, ambiente: str = '1') -> ResultadoRecepcion:
    """
    Envia el XML ya firmado (XAdES-BES) al webservice de Recepcion.
    """
    wsdl_url = URLS[ambiente]['recepcion']
    xml_bytes = xml_firmado.encode('utf-8')

    try:
        client = _get_client(wsdl_url)
        respuesta = client.service.validarComprobante(xml_bytes)
    except Exception as exc:
        logger.exception('Error de conexion al webservice de Recepcion del SRI')
        return ResultadoRecepcion(estado='ERROR_CONEXION', mensajes=[str(exc)])

    estado = respuesta.estado

    mensajes = []
    if hasattr(respuesta, 'comprobantes') and respuesta.comprobantes:
        for comprobante in respuesta.comprobantes.comprobante:
            if hasattr(comprobante, 'mensajes') and comprobante.mensajes:
                for m in comprobante.mensajes.mensaje:
                    mensajes.append({
                        'identificador': getattr(m, 'identificador', ''),
                        'mensaje': getattr(m, 'mensaje', ''),
                        'informacionAdicional': getattr(m, 'informacionAdicional', ''),
                        'tipo': getattr(m, 'tipo', ''),
                    })

    return ResultadoRecepcion(estado=estado, mensajes=mensajes)


def consultar_autorizacion(clave_acceso: str, ambiente: str = '1') -> ResultadoAutorizacion:
    """
    Consulta el estado de autorizacion de un comprobante ya enviado.
    Puede llamarse varias veces mientras el estado sea EN PROCESO.
    """
    wsdl_url = URLS[ambiente]['autorizacion']

    try:
        client = _get_client(wsdl_url)
        respuesta = client.service.autorizacionComprobante(clave_acceso)
    except Exception as exc:
        logger.exception('Error de conexion al webservice de Autorizacion del SRI')
        return ResultadoAutorizacion(estado='ERROR_CONEXION', mensajes=[str(exc)])

    if not respuesta.autorizaciones:
        return ResultadoAutorizacion(estado='NO_ENCONTRADO', mensajes=[])

    autorizacion = respuesta.autorizaciones.autorizacion[0]

    mensajes = []
    if hasattr(autorizacion, 'mensajes') and autorizacion.mensajes:
        for m in autorizacion.mensajes.mensaje:
            mensajes.append({
                'identificador': getattr(m, 'identificador', ''),
                'mensaje': getattr(m, 'mensaje', ''),
                'informacionAdicional': getattr(m, 'informacionAdicional', ''),
                'tipo': getattr(m, 'tipo', ''),
            })

    return ResultadoAutorizacion(
        estado=autorizacion.estado,
        numero_autorizacion=getattr(autorizacion, 'numeroAutorizacion', '') or '',
        fecha_autorizacion=str(getattr(autorizacion, 'fechaAutorizacion', '') or ''),
        mensajes=mensajes,
        comprobante_autorizado=getattr(autorizacion, 'comprobante', '') or '',
    )


def procesar_comprobante_completo(xml_firmado: str, clave_acceso: str, ambiente: str = '1',
                                    intentos_autorizacion: int = 5, espera_segundos: int = 3):
    """
    Orquesta el flujo completo: envia a Recepcion, y si es RECIBIDA,
    consulta Autorizacion reintentando unas cuantas veces (el SRI
    procesa de forma asincrona, normalmente responde en 1-5 segundos
    pero puede tardar mas en horas pico).

    Devuelve un dict con el resultado final, listo para guardar en el
    modelo Comprobante.
    """
    recepcion = enviar_recepcion(xml_firmado, ambiente)

    if recepcion.estado != 'RECIBIDA':
        return {
            'estado_final': 'DEVUELTA' if recepcion.estado == 'DEVUELTA' else 'ERROR',
            'mensajes': recepcion.mensajes,
        }

    for intento in range(intentos_autorizacion):
        time.sleep(espera_segundos)
        autorizacion = consultar_autorizacion(clave_acceso, ambiente)

        if autorizacion.estado == 'AUTORIZADO':
            return {
                'estado_final': 'AUTORIZADO',
                'numero_autorizacion': autorizacion.numero_autorizacion,
                'fecha_autorizacion': autorizacion.fecha_autorizacion,
                'comprobante_autorizado': autorizacion.comprobante_autorizado,
                'mensajes': autorizacion.mensajes,
            }
        elif autorizacion.estado == 'NO AUTORIZADO':
            return {
                'estado_final': 'NO_AUTORIZADO',
                'mensajes': autorizacion.mensajes,
            }
        # si sigue EN PROCESO, el loop reintenta

    return {
        'estado_final': 'EN_PROCESO',
        'mensajes': [{'mensaje': 'El SRI no respondio con un estado final tras varios intentos. Reintenta la consulta mas tarde.'}],
    }
