"""Lambda de emissão: `Handler: nfse_lambda.handler.handler`.

Sem estado, como a biblioteca: quem chama manda a configuração do prestador, a série e o número da DPS
(a numeração é de quem chama, no banco dele). O certificado vem do Secrets Manager e nunca do evento.

Variáveis de ambiente:
  NFSE_SEGREDO_CERTIFICADO  nome ou ARN do segredo; `{cnpj}` é trocado pelo CNPJ do prestador
                            (ex.: "nfse/certificado/{cnpj}"). Conteúdo: JSON {"pfx": "<base64>", "senha": "..."}
  NFSE_PRODUCAO_LIBERADA    "1" para aceitar `"ambiente": "producao"`; sem ela a função só fala com homologação
  NFSE_CONFIG               opcional: JSON da configuração, para quem tem um prestador só

Evento:
  {"acao": "emitir", "config": {...}, "ambiente": "homologacao", "serie": "1", "numero": 7,
   "valor": "9000.00", "descricao": "...", "tomador": {...}?, "competencia": "2026-10-01"?,
   "info_complementar": "..."?}
  {"acao": "dps", ...mesmos campos}        DPS assinada e validada, sem enviar
  {"acao": "consultar", "config", "ambiente", "serie", "numero"}  ou  {"id_dps"}
  {"acao": "baixar", "config", "ambiente", "chave"}
  {"acao": "danfse", "xml": "<NFSe...>"}  ou  {"config", "ambiente", "chave"}  (pacote com o extra danfse)

Resposta: {"ok": true, ...} ou {"ok": false, "erro": "rejeicao"|"dados"|"certificado"|"comunicacao", ...}.
`comunicacao` pode ser repetida: `emitir` consulta a DPS antes de enviar e devolve a nota se ela já saiu.

Log: só ação, ambiente, id da DPS, chave e códigos de erro. Nunca XML, tomador ou senha.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import nfse

log = logging.getLogger("nfse_lambda")
log.setLevel(logging.INFO)

AMBIENTES = {"homologacao": nfse.HOMOLOGACAO, "producao": nfse.PRODUCAO}
VALIDADE_CACHE = 3600  # segundos; certificado renovado no segredo entra em até uma hora


class ErroEvento(ValueError):
    pass


# --- certificado ---------------------------------------------------------------

_certificados: dict[str, tuple[float, nfse.Certificado]] = {}
_sefins: dict[tuple[str, int], nfse.Sefin] = {}


def ler_segredo(nome: str) -> dict:
    """Conteúdo do segredo. Separado para os testes trocarem; o boto3 já vem no runtime da Lambda."""
    import boto3

    resposta = boto3.client("secretsmanager").get_secret_value(SecretId=nome)
    return json.loads(resposta["SecretString"])


def certificado(cnpj: str) -> nfse.Certificado:
    agora = time.monotonic()
    em_cache = _certificados.get(cnpj)
    if em_cache and agora - em_cache[0] < VALIDADE_CACHE:
        return em_cache[1]
    modelo = os.environ.get("NFSE_SEGREDO_CERTIFICADO")
    if not modelo:
        raise ErroEvento("NFSE_SEGREDO_CERTIFICADO não configurada")
    segredo = ler_segredo(modelo.replace("{cnpj}", cnpj))
    try:
        pfx, senha = base64.b64decode(segredo["pfx"]), segredo["senha"]
    except (KeyError, TypeError, ValueError) as e:
        raise nfse.CertificadoInvalido('segredo sem {"pfx": base64, "senha"}') from e
    cert = nfse.Certificado.de_pfx(pfx, senha)
    cert.validar(cnpj)
    _certificados[cnpj] = (agora, cert)
    for chave in [k for k in _sefins if k[0] == cnpj]:
        del _sefins[chave]
    return cert


def sefin(cnpj: str, ambiente: int) -> nfse.Sefin:
    cert = certificado(cnpj)
    if (cnpj, ambiente) not in _sefins:
        _sefins[(cnpj, ambiente)] = nfse.Sefin(cert, ambiente)
    return _sefins[(cnpj, ambiente)]


# --- leitura do evento ---------------------------------------------------------

def _config(evento: dict) -> nfse.Config:
    dados = evento.get("config")
    if dados is None and os.environ.get("NFSE_CONFIG"):
        dados = json.loads(os.environ["NFSE_CONFIG"])
    if dados is None:
        raise ErroEvento("falta config")
    return nfse.config_de_dict(dados)


def _ambiente(evento: dict) -> int:
    nome = evento.get("ambiente", "homologacao")
    if nome not in AMBIENTES:
        raise ErroEvento(f"ambiente inválido: {nome} (homologacao ou producao)")
    if nome == "producao" and os.environ.get("NFSE_PRODUCAO_LIBERADA") != "1":
        raise ErroEvento("produção não liberada nesta função (NFSE_PRODUCAO_LIBERADA)")
    return AMBIENTES[nome]


def _campo(evento: dict, nome: str):
    if evento.get(nome) in (None, ""):
        raise ErroEvento(f"falta {nome}")
    return evento[nome]


def _emissao(evento: dict, ambiente: int) -> nfse.Emissao:
    valor, numero = _campo(evento, "valor"), _campo(evento, "numero")
    try:
        valor = Decimal(str(valor))
        numero = int(numero)
        competencia = date.fromisoformat(evento["competencia"]) if evento.get("competencia") else None
    except (InvalidOperation, ValueError) as e:
        raise ErroEvento(f"valor, numero ou competencia inválido: {e}") from e
    return nfse.Emissao(
        ambiente=ambiente,
        serie=str(_campo(evento, "serie")),
        numero=numero,
        valor=valor,
        descricao=_campo(evento, "descricao"),
        competencia=competencia,
        info_complementar=evento.get("info_complementar"),
    )


def _tomador(evento: dict) -> nfse.Tomador | None:
    return nfse.tomador_de_dict(evento["tomador"]) if evento.get("tomador") else None


# --- ações -----------------------------------------------------------------------

def acao_dps(evento: dict) -> dict:
    cfg, ambiente = _config(evento), _ambiente(evento)
    emissao = _emissao(evento, ambiente)
    dps = nfse.gerar_dps(cfg, certificado(cfg.prestador.cnpj), emissao, _tomador(evento))
    log.info("dps gerada %s", dps.id)
    return {"id_dps": dps.id, "xml_dps": dps.xml.decode()}


def acao_emitir(evento: dict) -> dict:
    cfg, ambiente = _config(evento), _ambiente(evento)
    emissao = _emissao(evento, ambiente)
    cnpj = cfg.prestador.cnpj
    r = nfse.emitir(
        cfg, certificado(cnpj), ambiente, emissao.serie, emissao.numero, emissao.valor, emissao.descricao,
        tomador=_tomador(evento), competencia=emissao.competencia, info_complementar=emissao.info_complementar,
        sefin=sefin(cnpj, ambiente),
    )
    log.info("emitida %s chave %s%s", r.id_dps, r.chave_acesso, " (já existia)" if r.ja_existia else "")
    return {
        "id_dps": r.id_dps,
        "chave_acesso": r.chave_acesso,
        "numero_nfse": r.numero_nfse,
        "ja_existia": r.ja_existia,
        "processada_em": r.processada_em,
        "alertas": r.alertas,
        "xml_nfse": r.xml_nfse.decode(),
    }


def acao_consultar(evento: dict) -> dict:
    cfg, ambiente = _config(evento), _ambiente(evento)
    p = cfg.prestador
    id_dps = evento.get("id_dps") or nfse.id_dps(p.cod_municipio, p.cnpj, str(_campo(evento, "serie")), int(_campo(evento, "numero")))
    chave = sefin(p.cnpj, ambiente).consultar_dps(id_dps)
    log.info("consulta %s: %s", id_dps, chave or "sem nota")
    return {"id_dps": id_dps, "chave_acesso": chave}


def acao_baixar(evento: dict) -> dict:
    cfg, ambiente = _config(evento), _ambiente(evento)
    xml = sefin(cfg.prestador.cnpj, ambiente).baixar_nfse(_campo(evento, "chave"))
    log.info("baixada %s", evento["chave"])
    return {"xml_nfse": xml.decode()}


def acao_danfse(evento: dict) -> dict:
    if evento.get("xml"):
        xml = evento["xml"].encode()
    else:
        xml = acao_baixar(evento)["xml_nfse"].encode()
    pdf = nfse.gerar_danfse(xml)
    log.info("danfse gerado (%d bytes)", len(pdf))
    return {"pdf_base64": base64.b64encode(pdf).decode()}


ACOES = {"emitir": acao_emitir, "dps": acao_dps, "consultar": acao_consultar, "baixar": acao_baixar, "danfse": acao_danfse}


def handler(evento: dict, contexto=None) -> dict:
    acao = evento.get("acao") if isinstance(evento, dict) else None
    if acao not in ACOES:
        return {"ok": False, "erro": "dados", "mensagem": f"acao deve ser uma de {sorted(ACOES)}"}
    try:
        return {"ok": True, **ACOES[acao](evento)}
    except nfse.Rejeicao as e:
        log.warning("%s rejeitada: %s", acao, ", ".join(x.codigo for x in e.erros) or f"HTTP {e.status}")
        return {"ok": False, "erro": "rejeicao", "status": e.status,
                "erros": [{"codigo": x.codigo, "descricao": x.descricao, "complemento": x.complemento} for x in e.erros]}
    except nfse.FalhaComunicacao as e:
        log.warning("%s: falha de comunicação (HTTP %s)", acao, e.status)
        return {"ok": False, "erro": "comunicacao", "status": e.status, "mensagem": "Sefin indisponível; pode repetir"}
    except nfse.CertificadoInvalido as e:
        log.warning("%s: certificado inválido", acao)
        return {"ok": False, "erro": "certificado", "mensagem": str(e)}
    except (ErroEvento, nfse.DadosInvalidos, nfse.EsquemaInvalido, nfse.DanfseIndisponivel) as e:
        log.warning("%s: dados inválidos", acao)
        return {"ok": False, "erro": "dados", "mensagem": str(e)}
