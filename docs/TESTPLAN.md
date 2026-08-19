# Vincent CLI — Test Plan

Source of truth: `src/vincent/cli.py` (read in full for this plan — argparse
block in `main()`, dispatcher in `interactive_repl()`). Verified against a real
`python3 -m vincent.cli --help` run and `py_compile` on every touched module
(see verification note at the end).

Per `CLAUDE.md`: this dev machine overloads under concurrent LLM calls. Every
step below is tagged:

- **[STATIC]** — verifiable now, locally, without a live model call: `py_compile`,
  import, argparse `--help`, or logic that never reaches `execute_inference`.
- **[LIVE LLM]** — reaches `ModelManager.execute_inference` (OmniRoute gateway
  or local Ollama). Do not run in bulk on this machine — one-off, human-run,
  on stronger hardware.
- **[HARDWARE]** — needs a real ESP32 board (T-Embed CC1101 or ESP32DIV
  Kilaz v2) over USB/serial.
- **[NETWORK]** — needs a reachable OmniRoute gateway / Ollama host / git
  remote, but not a full LLM completion.
- **[INTERACTIVE]** — needs a real TTY (curses panel, `getpass` prompt,
  confirm-y/n). Test via a real pty with simulated keys, not a bare call.

---

## A. CLI flags (argparse, `main()`)

T1. **[STATIC]** `python3 -m vincent.cli --help` — exits 0, prints usage with
    all flags below. Already run for this plan; output matched the code
    exactly (see verification note).

T2. **[STATIC]** `vincent -l` / `vincent --list-models` — calls
    `display_models_catalog()` then `sys.exit(0)`. Works with zero reachable
    models (prints "Nenhum modelo indexado" warning) — no network required
    to not-crash, but the real catalog needs T4's network.

T3. **[NETWORK]** `vincent -s free` / `vincent --search free` — same path as
    T2 filtered by `search_term`; needs OmniRoute/Ollama reachable to return
    non-empty results.

T4. **[NETWORK]** Start `vincent` (bare REPL) with no network/Ollama running
    at all — confirm it doesn't crash: `sync_catalogs()` should return
    `(0, 0)` and the HUD prints "0 obras conectadas" / "0 modelos quentes"
    instead of raising.

T5. **[STATIC]** `vincent -d` / `vincent --devices` — calls
    `registry.scan(quick=False)`; with no board attached prints "Nenhuma
    placa ESP32 detectada." and exits 0. No crash expected.

T6. **[HARDWARE]** `vincent -d` with a T-Embed or ESP32DIV attached — expect
    an HUD card row per detected device: `id | label | Porta: <port> |
    Firmware: <firmware_id>`.

T7. **[STATIC]** `vincent -t` / `vincent --train` — calls
    `LlamaFactoryOrchestrator.generate_lora_config()` +
    `build_training_command()`; prints an HUD card (FRAMEWORK / CONFIGURAÇÃO
    YAML / MODELO BASE / COMANDO) and exits 0. Pure local string generation,
    no LLM/network.

T8. **[STATIC]** `vincent --vault` / `vincent --auth` — instantiates
    `VincentAuth()`, prints `status_card_data()`. With no
    `~/.vincent/credentials.json`, all providers show "○ Não configurado".

T9. **[INTERACTIVE]** `vincent --config` — opens the curses TUI
    (`run_config_tui`). Test via pty + simulated arrow keys/Enter per
    project policy (never a bare LLM call to "confirm"). On selection,
    prints `✓ Modelo ativo: <chosen> — rode 'vincent -m <chosen>' pra usar
    direto.`

T10. **[STATIC]** `vincent --serve` / `vincent --daemon` — calls
    `run_server(daemon=True, socket_path=None)` then exits. Verify only that
    it starts without a traceback and the default socket path
    `~/.vincent/run/mcp.sock` gets created; do not exercise a live MCP
    round-trip here (that's a network/IDE-integration concern, out of scope
    for this plan unless requested separately).

T11. **[STATIC]** `vincent --mcp` — calls `run_server(daemon=False,
    socket_path=None)`, which calls `serve_stdio()`. Verify process starts
    and reads from stdin without crashing on an empty/garbage line (should
    error-respond via JSON-RPC, not throw).

T12. **[STATIC]** `vincent --mcp --socket /tmp/vincent-test.sock` — routes to
    `serve_socket()` instead of stdio. Verify the socket file gets created at
    that path.

T13. **[STATIC]** `vincent -m qwen3:0.6b` alone (no prompt, no other flag) —
    falls through to `interactive_repl()`. Confirm `agent.model_manager.resolve()`
    accepts the id without raising, even if Ollama isn't running (resolve is
    local string logic, not a network call).

T14. **[STATIC]** `vincent -c full` alone — `agent.set_caveman_mode("full")`
    called before REPL entry; confirm `/caveman` (T33) shows mode `FULL` at
    startup without needing a model call.

T15. **[LIVE LLM]** `vincent "pergunta simples"` (bare positional prompt) —
    goes through `agentic_run()` → `execute_inference()`. Expect a rendered
    response box and exit 0.

T16. **[LIVE LLM]** `vincent -a "liste os arquivos do diretório atual"` /
    `vincent --agent "..."` — same agentic loop, forced via flag instead of
    REPL `/act`. Expect at least one `list_dir` tool call executed for real
    (verify via printed tool_call JSON or resulting file listing in the
    response).

---

## B. REPL meta / exit / catalog commands

T17. **[STATIC]** Start `vincent`, type `/exit` (also test `/quit`, bare
    `exit`, bare `quit`, `:q`) — REPL prints the farewell line and returns.
    No background threads running → no confirmation prompt.

T18. **[STATIC]** With a `/bg` task still running (see T24), type `/exit` —
    expect the "N tarefa(s) em segundo plano ainda rodando" warning and a
    `(s/N)` confirm prompt; typing anything but `s` must NOT exit (loop
    `continue`s).

T19. **[STATIC]** `/clear` (also bare `clear`, `cls`) — clears the terminal
    and reprints `BANNER`, no crash.

T20. **[STATIC]** `models` (bare, no slash) — `BARE_COMMAND_ALIASES` rewrites
    it to `/models` before dispatch; confirm identical output to typing
    `/models` directly.

T21. **[NETWORK]** `/models` — calls `display_models_catalog(agent)`; with a
    reachable Ollama/OmniRoute, expect sectioned output ("PALETA LOCAL
    OFFLINE", "COMBOS DE HARMONIA DINÂMICA", "ROTAS PÚBLICAS ZERO-KEY",
    "ATELIER AVANÇADO / PRO") each capped at display limits (12/12/14/12)
    with an "+N adicionais" tail line when exceeded.

T22. **[NETWORK]** `/search coding` — filtered catalog via
    `display_models_catalog(agent, search_term="coding")`; header shows
    "BUSCA POR 'coding': N MODELOS ENCONTRADOS".

T23. **[STATIC]** `/model` with no argument — prints current
    `agent.display_model` and usage hint, no state change.

T24. **[STATIC]** `/model qwen3:0.6b` — calls `agent.set_model()`
    (local resolve, no network required to not-crash) and prints
    "✓ Modelo ativo alterado para: ...".

T25. **[STATIC]** `/help` — prints the full command guide (18 lines listed
    in the dispatcher). Cross-check line-by-line against the command list in
    this plan; if a command exists in the dispatcher but is missing from
    `/help` (or vice versa), that's a doc bug in `cli.py` worth flagging back
    (not fixed here — `src/vincent/` is off-limits for this task).

T26. **[STATIC]** `/stats` — pure telemetry read
    (`agent.telemetry.get_summary_cards`), no model call. Works even with
    zero queries run so far (should show zeroed counters, not crash).

T27. **[STATIC]** Unknown slash command, e.g. `/frobnicate` — falls to the
    final `elif prompt.startswith("/")` branch: prints "✗ Comando
    desconhecido: /frobnicate" and does NOT forward to chat (this was a
    deliberate anti-hallucination fix per the comment at cli.py:498-505).

---

## C. Agentic / background / parallel commands (chat = action)

All of these route through `agent.agentic_run()` → `execute_inference()` and
therefore need a live model.

T28. **[LIVE LLM]** `/act lista os arquivos em src/vincent` (also test bare
    `/agent ...`) — spinner shows "Vincent Agentic Loop iniciando...", then a
    response box with mode "Agentic Loop (Tools)". Confirm at least one real
    tool call happened (not a hallucinated description of one).

T29. **[STATIC]** `/act` with no argument — prints usage hint only, no model
    call, no crash.

T30. **[LIVE LLM]** `/bg resuma o README.md` — prints "◈ Tarefa em segundo
    plano #1 disparada" immediately and returns control to the prompt
    without blocking. On completion (check by continuing to interact with
    the REPL), a "Tarefa em segundo plano #1 concluída" block should appear
    on the next loop iteration.

T31. **[STATIC]** `/bg` with no argument — usage hint, no thread spawned.

T32. **[LIVE LLM]** `/spawn 3 investigue o módulo caveman.py` — one task
    string, `n=3` → per cli.py:271-272 logic, expands to 3 identical copies
    run in parallel via `agent.spawn_workers` (ThreadPoolExecutor). Expect 3
    "worker i/3: ocupado/terminado" status lines and a combined result with
    3 `── Worker N ──` sections.

T33. **[LIVE LLM]** `/spawn 2 liste arquivos .py; conte linhas do README` —
    semicolon-separated → 2 distinct subtasks, one worker each (ignores the
    leading `2` as a worker-count once `;` splits >1 subtask — verify actual
    behavior matches cli.py:270 `[t.strip() for t in task_str.split(";")...]`
    with the `n>1 and len(subtasks)==1` guard NOT triggering here).

T34. **[STATIC]** `/spawn` with a non-numeric or missing count, e.g. `/spawn
    foo bar` — fails the `parts[1].isdigit()` check, prints usage hint, no
    threads spawned.

T35. **[STATIC]** Plain chat prompt that is a greeting, e.g. `oi` — per the
    chat=action merge comment (cli.py:507-509), `agentic_run` should exit in
    1 turn with no tool call for something this trivial. This is still a
    live-model round trip technically, but worth a note: **[LIVE LLM]**, low
    cost (should not trigger multi-turn tool use).

---

## D. Config / vault / credentials commands

T36. **[STATIC]** `/config` (REPL) — same curses panel as T9; if a model is
    chosen, `agent.set_model()` runs afterward (local, no network needed to
    not-crash). **[INTERACTIVE]** for the actual keypress flow.

T37. **[INTERACTIVE]** `/vault` (also bare `vault`, `/auth`, `/login`) —
    prints the 9-option menu (1-8 provider keys, 9 = status). Selecting
    1-8 calls `auth.interactive_login()` which uses `getpass` (hidden input)
    — needs a real pty to simulate keystrokes, not a piped stdin (getpass
    may refuse non-tty in some environments — worth confirming behavior on
    the target machine).

T38. **[STATIC]** `/vault` → option `9` — prints `status_card_data()` HUD,
    same as T8 but from inside the REPL. No live LLM.

T39. **[STATIC]** `/key mysecretkey123` — calls `auth.set_key("omniroute",
    ...)` directly (no getpass prompt since the key is inline); confirm
    `~/.vincent/credentials.json` is written with mode `0600` and env var
    `OMNIROUTE_API_KEY`/`VINCENT_AUTH_KEY` gets set in-process. **Caution**:
    this writes a real file under `~/.vincent/` — use a throwaway value and
    clean up (`/key` supports no delete command in the REPL; delete via
    `auth.remove_key()` or by editing the JSON directly if needed).

T40. **[INTERACTIVE]** `/key` with no argument — falls back to
    `auth.interactive_login("omniroute")`, same getpass caveat as T37.

T41. **[STATIC]** `/train` (also bare `train`, `/lora`, bare `lora`) — same
    as T7 but from inside the REPL, using `agent.model` as the base model.

T42. **[STATIC]** `/export` — calls
    `trainer.export_session_dataset(agent._history)`; with an empty history
    (no chat yet this session) confirm it still writes a file (even if the
    dataset is empty/near-empty) rather than crashing, and prints the output
    path.

---

## E. Hardware / device commands

T43. **[HARDWARE]** `/devices` (also bare `devices`) — same
    `registry.scan(quick=False)` as T5/T6, from inside the REPL.

T44. **[HARDWARE]** `/cmd TEMBED help` (or `/cmd ESP32DIV <serial-cmd>`) —
    requires the named device to be `online` in the registry; sends
    `cmd_str` over serial and prints `[dev] → response`. With the device
    unplugged, expect "Dispositivo 'TEMBED' offline ou não encontrado."
    (this branch alone is **[STATIC]**-testable — the negative path needs no
    hardware).

T45. **[STATIC]** `/cmd` with fewer than 2 args, e.g. `/cmd TEMBED` — prints
    usage hint, no send attempted.

---

## F. Skills commands

T46. **[STATIC]** `/skills` (also bare `skills`) with an empty
    `~/.vincent/skills/` — prints "Nenhuma skill instalada." No crash.

T47. **[NETWORK]** `/skill add https://github.com/<org>/<skills-repo>` (also
    bare `skill add ...`) — `git clone --depth 1` into a temp dir, then
    copies any `skills/<name>/SKILL.md` found into `~/.vincent/skills/<name>/`.
    Expect "✓ Skills instaladas: <names>" or the "Nenhum SKILL.md encontrado"
    error if the repo doesn't match the expected layout.

T48. **[STATIC]** `/skill add` with a non-http(s) URL, e.g. `/skill add
    git@github.com:x/y.git` — `add_skill_from_git` raises `ValueError`
    ("Só URLs http(s)..."), caught and printed as `✗ <msg>`.

T49. **[STATIC]** `/skills` after T47 succeeded — lists the installed
    skill(s) with name + description read from frontmatter only (cheap, no
    body load).

T50. **[STATIC]** `python3 -m vincent.skills` (module self-check / `demo()`)
    — asserts frontmatter parsing and keyword matching without touching
    `~/.vincent/`. Already covered by the module's own `if __name__ ==
    "__main__"` block; safe to run directly as a regression check.

---

## G. Vision / multimodal

T51. **[STATIC]** `/vision` with no argument — prints usage hint + note that
    a multimodal model is required, no call made.

T52. **[STATIC]** `/vision /path/does/not/exist.png` — `build_image_content`
    raises `FileNotFoundError`/`ValueError`, caught and printed as `✗ <msg>`,
    no model call attempted.

T53. **[LIVE LLM]** `/vision <real-image-path> "o que você vê?"` with a
    multimodal model active (e.g. `/model qwen2.5vl` or `/model
    auto/best-vision` first) — expect a description in the response box,
    mode "Visão Multimodal". This needs both a real image file and a real
    vision-capable model reachable — flag clearly as needing live LLM +
    correct model selection; a non-vision model will likely reply
    nonsensically rather than error cleanly (worth confirming actual failure
    mode on real hardware).

---

## H. Git / commit command

T54. **[STATIC]** `/commit` with no message — prints usage hint, no git
    calls made.

T55. **[STATIC]** `/commit "chore: test"` on a clean working tree (no
    changes) — `tool_git_status()` returns empty stdout, prints "Nada para
    commitar — working tree limpo." No commit created. Pure local git call,
    no LLM.

T56. **[STATIC]** `/commit "chore: test"` with a real uncommitted change
    present — calls `tool_git_commit(message=...)`, prints "✓ Checkpoint
    criado: ..." on success or "✗ Commit falhou: ..." on failure (e.g. no
    git identity configured). Since this repo (`vincent`) is git-tracked,
    this is safe to test end-to-end locally with a throwaway file change —
    still tagged STATIC because no LLM is involved, but be careful not to
    commit unrelated in-flight work from the concurrent process editing
    `src/vincent/`.

---

## I. Compression / caveman command

T57. **[STATIC]** `/caveman` with no argument — prints current mode +
    usage hint listing `off | lite | full | ultra` (note: the REPL's own
    hint text omits the `wenyan-*` modes even though
    `CavemanEngine.INTENSITY_LEVELS` includes `wenyan-lite`, `wenyan-full`,
    `wenyan-ultra` — worth flagging as a doc gap in the code's own help
    text, not fixed here since it's in `src/vincent/`).

T58. **[STATIC]** `/caveman full` — `agent.set_caveman_mode("full")` returns
    `True`; prints an HUD card with mode, directive, and total tokens saved
    so far (0 on a fresh session).

T59. **[STATIC]** `/caveman wenyan-ultra` — valid per `INTENSITY_LEVELS`
    even though not listed in the REPL's own usage hint (see T57); confirm
    it's actually accepted (`set_mode` returns `True`) despite the
    misleading hint text.

T60. **[STATIC]** `/caveman bogus` — `set_caveman_mode` returns `False`
    (mode not in `INTENSITY_LEVELS`), prints "Modo inválido. Opções: off,
    lite, full, ultra, wenyan-lite, wenyan-full" — note this error message
    itself is missing `wenyan-ultra` from its own list, a second small gap
    in the same area.

---

## J. Gateway status command

T61. **[NETWORK]** `/gateway` (also `/gateway status`, `/gateway anything` —
    fixed to `prompt.startswith("/gateway")`, no longer an exact-match quirk)
    — prints an HUD card: URL, ALCANÇÁVEL (yes/no + model count), CIRCUITO
    (circuit breaker state from `routing/resilience.py`), COOLDOWN ATIVO.
    With no network, expect ALCANÇÁVEL = NÃO and CIRCUITO likely `closed`
    (no failures recorded yet) rather than a crash.

T62. **[STATIC]** *(superseded — `/gateway foo` now matches via
    `startswith`, see T61; the former exact-match-only quirk was fixed.)*

T64. **[STATIC/INTERACTIVE]** `/tui` — with no `/bg`/`/spawn` task alive,
    prints a single static Rich frame (header + workers panel showing
    "no active workers" + last-10-messages log) and returns to the prompt.
    With a `/bg`/`/spawn` task running, enters a live-refreshing view
    (0.5s tick) until all tracked background threads finish, then renders
    a final frame and returns; Ctrl+C exits the live view early without
    killing the background task. `render_frame()`/`mount()` themselves are
    covered by `tests/test_tui.py` (mocked state, no terminal needed); this
    step is about the real wiring in `cli.py` (`bg_tasks` dict feeding
    worker rows), which needs a live REPL to exercise end-to-end.

T65. **[NETWORK]** `/gateway` with the OmniRoute gateway unreachable now
    also prints a MOTIVO line (`ModelManager.last_omniroute_error`,
    `test_sync_catalogs_records_reason_when_gateway_unreachable` covers the
    logic with a mocked `urlopen`) — distinguishes "porta fechada, rode
    omniroute" (`URLError`) from "gateway respondeu mas sem provider/chave"
    (`HTTPError`). Live check: stop any local omniroute process, run
    `/gateway`, confirm MOTIVO names the actual cause instead of just
    ALCANÇÁVEL = NÃO. Also covers `install.sh`'s new step 5 (bootstraps
    `npm install -g omniroute` + background start when port 20128 is
    closed) — needs a machine with `npm` and no prior OmniRoute install to
    exercise for real; `bash -n install.sh` only proves it parses.

---

## K. Resilience / routing layer (module-level, not REPL commands)

These aren't slash commands but back `/gateway` (T61) and every
`execute_inference` call; already covered by real unit tests in `tests/`
(`test_resilience.py`, `test_strategies.py`, `test_models_resilience.py`),
all LLM-call-free and safe to run repeatedly on this machine.

T63. **[STATIC]** `python3 -m pytest tests/ -v` — all three resilience/
    strategy test files should pass with mocked HTTP (per
    `test_models_resilience.py`'s `monkeypatch` usage), no live network or
    LLM calls.

---

## Summary

- Total steps: 65 (T1–T65; T62 superseded by the `/gateway` startswith fix,
  kept as a marker rather than renumbering everything below it).
- **[STATIC]**: majority — runnable now via `py_compile`, `--help`, mocked
  `pytest`, or REPL paths that error out before reaching a model call.
- **[LIVE LLM]**: T15, T16, T28, T30, T32, T33, T35, T53 — hand these to a
  human on stronger hardware; report back actual output/latency/failure
  modes.
- **[HARDWARE]**: T6, T43, T44 (positive path only) — need a T-Embed or
  ESP32DIV board over USB.
- **[NETWORK]**: T3, T4 (negative path), T21, T22, T47, T61, T65 — need a
  reachable OmniRoute gateway / Ollama host / git remote, but not a full
  model completion.
- **[INTERACTIVE]**: T9, T37, T40, T64 (live-view branch only) — need a
  real pty with simulated keystrokes, per this repo's existing testing
  convention for curses UIs.

### Verification performed while writing this plan

```
$ python3 -m py_compile src/vincent/cli.py src/vincent/agent.py \
    src/vincent/skills.py src/vincent/auth.py src/vincent/models.py \
    src/vincent/routing/resilience.py src/vincent/routing/strategies.py
PYCOMPILE_OK

$ PYTHONPATH=src python3 -m vincent.cli --help
# output matched the flag table in section A exactly (T1)
```
