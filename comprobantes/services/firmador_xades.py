"""
Firma XAdES-BES para comprobantes del SRI (Ecuador).

El SRI no acepta XML-DSig generico (lo que armamos con signxml en
firmador.py): exige el perfil XAdES-BES, que agrega:

  - Un elemento <ds:Object><xades:QualifyingProperties> con:
      * SigningTime (fecha/hora de la firma)
      * SigningCertificate (huella digital SHA1 del certificado + su
        emisor y numero de serie) -- esto es lo que le "ata"
        criptograficamente la firma a ESE certificado especifico.
  - Una segunda <ds:Reference> dentro de SignedInfo que apunta a las
    SignedProperties de arriba (con Type=".../SignedProperties"), para
    que tambien esten protegidas por la firma.

Todo el documento (SignedInfo, SignedProperties, y el documento en si)
se firma con RSA-SHA1 / SHA1, que es lo que el SRI exige por
compatibilidad con su validador.

Este modulo construye el XML de firma "a mano" con lxml, sin depender
de que signxml soporte XAdES (no lo soporta).
"""

import base64
import hashlib
import uuid
from datetime import datetime, timezone

from lxml import etree
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding

NS_DS = 'http://www.w3.org/2000/09/xmldsig#'
NS_XADES = 'http://uri.etsi.org/01903/v1.3.2#'
NS_C14N = 'http://www.w3.org/TR/2001/REC-xml-c14n-20010315'
NS_SHA1 = 'http://www.w3.org/2000/09/xmldsig#sha1'
NS_RSA_SHA1 = 'http://www.w3.org/2000/09/xmldsig#rsa-sha1'
NS_ENVELOPED = 'http://www.w3.org/2000/09/xmldsig#enveloped-signature'

NSMAP = {'ds': NS_DS, 'xades': NS_XADES}


def _c14n(elemento):
    """Canonicaliza un elemento lxml (C14N exclusivo, sin comentarios)."""
    return etree.tostring(elemento, method='c14n', exclusive=False, with_comments=False)


def _sha1_b64(datos_bytes):
    return base64.b64encode(hashlib.sha1(datos_bytes).digest()).decode()


def firmar_xades_bes(xml_string: str, p12_bytes: bytes, p12_password: str) -> str:
    clave_privada, certificado, _ = pkcs12.load_key_and_certificates(
        p12_bytes, p12_password.encode()
    )
    if clave_privada is None or certificado is None:
        raise ValueError('El .p12 no contiene clave privada o certificado validos.')

    doc = etree.fromstring(xml_string.encode('utf-8'))

    signature_id = 'Signature' + uuid.uuid4().hex[:8]
    signed_props_id = 'SignedProperties' + uuid.uuid4().hex[:8]
    cert_id = 'Certificate' + uuid.uuid4().hex[:8]
    keyinfo_id = 'KeyInfo' + uuid.uuid4().hex[:8]
    reference_id = 'Reference' + uuid.uuid4().hex[:8]

    # ---- 1. Digest del documento completo (antes de insertarle la firma) ----
    digest_documento = _sha1_b64(_c14n(doc))

    # ---- 2. Datos del certificado para SigningCertificate ----
    cert_der = certificado.public_bytes(Encoding.DER)
    digest_cert = base64.b64encode(hashlib.sha1(cert_der).digest()).decode()
    issuer_name = certificado.issuer.rfc4514_string()
    serial_number = str(certificado.serial_number)
    cert_pem_contenido = base64.b64encode(cert_der).decode()

    # ---- 3. Construir <xades:QualifyingProperties> (SignedProperties) ----
    fecha_firma = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'

    qualifying = etree.Element(f'{{{NS_XADES}}}QualifyingProperties', nsmap=NSMAP)
    qualifying.set('Target', f'#{signature_id}')
    signed_props = etree.SubElement(qualifying, f'{{{NS_XADES}}}SignedProperties')
    signed_props.set('Id', signed_props_id)

    ssp = etree.SubElement(signed_props, f'{{{NS_XADES}}}SignedSignatureProperties')
    etree.SubElement(ssp, f'{{{NS_XADES}}}SigningTime').text = fecha_firma

    signing_cert = etree.SubElement(ssp, f'{{{NS_XADES}}}SigningCertificate')
    cert_el = etree.SubElement(signing_cert, f'{{{NS_XADES}}}Cert')
    cert_digest = etree.SubElement(cert_el, f'{{{NS_XADES}}}CertDigest')
    dm = etree.SubElement(cert_digest, f'{{{NS_DS}}}DigestMethod')
    dm.set('Algorithm', NS_SHA1)
    etree.SubElement(cert_digest, f'{{{NS_DS}}}DigestValue').text = digest_cert
    issuer_serial = etree.SubElement(cert_el, f'{{{NS_XADES}}}IssuerSerial')
    etree.SubElement(issuer_serial, f'{{{NS_DS}}}X509IssuerName').text = issuer_name
    etree.SubElement(issuer_serial, f'{{{NS_DS}}}X509SerialNumber').text = serial_number

    # Digest de SignedProperties (se calcula sobre su forma canonicalizada,
    # ANTES de insertarlo en el documento final)
    digest_signed_props = _sha1_b64(_c14n(signed_props))

    # ---- 4. Construir <ds:SignedInfo> con las 2 referencias ----
    signed_info = etree.Element(f'{{{NS_DS}}}SignedInfo', nsmap={'ds': NS_DS})
    c14n_method = etree.SubElement(signed_info, f'{{{NS_DS}}}CanonicalizationMethod')
    c14n_method.set('Algorithm', NS_C14N)
    sig_method = etree.SubElement(signed_info, f'{{{NS_DS}}}SignatureMethod')
    sig_method.set('Algorithm', NS_RSA_SHA1)

    # Referencia 1: al documento completo
    ref_doc = etree.SubElement(signed_info, f'{{{NS_DS}}}Reference')
    ref_doc.set('Id', reference_id)
    ref_doc.set('URI', '#comprobante')
    transforms = etree.SubElement(ref_doc, f'{{{NS_DS}}}Transforms')
    transform = etree.SubElement(transforms, f'{{{NS_DS}}}Transform')
    transform.set('Algorithm', NS_ENVELOPED)
    dm1 = etree.SubElement(ref_doc, f'{{{NS_DS}}}DigestMethod')
    dm1.set('Algorithm', NS_SHA1)
    etree.SubElement(ref_doc, f'{{{NS_DS}}}DigestValue').text = digest_documento

    # Referencia 2: a las SignedProperties (obligatoria en XAdES-BES)
    ref_props = etree.SubElement(signed_info, f'{{{NS_DS}}}Reference')
    ref_props.set('Type', 'http://uri.etsi.org/01903#SignedProperties')
    ref_props.set('URI', f'#{signed_props_id}')
    dm2 = etree.SubElement(ref_props, f'{{{NS_DS}}}DigestMethod')
    dm2.set('Algorithm', NS_SHA1)
    etree.SubElement(ref_props, f'{{{NS_DS}}}DigestValue').text = digest_signed_props

    # ---- 5. Firmar SignedInfo canonicalizado con la clave privada ----
    signed_info_c14n = _c14n(signed_info)
    firma_bytes = clave_privada.sign(
        signed_info_c14n, padding.PKCS1v15(), crypto_hashes.SHA1()
    )
    signature_value_b64 = base64.b64encode(firma_bytes).decode()

    # ---- 6. Ensamblar <ds:Signature> completo ----
    signature = etree.Element(f'{{{NS_DS}}}Signature', nsmap={'ds': NS_DS})
    signature.set('Id', signature_id)
    signature.append(signed_info)

    sig_value_el = etree.SubElement(signature, f'{{{NS_DS}}}SignatureValue')
    sig_value_el.text = signature_value_b64

    key_info = etree.SubElement(signature, f'{{{NS_DS}}}KeyInfo')
    key_info.set('Id', keyinfo_id)
    x509_data = etree.SubElement(key_info, f'{{{NS_DS}}}X509Data')
    etree.SubElement(x509_data, f'{{{NS_DS}}}X509Certificate').text = cert_pem_contenido

    obj = etree.SubElement(signature, f'{{{NS_DS}}}Object')
    obj.append(qualifying)

    # ---- 7. Insertar la firma dentro del documento (enveloped) ----
    doc.append(signature)

    return etree.tostring(
        doc, xml_declaration=True, encoding='UTF-8', standalone=True
    ).decode('utf-8')
