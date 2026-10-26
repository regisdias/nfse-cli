import email
import email.policy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from nfse_cli import correio

RASCUNHO = dict(para="a@x.com,b@x.com", cc="c@x.com", assunto="NFS-e nº 7 - outubro/2026 - D'Ávila",
                corpo="Olá, Fulana,\n\nSegue a nota de R$ 9.000,00 & cia.\n")


@pytest.fixture
def rascunho(tmp_path) -> correio.Rascunho:
    pdf = tmp_path / "NFS-e 7, outubro.pdf"
    pdf.write_bytes(b"%PDF-1.4 teste")
    return correio.Rascunho(**RASCUNHO, anexos=[pdf], eml=tmp_path / "nota.eml")


def test_gmail_e_outlook_web_levam_tudo_menos_o_anexo(rascunho):
    q = parse_qs(urlparse(correio.url_web("gmail", rascunho)).query)
    assert q == {"view": ["cm"], "fs": ["1"], "to": [RASCUNHO["para"]], "cc": ["c@x.com"],
                 "su": [RASCUNHO["assunto"]], "body": [RASCUNHO["corpo"]]}
    url = correio.url_web("outlook-web", rascunho)
    assert url.startswith("https://outlook.office.com/mail/deeplink/compose?")
    assert parse_qs(urlparse(url).query)["subject"] == [RASCUNHO["assunto"]]


def test_thunderbird_corpo_em_arquivo_e_anexo_como_url(rascunho, tmp_path):
    cmd = correio.comando_thunderbird("thunderbird", rascunho, tmp_path / "corpo.txt")
    assert cmd[:2] == ["thunderbird", "-compose"]
    assert "subject='NFS-e nº 7 - outubro/2026 - D’Ávila'" in cmd[2]  # aspas simples não quebram o comando
    assert f"message='{tmp_path / 'corpo.txt'}'" in cmd[2]
    assert "attachment='file://" in cmd[2] and "NFS-e%207%2C%20outubro.pdf" in cmd[2]


def test_eml(rascunho):
    assert "nota.eml" in correio.abrir("eml", rascunho)
    msg = email.message_from_bytes(rascunho.eml.read_bytes(), policy=email.policy.default)
    assert msg["X-Unsent"] == "1" and msg["Cc"] == "c@x.com"
    assert [p.get_filename() for p in msg.iter_attachments()] == ["NFS-e 7, outubro.pdf"]


def test_padrao_sem_programa_que_anexa_vira_eml(monkeypatch):
    monkeypatch.setattr(correio, "padrao_do_sistema", lambda: None)
    assert correio.modo_padrao() == "eml"
    monkeypatch.setattr(correio, "padrao_do_sistema", lambda: "thunderbird")
    monkeypatch.setattr(correio, "binario_thunderbird", lambda: None)
    assert correio.modo_padrao() == "eml"  # padrão do sistema, mas não instalado


def test_modo_desconhecido(rascunho):
    with pytest.raises(correio.ErroCli):
        correio.abrir("pombo-correio", rascunho)


@pytest.mark.skipif(not Path("/usr/bin/osacompile").exists(), reason="só no macOS")
@pytest.mark.parametrize("modo", ["outlook", "mail"])
def test_applescript_compila(modo, tmp_path):
    import subprocess

    fonte = tmp_path / "s.applescript"
    fonte.write_text(correio.APPLESCRIPT[modo])
    r = subprocess.run(["osacompile", "-o", str(tmp_path / "s.scpt"), str(fonte)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
