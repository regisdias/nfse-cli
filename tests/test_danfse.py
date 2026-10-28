import re
from dataclasses import replace

import pytest
from lxml import etree

pytest.importorskip("reportlab")

from nfse import Endereco, gerar_danfse, gerar_dps  # noqa: E402
from nfse.danfse import _cep, _dinheiro, _doc, _fone, municipio  # noqa: E402
from nfse.dps import NS  # noqa: E402

CHAVE = "35503082" + "11222333000181" + "0000000000007" + "2610" + "123456789"


def nfse_de_teste(dps_xml: bytes, ambiente: str = "2") -> bytes:
    """NFS-e sintética em volta de uma DPS de teste, como a Sefin devolveria."""
    nfse = etree.Element(f"{{{NS}}}NFSe", nsmap={None: NS}, versao="1.01")
    inf = etree.SubElement(nfse, f"{{{NS}}}infNFSe", Id="NFS" + CHAVE)
    for campo, valor in [
        ("xLocEmi", "São Paulo"), ("xLocPrestacao", "São Paulo"), ("nNFSe", "7"), ("cLocIncid", "3550308"),
        ("xLocIncid", "São Paulo"), ("xTribNac", "Assessoria ou consultoria de qualquer natureza."),
        ("verAplic", "teste"), ("ambGer", "2"), ("tpEmis", "1"), ("procEmi", "1"), ("cStat", "100"),
        ("dhProc", "2026-10-26T14:04:34-03:00"), ("nDFSe", "1"),
    ]:
        etree.SubElement(inf, f"{{{NS}}}{campo}").text = valor
    emit = etree.SubElement(inf, f"{{{NS}}}emit")
    etree.SubElement(emit, f"{{{NS}}}CNPJ").text = "11222333000181"
    etree.SubElement(emit, f"{{{NS}}}xNome").text = "EMPRESA TESTE LTDA"
    end = etree.SubElement(emit, f"{{{NS}}}enderNac")
    for campo, valor in [("xLgr", "PRACA DA SE"), ("nro", "1"), ("xBairro", "SE"), ("cMun", "3550308"),
                         ("UF", "SP"), ("CEP", "01001000")]:
        etree.SubElement(end, f"{{{NS}}}{campo}").text = valor
    valores = etree.SubElement(inf, f"{{{NS}}}valores")
    etree.SubElement(valores, f"{{{NS}}}vLiq").text = "9000.00"
    dps = etree.fromstring(dps_xml)
    dps.find(f".//{{{NS}}}tpAmb").text = ambiente
    inf.append(dps)
    return etree.tostring(nfse, xml_declaration=True, encoding="UTF-8")


def test_danfse_e_um_pdf_de_uma_pagina(cfg, cert, emissao, tomador):
    end = Endereco(cod_municipio="3304557", cep="20010000", logradouro="Rua X", numero="100", bairro="Centro")
    pdf = gerar_danfse(nfse_de_teste(gerar_dps(cfg, cert, emissao, replace(tomador, endereco=end)).xml))
    assert pdf.startswith(b"%PDF")
    assert re.search(rb"/Count 1\b", pdf) and not re.search(rb"/Count [2-9]", pdf)


@pytest.mark.parametrize("ambiente", ["1", "2"])
def test_danfse_sem_tomador_e_descricao_longa(cfg, cert, emissao, ambiente):
    longa = replace(emissao, descricao=("Consultoria em tecnologia. " * 60).strip())
    pdf = gerar_danfse(nfse_de_teste(gerar_dps(cfg, cert, longa, None).xml, ambiente))
    assert pdf.startswith(b"%PDF")


def test_danfse_de_empresa_fora_do_simples(cfg_presumido, cert, emissao, tomador):
    pdf = gerar_danfse(nfse_de_teste(gerar_dps(cfg_presumido, cert, emissao, tomador).xml))
    assert pdf.startswith(b"%PDF")


def test_xml_que_nao_e_nfse():
    with pytest.raises(ValueError, match="infNFSe"):
        gerar_danfse(b'<DPS xmlns="http://www.sped.fazenda.gov.br/nfse"/>')


def test_formatos_do_danfse():
    assert _doc("11222333000181", None, None) == "11.222.333/0001-81"
    assert _doc(None, "12345678909", None) == "123.456.789-09"
    assert _fone("1133334444") == "(11) 3333-4444"
    assert _fone("11999998888") == "(11) 99999-8888"
    assert _cep("01001000") == "01.001-000"
    assert _dinheiro("18000") == "R$ 18.000,00"
    assert _dinheiro(None) == "-"
    assert municipio("3550308") == ("São Paulo", "SP")
    assert municipio("9999999") is None


def test_mesmo_xml_mesmo_pdf(cfg, cert, emissao, tomador):
    xml = nfse_de_teste(gerar_dps(cfg, cert, emissao, tomador).xml)
    assert gerar_danfse(xml) == gerar_danfse(xml)
