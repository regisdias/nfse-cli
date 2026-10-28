"""Montagem da DPS (Declaração de Prestação de Serviço), leiaute 1.01.

A ordem dos elementos segue a sequência do XSD oficial (`esquemas/`).
Só cobre o caso de emissão pelo próprio prestador (tpEmit = 1), com
serviço prestado no Brasil; o resto do leiaute entra quando for preciso.

O leiaute continua se chamando "1.01", mas o conteúdo mudou com a NT 009:
cada pacote oficial de esquemas fica numa pasta com a data de publicação.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

NS = "http://www.sped.fazenda.gov.br/nfse"
VERSAO = "1.01"
FUSO_BRASILIA = timezone(timedelta(hours=-3))

PRODUCAO = 1
HOMOLOGACAO = 2

# Pacotes de esquemas (pasta em esquemas/), pela data de publicação.
LEIAUTE_ANTERIOR = "20260209"
"""Pacote 1.01 de 09/02/2026: o que a produção aceita até a virada da NT 009."""
LEIAUTE_NT009 = "20261020"
"""Pacote da produção restrita de 20/10/2026 (NT 009): finNFSe obrigatório
logo depois de tpEmit e cNBS antes de xDescServ."""
LEIAUTES = (LEIAUTE_ANTERIOR, LEIAUTE_NT009)

# Produção restrita já está na NT 009; a produção vira depois (data a confirmar
# no portal). Na virada, basta trocar a produção para LEIAUTE_NT009.
LEIAUTE_POR_AMBIENTE = {PRODUCAO: LEIAUTE_ANTERIOR, HOMOLOGACAO: LEIAUTE_NT009}


class DadosInvalidos(ValueError):
    pass


@dataclass(frozen=True)
class Endereco:
    cod_municipio: str
    cep: str
    logradouro: str
    numero: str
    bairro: str
    complemento: str | None = None


@dataclass(frozen=True)
class Prestador:
    cnpj: str
    cod_municipio: str
    """Código IBGE do município do prestador: vira cLocEmi."""
    op_simp_nac: int
    """1 não optante; 2 MEI; 3 ME/EPP."""
    reg_esp_trib: int = 0
    reg_ap_trib_sn: int | None = None
    """Só para ME/EPP (op_simp_nac = 3): 1 tudo pelo SN; 2 e 3 ISSQN fora do SN."""
    im: str | None = None
    """Só se o município tiver inscrição no CNC nacional; senão a DPS é rejeitada."""
    fone: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class TotTrib:
    """Valor aproximado dos tributos (Lei 12.741). Um dos quatro modos do leiaute.

    - ``sn``: percentual do Simples Nacional (``pTotTribSN``), só ME/EPP.
    - ``percentual``: (federal, estadual, municipal) em %.
    - ``valor``: (federal, estadual, municipal) em R$.
    - ``nao_informado``: ``indTotTrib = 0``; proibido para ME/EPP (E0712).
    """

    modo: str
    valores: tuple[Decimal, ...] = ()

    @classmethod
    def sn(cls, percentual: Decimal | str) -> "TotTrib":
        return cls("sn", (Decimal(percentual),))

    @classmethod
    def percentual(cls, fed: Decimal | str, est: Decimal | str, mun: Decimal | str) -> "TotTrib":
        return cls("percentual", (Decimal(fed), Decimal(est), Decimal(mun)))

    @classmethod
    def valor(cls, fed: Decimal | str, est: Decimal | str, mun: Decimal | str) -> "TotTrib":
        return cls("valor", (Decimal(fed), Decimal(est), Decimal(mun)))

    @classmethod
    def nao_informado(cls) -> "TotTrib":
        return cls("nao_informado")


@dataclass(frozen=True)
class PisCofins:
    """PIS/COFINS de apuração própria, sem retenção (empresa fora do Simples).

    Base = valor do serviço; vPis e vCofins saem das alíquotas (lucro presumido: 0,65 e 3,00;
    lucro real: 1,65 e 7,60).
    """

    p_aliq_pis: Decimal
    p_aliq_cofins: Decimal
    cst: str = "01"
    """01 tributável com alíquota básica; a tabela inteira está em TSTipoCST."""


@dataclass(frozen=True)
class IbsCbs:
    """Grupo IBS/CBS declarado pelo emitente (reforma tributária). A Sefin calcula base e valores."""

    cst: str
    """3 dígitos (000 = tributação integral)."""
    c_class_trib: str
    """6 dígitos (000001 = situações tributadas integralmente)."""
    c_ind_op: str
    """Código indicador da operação, 6 dígitos (tabela do anexo de IBS/CBS)."""
    ind_final: int | None = None
    """Uso ou consumo pessoal: 0 não, 1 sim. None não informa."""


@dataclass(frozen=True)
class Servico:
    c_trib_nac: str
    """Código de tributação nacional, 6 dígitos (17.01.01 -> 170101)."""
    cod_municipio_prestacao: str
    tot_trib: TotTrib
    c_nbs: str | None = None
    c_trib_mun: str | None = None
    trib_issqn: int = 1
    """1 operação tributável; 2 imunidade; 3 exportação; 4 não incidência."""
    tp_ret_issqn: int = 1
    """1 não retido; 2 retido pelo tomador; 3 retido pelo intermediário."""
    p_aliq: Decimal | None = None
    """Alíquota do ISSQN. ME/EPP no SN sem retenção não informa (E0625)."""
    pis_cofins: PisCofins | None = None
    ibs_cbs: IbsCbs | None = None


@dataclass(frozen=True)
class Tomador:
    documento: str
    """CPF (11) ou CNPJ (14), só dígitos."""
    nome: str
    email: str | None = None
    fone: str | None = None
    im: str | None = None
    endereco: Endereco | None = None


@dataclass(frozen=True)
class Emissao:
    ambiente: int
    serie: str
    numero: int
    valor: Decimal
    descricao: str
    competencia: date | None = None
    emitida_em: datetime | None = None
    info_complementar: str | None = None
    ver_aplic: str = "nfse-cli"
    leiaute: str | None = None
    """Pacote de esquemas (LEIAUTES); None usa o do ambiente (LEIAUTE_POR_AMBIENTE)."""

    @property
    def leiaute_efetivo(self) -> str:
        return self.leiaute or LEIAUTE_POR_AMBIENTE[self.ambiente]


# --- formatação ------------------------------------------------------------

# TSString: sem espaço nas pontas e só caracteres até U+00FF (Latin-1).
_FORA_DO_LATIN1 = re.compile(r"[^\n\r\t -ÿ]")


def texto(valor: str, campo: str, maximo: int, multilinha: bool = False) -> str:
    valor = valor.strip()
    if not valor:
        raise DadosInvalidos(f"{campo}: vazio")
    if len(valor) > maximo:
        raise DadosInvalidos(f"{campo}: {len(valor)} caracteres, máximo {maximo}")
    proibidos = sorted(set(_FORA_DO_LATIN1.findall(valor)))
    if proibidos:
        raise DadosInvalidos(
            f"{campo}: caracteres não aceitos pela Sefin: {' '.join(repr(c) for c in proibidos)}"
            " (troque travessões e aspas curvas por - e \")"
        )
    if not multilinha and re.search(r"[\n\r\t]", valor):
        raise DadosInvalidos(f"{campo}: não aceita quebra de linha")
    return valor


def digitos(valor: str, campo: str, tamanhos: tuple[int, ...]) -> str:
    so_digitos = re.sub(r"\D", "", valor)
    if len(so_digitos) not in tamanhos:
        raise DadosInvalidos(f"{campo}: esperado {' ou '.join(map(str, tamanhos))} dígitos, veio {valor!r}")
    return so_digitos


def dinheiro(valor: Decimal | str | int) -> str:
    q = Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if q < 0:
        raise DadosInvalidos(f"valor negativo: {valor}")
    return f"{q:.2f}"


def data_hora(dt: datetime) -> str:
    """AAAA-MM-DDThh:mm:ss-03:00: o XSD exige fuso e não aceita fração de segundo."""
    return dt.astimezone(FUSO_BRASILIA).replace(microsecond=0).isoformat()


# --- identificador ---------------------------------------------------------

def id_dps(cod_municipio: str, documento: str, serie: str, numero: int) -> str:
    """"DPS" + município (7) + tipo inscrição (1) + inscrição (14) + série (5) + número (15)."""
    documento = digitos(documento, "inscrição do emitente", (11, 14))
    tipo = "1" if len(documento) == 11 else "2"
    return (
        "DPS"
        + digitos(cod_municipio, "município emissor", (7,))
        + tipo
        + documento.zfill(14)
        + str(int(serie)).zfill(5)
        + str(numero).zfill(15)
    )


# --- XML -------------------------------------------------------------------

def _el(pai: etree._Element, nome: str, valor: str | None = None) -> etree._Element:
    filho = etree.SubElement(pai, f"{{{NS}}}{nome}")
    if valor is not None:
        filho.text = valor
    return filho


def _documento(pai: etree._Element, documento: str, campo: str) -> None:
    documento = digitos(documento, campo, (11, 14))
    _el(pai, "CPF" if len(documento) == 11 else "CNPJ", documento)


def montar_dps(prestador: Prestador, servico: Servico, tomador: Tomador | None, emissao: Emissao) -> etree._Element:
    """Monta o elemento <DPS> ainda sem assinatura."""
    if emissao.ambiente not in (PRODUCAO, HOMOLOGACAO):
        raise DadosInvalidos(f"ambiente inválido: {emissao.ambiente}")
    leiaute = emissao.leiaute_efetivo
    if leiaute not in LEIAUTES:
        raise DadosInvalidos(f"leiaute desconhecido: {leiaute} (conhecidos: {', '.join(LEIAUTES)})")
    if not 1 <= int(emissao.serie) <= 49999:
        raise DadosInvalidos("série de aplicativo próprio vai de 1 a 49999 (E0010)")
    if not 1 <= emissao.numero < 10**15:
        raise DadosInvalidos(f"número da DPS fora da faixa: {emissao.numero}")
    if Decimal(emissao.valor) <= 0:
        raise DadosInvalidos("valor do serviço precisa ser maior que zero")

    # Um minuto para trás: a Sefin rejeita dhEmi posterior ao processamento (E0008).
    emitida_em = emissao.emitida_em or (datetime.now(timezone.utc) - timedelta(minutes=1))
    competencia = emissao.competencia or emitida_em.astimezone(FUSO_BRASILIA).date()
    if competencia > emitida_em.astimezone(FUSO_BRASILIA).date():
        raise DadosInvalidos("competência não pode ser posterior à emissão (E0015)")

    dps = etree.Element(f"{{{NS}}}DPS", nsmap={None: NS})
    dps.set("versao", VERSAO)
    inf = _el(dps, "infDPS")
    inf.set("Id", id_dps(prestador.cod_municipio, prestador.cnpj, emissao.serie, emissao.numero))

    _el(inf, "tpAmb", str(emissao.ambiente))
    _el(inf, "dhEmi", data_hora(emitida_em))
    _el(inf, "verAplic", texto(emissao.ver_aplic, "verAplic", 20))
    _el(inf, "serie", str(int(emissao.serie)))
    _el(inf, "nDPS", str(emissao.numero))
    _el(inf, "dCompet", competencia.isoformat())
    _el(inf, "tpEmit", "1")
    if leiaute == LEIAUTE_NT009:
        _el(inf, "finNFSe", "0")  # NFS-e regular (1 e 2 são notas de ajuste de IBS/CBS)
    _el(inf, "cLocEmi", digitos(prestador.cod_municipio, "município do prestador", (7,)))

    # Prestador emitente: sem xNome (E0121) e sem endereço (vem do cadastro).
    prest = _el(inf, "prest")
    _documento(prest, prestador.cnpj, "CNPJ do prestador")
    if prestador.im:
        _el(prest, "IM", texto(prestador.im, "IM do prestador", 15))
    if prestador.fone:
        _el(prest, "fone", digitos(prestador.fone, "fone do prestador", tuple(range(6, 21))))
    if prestador.email:
        _el(prest, "email", texto(prestador.email, "email do prestador", 80))
    reg = _el(prest, "regTrib")
    _el(reg, "opSimpNac", str(prestador.op_simp_nac))
    if prestador.reg_ap_trib_sn is not None:
        if prestador.op_simp_nac != 3:
            raise DadosInvalidos("regApTribSN só existe para ME/EPP (opSimpNac = 3) (E0162)")
        _el(reg, "regApTribSN", str(prestador.reg_ap_trib_sn))
    _el(reg, "regEspTrib", str(prestador.reg_esp_trib))

    if tomador is not None:
        toma = _el(inf, "toma")
        _documento(toma, tomador.documento, "documento do tomador")
        if tomador.im:
            _el(toma, "IM", texto(tomador.im, "IM do tomador", 15))
        _el(toma, "xNome", texto(tomador.nome, "nome do tomador", 300))
        if tomador.endereco:
            e = tomador.endereco
            end = _el(toma, "end")
            nac = _el(end, "endNac")
            _el(nac, "cMun", digitos(e.cod_municipio, "município do tomador", (7,)))
            _el(nac, "CEP", digitos(e.cep, "CEP do tomador", (8,)))
            _el(end, "xLgr", texto(e.logradouro, "logradouro do tomador", 255))
            _el(end, "nro", texto(e.numero, "número do endereço do tomador", 60))
            if e.complemento:
                _el(end, "xCpl", texto(e.complemento, "complemento do tomador", 156))
            _el(end, "xBairro", texto(e.bairro, "bairro do tomador", 60))
        if tomador.fone:
            _el(toma, "fone", digitos(tomador.fone, "fone do tomador", tuple(range(6, 21))))
        if tomador.email:
            _el(toma, "email", texto(tomador.email, "email do tomador", 80))

    serv = _el(inf, "serv")
    loc = _el(serv, "locPrest")
    _el(loc, "cLocPrestacao", digitos(servico.cod_municipio_prestacao, "município da prestação", (7,)))
    cserv = _el(serv, "cServ")
    _el(cserv, "cTribNac", digitos(servico.c_trib_nac, "cTribNac", (6,)))
    if servico.c_trib_mun:
        _el(cserv, "cTribMun", digitos(servico.c_trib_mun, "cTribMun", (3,)))
    descricao = texto(emissao.descricao, "descrição do serviço", 2000, multilinha=True)
    if leiaute == LEIAUTE_ANTERIOR:
        _el(cserv, "xDescServ", descricao)
    if servico.c_nbs:
        _el(cserv, "cNBS", digitos(servico.c_nbs, "cNBS", (9,)))
    if leiaute == LEIAUTE_NT009:
        _el(cserv, "xDescServ", descricao)
    if emissao.info_complementar:
        compl = _el(serv, "infoCompl")
        _el(compl, "xInfComp", texto(emissao.info_complementar, "informação complementar", 2000))

    valores = _el(inf, "valores")
    vserv = _el(valores, "vServPrest")
    _el(vserv, "vServ", dinheiro(emissao.valor))
    trib = _el(valores, "trib")
    mun = _el(trib, "tribMun")
    _el(mun, "tribISSQN", str(servico.trib_issqn))
    _el(mun, "tpRetISSQN", str(servico.tp_ret_issqn))
    if servico.p_aliq is not None:
        _el(mun, "pAliq", dinheiro(servico.p_aliq))
    if servico.pis_cofins:
        _pis_cofins(_el(_el(trib, "tribFed"), "piscofins"), servico.pis_cofins, Decimal(emissao.valor))
    _tot_trib(_el(trib, "totTrib"), servico.tot_trib, prestador)
    if servico.ibs_cbs:
        _ibs_cbs(_el(inf, "IBSCBS"), servico.ibs_cbs, leiaute)

    return dps


def _pis_cofins(pc: etree._Element, t: PisCofins, base: Decimal) -> None:
    cst = digitos(t.cst, "CST do PIS/COFINS", (2,))
    _el(pc, "CST", cst)
    _el(pc, "vBCPisCofins", dinheiro(base))
    _el(pc, "pAliqPis", dinheiro(t.p_aliq_pis))
    _el(pc, "pAliqCofins", dinheiro(t.p_aliq_cofins))
    _el(pc, "vPis", dinheiro(base * Decimal(t.p_aliq_pis) / 100))
    _el(pc, "vCofins", dinheiro(base * Decimal(t.p_aliq_cofins) / 100))
    _el(pc, "tpRetPisCofins", "0")  # PIS/COFINS/CSLL não retidos


def _ibs_cbs(g: etree._Element, t: IbsCbs, leiaute: str) -> None:
    if leiaute == LEIAUTE_ANTERIOR:
        _el(g, "finNFSe", "0")  # na NT 009 subiu para o infDPS
    if t.ind_final is not None:
        if t.ind_final not in (0, 1):
            raise DadosInvalidos(f"indFinal do IBS/CBS: 0 ou 1, veio {t.ind_final}")
        _el(g, "indFinal", str(t.ind_final))
    _el(g, "cIndOp", digitos(t.c_ind_op, "cIndOp do IBS/CBS", (6,)))
    _el(g, "indDest", "0")  # destinatário é o próprio tomador
    trib = _el(_el(g, "valores"), "trib")
    sit = _el(trib, "gIBSCBS") if leiaute == LEIAUTE_ANTERIOR else trib  # NT 009 subiu CST e cClassTrib
    _el(sit, "CST", digitos(t.cst, "CST do IBS/CBS", (3,)))
    _el(sit, "cClassTrib", digitos(t.c_class_trib, "cClassTrib do IBS/CBS", (6,)))


def _tot_trib(tot: etree._Element, t: TotTrib, prestador: Prestador) -> None:
    if t.modo == "sn":
        if prestador.op_simp_nac != 3:
            raise DadosInvalidos("pTotTribSN só vale para ME/EPP (E0710/E0713)")
        _el(tot, "pTotTribSN", dinheiro(t.valores[0]))
    elif t.modo in ("percentual", "valor"):
        grupo, prefixo = ("pTotTrib", "pTotTrib") if t.modo == "percentual" else ("vTotTrib", "vTotTrib")
        g = _el(tot, grupo)
        for sufixo, v in zip(("Fed", "Est", "Mun"), t.valores):
            _el(g, prefixo + sufixo, dinheiro(v))
    elif t.modo == "nao_informado":
        if prestador.op_simp_nac == 3:
            raise DadosInvalidos("ME/EPP não pode usar indTotTrib (E0712)")
        _el(tot, "indTotTrib", "0")
    else:
        raise DadosInvalidos(f"modo de totTrib desconhecido: {t.modo}")


def serializar(elemento: etree._Element) -> bytes:
    """UTF-8, com declaração e sem indentação: depois de assinado, nem um byte muda."""
    return etree.tostring(elemento, xml_declaration=True, encoding="UTF-8")
