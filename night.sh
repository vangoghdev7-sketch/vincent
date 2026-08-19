#!/usr/bin/env bash
# Roteiro da noite: aproveita as horas de sono em duas marchas.
#
#   1ª marcha — overnight.py: o Claude em MODO AGENTE fechando FEATURES inteiras
#               do backlog (uma por commit, com portão de testes).
#   2ª marcha — self_improve.py: quando o backlog acaba (ou o Claude começa a
#               falhar), cai pros micro-fixes cirúrgicos, que são baratos e
#               aceitam cérebro alternativo pelo gateway.
#
# Tudo é commitado na branch self-improve, cada passo com teste antes. Pra
# acompanhar de manhã:  tail -n 200 ~/.vincent/overnight.log
# Pra parar:            pkill -f overnight.py ; pkill -f self_improve.py

set -uo pipefail
REPO=/home/snop/vincent-cli
LOG=~/.vincent/overnight.log
cd "$REPO" || exit 1

HORAS_FEATURES=${1:-6}     # teto da 1ª marcha
CICLOS_FIX=${2:-25}        # ciclos da 2ª marcha

mkdir -p ~/.vincent
{
  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "◈ NOITE DE $(date '+%d/%m %H:%M') — features por ${HORAS_FEATURES}h, depois ${CICLOS_FIX} micro-fixes"
  echo "════════════════════════════════════════════════════════════════"
} >> "$LOG"

# ── 1ª marcha: features de verdade ───────────────────────────────────────────
python3 overnight.py --hours "$HORAS_FEATURES" --max-tasks 20 --max-fails 4 >> "$LOG" 2>&1
echo "[night.sh] overnight.py terminou com código $?" >> "$LOG"

# ── 2ª marcha: micro-fixes cirúrgicos ────────────────────────────────────────
# O gateway expõe o antigravity funcionando (o gh/* devolve 400 nesta máquina),
# então a cascata é claude → antigravity → local (repo é público, conta é do dono).
python3 self_improve.py --cycles "$CICLOS_FIX" --brains claude,antigravity,local >> "$LOG" 2>&1
echo "[night.sh] self_improve.py terminou com código $?" >> "$LOG"

# ── Aplica no Vincent instalado, pra de manhã o comando `vincent` já rodar novo ─
LIVE=/home/snop/.local/share/pipx/venvs/vincent-cli/lib/python3.13/site-packages/vincent
if [ -d "$LIVE" ]; then
  cp -f "$REPO"/src/vincent/*.py "$LIVE"/ 2>/dev/null
  [ -d "$REPO/src/vincent/static" ] && cp -rf "$REPO"/src/vincent/static/. "$LIVE"/static/ 2>/dev/null
  echo "[night.sh] pacote instalado atualizado a partir do src" >> "$LOG"
fi

{
  echo
  echo "◈ RESUMO DA NOITE — $(date '+%d/%m %H:%M')"
  git -C "$REPO" log --oneline --since="12 hours ago" --no-decorate | sed 's/^/    /'
  echo "    total de commits na noite: $(git -C "$REPO" log --oneline --since='12 hours ago' | wc -l)"
} >> "$LOG" 2>&1
