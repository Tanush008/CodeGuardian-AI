"""Runs Gitleaks against changed files to catch hardcoded secrets.

Gitleaks is run with `--no-git` against a plain directory of changed files
(not a git history scan) since we only have the PR's changed content, not a
full clone. This catches secrets introduced in this diff; it does not scan
prior history — that's a deliberate v1 scope limit, not an oversight.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_SEVERITY = "CRITICAL"  # any hardcoded secret is treated as critical, no tiers


async def run_gitleaks(files: dict[str, str]) -> list[dict]:
    """files: {relative_path: file_content}. Returns normalized findings."""
    with tempfile.TemporaryDirectory(prefix="cg_gitleaks_") as tmpdir:
        tmp_path = Path(tmpdir)
        for rel_path, content in files.items():
            dest = tmp_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8", errors="ignore")

        report_path = tmp_path / "_gitleaks_report.json"
        proc = await asyncio.create_subprocess_exec(
            "gitleaks",
            "detect",
            "--no-git",
            "--source",
            str(tmp_path),
            "--report-format",
            "json",
            "--report-path",
            str(report_path),
            "--exit-code",
            "0",  # don't fail the process on findings, we parse the report
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if not report_path.exists():
            # gitleaks exits without writing a report if zero findings, in
            # some versions — treat that as "no findings", not an error.
            return []

        try:
            data = json.loads(report_path.read_text())
        except json.JSONDecodeError:
            logger.error("gitleaks_bad_output", stderr=stderr.decode(errors="replace")[:500])
            return []

        findings = []
        for r in data:
            rel_file = str(Path(r["File"]).relative_to(tmp_path))
            findings.append(
                {
                    "tool": "gitleaks",
                    "rule_id": r.get("RuleID", "generic-secret"),
                    "severity": _SEVERITY,
                    "file": rel_file,
                    "line": r.get("StartLine", 0),
                    "message": f"Potential hardcoded secret matching rule '{r.get('RuleID')}'",
                }
            )
        logger.info("gitleaks_complete", finding_count=len(findings))
        return findings
