import zlib
from dataclasses import replace
from decimal import Decimal

import pytest
from lxml import etree

from nfse import gerar_dps, tabelas
from nfse.dps import NS
from nfse.modelo import chave_valida, chaves_no_pdf, cnpj_da_chave, ler_nfse

from .conftest import CNPJ

CHAVE = "3550308" + "2" + "2" + CNPJ + "0000000000007" + "2610" + "123456789" + "0"


def nfse_de(dps_xml: bytes, chave: str = CHAVE) -> bytes:
    nota = etree.Element(f"{{{NS}}}NFSe", nsmap={None: NS})
    inf = etree.SubElement(nota, f"{{{NS}}}infNFSe", Id="NFS" + chave)
    etree.SubElement(inf, f"{{{NS}}}nNFSe").text = "7"
    etree.SubElement(inf, f"{{{NS}}}dhProc").text = "2026-10-26T14:04:34-03:00"
    emit = etree.SubElement(inf, f"{{{NS}}}emit")
    etree.SubElement(emit, f"{{{NS}}}xNome").text = "EMPRESA TESTE LTDA"
    inf.append(etree.fromstring(dps_xml))
    return etree.tostring(nota, xml_declaration=True, encoding="UTF-8")


def acrescentar(xml: bytes, pai: str, filho: str, texto: str = "1") -> bytes:
    raiz = etree.fromstring(xml)
    alvo = raiz.find(".//" + "/".join(f"{{{NS}}}{p}" for p in pai.split("/")))
    el = alvo
    for parte in filho.split("/"):
        el = etree.SubElement(el, f"{{{NS}}}{parte}")
    el.text = texto
    return etree.tostring(raiz)


@pytest.fixture
def nota(cfg, cert, emissao, tomador) -> bytes:
    return nfse_de(gerar_dps(cfg, cert, emissao, tomador).xml)


def test_le_a_configuracao_da_nota(nota, cfg, tomador, emissao):
    m = ler_nfse(nota)
    assert m.chave == CHAVE and m.numero_nfse == "7" and m.prestador_nome == "EMPRESA TESTE LTDA"
    assert m.config["prestador"] == {"cnpj": CNPJ, "cod_municipio": "3550308", "op_simp_nac": 3, "reg_esp_trib": 0,
                                     "reg_ap_trib_sn": 1, "fone": "11999999999"}
    assert m.config["servico"] == {"c_trib_nac": "170101", "c_nbs": "114013900", "trib_issqn": 1, "tp_ret_issqn": 1,
                                   "tot_trib": {"modo": "sn", "percentual": "6.00"}}
    assert m.tomador == {"documento": tomador.documento, "nome": tomador.nome, "email": tomador.email}
    assert m.valor == "9000.00" and m.descricao == emissao.descricao
    assert m.serie_dps == "1" and m.numero_dps == 1
    assert m.nao_suportado == [] and m.avisos == []


def test_o_que_volta_monta_a_mesma_dps(nota, cert, emissao):
    """Ida e volta: a configuração lida da nota gera uma DPS com os mesmos campos."""
    import nfse

    m = ler_nfse(nota)
    de_novo = gerar_dps(nfse.config_de_dict(m.config), cert, emissao, nfse.tomador_de_dict(m.tomador)).xml
    original = etree.fromstring(nota).find(f".//{{{NS}}}infDPS")
    refeita = etree.fromstring(de_novo).find(f".//{{{NS}}}infDPS")
    sem_hora = lambda el: [(e.tag, e.text) for e in el.iter() if etree.QName(e).localname != "dhEmi"]  # noqa: E731
    assert sem_hora(original) == sem_hora(refeita)


def test_lucro_presumido_ida_e_volta(cfg_presumido, cert, emissao, tomador):
    import nfse

    nota = nfse_de(gerar_dps(cfg_presumido, cert, emissao, tomador).xml)
    m = ler_nfse(nota)
    assert m.nao_suportado == []
    assert m.config["servico"]["pis_cofins"] == {"cst": "01", "p_aliq_pis": "0.65", "p_aliq_cofins": "3.00"}
    assert m.config["servico"]["ibs_cbs"] == {"cst": "000", "c_class_trib": "000001", "c_ind_op": "070101"}
    de_novo = gerar_dps(nfse.config_de_dict(m.config), cert, emissao, nfse.tomador_de_dict(m.tomador)).xml
    sem_hora = lambda x: [(e.tag, e.text) for e in etree.fromstring(x).find(f".//{{{NS}}}infDPS").iter()  # noqa: E731
                          if etree.QName(e).localname != "dhEmi"]
    assert sem_hora(nota) == sem_hora(de_novo)


def test_pis_cofins_retido_nao_sabe_emitir(cfg_presumido, cert, emissao):
    raiz = etree.fromstring(nfse_de(gerar_dps(cfg_presumido, cert, emissao, None).xml))
    raiz.find(f".//{{{NS}}}tpRetPisCofins").text = "1"
    assert "PIS/COFINS/CSLL retidos" in ler_nfse(etree.tostring(raiz)).nao_suportado


@pytest.mark.parametrize("pai, filho, texto, esperado", [
    ("valores/trib", "tribFed/vRetCSLL", "100.00", "tributos federais (retenções)"),
    ("infDPS", "interm/CNPJ", "11444777000161", "intermediário do serviço"),
    ("valores", "vDedRed/vDR", "10.00", "dedução da base de cálculo"),
])
def test_o_que_nao_sabe_emitir(nota, pai, filho, texto, esperado):
    assert esperado in ler_nfse(acrescentar(nota, pai, filho, texto)).nao_suportado


def test_pis_cofins_sem_retencao_do_emissor_web_nao_atrapalha(nota):
    xml = acrescentar(nota, "valores/trib", "tribFed/piscofins/CST", "00")
    raiz = etree.fromstring(xml)
    etree.SubElement(raiz.find(f".//{{{NS}}}piscofins"), f"{{{NS}}}tpRetPisCofins").text = "0"
    assert ler_nfse(etree.tostring(raiz)).nao_suportado == []


def test_iss_retido_e_mei(nota):
    raiz = etree.fromstring(nota)
    raiz.find(f".//{{{NS}}}tpRetISSQN").text = "2"
    raiz.find(f".//{{{NS}}}opSimpNac").text = "2"
    nao = ler_nfse(etree.tostring(raiz)).nao_suportado
    assert "ISS retido pelo tomador" in nao and "MEI" in nao


def test_xml_que_nao_e_nota():
    with pytest.raises(ValueError, match="infDPS"):
        ler_nfse(b"<qualquer/>")


def test_chave():
    assert chave_valida(CHAVE) and cnpj_da_chave(CHAVE) == CNPJ
    assert not chave_valida("9" * 50)  # município inexistente
    assert not chave_valida(CHAVE[:-1])


def _pdf(conteudo: bytes) -> bytes:
    fluxo = zlib.compress(conteudo)
    cabecalho = b"%%PDF-1.7\n1 0 obj\n<</Length %d/Filter/FlateDecode>>\nstream\n" % len(fluxo)
    return cabecalho + fluxo + b"\nendstream\nendobj\n%%EOF\n"


def test_chave_no_pdf_do_emissor_web():
    """Como o PDF do governo escreve: rótulo e chave em operadores Tj separados."""
    texto = b"BT (CHAVE) Tj (NFS-) Tj (e) Tj (" + CHAVE.encode() + b") Tj ET"
    assert chaves_no_pdf(_pdf(texto)) == [CHAVE]


def test_chave_quebrada_em_pedacos_no_pdf():
    texto = b"BT (" + CHAVE[:20].encode() + b") Tj (" + CHAVE[20:].encode() + b") Tj ET"
    assert chaves_no_pdf(_pdf(texto)) == [CHAVE]


def test_chave_no_nosso_danfse(nota):
    pytest.importorskip("reportlab")
    from nfse import gerar_danfse

    assert chaves_no_pdf(gerar_danfse(nota)) == [CHAVE]


def test_pdf_sem_chave_e_arquivo_que_nao_e_pdf():
    assert chaves_no_pdf(_pdf(b"BT (sem chave) Tj ET")) == []
    with pytest.raises(ValueError):
        chaves_no_pdf(b"<NFSe/>")


def test_tabelas():
    assert tabelas.municipio("3550308") == ("São Paulo", "SP")
    assert tabelas.buscar_municipios("sao paulo sp")[0][0] == "3550308"
    assert tabelas.buscar_servicos("17.01.01") == [("170101", tabelas.servico("170101"))]
    assert ("010101", "Análise e desenvolvimento de sistemas.") in tabelas.buscar_servicos("desenvolvimento de sistemas")
    assert tabelas.buscar_nbs("1.1401.39.00")[0][0] == "114013900"
    assert tabelas.buscar_servicos("xyzzy inexistente") == []


def test_irrf_retido_ida_e_volta(cfg_presumido, cert, emissao):
    import nfse

    cfg = replace(cfg_presumido, servico=replace(cfg_presumido.servico, irrf=nfse.Irrf(p_aliq=Decimal("1.50"))))
    nota = nfse_de(gerar_dps(cfg, cert, emissao, None).xml)
    m = ler_nfse(nota)
    assert m.nao_suportado == []
    assert m.config["servico"]["irrf"] == {"p_aliq": "1.50"}
    assert nfse.config_de_dict(m.config).servico.irrf.valor(Decimal("9000")) == Decimal("135.00")
