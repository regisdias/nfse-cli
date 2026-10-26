"""Rascunho do e-mail da nota no programa que a pessoa usa. Nunca envia: só abre pronto para ela revisar.

| modo          | onde                     | anexa o PDF                                        |
|---------------|--------------------------|----------------------------------------------------|
| outlook       | Outlook do Mac           | sim (AppleScript)                                  |
| mail          | Mail da Apple            | sim (AppleScript)                                  |
| thunderbird   | Thunderbird              | sim (`thunderbird -compose`)                       |
| gmail         | Gmail no navegador       | não: abre a pasta do PDF para arrastar             |
| outlook-web   | Outlook na web (365)     | não: abre a pasta do PDF para arrastar             |
| eml           | arquivo .eml             | sim (abre em qualquer programa de e-mail)          |
| nenhum        |                          |                                                    |

Nenhum webmail aceita anexo por link: é limite deles, não daqui.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import webbrowser
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from .cli import ErroCli

MODOS = {
    "outlook": "Outlook (Mac)",
    "mail": "Mail da Apple",
    "thunderbird": "Thunderbird",
    "gmail": "Gmail no navegador",
    "outlook-web": "Outlook na web (Microsoft 365)",
    "eml": "Arquivo .eml",
    "nenhum": "Não preparar e-mail",
}


@dataclass
class Rascunho:
    para: str          # endereços separados por vírgula, sem espaços
    cc: str
    assunto: str
    corpo: str         # texto simples
    anexos: list[Path]
    eml: Path          # onde gravar no modo eml


# --- o que existe nesta máquina ----------------------------------------------------------

def _mac() -> bool:
    return platform.system() == "Darwin"


def _app_mac(*nomes: str) -> bool:
    return _mac() and any(Path(base, f"{n}.app").exists() for n in nomes
                          for base in ("/Applications", "/System/Applications", Path.home() / "Applications"))


def binario_thunderbird() -> str | None:
    candidatos = [
        "/Applications/Thunderbird.app/Contents/MacOS/thunderbird",
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files"), "Mozilla Thunderbird", "thunderbird.exe")),
    ]
    return shutil.which("thunderbird") or next((c for c in candidatos if Path(c).exists()), None)


def padrao_do_sistema() -> str | None:
    """Programa que o sistema abre para links mailto:, como um dos MODOS (ou None se não der para saber)."""
    if _mac():
        plist = Path.home() / "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"
        try:
            dados = json.loads(subprocess.run(["plutil", "-convert", "json", "-o", "-", str(plist)],
                                              capture_output=True, text=True, check=True).stdout)
            app = next((h.get("LSHandlerRoleAll", "") for h in dados.get("LSHandlers", [])
                        if h.get("LSHandlerURLScheme") == "mailto"), "")
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
            app = ""
        app = app.lower()
        if not app or app == "com.apple.mail":
            return "mail"  # sem escolha feita, o macOS usa o Mail
        return {"com.microsoft.outlook": "outlook", "org.mozilla.thunderbird": "thunderbird"}.get(app)
    if shutil.which("xdg-mime"):
        r = subprocess.run(["xdg-mime", "query", "default", "x-scheme-handler/mailto"], capture_output=True, text=True)
        if "thunderbird" in r.stdout.lower():
            return "thunderbird"
    return None


def disponiveis() -> list[tuple[str, str, bool]]:
    """(modo, nome, instalado) de todos os modos; web e .eml contam como sempre disponíveis."""
    return [
        ("outlook", MODOS["outlook"], _app_mac("Microsoft Outlook")),
        ("mail", MODOS["mail"], _app_mac("Mail")),
        ("thunderbird", MODOS["thunderbird"], binario_thunderbird() is not None),
        ("gmail", MODOS["gmail"], True),
        ("outlook-web", MODOS["outlook-web"], True),
        ("eml", MODOS["eml"], True),
    ]


def modo_padrao() -> str:
    """Sem `email` na configuração: o padrão do sistema, se for um programa que anexa; senão o .eml."""
    padrao = padrao_do_sistema()
    instalados = {m for m, _, ok in disponiveis() if ok}
    return padrao if padrao in instalados else "eml"


# --- abrir o rascunho ------------------------------------------------------------------------

_SEPARAR = """
on separar(texto)
	if texto is "" then return {}
	set AppleScript's text item delimiters to ","
	set itens to text items of texto
	set AppleScript's text item delimiters to ""
	return itens
end separar
"""

# Valores entram por argv: nada do e-mail é interpolado no código AppleScript.
APPLESCRIPT = {
    "outlook": """
on run argv
	set {para, cc, assunto, corpo} to items 1 thru 4 of argv
	tell application "Microsoft Outlook"
		set msg to make new outgoing message with properties {subject:assunto, content:corpo}
		repeat with endereco in my separar(para)
			make new to recipient at msg with properties {email address:{address:endereco}}
		end repeat
		repeat with endereco in my separar(cc)
			make new cc recipient at msg with properties {email address:{address:endereco}}
		end repeat
		repeat with i from 5 to count of argv
			make new attachment at msg with properties {file:(POSIX file (item i of argv))}
		end repeat
		open msg
	end tell
end run
""" + _SEPARAR,
    "mail": """
on run argv
	set {para, cc, assunto, corpo} to items 1 thru 4 of argv
	tell application "Mail"
		set msg to make new outgoing message with properties {subject:assunto, content:corpo & return & return, visible:true}
		tell msg
			repeat with endereco in my separar(para)
				make new to recipient at end of to recipients with properties {address:endereco}
			end repeat
			repeat with endereco in my separar(cc)
				make new cc recipient at end of cc recipients with properties {address:endereco}
			end repeat
			repeat with i from 5 to count of argv
				make new attachment with properties {file name:((POSIX file (item i of argv)) as alias)} at after the last paragraph
			end repeat
		end tell
		activate
	end tell
end run
""" + _SEPARAR,
}


def _applescript(modo: str, r: Rascunho) -> None:
    if not _mac():
        raise ErroCli(f"{MODOS[modo]} só funciona no macOS; use outro modo (eml, thunderbird, gmail...)")
    corpo = escape(r.corpo).replace("\n", "<br>") if modo == "outlook" else r.corpo
    p = subprocess.run(["osascript", "-", r.para, r.cc, r.assunto, corpo, *map(str, r.anexos)],
                       input=APPLESCRIPT[modo], text=True, capture_output=True)
    if p.returncode:
        raise ErroCli(f"o {MODOS[modo]} recusou o rascunho: {p.stderr.strip()}\nAlternativa: --modo eml")


def comando_thunderbird(binario: str, r: Rascunho, arquivo_corpo: Path) -> list[str]:
    """`-compose` com o corpo num arquivo (message=): o texto livre não passa pela sintaxe de aspas do Thunderbird."""
    def limpo(v: str) -> str:
        return v.replace("'", "’")
    partes = [f"to='{r.para}'", f"subject='{limpo(r.assunto)}'", f"message='{arquivo_corpo}'", "format=2"]
    if r.cc:
        partes.append(f"cc='{r.cc}'")
    if r.anexos:
        partes.append("attachment='" + ",".join(a.resolve().as_uri() for a in r.anexos) + "'")
    return [binario, "-compose", ",".join(partes)]


def _thunderbird(r: Rascunho) -> None:
    binario = binario_thunderbird()
    if not binario:
        raise ErroCli("Thunderbird não encontrado; use outro modo")
    pasta = Path(tempfile.mkdtemp(prefix="nfse-email-"))
    corpo = pasta / "corpo.txt"
    corpo.write_text(r.corpo, encoding="utf-8")
    subprocess.Popen(comando_thunderbird(binario, r, corpo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def url_web(modo: str, r: Rascunho) -> str:
    if modo == "gmail":
        return "https://mail.google.com/mail/?" + urlencode(
            {"view": "cm", "fs": "1", "to": r.para, "cc": r.cc, "su": r.assunto, "body": r.corpo})
    return "https://outlook.office.com/mail/deeplink/compose?" + urlencode(
        {"to": r.para, "cc": r.cc, "subject": r.assunto, "body": r.corpo})


def _mostrar_na_pasta(arquivo: Path) -> None:
    if _mac():
        subprocess.run(["open", "-R", str(arquivo)], check=False)
    elif platform.system() == "Windows":
        subprocess.run(["explorer", f"/select,{arquivo}"], check=False)
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(arquivo.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def gravar_eml(r: Rascunho) -> None:
    msg = EmailMessage()
    msg["To"], msg["Subject"], msg["Date"] = r.para, r.assunto, formatdate(localtime=True)
    if r.cc:
        msg["Cc"] = r.cc
    msg["X-Unsent"] = "1"  # o Outlook clássico e o Thunderbird abrem como rascunho
    msg.set_content(r.corpo)
    for a in r.anexos:
        msg.add_attachment(a.read_bytes(), maintype="application", subtype=a.suffix[1:], filename=a.name)
    r.eml.write_bytes(bytes(msg))


def abrir(modo: str, r: Rascunho) -> str:
    """Prepara o rascunho e devolve o que dizer à pessoa."""
    anexos = ", ".join(a.name for a in r.anexos)
    if modo in APPLESCRIPT:
        _applescript(modo, r)
        return f"Rascunho aberto no {MODOS[modo]}, com {anexos}. Cada execução cria outro rascunho."
    if modo == "thunderbird":
        _thunderbird(r)
        return f"Rascunho aberto no Thunderbird, com {anexos}."
    if modo in ("gmail", "outlook-web"):
        webbrowser.open(url_web(modo, r))
        _mostrar_na_pasta(r.anexos[0])
        return (f"Nova mensagem aberta no {MODOS[modo]}, já com destinatário, assunto e texto. O navegador não "
                f"deixa anexar sozinho: arraste {anexos} da pasta que abriu para a mensagem.")
    if modo == "eml":
        gravar_eml(r)
        return f"E-mail pronto em {r.eml}, com {anexos}. Abra o arquivo no seu programa de e-mail."
    if modo == "nenhum":
        return "E-mail desligado para este cliente (email = \"nenhum\")."
    raise ErroCli(f"modo de e-mail desconhecido: {modo} ({', '.join(MODOS)})")


def cmd_programas(args) -> None:
    padrao = padrao_do_sistema()
    print("Programas de e-mail nesta máquina:")
    for modo, nome, ok in disponiveis():
        if ok:
            marca = "  <- padrão do sistema para e-mail" if modo == padrao else ""
            print(f"  {modo:<12} {nome}{marca}")
    print("\nO padrão do sistema nem sempre é o que a pessoa usa: pergunte.")
