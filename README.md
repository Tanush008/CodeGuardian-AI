# CodeGuardian AI

**Autonomous multi-agent code review & DevSecOps platform for GitHub pull requests.**

CodeGuardian AI watches your pull requests, runs real static analysis tools (Semgrep, Bandit, Gitleaks), has an LLM triage those findings for severity and false positives, separately reviews the diff for code-quality/style against your team's own standards doc using RAG, merges everything into one prioritized report, and posts it as a single PR comment — automatically, on every push.

There is no dashboard in v1, and that's a deliberate choice, not a missing feature: the PR comment *is* the product. Open a pull request, watch the bot comment appear, and you've seen the whole system work end-to-end.

---

## Table of Contents

- [Why this exists](#why-this-exists)
- [How it works](#how-it-works)
- [Why static analysis *and* an LLM](#why-static-analysis-and-an-llm)
- [Why a real MCP server instead of the GitHub REST API](#why-a-real-mcp-server-instead-of-the-github-rest-api)
- [Project layout](#project-layout)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Creating the GitHub App](#creating-the-github-app-required-once)
- [Configuration](#configuration)
- [Running with Docker](#running-with-docker)
- [Testing](#testing)
- [Benchmarking (in progress)](#benchmarking-in-progress)
- [Roadmap](#roadmap)
- [Limitations](#limitations)

---

## Why this exists

Most "AI code review" tools fall into one of two traps:

1. **Pure LLM review** — fast to build, but the model hallucinates vulnerabilities that don't exist and misses ones that deterministic tools catch trivially (hardcoded secrets, SQL string concatenation, insecure deserialization).
2. **Pure static analysis** — reliable, but dumps raw findings on developers with no prioritization, no plain-English explanation, and no awareness of the team's own conventions.

CodeGuardian AI is built around a stricter division of labor: **deterministic tools decide *what* is wrong, the LLM decides *how bad* it is and *how to explain it*.** The LLM is never asked to invent a vulnerability from a blank diff — only to reason over findings that Semgrep, Bandit, or Gitleaks already produced. Quality/style review is handled separately through RAG against a real standards document, so "good code" is judged against *your* rules, not generic best-practice folklore baked into the model's training data.

## How it works

```
GitHub PR event
      │  (webhook, HMAC-verified)
      ▼
FastAPI webhook receiver         (app/core/webhook.py)
      │
      ▼
Supervisor Agent — LangGraph StateGraph     (app/agents/supervisor.py)
      │
      ├──► Security Agent  ──► Semgrep / Bandit / Gitleaks  ──► Groq triage
      │        (app/agents/security_agent.py)
      │
      └──► Quality Agent   ──► RAG over coding-standards.md  ──► Groq review
               (app/agents/quality_agent.py)
      │
      ▼
Aggregator — merges + ranks findings by severity   (app/agents/aggregator.py)
      │
      ▼
GitHub MCP Server                (app/mcp_servers/github_mcp.py)
      │
      ▼
Prioritized report posted as a PR comment
```

Step by step:

1. A developer opens or updates a pull request. GitHub fires a webhook to the FastAPI receiver, which verifies the payload signature against `GITHUB_WEBHOOK_SECRET` (HMAC) before trusting anything in it.
2. The webhook hands the event to a **Supervisor Agent**, implemented as a LangGraph `StateGraph`. The supervisor fans out to two agents *in parallel* rather than running them sequentially — there's no dependency between "is this code secure" and "does this code match our style guide," so there's no reason to pay that latency serially.
3. The **Security Agent** runs Semgrep, Bandit, and Gitleaks against the changed files, then sends the raw findings to Groq (Llama 3.1) for triage: is this a true positive, how severe is it in context, and how do we explain it to a human in one paragraph.
4. The **Quality Agent** pulls the team's `coding-standards.md` into a ChromaDB vector store and retrieves the passages most relevant to the diff, then asks the LLM to review the diff *against those retrieved standards specifically* — not against generic conventions it happens to know.
5. The **Aggregator** merges both agents' outputs, ranks everything by severity, and renders a single Markdown report.
6. The report goes out through the **GitHub MCP server**, which posts it as one PR comment.

## Why static analysis *and* an LLM

- **Semgrep / Bandit / Gitleaks are deterministic and explainable.** Same diff in, same findings out, every time. They're excellent at pattern-matching known-bad code but can't reason about business intent or judge severity in context — every finding gets treated with the same generic weight.
- **The LLM (Groq / Llama 3.1) never invents vulnerabilities from scratch.** It only triages and explains findings the static tools already produced, and separately reviews style/quality against the repo's own standards doc via RAG. This keeps the security-critical path fully deterministic while spending the LLM's reasoning where it actually adds value: plain-English explanation, severity judgment, and filtering out static-analysis noise.

This split matters for anyone deciding whether to trust the output: a security finding can always be traced back to a specific Semgrep/Bandit/Gitleaks rule, never to an LLM guess.

## Why a real MCP server instead of the GitHub REST API

The agent graph never calls the GitHub REST API directly. It talks to GitHub exclusively through a small set of typed MCP tools — `get_pr_diff`, `post_review_comment`, `list_changed_files`, `get_file_content` — served by a real MCP server (`app/mcp_servers/github_mcp.py`) built with the MCP SDK's subprocess/stdio transport, doing a genuine protocol handshake. This is not a thin REST wrapper dressed up with an MCP-shaped interface.

Two concrete benefits fall out of that choice:

- **Transport is decoupled from reasoning.** Swapping GitHub for GitLab later means writing a new MCP server, not touching a single agent.
- **Every external action is a typed, schema-validated, logged tool call**, which gives a clean audit boundary between "the agents decided X" and "the agents were allowed to do Y."

## Project layout

```
app/
  core/
    config.py          # env-based settings
    webhook.py          # FastAPI app + GitHub webhook endpoint + HMAC verification
    llm.py              # Groq client wrapper
  agents/
    state.py            # shared LangGraph state schema
    supervisor.py       # supervisor graph: fan-out / fan-in
    security_agent.py   # runs analyzers + LLM triage
    quality_agent.py    # RAG-grounded quality review
    aggregator.py        # merges + ranks findings, renders markdown report
  analyzers/
    semgrep_runner.py
    bandit_runner.py
    gitleaks_runner.py
  rag/
    standards_store.py  # ChromaDB over coding-standards.md
  mcp_servers/
    github_mcp.py        # MCP server exposing GitHub tools
  github/
    app_auth.py          # GitHub App JWT + installation token auth
tests/
  test_analyzers.py
  test_aggregator.py
  fixtures/
docs/
  coding-standards.md    # sample standards doc used for the RAG demo
semgrep-rules/           # custom Semgrep rule definitions
```

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph `StateGraph` | Explicit fan-out/fan-in for parallel agents, typed shared state, easy to reason about vs. a hand-rolled agent loop |
| LLM | Groq (Llama 3.1) | Low-latency inference so triage doesn't add noticeable delay to the PR-comment turnaround |
| Static analysis | Semgrep, Bandit, Gitleaks | Deterministic, industry-standard coverage of code patterns, Python-specific issues, and leaked secrets |
| RAG store | ChromaDB | Lightweight, local vector store for the team standards doc — no external RAG infra needed |
| API layer | FastAPI | Async webhook receiver with clean request validation |
| GitHub integration | MCP server (MCP SDK, stdio transport) | Typed tool boundary between agents and GitHub, see above |
| Auth | GitHub App (JWT + installation tokens) | Scoped, revocable permissions instead of a personal access token |
| Deployment | Docker → Render / Railway | Single container, minimal ops overhead for a portfolio-scale deployment |

## Getting started

**Prerequisites:** Python 3.10+, Docker (optional but recommended), a GitHub account you can create a GitHub App under, a [Groq API key](https://console.groq.com), and `ngrok` (or similar) if testing locally.

```bash
# 1. Clone and configure
git clone https://github.com/Tanush008/CodeGuardian-AI.git
cd CodeGuardian-AI
cp .env.example .env
# fill in GROQ_API_KEY, GITHUB_APP_ID, GITHUB_PRIVATE_KEY_PATH, GITHUB_WEBHOOK_SECRET

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install analyzer binaries
pip install semgrep bandit
# Gitleaks isn't a pip package — install via brew or download the binary,
# see app/analyzers/gitleaks_runner.py for the expected path

# 4. Run locally
uvicorn app.core.webhook:app --reload --port 8000

# 5. Expose the webhook for GitHub to reach
ngrok http 8000
# point your GitHub App's webhook URL at <ngrok-url>/webhook/github
```

## Creating the GitHub App (required, once)

CodeGuardian AI runs as a **GitHub App**, not a personal access token integration — this keeps its permissions scoped and revocable per-repository.

1. GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. **Webhook URL:** your ngrok URL (local) or your Render/Railway URL (deployed) + `/webhook/github`.
3. **Webhook secret:** generate one and put it in `GITHUB_WEBHOOK_SECRET` — this is what the FastAPI receiver uses to verify incoming payloads.
4. **Permissions:** Pull requests → Read & Write, Contents → Read-only.
5. **Subscribe to events:** Pull request.
6. Generate a private key, save it somewhere safe, and point `GITHUB_PRIVATE_KEY_PATH` at it.
7. Install the App on whichever repository(ies) you want reviewed.

## Configuration

All configuration lives in `.env` (see `.env.example` for the full list):

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Auth for the Groq LLM calls used in triage and quality review |
| `GITHUB_APP_ID` | Identifies the GitHub App during JWT auth |
| `GITHUB_PRIVATE_KEY_PATH` | Path to the App's private key, used to mint installation tokens |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret used to verify incoming webhook payloads |

## Running with Docker

```bash
docker build -t codeguardian .
docker run --env-file .env -p 8000:8000 codeguardian
```

For deployment, push the image to Render or Railway, set the same environment variables in the platform's dashboard, and point the GitHub App's webhook URL at the deployed service instead of ngrok. `docker-compose.yml` is included for local multi-service runs.

## Testing

```bash
pytest
```

Tests cover the analyzer wrappers (`test_analyzers.py`) and the aggregation/ranking logic (`test_aggregator.py`), with fixtures under `tests/fixtures/` standing in for real diffs and Semgrep/Bandit/Gitleaks output, so the suite doesn't depend on network calls or a live LLM.

## Benchmarking (in progress)

The credibility of a code-review bot lives or dies on whether it's actually useful, not just functional — so the plan is to run the pipeline against a fixture repo with a known number of seeded vulnerabilities across several test PRs and record:

- **Precision / recall vs. raw Semgrep output** — does LLM triage reduce false positives without dropping true positives?
- **Median time from PR-open to comment-posted** — the whole point is fast feedback.
- **% of findings a human reviewer marks "useful" vs. "noise"** — even 5–10 manually graded PRs turns this from a vibe into a number.

These results will be added here once collected.

## Roadmap

- [ ] Benchmark results (precision/recall, latency, human-graded usefulness)
- [ ] GitLab support via a second MCP server (no changes to the agent layer required)
- [ ] Per-repository configuration for which analyzers run and which standards doc to use
- [ ] Incremental re-review on new commits to an already-reviewed PR, instead of a full re-run

## Limitations

- v1 has no persistent dashboard or history — the PR comment is the only surface. Past review results aren't stored or queryable yet.
- Quality review is only as good as the `coding-standards.md` it's given; a thin or generic standards doc will produce thin or generic review comments.
- Gitleaks requires a separate binary install (not distributed via pip), which adds a small amount of setup friction versus Semgrep/Bandit.

----------

Built by [Tanush008](https://github.com/Tanush008).
