"""Depois de emitir: quais notas já existem, arquivar XML e PDF numa pasta, e preparar o e-mail.

Configuração (tudo opcional), no config.toml:

    [entrega]                          # padrão para todos os clientes
    pasta = "~/Documents/NFS-e"
    nome_arquivo = "NFS-e {numero} - {cliente} - {mes} de {ano}"
    email = "outlook"                  # outlook (rascunho aberto no Outlook do Mac) | eml | nenhum
    assinatura = "Fulano"
    anexar_xml = false

    [tomadores.<apelido>.entrega]      # sobrescreve o [entrega] para esse cliente
    pasta = "Cliente X"                # subpasta de [entrega].pasta (padrão: o apelido)
    para = "financeiro@cliente.com.br" # vários: separados por vírgula
    cc = ""
    assunto = "NFS-e {mes_min}/{ano} - {prestador}"
    saudacao = "Olá, Fulana,"
    corpo = "..."                      # ver CORPO_PADRAO

Campos dos modelos: {numero} {valor} {mes} {mes_min} {mes_num} {ano} {cliente} {prestador} {chave} {anexos}
{saudacao} {assinatura}.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import nfse
from lxml import etree
from nfse import PRODUCAO
from nfse.dps import NS

from . import correio
from .cli import Ajustes, ErroCli, campos_do_mes, carregar_certificado

SERIE_EMISSOR_WEB = "70000"
NOME_ARQUIVO_PADRAO = "NFS-e {numero} - {cliente} - {mes} de {ano}"
ASSUNTO_PADRAO = "NFS-e nº {numero} - {mes_min}/{ano} - {prestador}"
CORPO_PADRAO = """{saudacao}

Segue a NFS-e nº {numero}, referente aos serviços de {mes_min}/{ano}, no valor de R$ {valor}.

Em anexo, {anexos} da nota.

{assinatura}
"""


def _t(el, caminho: str) -> str | None:
    return el.findtext(".//" + "/".join(f"{{{NS}}}{p}" for p in caminho.split("/")))


# --- notas já emitidas ---------------------------------------------------------------

def _pasta_producao(aj: Ajustes) -> Path:
    return aj.pasta_notas / "producao"


def xml_da_nota(aj: Ajustes, sefin: nfse.Sefin | None, chave: str) -> bytes:
    """Do cache local (`<pasta_notas>/producao/`) ou baixado da Sefin, e aí guardado."""
    arquivo = _pasta_producao(aj) / f"{chave}-nfse.xml"
    if not arquivo.exists():
        sefin = sefin or nfse.Sefin(carregar_certificado(aj), PRODUCAO)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(sefin.baixar_nfse(chave))
    return arquivo.read_bytes()


def notas_de_producao(aj: Ajustes) -> list[dict]:
    """Notas do prestador na série deste aplicativo e na do Emissor Web do governo.

    A API não lista notas: consulta DPS por DPS (série, número) até três números seguidos sem nota. O índice
    local guarda as já achadas, então só a primeira vez é demorada.
    """
    sefin = nfse.Sefin(carregar_certificado(aj), PRODUCAO)
    p = aj.cfg.prestador
    arq_indice = _pasta_producao(aj) / "indice.json"
    indice = json.loads(arq_indice.read_text()) if arq_indice.exists() else {}
    for serie in dict.fromkeys((SERIE_EMISSOR_WEB, aj.serie)):
        numero, faltas = 1, 0
        while faltas < 3:
            id_dps = nfse.id_dps(p.cod_municipio, p.cnpj, serie, numero)
            if id_dps not in indice and (chave := sefin.consultar_dps(id_dps)):
                indice[id_dps] = chave
            faltas = 0 if id_dps in indice else faltas + 1
            numero += 1
    arq_indice.parent.mkdir(parents=True, exist_ok=True)
    arq_indice.write_text(json.dumps(indice, indent=2, sort_keys=True) + "\n")

    notas = []
    for id_dps, chave in indice.items():
        r = etree.fromstring(xml_da_nota(aj, sefin, chave))
        notas.append({
            "chave": chave,
            "numero": int(_t(r, "nNFSe")),
            "competencia": _t(r, "dCompet"),
            "tomador": _t(r, "toma/CNPJ") or _t(r, "toma/CPF"),
            "tomador_nome": _t(r, "toma/xNome"),
            "valor": _t(r, "vServ"),
            "serie_dps": str(int(id_dps[-20:-15])),
        })
    return sorted(notas, key=lambda n: n["numero"])


def cmd_notas(aj: Ajustes, args) -> None:
    notas = notas_de_producao(aj)
    if args.tomador:
        if args.tomador not in aj.tomadores:
            raise ErroCli(f"tomador '{args.tomador}' não está na configuração")
        notas = [n for n in notas if n["tomador"] == aj.tomadores[args.tomador].documento]
    mes = args.mes or date.today().strftime("%Y-%m")
    do_mes = [n for n in notas if (n["competencia"] or "").startswith(mes)]
    if args.json:
        print(json.dumps({"mes": mes, "notas": notas, "do_mes": do_mes}, ensure_ascii=False, indent=2))
        return
    for n in notas:
        marca = "  <- deste mês" if n in do_mes else ""
        print(f"nº {n['numero']:>4}  competência {n['competencia']}  R$ {n['valor']:>11}  "
              f"{(n['tomador_nome'] or '(sem tomador)')[:40]:<40}  série {n['serie_dps']}  {n['chave']}{marca}")
    if not notas:
        print("Nenhuma nota de produção encontrada.")
    print(f"\n{mes}: " + (f"já tem nota ({', '.join('nº ' + str(n['numero']) for n in do_mes)})" if do_mes
                         else "nenhuma nota ainda"))


# --- arquivar e e-mail -------------------------------------------------------------------

def _apelido_da_nota(aj: Ajustes, xml: bytes, pedido: str | None) -> str | None:
    if pedido:
        if pedido not in aj.tomadores:
            raise ErroCli(f"tomador '{pedido}' não está na configuração")
        return pedido
    doc = _t(etree.fromstring(xml), "toma/CNPJ") or _t(etree.fromstring(xml), "toma/CPF")
    return next((a for a, t in aj.tomadores.items() if t.documento == doc), None)


def _entrega(aj: Ajustes, apelido: str | None) -> dict:
    geral = dict(aj.bruto.get("entrega", {}))
    proprio = aj.extra_do_tomador(apelido, "entrega") if apelido else {}
    return {**geral, **proprio, "pasta_raiz": geral.get("pasta", "~/Documents/NFS-e"),
            "pasta": proprio.get("pasta") or apelido or "Sem cliente"}


def _campos(aj: Ajustes, xml: bytes, ent: dict) -> dict:
    r = etree.fromstring(xml)
    valor = Decimal(_t(r, "vServ") or "0")
    anexar_xml = bool(ent.get("anexar_xml", False))
    return {
        **campos_do_mes(date.fromisoformat(_t(r, "dCompet"))),
        "numero": _t(r, "nNFSe"),
        "valor": f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "cliente": _t(r, "toma/xNome") or "Sem cliente",
        "prestador": _t(r, "emit/xNome") or aj.cfg.prestador.cnpj,
        "chave": (r.find(f"{{{NS}}}infNFSe").get("Id") or "")[3:],
        "anexos": "o PDF (DANFSe) e o XML" if anexar_xml else "o PDF (DANFSe)",
        "saudacao": ent.get("saudacao", "Olá,"),
        "assinatura": ent.get("assinatura", ""),
    }


def _base(ent: dict, campos: dict) -> Path:
    nome = ent.get("nome_arquivo", NOME_ARQUIVO_PADRAO).format(**campos)
    nome = "".join("-" if c in '/\\:*?"<>|' else c for c in nome).strip()
    return Path(ent["pasta_raiz"]).expanduser() / ent["pasta"] / nome


def _gravar(arquivo: Path, conteudo: bytes) -> None:
    """Não sobrescreve arquivo de outra nota com o mesmo nome."""
    if arquivo.exists() and arquivo.read_bytes() != conteudo:
        raise ErroCli(f"já existe {arquivo} com outro conteúdo; mude `nome_arquivo` ou mova o arquivo antigo")
    arquivo.write_bytes(conteudo)
    print(f"Salvo em {arquivo}")


def cmd_arquivar(aj: Ajustes, args) -> None:
    xml = xml_da_nota(aj, None, args.chave)
    ent = _entrega(aj, _apelido_da_nota(aj, xml, args.tomador))
    base = _base(ent, _campos(aj, xml, ent))
    base.parent.mkdir(parents=True, exist_ok=True)
    _gravar(base.with_suffix(".xml"), xml)
    _gravar(base.with_suffix(".pdf"), nfse.gerar_danfse(xml))


def _enderecos(texto: str | None) -> str:
    return ",".join(e.strip() for e in (texto or "").split(",") if e.strip())


def cmd_email(aj: Ajustes, args) -> None:
    xml = xml_da_nota(aj, None, args.chave)
    apelido = _apelido_da_nota(aj, xml, args.tomador)
    ent = _entrega(aj, apelido)
    campos = _campos(aj, xml, ent)
    base = _base(ent, campos)
    pdf = base.with_suffix(".pdf")
    if not pdf.exists():
        raise ErroCli(f"falta o PDF ({pdf}); rode `nfse arquivar {args.chave}` antes")
    anexos = [pdf]
    if ent.get("anexar_xml"):
        anexos.append(base.with_suffix(".xml"))
    # --para: teste mandando para si mesmo (sem cópia para ninguém).
    para = _enderecos(args.para or ent.get("para"))
    if not para:
        raise ErroCli(f"falta o destinatário: `para` em [tomadores.{apelido or '<apelido>'}.entrega]")
    rascunho = correio.Rascunho(
        para=para,
        cc="" if args.para else _enderecos(ent.get("cc")),
        assunto=ent.get("assunto", ASSUNTO_PADRAO).format(**campos),
        corpo=ent.get("corpo", CORPO_PADRAO).format(**campos).strip() + "\n",
        anexos=anexos,
        eml=base.with_suffix(".eml"),
    )
    modo = args.modo or ent.get("email") or correio.modo_padrao()
    print(correio.abrir(modo, rascunho))
    print(f"Para: {rascunho.para}" + (f" (cópia: {rascunho.cc})" if rascunho.cc else "") + f"\nAssunto: {rascunho.assunto}")


def registrar(sub) -> dict:
    """Subcomandos que precisam da configuração. Devolve {nome: função(aj, args)}."""
    p = sub.add_parser("notas", help="notas de produção já emitidas (diz se o mês já tem nota)")
    p.add_argument("--tomador", help="só as deste cliente (apelido)")
    p.add_argument("--mes", help="AAAA-MM (padrão: mês atual)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("arquivar", help="grava o XML e o PDF da nota na pasta do cliente")
    p.add_argument("chave")
    p.add_argument("--tomador", help="apelido do cliente (padrão: o da nota)")
    p = sub.add_parser("email", help="prepara o e-mail da nota com o PDF, no programa de e-mail configurado")
    p.add_argument("chave")
    p.add_argument("--tomador", help="apelido do cliente (padrão: o da nota)")
    p.add_argument("--modo", choices=list(correio.MODOS), help="sobrescreve o `email` da configuração")
    p.add_argument("--para", help="teste: manda o rascunho para este endereço, sem cópia")
    return {"notas": cmd_notas, "arquivar": cmd_arquivar, "email": cmd_email}
