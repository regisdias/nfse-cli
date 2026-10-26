"""Certificado A1 (.pfx) carregado a partir de bytes + senha.

Nada aqui lê caminho de arquivo: quem chama decide de onde vêm os bytes
(arquivo local, Secrets Manager...). A chave privada fica só em memória;
o único momento em que toca o disco é no TLS (ver `contexto_tls`).
"""

from __future__ import annotations

import os
import secrets
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12

# OID ICP-Brasil do CNPJ da pessoa jurídica titular (otherName do SAN)
OID_CNPJ = x509.ObjectIdentifier("2.16.76.1.3.3")


class CertificadoInvalido(Exception):
    pass


@dataclass(frozen=True)
class Certificado:
    chave: rsa.RSAPrivateKey
    cert: x509.Certificate
    cadeia: tuple[x509.Certificate, ...]

    @classmethod
    def de_pfx(cls, dados: bytes, senha: str | bytes) -> "Certificado":
        if isinstance(senha, str):
            senha = senha.encode()
        try:
            chave, cert, cadeia = pkcs12.load_key_and_certificates(dados, senha)
        except ValueError as e:
            raise CertificadoInvalido("não foi possível abrir o .pfx (senha errada ou arquivo inválido)") from e
        if cert is None or chave is None:
            raise CertificadoInvalido(".pfx sem certificado ou sem chave privada")
        if not isinstance(chave, rsa.RSAPrivateKey):
            raise CertificadoInvalido("a chave do certificado não é RSA")
        return cls(chave=chave, cert=cert, cadeia=tuple(cadeia or ()))

    @property
    def cnpj(self) -> str | None:
        """CNPJ do titular: otherName ICP-Brasil, ou o sufixo do CN ("NOME:CNPJ")."""
        try:
            san = self.cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            for nome in san.get_values_for_type(x509.OtherName):
                if nome.type_id == OID_CNPJ:
                    digitos = "".join(c for c in nome.value.decode("latin-1") if c.isdigit())
                    if len(digitos) >= 14:
                        return digitos[-14:]
        except x509.ExtensionNotFound:
            pass
        cn = self.titular
        if ":" in cn:
            sufixo = cn.rsplit(":", 1)[1].strip()
            if len(sufixo) == 14 and sufixo.isdigit():
                return sufixo
        return None

    @property
    def titular(self) -> str:
        atributos = self.cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return str(atributos[0].value) if atributos else self.cert.subject.rfc4514_string()

    @property
    def valido_de(self) -> datetime:
        return self.cert.not_valid_before_utc

    @property
    def valido_ate(self) -> datetime:
        return self.cert.not_valid_after_utc

    def dias_para_vencer(self, agora: datetime | None = None) -> int:
        agora = agora or datetime.now(timezone.utc)
        return (self.valido_ate - agora).days

    def validar(self, cnpj_esperado: str | None = None, agora: datetime | None = None) -> None:
        agora = agora or datetime.now(timezone.utc)
        if agora < self.valido_de:
            raise CertificadoInvalido(f"certificado só vale a partir de {self.valido_de:%d/%m/%Y}")
        if agora > self.valido_ate:
            raise CertificadoInvalido(f"certificado venceu em {self.valido_ate:%d/%m/%Y}")
        if cnpj_esperado and self.cnpj != cnpj_esperado:
            raise CertificadoInvalido(f"CNPJ do certificado ({self.cnpj}) difere do prestador ({cnpj_esperado})")

    def cert_der(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.DER)

    def contexto_tls(self) -> ssl.SSLContext:
        """Contexto TLS com o certificado de cliente (mTLS exigido pela Sefin).

        O `ssl` da stdlib só carrega certificado de cliente a partir de arquivo.
        A chave vai para um arquivo temporário cifrado com uma senha aleatória,
        lido e apagado na hora: o disco nunca vê a chave em claro.
        """
        senha = secrets.token_bytes(32)
        pem_chave = self.chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(senha),
        )
        pem_cert = b"".join(
            c.public_bytes(serialization.Encoding.PEM) for c in (self.cert, *self.cadeia)
        )
        ctx = ssl.create_default_context()
        with tempfile.TemporaryDirectory(prefix="nfse-") as pasta:
            caminho_chave = os.path.join(pasta, "chave.pem")
            caminho_cert = os.path.join(pasta, "cert.pem")
            for caminho, conteudo in ((caminho_chave, pem_chave), (caminho_cert, pem_cert)):
                fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(conteudo)
            ctx.load_cert_chain(caminho_cert, caminho_chave, password=senha)
        return ctx
