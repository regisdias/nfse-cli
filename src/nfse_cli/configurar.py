"""`nfse configurar`: monta o config.toml a partir de uma nota modelo ou de respostas, e guarda o certificado.

O caminho é sempre o mesmo, para a skill e para quem usa direto:

  1. `nfse configurar certificado arquivo.pfx`  copia o .pfx e guarda a senha no Keychain (pede no terminal)
  2. `nfse configurar modelo <xml|pdf|chave>`   lê uma nota já emitida e grava um rascunho (JSON)
     ou a skill escreve o mesmo rascunho com as respostas do caminho manual
  3. `nfse configurar salvar rascunho.json`     valida (monta e confere uma DPS de teste) e grava o config.toml

O rascunho: {"config": {"prestador", "servico"}, "tomadores": {"apelido": {...}}, "serie"?, "modelo"?,
"nao_suportado"?, "avisos"?}. `nao_suportado` não vazio impede de salvar.
"""

from __future__ import annotations

import getpass
import json
import re
import shutil
import subprocess
import sys
import tomllib
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import nfse
from nfse import HOMOLOGACAO, LEIAUTES, PRODUCAO, Certificado, Emissao, tabelas
from nfse.danfse import OP_SIMP_NAC, REG_AP_TRIB_SN, REG_ESP_TRIB, TP_RET_ISSQN, TRIB_ISSQN, _cep, _dinheiro, _doc
from nfse.modelo import Modelo, chave_valida, chaves_no_pdf, cnpj_da_chave, ler_nfse

from . import cli, correio
from .cli import SERVICO_KEYCHAIN, ErroCli


# --- certificado -------------------------------------------------------------------

def _guardar_senha_keychain(cnpj: str, senha: str) -> bool:
    """Grava no Keychain do macOS. A senha vai em hexadecimal pela entrada padrão do `security -i`,
    nunca na linha de comando (que outros processos enxergam)."""
    if not shutil.which("security"):
        return False
    comando = f"add-generic-password -U -s {SERVICO_KEYCHAIN} -a {cnpj} -X {senha.encode().hex()}\n"
    r = subprocess.run(["security", "-i"], input=comando, text=True, capture_output=True)
    return r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower()


def cmd_certificado(args) -> None:
    origem = Path(args.arquivo).expanduser()
    if not origem.exists():
        raise ErroCli(f"arquivo não encontrado: {origem}")
    if not sys.stdin.isatty():
        raise ErroCli(
            "a senha do certificado é digitada só por você, no seu terminal (o agente não deve vê-la). Rode:\n"
            f"  nfse configurar certificado {args.arquivo}"
        )
    dados = origem.read_bytes()
    senha = getpass.getpass("Senha do certificado: ")
    cert = Certificado.de_pfx(dados, senha)
    if not cert.cnpj:
        raise ErroCli("não achei o CNPJ no certificado: é um e-CNPJ A1?")
    cert.validar()

    destino = cli.PASTA_CONFIG / "certificado.pfx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.read_bytes() != dados:
        atual = None
        try:
            atual = Certificado.de_pfx(destino.read_bytes(), senha).cnpj
        except nfse.CertificadoInvalido:
            pass
        if atual != cert.cnpj and not args.substituir:
            raise ErroCli(f"já existe {destino} de outro CNPJ (ou com outra senha); use --substituir para trocar")
        destino.replace(destino.with_name(f"certificado-{datetime.now():%Y%m%d%H%M%S}.pfx.bak"))
    destino.write_bytes(dados)
    destino.chmod(0o600)

    guardou = _guardar_senha_keychain(cert.cnpj, senha)
    del senha
    print(f"Titular:  {cert.titular}")
    print(f"CNPJ:     {_doc(cert.cnpj, None, None)}")
    print(f"Validade: até {cert.valido_ate:%d/%m/%Y} ({cert.dias_para_vencer()} dias)")
    print(f"Copiado para {destino}")
    if guardou:
        print("Senha guardada no Keychain.")
    else:
        print("Não há Keychain neste sistema: defina NFSE_CERT_SENHA antes de usar o nfse (ou digite quando pedir).")


def _certificado_local(cnpj: str) -> Certificado:
    arquivo = cli.PASTA_CONFIG / "certificado.pfx"
    if not arquivo.exists():
        raise ErroCli("falta o certificado: rode `nfse configurar certificado arquivo.pfx` no seu terminal")
    return cli.abrir_certificado(arquivo, cnpj)


# --- modelo --------------------------------------------------------------------------

def _xml_do_modelo(fonte: str, ambiente: int) -> bytes:
    caminho = Path(fonte).expanduser()
    if caminho.exists():
        dados = caminho.read_bytes()
        if dados.lstrip().startswith(b"<"):
            return dados
        chaves = chaves_no_pdf(dados)
        if not chaves:
            raise ErroCli("não achei a chave de acesso no PDF; informe a chave (50 dígitos, está no PDF) ou o XML")
        if len(chaves) > 1:
            raise ErroCli("o PDF tem mais de uma chave de acesso: informe qual usar\n  " + "\n  ".join(chaves))
        chave = chaves[0]
    else:
        chave = re.sub(r"\D", "", fonte)
        if not chave_valida(chave):
            raise ErroCli(f"não é arquivo nem chave de acesso válida: {fonte}")
    return nfse.Sefin(_certificado_local(cnpj_da_chave(chave)), ambiente).baixar_nfse(chave)


def _apelido(nome: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    palavras = [p for p in re.findall(r"[a-z0-9]+", ascii_) if p not in {"ltda", "sa", "me", "epp", "eireli", "de", "da", "do"}]
    return palavras[0] if palavras else "cliente"


def rascunho_do_modelo(m: Modelo, apelido: str | None = None) -> dict:
    rascunho = {"config": m.config, "tomadores": {}}
    if m.tomador:
        recorrente = {"valor": m.valor, "descricao": m.descricao} if m.valor else {}
        rascunho["tomadores"][apelido or _apelido(m.tomador["nome"])] = {**m.tomador, "recorrente": recorrente}
    rascunho["modelo"] = {
        "chave": m.chave, "numero_nfse": m.numero_nfse, "emitida_em": m.emitida_em, "ambiente": m.ambiente,
        "prestador_nome": m.prestador_nome, "valor": m.valor, "descricao": m.descricao,
        "competencia": m.competencia, "serie_dps": m.serie_dps, "numero_dps": m.numero_dps,
    }
    rascunho["nao_suportado"] = m.nao_suportado
    rascunho["avisos"] = m.avisos
    return rascunho


def cmd_modelo(args) -> None:
    ambiente = HOMOLOGACAO if args.homologacao else PRODUCAO
    try:
        m = ler_nfse(_xml_do_modelo(args.fonte, ambiente))
    except ValueError as e:
        raise ErroCli(str(e)) from e
    rascunho = rascunho_do_modelo(m, args.apelido)
    destino = Path(args.saida) if args.saida else cli.PASTA_CONFIG / "rascunho.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(rascunho, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(descrever(rascunho))
    print(f"\nRascunho em {destino}. Conferiu? `nfse configurar salvar {destino}`")


# --- salvar ----------------------------------------------------------------------------

def _certificado_de_teste(cnpj: str) -> Certificado:
    """Certificado autoassinado só para montar e validar uma DPS de teste, sem pedir a senha do real."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"TESTE DE CONFIGURACAO:{cnpj}")])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=1))
        .sign(chave, hashes.SHA256())
    )
    return Certificado(chave=chave, cert=cert, cadeia=())


def nao_suportado(rascunho: dict) -> list[str]:
    """O que o rascunho pede e o nfse ainda não emite: o que veio da nota modelo e o que dá para ver na configuração."""
    cfg = nfse.config_de_dict(rascunho["config"])
    lista = list(rascunho.get("nao_suportado") or [])
    for condicao, nome in [(cfg.prestador.op_simp_nac == 2, "MEI"),
                           (cfg.servico.tp_ret_issqn != 1, "ISS retido pelo tomador"),
                           (cfg.servico.trib_issqn != 1, "ISS não tributável (imunidade, exportação ou não incidência)")]:
        if condicao and nome not in lista:
            lista.append(nome)
    return lista


def validar_rascunho(rascunho: dict) -> None:
    if faltam := nao_suportado(rascunho):
        raise ErroCli("a configuração usa o que o nfse ainda não sabe emitir: " + ", ".join(faltam)
                      + ". Por enquanto, emita pelo Emissor Web do governo.")
    cfg = nfse.config_de_dict(rascunho["config"])
    tomadores = {k: nfse.tomador_de_dict(v) for k, v in rascunho.get("tomadores", {}).items()}
    modelo = rascunho.get("modelo") or {}
    cert = _certificado_de_teste(cfg.prestador.cnpj)
    for tomador in [*tomadores.values()] or [None]:
        for leiaute in LEIAUTES:
            emissao = Emissao(ambiente=HOMOLOGACAO, leiaute=leiaute, serie=str(rascunho.get("serie", "1")), numero=1,
                              valor=Decimal(modelo.get("valor") or "1.00"),
                              descricao=modelo.get("descricao") or "Teste de configuração.")
            nfse.gerar_dps(cfg, cert, emissao, tomador)


def _toml_valor(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)  # string básica do TOML: mesmas regras de escape do JSON


def _toml_chave(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def para_toml(dados: dict, prefixo: str = "") -> str:
    simples = {k: v for k, v in dados.items() if not isinstance(v, dict)}
    tabelas_ = {k: v for k, v in dados.items() if isinstance(v, dict)}
    linhas = [f"{_toml_chave(k)} = {_toml_valor(v)}" for k, v in simples.items() if v is not None]
    blocos = []
    if prefixo and linhas:
        blocos.append(f"[{prefixo}]\n" + "\n".join(linhas))
    elif linhas:
        blocos.append("\n".join(linhas))
    for k, v in tabelas_.items():
        chave = f"{prefixo}.{_toml_chave(k)}" if prefixo else _toml_chave(k)
        interno = para_toml(v, chave)
        if interno:
            blocos.append(interno)
        elif not v:
            blocos.append(f"[{chave}]")
    return "\n\n".join(blocos)


def _juntar_tomadores(atuais: dict, novos: dict) -> dict:
    """Cliente novo entra inteiro; cliente que já existe é atualizado seção por seção (recorrente e entrega
    que o rascunho não traz continuam como estavam)."""
    saida = {k: dict(v) for k, v in atuais.items()}
    for apelido, dados in novos.items():
        atual = saida.get(apelido, {})
        junto = {**atual, **dados}
        for secao in ("recorrente", "entrega"):
            if isinstance(atual.get(secao), dict) or isinstance(dados.get(secao), dict):
                junto[secao] = {**atual.get(secao, {}), **dados.get(secao, {})}
                if not junto[secao]:
                    del junto[secao]
        saida[apelido] = junto
    return saida


def cmd_salvar(args) -> None:
    origem = Path(args.rascunho).expanduser()
    rascunho = json.loads(origem.read_text(encoding="utf-8"))
    validar_rascunho(rascunho)

    destino = args.config
    atual = tomllib.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {}
    cnpj_novo = str(rascunho["config"]["prestador"]["cnpj"])
    cnpj_atual = str(atual.get("prestador", {}).get("cnpj", "")) or None
    if cnpj_atual and cnpj_atual != cnpj_novo and not args.substituir:
        raise ErroCli(f"{destino} é de outro CNPJ ({cnpj_atual}); use --substituir para trocar")

    novo = {
        "serie": str(rascunho.get("serie") or atual.get("serie") or "1"),
        "pasta_notas": atual.get("pasta_notas", "notas"),
        "certificado": atual.get("certificado") or {"arquivo": "certificado.pfx"},
        "prestador": rascunho["config"]["prestador"],
        "servico": rascunho["config"]["servico"],
        "tomadores": _juntar_tomadores(atual.get("tomadores", {}) if cnpj_atual == cnpj_novo else {},
                                       rascunho.get("tomadores", {})),
    }
    if atual.get("entrega") or rascunho.get("entrega"):
        novo["entrega"] = {**atual.get("entrega", {}), **rascunho.get("entrega", {})}
    novo.update({k: v for k, v in atual.items() if k not in novo})
    texto = ("# Gerado por `nfse configurar salvar`. A senha do certificado não fica aqui.\n\n"
             + para_toml(novo) + "\n")
    tomllib.loads(texto)  # o que foi escrito precisa ler de volta
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        shutil.copy2(destino, destino.with_name(f"{destino.name}.{datetime.now():%Y%m%d%H%M%S}.bak"))
    destino.write_text(texto, encoding="utf-8")

    # Nota modelo emitida por este aplicativo (série 1 a 49999) em produção: a numeração continua dela.
    modelo = rascunho.get("modelo") or {}
    if modelo.get("ambiente") == PRODUCAO and str(modelo.get("serie_dps")) == novo["serie"] and modelo.get("numero_dps"):
        cli.registrar_numero(cnpj_novo, PRODUCAO, novo["serie"], int(modelo["numero_dps"]))

    print(f"Configuração salva em {destino}.")
    if not (destino.parent / novo["certificado"]["arquivo"]).exists():
        print("Falta o certificado: rode `nfse configurar certificado arquivo.pfx` no seu terminal.")
    print("Próximo passo: uma nota de teste em homologação (`nfse emitir`, sem --producao).")


def cmd_mostrar(args) -> None:
    if not args.config.exists():
        raise ErroCli(f"ainda não há configuração em {args.config}")
    d = tomllib.loads(args.config.read_text(encoding="utf-8"))
    print(descrever({"config": {"prestador": d.get("prestador", {}), "servico": d.get("servico", {})},
                     "tomadores": d.get("tomadores", {})}))


# --- resumo em português ----------------------------------------------------------------

def _cod(codigo: str, partes: tuple[int, ...]) -> str:
    saida, i = [], 0
    for n in partes:
        saida.append(codigo[i:i + n])
        i += n
    return ".".join(saida)


def _municipio(codigo) -> str:
    m = tabelas.municipio(str(codigo))
    return f"{m[0]}/{m[1]}" if m else f"município {codigo}"


def descrever(rascunho: dict) -> str:
    p = rascunho["config"]["prestador"]
    s = rascunho["config"]["servico"]
    modelo = rascunho.get("modelo") or {}
    linhas = []
    nome = modelo.get("prestador_nome")
    linhas.append(f"Prestador:  {nome + ', ' if nome else ''}CNPJ {_doc(str(p.get('cnpj')), None, None)}, {_municipio(p.get('cod_municipio'))}")
    regime = OP_SIMP_NAC.get(str(p.get("op_simp_nac")), f"opção {p.get('op_simp_nac')}")
    if p.get("reg_ap_trib_sn"):
        regime += f" ({REG_AP_TRIB_SN.get(str(p['reg_ap_trib_sn']), p['reg_ap_trib_sn'])})"
    if int(p.get("reg_esp_trib") or 0):
        regime += f"; regime especial: {REG_ESP_TRIB.get(str(p['reg_esp_trib']), p['reg_esp_trib'])}"
    linhas.append(f"Regime:     {regime}")
    c = str(s.get("c_trib_nac", ""))
    linhas.append(f"Serviço:    {_cod(c, (2, 2, 2))} {tabelas.servico(c) or '(código fora da lista nacional)'}")
    if s.get("c_nbs"):
        n = str(s["c_nbs"])
        linhas.append(f"NBS:        {_cod(n, (1, 4, 2, 2))} {tabelas.nbs(n) or '(fora da lista NBS)'}")
    if s.get("cod_municipio_prestacao"):
        linhas.append(f"Prestado em: {_municipio(s['cod_municipio_prestacao'])}")
    iss = f"{TRIB_ISSQN.get(str(s.get('trib_issqn', 1)), '?')}, {TP_RET_ISSQN.get(str(s.get('tp_ret_issqn', 1)), '?')}"
    if s.get("p_aliq"):
        iss += f", alíquota {str(s['p_aliq']).replace('.', ',')}%"
    linhas.append(f"ISS:        {iss}")
    t = s.get("tot_trib", {})
    if t.get("modo") == "sn":
        tot = f"{str(t.get('percentual')).replace('.', ',')}% (alíquota do Simples)"
    elif t.get("modo") in ("percentual", "valor"):
        un = "%" if t["modo"] == "percentual" else " (R$)"
        tot = f"federal {t.get('federal')}, estadual {t.get('estadual')}, municipal {t.get('municipal')}{un}"
    else:
        tot = "não informados"
    linhas.append(f"Tributos aproximados: {tot}")
    if pc := s.get("pis_cofins"):
        linhas.append(f"PIS/COFINS: apuração própria, CST {pc.get('cst', '01')}, PIS {str(pc.get('p_aliq_pis')).replace('.', ',')}%"
                      f", COFINS {str(pc.get('p_aliq_cofins')).replace('.', ',')}%, sem retenção")
    if ib := s.get("ibs_cbs"):
        linhas.append(f"IBS/CBS:    CST {ib.get('cst')}, cClassTrib {ib.get('c_class_trib')}, "
                      f"indicador da operação {ib.get('c_ind_op')} (valores calculados pela Sefin)")
    for apelido, tom in (rascunho.get("tomadores") or {}).items():
        doc = re.sub(r"\D", "", str(tom.get("documento", "")))
        doc_fmt = _doc(doc, None, None) if len(doc) == 14 else _doc(None, doc, None)
        linhas.append(f"Cliente \"{apelido}\": {tom.get('nome')}, {'CNPJ' if len(doc) == 14 else 'CPF'} {doc_fmt}")
        if tom.get("endereco"):
            e = tom["endereco"]
            compl = f", {e['complemento']}" if e.get("complemento") else ""
            linhas.append(f"  {e.get('logradouro')}, {e.get('numero')}{compl}, {e.get('bairro')}, "
                          f"{_municipio(e.get('cod_municipio'))}, CEP {_cep(str(e.get('cep')))}")
        if tom.get("email"):
            linhas.append(f"  e-mail: {tom['email']}")
        rec = tom.get("recorrente") or {}
        if rec.get("valor"):
            linhas.append(f"  Todo mês: {_dinheiro(str(rec['valor']))}" + (f", \"{rec['descricao'].splitlines()[0][:70]}\"" if rec.get("descricao") else ""))
        ent = tom.get("entrega") or {}
        if ent.get("para"):
            linhas.append(f"  Enviar para: {ent['para']}" + (f" (cópia: {ent['cc']})" if ent.get("cc") else ""))
    if modelo:
        quando = (modelo.get("emitida_em") or "")[:10]
        if quando:
            quando = f" de {quando[8:10]}/{quando[5:7]}/{quando[:4]}"
        linhas.append(f"Nota modelo: nº {modelo.get('numero_nfse')}{quando}, {_dinheiro(modelo.get('valor'))}")
        if modelo.get("descricao"):
            linhas.append("  Descrição: " + modelo["descricao"].splitlines()[0][:100])
    for aviso in rascunho.get("avisos") or []:
        linhas.append(f"Atenção: {aviso}")
    if rascunho.get("nao_suportado"):
        linhas.append("NÃO SUPORTADO: " + ", ".join(rascunho["nao_suportado"])
                      + ". O nfse ainda não emite notas assim; use o Emissor Web do governo.")
    return "\n".join(linhas)


# --- buscas nas tabelas oficiais ----------------------------------------------------------

def cmd_municipio(args) -> None:
    achados = tabelas.buscar_municipios(" ".join(args.termo))
    for codigo, nome, uf in achados:
        print(f"{codigo}  {nome}/{uf}")
    if not achados:
        raise ErroCli("nenhum município encontrado")


def cmd_servico(args) -> None:
    achados = tabelas.buscar_servicos(" ".join(args.termo))
    for codigo, descricao in achados:
        print(f"{codigo}  {_cod(codigo, (2, 2, 2))}  {descricao}")
    if not achados:
        raise ErroCli("nenhum serviço encontrado; tente outras palavras (ex.: consultoria, desenvolvimento, limpeza)")


def cmd_nbs(args) -> None:
    achados = tabelas.buscar_nbs(" ".join(args.termo))
    for codigo, descricao in achados:
        print(f"{codigo}  {_cod(codigo, (1, 4, 2, 2))}  {descricao}")
    if not achados:
        raise ErroCli("nenhum código NBS encontrado")


def registrar(sub) -> dict:
    """Subcomandos que não precisam de configuração pronta. Devolve {nome: função}."""
    p = sub.add_parser("configurar", help="configura o nfse (certificado, nota modelo, salvar)")
    s = p.add_subparsers(dest="etapa", required=True)
    e = s.add_parser("certificado", help="copia o .pfx e guarda a senha no Keychain (rode no seu terminal)")
    e.add_argument("arquivo")
    e.add_argument("--substituir", action="store_true", help="troca um certificado de outro CNPJ")
    e = s.add_parser("modelo", help="lê uma nota já emitida (XML, PDF ou chave) e grava um rascunho")
    e.add_argument("fonte", help="arquivo .xml, arquivo .pdf ou chave de acesso")
    e.add_argument("--homologacao", action="store_true", help="a nota modelo é de homologação")
    e.add_argument("--apelido", help="apelido do cliente na configuração (padrão: primeira palavra do nome)")
    e.add_argument("--saida", help="onde gravar o rascunho (padrão: ~/.config/nfse-cli/rascunho.json)")
    e = s.add_parser("salvar", help="valida um rascunho e grava o config.toml")
    e.add_argument("rascunho")
    e.add_argument("--substituir", action="store_true", help="troca a configuração de outro CNPJ")
    s.add_parser("mostrar", help="resume a configuração atual em português")
    for nome, ajuda in [("municipio", "procura o código IBGE de um município"),
                        ("servico", "procura o código de tributação nacional (lista de serviços)"),
                        ("nbs", "procura o código NBS")]:
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("termo", nargs="+")
    sub.add_parser("programas-de-email", help="lista os programas de e-mail desta máquina e o padrão do sistema")
    p = sub.add_parser("skill", help="instala ou remove a skill nos agentes (Claude Code, Codex, Antigravity)")
    p.add_argument("acao", choices=["instalar", "remover"])
    p.add_argument("--todos", action="store_true", help="instala também em agente que não parece instalado")
    etapas = {"certificado": cmd_certificado, "modelo": cmd_modelo, "salvar": cmd_salvar, "mostrar": cmd_mostrar}
    return {
        "configurar": lambda args: etapas[args.etapa](args),
        "municipio": cmd_municipio,
        "servico": cmd_servico,
        "nbs": cmd_nbs,
        "skill": cmd_skill,
        "programas-de-email": lambda args: correio.cmd_programas(args),
    }


# --- skill para agentes ---------------------------------------------------------------------

ORIGEM_SKILL = Path(__file__).parent / "skill"
MARCA_SKILL = ".instalado-pelo-nfse-cli"


def destinos_skill() -> dict[str, tuple[Path, Path]]:
    """Agente -> (pasta que indica que ele está instalado, pasta da skill). Padrão aberto Agent Skills."""
    casa = Path.home()
    return {
        "Claude Code": (casa / ".claude", casa / ".claude" / "skills" / "nfse"),
        "Codex": (casa / ".codex", casa / ".agents" / "skills" / "nfse"),
        "Antigravity": (casa / ".gemini", casa / ".gemini" / "config" / "skills" / "nfse"),
    }


def cmd_skill(args) -> None:
    feitos = []
    for agente, (indicio, destino) in destinos_skill().items():
        if args.acao == "remover":
            if (destino / MARCA_SKILL).exists():
                shutil.rmtree(destino)
                feitos.append(f"{agente}: removida de {destino}")
            continue
        if not indicio.exists() and not args.todos:
            continue
        if destino.exists() and not (destino / MARCA_SKILL).exists():
            feitos.append(f"{agente}: {destino} já existe e não é desta instalação; não mexi")
            continue
        if destino.exists():
            shutil.rmtree(destino)
        shutil.copytree(ORIGEM_SKILL, destino, ignore=shutil.ignore_patterns("__pycache__"))
        (destino / MARCA_SKILL).write_text(f"nfse-cli {nfse.__version__}\n")
        feitos.append(f"{agente}: {destino}")
    if not feitos:
        print("Nenhum agente encontrado (Claude Code, Codex ou Antigravity). Use --todos para instalar mesmo assim."
              if args.acao == "instalar" else "Nada para remover.")
    for linha in feitos:
        print(linha)
