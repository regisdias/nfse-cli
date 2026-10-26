"""Cliente HTTP da Sefin Nacional (mTLS com o certificado A1), só com stdlib.

Separa os dois tipos de falha, porque o tratamento é oposto:
- `Rejeicao`: a Sefin recusou a DPS (códigos E...). Tentar de novo não adianta.
- `FalhaComunicacao`: rede, timeout, 5xx. Pode tentar de novo, mas antes de
  reenviar consulte a DPS: o envio anterior pode ter gerado a nota.
"""

from __future__ import annotations

import base64
import gzip
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .certificado import Certificado
from .dps import HOMOLOGACAO, PRODUCAO

URLS = {
    HOMOLOGACAO: "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
    PRODUCAO: "https://sefin.nfse.gov.br/SefinNacional",
}


@dataclass(frozen=True)
class Erro:
    codigo: str
    descricao: str
    complemento: str | None = None

    def __str__(self) -> str:
        return f"{self.codigo}: {self.descricao}" + (f" ({self.complemento})" if self.complemento else "")


class Rejeicao(Exception):
    def __init__(self, erros: list[Erro], status: int, corpo: dict | str):
        self.erros = erros
        self.status = status
        self.corpo = corpo
        super().__init__("; ".join(map(str, erros)) or f"HTTP {status}")


class FalhaComunicacao(Exception):
    def __init__(self, mensagem: str, status: int | None = None):
        self.status = status
        super().__init__(mensagem)


@dataclass
class Resposta:
    status: int
    corpo: dict = field(default_factory=dict)


def compactar(xml: bytes) -> str:
    return base64.b64encode(gzip.compress(xml)).decode()


def descompactar(valor: str) -> bytes:
    return gzip.decompress(base64.b64decode(valor))


def _erros(corpo: dict) -> list[Erro]:
    lista = corpo.get("erros") or corpo.get("erro") or []
    if isinstance(lista, dict):
        lista = [lista]
    erros = []
    for item in lista:
        if not isinstance(item, dict):
            erros.append(Erro("?", str(item)))
            continue
        def pega(*chaves):
            return next((item[k] for k in chaves if item.get(k)), None)
        erros.append(Erro(
            codigo=str(pega("Codigo", "codigo") or "?"),
            descricao=str(pega("Descricao", "descricao", "mensagem") or ""),
            complemento=pega("Complemento", "complemento"),
        ))
    return erros


class Sefin:
    def __init__(self, cert: Certificado, ambiente: int, timeout: float = 60):
        if ambiente not in URLS:
            raise ValueError(f"ambiente inválido: {ambiente}")
        self.ambiente = ambiente
        self.base = URLS[ambiente]
        self.timeout = timeout
        self._ctx = cert.contexto_tls()

    def _requisicao(self, metodo: str, caminho: str, corpo: dict | None = None) -> Resposta:
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(
            self.base + caminho,
            data=dados,
            method=metodo,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout) as r:
                status, bruto = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, bruto = e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FalhaComunicacao(f"{metodo} {caminho}: {e}") from e

        try:
            json_corpo = json.loads(bruto) if bruto.strip() else {}
        except ValueError:
            json_corpo = None
        if status >= 500 or (json_corpo is None and status >= 400):
            texto = bruto[:500].decode("utf-8", "replace")
            raise FalhaComunicacao(f"{metodo} {caminho}: HTTP {status} {texto}", status)
        return Resposta(status, json_corpo if isinstance(json_corpo, dict) else {"dados": json_corpo})

    def enviar_dps(self, xml_assinado: bytes) -> dict:
        """POST /nfse. Devolve o JSON de sucesso (chaveAcesso, nfseXmlGZipB64...)."""
        r = self._requisicao("POST", "/nfse", {"dpsXmlGZipB64": compactar(xml_assinado)})
        if r.status >= 400 or not r.corpo.get("chaveAcesso"):
            raise Rejeicao(_erros(r.corpo), r.status, r.corpo)
        return r.corpo

    def consultar_dps(self, id_dps: str) -> str | None:
        """GET /dps/{id}: chave de acesso da NFS-e gerada pela DPS, ou None se não existe."""
        r = self._requisicao("GET", f"/dps/{id_dps}")
        if r.status == 404:
            return None
        if r.status >= 400:
            raise Rejeicao(_erros(r.corpo), r.status, r.corpo)
        return r.corpo.get("chaveAcesso")

    def baixar_nfse(self, chave: str) -> bytes:
        """GET /nfse/{chave}: XML da NFS-e."""
        r = self._requisicao("GET", f"/nfse/{chave}")
        if r.status >= 400 or not r.corpo.get("nfseXmlGZipB64"):
            raise Rejeicao(_erros(r.corpo), r.status, r.corpo)
        return descompactar(r.corpo["nfseXmlGZipB64"])
