#!/usr/bin/env bash
# Instala o nfse-cli (comando `nfse` + skill para agentes) só no seu usuário, sem sudo.
#
#   curl -fsSL https://raw.githubusercontent.com/regisdias/nfse-cli/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/regisdias/nfse-cli/main/install.sh | bash -s -- --desinstalar
#
# Variáveis (opcionais): NFSE_ORIGEM (de onde instalar o pacote), NFSE_DIR (ambiente Python),
# NFSE_BIN (onde fica o comando), NFSE_PYTHON (qual python usar).
set -euo pipefail

# Zip do GitHub em vez de git+https: não exige o git instalado.
ORIGEM="${NFSE_ORIGEM:-https://github.com/regisdias/nfse-cli/archive/refs/heads/main.zip}"
DIR="${NFSE_DIR:-$HOME/.local/share/nfse-cli}"
BIN="${NFSE_BIN:-$HOME/.local/bin}"

info() { printf '\033[1m%s\033[0m\n' "$*"; }
erro() { printf '\033[31merro:\033[0m %s\n' "$*" >&2; exit 1; }

desinstalar() {
  if [ -x "$DIR/venv/bin/nfse" ]; then
    "$DIR/venv/bin/nfse" skill remover || true
  fi
  if [ -L "$BIN/nfse" ] && [ "$(readlink "$BIN/nfse")" = "$DIR/venv/bin/nfse" ]; then
    rm "$BIN/nfse"
  fi
  rm -rf "$DIR"
  info "nfse-cli removido."
  echo "A configuração em ~/.config/nfse-cli/ (certificado, clientes, notas) foi mantida; apague à mão se quiser."
  if command -v security >/dev/null 2>&1; then
    echo "A senha do certificado continua no Keychain: security delete-generic-password -s nfse-cli -a <CNPJ>"
  fi
}

if [ "${1:-}" = "--desinstalar" ]; then
  desinstalar
  exit 0
fi

# Python 3.11 ou mais novo
PY="${NFSE_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidato in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidato" >/dev/null 2>&1 && "$candidato" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PY="$candidato"
      break
    fi
  done
fi
if [ -z "$PY" ]; then
  erro "precisa do Python 3.11 ou mais novo. No macOS: brew install python. No Ubuntu/Debian: sudo apt install python3 python3-venv."
fi

info "Instalando o nfse-cli"
cat <<EOF
  Ambiente Python isolado   $DIR/venv
  Pacotes                   nfse-cli, lxml, cryptography, reportlab (e as dependências deles)
  Comando                   $BIN/nfse
  Skill                     nas pastas do Claude Code, Codex e Antigravity que existirem
  Nada fora do seu usuário, nada com sudo. Para remover, rode de novo com: bash -s -- --desinstalar
EOF

mkdir -p "$DIR" "$BIN"
"$PY" -m venv "$DIR/venv" || erro "não consegui criar o ambiente Python (no Ubuntu/Debian: sudo apt install python3-venv)"
"$DIR/venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$DIR/venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade "nfse-cli[danfse] @ $ORIGEM"
ln -sf "$DIR/venv/bin/nfse" "$BIN/nfse"

echo
"$BIN/nfse" skill instalar

echo
info "Pronto: $("$BIN/nfse" --versao)"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    echo "Atenção: $BIN não está no seu PATH. Acrescente ao ~/.zshrc (ou ~/.bashrc):"
    echo "  export PATH=\"$BIN:\$PATH\""
    ;;
esac
cat <<'EOF'

Próximo passo: abra seu agente (Claude Code, Codex ou Antigravity) e peça "configura minha nota fiscal".
Sem agente: nfse configurar certificado <arquivo.pfx>  (veja o README).
EOF
