"""Aviso de versão nova e `nfse atualizar`.

Uma versão velha pode ter a nota rejeitada quando a Receita muda o leiaute, então o aviso vem ligado. É a única
conexão fora da Sefin: um GET sem autenticação em api.github.com, no máximo uma vez por dia, só na linha de
comando (a biblioteca e a Lambda nunca checam). Desliga com `nfse atualizar --sem-aviso` ou com a variável
NFSE_SEM_AVISO_ATUALIZACAO=1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import nfse

from . import cli
from .cli import ErroCli

REPOSITORIO = "regisdias/nfse-cli"
URL_ULTIMA = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"
INTERVALO = 24 * 3600
PASTA_INSTALADOR = Path.home() / ".local" / "share" / "nfse-cli" / "venv"


def _versao(texto: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in texto.lstrip("v").split("."))
    except ValueError:
        return ()


def _cache() -> Path:
    return cli.PASTA_CONFIG / "atualizacao.json"


def _ler_cache() -> dict:
    try:
        return json.loads(_cache().read_text())
    except (OSError, ValueError):
        return {}


def _gravar_cache(dados: dict) -> None:
    try:
        _cache().parent.mkdir(parents=True, exist_ok=True)
        _cache().write_text(json.dumps(dados) + "\n")
    except OSError:
        pass


def buscar_ultima() -> str | None:
    """Tag da última versão publicada no GitHub, ou None (sem rede, sem versão publicada, limite da API)."""
    pedido = urllib.request.Request(URL_ULTIMA, headers={"Accept": "application/vnd.github+json",
                                                         "User-Agent": "nfse-cli"})
    try:
        with urllib.request.urlopen(pedido, timeout=2) as r:
            return json.loads(r.read()).get("tag_name")
    except Exception:  # aviso nunca pode atrapalhar o comando
        return None


def aviso() -> str | None:
    if os.environ.get("NFSE_SEM_AVISO_ATUALIZACAO") == "1":
        return None
    dados = _ler_cache()
    if dados.get("desligado"):
        return None
    if time.time() - dados.get("verificado_em", 0) > INTERVALO:
        dados.update(verificado_em=time.time(), ultima=buscar_ultima() or dados.get("ultima"))
        _gravar_cache(dados)
    ultima = dados.get("ultima")
    if ultima and _versao(ultima) > _versao(nfse.__version__):
        return (f"Nova versão do nfse-cli: {ultima.lstrip('v')} (esta é {nfse.__version__}). "
                f"Para atualizar: nfse atualizar")
    return None


def cmd_atualizar(args) -> None:
    if args.sem_aviso or args.com_aviso:
        dados = _ler_cache()
        dados["desligado"] = bool(args.sem_aviso)
        _gravar_cache(dados)
        print("Aviso de versão nova " + ("desligado." if args.sem_aviso else "ligado."))
        return
    ultima = buscar_ultima()
    if not ultima:
        raise ErroCli("não consegui ver a última versão no GitHub (sem internet?)")
    if _versao(ultima) <= _versao(nfse.__version__) and not args.forcar:
        print(f"Já está na última versão ({nfse.__version__}).")
        return
    if Path(sys.prefix).resolve() != PASTA_INSTALADOR.resolve():
        raise ErroCli(f"este nfse não foi instalado pelo install.sh ({sys.prefix}); atualize do jeito que instalou "
                      f"(git pull, pip install -U...). Versão nova: {ultima}")
    origem = f"https://github.com/{REPOSITORIO}/archive/refs/tags/{ultima}.zip"
    print(f"Atualizando para {ultima}...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade",
                    f"nfse-cli[danfse] @ {origem}"], check=True)
    # A skill vem no pacote: o processo novo copia a versão nova para os agentes.
    subprocess.run([str(Path(sys.prefix) / "bin" / "nfse"), "skill", "instalar"], check=True)
    _gravar_cache({**_ler_cache(), "ultima": ultima, "verificado_em": time.time()})
    print(f"Pronto: nfse-cli {ultima.lstrip('v')}. Notas da versão: https://github.com/{REPOSITORIO}/releases/tag/{ultima}")


def registrar(sub) -> dict:
    p = sub.add_parser("atualizar", help="atualiza o nfse-cli e a skill para a última versão")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--sem-aviso", action="store_true", help="desliga o aviso diário de versão nova")
    g.add_argument("--com-aviso", action="store_true", help="liga de novo o aviso")
    p.add_argument("--forcar", action="store_true", help="reinstala mesmo se já estiver na última versão")
    return {"atualizar": cmd_atualizar}
