import gzip
from decimal import Decimal

import pytest

from nfse import HOMOLOGACAO, Rejeicao, emitir, verificar
from nfse.sefin import Resposta, Sefin, _erros, compactar, descompactar

NFSE_XML = b'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe><nNFSe>7</nNFSe></infNFSe></NFSe>'


class SefinFalsa(Sefin):
    """Sefin em memória: guarda as DPS recebidas e responde como a API real."""

    def __init__(self, ja_existe: str | None = None, rejeitar: dict | None = None):
        self.ambiente = HOMOLOGACAO
        self.recebidas: list[bytes] = []
        self.ja_existe = ja_existe
        self.rejeitar = rejeitar

    def _requisicao(self, metodo, caminho, corpo=None):
        if metodo == "GET" and caminho.startswith("/dps/"):
            return Resposta(200, {"chaveAcesso": self.ja_existe}) if self.ja_existe else Resposta(404, {})
        if metodo == "GET" and caminho.startswith("/nfse/"):
            return Resposta(200, {"nfseXmlGZipB64": compactar(NFSE_XML)})
        if metodo == "POST" and caminho == "/nfse":
            self.recebidas.append(descompactar(corpo["dpsXmlGZipB64"]))
            if self.rejeitar:
                return Resposta(400, self.rejeitar)
            return Resposta(201, {"chaveAcesso": "4" * 50, "nfseXmlGZipB64": compactar(NFSE_XML), "alertas": None})
        raise AssertionError(f"chamada inesperada {metodo} {caminho}")


def _emitir(cfg, cert, tomador, sefin):
    return emitir(cfg, cert, HOMOLOGACAO, "1", 5, Decimal("9000"), "Consultoria.", tomador, sefin=sefin)


def test_emite_e_envia_os_bytes_assinados(cfg, cert, tomador):
    sefin = SefinFalsa()
    r = _emitir(cfg, cert, tomador, sefin)
    assert r.chave_acesso == "4" * 50
    assert r.numero_nfse == "7"
    assert not r.ja_existia
    assert sefin.recebidas == [r.xml_dps]
    verificar(sefin.recebidas[0])


def test_dps_que_ja_virou_nota_nao_e_reenviada(cfg, cert, tomador):
    sefin = SefinFalsa(ja_existe="5" * 50)
    r = _emitir(cfg, cert, tomador, sefin)
    assert r.ja_existia
    assert r.chave_acesso == "5" * 50
    assert sefin.recebidas == []


def test_rejeicao_traz_os_codigos(cfg, cert, tomador):
    corpo = {"erros": [{"Codigo": "E0160", "Descricao": "Simples Nacional divergente", "Complemento": None}]}
    with pytest.raises(Rejeicao) as e:
        _emitir(cfg, cert, tomador, SefinFalsa(rejeitar=corpo))
    assert [x.codigo for x in e.value.erros] == ["E0160"]


def test_erros_em_minusculas_e_objeto_unico():
    assert _erros({"erro": {"codigo": "E1235", "descricao": "esquema"}})[0].codigo == "E1235"


def test_compactacao_e_gzip_base64():
    assert gzip.decompress(__import__("base64").b64decode(compactar(b"<a/>"))) == b"<a/>"


class AdnFalso(Sefin):
    def __init__(self, status: int, corpo: bytes):
        self.ambiente = HOMOLOGACAO
        self.resposta = (status, corpo)
        self.urls: list[str] = []

    def _abrir(self, url, metodo="GET", dados=None, accept="application/json"):
        self.urls.append(url)
        return self.resposta


def test_danfse_devolve_o_pdf():
    adn = AdnFalso(200, b"%PDF-1.7 ...")
    assert adn.baixar_danfse("4" * 50) == b"%PDF-1.7 ..."
    assert adn.urls == ["https://adn.producaorestrita.nfse.gov.br/danfse/" + "4" * 50]


@pytest.mark.parametrize("status, corpo", [(503, b"<html>503</html>"), (200, b"<html>manutencao</html>")])
def test_danfse_fora_do_ar_e_falha_de_comunicacao(status, corpo):
    from nfse import FalhaComunicacao
    with pytest.raises(FalhaComunicacao):
        AdnFalso(status, corpo).baixar_danfse("4" * 50)


def test_danfse_nota_inexistente_e_rejeicao():
    with pytest.raises(Rejeicao):
        AdnFalso(404, b'{"erros":[{"Codigo":"E404","Descricao":"nao encontrada"}]}').baixar_danfse("4" * 50)
