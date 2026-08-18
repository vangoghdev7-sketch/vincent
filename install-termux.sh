#!/data/data/com.termux/files/usr/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Vincent CLI 4.0 — Van Gogh 'Starry Night' Edition
# Script de Instalação Automática para Termux (Android / ADB Root)
# ══════════════════════════════════════════════════════════════════════════════

set -e

echo -e "\033[38;5;33m"
echo "  ★   .  ☆  *  .  ★  .  *  ☆  .  ★  .  *  ☆  .  ★"
echo "  ██╗   ██╗██╗███╗   ██╗ ██████╗███████╗███╗   ██╗████████╗"
echo "  ██║   ██║██║████╗  ██║██╔════╝██╔════╝████╗  ██║╚══██╔══╝"
echo "  ██║   ██║██║██╔██╗ ██║██║     █████╗  ██╔██╗ ██║   ██║   "
echo "  ╚██╗ ██╔╝██║██║╚██╗██║██║     ██╔══╝  ██║╚██╗██║   ██║   "
echo "   ╚████╔╝ ██║██║ ╚████║╚██████╗███████╗██║ ╚████║   ██║   "
echo "    ╚═══╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   "
echo -e "\033[38;5;220m  ◈ INSTALADOR TERMUX • V I N C E N T   C L I   v 4 . 0 ◈\033[0m\n"

echo -e "\033[38;5;254m[1/4] Atualizando repositórios e instalando dependências base...\033[0m"
pkg update -y
pkg install -y python python-pip git clang libffi openssl

echo -e "\033[38;5;254m[2/4] Instalando pacotes Python necessários...\033[0m"
pip install --upgrade pip
pip install pyserial psutil pyyaml setuptools

echo -e "\033[38;5;254m[3/4] Instalando pacote Vincent CLI em modo editável...\033[0m"
VINCENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pip install -e "$VINCENT_DIR"

echo -e "\033[38;5;254m[4/4] Configurando launcher global no Termux...\033[0m"
mkdir -p "$PREFIX/bin"
cat << 'EOF' > "$PREFIX/bin/vincent"
#!/data/data/com.termux/files/usr/bin/python3
import sys
from vincent.cli import main
if __name__ == '__main__':
    sys.exit(main())
EOF
chmod +x "$PREFIX/bin/vincent"

echo -e "\n\033[38;5;48m✓ Instalação concluída com sucesso no Termux!\033[0m"
echo -e "\033[38;5;220mPara iniciar o Vincent CLI, digite no terminal:\033[0m"
echo -e "  \033[38;5;33mvincent\033[0m\n"
