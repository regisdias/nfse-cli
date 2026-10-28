"""Nota modelo: tira de uma NFS-e já emitida a configuração para emitir as próximas.

`ler_nfse(xml)` devolve a configuração no formato de `config_de_dict`, o tomador no de `tomador_de_dict`, o
valor e a descrição, e a lista do que a nota usa e a biblioteca ainda não sabe emitir (`nao_suportado`).
`chaves_no_pdf(pdf)` acha a chave de acesso no texto de um DANFSe, para baixar o XML pela API.
"""

from __future__ import annotations

import base64
import re
import zlib
from dataclasses import dataclass, field

from lxml import etree

from .dps import NS
from .tabelas import municipio

# Folhas da DPS que a biblioteca sabe montar. O que aparecer fora daqui vai para `nao_suportado`.
SUPORTADOS = {
    "tpAmb", "dhEmi", "verAplic", "serie", "nDPS", "dCompet", "tpEmit", "finNFSe", "cLocEmi",
    "prest/CNPJ", "prest/IM", "prest/fone", "prest/email",
    "prest/regTrib/opSimpNac", "prest/regTrib/regApTribSN", "prest/regTrib/regEspTrib",
    "toma/CNPJ", "toma/CPF", "toma/IM", "toma/xNome", "toma/fone", "toma/email",
    "toma/end/endNac/cMun", "toma/end/endNac/CEP", "toma/end/xLgr", "toma/end/nro", "toma/end/xCpl",
    "toma/end/xBairro",
    "serv/locPrest/cLocPrestacao", "serv/cServ/cTribNac", "serv/cServ/cTribMun", "serv/cServ/xDescServ",
    "serv/cServ/cNBS", "serv/infoCompl/xInfComp",
    "valores/vServPrest/vServ",
    "valores/trib/tribMun/tribISSQN", "valores/trib/tribMun/tpRetISSQN", "valores/trib/tribMun/pAliq",
    "valores/trib/totTrib/pTotTribSN", "valores/trib/totTrib/indTotTrib",
    "valores/trib/totTrib/pTotTrib/pTotTribFed", "valores/trib/totTrib/pTotTrib/pTotTribEst",
    "valores/trib/totTrib/pTotTrib/pTotTribMun",
    "valores/trib/totTrib/vTotTrib/vTotTribFed", "valores/trib/totTrib/vTotTrib/vTotTribEst",
    "valores/trib/totTrib/vTotTrib/vTotTribMun",
    "valores/trib/tribFed/piscofins/CST", "valores/trib/tribFed/piscofins/vBCPisCofins",
    "valores/trib/tribFed/piscofins/pAliqPis", "valores/trib/tribFed/piscofins/pAliqCofins",
    "valores/trib/tribFed/piscofins/vPis", "valores/trib/tribFed/piscofins/vCofins",
    "valores/trib/tribFed/piscofins/tpRetPisCofins",
    "IBSCBS/finNFSe", "IBSCBS/indFinal", "IBSCBS/cIndOp", "IBSCBS/indDest",
    "IBSCBS/valores/trib/gIBSCBS/CST", "IBSCBS/valores/trib/gIBSCBS/cClassTrib",  # até a NT 009
    "IBSCBS/valores/trib/CST", "IBSCBS/valores/trib/cClassTrib",  # NT 009
}

# O Emissor Web informa PIS/COFINS mesmo sem nada a apurar: CST 00 e tpRetPisCofins 0 ("não retidos").
# A nota sai igual sem o grupo.
SEM_PIS_COFINS = {"valores/trib/tribFed/piscofins/CST": "00", "valores/trib/tribFed/piscofins/tpRetPisCofins": "0"}

# Prefixo do caminho -> o que é, em português, para a mensagem.
NOMES = [
    ("toma/NIF", "cliente no exterior"), ("toma/cNaoNIF", "cliente no exterior"),
    ("toma/end/endExt", "cliente no exterior"), ("interm", "intermediário do serviço"),
    ("serv/comExt", "comércio exterior"), ("serv/obra", "serviço de obra"), ("serv/atvEvento", "evento"),
    ("serv/explRod", "exploração de rodovia"), ("valores/vDescCondIncond", "desconto"),
    ("valores/vDedRed", "dedução da base de cálculo"), ("valores/trib/tribFed", "tributos federais (retenções)"),
    ("valores/trib/tribMun/BM", "benefício municipal"), ("valores/trib/tribMun/exigSusp", "ISS com exigibilidade suspensa"),
    ("valores/trib/tribMun/tpImunidade", "imunidade de ISS"), ("IBSCBS", "IBS/CBS"), ("subst", "nota substituta"),
]


@dataclass
class Modelo:
    chave: str | None
    numero_nfse: str | None
    emitida_em: str | None
    ambiente: int
    prestador_nome: str | None
    config: dict
    tomador: dict | None
    valor: str
    descricao: str
    competencia: str | None
    serie_dps: str
    numero_dps: int
    nao_suportado: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _sem_ns(el) -> str:
    return etree.QName(el).localname


def _folhas(raiz) -> dict[str, str]:
    """Caminho relativo (sem namespace) -> texto, para cada elemento com texto."""
    saida = {}

    def andar(el, caminho):
        filhos = [f for f in el if isinstance(f.tag, str)]
        if not filhos:
            saida[caminho] = (el.text or "").strip()
        for f in filhos:
            andar(f, f"{caminho}/{_sem_ns(f)}" if caminho else _sem_ns(f))

    andar(raiz, "")
    return saida


def _nome(caminho: str) -> str:
    for prefixo, nome in NOMES:
        if caminho == prefixo or caminho.startswith(prefixo + "/"):
            return nome
    return f"campo {caminho}"


def ler_nfse(xml: bytes) -> Modelo:
    raiz = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    inf_nfse = raiz.find(f"{{{NS}}}infNFSe") if _sem_ns(raiz) == "NFSe" else None
    inf_dps = raiz.find(f".//{{{NS}}}infDPS")
    if inf_dps is None:
        raise ValueError("não é uma NFS-e nem uma DPS (sem infDPS)")
    f = _folhas(inf_dps)
    g = (lambda c: f.get(c) or None)

    nao_suportado, avisos = [], []
    for caminho, valor in f.items():
        if caminho in SUPORTADOS:
            continue
        nome = _nome(caminho)
        if nome not in nao_suportado:
            nao_suportado.append(nome)
    if g("tpEmit") not in (None, "1"):
        nao_suportado.append("nota emitida pelo tomador ou intermediário")
    if g("prest/regTrib/opSimpNac") == "2":
        nao_suportado.append("MEI")
    if g("valores/trib/tribMun/tribISSQN") not in (None, "1"):
        nao_suportado.append("ISS não tributável (imunidade, exportação ou não incidência)")
    if g("valores/trib/tribMun/tpRetISSQN") not in (None, "1"):
        nao_suportado.append("ISS retido pelo tomador")
    pc = "valores/trib/tribFed/piscofins/"
    tem_pis_cofins = g(pc + "CST") not in (None, SEM_PIS_COFINS[pc + "CST"])
    if g(pc + "tpRetPisCofins") not in (None, "0"):
        nao_suportado.append("PIS/COFINS/CSLL retidos")
    if tem_pis_cofins and g(pc + "vBCPisCofins") not in (None, g("valores/vServPrest/vServ")):
        nao_suportado.append("base do PIS/COFINS diferente do valor do serviço")
    if g("IBSCBS/indDest") not in (None, "0"):
        nao_suportado.append("destinatário diferente do tomador (IBS/CBS)")
    if g("prest/regTrib/opSimpNac") == "1":
        avisos.append("empresa fora do Simples: a biblioteca monta a nota, mas esse regime ainda não foi testado em produção")
    if g("valores/trib/totTrib/vTotTrib/vTotTribFed"):
        avisos.append("tributos aproximados em valor (R$) fixo: se o valor da nota mudar, troque por percentual")

    prestador = {
        "cnpj": g("prest/CNPJ"),
        "cod_municipio": g("cLocEmi"),
        "op_simp_nac": int(g("prest/regTrib/opSimpNac") or 0),
        "reg_esp_trib": int(g("prest/regTrib/regEspTrib") or 0),
    }
    for chave, caminho in [("reg_ap_trib_sn", "prest/regTrib/regApTribSN")]:
        if g(caminho):
            prestador[chave] = int(g(caminho))
    for chave, caminho in [("im", "prest/IM"), ("fone", "prest/fone"), ("email", "prest/email")]:
        if g(caminho):
            prestador[chave] = g(caminho)

    servico = {"c_trib_nac": g("serv/cServ/cTribNac")}
    for chave, caminho in [("c_nbs", "serv/cServ/cNBS"), ("c_trib_mun", "serv/cServ/cTribMun")]:
        if g(caminho):
            servico[chave] = g(caminho)
    if g("serv/locPrest/cLocPrestacao") and g("serv/locPrest/cLocPrestacao") != prestador["cod_municipio"]:
        servico["cod_municipio_prestacao"] = g("serv/locPrest/cLocPrestacao")
    servico["trib_issqn"] = int(g("valores/trib/tribMun/tribISSQN") or 1)
    servico["tp_ret_issqn"] = int(g("valores/trib/tribMun/tpRetISSQN") or 1)
    if g("valores/trib/tribMun/pAliq"):
        servico["p_aliq"] = g("valores/trib/tribMun/pAliq")
    t = "valores/trib/totTrib/"
    if g(t + "pTotTribSN"):
        servico["tot_trib"] = {"modo": "sn", "percentual": g(t + "pTotTribSN")}
    elif g(t + "pTotTrib/pTotTribFed"):
        servico["tot_trib"] = {"modo": "percentual", **{k: g(f"{t}pTotTrib/pTotTrib{s}") for k, s in
                                                        (("federal", "Fed"), ("estadual", "Est"), ("municipal", "Mun"))}}
    elif g(t + "vTotTrib/vTotTribFed"):
        servico["tot_trib"] = {"modo": "valor", **{k: g(f"{t}vTotTrib/vTotTrib{s}") for k, s in
                                                   (("federal", "Fed"), ("estadual", "Est"), ("municipal", "Mun"))}}
    else:
        servico["tot_trib"] = {"modo": "nao_informado"}
    if tem_pis_cofins:
        servico["pis_cofins"] = {"cst": g(pc + "CST"), "p_aliq_pis": g(pc + "pAliqPis") or "0",
                                 "p_aliq_cofins": g(pc + "pAliqCofins") or "0"}
    ib = "IBSCBS/valores/trib/" if g("IBSCBS/valores/trib/CST") else "IBSCBS/valores/trib/gIBSCBS/"
    if g(ib + "CST"):
        servico["ibs_cbs"] = {"cst": g(ib + "CST"), "c_class_trib": g(ib + "cClassTrib"),
                              "c_ind_op": g("IBSCBS/cIndOp")}
        if g("IBSCBS/indFinal"):
            servico["ibs_cbs"]["ind_final"] = int(g("IBSCBS/indFinal"))

    tomador = None
    if g("toma/xNome"):
        tomador = {"documento": g("toma/CNPJ") or g("toma/CPF"), "nome": g("toma/xNome")}
        for chave, caminho in [("im", "toma/IM"), ("fone", "toma/fone"), ("email", "toma/email")]:
            if g(caminho):
                tomador[chave] = g(caminho)
        if g("toma/end/endNac/cMun"):
            end = {"cod_municipio": g("toma/end/endNac/cMun"), "cep": g("toma/end/endNac/CEP"),
                   "logradouro": g("toma/end/xLgr"), "numero": g("toma/end/nro"), "bairro": g("toma/end/xBairro")}
            if g("toma/end/xCpl"):
                end["complemento"] = g("toma/end/xCpl")
            tomador["endereco"] = end

    def nfse(campo):
        return inf_nfse.findtext(f"{{{NS}}}{campo}") if inf_nfse is not None else None

    id_nfse = inf_nfse.get("Id") if inf_nfse is not None else None
    return Modelo(
        chave=id_nfse[3:] if id_nfse and id_nfse.startswith("NFS") else None,
        numero_nfse=nfse("nNFSe"),
        emitida_em=nfse("dhProc") or g("dhEmi"),
        ambiente=int(g("tpAmb") or 2),
        prestador_nome=inf_nfse.findtext(f"{{{NS}}}emit/{{{NS}}}xNome") if inf_nfse is not None else None,
        config={"prestador": prestador, "servico": servico},
        tomador=tomador,
        valor=g("valores/vServPrest/vServ") or "",
        descricao=g("serv/cServ/xDescServ") or "",
        competencia=g("dCompet"),
        serie_dps=g("serie") or "",
        numero_dps=int(g("nDPS") or 0),
        nao_suportado=nao_suportado,
        avisos=avisos,
    )


# --- chave de acesso dentro de um PDF ---------------------------------------------

def _fluxos(pdf: bytes):
    """Conteúdo descomprimido de cada stream do PDF (FlateDecode, com ou sem ASCII85 antes)."""
    for m in re.finditer(rb"stream\r?\n", pdf):
        dados = pdf[m.end():pdf.find(b"endstream", m.end())]
        candidatos = [dados]
        if dados.lstrip()[:2] != b"x\x9c" and b"~>" in dados:
            try:
                candidatos.insert(0, base64.a85decode(dados.strip(), adobe=True))
            except ValueError:
                pass
        for bruto in candidatos:
            try:
                yield zlib.decompressobj().decompress(bruto)
                break
            except zlib.error:
                continue


def chave_valida(chave: str) -> bool:
    """50 dígitos: município IBGE (7), ambiente (1), tipo de inscrição (1), CNPJ/CPF (14), número (13)..."""
    return (len(chave) == 50 and chave.isdigit() and municipio(chave[:7]) is not None
            and chave[7] in "12" and chave[8] in "12")


def chaves_no_pdf(pdf: bytes) -> list[str]:
    """Chaves de acesso no texto do DANFSe, na ordem em que aparecem (sem repetir)."""
    if not pdf.startswith(b"%PDF"):
        raise ValueError("não é um PDF")
    achadas: list[str] = []
    for conteudo in _fluxos(pdf):
        if b"T" not in conteudo:
            continue
        textos = re.findall(rb"\(((?:\\.|[^\\)])*)\)", conteudo)
        for candidato in [b"".join(textos)] + textos:
            digitos = re.sub(rb"[^0-9]", b"", candidato).decode()
            for m in re.finditer(r"(?=(\d{50}))", digitos):
                if chave_valida(m.group(1)) and m.group(1) not in achadas:
                    achadas.append(m.group(1))
    return achadas


def cnpj_da_chave(chave: str) -> str:
    return chave[9:23]
