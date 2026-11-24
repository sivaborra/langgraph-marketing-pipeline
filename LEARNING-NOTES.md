# LangGraph Learnings — Notes

Date: 17 Nov 2026; MCP section added 24 Nov 2026. Written after the overnight gh-aw port of the marketing pipeline
and the morning verification. The whole point of this exercise: learn, by building,
where each orchestration tool fits — and where it doesn't.

## Integrating Google ADK with the LangGraph marketing pipeline — the guide

The pipeline now runs on two orchestrators from one codebase. This section is the
how-to: the design, the file map, how each ADK piece maps to a LangGraph node, how
to run it, how to add a new agent, and the lessons that change how you build.

### The design: reuse by design (Siva's correction, 17 Nov 10:30)

NOT two implementations. The two paths differ ONLY in orchestration. Everything
else is shared code, so any output difference is attributable to the orchestrator,
not to drifted logic.

- **Shared core** under `src/marketing_pipeline/`: rules + prompt strings, retrieval
  (bge-m3 cosine top-3), deck builder (python-pptx), run/store IO, eval
  (`scripts/eval_draft.py`). Prompt strings live in the shared module so the rules
  can't drift; only the orchestration wording differs.
- **Thin layers only:** `graph.py` wires the shared pieces into a LangGraph state
  graph; `src/marketing_adk/` wires the SAME shared pieces into ADK agents +
  FunctionTools. No duplicated pipeline logic.
- **One CLI, one flag:** `python -m marketing_pipeline.cli run <id> --engine
  langgraph|adk`. Two usage paths, one pipeline.

### File map

Shared core (`src/marketing_pipeline/`):
- `config.py` — SERVICES, BRAND_NAME, env-overridable models, `generation_model(role)`.
- `llm.py` — Ollama transport `_post` / `_generate` / `_embed`. `_generate` posts
  with `"think": False`, temperature 0, num_ctx 2048 — that is why the LangGraph
  path is reliable.
- `rules.py` — BANNED_PHRASES, PII_PATTERNS, and the shared prompt builders
  `planner_prompt`, `synthesis_prompt`, `writer_prompt`.
- `retrieve.py` — `_cosine`, `_ensure_knowledge_base`, top-3 `retrieve()`;
  `DOCS_PREFIX` lives here.
- `deck.py` — deck helpers + `build_deck(plan, research, draft, run_id)`; returns
  (deck_path, deck_slides, fallback_slides).
- `store.py` — `publish(draft, deck_path, run_id)` to `published/<run_id>/`.
- `graph.py` — TypedDicts, thin node wrappers, routing, graph wiring, the approve
  `interrupt()`, `safe_json`.
- `cli.py` — one CLI, `--engine` flag.

ADK side (`src/marketing_adk/`, thin wrappers only):
- `models.py` — `adk_model(role, backend, think=None)`: Gemini (a plain model
  string) or Ollama via LiteLLM (`ollama/<model>`, `think` forwarded to Ollama).
- `runner.py` — the shared run helpers every ADK agent uses: `_collect` (events
  into a passed-in list so they survive a timeout), `run_agent_once` (120s
  timeout, `partial_on_timeout`), `run_with_fallback` (Gemini first, Ollama
  fallback), `find_tool_result` (tolerant of ADK's two response shapes).
- `tools.py` — `retrieve_docs` + `RETRIEVE_TOOL` (FunctionTool wrapping shared
  `retrieve`).
- `planner.py` — `build_planner_agent` + `run_planner_once` (shared
  `planner_prompt` as the instruction).
- `researcher.py` — `build_researcher_agent` + `run_researcher_once` (shared
  synthesis rules + `retrieve_docs` tool; anchored synthesis when the agent loops).
- `writer.py` — `build_writer_agent` + `run_writer_once` (shared `writer_prompt`;
  validates the draft the same way the LangGraph writer node does).
- `deck_tool.py` — `make_deck` + `DECK_TOOL` (FunctionTool wrapping shared
  `build_deck`); `run_deck_once`.
- `eval_gate.py` — `run_eval` (wraps `scripts/eval_draft.py` `evaluate()` via
  importlib) + `EVAL_TOOL` + `run_eval_loop` (eval → writer with feedback →
  deck → eval, max 2 attempts, app-orchestrated).
- `approve.py` — `run_approve_once` (asks the human between runner calls, then
  shared `publish` or reject; ADK has no `interrupt()`).
- `pipeline.py` — `run_adk_pipeline` (chains all of the above end to end).

### How each ADK piece maps to a LangGraph node

| LangGraph node | ADK equivalent | Shared code it wraps |
|---|---|---|
| planner_node | `planner.py` LlmAgent | `planner_prompt` (rules.py) |
| retrieve + synthesise | `researcher.py` LlmAgent + `retrieve_docs` tool | `retrieve` (retrieve.py), `synthesis_prompt` (rules.py) |
| writer_node | `writer.py` LlmAgent | `writer_prompt` (rules.py), same draft checks |
| deck_node | `deck_tool.py` FunctionTool | `build_deck` (deck.py) |
| evals_node | `eval_gate.py` `run_eval` + retry loop | `scripts/eval_draft.py` `evaluate()` |
| approve_node (`interrupt()`) | `approve.py` `run_approve_once` | `publish` (store.py) |
| `cli run` / `approve` | `cli.py --engine adk` (single phase) | `pipeline.py` `run_adk_pipeline` |

### Models and fallback

- **Gemini first, local Ollama fallback, per run, visible.** The runner prints
  which backend served the request, so you always know which model did the work.
  `run_with_fallback` tries Gemini, then Ollama on ServerError (5xx), TimeoutError,
  or ClientError with code 429. Any other 4xx (400/401/403) fails loudly — those are
  real problems, not outages.
- **Gemini free tier is 20 requests/day** for `gemini-3.8-flash` (resets ~09:00).
  Too tight for active development. Use Ollama-first while building
  (`ADK_MODEL_BACKEND=ollama` skips Gemini entirely — the runner has an explicit
  Ollama-only shortcut, because passing a backend through `run_with_fallback`
  otherwise ignores the env var). Use Gemini for occasional checks.
- **`gemini-2.5-flash` is retired for new users** (API 404). The ADK build uses
  `gemini-3.8-flash`.
- **Ollama lives at `http://172.22.112.1:11434` on AIBeast**, not localhost.
  The repo default is `localhost:11434` (correct for a laptop; the repo is public).
  Set it in env, not code. LiteLLM reads `OLLAMA_API_BASE`, the shared code reads
  `OLLAMA_BASE_URL` — a run needs BOTH set to the same address. Non-interactive
  shells (SSH) do not source `.bashrc`, so neither the key nor the URLs are there
  unless the run command sets them.
- **LiteLLM model name is `ollama/qwen3:14b`**, not `ollama/chat/qwen3:14b`
  (LiteLLM strips only `ollama/`). Install `litellm` directly, not
  `google-adk[extensions]` (that drags llama-index → pandas source builds).
  LiteLLM 1.106.2 + tools also needs the `mcp` package installed (its own
  packaging bug — it imports the MCP handler only when tools are present).

### How to run it

```bash
# From the repo root on AIBeast, in the lab venv:
export OLLAMA_BASE_URL=http://172.22.112.1:11434
export OLLAMA_API_BASE=http://172.22.112.1:11434
export GOOGLE_API_KEY='...'          # interactive shell only; export it

# LangGraph (default): two phases
PYTHONPATH=src .venv/bin/python -m marketing_pipeline.cli run demo
PYTHONPATH=src .venv/bin/python -m marketing_pipeline.cli approve demo yes

# ADK: one phase (approval happens inside the run)
PYTHONPATH=src .venv/bin/python -m marketing_pipeline.cli run demo --engine adk
PYTHONPATH=src .venv/bin/python -m marketing_pipeline.cli run demo --engine adk yes

# Ollama-only (skip Gemini, no quota burn):
ADK_MODEL_BACKEND=ollama PYTHONPATH=src .venv/bin/python -m marketing_pipeline.cli run demo --engine adk yes
```

### How to add a new ADK agent (the recipe)

1. If the step has a prompt, put the prompt in the shared module (`rules.py`) as a
   builder function, and refactor the LangGraph node to call it too. One source of
   truth.
2. If the step is deterministic (retrieval, deck, eval, publish), wrap the shared
   function in a `FunctionTool`. Do not re-implement it in the agent.
3. Write `build_<name>_agent(backend=None)` (LlmAgent, `adk_model(role, backend,
   think=False)` for tool-carrying or long-form agents, temperature 0.2 for
   free-form output, 0 for structured JSON) and `run_<name>_once(...)` that goes
   through `run_with_fallback` with `partial_on_timeout=True` when a tool is
   involved.
4. **Anchor it.** Prefer the agent's own output when it answers; fall back to the
   shared plain call / shared function when it loops, times out, or fails the
   checks. Capture the tool result from the event stream (`find_tool_result`) —
   that is the usable output even when the agent never produces a final answer.
5. Verify with a hello run: the agent's own output (if it answers) AND the
   anchored path (force the loop/timeout and confirm a correct result still comes
   back). Both must be green.

### The lessons that change how you build on ADK (local qwen3)

- **Tool-calling agents loop; pure-generation agents do not.** The researcher
  (tool) called `retrieve_docs` 5 times and never answered; the deck agent
  produced zero events in 120s (stuck in reasoning). The writer (no tools)
  answered directly in 59s with a valid draft. So: give tools only where a
  tool is needed, and always anchor a tool-carrying agent to shared code.
- **`think=False` changes the failure mode, it does not fix the loop.**
  With thinking, qwen3 reasons in circles; without it, it repeats the tool
  call. The fix is not a prompt tweak — it is the timeout + partial events +
  anchored fallback. (Verified in source: LiteLLM forwards a `think` kwarg to
  Ollama's top-level `think` field; ADK's `LiteLlm` passes `**kwargs` through.)
- **Temperature 0 + free-form output loops.** Greedy decoding is deterministic —
  once the model starts repeating, it cannot break out. The repeat-limit abort
  is Ollama's repetition guard, not a token-count limit. Use temperature 0.2 for
  free-form agent output (0 stays for structured JSON like the planner).
- **Timeout is the backstop, and it must return partial work.** 120s per leg
  (`asyncio.wait_for`), passed to both legs. `partial_on_timeout=True` returns
  the events collected so far instead of raising, so a tool result survives a
  timeout. Without it, a looping agent kills the run with nothing to show.
- **The agent's final text is optional; the tool result is the output.** For a
  tool-carrying agent, capture the result from the event stream. If the agent
  never answers, synthesise/compute from the captured result with shared code.
- **Verify the built artifact, not the draft.** The Gate 3/4 refactors broke
  `graph.py` (prompt builders called but never imported — loads fine, NameErrors
  at runtime) and nobody noticed because the LangGraph path was not re-run. An
  import check is not a run. Re-run the end-to-end path after every refactor.
- **File transfer that survives quoting:** heredocs mangle nested triple-quoted
  strings with double quotes (quotes stripped, broke `graph.py`). Reliable path:
  write the file locally, `scp` to AIBeast, verify md5. Surgical fixes: build
  strings with `chr(39)` / `chr(10)` to avoid quote nesting.
- **The eval gate catches real problems, including deck problems.** A good draft
  failed eval on `deck_slides_distinct` (identical slide bodies from fallback
  snippets) — the gate did its job, and the retry loop fixed it by re-writing.
  Test the gate both ways (good passes, sabotaged fails) or you have not tested it.

### Honest limits (what works where)

- On local qwen3, the ADK path works end to end ONLY because every deterministic
  stage is anchored to shared code. The pure agent loop (model answering for
  itself, tools included) is a Gemini job — verify it after the quota resets.
- The full ADK pipeline runs in ~7 minutes on Ollama (mostly the 120s timeouts
  on looping agents). That is the cost of the anchor on local models; on Gemini
  it should be far faster.
- ADK has no `interrupt()` and no checkpoint/resume. Approval is app-orchestrated
  between runner calls, and the ADK run is one-shot. If you need resume-after-
  approval, that is LangGraph's job.

## Exposing the eval as an MCP service — the guide

Added 24 Nov 2026. The repo now covers four things: LangGraph orchestration,
ADK orchestration, gh-aw workflows, and MCP service exposure. MCP is not a
fifth orchestrator. It is the protocol that lets another app call one piece of
the pipeline — the eval — without the pipeline code.

The point: another department or company can run the eval the way they want.
They generate a draft and a deck however they like, call the service before
publish, and get the same 9 checks, the same pass or fail, and the same
feedback the pipeline gets. The generator does not matter. The gate is the
same for every caller.

### The design: one pure function, one tool

- **The eval is a pure function now.** Gate 1 extracted the 9 checks verbatim
  from `evals_node` into `src/marketing_pipeline/evaluate.py`:
  `evaluate(draft, research_docs, deck_bodies)`. No new checks, no changed
  thresholds. `evals_node` in `graph.py` is a thin wrapper — attempts and
  status stay in the graph, the `evals` dict keeps its exact old shape.
- **One design point that matters:** the 9th check used to read deck slides
  from a local file path. A remote caller has no such path, so the service
  takes deck slide *bodies* as input, not a path. Only the graph wrapper
  reads the file.
- **One tool, over stdio.** `mcp-eval-service/server.py` exposes
  `evaluate_marketing_draft(draft, research_docs, deck_bodies, credential)`
  and returns the result as a JSON string. No network port, no HTTP in this
  version. The client spawns the server as a subprocess and talks to it over
  standard in and out.
- **mcp 2.3.0 is the v2 API.** FastMCP is gone. The server uses `MCPServer`
  from `mcp.server.mcpserver` and `mcp.run()` (stdio by default).

### File map

- `src/marketing_pipeline/evaluate.py` — the pure 9-check function (Gate 1).
- `src/marketing_pipeline/graph.py` — `evals_node` wrapper around it.
- `mcp-eval-service/server.py` — MCP server, one tool (Gate 2).
- `mcp-eval-service/client.py` — round-trip test client (Gate 3).
- `mcp-eval-service/auth.py` — token mint and verify, stdlib only (Gate 4).
- `mcp-eval-service/issue_token.py` — the issuer: mints short-lived tokens (Gate 4).
- `requirements.txt` — now includes `mcp==2.3.0`.
- `docs/mcp-eval-service-flow.pdf` — the flow doc: diagrams, the 9 checks,
  gates, commands, real outputs.

### Gate 4: per-call auth (24 Nov 2026)

Siva's rule from 23 Nov: each tool, before it executes, authorises the session
and makes sure it is still valid — not expired, not revoked, scopes cover the
tool. Checked on every call, not once at connect.

- Every call to `evaluate_marketing_draft` must carry a credential. The server
  verifies it before the tool runs, on every call, in this order: present,
  signature valid, scope covers the tool, not expired. Any failure and the
  tool does not run — it returns `{"error": "unauthorized: <reason>"}`.
- The token stands in for an OAuth access token: `base64url(json) .
  base64url(hmac-sha256)`, payload `{"scope": <tool name>, "exp": <unix
  time>}`, 5-minute life, HMAC-signed with a server-side secret
  (`MCP_EVAL_SECRET`). `issue_token.py` mints it and stands in for the OAuth
  authorization server. No new dependencies.
- Verified 24 Nov: 8 cases end to end. Valid ran (9/9, coverage 1.0). No
  credential, expired credential, an `--expired` issuer token, wrong scope,
  tampered signature, malformed token, and a token minted with a different
  secret were all refused. The server with no `MCP_EVAL_SECRET` set fails
  fast (exit 1) instead of starting open.
- Honest boundary: this is the per-call check demo, not a full OAuth server.
  Full OAuth needs the HTTP transport plus an authorization server. That is
  a later step, not this one.

### How to run it

From the repo root on AIBeast, in the lab venv:

export MCP_EVAL_SECRET=$(openssl rand -hex 16)
~/langgraph-lab/.venv/bin/python mcp-eval-service/issue_token.py
~/langgraph-lab/.venv/bin/python mcp-eval-service/client.py

The client lists the tool, then calls it four times with a passing draft: no
credential (refused), valid credential (passed True), expired credential
(refused), wrong scope (refused).

### Honest limits (what the eval proves, and what it doesn't)

- The checks prove the *form*, not the truth. A draft can cite real docs and
  still misstate what they say. The eval catches uncited and badly cited
  claims. It does not catch a wrong claim that happens to carry a valid
  citation number.
- Stdio only. No HTTP transport, no remote server in this version.
- `scripts/eval_draft.py` still duplicates the same 9 checks. Untouched in
  this work; it is a later cleanup.
- The `mcp-gate1` pipeline run is still paused at approve on AIBeast.
  Do not approve or publish it unless Siva says so.

## 1. The three tools, in one picture

| | LangGraph (Python) | gh-aw (GitHub Agentic Workflows) | Google ADK |
|---|---|---|---|
| What it is | A state machine you code | A trigger shell you describe in Markdown | An agent framework you code |
| What you write | Python: nodes, edges, state schema, checkpointers | Markdown: frontmatter = config, body = prose instructions for an agent | Python: agents (LlmAgent, Sequential/Parallel/Loop), tools, sessions |
| State | Typed state, checkpointing, resume mid-graph, `interrupt()` | None. State lives in GitHub objects (issues, PRs, artifacts) | Session-based state; graph workflows added in ADK 2.0 |
| Branching | Conditional edges — the graph decides the next step from state | Workflow-level if/else + the agent deciding in prose | Workflow agents + 2.0 graph workflows |
| Human-in-the-loop | `interrupt()` — pause inside a run, resume where it stopped | Coarse: approve-by-merge. One workflow ends, another starts | Tool-call approval, callbacks; approval orchestrated by the app between runner calls |
| Runtime | Wherever you put it — AIBeast, your hardware, $0 with Ollama | GitHub-hosted runners + metered cloud models | Wherever Python runs; happiest on Google Cloud (Agent Engine, Vertex AI) |
| Models | Any model, any endpoint, full control of tokens | Fixed engine list; magic secret names; proxy rewrites model ids | Gemini natively; others second-hand via LiteLLM |
| Writes | Code writes files directly | Agent is read-only; writes only via safe-outputs (PR/issue/comment) on allow-listed paths | Code/tools write directly |
| Debugging | Local logs, reproduce in seconds | 4-minute feedback loops; forensics from downloaded artifacts | Local logs, like LangGraph |
| Cost per run | $0 (local Ollama) | Copilot credits / metered API keys | Depends on model (Gemini free tier exists) |

## 2. The verdict (earned, not asserted)

- **gh-aw is better for GitHub-native chores.** Issue triage is the perfect fit: an issue
  opens, classify it, label it, comment — no state beyond the issue itself, no server
  to run, no Python to deploy.
- **LangGraph is better for the pipeline itself.** Anything stateful, resumable, or
  where you choose the model and the cost — the approve interrupt, the eval retry loop,
  the evals-as-code — belongs in the graph.
- **ADK is a brain, like LangGraph, not a shell like gh-aw.** ADK vs LangGraph is a
  much closer race: ADK is ready-made patterns first (Sequential/Parallel/Loop out of
  the box, built-in eval, hierarchical teams), strongest on Google Cloud with Gemini;
  LangGraph is low-level control (explicit graph, swappable checkpointers, durable
  execution, auditability) and vendor-neutral.
- **The synthesis: gh-aw as the trigger/shell, LangGraph (or ADK) as the brain.**
  A gh-aw workflow that fires on a GitHub event and calls your LangGraph API on
  AIBeast gives you GitHub events *plus* a real state machine.
- **Local files + local LLMs: among the three, LangGraph is the only natural choice.**
  The marketing pipeline proves it: local KB markdown files, local Ollama models on
  AIBeast, approve interrupt inside the run. On ADK the KB read becomes a tool call
  and approval a callback, wired through layers that assume the cloud. On gh-aw the
  KB would have to live in the repo and approval would be a PR merge — the wrong layer.
  ("Only choice in the world" overstates it — plain Python or another framework could
  do it too. Among these three, LangGraph is the one designed for local-first,
  stateful, human-gated work.)
- **Interview line:** *gh-aw triggers, ADK assembles on Google Cloud, LangGraph runs
  the state machine — and when the models and the data live on your own machine, only
  the state machine fits.* "State" isn't complicated-old — it's the checkpoint +
  approval feature.

## 3. Change log since yesterday (16 Nov evening → 17 Nov morning) — what changed and why

### The port itself — commit 09908f3 (16 Nov 21:50 UTC)
- **What:** the marketing flow ported to gh-aw: `marketing-draft.md` (manual trigger →
  plan/research/write/deck/eval → draft PR), `marketing-publish.md` (a merged PR moves
  `drafts/` to `published/`), `issue-triage.md` (new issue → classify, label, comment),
  plus `scripts/eval_draft.py` (the 9 eval checks as plain code, never the writer
  judging itself) and a README section.
- **Why:** make the same flow runnable from GitHub events, with no server to keep up.
- **Proved first on AIBeast:** the LangGraph demo ran end to end (run-c9622ffc, evals
  9/9 first attempt, published) before any porting — the original stays the reference.

### The OpenRouter fallback — commits 133a71b → 630face (16 Nov 22:50 → 23:17 UTC)
Each commit is one diagnosed failure, not a guess. The chain:
- **133a71b — Claude via OpenRouter.** *Why:* Copilot's endpoint 502'd twice
  (runs 43967220101, 43968212446). Needed a fallback engine. Secret `ANTHROPIC_API_KEY`
  set in the repo — value is the OpenRouter key, never in chat or files.
- **d81937e — Codex engine + `OPENAI_BASE_URL`.** *Why:* Claude 404'd
  (run 43973792007) — GitHub's api-proxy strips the `anthropic/` prefix when forwarding,
  and OpenRouter's Anthropic endpoint 404s bare model names. Secret `OPENAI_API_KEY`
  set from the same key.
- **eeb7265 — Codex + `openai/gpt-5.1`.** *Why:* Codex refuses any non-openai model
  prefix at startup (run 43974452524). Bare `gpt-5.1` was verified to work directly
  against OpenRouter (HTTP 200), so the plumbing was proven.
- **4ac92eb — attempted free model `gpt-oss-120b:free`.** *Why:* GPT-5.1 hit 402
  (run 43976171194) — the key was nearly out. The compiler rejects `:` in model ids,
  so the free id can't compile. (Lock briefly out of sync; fixed by the next commit.)
- **92ea9a8 — Codex + `openai/gpt-5-nano`.** *Why:* nano's 65,536-token reservation
  ($0.026) fit the remaining balance; mini ($0.131) and 5.1 ($0.65) did not.
  Nano ran clean (run 43976870632) but produced no output — it asked for the goal and
  audience, which was correct: they never reached the agent.
- **630face — inject goal/audience into the prompt (both draft workflows).**
  *Why:* the real bug — gh-aw does NOT auto-inject workflow_dispatch inputs into the
  agent prompt. The values are now embedded as `${{ inputs.goal }}` /
  `${{ inputs.audience }}`. Nano's next run (43978052446) did the plan and research,
  then died on shell quoting (12 failed tool calls) — nano is too weak at the
  Codex shell tooling for multi-line file writes.

### This morning (17 Nov)
- **Copilot test run 44044849320 — fifth 502** (agent failed 3m27s, 09:16 CET).
  Copilot's endpoint has been down ~10 hours. Waiting continues per Siva's call.
- **OpenRouter key, real numbers:** usage $9.96, limit $100 — but the $100 is a spend
  cap, not a balance. Prepaid credit left is ~$0.035. Proved directly: the same
  GPT-5.1 request 402s with this key outside GitHub too, so the proxy was innocent.
- **Push state verified:** local HEAD == GitHub HEAD == AIBeast clone == 630face.
  One untracked compile cache (`.github/aw/imports/`, 19 KB) deleted; AIBeast clone
  synced from its stale state to 630face. Nothing unpushed anywhere.
- **Repo noise:** 5 auto-generated failure-report issues (#1–#5) from the night's runs.
  Safe to close whenever.

## 4. Hard rules learned (keep these)

- Never attach a self-hosted runner to a public repo (a fork PR could execute code
  on the host). The Ollama variant belongs on a private repo or a local run.
- gh-aw strict mode rejects secrets in `engine.env` and top-level `env` — use the
  engine's magic secret name instead.
- Model ids in gh-aw: exactly one `/`, no `:` — `openai/anthropic/claude-sonnet-5.5`
  and `openai/gpt-oss-120b:free` both fail to compile.
- The gh-aw api-proxy strips the provider prefix; OpenRouter's OpenAI-compatible
  endpoint accepts bare OpenAI names, its Anthropic endpoint does not.
- No max-output-tokens knob exists in gh-aw engine config — a 402 from a big
  reservation can't be tuned away from inside the workflow.
- A 402's "afford N tokens" is about prepaid balance, not the key's limit number.
- `/root` on this VM is ephemeral — SSH uses
  `-o UserKnownHostsFile=/home/hatch/.ssh/known_hosts`.
- Tailscale proxy stalls above ~164 KB — gzip or chunk large transfers.

## 5. Open items

1. **Copilot:** wait for recovery, re-trigger `marketing-draft`. (Or top up OpenRouter
   ~$5 → switch fallback to GPT-5 mini, ~$0.10/run, re-trigger.)
2. **Close auto-issues #1–#5** (noise).
3. **ADK rebuild (next):** same marketing graph in Google ADK, guided step by step.
   First decision: model — Gemini via a free AI Studio key (learn ADK as designed)
   vs Ollama local via LiteLLM (prove the local point; more wiring). ADK has no
   LangGraph-style `interrupt()` — approval is orchestrated by the app between
   runner calls. The deck step is a custom tool wrapping python-pptx; the 9-check
   eval is custom code (a tool or callback), not ADK's built-in eval.
4. **Interview:** Nordea, Wed 18 Nov 13:30–14:15 CET (Teams). Sambla call today
   Tue 17 Nov 15:10–15:40 CET.

## gh-aw mechanics, as Siva put it (17 Nov 10:20, confirmed with one correction)
- Yes: you write .md files in .github/workflows/, `gh aw compile` generates the .lock.yml files, and you push BOTH — the .md is the source you edit, the lock is what Actions actually runs. Never edit a lock by hand; recompile.
- "Just a text version of our Python, nothing to do with our code" — almost. The workflows do NOT call the Python graph; the agent re-implements each node from prose. EXCEPT one place: the eval step runs our real script `scripts/eval_draft.py`. That is the one place the two worlds touch, and it is the most reliable step for exactly that reason.
- Siva's idea (right): mention which files/scripts to use at each stage. Already done for eval; can be extended — e.g. a `scripts/build_deck.py` for the deck step, a retrieval script for research. Principle: anchor deterministic stages to real scripts, leave the fuzzy stages (plan, write) to the agent in prose. The more a stage is pinned to a script, the closer gh-aw gets to the deterministic Python pipeline.

## Reuse by design (17 Nov 10:30, Siva's design correction)
- NOT two separate implementations. The two paths differ ONLY in orchestration; everything else is shared code. The ADK path must not duplicate the pipeline logic.
- Shared core (extract from graph.py into modules under src/marketing_pipeline/): rules + prompt strings (SERVICES, BANNED_PHRASES, outline/citation/CTA rules), retrieval (bge-m3 cosine top-3), deck builder (python-pptx), run/store IO (run-id, draft/deck/published paths), eval (scripts/eval_draft.py, already standalone).
- Thin layers only: graph.py wires the shared pieces into a LangGraph state graph; src/marketing_adk/ wires the SAME shared pieces into ADK agents + FunctionTools (thin wrappers, no duplicated logic). Prompt strings live in the shared module so the rules can't drift; only the orchestration wording differs.
- Entry: one CLI with an --engine flag (langgraph | adk) is the cleanest expression of this — two usage paths, one pipeline. (Proposed 17 Nov; confirm with Siva.)
- Why it matters: same KB, same rules, same eval, same deck builder — only the orchestrator differs. Any output difference is then attributable to the orchestrator, not to drifted logic. This is also what makes the comparison honest.
- Gate plan revised 17 Nov: Gate 1 (key+install) unchanged; new Gate 2 = extract shared core first, LangGraph path verified still green; ADK gates then build thin wrappers only.

## Shell gotcha — export matters (17 Nov 10:45, Gate 1)
- Siva put the Gemini key in muse's .bashrc line 39 as a plain assignment (`GOOGLE_API_KEY=...`, no `export`). grep finds it, but Python can't see it: a plain assignment is a shell variable, only `export` passes it to child processes. Fix: `export GOOGLE_API_KEY='...'`. Also note: non-interactive shells skip .bashrc's body (early-return guard), so scripts/ssh must export the key explicitly or source the line — don't rely on .bashrc outside interactive terminals.
- Verification pattern that keeps the key off chat: eval just the export line on AIBeast, then a tiny genai call; report only success/failure, never the value.

## Gate 1 GREEN (17 Nov ~10:52)
- export fix worked (line 39 now `export GOOGLE_API_KEY=...`); key present in shell; Gemini answered "Hi".
- MODEL CORRECTION: `gemini-2.5-flash` is retired for new users (API 404: "no longer available to new users"). The API itself points to `gemini-3.8-flash` — that is the model for the ADK build. Update any doc that says 2.5-flash.
## Gate 2 map — graph.py read in full (17 Nov)
- config.py already holds shared config (SERVICES, BRAND_NAME, SAMPLE_DOCS, env-overridable models). BUT graph.py lines 63-66 hardcode PLANNER/SYNTH/WRITER/EMBED models AFTER importing them from config — shadowing the env values. Gate 2 removes the shadows; config is the single source.
- Extraction: llm.py (_post/_generate/_embed, Ollama transport; _embed also feeds shared retrieve), rules.py (BANNED_PHRASES, PII_PATTERNS + prompt builders), retrieve.py (_cosine, _ensure_knowledge_base, top-3 retrieve), deck.py (_draft_sections/_draft_body_paragraphs/_keywords/_best_match/_assign_paragraphs/_deck_slide_bodies/_short + deck build; _deck_slide_bodies also feeds the eval 9th check), store.py (publish/reject IO). graph.py keeps TypedDicts, thin node wrappers, routing, graph wiring, approve interrupt, safe_json.
- Eval unification deferred to Gate 7: evals_node duplicates the 9 checks that scripts/eval_draft.py already implements. Known, time-boxed debt — Gate 7 makes ONE eval module used by both paths.
- Work happens in the AIBeast clone (~/langgraph-lab-github); the VM copy's graph.py is identical (630face). Uncommitted on the VM copy only: LEARNING-NOTES.md, GHAW-CHANGES-REVIEW.md, ghaw-changes.diff — sync/push later, not part of Gate 2.

## Conditional model selection by engine (17 Nov 11:10, Siva's correction)
- Siva caught it: the Ollama model lines must NOT be deleted or left commented — they are the LangGraph path's models. The right shape is a CONDITIONAL: model selection keyed by the active engine. Deleting throws away one path; commenting leaves dead code.
- Shape: config.py gains ENGINE (env, default "langgraph"), GEMINI_MODEL (default "gemini-3.8-flash"), and generation_model(role) — returns Ollama models for the LangGraph path, Gemini for the ADK path. Embeddings are NOT conditional: bge-m3 always, retrieval is shared. graph.py drops the commented duplicates (values already live in config.py) and keeps using the config Ollama constants — it IS the LangGraph path. The ADK side uses generation_model(..., engine="adk") / GEMINI_MODEL.
- The conditional executes at the engine choice (CLI --engine flag, Gate 9, sets ENGINE). Verify both branches: default run prints qwen3:14b; ENGINE=adk run prints gemini-3.8-flash.

## Step 2a verified both branches (17 Nov 11:17)
- LangGraph branch: `graph ok`, planner qwen3:14b. ADK branch (ENGINE=adk): planner + writer gemini-3.8-flash. The conditional works.

## Ollama lives at 172.22.112.1, not localhost (17 Nov 11:22, step 2b)
- The retrieve() import worked; the call failed with Connection refused — the repo's config.py defaults OLLAMA_BASE_URL to http://localhost:11434 and nothing listens there on AIBeast. Ollama answers at http://172.22.112.1:11434 (Windows host IP, models listed). The lab's step7 file hardcodes that address (line 57) — that is why the lab demo worked and the repo code didn't.
- Fix is environmental, NOT a code change: run with OLLAMA_BASE_URL=http://172.22.112.1:11434, or export it in .bashrc (interactive shells only). Do NOT change the repo default to the AIBeast address — the repo is public and meant to run anywhere; localhost:11434 is the correct default for a laptop. Machine-specific endpoints belong in env, same principle as the API key.

## Step 2b verified (17 Nov 11:24)
- Shared retrieve() works standalone: positioning.md 0.507, services-ai.md 0.499, services-platform.md 0.420 (bge-m3 cosine, best first). The OLLAMA_BASE_URL fix held (he exported it or prefixed it — the call reached 172.22.112.1:11434).

## Step 2c — test data fault, code correct (17 Nov 11:31)
- Deck test came back fallback: ['Safe AI automation', 'Local models first'], bodies 3 distinct 2 — NOT the expected [] / 3. Cause is the TEST draft, not deck.py: _draft_sections drops paragraphs of 20 chars or fewer. "Test paragraph one." is 19 chars, "Test paragraph two." is 19 — both dropped; "Test paragraph three." is 21 and survived. The two emptied slides fell back to identical doc snippets, so distinct dropped to 2.
- The lesson: the 9th eval check (deck_slides_distinct) did exactly its job — it caught identical slide bodies. The gate works; the test data was at fault. Re-test with paragraphs over 20 chars.

## Step 2c verified (17 Nov 11:32)
- Shared build_deck works: outputs/deck-test-2c.pptx, 5 slides, fallback [], bodies 3 distinct 3. The earlier 2/3 distinct was the test draft, not the code.

## Gate 2 — the extraction was copy, not move (17 Nov 11:39)
- The end-to-end run failed on NUM_CTX inside _generate. Root cause found by reading the AIBeast clone: graph.py (718 lines, barely shorter than the original 737) still contains ALL the moved code — _post/_generate/_embed (2a), _cosine/_ensure_knowledge_base (2b), all 8 deck helpers (2c) — plus the OLD retrieve_node and deck_node bodies. Only the imports and publish_node's wrapper were actually changed.
- The module tests passed because they tested the NEW modules directly; graph.py runs its own stale local copies, which shadow the imports. The stale _generate references NUM_CTX, removed from the imports in 2b. Lesson: an extraction is only done when the original is deleted — the end-to-end run is the proof, not the module tests.

## Gate 2 run — GPU out of memory, not a code error (17 Nov 12:03)
- The graph got all the way to the planner calling Ollama, then: cudaMalloc failed, out of memory — qwen3:14b needs an 8.8 GB CUDA buffer and the GPU didn't have it free. The extraction is proven at the code level; this is a Windows-host resource issue.
- Ollama api/ps shows NOTHING currently loaded, and qwen3:14b (8,846 MB) ran fine in yesterday's demo, so the card CAN hold it — something else on Windows was holding VRAM at that moment (another loaded model, a GPU-heavy app, or a zombie llama-server). Fix: check Task Manager / nvidia-smi on Windows, close GPU-heavy apps, restart Ollama, re-run. If the card is only 8 GB, qwen3:14b can never fit and the planner/writer fall back to qwen3:8b (5 GB) for local runs.

## Gate 2 run — persistent GPU OOM, numbers pinned down (17 Nov 12:05)
- Second run failed identically. nvidia-smi from WSL: RTX 3060, 12,288 MiB total, 3,382 MiB used, 8,906 MiB free, no compute processes visible (the 3.3 GB is Windows-side: desktop composition, Chrome, displays). qwen3:14b weights alone are 8,846 MB (~8,432 MiB); free VRAM minus CUDA context and KV cache leaves too little headroom, so the load fails.
- NUM_CTX is already 2048 (config comment says exactly this keeps a 14b inside a 12 GB GPU) — not the lever. Fixes in order: (1) close GPU-heavy Windows apps, above all Chrome, and re-run; (2) if still short, drop planner/writer to qwen3:8b via env (OLLAMA_PLANNER_MODEL=qwen3:8b OLLAMA_WRITER_MODEL=qwen3:8b, no code change — config is env-overridable). Yesterday's demo fit, so Windows-side VRAM usage is the variable that moved.

## Gate 2 run — full graph green on 14b (17 Nov 12:11)
- The run worked on the default 14b config after all (VRAM freed — the earlier OOM was a transient Windows-side hold): planner qwen3:14b, synthesis qwen3:8b (7.4s), writer qwen3:14b (421 tokens, 27.8s), eval_passed on attempt 1, paused at the approve interrupt with deck outputs/deck-gate2-test.pptx ready. The extraction is proven end to end — every node ran through the shared modules. Awaiting the approve step to close Gate 2.

## Gate 2 COMPLETE (17 Nov 12:13)
- approve gate2-test yes → GATE (yes): PASS, status published, published/gate2-test/draft.md + deck on disk. Full LangGraph path proven end to end on the extracted shared modules (llm/retrieve/rules/deck/store), planner + writer on qwen3:14b, eval passed attempt 1. The 14b OOM earlier was transient Windows-side VRAM (browser tabs); closing tabs frees it.
- Gate 3 starts: ADK scaffold + planner agent. rules.py's own docstring already promised the prompt builders would join it — that is this gate. ADK installed is version 2.14.1.

## Gemini free tier: 503 then hang (17 Nov 12:27)
- The ADK hello run 503'd (model overloaded), then on retry it hung. Same cause: the free tier is struggling, and the genai client's retry-with-backoff makes the command sit there for minutes looking hung instead of failing. Fix is a timeout around the runner call (120s, fail fast with a clear message) rather than letting it hang. If Gemini stays bad, the fork is LiteLLM + local Ollama for the ADK path — Siva's call, he chose Google free first.

## Fallback design (Siva's call, 17 Nov 12:42)
- Not a hard switch: Gemini first, local Ollama as automatic fallback when Google is down. Three Gemini failures in 20 min (503, hang, 503) made the case. The fallback is per-run and visible: the runner prints which backend served the request, so he always knows which model did the work. Needs `pip install "google-adk[extensions]"` (LiteLLM) + OLLAMA_API_BASE for LiteLLM (it does not read our OLLAMA_BASE_URL). Same pattern will be reused by the researcher/writer agents in Gates 4-5.

## google-adk[extensions] drags in pandas; install litellm directly (17 Nov 12:50)
- Dry-run proved it: the extensions extra pulls llama-index-readers-file, which pins pandas<3,>=2.0.0 — that is the package that kept building from source (meson python-not-found, then Cython<3 vs new NumPy headers). litellm alone has NO pandas in its tree. ADK's LiteLlm wrapper only needs `import litellm` — the "pip install google-adk[extensions]" message is just a hint, not a check. Fix: `~/langgraph-lab/.venv/bin/pip install "litellm>=1.84,<1.106.3"` (the extra's own version range), using the full venv pip path so there is no ambiguity about which pip runs.

## LiteLLM Ollama model name + KV cache CPU OOM (17 Nov 12:54)
- `ollama/chat/qwen3:14b` is WRONG: LiteLLM strips only `ollama/` and Ollama receives literally `chat/qwen3:14b` (model not found). Correct form is `ollama/qwen3:14b` — LiteLLM routes chat completions to /api/chat itself. Verified by direct test.
- But the direct test then hit a second blocker: Ollama 500, "failed to allocate CPU buffer of size 1476395008 ... failed to allocate buffer for kv cache". GPU VRAM is fine now (9,974 MiB free) — this is Windows RAM pressure: the 1.4 GB KV cache (2048 ctx) cannot allocate on CPU. The gate2-test worked this morning when RAM was freer. Same habit as VRAM, different resource: close tabs/apps to free RAM, or drop to qwen3:8b.

## Gate 3 COMPLETE (17 Nov 13:16)
- Hello run green via the fallback: "Gemini down (TimeoutError), falling back to local Ollama", backend ollama, valid plan JSON from local qwen3:14b — all 4 allowed services, both required KPIs, 6-item outline. One honest miss: "LangGraph Orchestration: Streamlined Workflows" is 46 chars, one over the 45-char outline rule (the prompt asks, nothing enforces it). The agent, the fallback chain, and the shared prompt all work. Reboot fixed the RAM pressure; the run happened on fresh memory.

## LiteLLM 1.106.2 + tools needs the `mcp` package (17 Nov 16:20)
- Researcher hello failed with `ModuleNotFoundError: No module named 'mcp'` — LiteLLM's `completion()` imports the MCP handler only when `tools` are present in the call (`main.py:5297`: `if not skip_mcp_handler and tools:`). The planner worked because it has no tools; the researcher has retrieve_docs, so it hit the import. `mcp` is not installed and LiteLLM 1.106.2 does not declare it — a LiteLLM packaging bug (its own bug-report link says so). Fix: `~/langgraph-lab/.venv/bin/pip install mcp`, then re-run the researcher.

## Ollama "token repeat limit" is a repetition loop, not a token count (17 Nov 16:24)
- Researcher hello failed with `OllamaException - {"error":"prediction aborted, token repeat limit reached"}`. This is NOT a context or max-tokens limit — Ollama's repetition guard aborted the generation because the model got stuck repeating the same tokens. The limits that exist: context window (num_ctx, ours 2048), output length (num_predict, unset = unlimited by default), and the repeat guard. Context was not the issue (prompt + bullets are short).
- Root cause: temperature 0 (greedy decoding) + qwen3:8b + free-form bullets. Greedy is deterministic — once the model starts repeating, it can never break out. The planner (temperature 0, structured JSON) does not loop; the researcher (free-form bullets, first agent with a tool) does. Fix: researcher temperature 0 → 0.2 (breaks the loop, stays near-deterministic). repeat_penalty is not available through ADK's GenerateContentConfig, so temperature is the lever. If it still loops, next step is the 14b for synthesis.

## Researcher synthesis: correct bullets, dirty wrapping (17 Nov 16:31)
- Temperature 0.2 fixed the loop — researcher hello completed, backend ollama, all 3 docs retrieved and the synthesis bullets are correct and faithful to the docs. But the synthesis text has the model's thinking out loud ("Okay, let's see...", "First, looking at...") plus a malformed JSON tail wrapping the bullets (`{"- positioning.md: ...": "# Example Consulting's AI Journey Guidance"}`). qwen3:8b reasons in its reply when the instruction does not forbid it. Fix: tighten the ADK researcher instruction to "output ONLY the bullet lines, one per line... No introduction, no reasoning, no JSON, no title, nothing before the first bullet and nothing after the last." Scoped to researcher.py (shared SYNTHESIS_INSTRUCTION untouched). Re-run and check the full output.

## Researcher: 8b cannot follow the agent+tool format — use the 14b (17 Nov 16:35)
- Retrieval + tool plumbing confirmed green: 3 docs with scores (positioning 0.8098, services-ai 0.6272, services-platform 0.6084), tool result captured from events (no fallback line), backend ollama. Scores differ from step 2b (0.507/0.499/0.420) because the query is the full DEFAULT_GOAL text, not a short phrase — expected.
- But the synthesis still failed: the model acknowledged "only the bullets, no extra text" in its reasoning, then output `{}` instead of bullets. The instruction tightening did not work — this is a capability gap, not a prompt gap. qwen3:8b handles a plain generate call (LangGraph path, works) but cannot reliably follow the ADK agent+tool format. Fix: ADK researcher uses the 14b (`adk_model("writer", backend)` in researcher.py, with a comment). LangGraph path keeps the 8b. Planner (14b, no tool) already proves the 14b follows instructions cleanly.

## Researcher: 14b ALSO hits the repeat limit — model size was not the cause (17 Nov 16:42)
- The 14b researcher run aborted with the same `OllamaException - {"error":"prediction aborted, token repeat limit reached"}`. So the 8b-was-too-weak diagnosis was wrong/incomplete: the 14b loops too. Correction to the earlier claim: the tool was NOT fully verified green — the docs in the synthesis prove the model saw them (only the tool could have shown them), but I never saw a backend line or a tool-call confirmation, only a pasted JSON fragment.
- Stop guessing, start seeing: add per-event logging to runner.py `_collect` (one line per event as it arrives: tool call + args, tool result, or text preview). A mid-run abort still leaves the earlier lines in stdout, showing exactly where it stopped — tool-call generation or final-answer generation. Then re-run the researcher and paste ALL output.

## Researcher: the fix is think=False, verified through the stack (17 Nov 18:38)
- The instrumented run showed the real sequence: Gemini 503 → fallback → Ollama run: a 902-char text event (the model reasoning out loud: "Okay, the user wants me to research... I need to use the retrieve_docs tool..."), then a CORRECT tool call (retrieve_docs, right query, top_k 3), then the tool result — and then nothing. The tool call works. The failure is the final-answer generation: qwen3 reasons at length and the reasoning loops until Ollama aborts (or comes out as garbage).
- Root cause: qwen3 is a thinking model and the ADK/LiteLLM agent loop lets its reasoning into the reply. Fix verified in source: LiteLLM's Ollama chat transformation accepts a `think` optional param and forwards it as Ollama's top-level `think` field (`data["think"] = think`); ADK's LiteLlm passes **kwargs to the litellm completion API. So `LiteLlm(model="ollama/qwen3:14b", think=False)` disables thinking at the source. Applied via a `think` param on adk_model (None = leave alone), used only by the researcher for now (planner works with thinking; writer will likely need it too in Gate 5). Temperature stays 0.2, tightened instruction stays.

## Gemini free tier quota exhausted — and the fallback did not catch 429 (17 Nov 18:45)
- New failure: `429 RESOURCE_EXHAUSTED`, free tier 20 generate_content requests/day for gemini-3.8-flash, all used; retry in ~14h15m (resets ~09:00 Wed 18 Nov). Today's repeated Gemini-first attempts burned the 20.
- Why the fallback did not save it: it catches ServerError (5xx) + TimeoutError only. A 429 is a ClientError (4xx). Verified MRO: ADK `_ResourceExhaustedError` → `ClientError` → `APIError`, and its `__init__` preserves `code=client_error.code` (429). So it sailed past the except clause. Fix: catch ClientError too, but re-raise unless code == 429 — other 4xx (400/401/403) are real problems and must fail loudly. Only public classes used.
- Tonight: run with `ADK_MODEL_BACKEND=ollama` to skip Gemini entirely — no quota burn, and it tests the think=False fix in isolation (think=False is in place but untested; the run died on Gemini before reaching Ollama). Bigger lesson: 20/day is too tight for active development; Ollama-first during development, Gemini for occasional checks.

## Timeout: already enforced, both legs (Siva's question, 17 Nov 18:49)
- `run_agent_once` wraps the whole agent run in `asyncio.wait_for(_collect(...), timeout=timeout)` (120s default). `run_with_fallback` passes `timeout` to BOTH legs — Gemini and Ollama each get their own 120s. Worst case ~240s total. A Gemini hang (the 12:27 genai retry-with-backoff case) is capped at 120s and the resulting TimeoutError is caught by the except, so it triggers the Ollama fallback. (asyncio.TimeoutError is the builtin TimeoutError since Python 3.11, so the except catches it.) An Ollama-leg timeout propagates — last resort, fails loudly, correct.
- Loose end spotted in the file: the 429 fix is half-applied — the import has ClientError but the except clause still reads `(ServerError, TimeoutError)`. Finish the except clause so a 429 falls back.

## Researcher: think=False did NOT stop the loop — it changed the failure mode (17 Nov 18:54)
- New run: Gemini 503 → fallback worked → Ollama leg called retrieve_docs FIVE times with the identical query, never produced a final answer, and the 120s timeout fired (TimeoutError). The timeout WORKED — first time seen firing, and it capped the run exactly as designed.
- Confirmed in researcher.py: `think=False` IS applied (`adk_model("writer", backend,think=False)`). It did not fix the loop; it changed it (reasoning-loop → tool-call-loop). qwen3 cannot run the ADK agent loop reliably either way: with thinking it reasons in circles, without it it repeats the tool call. The tool itself is fine (5 correct calls, 5 correct results). The `_generate` plain call in llm.py already has `"think": False` + temperature 0 — that is why the LangGraph path is reliable.
- Fix (given): partial events on timeout + anchored synthesis. `_collect` writes events into a passed-in list so they survive cancellation; `run_agent_once(..., partial_on_timeout=True)` returns ("", events) on timeout instead of raising; `run_with_fallback` passes the flag to the Ollama leg only. `run_researcher_once` then uses `find_tool_result` (already there) and, when the agent produced no final text, synthesises via the shared plain call `_generate(SYNTH_MODEL, synthesis_prompt(docs))`. Prefer the agent's own text when it answers; anchor to shared code when it loops. The run may still take the full 120s while the agent loops, but it returns a result instead of dying. Gemini-path verification of the pure agent loop waits for the quota reset (~09:00 Wed 18 Nov).

## Gate 4 GREEN on the Ollama path (17 Nov 19:14, run by Croissant per Siva's "go fix files")
- Run completed in ~135s: agent called retrieve_docs 5 times (looped, as expected), 120s timeout fired ("Agent timed out after 120s — using the events so far (10)"), partial events returned, anchored synthesis via the shared plain call produced 3 clean bullets (positioning 0.7911, services-ai 0.572, services-platform 0.5697; synthesis faithful, no reasoning/JSON). backend: ollama. Research JSON is the correct LangGraph shape. Gate 4 done.
- Two env gaps that broke the first two attempts tonight: (1) `ADK_MODEL_BACKEND=ollama` did NOT skip Gemini — run_with_fallback passed explicit backends, ignoring the env var. Fixed with an Ollama-only shortcut at the top of run_with_fallback (skip Gemini entirely when the env says ollama). (2) Non-interactive SSH does not source .bashrc, so GOOGLE_API_KEY is missing (Gemini leg fails "No API key", a ValueError the fallback does not catch) and OLLAMA_BASE_URL is unset (shared code defaulted to localhost:11434 → connection refused on _embed). The run command must set BOTH OLLAMA_BASE_URL and OLLAMA_API_BASE to http://172.22.112.1:11434. (Siva's interactive shell has both exported, which is why his runs reached Gemini/Ollama.)
- Remaining Gate 4 cleanup: strip the [event] debug prints from runner.py (kept for the verification run).

## Gate 5 GREEN — writer agent answered directly, no fallback needed (17 Nov 19:19)
- Writer hello run completed in ~59s on Ollama: the agent produced a 1438-char draft itself (no loop, no timeout, no fallback to the shared plain call). Draft has numeric citations [1]/[2]/[3] in every paragraph, the human-review-only CTA, and a Sources section; passes all three writer checks (>=200 chars, no banned phrases, has a citation). Gate 5 done.
- Contrast with the researcher: the writer is a pure generation task (no tools), and qwen3:14b handles the ADK loop fine for it. The researcher's loop problem is specific to tool-calling, not generation. So think=False + temperature 0.2 works for the writer; the anchored-synthesis fallback was only needed for the tool-carrying researcher.
- File-transfer lesson: heredocs mangle nested triple-quoted strings with double quotes (quotes stripped, broke graph.py). Reliable path for code with complex quoting: write the file locally with muse.write, scp to AIBeast, verify md5 (matched e52c08eb...). Surgical fixes: chr(39)/chr(10) to avoid quote nesting.
- Graph.py repair: the Gate 3/4 refactors had broken graph.py (planner_prompt/synthesis_prompt called but never imported — loads fine, NameErrors at runtime, unnoticed because the LangGraph path was not re-run). Fixed the import line; writer_node now uses the shared writer_prompt; graph imports OK.

## Gate 6 GREEN — deck built, 5 slides (17 Nov 19:26)
- Re-run after the fix: agent called make_deck once with the full correct args (plan now includes services), tool result captured, agent looped, 120s timeout fired, partial events (2) used. backend: ollama. Deck: outputs/deck-gate6-test.pptx, 5 slides (title + 3 outline + closing = 2 + 3, correct).
- fallback_slides = ["RAG and local inference", "Platforms and safe deployment"]: those two outline slides fell back to doc snippets (the draft paragraphs did not match those headings); the first outline slide got its draft paragraphs. Expected behaviour, not an error — the builder never leaves a slide empty.
- Root cause of the first failure: my test plan lacked 'services'. The shared build_deck reads plan['services'] for the closing slide (plus outline and objective). The writer_prompt does not need services, so the writer's test plan was fine — only the deck's plan needed it. Fixed by adding "services": list(SERVICES) to the deck hello's plan.

## Gate 7 GREEN — eval gate + retry loop works end to end (17 Nov 19:28)
- Eval wraps scripts/eval_draft.py evaluate() via importlib (the script is standalone, not a package; loading it by path is safe — stdlib imports only, main() guarded). No changes to the script or graph.py.
- Hello run: GOOD draft passed 8/9 (coverage 0.857, cited [1,2,3]) but FAILED on deck_slides_distinct — the deck's 3 content slides were identical (two outline slides fell back to the same snippets). The gate correctly caught a real deck problem, not a draft problem. SABOTAGED draft (citations stripped) failed on citations_present, all_docs_cited, coverage 0.0, and deck distinct — the gate catches a bad draft too.
- Retry loop proved its value: attempt 1 failed (deck distinct), writer re-wrote with the feedback ("Deck content slides are identical..."), deck rebuilt, attempt 2 PASSED (coverage 0.857). LOOP: attempts=2 passed=True. The loop is app-orchestrated in Python, not an ADK LoopAgent — the tool-calling agent loop is unreliable on qwen3, and deterministic stages belong in code. LoopAgent is the ADK-native form to revisit on Gemini.

## Gate 8 GREEN — approval + publish, both ways verified (17 Nov 19:30)
- run_approve_once with decision="yes" published to published/gate8-yes (draft.md + deck-gate8-test.pptx verified on disk). With decision="no" it returned rejected and verified no published/gate8-no folder was made. Nothing publishes without a yes. The app asks the human between runner calls (ADK has no interrupt()); decision can be passed in (for scripts/tests) or read from input().
- published/ now holds gate2-test (LangGraph) and gate8-yes (ADK). Gate 8 done.

## Gate 9 GREEN — full ADK pipeline end to end + committed (17 Nov 19:38)
- Full pipeline ran in ~7 min (425s), all on Ollama, decision=yes: planner produced the JSON plan; researcher looped 5x then 120s timeout, anchored synthesis, docs 4; writer 2029 chars directly; deck agent produced ZERO events in 120s (a new failure mode — stuck in reasoning that _collect does not print, not even a tool call), fallback built the deck directly (8 slides — the planner's outline had 6 items); eval attempt 1 passed (coverage 0.913); approve yes -> published to published/gate9-test (draft.md 2031 bytes + deck 35680 bytes). Status: published.
- Deck agent is the least reliable of the three tool/agents (0 events vs the researcher's 5 tool calls); the shared-code anchor is essential, not optional.
- Planner fix: planner.py was still on old code (local _run_agent_once, explicit gemini, only ServerError/TimeoutError caught) — it failed "No API key" because run_with_fallback was never wired in (the Gate 4b refactor had not landed). Fixed to use run_with_fallback; it now respects ADK_MODEL_BACKEND=ollama and catches 429.
- CLI: one CLI with --engine (langgraph default, adk single-phase). README: "Two engines" section with the table + commands + the honest qwen3 note.
- Committed locally as d14ccef on top of 630face (ADK package + shared modules + CLI + README + graph/config). PUSH NOT DONE — needs his explicit go-ahead; AIBeast has no GitHub login, so a push needs his PAT at the prompt (as on 16 Nov).
