import re
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from lxml import etree

from nfse import (
    AssinaturaInvalida,
    DadosInvalidos,
    Endereco,
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
    validar_dps(dps.xml)
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
    validar_dps(gerar_dps(cfg, cert, emissao, replace(tomador, endereco=end)).xml)


def test_sem_tomador_passa_no_xsd(cfg, cert, emissao):
    validar_dps(gerar_dps(cfg, cert, emissao, None).xml)


@pytest.mark.parametrize("tot", [TotTrib.percentual("0", "0", "2"), TotTrib.valor("100", "0", "0")])
def test_outros_modos_de_tot_trib(cfg, cert, emissao, tot):
    validar_dps(gerar_dps(replace(cfg, servico=replace(cfg.servico, tot_trib=tot)), cert, emissao, None).xml)


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
