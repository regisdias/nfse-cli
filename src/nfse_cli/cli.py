"""Linha de comando: consumidor da biblioteca `nfse`.

Diferente da biblioteca, a CLI guarda estado local: a configuração (TOML) e
o último número de DPS usado por (CNPJ, ambiente, série).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import nfse
from nfse import (
    HOMOLOGACAO,
    PRODUCAO,
    Certificado,
    Config,
    Emissao,
    Endereco,
    Prestador,
    Servico,
    Tomador,
    TotTrib,
)

PASTA_CONFIG = Path(os.environ.get("NFSE_HOME", Path.home() / ".config" / "nfse-cli"))
SERVICO_KEYCHAIN = "nfse-cli"
NOMES_AMBIENTE = {PRODUCAO: "producao", HOMOLOGACAO: "homologacao"}


class ErroCli(Exception):
    pass


# --- configuração ----------------------------------------------------------

@dataclass
class Ajustes:
    cfg: Config
    arquivo_certificado: Path
    pasta_notas: Path
    serie: str
    tomadores: dict[str, Tomador]


def _tot_trib(dados: dict) -> TotTrib:
    modo = dados.get("modo", "sn")
    if modo == "sn":
        return TotTrib.sn(str(dados["percentual"]))
    if modo in ("percentual", "valor"):
        valores = [str(dados[k]) for k in ("federal", "estadual", "municipal")]
        return TotTrib.percentual(*valores) if modo == "percentual" else TotTrib.valor(*valores)
    if modo == "nao_informado":
        return TotTrib.nao_informado()
    raise ErroCli(f"tot_trib.modo desconhecido: {modo}")


def _tomador(dados: dict) -> Tomador:
    end = dados.get("endereco")
    return Tomador(
        documento=str(dados["documento"]),
        nome=dados["nome"],
        email=dados.get("email"),
        fone=dados.get("fone"),
        im=dados.get("im"),
        endereco=Endereco(**end) if end else None,
    )


def carregar_ajustes(caminho: Path) -> Ajustes:
    if not caminho.exists():
        raise ErroCli(f"configuração não encontrada: {caminho} (copie config.exemplo.toml)")
    with caminho.open("rb") as f:
        d = tomllib.load(f)
    p, s = d["prestador"], d["servico"]
    prestador = Prestador(
        cnpj=str(p["cnpj"]),
        cod_municipio=str(p["cod_municipio"]),
        op_simp_nac=int(p["op_simp_nac"]),
        reg_esp_trib=int(p.get("reg_esp_trib", 0)),
        reg_ap_trib_sn=p.get("reg_ap_trib_sn"),
        im=p.get("im"),
        fone=p.get("fone"),
        email=p.get("email"),
    )
    servico = Servico(
        c_trib_nac=str(s["c_trib_nac"]),
        cod_municipio_prestacao=str(s.get("cod_municipio_prestacao", prestador.cod_municipio)),
        tot_trib=_tot_trib(s.get("tot_trib", {})),
        c_nbs=s.get("c_nbs"),
        c_trib_mun=s.get("c_trib_mun"),
        trib_issqn=int(s.get("trib_issqn", 1)),
        tp_ret_issqn=int(s.get("tp_ret_issqn", 1)),
        p_aliq=Decimal(str(s["p_aliq"])) if "p_aliq" in s else None,
    )
    base = caminho.parent
    return Ajustes(
        cfg=Config(prestador, servico),
        arquivo_certificado=(base / Path(d["certificado"]["arquivo"]).expanduser()),
        pasta_notas=(base / Path(d.get("pasta_notas", "notas")).expanduser()),
        serie=str(d.get("serie", "1")),
        tomadores={k: _tomador(v) for k, v in d.get("tomadores", {}).items()},
    )


def senha_certificado(cnpj: str) -> str:
    """NFSE_CERT_SENHA, depois o Keychain do macOS, por último pergunta."""
    if senha := os.environ.get("NFSE_CERT_SENHA"):
        return senha
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICO_KEYCHAIN, "-a", cnpj, "-w"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.rstrip("\n")
    except FileNotFoundError:
        pass
    if not sys.stdin.isatty():
        raise ErroCli(
            "senha do certificado não encontrada: defina NFSE_CERT_SENHA ou guarde no Keychain com\n"
            f"  security add-generic-password -s {SERVICO_KEYCHAIN} -a {cnpj} -w"
        )
    return getpass.getpass("Senha do certificado: ")


def carregar_certificado(aj: Ajustes) -> Certificado:
    if not aj.arquivo_certificado.exists():
        raise ErroCli(f"certificado não encontrado: {aj.arquivo_certificado}")
    cert = Certificado.de_pfx(aj.arquivo_certificado.read_bytes(), senha_certificado(aj.cfg.prestador.cnpj))
    cert.validar(aj.cfg.prestador.cnpj)
    return cert


# --- numeração local ---------------------------------------------------------

def _arquivo_numeracao() -> Path:
    return PASTA_CONFIG / "numeracao.json"


def _chave_numeracao(cnpj: str, ambiente: int, serie: str) -> str:
    return f"{cnpj}:{NOMES_AMBIENTE[ambiente]}:{int(serie)}"


def ultimo_numero(cnpj: str, ambiente: int, serie: str) -> int:
    arq = _arquivo_numeracao()
    dados = json.loads(arq.read_text()) if arq.exists() else {}
    return int(dados.get(_chave_numeracao(cnpj, ambiente, serie), 0))


def registrar_numero(cnpj: str, ambiente: int, serie: str, numero: int) -> None:
    arq = _arquivo_numeracao()
    dados = json.loads(arq.read_text()) if arq.exists() else {}
    chave = _chave_numeracao(cnpj, ambiente, serie)
    dados[chave] = max(numero, int(dados.get(chave, 0)))
    arq.parent.mkdir(parents=True, exist_ok=True)
    temporario = arq.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, indent=2) + "\n")
    temporario.replace(arq)


# --- comandos ----------------------------------------------------------------

def _ambiente(args) -> int:
    return PRODUCAO if args.producao else HOMOLOGACAO


def _valor(texto: str) -> Decimal:
    texto = texto.strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
        # "9.000" é nove mil ou nove reais? Não adivinha com dinheiro.
        raise ErroCli(f"valor ambíguo: {texto} (use 9000 ou 9.000,00)")
    try:
        v = Decimal(texto)
    except InvalidOperation as e:
        raise ErroCli(f"valor inválido: {texto}") from e
    if v <= 0:
        raise ErroCli("valor precisa ser maior que zero")
    return v


def _tomador_dos_args(aj: Ajustes, args) -> Tomador | None:
    if args.tomador:
        if args.tomador not in aj.tomadores:
            raise ErroCli(f"tomador '{args.tomador}' não está na configuração (tem: {', '.join(aj.tomadores) or 'nenhum'})")
        return aj.tomadores[args.tomador]
    if args.tomador_doc:
        if not args.tomador_nome:
            raise ErroCli("--tomador-doc exige --tomador-nome")
        return Tomador(documento=args.tomador_doc, nome=args.tomador_nome, email=args.tomador_email)
    return None


def _descricao(args) -> str:
    if args.descricao_arquivo:
        return Path(args.descricao_arquivo).read_text(encoding="utf-8").strip()
    if args.descricao:
        return args.descricao
    raise ErroCli("informe --descricao ou --descricao-arquivo")


def _resumo(aj: Ajustes, ambiente: int, serie: str, numero: int, valor: Decimal, tomador, descricao: str, competencia) -> str:
    p, s = aj.cfg.prestador, aj.cfg.servico
    linhas = [
        f"Ambiente:    {NOMES_AMBIENTE[ambiente].upper()} (esquemas {nfse.LEIAUTE_POR_AMBIENTE[ambiente]})",
        f"Prestador:   {p.cnpj} (município {p.cod_municipio})",
        f"Tomador:     {f'{tomador.nome} ({tomador.documento})' if tomador else '(sem tomador)'}",
        f"Serviço:     {s.c_trib_nac}" + (f" / NBS {s.c_nbs}" if s.c_nbs else ""),
        f"Valor:       R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        f"DPS:         série {int(serie)}, número {numero}",
        f"Competência: {(competencia or date.today()).strftime('%d/%m/%Y')}",
        "Descrição:",
        *("  " + linha for linha in descricao.splitlines()),
    ]
    return "\n".join(linhas)


def _proximo_numero(aj: Ajustes, ambiente: int, args) -> int:
    if args.numero:
        return args.numero
    return ultimo_numero(aj.cfg.prestador.cnpj, ambiente, aj.serie) + 1


def _emissao_dos_args(aj: Ajustes, args):
    ambiente = _ambiente(args)
    numero = _proximo_numero(aj, ambiente, args)
    competencia = date.fromisoformat(args.competencia) if args.competencia else None
    emissao = Emissao(
        ambiente=ambiente,
        serie=aj.serie,
        numero=numero,
        valor=_valor(args.valor),
        descricao=_descricao(args),
        competencia=competencia,
        info_complementar=args.info,
    )
    return emissao, _tomador_dos_args(aj, args)


def cmd_certificado(aj: Ajustes, args) -> None:
    cert = Certificado.de_pfx(aj.arquivo_certificado.read_bytes(), senha_certificado(aj.cfg.prestador.cnpj))
    print(f"Titular:  {cert.titular}")
    print(f"CNPJ:     {cert.cnpj}")
    print(f"Validade: {cert.valido_de:%d/%m/%Y} a {cert.valido_ate:%d/%m/%Y} ({cert.dias_para_vencer()} dias)")
    cert.validar(aj.cfg.prestador.cnpj)
    print("OK: válido e do mesmo CNPJ do prestador.")


def cmd_dps(aj: Ajustes, args) -> None:
    cert = carregar_certificado(aj)
    emissao, tomador = _emissao_dos_args(aj, args)
    dps = nfse.gerar_dps(aj.cfg, cert, emissao, tomador)
    destino = Path(args.saida or f"{dps.id}.xml")
    destino.write_bytes(dps.xml)
    print(_resumo(aj, emissao.ambiente, emissao.serie, emissao.numero, emissao.valor, tomador, emissao.descricao, emissao.competencia))
    print(f"\nDPS assinada e validada no XSD (não enviada): {destino}")


def cmd_emitir(aj: Ajustes, args) -> None:
    cert = carregar_certificado(aj)
    emissao, tomador = _emissao_dos_args(aj, args)
    print(_resumo(aj, emissao.ambiente, emissao.serie, emissao.numero, emissao.valor, tomador, emissao.descricao, emissao.competencia))
    # Assina e valida antes de perguntar: se tem erro local, nem chega a pedir confirmação.
    nfse.gerar_dps(aj.cfg, cert, emissao, tomador)

    if emissao.ambiente == PRODUCAO:
        if not sys.stdin.isatty():
            raise ErroCli("produção exige confirmação no terminal")
        print("\nIsto emite uma nota fiscal DE VERDADE.")
        if input("Digite EMITIR para confirmar: ").strip() != "EMITIR":
            raise ErroCli("cancelado, nada foi enviado")

    try:
        r = nfse.emitir(
            aj.cfg, cert, emissao.ambiente, emissao.serie, emissao.numero, emissao.valor,
            emissao.descricao, tomador, emissao.competencia, emissao.info_complementar,
        )
    except nfse.Rejeicao as e:
        print("\nRejeitada pela Sefin:", file=sys.stderr)
        for erro in e.erros:
            print(f"  {erro}", file=sys.stderr)
        if not e.erros:
            print(f"  HTTP {e.status}: {json.dumps(e.corpo, ensure_ascii=False)[:1000]}", file=sys.stderr)
        raise SystemExit(2)

    registrar_numero(aj.cfg.prestador.cnpj, emissao.ambiente, emissao.serie, emissao.numero)
    pasta = aj.pasta_notas / NOMES_AMBIENTE[emissao.ambiente]
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{r.chave_acesso}-dps.xml").write_bytes(r.xml_dps)
    (pasta / f"{r.chave_acesso}-nfse.xml").write_bytes(r.xml_nfse)

    print("\n" + ("Essa DPS já tinha virado nota antes; baixei a existente." if r.ja_existia else "NFS-e emitida."))
    print(f"Número:          {r.numero_nfse}")
    print(f"Chave de acesso: {r.chave_acesso}")
    print(f"XML:             {pasta / f'{r.chave_acesso}-nfse.xml'}")
    if r.alertas:
        print("Alertas da Sefin:", json.dumps(r.alertas, ensure_ascii=False))


def cmd_consultar(aj: Ajustes, args) -> None:
    cert = carregar_certificado(aj)
    ambiente = _ambiente(args)
    id_dps = args.id or nfse.id_dps(aj.cfg.prestador.cod_municipio, aj.cfg.prestador.cnpj, aj.serie, args.numero)
    chave = nfse.Sefin(cert, ambiente).consultar_dps(id_dps)
    print(f"{id_dps}: " + (f"virou a NFS-e {chave}" if chave else "não gerou nota"))


def cmd_baixar(aj: Ajustes, args) -> None:
    cert = carregar_certificado(aj)
    xml = nfse.Sefin(cert, _ambiente(args)).baixar_nfse(args.chave)
    destino = Path(args.saida or f"{args.chave}-nfse.xml")
    destino.write_bytes(xml)
    print(f"Salvo em {destino}")


def montar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nfse", description="Emissão de NFS-e pela API da Sefin Nacional.")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("NFSE_CONFIG", PASTA_CONFIG / "config.toml")))
    ap.add_argument("--versao", action="version", version=f"nfse-cli {nfse.__version__}")
    sub = ap.add_subparsers(dest="comando", required=True)

    def ambiente(p):
        p.add_argument("--producao", action="store_true", help="usar produção (padrão: homologação)")

    def dados_nota(p):
        ambiente(p)
        p.add_argument("--valor", required=True, help="ex.: 9000 ou 9.000,00")
        p.add_argument("--descricao")
        p.add_argument("--descricao-arquivo", help="arquivo texto com a descrição (aceita várias linhas)")
        p.add_argument("--tomador", help="apelido de um tomador da configuração")
        p.add_argument("--tomador-doc")
        p.add_argument("--tomador-nome")
        p.add_argument("--tomador-email")
        p.add_argument("--competencia", help="AAAA-MM-DD (padrão: hoje)")
        p.add_argument("--info", help="informações complementares")
        p.add_argument("--numero", type=int, help="número da DPS (padrão: último usado + 1)")

    sub.add_parser("certificado", help="mostra e valida o certificado")
    p = sub.add_parser("dps", help="gera a DPS assinada sem enviar")
    dados_nota(p)
    p.add_argument("--saida")
    p = sub.add_parser("emitir", help="emite a NFS-e")
    dados_nota(p)
    p = sub.add_parser("consultar", help="consulta se uma DPS virou nota")
    ambiente(p)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--numero", type=int)
    p = sub.add_parser("baixar", help="baixa o XML de uma NFS-e pela chave")
    ambiente(p)
    p.add_argument("chave")
    p.add_argument("--saida")
    return ap


COMANDOS = {
    "certificado": cmd_certificado,
    "dps": cmd_dps,
    "emitir": cmd_emitir,
    "consultar": cmd_consultar,
    "baixar": cmd_baixar,
}


def main(argv: list[str] | None = None) -> None:
    args = montar_parser().parse_args(argv)
    try:
        aj = carregar_ajustes(args.config)
        COMANDOS[args.comando](aj, args)
    except (ErroCli, nfse.DadosInvalidos, nfse.CertificadoInvalido, nfse.EsquemaInvalido, nfse.AssinaturaInvalida) as e:
        print(f"erro: {e}", file=sys.stderr)
        raise SystemExit(1)
    except nfse.FalhaComunicacao as e:
        print(f"falha de comunicação com a Sefin: {e}", file=sys.stderr)
        print("Antes de tentar de novo, rode `nfse consultar` com o mesmo número: a nota pode ter saído.", file=sys.stderr)
        raise SystemExit(3)
