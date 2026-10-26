"""Assinatura XMLDSig enveloped do elemento com atributo Id (infDPS, infPedReg...).

Perfil exigido pela Sefin Nacional:
- Reference para "#<Id>", transforms enveloped-signature + C14N 1.0 inclusiva;
- RSA-SHA256 com digest SHA-256 (SHA-1 ainda disponível, por garantia);
- <Signature> no namespace xmldsig como namespace padrão: prefixo como
  "ds:" é rejeitado (E1228);
- certificado do emitente em KeyInfo/X509Data.

Depois de assinado, o XML não pode ser reformatado: serializar uma vez e
mandar esses bytes.
"""

from __future__ import annotations

import base64
import copy
import hashlib

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree

from .certificado import Certificado

DSIG = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

ALGORITMOS = {
    "sha256": (
        "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "http://www.w3.org/2001/04/xmlenc#sha256",
        hashlib.sha256,
        hashes.SHA256,
    ),
    "sha1": (
        "http://www.w3.org/2000/09/xmldsig#rsa-sha1",
        "http://www.w3.org/2000/09/xmldsig#sha1",
        hashlib.sha1,
        hashes.SHA1,
    ),
}


class AssinaturaInvalida(Exception):
    pass


def _c14n(elemento: etree._Element) -> bytes:
    """C14N 1.0 inclusiva do elemento como subconjunto do documento.

    Não usa o C14N de subárvore do libxml2 direto: com um namespace padrão
    aninhado (o <Signature> redefine o padrão da <DPS>) ele emite xmlns=""
    falso nos netos e a assinatura sai sobre bytes que ninguém mais calcula.
    Uma cópia do elemento como raiz leva junto os namespaces em escopo, que é
    exatamente o que a C14N inclusiva coloca no elemento-ápice.
    """
    copia = copy.deepcopy(elemento)
    copia.tail = None
    return etree.tostring(copia, method="c14n", exclusive=False, with_comments=False)


def _d(pai: etree._Element, nome: str, texto: str | None = None, **atributos: str) -> etree._Element:
    filho = etree.SubElement(pai, f"{{{DSIG}}}{nome}", atributos)
    if texto is not None:
        filho.text = texto
    return filho


def assinar(raiz: etree._Element, cert: Certificado, algoritmo: str = "sha256") -> etree._Element:
    """Assina o primeiro filho de `raiz` que tem Id; a <Signature> entra como último filho da raiz."""
    metodo_assinatura, metodo_digest, hash_digest, hash_assinatura = ALGORITMOS[algoritmo]
    alvo = next((f for f in raiz if f.get("Id")), None)
    if alvo is None:
        raise AssinaturaInvalida("nenhum filho da raiz tem atributo Id para assinar")
    if raiz.find(f"{{{DSIG}}}Signature") is not None:
        raise AssinaturaInvalida("o XML já está assinado")

    digest = base64.b64encode(hash_digest(_c14n(alvo)).digest()).decode()

    assinatura = etree.SubElement(raiz, f"{{{DSIG}}}Signature", nsmap={None: DSIG})
    signed_info = _d(assinatura, "SignedInfo")
    _d(signed_info, "CanonicalizationMethod", Algorithm=C14N)
    _d(signed_info, "SignatureMethod", Algorithm=metodo_assinatura)
    referencia = _d(signed_info, "Reference", URI="#" + alvo.get("Id"))
    transforms = _d(referencia, "Transforms")
    _d(transforms, "Transform", Algorithm=ENVELOPED)
    _d(transforms, "Transform", Algorithm=C14N)
    _d(referencia, "DigestMethod", Algorithm=metodo_digest)
    _d(referencia, "DigestValue", digest)

    # SignedInfo é canonicalizado já dentro da árvore, com os namespaces que herda.
    valor = cert.chave.sign(_c14n(signed_info), padding.PKCS1v15(), hash_assinatura())
    _d(assinatura, "SignatureValue", base64.b64encode(valor).decode())
    key_info = _d(assinatura, "KeyInfo")
    x509_data = _d(key_info, "X509Data")
    _d(x509_data, "X509Certificate", base64.b64encode(cert.cert_der()).decode())
    return raiz


def verificar(xml: bytes) -> x509.Certificate:
    """Confere digest e assinatura a partir dos bytes finais; devolve o certificado usado."""
    raiz = etree.fromstring(xml)
    assinatura = raiz.find(f"{{{DSIG}}}Signature")
    if assinatura is None:
        raise AssinaturaInvalida("XML sem <Signature>")
    signed_info = assinatura.find(f"{{{DSIG}}}SignedInfo")
    metodo = signed_info.find(f"{{{DSIG}}}SignatureMethod").get("Algorithm")
    algoritmo = next((k for k, v in ALGORITMOS.items() if v[0] == metodo), None)
    if algoritmo is None:
        raise AssinaturaInvalida(f"algoritmo não suportado: {metodo}")
    _, _, hash_digest, hash_assinatura = ALGORITMOS[algoritmo]

    referencia = signed_info.find(f"{{{DSIG}}}Reference")
    alvo_id = referencia.get("URI").removeprefix("#")
    alvo = next((f for f in raiz if f.get("Id") == alvo_id), None)
    if alvo is None:
        raise AssinaturaInvalida(f"Reference aponta para Id inexistente: {alvo_id}")
    digest = base64.b64encode(hash_digest(_c14n(alvo)).digest()).decode()
    if digest != referencia.findtext(f"{{{DSIG}}}DigestValue"):
        raise AssinaturaInvalida("digest não confere: o conteúdo assinado foi alterado")

    der = base64.b64decode(assinatura.findtext(f".//{{{DSIG}}}X509Certificate"))
    cert = x509.load_der_x509_certificate(der)
    chave = cert.public_key()
    if not isinstance(chave, rsa.RSAPublicKey):
        raise AssinaturaInvalida("certificado sem chave RSA")
    valor = base64.b64decode(assinatura.findtext(f"{{{DSIG}}}SignatureValue"))
    try:
        chave.verify(valor, _c14n(signed_info), padding.PKCS1v15(), hash_assinatura())
    except InvalidSignature as e:
        raise AssinaturaInvalida("SignatureValue não confere com o SignedInfo") from e
    return cert
