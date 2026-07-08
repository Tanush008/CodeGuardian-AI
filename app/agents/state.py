"""Shared state schema for the Supervisor's LangGraph StateGraph.

Every node (agent) reads from and writes to this single TypedDict. Keeping
it as one explicit schema (rather than passing ad-hoc dicts between agents)
is what makes the graph debuggable — you can log the full state after any
node and know exactly what every agent saw and produced.
"""
from typing import TypedDict


class PRContext(TypedDict):
    installation_id: int
    owner: str
    repo: str
    pr_number: int
    pr_title: str


class Finding(TypedDict):
    tool: str            # semgrep | bandit | gitleaks | quality-llm
    rule_id: str
    severity: str         # CRITICAL | HIGH | MEDIUM | LOW | INFO
    file: str
    line: int
    message: str          # raw tool message
    explanation: str      # LLM-triaged plain-English explanation (filled in later)
    is_likely_false_positive: bool


class ReviewState(TypedDict, total=False):
    pr_context: PRContext
    changed_files: dict[str, str]     # {relative_path: file_content}
    security_findings: list[Finding]
    quality_findings: list[Finding]
    all_findings: list[Finding]        # populated by aggregator
    report_markdown: str               # populated by aggregator
    posted_comment_url: str
    errors: list[str]                  # non-fatal errors from any node, surfaced in report
