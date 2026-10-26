from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

from nfse import HOMOLOGACAO, LEIAUTES, Certificado, Config, Emissao, Prestador, Servico, Tomador, TotTrib
from nfse.certificado import OID_CNPJ

CNPJ = "11222333000181"
SENHA = "senha-de-teste"


def gerar_pfx(cnpj: str = CNPJ, inicio: datetime | None = None, dias: int = 365) -> bytes:
    """.pfx autoassinado no formato ICP-Brasil: CN "NOME:CNPJ" e CNPJ no otherName."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    inicio = inicio or datetime.now(timezone.utc) - timedelta(days=1)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{cnpj}")])
    # Valor do otherName: OCTET STRING DER com os dígitos, como nos certificados reais.
    valor = bytes([0x04, len(cnpj)]) + cnpj.encode()
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(inicio + timedelta(days=dias))
        .add_extension(x509.SubjectAlternativeName([x509.OtherName(OID_CNPJ, valor)]), critical=False)
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(b"teste", chave, cert, None, BestAvailableEncryption(SENHA.encode()))


@pytest.fixture(autouse=True)
def sem_aviso_de_atualizacao(monkeypatch):
    monkeypatch.setenv("NFSE_SEM_AVISO_ATUALIZACAO", "1")


@pytest.fixture(scope="session")
def pfx() -> bytes:
    return gerar_pfx()


@pytest.fixture(scope="session")
def cert(pfx) -> Certificado:
    return Certificado.de_pfx(pfx, SENHA)


@pytest.fixture
def prestador() -> Prestador:
    return Prestador(cnpj=CNPJ, cod_municipio="3550308", op_simp_nac=3, reg_ap_trib_sn=1, fone="11999999999")


@pytest.fixture
def servico() -> Servico:
    return Servico(
        c_trib_nac="170101",
        c_nbs="114013900",
        cod_municipio_prestacao="3550308",
        tot_trib=TotTrib.sn("6.00"),
    )


@pytest.fixture
def cfg(prestador, servico) -> Config:
    return Config(prestador, servico)


@pytest.fixture
def tomador() -> Tomador:
    return Tomador(documento="11444777000161", nome="CLIENTE TESTE LTDA", email="fiscal@cliente.com.br")


@pytest.fixture(params=LEIAUTES)
def emissao(request) -> Emissao:
    """Uma vez para cada pacote de esquemas: todo teste de DPS roda nos dois."""
    return Emissao(
        ambiente=HOMOLOGACAO,
        leiaute=request.param,
        serie="1",
        numero=1,
        valor=Decimal("9000"),
        descricao="Consultoria em tecnologia da informação.\nSegunda linha da descrição.",
    )
