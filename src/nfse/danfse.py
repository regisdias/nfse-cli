"""DANFSe v2.0 (Documento Auxiliar da NFS-e) gerado a partir do XML da nota.

Segue a Nota Técnica SE/CGNFS-e nº 008 (v1.02, 14/07/2026): a API de DANFSe do
ADN foi suspensa em 03/08/2026 e o PDF passou a ser gerado pelo software de
emissão. O documento fiscal é o XML; o DANFSe só o representa, então nada aqui
pode aparecer se não estiver no XML.

Medidas em centímetros, a partir do canto superior esquerdo da folha A4, como
na tabela do item 2.4.5 da NT. Blocos sem dados encolhem (notas 2 a 5) e a
sobra vai para "Informações Complementares", como a NT permite.

Precisa do extra `danfse` (reportlab): `pip install 'nfse-cli[danfse]'`.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lxml import etree

from .dps import NS
from .tabelas import municipio

RECURSOS = Path(__file__).parent / "danfse_recursos"
URL_CONSULTA = "https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave="

# Domínios do leiaute (Anexo VI), na redação que o DANFSe exibe.
TP_EMIT = {"1": "Prestador", "2": "Tomador", "3": "Intermediário"}
C_STAT = {
    "100": "NFS-e Gerada",
    "101": "NFS-e de Substituição Gerada",
    "102": "NFS-e de Decisão Judicial ou Administrativa",
    "103": "NFS-e Avulsa",
    "107": "NFS-e MEI",
}
FIN_NFSE = {"0": "NFS-e regular", "1": "NFS-e de crédito", "2": "NFS-e de débito"}
OP_SIMP_NAC = {
    "1": "Não Optante",
    "2": "Optante - Microempreendedor Individual (MEI)",
    "3": "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)",
    "4": "Optante Pendente",
}
REG_AP_TRIB_SN = {
    "1": "Regime de apuração dos tributos federais e municipal pelo Simples Nacional",
    "2": "Regime de apuração dos tributos federais pelo Simples Nacional e o ISSQN pela NFS-e "
         "conforme respectiva legislação municipal do tributo",
    "3": "Regime de apuração dos tributos federais e municipal pela NFS-e conforme respectivas "
         "legislações federal e municipal de cada tributo",
}
REG_ESP_TRIB = {
    "1": "Ato Cooperado (Cooperativa)", "2": "Estimativa", "3": "Microempresa Municipal",
    "4": "Notário ou Registrador", "5": "Profissional Autônomo", "6": "Sociedade de Profissionais",
    "9": "Outros",
}
TRIB_ISSQN = {"1": "Operação Tributável", "2": "Imunidade", "3": "Exportação de Serviço", "4": "Não Incidência"}
TP_IMUNIDADE = {
    "0": "Imunidade (tipo não informado na nota de origem)",
    "1": "Patrimônio, renda ou serviços, uns dos outros (CF88, Art 150, VI, a)",
    "2": "Entidades religiosas e templos de qualquer culto (CF88, Art 150, VI, b)",
    "3": "Partidos políticos, sindicatos, educação e assistência social (CF88, Art 150, VI, c)",
    "4": "Livros, jornais, periódicos e o papel destinado a sua impressão (CF88, Art 150, VI, d)",
    "5": "Fonogramas e videofonogramas musicais produzidos no Brasil (CF88, Art 150, VI, e)",
}
TP_SUSP = {
    "1": "Exigibilidade Suspensa por Decisão Judicial",
    "2": "Exigibilidade Suspensa por Processo Administrativo",
}
TP_BM = {"1": "Isenção", "2": "Redução da BC (percentual)", "3": "Redução da BC (valor)", "4": "Alíquota Diferenciada"}
TP_RET_ISSQN = {"1": "Não Retido", "2": "Retido pelo Tomador", "3": "Retido pelo Intermediário"}
TP_RET_PIS_COFINS = {
    "0": "PIS/COFINS/CSLL Não Retidos", "1": "PIS/COFINS Retido", "2": "PIS/COFINS Não Retido",
    "3": "PIS/COFINS/CSLL Retidos", "4": "PIS/COFINS Retidos, CSLL Não Retido",
    "5": "PIS Retido, COFINS/CSLL Não Retido", "6": "COFINS Retido, PIS/CSLL Não Retido",
    "7": "PIS Não Retido, COFINS/CSLL Retidos", "8": "PIS/COFINS Não Retidos, CSLL Retido",
    "9": "COFINS Não Retido, PIS/CSLL Retidos",
}

# Geometria (item 2.4.5): quatro colunas de 5,09 cm dentro da largura útil de 20,40 cm.
ESQ, LARGURA = 0.30, 20.40
COLUNAS = (0.30, 5.41, 10.51, 15.62)
COL = 5.09
LINHA = 0.63            # altura padrão de linha nos blocos
LINHA_VALORES = 0.67    # bloco "Valor Total da NFS-e" e canhoto
LINHA_AVISO = 0.32      # bloco suprimido ("... NÃO IDENTIFICADO NA NFS-e")
TOPO_CANHOTO = 28.10
FOLHA_ALT = 29.7
CINZA = 0.95            # 5% de densidade


class DanfseIndisponivel(RuntimeError):
    """Falta o reportlab (extra `danfse`)."""


# --- leitura do XML -----------------------------------------------------------

class _Nota:
    """Acesso aos campos da NFS-e por caminho relativo a infNFSe (ex.: 'DPS/infDPS/toma/CNPJ')."""

    def __init__(self, xml: bytes):
        raiz = etree.fromstring(xml)
        self.inf = raiz.find(f"{{{NS}}}infNFSe")
        if self.inf is None:
            raise ValueError("o XML não é de uma NFS-e (falta infNFSe)")

    def no(self, caminho: str):
        return self.inf.find("/".join(f"{{{NS}}}{p}" for p in caminho.split("/")))

    def __call__(self, caminho: str) -> str | None:
        el = self.no(caminho)
        return el.text.strip() if el is not None and el.text and el.text.strip() else None


# --- formatação ----------------------------------------------------------------

TRACO = "-"


def _doc(cnpj: str | None, cpf: str | None, nif: str | None) -> str:
    if cnpj:
        return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
    if cpf:
        return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
    return nif or TRACO


def _fone(f: str | None) -> str:
    if not f or not f.isdigit() or len(f) not in (10, 11):
        return f or TRACO
    return f"({f[:2]}) {f[2:-4]}-{f[-4:]}"


def _cep(c: str | None) -> str:
    return f"{c[:2]}.{c[2:5]}-{c[5:]}" if c and len(c) == 8 else (c or TRACO)


def _dinheiro(v: str | Decimal | None) -> str:
    if v is None:
        return TRACO
    texto = f"{Decimal(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _pct(v: str | None) -> str:
    return f"{Decimal(v):.2f}".replace(".", ",") + " %" if v else TRACO


def _data(d: str | None) -> str:
    return date.fromisoformat(d).strftime("%d/%m/%Y") if d else TRACO


def _data_hora(dh: str | None) -> str:
    # Mostra a hora como veio (já no fuso do emitente), sem converter.
    return datetime.fromisoformat(dh).strftime("%d/%m/%Y %H:%M:%S") if dh else TRACO


def _soma(*valores: str | None) -> Decimal:
    return sum((Decimal(v) for v in valores if v), Decimal(0))


def _juntar(*partes: str | None, sep: str = " / ") -> str:
    return sep.join(p if p else TRACO for p in partes)


# --- desenho -------------------------------------------------------------------

class _Folha:
    def __init__(self, canvas):
        from reportlab.lib.units import cm
        from reportlab.pdfbase.pdfmetrics import stringWidth

        self.c = canvas
        self.cm = cm
        self.largura_texto = stringWidth

    def y(self, topo: float) -> float:
        return (FOLHA_ALT - topo) * self.cm

    def caber(self, texto: str, fonte: str, tamanho: float, largura_cm: float) -> str:
        """Corta com reticências o que não cabe na largura do campo (item 2.4.5)."""
        limite = largura_cm * self.cm - 4
        if self.largura_texto(texto, fonte, tamanho) <= limite:
            return texto
        while texto and self.largura_texto(texto + "...", fonte, tamanho) > limite:
            texto = texto[:-1]
        return texto.rstrip() + "..."

    def texto(self, x: float, topo: float, texto: str, fonte="Helvetica", tamanho=7.0, largura: float | None = None,
              cor=(0, 0, 0), centro: bool = False) -> None:
        self.c.setFont(fonte, tamanho)
        self.c.setFillColorRGB(*cor)
        if largura:
            texto = self.caber(texto, fonte, tamanho, largura)
        base = self.y(topo) - tamanho  # topo da caixa -> linha de base
        if centro:
            self.c.drawCentredString((x + (largura or 0) / 2) * self.cm, base, texto)
        else:
            self.c.drawString(x * self.cm + 2, base, texto)

    def fundo(self, x: float, topo: float, largura: float, altura: float) -> None:
        self.c.setFillGray(CINZA)
        self.c.rect(x * self.cm, self.y(topo + altura), largura * self.cm, altura * self.cm, stroke=0, fill=1)
        self.c.setFillGray(0)

    def linha(self, topo: float) -> None:
        self.c.setLineWidth(0.5)
        self.c.line(ESQ * self.cm, self.y(topo), (ESQ + LARGURA) * self.cm, self.y(topo))

    def campo(self, x: float, topo: float, rotulo: str, valor: str | None, largura: float = COL,
              rotulo_tam: float = 6.0) -> None:
        self.texto(x, topo + 0.06, rotulo, "Helvetica-Bold", rotulo_tam, largura)
        self.texto(x, topo + 0.06 + rotulo_tam / 28.35 + 0.02, valor or TRACO, "Helvetica", 7.0, largura)

    def titulo_bloco(self, topo: float, titulo: str, altura: float = LINHA) -> None:
        self.fundo(ESQ, topo, COL, altura)
        self.texto(ESQ, topo + 0.08, titulo, "Helvetica-Bold", 7.0, COL)

    def aviso(self, topo: float, texto: str) -> float:
        self.texto(ESQ, topo + 0.03, texto, "Helvetica", 7.0, LARGURA, centro=True)
        self.linha(topo + LINHA_AVISO)
        return topo + LINHA_AVISO

    def paragrafo(self, x: float, topo: float, texto: str, largura: float, tamanho: float = 7.0) -> float:
        """Texto com quebra de linha; devolve a altura usada (cm)."""
        from reportlab.lib.utils import simpleSplit

        linhas: list[str] = []
        for trecho in texto.splitlines() or [""]:
            linhas += simpleSplit(trecho, "Helvetica", tamanho, largura * self.cm - 4) or [""]
        passo = tamanho * 1.18 / self.cm
        for i, l in enumerate(linhas):
            self.texto(x, topo + i * passo, l, "Helvetica", tamanho)
        return len(linhas) * passo


def _pessoa(f: _Folha, n: _Nota, topo: float, base: str, titulo: str, nao_identificado: str, tem_im: bool = True) -> float:
    """Blocos prestador, tomador, destinatário e intermediário (itens 2.1.3 a 2.1.6)."""
    if n.no(base) is None:
        return f.aviso(topo, nao_identificado)

    f.titulo_bloco(topo, titulo)
    f.campo(COLUNAS[1], topo, "CNPJ / CPF / NIF", _doc(n(f"{base}/CNPJ"), n(f"{base}/CPF"), n(f"{base}/NIF")))
    if tem_im:
        f.campo(COLUNAS[2], topo, "Indicador Municipal (Inscrição)", n(f"{base}/IM"))
    f.campo(COLUNAS[3], topo, "Telefone", _fone(n(f"{base}/fone")))

    # Prestador emitente não manda nome nem endereço na DPS: vêm de infNFSe/emit.
    eh_emitente = base == "DPS/infDPS/prest" and n(f"{base}/xNome") is None
    origem = "emit" if eh_emitente else base
    end = "emit/enderNac" if eh_emitente else f"{base}/end"
    cmun = n(f"{end}/cMun") or n(f"{end}/endNac/cMun")
    cep = n(f"{end}/CEP") or n(f"{end}/endNac/CEP")
    mun = municipio(cmun)
    if n(f"{end}/endExt/xCidade"):
        local, codigo_cep = n(f"{end}/endExt/xCidade"), _juntar(TRACO, n(f"{end}/endExt/cEndPost"))
    else:
        local = f"{mun[0]} / {mun[1]}" if mun else TRACO
        codigo_cep = _juntar(cmun, _cep(cep) if cep else None)
    endereco = ", ".join(p for p in (n(f"{end}/xLgr"), n(f"{end}/nro"), n(f"{end}/xCpl"), n(f"{end}/xBairro")) if p)

    l2 = topo + LINHA
    f.campo(COLUNAS[0], l2, "Nome / Nome Empresarial", n(f"{origem}/xNome") or n(f"{base}/xNome"), 2 * COL + 0.01)
    f.campo(COLUNAS[2], l2, "Município / Sigla UF", local)
    f.campo(COLUNAS[3], l2, "Código IBGE / CEP", codigo_cep)
    l3 = l2 + LINHA
    f.campo(COLUNAS[0], l3, "Endereço", endereco or None, 2 * COL + 0.01)
    f.campo(COLUNAS[2], l3, "E-mail", n(f"{origem}/email") or n(f"{base}/email"), 2 * COL + 0.01)
    fim = l3 + LINHA
    if base == "DPS/infDPS/prest":
        f.campo(COLUNAS[0], fim, "Simples Nacional na Data de Competência",
                OP_SIMP_NAC.get(n(f"{base}/regTrib/opSimpNac") or "", None))
        f.campo(COLUNAS[2], fim, "Regime de Apuração Tributária pelo SN",
                REG_AP_TRIB_SN.get(n(f"{base}/regTrib/regApTribSN") or "", None), 2 * COL + 0.01)
        fim += LINHA
    f.linha(fim)
    return fim


def _desenhar(f: _Folha, n: _Nota) -> None:
    c = f.c
    homologacao = n("DPS/infDPS/tpAmb") == "2"
    chave = (n.inf.get("Id") or "").removeprefix("NFS")

    # Borda de 1 ponto em volta de tudo (item 2.2.3).
    c.setLineWidth(1)
    c.rect(ESQ * f.cm, f.y(TOPO_CANHOTO + LINHA_VALORES + 0.6), LARGURA * f.cm,
           (TOPO_CANHOTO + LINHA_VALORES + 0.3) * f.cm, stroke=1, fill=0)

    # Cabeçalho (2.4.3)
    f.fundo(ESQ, 0.30, LARGURA, 1.16)
    c.drawImage(str(RECURSOS / "logo-nfse.png"), 0.49 * f.cm, f.y(0.44 + 0.85), 4.0 * f.cm, 0.85 * f.cm,
                mask="auto", preserveAspectRatio=True, anchor="w")
    f.texto(5.41, 0.42, "DANFSe v2.0", "Helvetica-Bold", 9, 10.19, centro=True)
    f.texto(5.41, 0.80, "Documento Auxiliar da NFS-e", "Helvetica-Bold", 9, 10.19, centro=True)
    if homologacao:
        f.texto(5.41, 1.12, "NFS-e SEM VALIDADE JURÍDICA", "Helvetica-Bold", 9, 10.19, cor=(1, 0, 0), centro=True)
    if (n("DPS/infDPS/serv/cServ/cTribNac") or "")[:2] != "99":
        uf = n("emit/enderNac/UF") or (municipio(n("DPS/infDPS/cLocEmi")) or ("", ""))[1]
        f.texto(15.62, 0.34, f"Município: {n('xLocEmi') or TRACO} - {uf or TRACO}", "Helvetica", 8, 5.09)
    f.texto(15.62, 0.80, f"Ambiente Gerador: {n('ambGer') or TRACO}", "Helvetica", 6, 5.09)
    f.texto(15.62, 1.05, f"Tipo de Ambiente: {n('DPS/infDPS/tpAmb') or TRACO}", "Helvetica", 6, 5.09)
    f.linha(1.46)

    # Dados da NFS-e (2.1.2): rótulos em 7 pt, caixa alta.
    f.campo(ESQ, 1.48, "CHAVE DE ACESSO DA NFS-e", chave, 15.30, rotulo_tam=7)
    linhas = [
        (2.27, [("NÚMERO DA NFS-e", n("nNFSe")), ("COMPETÊNCIA DA NFS-e", _data(n("DPS/infDPS/dCompet"))),
                ("DATA E HORA DA EMISSÃO DA NFS-e", _data_hora(n("dhProc")))]),
        (2.96, [("NÚMERO DA DPS", n("DPS/infDPS/nDPS")), ("SÉRIE DA DPS", n("DPS/infDPS/serie")),
                ("DATA E HORA DA EMISSÃO DA DPS", _data_hora(n("DPS/infDPS/dhEmi")))]),
        (3.65, [("EMITENTE DA NFS-e", TP_EMIT.get(n("DPS/infDPS/tpEmit") or "")),
                ("SITUAÇÃO DA NFS-e", C_STAT.get(n("cStat") or "", n("cStat"))),
                ("FINALIDADE", FIN_NFSE.get(n("DPS/infDPS/finNFSe") or n("DPS/infDPS/IBSCBS/finNFSe") or ""))]),
    ]
    f.fundo(ESQ, 3.65, COL, 0.67)
    for topo, campos in linhas:
        for x, (rotulo, valor) in zip(COLUNAS, campos):
            f.campo(x, topo, rotulo, valor, rotulo_tam=7)

    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    qr = QrCodeWidget(URL_CONSULTA + chave, barBorder=0)
    x0, y0, x1, y1 = qr.getBounds()
    lado = 1.52 * f.cm
    desenho = Drawing(lado, lado, transform=[lado / (x1 - x0), 0, 0, lado / (y1 - y0), 0, 0])
    desenho.add(qr)
    renderPDF.draw(desenho, c, 17.48 * f.cm, f.y(1.67 + 1.52))
    for i, l in enumerate(("A autenticidade desta NFS-e pode ser verificada",
                           "pela leitura deste código QR ou pela consulta da",
                           "chave de acesso no portal nacional da NFS-e")):
        f.texto(15.80, 3.36 + i * 0.23, l, "Helvetica", 6, 4.9)
    f.linha(4.32)

    # Pessoas
    topo = _pessoa(f, n, 4.34, "DPS/infDPS/prest", "PRESTADOR / FORNECEDOR", "")
    topo = _pessoa(f, n, topo, "DPS/infDPS/toma", "TOMADOR / ADQUIRENTE",
                   "TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")
    topo = _pessoa(f, n, topo, "DPS/infDPS/IBSCBS/dest", "DESTINATÁRIO DA OPERAÇÃO",
                   "DESTINATÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e", tem_im=False)
    topo = _pessoa(f, n, topo, "DPS/infDPS/interm", "INTERMEDIÁRIO DA OPERAÇÃO",
                   "INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")

    # Serviço prestado (2.1.7)
    serv = "DPS/infDPS/serv"
    ctn = n(f"{serv}/cServ/cTribNac") or ""
    nbs = n(f"{serv}/cServ/cNBS") or ""
    f.titulo_bloco(topo, "SERVIÇO PRESTADO")
    f.campo(COLUNAS[1], topo, "Código de Tributação Nacional/Municipal",
            _juntar(f"{ctn[:2]}.{ctn[2:4]}.{ctn[4:]}" if len(ctn) == 6 else ctn or None, n(f"{serv}/cServ/cTribMun")))
    f.campo(COLUNAS[2], topo, "Código da NBS", f"{nbs[0]}.{nbs[1:5]}.{nbs[5:7]}.{nbs[7:]}" if len(nbs) == 9 else nbs or None)
    mun_prest = municipio(n(f"{serv}/locPrest/cLocPrestacao"))
    f.campo(COLUNAS[3], topo, "Local da Prestação / Sigla UF / País",
            _juntar(n("xLocPrestacao"), mun_prest[1] if mun_prest else None, n(f"{serv}/locPrest/cPaisPrestacao")))
    topo += LINHA
    f.texto(ESQ, topo + 0.05, n("xTribMun") or n("xTribNac") or TRACO, "Helvetica", 7, LARGURA)
    topo += 0.38
    f.texto(ESQ, topo + 0.04, "Descrição do Serviço", "Helvetica-Bold", 6, LARGURA)
    topo += 0.04 + 6 / 28.35 + 0.02
    descricao = n(f"{serv}/cServ/xDescServ") or TRACO
    if len(descricao) > 1300:
        descricao = descricao[:1297] + "..."
    topo += max(f.paragrafo(ESQ, topo, descricao, LARGURA), 0.30) + 0.08
    f.linha(topo)

    # Tributação municipal (2.1.8)
    tm = "DPS/infDPS/valores/trib/tribMun"
    f.titulo_bloco(topo, "TRIBUTAÇÃO MUNICIPAL (ISSQN)")
    f.campo(COLUNAS[1], topo, "Tipo de Tributação do ISSQN", TRIB_ISSQN.get(n(f"{tm}/tribISSQN") or ""))
    mun_inc = municipio(n("cLocIncid"))
    f.campo(COLUNAS[2], topo, "Município / Sigla UF / País de Incidência do ISSQN",
            _juntar(n("xLocIncid"), mun_inc[1] if mun_inc else None, n(f"{tm}/cPaisResult")), 2 * COL + 0.01)
    topo += LINHA
    reg_esp = n("DPS/infDPS/prest/regTrib/regEspTrib")
    linha_regime = [REG_ESP_TRIB.get(reg_esp or ""), TP_IMUNIDADE.get(n(f"{tm}/tpImunidade") or ""),
                    TP_SUSP.get(n(f"{tm}/exigSusp/tpSusp") or ""), n(f"{tm}/exigSusp/nProcesso")]
    if any(linha_regime):  # nota 5: linha some quando não há dado nenhum
        for x, rotulo, valor in zip(COLUNAS, ("Regime Especial de Tributação do ISSQN", "Tipo de Imunidade do ISSQN",
                                              "Suspensão da Exigibilidade do ISSQN", "Número Processo Suspensão"),
                                    linha_regime):
            f.campo(x, topo, rotulo, valor)
        topo += LINHA
    v = "DPS/infDPS/valores"
    linha_bm = [TP_BM.get(n("valores/tpBM") or ""), n("valores/vCalcBM") or n(f"{tm}/BM/vRedBCBM"),
                n(f"{v}/vDedRed/vDR") or n("valores/vCalcDR"), n(f"{v}/vDescCondIncond/vDescIncond")]
    if any(linha_bm):
        for x, rotulo, valor in zip(COLUNAS, ("Benefício Municipal", "Cálculo do BM", "Total Deduções/Reduções",
                                              "Desconto Incondicionado"),
                                    [linha_bm[0]] + [_dinheiro(x) for x in linha_bm[1:]]):
            f.campo(x, topo, rotulo, valor)
        topo += LINHA
    f.campo(COLUNAS[0], topo, "BC ISSQN", _dinheiro(n("valores/vBC")))
    f.campo(COLUNAS[1], topo, "Alíquota Aplicada", _pct(n("valores/pAliqAplic")))
    f.campo(COLUNAS[2], topo, "Retenção do ISSQN", TP_RET_ISSQN.get(n(f"{tm}/tpRetISSQN") or ""))
    f.campo(COLUNAS[3], topo, "ISSQN Apurado", _dinheiro(n("valores/vISSQN")))
    topo += LINHA
    f.linha(topo)

    # Tributação federal (2.1.9)
    tf = "DPS/infDPS/valores/trib/tribFed"
    pc = f"{tf}/piscofins"
    ret_pc = n(f"{pc}/tpRetPisCofins")
    f.titulo_bloco(topo, "TRIBUTAÇÃO FEDERAL (EXCETO CBS)")
    f.campo(COLUNAS[1], topo, "IRRF", _dinheiro(n(f"{tf}/vRetIRRF")))
    f.campo(COLUNAS[2], topo, "Contribuição Previdenciária - Retida", _dinheiro(n(f"{tf}/vRetCP")))
    sociais = _soma(n(f"{tf}/vRetCSLL"), n(f"{pc}/vPis"), n(f"{pc}/vCofins")) if ret_pc == "1" else n(f"{tf}/vRetCSLL")
    f.campo(COLUNAS[3], topo, "Contribuições Sociais - Retidas", _dinheiro(sociais))
    topo += LINHA
    compet = n("DPS/infDPS/dCompet") or "2026"
    if compet[:4] <= "2026":  # nota 6
        f.campo(COLUNAS[0], topo, "PIS - Débito Apuração Própria",
                _dinheiro("0" if ret_pc == "1" else n(f"{pc}/vPis")))
        f.campo(COLUNAS[1], topo, "COFINS - Débito Apuração Própria",
                _dinheiro("0" if ret_pc == "1" else n(f"{pc}/vCofins")))
        f.campo(COLUNAS[2], topo, "Descrição Contrib. Sociais - Retidas",
                f"{ret_pc} - {TP_RET_PIS_COFINS[ret_pc]}" if ret_pc in TP_RET_PIS_COFINS else None, 2 * COL + 0.01)
        topo += LINHA
    f.linha(topo)

    # IBS/CBS (2.1.10)
    ib = "IBSCBS"
    gib = "DPS/infDPS/IBSCBS/valores/trib/gIBSCBS"
    f.titulo_bloco(topo, "TRIBUTAÇÃO IBS/CBS")
    f.campo(COLUNAS[1], topo, "CST / cClassTrib", _juntar(n(f"{gib}/CST"), n(f"{gib}/cClassTrib")))
    mun_ibs = municipio(n(f"{ib}/cLocalidadeIncid"))
    f.campo(COLUNAS[2], topo, "Indicador de Operação / Código IBGE Incidência / Município Incidência / Sigla UF",
            _juntar(n("DPS/infDPS/IBSCBS/cIndOp"), n(f"{ib}/cLocalidadeIncid"), n(f"{ib}/xLocalidadeIncid"),
                    mun_ibs[1] if mun_ibs else None), 2 * COL + 0.01)
    topo += LINHA
    exclusoes = _soma(n(f"{v}/vDescCondIncond/vDescIncond"), n(f"{ib}/valores/vCalcReeRepRes"),
                      n("valores/vISSQN"), n(f"{pc}/vPis"), n(f"{pc}/vCofins"))
    grade = [
        [("Exclusões e Reduções da Base de Cálculo", _dinheiro(exclusoes)),
         ("Base de Cálculo Após Exclusões e Reduções", _dinheiro(n(f"{ib}/valores/vBC"))),
         ("Red. Alíquota IBS / Red. Alíquota CBS", _juntar(n(f"{ib}/valores/uf/pRedAliqUF"),
                                                            n(f"{ib}/valores/mun/pRedAliqMun"),
                                                            n(f"{ib}/valores/fed/pRedAliqCBS"))),
         ("Alíquota - IBS UF / IBS Mun", _juntar(n(f"{ib}/valores/uf/pIBSUF"), n(f"{ib}/valores/mun/pIBSMun")))],
        [("Alíq. Efetiva Municipal - IBS", _pct(n(f"{ib}/valores/mun/pAliqEfetMun"))),
         ("Valor Apurado Municipal - IBS", _dinheiro(n(f"{ib}/totCIBS/gIBS/gIBSMunTot/vIBSMun"))),
         ("Alíq. Efetiva Estadual - IBS", _pct(n(f"{ib}/valores/uf/pAliqEfetUF"))),
         ("Valor Apurado Estadual - IBS", _dinheiro(n(f"{ib}/totCIBS/gIBS/gIBSUFTot/vIBSUF")))],
        [("Valor Total Apurado - IBS", _dinheiro(n(f"{ib}/totCIBS/gIBS/vIBSTot"))),
         ("Alíquota - CBS", _pct(n(f"{ib}/valores/fed/pCBS"))),
         ("Alíquota Efetiva - CBS", _pct(n(f"{ib}/valores/fed/pAliqEfetCBS"))),
         ("Valor Total Apurado - CBS", _dinheiro(n(f"{ib}/totCIBS/gCBS/vCBS")))],
    ]
    for linha in grade:
        for x, (rotulo, valor) in zip(COLUNAS, linha):
            f.campo(x, topo, rotulo, valor)
        topo += LINHA
    f.linha(topo)

    # Valor total (2.1.11)
    f.titulo_bloco(topo, "VALOR TOTAL DA NFS-e", LINHA_VALORES)
    f.campo(COLUNAS[1], topo, "VALOR DA OPERAÇÃO / SERVIÇO", _dinheiro(n(f"{v}/vServPrest/vServ")))
    f.campo(COLUNAS[2], topo, "Desconto Incondicionado", _dinheiro(n(f"{v}/vDescCondIncond/vDescIncond")))
    f.campo(COLUNAS[3], topo, "Desconto Condicionado", _dinheiro(n(f"{v}/vDescCondIncond/vDescCond")))
    topo += LINHA_VALORES
    f.fundo(COLUNAS[3], topo, COL + 0.01, LINHA_VALORES)
    f.campo(COLUNAS[0], topo, "Total das Retenções (ISSQN / Federais)", _dinheiro(n("valores/vTotalRet")))
    f.campo(COLUNAS[1], topo, "VALOR LÍQUIDO DA NFS-e", _dinheiro(n("valores/vLiq")))
    f.campo(COLUNAS[2], topo, "Total do IBS/CBS",
            _dinheiro(_soma(n(f"{ib}/totCIBS/gIBS/vIBSTot"), n(f"{ib}/totCIBS/gCBS/vCBS"))))
    f.campo(COLUNAS[3], topo, "VALOR LÍQUIDO DA NFS-e + IBS/CBS", _dinheiro(n(f"{ib}/totCIBS/vTotNF")))
    topo += LINHA_VALORES
    f.linha(topo)

    # Informações complementares (2.1.12): o que sobra até o canhoto.
    f.texto(ESQ, topo + 0.08, "INFORMAÇÕES COMPLEMENTARES", "Helvetica-Bold", 7, LARGURA)
    topo += 0.39
    ic = "DPS/infDPS/serv/infoCompl"
    partes = [
        ("Inf. Cont.: ", n(f"{ic}/xInfComp")), ("NFS-e Subst.: ", n("DPS/infDPS/subst/chSubstda")),
        ("Doc. Ref.: ", n(f"{ic}/docRef")), ("Cod. Obra: ", n("DPS/infDPS/serv/obra/cObra")),
        ("Insc. Imob.: ", n("DPS/infDPS/serv/obra/inscImobFisc") or n("DPS/infDPS/IBSCBS/imovel/inscImobFisc")),
        ("Cod. Evt.: ", n("DPS/infDPS/serv/atvEvento/idAtvEvt")), ("Doc. Tec.: ", n(f"{ic}/idDocTec")),
        ("Núm. Ped.: ", n(f"{ic}/xPed")), ("Item Ped.: ", n(f"{ic}/gItemPed/xItemPed")),
        ("Inf. A. T. Mun.: ", n("xOutInf")),
    ]
    infos = " | ".join(r + t for r, t in partes if t)
    if len(infos) > 1997:
        infos = infos[:1997] + "..."
    tt = "DPS/infDPS/valores/trib/totTrib"
    if n(f"{tt}/vTotTrib/vTotTribFed") is not None:
        fed, est, mun_ = (_dinheiro(n(f"{tt}/vTotTrib/vTotTrib{s}")) for s in ("Fed", "Est", "Mun"))
    elif n(f"{tt}/pTotTrib/pTotTribFed") is not None:
        fed, est, mun_ = (_pct(n(f"{tt}/pTotTrib/pTotTrib{s}")) for s in ("Fed", "Est", "Mun"))
    else:
        fed = est = mun_ = TRACO
    totais = f"Totais Aproximados dos Tributos cfe. Lei nº 12.741/2012: Federais: {fed}; Estaduais: {est}; Municipais: {mun_};"
    topo += 0.15
    if infos:
        topo += f.paragrafo(ESQ, topo, infos, LARGURA) + 0.15
    f.paragrafo(ESQ, topo, totais, LARGURA)
    if topo > TOPO_CANHOTO - 0.5:
        raise ValueError("o conteúdo não coube numa página (a NT exige página única)")

    # Canhoto (2.1.13, opcional)
    f.linha(TOPO_CANHOTO)
    c.setLineWidth(0.5)
    for x in COLUNAS[1:3]:
        c.line(x * f.cm, f.y(TOPO_CANHOTO), x * f.cm, f.y(TOPO_CANHOTO + LINHA_VALORES))
    f.campo(COLUNAS[0], TOPO_CANHOTO, "DATA CIENTIFICAÇÃO:", " ")
    f.campo(COLUNAS[1], TOPO_CANHOTO, "IDENTIFICAÇÃO E ASSINATURA", " ")
    f.campo(COLUNAS[2], TOPO_CANHOTO, "Nº NFS-e / CHAVE NFS-e", f"{n('nNFSe') or TRACO} / {chave}", 2 * COL + 0.01)


def gerar_danfse(xml_nfse: bytes) -> bytes:
    """PDF do DANFSe (uma página A4) a partir do XML da NFS-e."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as e:
        raise DanfseIndisponivel("gerar o DANFSe precisa do reportlab: pip install 'nfse-cli[danfse]'") from e

    nota = _Nota(xml_nfse)
    saida = io.BytesIO()
    # invariant: sem data de criação nem id aleatório, o mesmo XML gera sempre o mesmo PDF.
    c = canvas.Canvas(saida, pagesize=A4, pageCompression=1, invariant=1)
    chave = (nota.inf.get("Id") or "").removeprefix("NFS")
    c.setTitle(f"DANFSe {nota('nNFSe') or ''} - {chave}")
    c.setCreator("nfse-cli")
    _desenhar(_Folha(c), nota)
    c.showPage()
    c.save()
    return saida.getvalue()
