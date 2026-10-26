import email
import email.policy
from datetime import date

import pytest

import nfse
from nfse import gerar_dps
from nfse_cli import cli, entrega

from .conftest import CNPJ
from .test_emissao import SefinFalsa
from .test_modelo import CHAVE, nfse_de

CONFIG = f"""
serie = "1"
pasta_notas = "notas"

[certificado]
arquivo = "certificado.pfx"

[prestador]
cnpj = "{CNPJ}"
cod_municipio = "3550308"
op_simp_nac = 3
reg_ap_trib_sn = 1

[servico]
c_trib_nac = "170101"
c_nbs = "114013900"

[servico.tot_trib]
modo = "sn"
percentual = 6

[entrega]
pasta = "{{pasta}}/entregas"
assinatura = "Equipe Teste"

[tomadores.cliente]
documento = "11444777000161"
nome = "CLIENTE TESTE LTDA"

[tomadores.cliente.recorrente]
valor = "9000"
descricao = "Consultoria de {{mes_min}}/{{ano}}."

[tomadores.cliente.entrega]
pasta = "Cliente"
para = "fiscal@cliente.com.br, outro@cliente.com.br"
"""


@pytest.fixture
def aj(tmp_path, monkeypatch, cert):
    arquivo = tmp_path / "config.toml"
    arquivo.write_text(CONFIG.replace("{pasta}", str(tmp_path)))
    monkeypatch.setattr(cli, "PASTA_CONFIG", tmp_path)
    monkeypatch.setattr(cli, "carregar_certificado", lambda aj: cert)
    monkeypatch.setattr(entrega, "carregar_certificado", lambda aj: cert)
    return cli.carregar_ajustes(arquivo)


@pytest.fixture
def nota(aj, cert, emissao, tomador):
    """NFS-e sintética já no cache local, como se tivesse sido emitida ou baixada."""
    xml = nfse_de(gerar_dps(aj.cfg, cert, emissao, tomador).xml)
    pasta = aj.pasta_notas / "producao"
    pasta.mkdir(parents=True)
    (pasta / f"{CHAVE}-nfse.xml").write_bytes(xml)
    return xml


class Args:
    def __init__(self, **kw):
        self.__dict__.update({"tomador": None, "modo": None, "mes": None, "json": False}, **kw)


def test_arquivar_e_email(aj, nota, tmp_path):
    pytest.importorskip("reportlab")
    entrega.cmd_arquivar(aj, Args(chave=CHAVE))
    pasta = tmp_path / "entregas" / "Cliente"
    mes = cli.campos_do_mes(date.today())
    base = f"NFS-e 7 - CLIENTE TESTE LTDA - {mes['mes']} de {mes['ano']}"
    assert (pasta / f"{base}.xml").read_bytes() == nota
    assert (pasta / f"{base}.pdf").read_bytes().startswith(b"%PDF")
    entrega.cmd_arquivar(aj, Args(chave=CHAVE))  # de novo, mesmo conteúdo: não reclama

    entrega.cmd_email(aj, Args(chave=CHAVE, modo="eml"))
    msg = email.message_from_bytes((pasta / f"{base}.eml").read_bytes(), policy=email.policy.default)
    assert msg["To"] == "fiscal@cliente.com.br, outro@cliente.com.br"
    assert msg["X-Unsent"] == "1" and msg["Subject"].startswith("NFS-e nº 7 - ")
    anexos = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert anexos == [f"{base}.pdf"]
    corpo = next(p for p in msg.walk() if p.get_content_type() == "text/plain").get_content()
    assert "R$ 9.000,00" in corpo and "o PDF (DANFSe) da nota" in corpo and "Equipe Teste" in corpo


def test_arquivar_nao_sobrescreve_outra_nota(aj, nota, tmp_path):
    pytest.importorskip("reportlab")
    entrega.cmd_arquivar(aj, Args(chave=CHAVE))
    xml = next((tmp_path / "entregas" / "Cliente").glob("*.xml"))
    xml.write_bytes(b"<outra/>")
    with pytest.raises(cli.ErroCli, match="outro conteúdo"):
        entrega.cmd_arquivar(aj, Args(chave=CHAVE))


def test_email_sem_pdf_ou_sem_destinatario(aj, nota):
    with pytest.raises(cli.ErroCli, match="arquivar"):
        entrega.cmd_email(aj, Args(chave=CHAVE, modo="eml"))


def test_notas_varre_as_duas_series(aj, nota, monkeypatch, capsys):
    usados = {nfse.id_dps("3550308", CNPJ, "1", 1): CHAVE}

    class Sefin(SefinFalsa):
        def consultar_dps(self, id_dps):
            return usados.get(id_dps)

    monkeypatch.setattr(nfse, "Sefin", lambda cert, ambiente: Sefin())
    entrega.cmd_notas(aj, Args(tomador="cliente", mes=date.today().strftime("%Y-%m")))
    saida = capsys.readouterr().out
    assert "nº    7" in saida and "já tem nota (nº 7)" in saida
    assert (aj.pasta_notas / "producao" / "indice.json").exists()


# --- emitir com valores recorrentes e código de confirmação ----------------------------

class EmitirArgs(Args):
    def __init__(self, **kw):
        base = {"producao": True, "valor": None, "descricao": None, "descricao_arquivo": None, "tomador": "cliente",
                "tomador_doc": None, "competencia": None, "info": None, "numero": None, "saida": None,
                "confirmacao": None}
        super().__init__(**{**base, **kw})


@pytest.fixture
def sefin(monkeypatch):
    falsa = SefinFalsa()
    falsa.ambiente = nfse.PRODUCAO
    monkeypatch.setattr(nfse, "Sefin", lambda cert, ambiente: falsa)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    return falsa


def _codigo(aj, tmp_path, capsys, **kw) -> str:
    cli.cmd_dps(aj, EmitirArgs(saida=str(tmp_path / "dps.xml"), **kw))
    saida = capsys.readouterr().out
    assert "R$ 9.000,00" in saida  # valor recorrente
    mes = cli.campos_do_mes(date.today())
    assert f"Consultoria de {mes['mes_min']}/{mes['ano']}." in saida  # descrição com o mês
    return saida.split("Código de confirmação: ")[1][:6]


def test_producao_com_o_codigo_certo_envia(aj, sefin, tmp_path, capsys):
    codigo = _codigo(aj, tmp_path, capsys)
    cli.cmd_emitir(aj, EmitirArgs(confirmacao=codigo.lower()))
    assert len(sefin.recebidas) == 1
    assert cli.ultimo_numero(CNPJ, nfse.PRODUCAO, "1") == 1


def test_codigo_de_outra_nota_nao_envia(aj, sefin, tmp_path, capsys):
    codigo = _codigo(aj, tmp_path, capsys)
    with pytest.raises(cli.ErroCli, match="não bate"):
        cli.cmd_emitir(aj, EmitirArgs(confirmacao=codigo, valor="9500"))
    with pytest.raises(cli.ErroCli, match="confirmação"):
        cli.cmd_emitir(aj, EmitirArgs())
    assert sefin.recebidas == []


def test_numero_ja_usado_na_sefin_e_pulado(aj, monkeypatch):
    usados = {nfse.id_dps("3550308", CNPJ, "1", n) for n in (1, 2, 3)}

    class Sefin(SefinFalsa):
        def consultar_dps(self, id_dps):
            return "4" * 50 if id_dps in usados else None

    assert cli._proximo_numero(aj, nfse.PRODUCAO, EmitirArgs(), Sefin()) == 4
    assert cli.ultimo_numero(CNPJ, nfse.PRODUCAO, "1") == 3
