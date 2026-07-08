"""Security Agent.

Deterministic step: run Semgrep, Bandit, Gitleaks in parallel over the
PR's changed files.
LLM step: for each raw finding, ask Groq to (a) explain it in plain English,
and (b) flag if it's likely a false positive given the surrounding code
context. The LLM never invents findings — it only annotates ones the
static tools already produced. This is the "know when to use AI and when
not to" boundary called out in the project design.
"""
import asyncio

from app.analyzers.bandit_runner import run_bandit
from app.analyzers.gitleaks_runner import run_gitleaks
from app.analyzers.semgrep_runner import run_semgrep
from app.core.llm import complete_json
from app.core.logging_setup import get_logger
from app.agents.state import Finding, ReviewState

logger = get_logger(__name__)

_TRIAGE_SYSTEM_PROMPT = """You are a senior application security engineer triaging static
analysis findings for a pull request. For the given finding, you will be shown the rule
that fired, the file/line, the raw tool message, and a snippet of the surrounding code.

Respond with JSON: {"explanation": "<2-3 sentence plain-English explanation of the risk,
written for a developer who may not know security jargon>", "is_likely_false_positive":
<true/false>, "false_positive_reason": "<if true, why; else empty string>"}

Be conservative: only mark is_likely_false_positive=true if the surrounding code clearly
neutralizes the issue (e.g. input is already validated/escaped a few lines above, or it's
in a test fixture with fake data). When uncertain, mark it false (i.e. keep it as a real
finding) — a missed true positive is worse than an extra review item."""


async def _triage_finding(finding: dict, code_context: str) -> Finding:
    user_prompt = (
        f"Tool: {finding['tool']}\nRule: {finding['rule_id']}\nSeverity: {finding['severity']}\n"
        f"File: {finding['file']}:{finding['line']}\nRaw message: {finding['message']}\n\n"
        f"Surrounding code:\n```\n{code_context}\n```"
    )
    try:
        result = await complete_json(_TRIAGE_SYSTEM_PROMPT, user_prompt)
    except ValueError:
        # LLM triage failed after retries — degrade gracefully, don't drop the
        # finding. A raw untriaged finding is still useful; a silently
        # dropped security finding is not acceptable.
        result = {"explanation": finding["message"], "is_likely_false_positive": False}

    return Finding(
        tool=finding["tool"],
        rule_id=finding["rule_id"],
        severity=finding["severity"],
        file=finding["file"],
        line=finding["line"],
        message=finding["message"],
        explanation=result.get("explanation", finding["message"]),
        is_likely_false_positive=bool(result.get("is_likely_false_positive", False)),
    )


def _get_code_context(files: dict[str, str], file_path: str, line: int, window: int = 5) -> str:
    content = files.get(file_path, "")
    lines = content.splitlines()
    if not lines:
        return ""
    start = max(0, line - window - 1)
    end = min(len(lines), line + window)
    return "\n".join(lines[start:end])


async def security_agent_node(state: ReviewState) -> ReviewState:
    files = state["changed_files"]
    logger.info("security_agent_start", file_count=len(files))

    raw_findings_lists = await asyncio.gather(
        run_semgrep(files), run_bandit(files), run_gitleaks(files), return_exceptions=True
    )

    errors = list(state.get("errors", []))
    raw_findings: list[dict] = []
    for tool_name, result in zip(("semgrep", "bandit", "gitleaks"), raw_findings_lists):
        if isinstance(result, Exception):
            errors.append(f"{tool_name} failed: {result}")
            logger.error("analyzer_failed", tool=tool_name, error=str(result))
        else:
            raw_findings.extend(result)

    triaged = await asyncio.gather(
        *[
            _triage_finding(f, _get_code_context(files, f["file"], f["line"]))
            for f in raw_findings
        ]
    )

    logger.info("security_agent_complete", raw_count=len(raw_findings), triaged_count=len(triaged))
    return {**state, "security_findings": list(triaged), "errors": errors}
