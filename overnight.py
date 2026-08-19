#!/usr/bin/env python3
"""
LOOP NOTURNO do Vincent — o Claude em MODO AGENTE construindo features de verdade.

Diferença pro self_improve.py: aquele pede UM search/replace por ciclo, então só
consegue parir micro-fix (guard de None, try/except). Este aqui roda o `claude`
headless COM ferramentas (Read/Edit/Write/Bash), então ele consegue criar arquivo,
mexer em vários módulos e fechar uma FEATURE inteira por ciclo — que é o que falta
pro Vincent virar um CLI completo no nível de Claude Code / OpenCode / Copilot CLI.

Cada tarefa do backlog:
  1. checkpoint do git (SHA atual) e exige árvore limpa
  2. `claude -p "<tarefa>"` em modo agente, dentro do repo
  3. PORTÃO DE TESTES: py_compile + import do pacote + pytest + smoke do REPL sem TTY
  4. ✅ verde  -> git commit, marca a tarefa como feita no backlog
     ❌ vermelho -> uma nova tentativa com o erro em mãos; falhou de novo, git reset --hard
                    pro checkpoint (a tarefa volta pro backlog, nada de lixo meio-pronto)
  5. loga tudo com timestamp

Bounded de propósito: teto de tarefas, teto de horas, e para sozinho depois de N
falhas seguidas. Loop infinito às cegas REGRIDE o código — já vimos isso acontecer.

Uso:
  python3 overnight.py                       # backlog padrão, 8h de teto
  python3 overnight.py --hours 6 --max-tasks 12
  python3 overnight.py --backlog outro.md --model opus
  python3 overnight.py --dry-run             # só mostra o que faria
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO = "/home/snop/vincent-cli"
PKG = os.path.join(REPO, "src", "vincent")
VENVPY = "/home/snop/.local/share/pipx/venvs/vincent-cli/bin/python"
BACKLOG = os.path.join(REPO, "overnight_backlog.md")
LOGDIR = os.path.expanduser("~/.vincent")
LOGFILE = os.path.join(LOGDIR, "overnight.log")
BRANCH = "self-improve"

# Ferramentas liberadas pro Claude headless. Sem isso ele só conversa e não edita nada.
# A flag é variádica (`--allowedTools <tools...>`), então vai como lista de argumentos.
ALLOWED_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash", "MultiEdit", "TodoWrite"]

C = {"g": "\033[92m", "r": "\033[91m", "y": "\033[93m", "b": "\033[94m",
     "v": "\033[95m", "d": "\033[90m", "0": "\033[0m", "bold": "\033[1m"}

TASK_PROMPT = """Você é um engenheiro Python sênior trabalhando no repositório `{repo}` (branch `{branch}`).

O projeto é o **Vincent**, um CLI agêntico em Python. A meta declarada do dono é que ele fique no
nível dos concorrentes grandes: **Claude Code CLI, GitHub Copilot CLI, OpenCode, Kimi Code**.
O dono reclama constantemente que a interface é "primitiva". Trate UX de terminal como requisito de
primeira classe, não como enfeite.

Mapa do código (o pacote fica em `src/vincent/`):
  cli.py          REPL principal e dispatch dos comandos /...
  interactive.py  camada prompt_toolkit (picker fuzzy, autocomplete, bottom toolbar)
  tui_app.py      TUI full-screen em Textual (`vincent --tui`)
  marketplace.py  catálogo de skills instaláveis
  agent.py        loop agêntico (agentic_run) e tool-calling
  agent_tools.py  implementação das ferramentas (bash, arquivos, git, web)
  models.py       roteamento de modelos (Ollama :11434 + gateway OmniRoute :20128)
  ui.py           tema "Noite Estrelada", HUD, caixas, spinner
  web_ui.py       GUI web Flask + static/app.html
  skills.py plugins.py caveman.py memory.py telemetry.py devices.py config.py

SUA TAREFA NESTE CICLO:
{task}

REGRAS:
- Implemente de ponta a ponta. Nada de TODO, nada de stub, nada de "deixei preparado pra depois".
- Leia o código existente antes de escrever. Reaproveite os helpers e o tema que já existem
  (as cores e os widgets vêm de `ui.py`; não invente uma paleta nova).
- Dependências disponíveis no venv: prompt_toolkit, textual, rich, click, flask. NÃO adicione outras.
- Tudo em Python 3.13. Textos de interface em português-BR, no tom já usado no projeto.
- Degrade com elegância: se não houver TTY, ou se uma lib opcional faltar, o caminho antigo tem que
  continuar funcionando em vez de estourar exceção.
- Escreva ou estenda testes em `tests/` cobrindo o que você fez e RODE-OS antes de terminar:
    PYTHONPATH={repo}/src {venvpy} -m pytest {repo}/tests -q
- NÃO rode `git commit`, `git checkout`, `git reset` nem `git push`. O supervisor cuida do git.
- NÃO copie nada pro site-packages do pipx. O supervisor cuida disso.
- NÃO mexa em arquivos fora de `{repo}`.

Quando terminar, responda em uma linha curta o que você mudou.
"""

RETRY_SUFFIX = """

ATENÇÃO — sua tentativa anterior FOI REJEITADA porque quebrou o portão de testes.
Saída real da falha:
---
{error}
---
Conserte a causa e entregue a tarefa funcionando. Se a abordagem anterior era inviável, troque de
abordagem em vez de insistir nela.
"""


# ─────────────────────────────── infra ────────────────────────────────────────

def log(msg, color=None, quiet=False):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    plain = f"[{stamp}] {msg}"
    os.makedirs(LOGDIR, exist_ok=True)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as fh:
            fh.write(plain + "\n")
    except OSError:
        pass
    if not quiet:
        tint = C.get(color or "", "")
        print(f"{tint}{plain}{C['0']}", flush=True)


def sh(cmd, timeout=None, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(cmd, 124, out, err + f"\n[timeout após {timeout}s]")


def git(*args, timeout=120):
    return sh(["git", "-C", REPO, *args], timeout=timeout)


def find_claude():
    """O path do nvm muda quando o node é reinstalado — procure de verdade."""
    cands = [shutil.which("claude"),
             "/home/snop/.nvm/versions/node/v20.20.2/bin/claude"]
    cands += sorted(glob.glob("/home/snop/.nvm/versions/node/*/bin/claude"), reverse=True)
    cands += [os.path.expanduser("~/.local/bin/claude"), "/usr/local/bin/claude"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ─────────────────────────────── backlog ──────────────────────────────────────

TASK_RE = re.compile(r"^\s*-\s*\[(?P<mark>[ xX~])\]\s*(?P<text>.+?)\s*$")


def read_backlog(path):
    """Devolve [(numero_da_linha, feito?, texto)] das linhas '- [ ] tarefa'."""
    if not os.path.isfile(path):
        return []
    tasks = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh):
            m = TASK_RE.match(line)
            if m:
                tasks.append((lineno, m.group("mark").lower() in ("x", "~"), m.group("text")))
    return tasks


def mark_backlog(path, lineno, mark, note=""):
    """Marca a linha da tarefa como feita (x) ou tentada-e-falhou (~)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    if lineno >= len(lines):
        return
    m = TASK_RE.match(lines[lineno])
    if not m:
        return
    text = m.group("text")
    if note and note not in text:
        text = f"{text}  <!-- {note} -->"
    indent = lines[lineno][:len(lines[lineno]) - len(lines[lineno].lstrip())]
    lines[lineno] = f"{indent}- [{mark}] {text}\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


# ─────────────────────────── portão de testes ─────────────────────────────────

# Testes que já falhavam ANTES do loop começar. Um portão que exige suíte 100%
# verde numa suíte que nasce com falha reprova tudo e reverte a noite inteira;
# o que interessa é regressão — teste que passava e parou de passar.
_BASELINE_FAILURES = set()

_FAIL_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)


def _failing_tests(py, env):
    """Conjunto de ids de teste falhando agora. None se o pytest nem rodou."""
    testdir = os.path.join(REPO, "tests")
    if not os.path.isdir(testdir):
        return set()
    r = sh([py, "-m", "pytest", testdir, "-q", "--tb=no", "-p", "no:cacheprovider"],
           env=env, timeout=1200)
    saida = (r.stdout or "") + (r.stderr or "")
    if r.returncode not in (0, 1, 5):  # 2=interrompido, 3=erro interno, 4=uso errado
        return None
    return {m.group(1) for m in _FAIL_RE.finditer(saida)}


def snapshot_baseline(py=None, env=None):
    """Fotografa as falhas pré-existentes. Chamado uma vez, antes do 1º ciclo."""
    global _BASELINE_FAILURES
    py = py or (VENVPY if os.path.exists(VENVPY) else sys.executable)
    env = env or dict(os.environ, PYTHONPATH=os.path.join(REPO, "src"),
                      OLLAMA_HOST="127.0.0.1:11434", PYTHONWARNINGS="ignore")
    f = _failing_tests(py, env)
    _BASELINE_FAILURES = f if f is not None else set()
    return _BASELINE_FAILURES


def gate():
    """Roda tudo que prova que o Vincent continua de pé. (ok, relatório)"""
    env = dict(os.environ,
               PYTHONPATH=os.path.join(REPO, "src"),
               OLLAMA_HOST="127.0.0.1:11434",
               PYTHONWARNINGS="ignore")
    py = VENVPY if os.path.exists(VENVPY) else sys.executable

    pyfiles = sorted(glob.glob(os.path.join(PKG, "*.py")))
    r = sh([py, "-m", "py_compile", *pyfiles], timeout=180)
    if r.returncode != 0:
        return False, "py_compile falhou:\n" + (r.stderr or "")[-1500:]

    mods = ("import vincent.cli, vincent.agent, vincent.models, vincent.ui, "
            "vincent.agent_tools, vincent.caveman, vincent.memory, vincent.skills, "
            "vincent.plugins, vincent.telemetry, vincent.config; print('imports ok')")
    r = sh([py, "-c", mods], env=env, timeout=180)
    if r.returncode != 0:
        return False, "import do pacote falhou:\n" + (r.stderr or "")[-1500:]

    # Módulos opcionais: só reprovam se EXISTIREM e não importarem.
    for opt in ("interactive", "marketplace", "tui_app", "web_ui"):
        if os.path.exists(os.path.join(PKG, f"{opt}.py")):
            r = sh([py, "-c", f"import vincent.{opt}; print('ok')"], env=env, timeout=180)
            if r.returncode != 0:
                return False, f"import de vincent.{opt} falhou:\n" + (r.stderr or "")[-1200:]

    falhas = _failing_tests(py, env)
    if falhas is None:
        return False, "não consegui rodar o pytest"
    novas = falhas - _BASELINE_FAILURES
    if novas:
        return False, ("testes que ANTES passavam agora falham:\n  "
                       + "\n  ".join(sorted(novas)))

    # Smoke do REPL sem TTY: tem que abrir, aceitar comando e sair sem traceback.
    r = sh([py, "-m", "vincent.cli"], env=env, timeout=180, input="/help\n/exit\n")
    combined = (r.stdout or "") + (r.stderr or "")
    if "Traceback (most recent call last)" in combined:
        return False, "REPL sem TTY estourou traceback:\n" + combined[-1800:]

    return True, "py_compile + imports + pytest + smoke do REPL: tudo verde"


# ──────────────────────────────── ciclo ───────────────────────────────────────

def run_claude(claude_bin, prompt, model, timeout):
    env = dict(os.environ, PATH=os.path.dirname(claude_bin) + ":" + os.environ.get("PATH", ""))
    cmd = [claude_bin, "-p", prompt,
           "--allowedTools", *ALLOWED_TOOLS,
           "--permission-mode", "acceptEdits"]
    if model:
        cmd += ["--model", model]
    r = sh(cmd, cwd=REPO, env=env, timeout=timeout)
    return r


def tree_dirty():
    return bool(git("status", "--porcelain").stdout.strip())


def do_task(claude_bin, task, model, timeout, dry_run=False):
    """Executa uma tarefa do backlog. Devolve (sucesso, detalhe)."""
    checkpoint = git("rev-parse", "HEAD").stdout.strip()
    if not checkpoint:
        return False, "não consegui ler o HEAD do git"
    if tree_dirty():
        log("  árvore suja antes de começar — guardando em stash", "y")
        git("stash", "push", "-u", "-m", f"overnight-autostash-{int(time.time())}")

    prompt = TASK_PROMPT.format(repo=REPO, branch=BRANCH, venvpy=VENVPY, task=task)
    if dry_run:
        log(f"  [dry-run] rodaria o claude com {len(prompt)} chars de prompt", "d")
        return True, "dry-run"

    error_ctx = ""
    for attempt in (1, 2):
        label = "tentativa" if attempt == 1 else "REtentativa (com o erro em mãos)"
        log(f"  🧠 {label} — claude em modo agente…", "v")
        t0 = time.time()
        r = run_claude(claude_bin, prompt + (RETRY_SUFFIX.format(error=error_ctx) if error_ctx else ""),
                       model, timeout)
        dur = time.time() - t0
        head = (r.stdout or "").strip().replace("\n", " ")[:180]
        log(f"  ↳ claude saiu com código {r.returncode} em {dur:.0f}s: {head}", "d")

        if r.returncode != 0 and not tree_dirty():
            error_ctx = ((r.stderr or "") + (r.stdout or ""))[-1500:]
            log(f"  ⚠ claude falhou e não mudou nada", "y")
            if attempt == 2:
                return False, f"claude falhou 2x (rc={r.returncode})"
            continue

        if not tree_dirty():
            log("  ⚠ nenhuma alteração no repositório — tarefa não produziu código", "y")
            return False, "nenhuma alteração produzida"

        ok, report = gate()
        if ok:
            log(f"  ✓ portão de testes verde ({report})", "g")
            return True, report

        log(f"  ✗ portão de testes vermelho", "r")
        log(f"    {report.splitlines()[0] if report else ''}", "d")
        error_ctx = report
        git("reset", "--hard", checkpoint)
        git("clean", "-fd", "src", "tests")
        if attempt == 2:
            return False, f"reprovado no portão 2x: {report[:400]}"

    return False, "esgotou as tentativas"


def apply_to_live():
    """Copia src/vincent/*.py pro pacote instalado do pipx (é lá que o `vincent` roda)."""
    live = "/home/snop/.local/share/pipx/venvs/vincent-cli/lib/python3.13/site-packages/vincent"
    if not os.path.isdir(live):
        return 0
    n = 0
    for src in sorted(glob.glob(os.path.join(PKG, "*.py"))):
        try:
            shutil.copy2(src, os.path.join(live, os.path.basename(src)))
            n += 1
        except OSError as exc:
            log(f"  ⚠ não consegui copiar {os.path.basename(src)}: {exc}", "y")
    static_src = os.path.join(PKG, "static")
    if os.path.isdir(static_src):
        try:
            shutil.copytree(static_src, os.path.join(live, "static"), dirs_exist_ok=True)
        except OSError:
            pass
    return n


def main():
    ap = argparse.ArgumentParser(description="Loop noturno: Claude em modo agente evoluindo o Vincent.")
    ap.add_argument("--backlog", default=BACKLOG, help="arquivo markdown com as tarefas")
    ap.add_argument("--hours", type=float, default=8.0, help="teto de horas (padrão 8)")
    ap.add_argument("--max-tasks", type=int, default=20, help="teto de tarefas (padrão 20)")
    ap.add_argument("--model", default="", help="modelo do claude (ex: opus, sonnet). vazio = padrão")
    ap.add_argument("--task-timeout", type=int, default=2400, help="timeout por tarefa em s (padrão 40min)")
    ap.add_argument("--max-fails", type=int, default=4, help="para depois de N falhas seguidas")
    ap.add_argument("--no-live", action="store_true", help="não copiar pro pipx no fim")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log("", quiet=True)
    log("═" * 70, "d")
    log("◈ LOOP NOTURNO DO VINCENT — Claude em modo agente", "bold")
    log(f"  backlog={args.backlog} teto={args.hours}h/{args.max_tasks} tarefas modelo={args.model or 'padrão'}", "d")

    claude_bin = find_claude()
    if not claude_bin:
        log("✗ binário do `claude` não encontrado. Abortando.", "r")
        return 1
    log(f"  claude: {claude_bin}", "d")

    cur = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if cur != BRANCH:
        log(f"✗ esperava estar na branch {BRANCH}, mas estou em {cur}. Abortando por segurança.", "r")
        return 1

    base = snapshot_baseline()
    if base:
        log(f"  {len(base)} teste(s) já falhavam antes de começar — serão ignorados "
            f"(só regressão reprova): {', '.join(sorted(base)[:4])}"
            + (" …" if len(base) > 4 else ""), "y")

    ok, report = gate()
    if not ok:
        log(f"✗ a baseline JÁ está quebrada — não dá pra distinguir dano novo de antigo:\n{report}", "r")
        return 1
    log(f"✓ baseline sadia ({report})", "g")

    deadline = time.time() + args.hours * 3600
    done = fails = streak = 0

    while True:
        if time.time() > deadline:
            log("⏰ teto de horas atingido — encerrando.", "y")
            break
        if done + fails >= args.max_tasks:
            log("🎯 teto de tarefas atingido — encerrando.", "y")
            break
        if streak >= args.max_fails:
            log(f"🛑 {streak} falhas seguidas — parando pra não estragar o código.", "r")
            break

        pending = [(ln, txt) for ln, feito, txt in read_backlog(args.backlog) if not feito]
        if not pending:
            log("📭 backlog vazio — nada mais a fazer.", "g")
            break

        lineno, task = pending[0]
        restante = (deadline - time.time()) / 3600
        log("", quiet=True)
        log(f"── Tarefa {done + fails + 1} ({len(pending)} na fila, {restante:.1f}h restantes)", "b")
        log(f"   {task}", "bold")

        sucesso, detalhe = do_task(claude_bin, task, args.model, args.task_timeout, args.dry_run)

        if sucesso and not args.dry_run:
            git("add", "-A", "src", "tests", "docs", "pyproject.toml", "README.md")
            msg = f"feat(overnight): {task[:110]}"
            git("-c", "user.name=vincent-overnight", "-c", "user.email=overnight@vincent",
                "commit", "-m", msg, "-m", f"Portão de testes: {detalhe[:300]}")
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            mark_backlog(args.backlog, lineno, "x", f"feito em {sha}")
            log(f"  ✅ commitado como {sha}", "g")
            done += 1
            streak = 0
        elif sucesso:
            done += 1
        else:
            mark_backlog(args.backlog, lineno, "~", f"falhou: {detalhe[:80]}")
            log(f"  ❌ tarefa devolvida ao backlog: {detalhe[:200]}", "r")
            fails += 1
            streak += 1

    log("", quiet=True)
    log(f"◈ FIM DO LOOP — {done} tarefas concluídas, {fails} falhadas", "bold")
    recent = git("log", "--oneline", "-15", "--no-decorate").stdout.strip()
    log("últimos commits:\n" + recent, "d")

    if done and not args.no_live and not args.dry_run:
        n = apply_to_live()
        log(f"📦 {n} arquivos copiados pro Vincent instalado (pipx) — o `vincent` já roda o código novo", "g")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("⏹ interrompido. Os commits já feitos estão salvos no git.", "y")
        sys.exit(130)
