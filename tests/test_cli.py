from decimal import Decimal

import pytest

from nfse_cli import cli


@pytest.mark.parametrize("texto,esperado", [
    ("9000", Decimal("9000")),
    ("9000.50", Decimal("9000.50")),
    ("9.000,00", Decimal("9000.00")),
    ("1.234.567,89", Decimal("1234567.89")),
])
def test_valor(texto, esperado):
    assert cli._valor(texto) == esperado


@pytest.mark.parametrize("texto", ["9.000", "0", "-5", "abc"])
def test_valor_invalido_ou_ambiguo(texto):
    with pytest.raises(cli.ErroCli):
        cli._valor(texto)


def test_numeracao_so_avanca(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PASTA_CONFIG", tmp_path)
    assert cli.ultimo_numero("1", 2, "1") == 0
    cli.registrar_numero("1", 2, "1", 3)
    cli.registrar_numero("1", 2, "1", 2)
    assert cli.ultimo_numero("1", 2, "1") == 3
    assert cli.ultimo_numero("1", 1, "1") == 0


def test_config_exemplo_carrega(monkeypatch):
    from pathlib import Path
    aj = cli.carregar_ajustes(Path(__file__).parent.parent / "config.exemplo.toml")
    assert aj.cfg.prestador.op_simp_nac == 3
    assert "cliente" in aj.tomadores
