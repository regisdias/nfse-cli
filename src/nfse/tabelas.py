"""Tabelas oficiais empacotadas em `dados/`: municípios do IBGE, lista de serviços nacional e NBS.

`scripts/gerar_tabelas.py` regenera serviços e NBS a partir do Anexo B do leiaute.
"""

from __future__ import annotations

import csv
import unicodedata
from functools import cache
from pathlib import Path

DADOS = Path(__file__).parent / "dados"


def _ler(nome: str) -> list[list[str]]:
    with open(DADOS / nome, encoding="utf-8") as f:
        return list(csv.reader((l for l in f if not l.startswith("#")), delimiter=";"))


@cache
def _municipios() -> dict[str, tuple[str, str]]:
    return {c: (n, uf) for c, n, uf in _ler("municipios.csv")}


@cache
def _servicos() -> dict[str, str]:
    return dict(_ler("servicos.csv"))


@cache
def _nbs() -> dict[str, str]:
    return dict(_ler("nbs.csv"))


def municipio(codigo: str | None) -> tuple[str, str] | None:
    """(nome, UF) pelo código IBGE de 7 dígitos."""
    return _municipios().get(codigo or "")


def servico(codigo: str | None) -> str | None:
    """Descrição do código de tributação nacional (cTribNac, 6 dígitos)."""
    return _servicos().get(codigo or "")


def nbs(codigo: str | None) -> str | None:
    """Descrição do código NBS (cNBS, 9 dígitos)."""
    return _nbs().get(codigo or "")


def _normal(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().replace("-", " ").split())


def _buscar(itens: dict[str, str], termo: str, limite: int) -> list[tuple[str, str]]:
    """Itens cuja descrição tem todas as palavras do termo (sem acento, sem caixa); o código exato vem primeiro."""
    palavras = _normal(termo).split()
    digitos = "".join(c for c in termo if c.isdigit())
    if digitos and digitos in itens:
        return [(digitos, itens[digitos])]
    achados = [(c, d) for c, d in itens.items() if all(p in _normal(d) for p in palavras)]
    achados.sort(key=lambda cd: (len(cd[1]), cd[0]))
    return achados[:limite]


def buscar_municipios(termo: str, limite: int = 10) -> list[tuple[str, str, str]]:
    """(código, nome, UF). Aceita "Itajaí", "itajai sc" ou o código."""
    palavras = _normal(termo).split()
    uf = palavras[-1].upper() if len(palavras) > 1 and len(palavras[-1]) == 2 else None
    nome = " ".join(palavras[:-1] if uf else palavras)
    if termo.strip().isdigit():
        m = municipio(termo.strip())
        return [(termo.strip(), *m)] if m else []
    achados = [
        (c, n, u) for c, (n, u) in _municipios().items()
        if (not uf or u == uf) and nome in _normal(n)
    ]
    achados.sort(key=lambda m: (_normal(m[1]) != nome, len(m[1]), m[1]))
    return achados[:limite]


def buscar_servicos(termo: str, limite: int = 15) -> list[tuple[str, str]]:
    """(cTribNac, descrição) pela descrição ou pelo código (17.01.01 ou 170101)."""
    return _buscar(_servicos(), termo, limite)


def buscar_nbs(termo: str, limite: int = 15) -> list[tuple[str, str]]:
    """(cNBS, descrição) pela descrição ou pelo código (1.1401.39.00 ou 114013900)."""
    return _buscar(_nbs(), termo, limite)
