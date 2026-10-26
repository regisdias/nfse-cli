"""Zip da Lambda (ou camada) com a biblioteca e as dependências compiladas para o Linux da AWS.

    python lambda/empacotar.py                      # dist/nfse-lambda-arm64-py3.13.zip
    python lambda/empacotar.py --danfse             # com reportlab, para a ação "danfse"
    python lambda/empacotar.py --arquitetura x86_64 --python 3.12
    python lambda/empacotar.py --camada             # conteúdo em python/, para usar como Lambda layer

lxml e cryptography têm partes em C: o pip baixa as rodas manylinux da arquitetura pedida, então dá para
empacotar de um Mac. O zip é determinístico (ordem e datas fixas): conteúdo igual, hash igual, e o deploy
não reenvia nem toca a função.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PLATAFORMAS = {"arm64": "manylinux2014_aarch64", "x86_64": "manylinux2014_x86_64"}
FORA_DO_PACOTE = ("bin", "nfse_cli")  # o comando `nfse` não serve na Lambda
DATA_FIXA = (1980, 1, 1, 0, 0, 0)


def pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "--disable-pip-version-check", "-q", *args], check=True)


def zipar(origem: Path, destino: Path, prefixo: str) -> None:
    arquivos = sorted(p for p in origem.rglob("*") if p.is_file())
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arquivo in arquivos:
            info = zipfile.ZipInfo(prefixo + arquivo.relative_to(origem).as_posix(), DATA_FIXA)
            info.external_attr = (0o755 if arquivo.stat().st_mode & 0o111 else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, arquivo.read_bytes())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arquitetura", choices=sorted(PLATAFORMAS), default="arm64")
    ap.add_argument("--python", default="3.13", help="versão do runtime da Lambda (padrão 3.13)")
    ap.add_argument("--danfse", action="store_true", help="inclui o reportlab (ação danfse)")
    ap.add_argument("--camada", action="store_true", help="conteúdo em python/, para Lambda layer")
    ap.add_argument("--saida", type=Path, default=RAIZ / "dist")
    args = ap.parse_args()

    nome = f"nfse-lambda-{args.arquitetura}-py{args.python}" + ("-danfse" if args.danfse else "") + ("-camada" if args.camada else "")
    with tempfile.TemporaryDirectory(prefix="nfse-lambda-") as tmp:
        tmp = Path(tmp)
        pip("wheel", "--no-deps", "-w", str(tmp / "rodas"), str(RAIZ))
        roda = next((tmp / "rodas").glob("*.whl"))
        pip(
            "install", "--target", str(tmp / "pacote"), "--no-compile",
            "--platform", PLATAFORMAS[args.arquitetura], "--implementation", "cp",
            "--python-version", args.python, "--only-binary=:all:",
            f"{roda}[danfse]" if args.danfse else str(roda),
        )
        for nome_fora in FORA_DO_PACOTE:
            shutil.rmtree(tmp / "pacote" / nome_fora, ignore_errors=True)
        for cache in (tmp / "pacote").rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        # direct_url.json grava o caminho temporário da roda: mudaria o zip a cada build.
        for url in (tmp / "pacote").glob("*.dist-info/direct_url.json"):
            url.unlink()
            record = url.with_name("RECORD")
            linhas = record.read_text().splitlines(keepends=True)
            record.write_text("".join(l for l in linhas if not l.startswith(f"{url.parent.name}/direct_url.json,")))

        args.saida.mkdir(parents=True, exist_ok=True)
        destino = args.saida / f"{nome}.zip"
        zipar(tmp / "pacote", destino, "python/" if args.camada else "")
    print(f"{destino} ({destino.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
