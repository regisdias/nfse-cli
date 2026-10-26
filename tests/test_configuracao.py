import subprocess
import sys
from decimal import Decimal

import pytest

from nfse import DadosInvalidos, config_de_dict, tomador_de_dict


def test_config_de_dict():
    cfg = config_de_dict({
        "prestador": {"cnpj": 11222333000181, "cod_municipio": 3550308, "op_simp_nac": 3},
        "servico": {"c_trib_nac": "170101", "p_aliq": 2.5, "tot_trib": {"modo": "nao_informado"}},
    })
    assert cfg.prestador.cnpj == "11222333000181"
    assert cfg.servico.cod_municipio_prestacao == "3550308"
    assert cfg.servico.p_aliq == Decimal("2.5")


@pytest.mark.parametrize("dados, falta", [
    ({}, "config.prestador"),
    ({"prestador": {"cnpj": "1"}, "servico": {}}, "prestador.cod_municipio"),
    ({"prestador": {"cnpj": "1", "cod_municipio": "1", "op_simp_nac": 3}, "servico": {"c_trib_nac": "1"}},
     "servico.tot_trib.percentual"),
])
def test_config_incompleta(dados, falta):
    with pytest.raises(DadosInvalidos, match=falta):
        config_de_dict(dados)


def test_tomador_com_endereco_numerico():
    t = tomador_de_dict({"documento": "11444777000161", "nome": "X", "endereco": {
        "cod_municipio": 3550308, "cep": "01001000", "logradouro": "Rua", "numero": 1, "bairro": "Centro"}})
    assert t.endereco.numero == "1"


def test_biblioteca_sem_reportlab():
    """A Lambda que só emite não leva o reportlab: importar e gerar DPS não pode depender dele."""
    codigo = """
import sys
sys.modules["reportlab"] = None
import nfse, nfse_lambda.handler
try:
    nfse.gerar_danfse(b"<NFSe/>")
except nfse.DanfseIndisponivel:
    print("ok")
"""
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert r.stdout.strip() == "ok", r.stderr
