# CodeGuardian AI — Autonomous Multi-Agent Code Review Platform (v1)

A multi-agent system that reviews GitHub pull requests: runs deterministic static
analysis (Semgrep, Bandit, Gitleaks), triages findings with an LLM, checks code
quality against a team standards doc via RAG, and posts one prioritized report
as a PR comment.

## Architecture (v1)

```
GitHub PR event
      │  (webhook, HMAC-verified)
      ▼
FastAPI webhook receiver  (app/core/webhook.py)
      │
      ▼
Supervisor Agent (LangGraph StateGraph)  (app/agents/supervisor.py)
      │
      ├──► Security Agent  ──► Semgrep / Bandit / Gitleaks  ──► Groq triage
      │                                                          (app/agents/security_agent.py)
      │
      └──► Quality Agent   ──► RAG over coding-standards.md  ──► Groq review
                                                                  (app/agents/quality_agent.py)
      │
      ▼
Aggregator merges + ranks findings by severity  (app/agents/aggregator.py)
      │
      ▼
GitHub MCP Server (app/mcp_servers/github_mcp.py)
      │
      ▼
PR comment posted on GitHub
```

Why MCP instead of calling the GitHub REST API directly: the agent graph talks
to GitHub only through a small set of typed MCP tools (`get_pr_diff`,
`post_review_comment`, `list_changed_files`, `get_file_content`). This means
the agent layer is decoupled from the transport — swapping GitHub for GitLab
later is a new MCP server, not a rewrite of the agents. It also gives us a
clean audit boundary: every external action the agents take is a logged,
schema-validated tool call.

## Why static analysis AND an LLM (not just one)

- Semgrep/Bandit/Gitleaks are deterministic and explainable: same diff in,
  same findings out, every time. They're good at pattern-matching known-bad
  code (hardcoded secrets, SQL string concatenation, insecure deserialization)
  but can't reason about business intent or judge severity in context.
- The LLM (Groq/Llama 3.1) never invents vulnerabilities from scratch — it
  only triages and explains findings the static tools already produced, and
  separately reviews style/quality against the repo's own standards doc via
  RAG. This keeps the security-critical path deterministic while using the
  LLM where it adds real value: plain-English explanation, severity
  reasoning, and false-positive filtering.

## Project layout

```
app/
  core/
    config.py        # env-based settings
    webhook.py        # FastAPI app + GitHub webhook endpoint + HMAC verification
    llm.py            # Groq client wrapper
  agents/
    state.py          # shared LangGraph state schema
    supervisor.py      # supervisor graph: fan-out/fan-in
    security_agent.py  # runs analyzers + LLM triage
    quality_agent.py   # RAG-grounded quality review
    aggregator.py       # merges + ranks findings, renders markdown report
  analyzers/
    semgrep_runner.py
    bandit_runner.py
    gitleaks_runner.py
  rag/
    standards_store.py # ChromaDB over coding-standards.md
  mcp_servers/
    github_mcp.py       # MCP server exposing GitHub tools
  github/
    app_auth.py         # GitHub App JWT + installation token auth
tests/
  test_analyzers.py
  test_aggregator.py
  fixtures/
docs/
  coding-standards.md   # sample standards doc for the RAG demo
```

## Setup

1. `cp .env.example .env` and fill in:
   - `GROQ_API_KEY`
   - `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET`
2. `pip install -r requirements.txt`
3. Install analyzer binaries: `pip install semgrep bandit`, and
   `brew install gitleaks` (or download binary — see analyzers/gitleaks_runner.py)
4. Run locally: `uvicorn app.core.webhook:app --reload --port 8000`
5. Expose with `ngrok http 8000` and point your GitHub App webhook URL at
   the ngrok URL + `/webhook/github`.
6. Deploy: `docker build -t codeguardian . && ` push to Render/Railway;
   set the same env vars there and point the GitHub App webhook at the
   deployed URL.

## Creating the GitHub App (required — do this once)

1. GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
2. Webhook URL: your ngrok/Render URL + `/webhook/github`.
3. Webhook secret: generate one, put it in `GITHUB_WEBHOOK_SECRET`.
4. Permissions: Pull requests (Read & Write), Contents (Read-only).
5. Subscribe to events: Pull request.
6. Generate a private key, save it, set `GITHUB_PRIVATE_KEY_PATH`.
7. Install the App on the repo(s) you want reviewed.

## Benchmark (fill this in as you build — this is what makes v1 credible)

Run the pipeline against a fixture repo with N seeded vulnerabilities across
M test PRs and record:
- Precision / recall vs. raw Semgrep output (does LLM triage reduce false
  positives without missing true positives?)
- Median time from PR-open to comment-posted
- % of findings a human reviewer marked "useful" vs "noise" (even 5-10
  manually graded PRs gives you a real number to put on your resume)
