import json
import tomllib

import pytest

from nfse_cli import cli
from nfse_cli.configurar import para_toml, rascunho_do_modelo
from nfse.modelo import ler_nfse
from nfse import gerar_dps

from .conftest import CNPJ
from .test_modelo import nfse_de


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PASTA_CONFIG", tmp_path)
    return tmp_path


@pytest.fixture
def nota(cfg, cert, emissao, tomador) -> bytes:
    return nfse_de(gerar_dps(cfg, cert, emissao, tomador).xml)


def nfse(*args) -> int:
    try:
        cli.main(list(args))
    except SystemExit as e:
        return e.code
    return 0


def test_modelo_do_xml_e_salvar(pasta, nota, capsys):
    (pasta / "nota.xml").write_bytes(nota)
    assert nfse("configurar", "modelo", str(pasta / "nota.xml"), "--apelido", "cliente-teste") == 0
    saida = capsys.readouterr().out
    assert "17.01.01 Assessoria ou consultoria" in saida and "São Paulo/SP" in saida and "R$ 9.000,00" in saida

    config = pasta / "config.toml"
    assert nfse("--config", str(config), "configurar", "salvar", str(pasta / "rascunho.json")) == 0
    d = tomllib.loads(config.read_text())
    assert d["prestador"]["cnpj"] == CNPJ and d["certificado"]["arquivo"] == "certificado.pfx"
    assert d["tomadores"]["cliente-teste"]["nome"] == "CLIENTE TESTE LTDA"
    aj = cli.carregar_ajustes(config)  # o que foi gravado carrega na CLI
    assert aj.cfg.servico.c_trib_nac == "170101"
    # Nota modelo de homologação: a numeração de produção não muda.
    assert cli.ultimo_numero(CNPJ, cli.PRODUCAO, "1") == 0


def test_salvar_continua_a_numeracao_da_nota_de_producao(pasta, nota):
    rascunho = rascunho_do_modelo(ler_nfse(nota))
    rascunho["modelo"].update(ambiente=1, numero_dps=41)
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(pasta / "config.toml"), "configurar", "salvar", str(pasta / "r.json")) == 0
    assert cli.ultimo_numero(CNPJ, cli.PRODUCAO, "1") == 41


def test_salvar_recusa_o_que_nao_sabe_emitir(pasta, nota, capsys):
    rascunho = rascunho_do_modelo(ler_nfse(nota))
    rascunho["nao_suportado"] = ["MEI"]
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(pasta / "config.toml"), "configurar", "salvar", str(pasta / "r.json")) == 1
    assert "MEI" in capsys.readouterr().err
    assert not (pasta / "config.toml").exists()


@pytest.mark.parametrize("secao, campo, valor, aviso", [
    ("prestador", "op_simp_nac", 2, "MEI"),
    ("servico", "tp_ret_issqn", 2, "ISS retido"),
    ("servico", "trib_issqn", 3, "ISS não tributável"),
])
def test_salvar_recusa_pela_configuracao_no_caminho_manual(pasta, nota, capsys, secao, campo, valor, aviso):
    rascunho = rascunho_do_modelo(ler_nfse(nota))
    rascunho["config"][secao][campo] = valor
    if campo == "op_simp_nac":
        rascunho["config"]["prestador"].pop("reg_ap_trib_sn")
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(pasta / "config.toml"), "configurar", "salvar", str(pasta / "r.json")) == 1
    assert aviso in capsys.readouterr().err


def test_salvar_recusa_dados_que_a_sefin_rejeitaria(pasta, nota, capsys):
    rascunho = rascunho_do_modelo(ler_nfse(nota))
    rascunho["config"]["servico"]["c_trib_nac"] = "17"
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(pasta / "config.toml"), "configurar", "salvar", str(pasta / "r.json")) == 1
    assert "cTribNac" in capsys.readouterr().err


def test_salvar_nao_troca_de_cnpj_sem_pedir_e_guarda_os_outros_clientes(pasta, nota):
    config = pasta / "config.toml"
    rascunho = rascunho_do_modelo(ler_nfse(nota), "primeiro")
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(config), "configurar", "salvar", str(pasta / "r.json")) == 0

    rascunho["tomadores"] = {"segundo": {"documento": "11444777000161", "nome": "OUTRO CLIENTE LTDA"}}
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(config), "configurar", "salvar", str(pasta / "r.json")) == 0
    assert set(tomllib.loads(config.read_text())["tomadores"]) == {"primeiro", "segundo"}
    assert list(pasta.glob("config.toml.*.bak"))  # cópia do anterior

    rascunho["config"]["prestador"]["cnpj"] = "11444777000161"
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(config), "configurar", "salvar", str(pasta / "r.json")) == 1


def test_modelo_de_fonte_invalida(pasta, capsys):
    assert nfse("configurar", "modelo", "123") == 1
    assert "chave de acesso" in capsys.readouterr().err


def test_certificado_exige_terminal(pasta, monkeypatch, capsys):
    (pasta / "c.pfx").write_bytes(b"x")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert nfse("configurar", "certificado", str(pasta / "c.pfx")) == 1
    assert "no seu terminal" in capsys.readouterr().err


def test_buscas(capsys):
    assert nfse("servico", "consultoria", "informatica") == 0
    assert "01.06.01" in capsys.readouterr().out
    assert nfse("municipio", "campinas", "sp") == 0
    assert "3509502" in capsys.readouterr().out
    assert nfse("nbs", "nada", "parecido", "xyzzy") == 1


def test_para_toml_le_de_volta():
    dados = {"a": "texto \"com\" aspas\ne quebra", "b": 3, "c": {"d": "ç", "e": {"f": True}}, "chave com espaço": {"x": 1}}
    assert tomllib.loads(para_toml(dados)) == dados


def test_salvar_preserva_recorrencia_e_entrega_do_cliente(pasta, nota):
    config = pasta / "config.toml"
    rascunho = rascunho_do_modelo(ler_nfse(nota), "cliente")
    assert rascunho["tomadores"]["cliente"]["recorrente"]["valor"] == "9000.00"
    rascunho["tomadores"]["cliente"]["entrega"] = {"para": "fiscal@cliente.com.br"}
    rascunho["entrega"] = {"pasta": "~/NFS-e"}
    (pasta / "r.json").write_text(json.dumps(rascunho))
    assert nfse("--config", str(config), "configurar", "salvar", str(pasta / "r.json")) == 0

    # Atualiza só o nome: recorrência, entrega e [entrega] continuam.
    so_nome = {"config": rascunho["config"], "tomadores": {"cliente": {"documento": "11444777000161", "nome": "NOVO NOME LTDA"}}}
    (pasta / "r.json").write_text(json.dumps(so_nome))
    assert nfse("--config", str(config), "configurar", "salvar", str(pasta / "r.json")) == 0
    d = tomllib.loads(config.read_text())
    cliente = d["tomadores"]["cliente"]
    assert cliente["nome"] == "NOVO NOME LTDA" and cliente["recorrente"]["valor"] == "9000.00"
    assert cliente["entrega"]["para"] == "fiscal@cliente.com.br" and d["entrega"]["pasta"] == "~/NFS-e"


def test_skill_instalar_e_remover(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".gemini" / "config" / "skills" / "nfse").mkdir(parents=True)  # de outra pessoa: não mexe
    assert nfse("skill", "instalar") == 0
    assert (tmp_path / ".claude" / "skills" / "nfse" / "SKILL.md").read_text().startswith("---\nname: nfse")
    assert not (tmp_path / ".agents").exists()  # sem Codex instalado
    assert "não é desta instalação" in capsys.readouterr().out
    assert nfse("skill", "instalar") == 0  # de novo: atualiza
    assert nfse("skill", "remover") == 0
    assert not (tmp_path / ".claude" / "skills" / "nfse").exists()
    assert (tmp_path / ".gemini" / "config" / "skills" / "nfse").exists()
