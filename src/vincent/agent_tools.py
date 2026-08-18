"""
Vincent CLI 4.0 — Agentic Local Tools Arsenal.
Provides sandboxed execution tools for autonomous multi-turn reasoning and coding:
- ListDirTool: intelligent directory mapping (ignores .git, node_modules, __pycache__, .venv)
- ReadFileTool: safe file reading with slice support and line numbers
- GrepTool: global codebase search with regex and context lines
- BashTool: subprocess execution for linters, tests, and environment checks
- ApplyDiffTool: surgical search-and-replace block patching (and unified diff support)
"""

import os
import re
import glob
import subprocess
import fnmatch
from typing import Dict, Any, List, Optional, Tuple

IGNORE_PATTERNS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".eggs", "*.egg-info",
    "dist", "build", ".claude-flow", ".vincent/cache"
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

def tool_bash(command: str, timeout_sec: int = 30, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Executa comandos de terminal em subprocesso isolado com controle de timeout."""
    work_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    
    # Bloqueio simples de comandos perigosos
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
                text=True
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
                "timeout_sec": {"type": "integer", "description": "Tempo limite em segundos (padrão: 30)"}
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
            timeout_sec=arguments.get("timeout_sec", 30)
        )
    elif name in ("apply_diff", "patch", "replace"):
        return tool_apply_diff(
            path=arguments.get("path", ""),
            search_block=arguments.get("search_block"),
            replace_block=arguments.get("replace_block"),
            diff_content=arguments.get("diff")
        )
    else:
        return {"error": f"Ferramenta desconhecida: {tool_name}"}
