"""Runs Semgrep against a checked-out copy of the changed files.

Semgrep is invoked as a subprocess against a temp directory containing only
the changed files (not the whole repo) — keeps scans fast and scoped to what
actually changed in the PR. Results are normalized into a common Finding
shape shared with bandit_runner and gitleaks_runner so the Security Agent
can treat all three tools uniformly.

We use a bundled, pinned rule set (semgrep-rules/security.yml) instead of
`--config=auto`. `auto` fetches rules from semgrep.dev's registry at scan
time, which means: (a) a hard runtime dependency on an external service
being reachable, (b) non-reproducible scans as the registry ruleset changes
under you, and (c) failures in network-restricted CI/deploy environments.
A bundled rule set is slower to grow but versioned, explainable in an
interview, and works offline.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "semgrep-rules"

# Semgrep only ever emits ERROR/WARNING/INFO natively. Map those onto the
# same CRITICAL/HIGH/MEDIUM/LOW/INFO scale that bandit_runner and
# gitleaks_runner already use, so the Aggregator's severity sort and
# summary counts stay meaningful across all three tools.
_SEMGREP_SEVERITY_MAP = {
    "ERROR": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
}


async def run_semgrep(files: dict[str, str]) -> list[dict]:
    """files: {relative_path: file_content}. Returns a list of normalized
    findings: {tool, rule_id, severity, file, line, message}.
    """
    with tempfile.TemporaryDirectory(prefix="cg_semgrep_") as tmpdir:
        tmp_path = Path(tmpdir)
        for rel_path, content in files.items():
            dest = tmp_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8", errors="ignore")

        proc = await asyncio.create_subprocess_exec(
            "semgrep",
            f"--config={_RULES_PATH}",
            "--json",
            "--quiet",
            "--timeout=60",
            str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode not in (0, 1):  # semgrep returns 1 when findings exist
            logger.error("semgrep_failed", stderr=stderr.decode(errors="replace")[:1000])
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.error("semgrep_bad_output", stdout=stdout.decode(errors="replace")[:500])
            return []

        findings = []
        for r in data.get("results", []):
            rel_file = str(Path(r["path"]).relative_to(tmp_path))
            raw_severity = r.get("extra", {}).get("severity", "INFO").upper()
            findings.append(
                {
                    "tool": "semgrep",
                    "rule_id": r.get("check_id", "unknown"),
                    "severity": _SEMGREP_SEVERITY_MAP.get(raw_severity, "LOW"),
                    "file": rel_file,
                    "line": r.get("start", {}).get("line", 0),
                    "message": r.get("extra", {}).get("message", ""),
                }
            )
        logger.info("semgrep_complete", finding_count=len(findings))
        return findings