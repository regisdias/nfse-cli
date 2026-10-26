"""Fluxo completo de emissão: monta, assina, confere, consulta e envia."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lxml import etree

from .assinatura import assinar, verificar
from .certificado import Certificado
from .dps import NS, Emissao, Prestador, Servico, Tomador, montar_dps, serializar
from .esquema import validar_dps
from .sefin import Sefin, descompactar


@dataclass(frozen=True)
class Config:
    prestador: Prestador
    servico: Servico


@dataclass(frozen=True)
class DpsAssinada:
    id: str
    xml: bytes


@dataclass(frozen=True)
class Resultado:
    id_dps: str
    chave_acesso: str
    numero_nfse: str | None
    xml_dps: bytes
    xml_nfse: bytes
    ja_existia: bool
    """True quando a DPS já tinha virado nota antes (envio repetido após timeout)."""
    alertas: list | None = None
    processada_em: str | None = None


def gerar_dps(cfg: Config, cert: Certificado, emissao: Emissao, tomador: Tomador | None, algoritmo: str = "sha256") -> DpsAssinada:
    """DPS assinada e conferida (assinatura e XSD) sobre os bytes finais, sem enviar."""
    cert.validar(cfg.prestador.cnpj)
    raiz = montar_dps(cfg.prestador, cfg.servico, tomador, emissao)
    assinar(raiz, cert, algoritmo)
    xml = serializar(raiz)
    verificar(xml)
    validar_dps(xml)
    return DpsAssinada(id=raiz.find(f"{{{NS}}}infDPS").get("Id"), xml=xml)


def numero_nfse(xml_nfse: bytes) -> str | None:
    return etree.fromstring(xml_nfse).findtext(f".//{{{NS}}}nNFSe")


def emitir(
    cfg: Config,
    cert: Certificado,
    ambiente: int,
    serie: str,
    numero: int,
    valor: Decimal | str,
    descricao: str,
    tomador: Tomador | None = None,
    competencia: date | None = None,
    info_complementar: str | None = None,
    sefin: Sefin | None = None,
) -> Resultado:
    emissao = Emissao(
        ambiente=ambiente,
        serie=serie,
        numero=numero,
        valor=Decimal(valor),
        descricao=descricao,
        competencia=competencia,
        info_complementar=info_complementar,
    )
    dps = gerar_dps(cfg, cert, emissao, tomador)
    sefin = sefin or Sefin(cert, ambiente)

    # Se um envio anterior desta mesma DPS deu timeout mas gerou a nota, devolve a nota.
    chave = sefin.consultar_dps(dps.id)
    if chave:
        xml_nfse = sefin.baixar_nfse(chave)
        return Resultado(dps.id, chave, numero_nfse(xml_nfse), dps.xml, xml_nfse, ja_existia=True)

    resposta = sefin.enviar_dps(dps.xml)
    xml_nfse = descompactar(resposta["nfseXmlGZipB64"])
    return Resultado(
        id_dps=dps.id,
        chave_acesso=resposta["chaveAcesso"],
        numero_nfse=numero_nfse(xml_nfse),
        xml_dps=dps.xml,
        xml_nfse=xml_nfse,
        ja_existia=False,
        alertas=resposta.get("alertas"),
        processada_em=resposta.get("dataHoraProcessamento"),
    )
