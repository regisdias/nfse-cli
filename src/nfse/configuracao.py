"""Configuração a partir de dicionário: o mesmo formato no TOML da CLI e no JSON de quem chama a Lambda.

{
  "prestador": {"cnpj", "cod_municipio", "op_simp_nac", "reg_ap_trib_sn"?, "reg_esp_trib"?, "im"?, "fone"?, "email"?},
  "servico": {"c_trib_nac", "c_nbs"?, "c_trib_mun"?, "cod_municipio_prestacao"?, "trib_issqn"?,
              "tp_ret_issqn"?, "p_aliq"?, "tot_trib": {"modo": "sn"|"percentual"|"valor"|"nao_informado", ...}}
}
"""

from __future__ import annotations

from decimal import Decimal

from .dps import DadosInvalidos, Endereco, Prestador, Servico, Tomador, TotTrib
from .emissao import Config


def _exigir(d: dict, chave: str, onde: str):
    if not isinstance(d, dict) or d.get(chave) in (None, ""):
        raise DadosInvalidos(f"falta {onde}.{chave}")
    return d[chave]


def tot_trib_de_dict(d: dict) -> TotTrib:
    modo = d.get("modo", "sn")
    if modo == "sn":
        return TotTrib.sn(str(_exigir(d, "percentual", "servico.tot_trib")))
    if modo in ("percentual", "valor"):
        valores = [str(_exigir(d, k, "servico.tot_trib")) for k in ("federal", "estadual", "municipal")]
        return TotTrib.percentual(*valores) if modo == "percentual" else TotTrib.valor(*valores)
    if modo == "nao_informado":
        return TotTrib.nao_informado()
    raise DadosInvalidos(f"servico.tot_trib.modo desconhecido: {modo}")


def tomador_de_dict(d: dict) -> Tomador:
    end = d.get("endereco")
    return Tomador(
        documento=str(_exigir(d, "documento", "tomador")),
        nome=_exigir(d, "nome", "tomador"),
        email=d.get("email"),
        fone=d.get("fone"),
        im=d.get("im"),
        endereco=Endereco(**{k: str(v) for k, v in end.items()}) if end else None,
    )


def config_de_dict(d: dict) -> Config:
    p, s = _exigir(d, "prestador", "config"), _exigir(d, "servico", "config")
    prestador = Prestador(
        cnpj=str(_exigir(p, "cnpj", "prestador")),
        cod_municipio=str(_exigir(p, "cod_municipio", "prestador")),
        op_simp_nac=int(_exigir(p, "op_simp_nac", "prestador")),
        reg_esp_trib=int(p.get("reg_esp_trib", 0)),
        reg_ap_trib_sn=p.get("reg_ap_trib_sn"),
        im=p.get("im"),
        fone=p.get("fone"),
        email=p.get("email"),
    )
    servico = Servico(
        c_trib_nac=str(_exigir(s, "c_trib_nac", "servico")),
        cod_municipio_prestacao=str(s.get("cod_municipio_prestacao", prestador.cod_municipio)),
        tot_trib=tot_trib_de_dict(s.get("tot_trib", {})),
        c_nbs=s.get("c_nbs"),
        c_trib_mun=s.get("c_trib_mun"),
        trib_issqn=int(s.get("trib_issqn", 1)),
        tp_ret_issqn=int(s.get("tp_ret_issqn", 1)),
        p_aliq=Decimal(str(s["p_aliq"])) if "p_aliq" in s else None,
    )
    return Config(prestador, servico)
