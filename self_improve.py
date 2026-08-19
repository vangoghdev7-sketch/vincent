#!/usr/bin/env python3
"""
Loop de AUTO-MELHORIA do Vincent — bounded, git-checkpointed, 3 cérebros.

Cada ciclo:
  1. escolhe um arquivo do pacote (rotativo)
  2. pede a um cérebro (cascata Claude -> OmniRoute -> qwen3:8b local) UMA melhoria
     pequena, no formato JSON {file, rationale, search, replace}
  3. aplica o patch (search/replace literal e único)
  4. RODA TESTES (py_compile de tudo + import do pacote)
  5. ✅ passou -> git commit (checkpoint)   ❌ quebrou -> git revert do arquivo
  6. loga o ciclo

Seguro por design: opera no repo git ~/vincent-cli/src (NÃO no Vincent instalado),
cada mudança é um commit reversível, testa a cada passo, e é LIMITADO a N ciclos.
Pare quando quiser com Ctrl+C. Nada de loop infinito às cegas.

Uso:
  python3 self_improve.py --cycles 5
  python3 self_improve.py --cycles 3 --brains claude
  python3 self_improve.py --cycles 5 --brains omniroute,local   # sem gastar Claude
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request

REPO = "/home/snop/vincent-cli"
PKG = os.path.join(REPO, "src", "vincent")
CLAUDE = "/home/snop/.nvm/versions/node/v20.20.2/bin/claude"
NODE_BIN = "/home/snop/.nvm/versions/node/v20.20.2/bin"
OMNI_URL = "http://localhost:20128/v1/chat/completions"
OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
LOCAL_MODEL = "qwen3:8b"
BRANCH = "self-improve"

CANDIDATES = ["agent.py", "models.py", "cli.py", "ui.py", "agent_tools.py",
              "caveman.py", "memory.py", "skills.py", "plugins.py", "telemetry.py",
              "devices.py", "config.py", "env_detect.py"]

C = {"g": "\033[92m", "r": "\033[91m", "y": "\033[93m", "b": "\033[94m",
     "d": "\033[90m", "0": "\033[0m", "bold": "\033[1m"}

PROMPT = """Você é um engenheiro Python sênior evoluindo o "Vincent" — um CLI agêntico — para se tornar
um CLI COMPLETO e competitivo, no nível de Claude Code / aider / OpenCode.
Abaixo está o conteúdo ATUAL do arquivo `{fname}`. Proponha UMA única melhoria concreta e de ALTO VALOR
que aproxime o Vincent desses concorrentes. Priorize nesta ordem:
1. Bug real / crash / edge case não tratado;
2. UX/DX do CLI (mensagens de erro claras e acionáveis, feedback melhor, ajuda/exemplos, cores/formatação);
3. Robustez (timeouts, retries, validação de entrada, degradação graciosa);
4. Funcionalidade que falta vs. concorrentes (ex: melhor manejo de contexto, atalhos, flags úteis, cache).
Faça uma mudança CIRÚRGICA (não reescreva o arquivo todo). NÃO invente APIs inexistentes — use só o que já existe no código/stdlib. A mudança tem que manter o código 100% válido e não quebrar nada existente.

Responda APENAS com UM objeto JSON (sem mais nada, sem markdown), no formato EXATO:
{{"file": "{fname}", "rationale": "<1 frase do porquê>", "search": "<trecho LITERAL e ÚNICO do código atual>", "replace": "<código novo>"}}

Regras do "search":
- Copie um trecho EXATO do arquivo (mesma indentação, mesmas quebras de linha).
- Tem que ser ÚNICO no arquivo (não repetido).
- Curto (3 a 15 linhas), suficiente pra localizar sem ambiguidade.
- Se não houver melhoria óbvia e segura, responda com search e replace vazios ("").

--- CONTEÚDO DE {fname} ---
{content}
--- FIM ---"""


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def git(*args):
    return sh(["git", "-C", REPO, *args])


def ensure_branch():
    cur = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if cur != BRANCH:
        # cria a partir da branch atual (baseline funcional) ou faz checkout se já existe
        if git("rev-parse", "--verify", BRANCH).returncode == 0:
            git("checkout", BRANCH)
        else:
            git("checkout", "-b", BRANCH)
    return git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def run_tests():
    pyfiles = [os.path.join(PKG, f) for f in os.listdir(PKG) if f.endswith(".py")]
    r = sh([sys.executable, "-m", "py_compile", *pyfiles])
    if r.returncode != 0:
        return False, "py_compile falhou: " + r.stderr.strip()[-240:]
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "src"),
               OLLAMA_HOST="127.0.0.1:11434")
    r = sh([sys.executable, "-c",
            "import vincent.cli, vincent.agent, vincent.models, vincent.ui, "
            "vincent.agent_tools, vincent.caveman, vincent.memory; print('ok')"],
           env=env, timeout=60)
    if r.returncode != 0:
        return False, "import falhou: " + r.stderr.strip()[-240:]
    return True, "py_compile + import OK"


def _find_claude():
    """Acha o binário do claude de forma robusta (o path do nvm às vezes muda
    durante reinstalação → antes o loop crashava com FileNotFoundError)."""
    import shutil, glob
    for c in ([shutil.which("claude"), CLAUDE]
              + sorted(glob.glob("/home/snop/.nvm/versions/node/*/bin/claude"))):
        if c and os.path.exists(c):
            return c
    return None


def brain_claude(prompt):
    claude = _find_claude()
    if not claude:
        return None  # claude indisponível agora → cascata cai pro próximo cérebro
    env = dict(os.environ, PATH=NODE_BIN + ":" + os.environ.get("PATH", ""))
    try:
        r = sh([claude, "-p", prompt, "--model", "sonnet"], cwd=REPO, env=env, timeout=240)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


def brain_http(url, model, prompt):
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "stream": False, "temperature": 0.2}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            d = json.loads(resp.read().decode())
        return (d.get("choices", [{}])[0].get("message", {}).get("content", "") or None)
    except Exception:
        return None


# Rotas do gateway usadas como cérebro. O painel do OmniRoute expõe o Antigravity
# (OAuth do Google já ligado pelo dono) e ele responde em ~7s — contra ~50s do 7B
# local. As rotas gh/* estão devolvendo 400 "model not supported" nesta máquina,
# então não entram na cascata.
# Rotas do gateway em ordem de preferência. O tier grátis entra em cooldown por
# modelo ("All credentials for X are cooling down"), então uma rota só não basta:
# tentamos as irmãs antes de desistir e cair pro próximo cérebro.
ANTIGRAVITY_MODELS = [
    "antigravity/claude-sonnet-4-6",
    "antigravity/gemini-3.6-flash-high",
    "auto/best-coding",
    "auto/coding",
]


def ask_brains(prompt, order):
    for name in order:
        if name == "claude":
            out = brain_claude(prompt)
        elif name == "antigravity":
            out = None
            for rota in ANTIGRAVITY_MODELS:
                out = brain_http(OMNI_URL, rota, prompt)
                if out:
                    break
        elif name == "omniroute":
            out = brain_http(OMNI_URL, "auto", prompt)
        elif name == "local":
            out = brain_http(OLLAMA_URL, LOCAL_MODEL, prompt + "\n/no_think")
        else:
            out = None
        if out:
            return name, out
    return None, None


def parse_edit(text):
    # tira bloco ```json ... ``` se houver
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    # maior objeto {...} contendo "file"
    braces = re.findall(r"\{.*\}", text, re.DOTALL)
    candidates.extend(braces)
    for cand in candidates:
        for attempt in (cand, cand.replace("\n", "\\n")):
            try:
                obj = json.loads(attempt)
                if isinstance(obj, dict) and "file" in obj:
                    return obj
            except Exception:
                continue
    return None


def apply_edit(edit):
    fname = os.path.basename((edit.get("file") or "").strip())
    search = edit.get("search") or ""
    replace = edit.get("replace") or ""
    if not fname or not search.strip():
        return None, "sem melhoria proposta (search vazio)"
    path = os.path.join(PKG, fname)
    if not os.path.isfile(path):
        return None, f"arquivo inexistente: {fname}"
    src = open(path, encoding="utf-8").read()
    n = src.count(search)
    if n == 0:
        return None, "search não bate com o código atual"
    if n > 1:
        return None, f"search ambíguo (aparece {n}x)"
    open(path, "w", encoding="utf-8").write(src.replace(search, replace, 1))
    return fname, "aplicado"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=5, help="número de ciclos (padrão 5)")
    ap.add_argument("--brains", default="claude,omniroute,local",
                    help="cascata de cérebros (padrão: claude,omniroute,local)")
    args = ap.parse_args()
    order = [b.strip() for b in args.brains.split(",") if b.strip()]

    print(f"{C['bold']}{C['b']}◈ LOOP DE AUTO-MELHORIA DO VINCENT{C['0']}")
    print(f"{C['d']}repo: {REPO} | cérebros: {'→'.join(order)} | ciclos: {args.cycles}{C['0']}")
    branch = ensure_branch()
    print(f"{C['d']}branch: {branch}{C['0']}")
    ok, msg = run_tests()
    if not ok:
        print(f"{C['r']}✗ baseline já está quebrado: {msg}. Abortando.{C['0']}")
        return 1
    print(f"{C['g']}✓ baseline sadio ({msg}){C['0']}\n")

    stats = {"commit": 0, "skip": 0, "revert": 0}
    for i in range(args.cycles):
        fname = CANDIDATES[i % len(CANDIDATES)]
        path = os.path.join(PKG, fname)
        if not os.path.isfile(path):
            continue
        content = open(path, encoding="utf-8").read()
        print(f"{C['b']}── Ciclo {i+1}/{args.cycles} — alvo: {fname}{C['0']}")
        prompt = PROMPT.format(fname=fname, content=content[:24000])

        t0 = time.time()
        brain, out = ask_brains(prompt, order)
        if not out:
            print(f"  {C['y']}⚠ nenhum cérebro respondeu (rate-limit/offline). pulando.{C['0']}")
            stats["skip"] += 1
            continue
        edit = parse_edit(out)
        if not edit:
            print(f"  {C['y']}⚠ {brain} não devolveu JSON válido. pulando.{C['0']}")
            stats["skip"] += 1
            continue

        applied, why = apply_edit(edit)
        rationale = (edit.get("rationale") or "").strip()[:100]
        print(f"  {C['d']}🧠 {brain} ({time.time()-t0:.0f}s): {rationale}{C['0']}")
        if not applied:
            print(f"  {C['y']}⚠ {why}. pulando.{C['0']}")
            stats["skip"] += 1
            continue

        ok, tmsg = run_tests()
        if ok:
            git("add", os.path.join("src", "vincent", applied))
            git("-c", "user.name=vincent-loop", "-c", "user.email=loop@vincent",
                "commit", "-m", f"auto({applied}): {rationale or 'melhoria'} [{brain}]")
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            print(f"  {C['g']}✓ testes passaram → commit {sha}{C['0']}\n")
            stats["commit"] += 1
        else:
            git("checkout", "--", os.path.join("src", "vincent", applied))
            print(f"  {C['r']}✗ testes quebraram ({tmsg}) → revertido{C['0']}\n")
            stats["revert"] += 1

    print(f"{C['bold']}◈ FIM.{C['0']} commits: {C['g']}{stats['commit']}{C['0']} | "
          f"revertidos: {C['r']}{stats['revert']}{C['0']} | pulados: {C['y']}{stats['skip']}{C['0']}")
    log = git("log", "--oneline", f"-{max(1, stats['commit'])}", "--no-decorate")
    if stats["commit"]:
        print(f"{C['d']}últimos commits:\n{log.stdout.strip()}{C['0']}")
        print(f"\n{C['b']}Pra aplicar as melhorias no Vincent instalado:{C['0']} "
              f"copie src/vincent/*.py pro site-packages, ou reinstale o pacote.")
        print(f"{C['b']}Pra reverter TUDO:{C['0']} git -C {REPO} reset --hard working-patches-2026-08-18")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{C['y']}⏹ interrompido pelo usuário. Commits já feitos estão salvos no git.{C['0']}")
