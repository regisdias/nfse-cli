"""Emissão de NFS-e pela API da Sefin Nacional.

Biblioteca sem estado: numeração, série e configuração entram como parâmetro;
quem guarda é quem chama (a CLI, o painel).
"""

from .assinatura import AssinaturaInvalida, assinar, verificar
from .certificado import Certificado, CertificadoInvalido
from .dps import (
    HOMOLOGACAO,
    LEIAUTE_ANTERIOR,
    LEIAUTE_NT009,
    LEIAUTE_POR_AMBIENTE,
    LEIAUTES,
    PRODUCAO,
    DadosInvalidos,
    Emissao,
    Endereco,
    Prestador,
    Servico,
    Tomador,
    TotTrib,
    id_dps,
    montar_dps,
)
from .configuracao import config_de_dict, tomador_de_dict
from .danfse import DanfseIndisponivel, gerar_danfse
from .emissao import Config, DpsAssinada, Resultado, emitir, gerar_dps
from .esquema import EsquemaInvalido, validar_dps
from .sefin import Erro, FalhaComunicacao, Rejeicao, Sefin

__version__ = "0.2.0"

__all__ = [
    "HOMOLOGACAO", "PRODUCAO",
    "LEIAUTES", "LEIAUTE_ANTERIOR", "LEIAUTE_NT009", "LEIAUTE_POR_AMBIENTE",
    "AssinaturaInvalida", "CertificadoInvalido", "DanfseIndisponivel", "DadosInvalidos", "EsquemaInvalido",
    "FalhaComunicacao", "Rejeicao", "Erro",
    "Certificado", "Config", "DpsAssinada", "Emissao", "Endereco", "Prestador",
    "Resultado", "Sefin", "Servico", "Tomador", "TotTrib",
    "assinar", "config_de_dict", "emitir", "gerar_danfse", "gerar_dps", "id_dps", "montar_dps", "tomador_de_dict", "validar_dps", "verificar",
]
