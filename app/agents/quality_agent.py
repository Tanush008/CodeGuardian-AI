"""Quality Agent.

For each changed file, retrieves the most relevant chunks of the team's
coding-standards doc via RAG, then asks Groq to review the file against
those specific standards (not generic style opinions). This is what makes
the review "grounded" rather than a generic LLM code review — the model is
explicitly given the team's actual stated rules and asked to check
adherence to *those*, and to cite which rule a violation maps to.
"""
from app.core.llm import complete_json
from app.core.logging_setup import get_logger
from app.rag.standards_store import standards_store
from app.agents.state import Finding, ReviewState

logger = get_logger(__name__)

_QUALITY_SYSTEM_PROMPT = """You are a senior engineer reviewing a code file against your
team's specific coding standards (provided below). Only flag violations of the standards
shown — do not invent generic style preferences that aren't in the provided standards.

Respond with JSON: {"findings": [{"rule_id": "<short slug of the standard violated,
e.g. 'naming-boolean-predicate'>", "severity": "<LOW|MEDIUM|HIGH>", "line": <int, best
estimate>, "message": "<what the standard says>", "explanation": "<1-2 sentences on
where/how this file violates it>"}]}

If the file has no standards violations, respond with {"findings": []}. Do not flag
more than 5 issues per file — prioritize the most impactful ones."""

_MAX_CHARS_PER_FILE = 6000  # cap to keep prompts within a reasonable token budget


async def _review_file(path: str, content: str) -> list[Finding]:
    truncated = content[:_MAX_CHARS_PER_FILE]
    relevant_standards = standards_store.query(truncated, top_k=3)
    if not relevant_standards:
        return []

    standards_block = "\n---\n".join(relevant_standards)
    user_prompt = f"Coding standards (relevant excerpts):\n{standards_block}\n\nFile: {path}\n```\n{truncated}\n```"

    try:
        result = await complete_json(_QUALITY_SYSTEM_PROMPT, user_prompt)
    except ValueError:
        logger.error("quality_agent_llm_failed", file=path)
        return []

    findings = []
    for f in result.get("findings", [])[:5]:
        findings.append(
            Finding(
                tool="quality-llm",
                rule_id=f.get("rule_id", "standards-violation"),
                severity=f.get("severity", "LOW").upper(),
                file=path,
                line=int(f.get("line", 0) or 0),
                message=f.get("message", ""),
                explanation=f.get("explanation", ""),
                is_likely_false_positive=False,
            )
        )
    return findings


async def quality_agent_node(state: ReviewState) -> ReviewState:
    files = state["changed_files"]
    logger.info("quality_agent_start", file_count=len(files))

    all_findings: list[Finding] = []
    errors = list(state.get("errors", []))
    for path, content in files.items():
        try:
            all_findings.extend(await _review_file(path, content))
        except Exception as exc:  # noqa: BLE001 - a single file failing shouldn't kill the review
            errors.append(f"quality review of {path} failed: {exc}")
            logger.error("quality_agent_file_failed", file=path, error=str(exc))

    logger.info("quality_agent_complete", finding_count=len(all_findings))
    return {**state, "quality_findings": all_findings, "errors": errors}
