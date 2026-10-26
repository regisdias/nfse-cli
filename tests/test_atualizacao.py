import time

import pytest

import nfse
from nfse_cli import atualizacao, cli


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PASTA_CONFIG", tmp_path)
    monkeypatch.delenv("NFSE_SEM_AVISO_ATUALIZACAO")
    return tmp_path


def test_avisa_versao_nova_e_consulta_uma_vez_por_dia(pasta, monkeypatch):
    consultas = []
    monkeypatch.setattr(atualizacao, "buscar_ultima", lambda: consultas.append(1) or "v99.0.0")
    assert "Nova versão do nfse-cli: 99.0.0" in atualizacao.aviso()
    assert "nfse atualizar" in atualizacao.aviso()
    assert len(consultas) == 1  # a segunda usou o cache


def test_sem_aviso_quando_esta_em_dia_ou_sem_rede(pasta, monkeypatch):
    monkeypatch.setattr(atualizacao, "buscar_ultima", lambda: "v" + nfse.__version__)
    assert atualizacao.aviso() is None
    (pasta / "atualizacao.json").unlink()
    monkeypatch.setattr(atualizacao, "buscar_ultima", lambda: None)
    assert atualizacao.aviso() is None


def test_desligar(pasta, monkeypatch, capsys):
    monkeypatch.setattr(atualizacao, "buscar_ultima", lambda: "v99.0.0")
    cli.main(["atualizar", "--sem-aviso"])
    assert atualizacao.aviso() is None
    monkeypatch.setenv("NFSE_SEM_AVISO_ATUALIZACAO", "1")
    cli.main(["atualizar", "--com-aviso"])
    monkeypatch.delenv("NFSE_SEM_AVISO_ATUALIZACAO")
    assert atualizacao.aviso() is not None


def test_aviso_sai_no_fim_de_qualquer_comando(pasta, monkeypatch, capsys):
    monkeypatch.setattr(atualizacao, "_ler_cache", lambda: {"verificado_em": time.time(), "ultima": "v99.0.0"})
    cli.main(["municipio", "campinas"])
    assert "Nova versão" in capsys.readouterr().err


def test_atualizar_fora_do_instalador_nao_mexe(pasta, monkeypatch):
    monkeypatch.setattr(atualizacao, "buscar_ultima", lambda: "v99.0.0")
    with pytest.raises(SystemExit):
        cli.main(["atualizar"])
