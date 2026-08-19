"""
Vincent CLI 4.0 — Agentic Local Tools Arsenal.
Provides sandboxed execution tools for autonomous multi-turn reasoning and coding:
- ListDirTool: intelligent directory mapping (ignores .git, node_modules, __pycache__, .venv)
- ReadFileTool: safe file reading with slice support and line numbers
- GrepTool: global codebase search with regex and context lines
- BashTool: subprocess execution for linters, tests, and environment checks
- ApplyDiffTool: surgical search-and-replace block patching (and unified diff support)
- GitOps tools: git_status, git_diff, git_commit (checkpoint), git_rollback (single-file undo)
"""

import os
import re
import glob
import json
import difflib
import subprocess
import fnmatch
import urllib.request
import urllib.parse
import html as html_lib
from html.parser import HTMLParser
from typing import Dict, Any, List, Optional, Tuple

IGNORE_PATTERNS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".eggs", "*.egg-info",
    "dist", "build", ".claude-flow", ".vincent"
}

def is_ignored(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        for pat in IGNORE_PATTERNS:
            if fnmatch.fnmatch(part, pat):
                return True
    return False


# ─── 1. ListDirTool ───────────────────────────────────────────────────────────

def tool_list_dir(path: str = ".", max_depth: int = 2) -> Dict[str, Any]:
    """Lista diretórios e arquivos recursivamente ignorando artefatos temporários."""
    root_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(root_path):
        return {"error": f"Diretório não encontrado: {path}"}

    entries = []
    root_depth = root_path.rstrip(os.path.sep).count(os.path.sep)

    for root, dirs, files in os.walk(root_path):
        # Filtra diretórios ignorados in-place
        dirs[:] = [d for d in dirs if not is_ignored(d)]
        
        current_depth = root.count(os.path.sep) - root_depth
        if current_depth > max_depth:
            continue

        rel_root = os.path.relpath(root, root_path)
        if rel_root != "." and is_ignored(rel_root):
            continue

        for f in files:
            if not is_ignored(f):
                rel_file = os.path.normpath(os.path.join(rel_root, f))
                full_path = os.path.join(root, f)
                try:
                    size = os.path.getsize(full_path)
                    entries.append({"path": rel_file, "type": "file", "size_bytes": size})
                except Exception:
                    entries.append({"path": rel_file, "type": "file", "size_bytes": 0})

        for d in dirs:
            rel_dir = os.path.normpath(os.path.join(rel_root, d))
            entries.append({"path": rel_dir, "type": "dir"})

    return {
        "root": root_path,
        "total_entries": len(entries),
        "entries": entries[:200]  # Limite de segurança de contexto
    }


# ─── 2. ReadFileTool ──────────────────────────────────────────────────────────

def tool_read_file(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
    """Lê o conteúdo de um arquivo do disco com numeração de linhas e suporte a fatiamento."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(abs_path):
        return {"error": f"Arquivo não encontrado: {path}"}

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        s_idx = max(1, start_line) if start_line is not None else 1
        e_idx = min(total_lines, end_line) if end_line is not None else min(total_lines, s_idx + 300)

        selected_lines = lines[s_idx - 1:e_idx]
        formatted = "".join([f"{i:4d} | {line}" for i, line in enumerate(selected_lines, start=s_idx)])

        return {
            "path": abs_path,
            "total_lines": total_lines,
            "start_line": s_idx,
            "end_line": e_idx,
            "content": formatted,
            "raw_content": "".join(selected_lines)
        }
    except Exception as e:
        return {"error": f"Falha ao ler arquivo {path}: {str(e)}"}


# ─── 3. GrepTool ──────────────────────────────────────────────────────────────

def tool_grep(pattern: str, path: str = ".", is_regex: bool = False, case_insensitive: bool = True) -> Dict[str, Any]:
    """Realiza busca global por texto ou regex em todo o projeto."""
    if not pattern or not pattern.strip():
        return {"error": "Padrão de busca vazio."}
    root_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(root_path):
        return {"error": f"Caminho não encontrado: {path}"}

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern if is_regex else re.escape(pattern), flags)
    except Exception as e:
        return {"error": f"Regex inválido: {str(e)}"}

    matches = []
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if not is_ignored(d)]
        for file in files:
            if is_ignored(file):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, root_path)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, start=1):
                        if regex.search(line):
                            matches.append({
                                "file": rel_path,
                                "line_number": line_no,
                                "line_content": line.strip()
                            })
                            if len(matches) >= 50:
                                break
            except Exception:
                continue
        if len(matches) >= 50:
            break

    return {
        "pattern": pattern,
        "total_matches": len(matches),
        "matches": matches
    }


# ─── 4. BashTool ──────────────────────────────────────────────────────────────

def tool_bash(command: str, timeout_sec: int = 600, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Executa comandos de terminal em subprocesso isolado com controle de timeout."""
    if not command or not command.strip():
        return {"error": "Comando vazio."}
    try:
        timeout_sec = int(timeout_sec)
    except (TypeError, ValueError):
        timeout_sec = 600
    if timeout_sec <= 0:
        timeout_sec = 600
    work_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    if cwd and not os.path.isdir(work_dir):
        return {"error": f"Diretório de trabalho não encontrado: {cwd}"}
    
    # Bloqueio simples de comandos perigosos.
    # ponytail: denylist por substring, contornável (ex: python -c os.remove).
    # Agora todo chat cai aqui (não só /act) — se precisar de garantia real,
    # trocar por allowlist ou sandbox (bwrap/firejail) quando isso importar.
    dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:"]
    if any(d in command for d in dangerous):
        return {"error": "Comando bloqueado por motivos de segurança do sistema."}

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec
        )
        return {
            "command": command,
            "cwd": work_dir,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:8000],
            "stderr": proc.stderr[:8000],
            "success": proc.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "error": f"Comando excedeu o tempo limite de {timeout_sec}s.",
            "exit_code": -1
        }
    except Exception as e:
        return {"error": f"Falha na execução: {str(e)}"}


# ─── 5. ApplyDiffTool (Search & Replace Patching) ──────────────────────────────

def tool_apply_diff(path: str, search_block: Optional[str] = None, replace_block: Optional[str] = None, diff_content: Optional[str] = None) -> Dict[str, Any]:
    """
    Aplica modificações cirúrgicas em arquivos por Search & Replace ou Unified Diff.
    Garante preservação de indentação e contexto.
    """
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(abs_path):
        return {"error": f"Arquivo não encontrado: {path}"}

    # Método 1: Search and Replace exato
    if search_block is not None and replace_block is not None:
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                original_text = f.read()

            if search_block not in original_text:
                return {
                    "error": "Bloco de busca não encontrado no arquivo. Verifique espaços e indentação exatos.",
                    "success": False
                }

            # Garante que ocorre apenas uma vez para evitar edições ambíguas
            occurrences = original_text.count(search_block)
            if occurrences > 1:
                return {
                    "error": f"O bloco de busca foi encontrado {occurrences} vezes. Forneça mais linhas de contexto ao redor.",
                    "success": False
                }

            new_text = original_text.replace(search_block, replace_block, 1)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_text)

            return {
                "path": abs_path,
                "success": True,
                "message": f"Alteração cirúrgica aplicada com sucesso em {os.path.basename(abs_path)}.",
                "bytes_written": len(new_text)
            }
        except Exception as e:
            return {"error": f"Falha no search & replace: {str(e)}", "success": False}

    # Método 2: Patch unificado (patch utility)
    if diff_content:
        try:
            proc = subprocess.run(
                ["patch", "--fuzz=0", "-p0", "-o", "-", abs_path],
                input=diff_content,
                capture_output=True,
                text=True,
                timeout=30
            )
            if proc.returncode != 0:
                return {"error": f"Patch falhou: {proc.stderr or proc.stdout}", "success": False}

            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(proc.stdout)

            return {
                "path": abs_path,
                "success": True,
                "message": f"Diff unificado aplicado com sucesso em {os.path.basename(abs_path)}.",
                "bytes_written": len(proc.stdout)
            }
        except Exception as e:
            return {"error": f"Falha ao executar patch: {str(e)}", "success": False}

    return {"error": "Parâmetros insuficientes. Forneça (search_block e replace_block) ou diff_content."}


# ─── 5b. Preview de edição (diff ANTES de escrever no disco) ──────────────────

EDIT_TOOL_ALIASES = {"apply_diff", "patch", "replace"}
# Rollback também reescreve o arquivo — e é o único que APAGA trabalho. Sem
# preview o usuário aprova a perda às cegas, que é justamente o que isto evita.
ROLLBACK_TOOL_ALIASES = {"git_rollback", "gitrollback", "git_undo"}


def is_edit_tool(tool_name: str) -> bool:
    """A ferramenta escreve/altera arquivo? (usado pra decidir se há preview)"""
    name = str(tool_name or "").strip().lower()
    return name in EDIT_TOOL_ALIASES or name in ROLLBACK_TOOL_ALIASES


def build_edit_preview(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Diff unificado do que a ferramenta VAI escrever — sem tocar no disco.

    Devolve "" quando não dá pra prever (não é edição, arquivo inexistente,
    bloco de busca que não casa, diff cru ilegível): nesse caso quem chama
    simplesmente não mostra preview, em vez de estourar.
    """
    if not is_edit_tool(tool_name) or not isinstance(arguments, dict):
        return ""

    if str(tool_name).strip().lower() in ROLLBACK_TOOL_ALIASES:
        # `git diff -R` é literalmente o que o `git checkout --` do rollback vai
        # escrever no disco: o que está prestes a ser descartado sai em vermelho.
        path = str(arguments.get("path") or "")
        if not path:
            return ""
        res = _run_git(["diff", "-R", "--", path], cwd=arguments.get("cwd"))
        return res.get("stdout", "") if res.get("success") else ""

    # O modelo já mandou um diff unificado pronto — mostra ele mesmo.
    raw_diff = arguments.get("diff") or arguments.get("diff_content")
    if raw_diff:
        return str(raw_diff)

    search_block = arguments.get("search_block")
    replace_block = arguments.get("replace_block")
    if search_block is None or replace_block is None:
        return ""

    path = str(arguments.get("path") or "")
    abs_path = os.path.abspath(os.path.expanduser(path)) if path else ""
    if not abs_path or not os.path.isfile(abs_path):
        return ""

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception:
        return ""

    # Mesma regra do `tool_apply_diff`: bloco ausente ou ambíguo não vira edição.
    # Sem isto o preview mostraria uma mudança que a ferramenta vai recusar.
    if original.count(str(search_block)) != 1:
        return ""
    updated = original.replace(str(search_block), str(replace_block), 1)
    if updated == original:
        return ""

    # splitlines() sem keepends + lineterm="": arquivo sem quebra de linha final
    # não gruda duas linhas do diff numa só.
    name = os.path.basename(abs_path)
    return "\n".join(difflib.unified_diff(
        original.splitlines(),
        updated.splitlines(),
        fromfile=f"a/{name}", tofile=f"b/{name}", n=3, lineterm=""
    ))


# ─── 6. GitOps Tools (status, diff, commit, rollback) ─────────────────────────

def _run_git(args: List[str], cwd: Optional[str] = None) -> Dict[str, Any]:
    """Executa um subcomando git via lista de argumentos (sem shell, sem risco de injeção)."""
    work_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=work_dir, capture_output=True, text=True, timeout=30
        )
        return {
            "command": "git " + " ".join(args),
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:8000],
            "stderr": proc.stderr[:8000],
            "success": proc.returncode == 0
        }
    except Exception as e:
        return {"error": f"Falha ao executar git: {str(e)}"}


def tool_git_status(cwd: Optional[str] = None) -> Dict[str, Any]:
    """Mostra o estado atual do repositório git (branch, staged, modificados)."""
    return _run_git(["status", "--porcelain=v1", "-b"], cwd=cwd)


def tool_git_diff(path: Optional[str] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Mostra o diff das mudanças não commitadas (staged + unstaged), do repo ou de um arquivo."""
    args = ["diff", "HEAD"]
    if path:
        args += ["--", path]
    return _run_git(args, cwd=cwd)


def tool_git_commit(message: str, paths: Optional[List[str]] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    Cria um checkpoint git. Sem 'paths', faz stage só de arquivos JÁ rastreados
    (git add -u) — nunca adiciona arquivo novo/não rastreado às cegas.
    """
    if not message or not message.strip():
        return {"error": "Mensagem de commit vazia."}
    stage_args = ["add", "-u"] if not paths else ["add", "--"] + paths
    staged = _run_git(stage_args, cwd=cwd)
    if not staged.get("success"):
        return {"error": f"Falha ao dar stage: {staged.get('stderr') or staged.get('error')}", "success": False}
    return _run_git(["commit", "-m", message], cwd=cwd)


def tool_git_rollback(path: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Reverte UM arquivo para a última versão commitada. Exige path explícito — sem wipe do repositório inteiro."""
    if not path or not path.strip():
        return {"error": "Rollback exige um 'path' explícito — sem wipe do repositório inteiro."}
    return _run_git(["checkout", "--", path], cwd=cwd)


# ─── 7. Deep Research Tools (web_search, fetch_url) ────────────────────────────

class _TextExtractor(HTMLParser):
    """Extrai texto legível de HTML, descartando script/style."""
    def __init__(self):
        super().__init__()
        self._skip = False
        self.chunks: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.chunks.append(text)


def _html_to_text(raw_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw_html)
    return "\n".join(parser.chunks)


def _resolve_ddg_redirect(href: str) -> str:
    """DDG Lite retorna links de redirecionamento (/l/?uddg=<url_encoded>) — extrai a URL real."""
    parsed = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href)
    qs = urllib.parse.parse_qs(parsed.query)
    return qs.get("uddg", [href])[0]


def tool_web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Busca na web roteando requisições para a API gateway /v1/ (ou fallback via DuckDuckGo Lite).
    """
    if not query or not query.strip():
        return {"error": "Query de busca vazia."}
    
    omniroute_url = os.environ.get("VINCENT_GATEWAY_URL", os.environ.get("OMNIROUTE_URL", "http://localhost:20128/v1")).rstrip("/")
    search_endpoint = f"{omniroute_url}/search"
    payload = json.dumps({"query": query, "max_results": max_results}).encode("utf-8")
    req = urllib.request.Request(search_endpoint, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Vincent/1.0"}, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data
    except Exception:
        pass

    # Fallback para DuckDuckGo Lite se a API /v1/ não responder
    url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
    req_ddg = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req_ddg, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return {"error": f"Falha na busca web: {str(e)}"}

    if "anomaly.js" in raw or "result-link" not in raw:
        return {
            "error": "DuckDuckGo bloqueou a requisição (challenge anti-bot) — sem resultados reais nesta rede/ambiente.",
            "blocked": True
        }

    results = []
    for m in re.finditer(
        r"href=\"([^\"]+)\"\s+class='result-link'>(.*?)</a>.*?class='result-snippet'>(.*?)</td>",
        raw, re.DOTALL
    ):
        href, title_html, snippet_html = m.groups()
        try:
            title = html_lib.unescape(re.sub(r"<.*?>", "", title_html)).strip()
            snippet = html_lib.unescape(re.sub(r"<.*?>", "", snippet_html)).strip()
            results.append({"title": title, "url": _resolve_ddg_redirect(href), "snippet": snippet})
        except Exception:
            continue
        if len(results) >= max_results:
            break

    return {"query": query, "total_results": len(results), "results": results}


def tool_fetch_url(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    """Baixa uma URL e retorna o texto legível (sem tags HTML) — para ler documentação/fóruns."""
    if not url or not url.strip():
        return {"error": "URL vazia."}
    if not url.strip().lower().startswith(("http://", "https://")):
        return {"error": "Apenas URLs http/https são permitidas."}
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (VincentCLI Agentic Fetch)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return {"error": f"Falha ao buscar URL: {str(e)}"}

    text = _html_to_text(raw)
    return {"url": url, "content": text[:max_chars], "truncated": len(text) > max_chars}


# ─── Esquemas de Ferramentas (JSON Schema / Tool Definitions) ─────────────────

TOOL_DEFINITIONS = [
    {
        "name": "list_dir",
        "description": "Lista diretórios e arquivos recursivamente do projeto, ignorando pastas temporárias.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do diretório (padrão: '.')"},
                "max_depth": {"type": "integer", "description": "Profundidade máxima de busca (padrão: 2)"}
            },
            "required": []
        }
    },
    {
        "name": "read_file",
        "description": "Lê o conteúdo de um arquivo real do disco com numeração de linhas.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo a ser lido"},
                "start_line": {"type": "integer", "description": "Linha inicial (1-indexed, opcional)"},
                "end_line": {"type": "integer", "description": "Linha final (1-indexed, opcional)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "grep_search",
        "description": "Realiza busca global por texto ou expressão regular em todos os arquivos do projeto.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Texto ou padrão regex a procurar"},
                "path": {"type": "string", "description": "Diretório base (padrão: '.')"},
                "is_regex": {"type": "boolean", "description": "Se o padrão é regex"}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "run_bash",
        "description": "Executa comandos de terminal no projeto (ex: pytest, flake8, git status, npm test).",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando de shell a executar"},
                "timeout_sec": {"type": "integer", "description": "Tempo limite em segundos (padrão: 600 — espera o suficiente até comandos lentos como 'claude' responderem)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "apply_diff",
        "description": "Aplica uma modificação cirúrgica no código substituindo um bloco exato por outro.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo a ser modificado"},
                "search_block": {"type": "string", "description": "Bloco exato de código a ser substituído"},
                "replace_block": {"type": "string", "description": "Novo bloco de código substituto"}
            },
            "required": ["path", "search_block", "replace_block"]
        }
    },
    {
        "name": "git_status",
        "description": "Mostra o estado do repositório git: branch atual, arquivos modificados e staged.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "git_diff",
        "description": "Mostra o diff das mudanças não commitadas, do repo inteiro ou de um arquivo.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo (opcional, padrão: repo inteiro)"}
            },
            "required": []
        }
    },
    {
        "name": "git_commit",
        "description": "Cria um checkpoint git (Conventional Commits). Sem 'paths', só arquivos já rastreados (git add -u).",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Mensagem no formato Conventional Commits (ex: 'fix(core): ...')"},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Arquivos específicos a incluir (opcional)"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "git_rollback",
        "description": "Reverte UM arquivo para a última versão commitada (desfaz uma mudança ruim). Exige path explícito.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo a reverter"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "web_search",
        "description": "Busca na web (DuckDuckGo, sem chave de API) por documentação/soluções antes de adivinhar sobre uma lib ou API desconhecida.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termos de busca"},
                "max_results": {"type": "integer", "description": "Máximo de resultados (padrão: 5)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch_url",
        "description": "Baixa uma URL e retorna o texto legível (sem HTML) — para ler uma página de documentação encontrada na busca.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa a buscar"},
                "max_chars": {"type": "integer", "description": "Limite de caracteres retornados (padrão: 4000)"}
            },
            "required": ["url"]
        }
    }
]


def execute_agent_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Despachante central para execução segura de ferramentas."""
    name = tool_name.strip().lower()
    if name in ("list_dir", "listdir", "ls"):
        return tool_list_dir(
            path=arguments.get("path", "."),
            max_depth=arguments.get("max_depth", 2)
        )
    elif name in ("read_file", "readfile", "read_buffer"):
        return tool_read_file(
            path=arguments.get("path", ""),
            start_line=arguments.get("start_line"),
            end_line=arguments.get("end_line")
        )
    elif name in ("grep_search", "grep", "search_codebase"):
        return tool_grep(
            pattern=arguments.get("pattern", ""),
            path=arguments.get("path", "."),
            is_regex=arguments.get("is_regex", False)
        )
    elif name in ("run_bash", "bash", "exec"):
        return tool_bash(
            command=arguments.get("command", ""),
            timeout_sec=arguments.get("timeout_sec", 600)
        )
    elif name in ("apply_diff", "patch", "replace"):
        return tool_apply_diff(
            path=arguments.get("path", ""),
            search_block=arguments.get("search_block"),
            replace_block=arguments.get("replace_block"),
            # Mesmas chaves que `build_edit_preview` lê: senão o modelo manda
            # 'diff_content', o usuário vê o preview e a ferramenta responde
            # "parâmetros insuficientes" — preview prometendo o que não é aplicado.
            diff_content=arguments.get("diff") or arguments.get("diff_content")
        )
    elif name in ("git_status", "gitstatus"):
        return tool_git_status(cwd=arguments.get("cwd"))
    elif name in ("git_diff", "gitdiff"):
        return tool_git_diff(path=arguments.get("path"), cwd=arguments.get("cwd"))
    elif name in ("git_commit", "gitcommit"):
        return tool_git_commit(
            message=arguments.get("message", ""),
            paths=arguments.get("paths"),
            cwd=arguments.get("cwd")
        )
    elif name in ("git_rollback", "gitrollback", "git_undo"):
        return tool_git_rollback(path=arguments.get("path", ""), cwd=arguments.get("cwd"))
    elif name in ("web_search", "websearch", "search"):
        return tool_web_search(
            query=arguments.get("query", ""),
            max_results=arguments.get("max_results", 5)
        )
    elif name in ("fetch_url", "fetchurl", "webfetch", "scrape"):
        return tool_fetch_url(
            url=arguments.get("url", ""),
            max_chars=arguments.get("max_chars", 4000)
        )
    else:
        return {"error": f"Ferramenta desconhecida: {tool_name}"}
