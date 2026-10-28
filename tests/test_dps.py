import re
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from lxml import etree

from nfse import (
    AssinaturaInvalida,
    HOMOLOGACAO,
    LEIAUTE_ANTERIOR,
    LEIAUTE_NT009,
    LEIAUTES,
    PRODUCAO,
    DadosInvalidos,
    Endereco,
    EsquemaInvalido,
    IbsCbs,
    Irrf,
    PisCofins,
    Prestador,
    TotTrib,
    gerar_dps,
    id_dps,
    montar_dps,
    validar_dps,
    verificar,
)
from nfse.dps import NS, data_hora, dinheiro

from .conftest import CNPJ


def test_id_dps_cnpj():
    i = id_dps("3550308", CNPJ, "1", 3)
    assert i == "DPS" + "3550308" + "2" + CNPJ + "00001" + "000000000000003"
    assert len(i) == 45


def test_id_dps_cpf_completa_com_zeros():
    i = id_dps("3550308", "12345678909", "70000", 12)
    assert i[10] == "1"
    assert i[11:25] == "00012345678909"
    assert len(i) == 45


def test_formatos():
    assert dinheiro("9000") == "9000.00"
    assert dinheiro(Decimal("0.005")) == "0.01"
    assert data_hora(datetime(2026, 10, 26, 15, 30, 5, 123, tzinfo=timezone.utc)) == "2026-10-26T12:30:05-03:00"


def test_dps_assinada_passa_no_xsd_e_na_assinatura(cfg, cert, emissao, tomador):
    dps = gerar_dps(cfg, cert, emissao, tomador)
    validar_dps(dps.xml, emissao.leiaute_efetivo)
    assert verificar(dps.xml).serial_number == cert.cert.serial_number
    assert dps.xml.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")
    # Sem prefixo de namespace em lugar nenhum (E1228)
    assert not re.search(rb"<\w+:", dps.xml)
    assert b'<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">' in dps.xml
    assert b"rsa-sha256" in dps.xml


def test_ordem_e_regras_do_prestador_emitente(cfg, cert, emissao, tomador):
    raiz = etree.fromstring(gerar_dps(cfg, cert, emissao, tomador).xml)
    assert [etree.QName(f).localname for f in raiz] == ["infDPS", "Signature"]
    prest = raiz.find(f"{{{NS}}}infDPS/{{{NS}}}prest")
    # Prestador emitente não informa nome nem endereço (E0121)
    assert prest.find(f"{{{NS}}}xNome") is None
    assert prest.find(f"{{{NS}}}end") is None
    # ME/EPP no SN sem retenção: sem alíquota
    assert raiz.find(f".//{{{NS}}}pAliq") is None
    assert raiz.findtext(f".//{{{NS}}}pTotTribSN") == "6.00"


def test_c14n_do_signed_info_sem_xmlns_vazio(cfg, cert, emissao, tomador):
    # Regressão: o C14N de subárvore do libxml2 punha xmlns="" nos filhos de
    # <Reference>, e a assinatura não batia com a de qualquer outro verificador.
    from nfse.assinatura import DSIG, _c14n
    raiz = etree.fromstring(gerar_dps(cfg, cert, emissao, tomador).xml)
    signed_info = _c14n(raiz.find(f"{{{DSIG}}}Signature/{{{DSIG}}}SignedInfo"))
    assert b'xmlns=""' not in signed_info
    assert signed_info.count(b"xmlns=") == 1
    inf = _c14n(raiz.find(f"{{{NS}}}infDPS"))
    assert inf.startswith(b'<infDPS xmlns="http://www.sped.fazenda.gov.br/nfse" Id="DPS')
    assert inf.count(b"xmlns=") == 1


def test_c14n_confere_com_implementacao_independente(cfg, cert, emissao, tomador):
    """Confere o C14N contra o canonicalize da stdlib (Python puro, sem libxml2).

    Canonicaliza o documento inteiro, recorta o elemento e acrescenta no ápice
    o namespace em escopo, que é o que a C14N inclusiva de subconjunto faz.
    Para este documento (sem comentários, sem prefixos) C14N 2.0 = 1.0.
    """
    import base64
    import hashlib
    import xml.etree.ElementTree as ET

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    from nfse.assinatura import DSIG, _c14n

    xml = gerar_dps(cfg, cert, emissao, tomador).xml
    doc = ET.canonicalize(xml.decode("utf-8")).encode("utf-8")

    def recorte(tag: bytes, ns: str) -> bytes:
        inicio = doc.index(b"<" + tag + b" ") if b"<" + tag + b" " in doc else doc.index(b"<" + tag + b">")
        fim = doc.index(b"</" + tag + b">") + len(tag) + 3
        trecho = doc[inicio:fim]
        if b"xmlns=" not in trecho.split(b">", 1)[0]:
            trecho = trecho.replace(b"<" + tag, b"<" + tag + b' xmlns="' + ns.encode() + b'"', 1)
        return trecho

    raiz = etree.fromstring(xml)
    inf = recorte(b"infDPS", NS)
    signed_info = recorte(b"SignedInfo", DSIG)
    assert inf == _c14n(raiz.find(f"{{{NS}}}infDPS"))
    assert signed_info == _c14n(raiz.find(f"{{{DSIG}}}Signature/{{{DSIG}}}SignedInfo"))

    digest = raiz.findtext(f".//{{{DSIG}}}DigestValue")
    assert base64.b64encode(hashlib.sha256(inf).digest()).decode() == digest
    valor = base64.b64decode(raiz.findtext(f".//{{{DSIG}}}SignatureValue"))
    cert.cert.public_key().verify(valor, signed_info, padding.PKCS1v15(), hashes.SHA256())


def test_alterar_um_byte_quebra_a_assinatura(cfg, cert, emissao, tomador):
    xml = gerar_dps(cfg, cert, emissao, tomador).xml
    with pytest.raises(AssinaturaInvalida, match="digest"):
        verificar(xml.replace(b"<vServ>9000.00</vServ>", b"<vServ>9000.01</vServ>"))


def test_tomador_com_endereco_passa_no_xsd(cfg, cert, emissao, tomador):
    end = Endereco(cod_municipio="3304557", cep="20010000", logradouro="Rua X", numero="100", bairro="Centro", complemento="Sala 2")
    validar_dps(gerar_dps(cfg, cert, emissao, replace(tomador, endereco=end)).xml, emissao.leiaute_efetivo)


def test_sem_tomador_passa_no_xsd(cfg, cert, emissao):
    validar_dps(gerar_dps(cfg, cert, emissao, None).xml, emissao.leiaute_efetivo)


@pytest.mark.parametrize("tot", [TotTrib.percentual("0", "0", "2"), TotTrib.valor("100", "0", "0")])
def test_outros_modos_de_tot_trib(cfg, cert, emissao, tot):
    validar_dps(gerar_dps(replace(cfg, servico=replace(cfg.servico, tot_trib=tot)), cert, emissao, None).xml, emissao.leiaute_efetivo)


def test_travessao_na_descricao_e_rejeitado(prestador, servico, emissao):
    with pytest.raises(DadosInvalidos, match="caracteres"):
        montar_dps(prestador, servico, None, replace(emissao, descricao="Consultoria — outubro"))


def test_me_epp_nao_pode_ind_tot_trib(prestador, servico, emissao):
    with pytest.raises(DadosInvalidos, match="E0712"):
        montar_dps(prestador, replace(servico, tot_trib=TotTrib.nao_informado()), None, emissao)


def test_reg_ap_trib_sn_so_para_me_epp(servico, emissao):
    p = Prestador(cnpj=CNPJ, cod_municipio="3550308", op_simp_nac=1, reg_ap_trib_sn=1)
    with pytest.raises(DadosInvalidos, match="E0162"):
        montar_dps(p, servico, None, emissao)


def test_serie_fora_da_faixa_de_aplicativo_proprio(prestador, servico, emissao):
    with pytest.raises(DadosInvalidos, match="E0010"):
        montar_dps(prestador, servico, None, replace(emissao, serie="70000"))


def test_competencia_no_futuro(prestador, servico, emissao):
    with pytest.raises(DadosInvalidos, match="E0015"):
        montar_dps(prestador, servico, None, replace(emissao, competencia=date(2099, 1, 1)))


def test_emissao_um_minuto_no_passado(prestador, servico, emissao):
    antes = datetime.now(timezone.utc)
    dh = montar_dps(prestador, servico, None, emissao).findtext(f".//{{{NS}}}dhEmi")
    assert datetime.fromisoformat(dh) < antes


def _ordem(xml: bytes, caminho: str) -> list[str]:
    return [etree.QName(f).localname for f in etree.fromstring(xml).find(caminho, {"n": NS})]


def test_ordem_de_cada_leiaute(cfg, cert, emissao, tomador):
    xml = gerar_dps(cfg, cert, emissao, tomador).xml
    inicio = _ordem(xml, "n:infDPS")[:10]
    cserv = _ordem(xml, "n:infDPS/n:serv/n:cServ")
    if emissao.leiaute == LEIAUTE_NT009:
        assert inicio[6:9] == ["tpEmit", "finNFSe", "cLocEmi"]
        assert cserv == ["cTribNac", "cNBS", "xDescServ"]
    else:
        assert inicio[6:8] == ["tpEmit", "cLocEmi"]
        assert cserv == ["cTribNac", "xDescServ", "cNBS"]


def test_dps_de_um_leiaute_nao_passa_no_outro(cfg, cert, emissao, tomador):
    xml = gerar_dps(cfg, cert, emissao, tomador).xml
    outro = next(l for l in LEIAUTES if l != emissao.leiaute)
    with pytest.raises(EsquemaInvalido):
        validar_dps(xml, outro)


def test_leiaute_padrao_por_ambiente(emissao):
    assert replace(emissao, leiaute=None, ambiente=HOMOLOGACAO).leiaute_efetivo == LEIAUTE_NT009
    assert replace(emissao, leiaute=None, ambiente=PRODUCAO).leiaute_efetivo == LEIAUTE_ANTERIOR


def test_leiaute_desconhecido(prestador, servico, emissao):
    with pytest.raises(DadosInvalidos, match="leiaute"):
        montar_dps(prestador, servico, None, replace(emissao, leiaute="20990101"))


# --- empresa fora do Simples (lucro presumido) ---------------------------------------

def test_lucro_presumido_passa_no_xsd(cfg_presumido, cert, emissao, tomador):
    xml = gerar_dps(cfg_presumido, cert, replace(emissao, valor=Decimal("180.00")), tomador).xml
    validar_dps(xml, emissao.leiaute_efetivo)
    r = etree.fromstring(xml)
    pc = {etree.QName(e).localname: e.text for e in r.find(".//n:piscofins", {"n": NS})}
    assert pc == {"CST": "01", "vBCPisCofins": "180.00", "pAliqPis": "0.65", "pAliqCofins": "3.00",
                  "vPis": "1.17", "vCofins": "5.40", "tpRetPisCofins": "0"}
    assert _ordem(xml, "n:infDPS/n:valores/n:trib") == ["tribMun", "tribFed", "totTrib"]
    assert _ordem(xml, "n:infDPS")[-2:] == ["valores", "IBSCBS"]
    ibs = _ordem(xml, "n:infDPS/n:IBSCBS")
    if emissao.leiaute == LEIAUTE_NT009:
        assert ibs == ["cIndOp", "indDest", "valores"]
    else:
        assert ibs == ["finNFSe", "cIndOp", "indDest", "valores"]
    caminho = ".//n:IBSCBS/n:valores/n:trib/" + ("" if emissao.leiaute == LEIAUTE_NT009 else "n:gIBSCBS/")
    assert r.findtext(caminho + "n:cClassTrib", namespaces={"n": NS}) == "000001"


def test_pis_cofins_arredonda_para_centavos(cfg_presumido, cert, emissao):
    xml = gerar_dps(cfg_presumido, cert, replace(emissao, valor=Decimal("157.33")), None).xml
    r = etree.fromstring(xml)
    assert r.findtext(".//n:vPis", namespaces={"n": NS}) == "1.02"
    assert r.findtext(".//n:vCofins", namespaces={"n": NS}) == "4.72"


def test_ibs_cbs_com_ind_final(cfg_presumido, cert, emissao):
    ibs = replace(cfg_presumido.servico.ibs_cbs, ind_final=0)
    cfg = replace(cfg_presumido, servico=replace(cfg_presumido.servico, ibs_cbs=ibs))
    xml = gerar_dps(cfg, cert, emissao, None).xml
    validar_dps(xml, emissao.leiaute_efetivo)
    assert "indFinal" in _ordem(xml, "n:infDPS/n:IBSCBS")


@pytest.mark.parametrize("campo, valor", [("cst", "00"), ("c_class_trib", "1"), ("c_ind_op", "abc")])
def test_ibs_cbs_codigos_invalidos(cfg_presumido, emissao, campo, valor):
    ibs = replace(cfg_presumido.servico.ibs_cbs, **{campo: valor})
    with pytest.raises(DadosInvalidos, match="IBS/CBS"):
        montar_dps(cfg_presumido.prestador, replace(cfg_presumido.servico, ibs_cbs=ibs), None, emissao)


# --- IRRF retido -----------------------------------------------------------------------------------


def _com_irrf(cfg, p_aliq="1.50"):
    return replace(cfg, servico=replace(cfg.servico, irrf=Irrf(p_aliq=Decimal(p_aliq))))


def test_irrf_retido_vem_depois_do_pis_cofins(cfg_presumido, cert, emissao):
    xml = gerar_dps(_com_irrf(cfg_presumido), cert, replace(emissao, valor=Decimal("1000")), None).xml
    validar_dps(xml, emissao.leiaute_efetivo)
    assert _ordem(xml, "n:infDPS/n:valores/n:trib/n:tribFed") == ["piscofins", "vRetIRRF"]
    assert etree.fromstring(xml).findtext(".//n:vRetIRRF", namespaces={"n": NS}) == "15.00"


def test_irrf_sem_pis_cofins_cria_o_grupo_federal(cfg, cert, emissao):
    xml = gerar_dps(_com_irrf(cfg), cert, emissao, None).xml
    validar_dps(xml, emissao.leiaute_efetivo)
    assert _ordem(xml, "n:infDPS/n:valores/n:trib/n:tribFed") == ["vRetIRRF"]


# Lei 9.430/1996, art. 67: dispensada a retenção de IR de valor igual ou inferior a R$ 10,00.
@pytest.mark.parametrize("valor, retido", [
    ("157.33", None),       # 2,36
    ("666.67", None),       # 10,00: igual ao mínimo, dispensado
    ("667.00", "10.01"),    # 10,005 arredonda para 10,01
    ("9000", "135.00"),
])
def test_irrf_dispensado_ate_dez_reais(cfg_presumido, cert, emissao, valor, retido):
    xml = gerar_dps(_com_irrf(cfg_presumido), cert, replace(emissao, valor=Decimal(valor)), None).xml
    assert etree.fromstring(xml).findtext(".//n:vRetIRRF", namespaces={"n": NS}) == retido


def test_irrf_dispensado_sem_pis_cofins_nao_deixa_grupo_vazio(cfg, cert, emissao):
    xml = gerar_dps(_com_irrf(cfg), cert, replace(emissao, valor=Decimal("100")), None).xml
    validar_dps(xml, emissao.leiaute_efetivo)
    assert etree.fromstring(xml).find(".//n:tribFed", namespaces={"n": NS}) is None
