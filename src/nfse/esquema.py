"""Validação contra os XSD oficiais, um pacote por pasta em `esquemas/<data>/`."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from lxml import etree

PASTA = Path(__file__).parent / "esquemas"


class EsquemaInvalido(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("XML fora do esquema: " + "; ".join(erros))


@cache
def _esquema(leiaute: str, nome: str) -> etree.XMLSchema:
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
    return etree.XMLSchema(etree.parse(str(PASTA / leiaute / nome), parser))


def validar_dps(xml: bytes, leiaute: str) -> None:
    """`leiaute` é um de `nfse.LEIAUTES` (o mesmo usado para montar a DPS)."""
    esquema = _esquema(leiaute, "DPS_v1.01.xsd")
    if not esquema.validate(etree.fromstring(xml)):
        raise EsquemaInvalido([f"linha {e.line}: {e.message}" for e in esquema.error_log])
