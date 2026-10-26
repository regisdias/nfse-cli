"""Gera src/nfse/dados/{servicos,nbs}.csv a partir do Anexo B oficial (lista de serviços nacional e NBS).

    curl -L -o /tmp/anexo_b.xlsx \\
      https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/anexo_b-nbs2-lista_servico_nacional-snnfse-v1-01-20260122.xlsx
    python3 -I scripts/gerar_tabelas.py /tmp/anexo_b.xlsx

Rodar de novo quando sair versão nova do anexo e conferir o diff antes de versionar.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ler_xlsx import linhas  # noqa: E402

DADOS = Path(__file__).resolve().parent.parent / "src" / "nfse" / "dados"


def servicos(planilha: str) -> list[tuple[str, str]]:
    """Aba 1: CÓDIGO DE TRIBUTAÇÃO NACIONAL (sem zero à esquerda) e DESCRIÇÃO. Linhas sem código são títulos."""
    saida = []
    for l in linhas(planilha, 1):
        codigo = l.get("A", "")
        if codigo.isdigit():
            saida.append((codigo.zfill(6), l["E"]))
    return saida


def nbs(planilha: str) -> list[tuple[str, str]]:
    """Aba 2: só os códigos completos (1.0101.11.00 vira 101011100), que são os que entram no cNBS."""
    saida = []
    for l in linhas(planilha, 2):
        codigo = l.get("A", "")
        if re.fullmatch(r"\d\.\d{4}\.\d{2}\.\d{2}", codigo):
            saida.append((codigo.replace(".", ""), l["B"]))
    return saida


def gravar(nome: str, cabecalho: str, itens: list[tuple[str, str]]) -> None:
    with open(DADOS / nome, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {cabecalho}\n")
        for codigo, descricao in itens:
            f.write(f"{codigo};{descricao.replace(';', ',')}\n")
    print(f"{nome}: {len(itens)} linhas")


if __name__ == "__main__":
    planilha = sys.argv[1]
    origem = "Anexo B do leiaute da NFS-e nacional (v1.01, 22/01/2026)"
    gravar("servicos.csv", f"{origem}, aba LISTA.SERV.NAC.: cTribNac;descrição", servicos(planilha))
    gravar("nbs.csv", f"{origem}, aba LISTA.NBS_v2.0: cNBS;descrição", nbs(planilha))
