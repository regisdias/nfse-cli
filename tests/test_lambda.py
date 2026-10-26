import base64
import json
import logging

import pytest

from nfse_lambda import handler as h

from .conftest import CNPJ, SENHA
from .test_emissao import SefinFalsa

CONFIG = {
    "prestador": {"cnpj": CNPJ, "cod_municipio": "3550308", "op_simp_nac": 3, "reg_ap_trib_sn": 1},
    "servico": {"c_trib_nac": "170101", "c_nbs": "114013900", "tot_trib": {"modo": "sn", "percentual": 6}},
}
TOMADOR = {"documento": "11444777000161", "nome": "CLIENTE SIGILOSO LTDA", "email": "fiscal@cliente.com.br"}
NOTA = {"config": CONFIG, "serie": "1", "numero": 5, "valor": "9000.00", "descricao": "Consultoria.", "tomador": TOMADOR}


@pytest.fixture(autouse=True)
def ambiente_lambda(monkeypatch, pfx):
    lidos = []

    def ler_segredo(nome):
        lidos.append(nome)
        return {"pfx": base64.b64encode(pfx).decode(), "senha": SENHA}

    monkeypatch.setenv("NFSE_SEGREDO_CERTIFICADO", "nfse/certificado/{cnpj}")
    monkeypatch.delenv("NFSE_PRODUCAO_LIBERADA", raising=False)
    monkeypatch.setattr(h, "ler_segredo", ler_segredo)
    h._certificados.clear()
    h._sefins.clear()
    return lidos


@pytest.fixture
def sefin(monkeypatch):
    falsa = SefinFalsa()
    monkeypatch.setattr(h, "sefin", lambda cnpj, ambiente: falsa)
    return falsa


def test_dps_sem_enviar_le_o_segredo_do_cnpj(ambiente_lambda):
    r = h.handler({"acao": "dps", **NOTA})
    assert r["ok"] and r["id_dps"].startswith("DPS3550308")
    assert "<Signature" in r["xml_dps"]
    assert ambiente_lambda == [f"nfse/certificado/{CNPJ}"]
    h.handler({"acao": "dps", **NOTA})
    assert len(ambiente_lambda) == 1  # certificado fica em cache entre invocações


def test_emitir(sefin):
    r = h.handler({"acao": "emitir", **NOTA})
    assert r["ok"] and r["chave_acesso"] == "4" * 50 and r["numero_nfse"] == "7"
    assert len(sefin.recebidas) == 1


def test_producao_exige_liberacao_na_funcao(sefin, monkeypatch):
    r = h.handler({"acao": "emitir", "ambiente": "producao", **NOTA})
    assert r == {"ok": False, "erro": "dados", "mensagem": "produção não liberada nesta função (NFSE_PRODUCAO_LIBERADA)"}
    assert sefin.recebidas == []


def test_rejeicao_volta_com_codigos(monkeypatch):
    falsa = SefinFalsa(rejeitar={"erros": [{"Codigo": "E0625", "Descricao": "pAliq"}]})
    monkeypatch.setattr(h, "sefin", lambda cnpj, ambiente: falsa)
    r = h.handler({"acao": "emitir", **NOTA})
    assert r["ok"] is False and r["erro"] == "rejeicao" and r["erros"][0]["codigo"] == "E0625"


def test_dados_faltando():
    assert h.handler({"acao": "emitir", **{**NOTA, "valor": None}})["mensagem"] == "falta valor"
    assert h.handler({"acao": "emitir", **{k: v for k, v in NOTA.items() if k != "config"}})["mensagem"] == "falta config"
    assert h.handler({"acao": "apagar"})["erro"] == "dados"
    assert h.handler({"acao": "dps", **{**NOTA, "config": {"prestador": {}, "servico": {}}}})["erro"] == "dados"


def test_config_por_variavel(monkeypatch):
    monkeypatch.setenv("NFSE_CONFIG", json.dumps(CONFIG))
    assert h.handler({"acao": "dps", **{k: v for k, v in NOTA.items() if k != "config"}})["ok"]


def test_segredo_de_outro_cnpj(monkeypatch):
    outro = {**CONFIG, "prestador": {**CONFIG["prestador"], "cnpj": "99888777000100"}}
    r = h.handler({"acao": "dps", **{**NOTA, "config": outro}})
    assert r["erro"] == "certificado"


def test_log_nao_tem_xml_nem_tomador(sefin, caplog):
    caplog.set_level(logging.INFO, logger="nfse_lambda")
    h.handler({"acao": "emitir", **NOTA})
    h.handler({"acao": "dps", **NOTA})
    texto = caplog.text
    assert "emitida" in texto
    assert "<" not in texto and "SIGILOSO" not in texto and "11444777000161" not in texto and SENHA not in texto


def test_danfse_de_xml():
    pytest.importorskip("reportlab")
    from .test_danfse import nfse_de_teste

    xml = nfse_de_teste(h.handler({"acao": "dps", **NOTA})["xml_dps"].encode())
    r = h.handler({"acao": "danfse", "xml": xml.decode()})
    assert base64.b64decode(r["pdf_base64"]).startswith(b"%PDF")
