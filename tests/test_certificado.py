from datetime import datetime, timedelta, timezone

import pytest

from nfse import Certificado, CertificadoInvalido

from .conftest import CNPJ, SENHA, gerar_pfx


def test_le_cnpj_titular_e_validade(cert):
    assert cert.cnpj == CNPJ
    assert cert.titular == f"EMPRESA TESTE LTDA:{CNPJ}"
    assert 360 <= cert.dias_para_vencer() <= 365
    cert.validar(CNPJ)


def test_senha_errada():
    with pytest.raises(CertificadoInvalido, match="senha"):
        Certificado.de_pfx(gerar_pfx(), "errada")


def test_cnpj_diferente_do_prestador(cert):
    with pytest.raises(CertificadoInvalido, match="difere"):
        cert.validar("99888777000166")


def test_vencido():
    antigo = Certificado.de_pfx(gerar_pfx(inicio=datetime.now(timezone.utc) - timedelta(days=400), dias=30), SENHA)
    with pytest.raises(CertificadoInvalido, match="venceu"):
        antigo.validar(CNPJ)


def test_contexto_tls_nao_deixa_arquivo(cert, tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)
    cert.contexto_tls()
    assert list(tmp_path.iterdir()) == []
