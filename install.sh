#!/usr/bin/env bash
# Vincent CLI — instalador universal de uma linha.
#   curl -fsSL https://raw.githubusercontent.com/vangoghdev7-sketch/vincent/master/install.sh | bash
# Detecta Termux / Linux / macOS, instala dependências, deixa o binário `vincent`
# no PATH e diz o próximo passo (configurar chave). Idempotente: rodar de novo
# só atualiza o checkout existente.
set -e

REPO_URL="https://github.com/vangoghdev7-sketch/vincent.git"
INSTALL_DIR="${VINCENT_INSTALL_DIR:-$HOME/vincent-cli}"

echo "◈ Vincent CLI — instalador universal"

# ── 1. Detecta plataforma ──────────────────────────────────────────────
if [ -n "$PREFIX" ] && [ -d "$PREFIX/../usr" ] && command -v termux-info >/dev/null 2>&1; then
    PLATFORM="termux"
elif [ "$(uname -s)" = "Darwin" ]; then
    PLATFORM="macos"
else
    PLATFORM="linux"
fi
echo "  plataforma detectada: $PLATFORM"

# ── 2. Garante python3/pip/git (instala só no Termux, que é sandbox do   ──
#    usuário; em Linux/macOS só avisa — script de instalação não deve     ──
#    sair rodando apt/brew como root sem pedir).                         ──
case "$PLATFORM" in
    termux)
        pkg update -y && pkg install -y python python-pip git
        ;;
    *)
        for bin in python3 pip3 git; do
            if ! command -v "$bin" >/dev/null 2>&1; then
                echo "✗ Falta '$bin' no PATH. Instale com o gerenciador de pacotes do seu sistema e rode de novo." >&2
                exit 1
            fi
        done
        ;;
esac

# ── 3. Clona (ou reusa) o repo ─────────────────────────────────────────
# Se este script já está rodando de dentro de um checkout do Vincent
# (ex: ./install.sh local), reusa em vez de clonar de novo.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/pyproject.toml" ] && grep -q '^name = "vincent-cli"' "$SELF_DIR/pyproject.toml" 2>/dev/null; then
    INSTALL_DIR="$SELF_DIR"
    echo "  usando checkout local: $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
    echo "  checkout existente encontrado em $INSTALL_DIR, atualizando..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "  clonando em $INSTALL_DIR..."
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

# ── 4. Instala o pacote ─────────────────────────────────────────────────
# Termux primeiro e SEM pipx: pipx isola em venv próprio, que não enxerga
# pacote nenhum instalado via `pkg` — psutil (extensão C) não tem wheel
# pra Android no PyPI, pip/uv tentam compilar do zero e quebram com
# "platform android is not supported". python-psutil do repositório do
# Termux (TUR/main) já vem precompilado; plain pip (sem venv/isolamento,
# igual o Termux já opera por padrão) enxerga esse pacote direto.
cd "$INSTALL_DIR"
if [ "$PLATFORM" = "termux" ]; then
    pkg install -y python-psutil
    pip install --upgrade pip
    pip install pyserial pyyaml setuptools
    pip install -e .
elif command -v pipx >/dev/null 2>&1; then
    pipx install --force .
else
    python3 -m pip install --user -e .
    echo "  (sem pipx — instalado via pip --user; garanta que ~/.local/bin está no PATH)"
fi

echo ""
echo "✓ Vincent CLI instalado."
echo "  Rode: vincent"
echo "  Pra configurar chaves de API: vincent --vault  (ou /vault dentro do REPL)"
