"""Shared state schema for the Supervisor's LangGraph StateGraph.

Every node (agent) reads from and writes to this single TypedDict. Keeping
it as one explicit schema (rather than passing ad-hoc dicts between agents)
is what makes the graph debuggable — you can log the full state after any
node and know exactly what every agent saw and produced.

IMPORTANT: security_agent_node and quality_agent_node run in parallel (fan-out
from fetch_changed_files). LangGraph's default state channels allow only ONE
writer per key per parallel step, so:
  - each parallel node must return ONLY the keys it actually changes (never
    the full merged state via `{**state, ...}`), or you get
    `InvalidUpdateError: Can receive only one value per step`.
  - any key that legitimately IS written by multiple parallel nodes (like
    `errors`) needs an Annotated reducer telling LangGraph how to combine
    the concurrent writes, instead of just overwriting.
"""
import operator
from typing import Annotated, TypedDict


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
    pr_context: PRContext                          # written once, by fetch_changed_files_node only
    changed_files: dict[str, str]                  # written once, by fetch_changed_files_node only
    security_findings: list[Finding]               # written once, by security_agent_node only
    quality_findings: list[Finding]                # written once, by quality_agent_node only
    all_findings: list[Finding]                     # populated by aggregator
    report_markdown: str                            # populated by aggregator
    posted_comment_url: str
    # errors CAN be written by multiple parallel nodes (security + quality
    # agents both may report failures in the same step), so it needs a
    # reducer: operator.add concatenates the lists instead of raising a
    # conflict. Each node should return only the NEW errors it adds, not
    # the accumulated list — the reducer handles accumulation for you.
    errors: Annotated[list[str], operator.add]
