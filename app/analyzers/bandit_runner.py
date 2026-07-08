"""Runs Bandit against changed Python files only.

Bandit is Python-specific and complements Semgrep with deeper knowledge of
Python-specific issues (e.g. use of `eval`, insecure `pickle`, weak random
for security contexts) via its dedicated rule set (B1xx-B7xx).
"""
import asyncio
import json
import tempfile
from pathlib import Path

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_BANDIT_SEVERITY_MAP = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH"}


async def run_bandit(files: dict[str, str]) -> list[dict]:
    """files: {relative_path: file_content}. Only .py files are scanned;
    non-Python files are silently skipped (Bandit would error on them).
    """
    py_files = {path: content for path, content in files.items() if path.endswith(".py")}
    if not py_files:
        return []

    with tempfile.TemporaryDirectory(prefix="cg_bandit_") as tmpdir:
        tmp_path = Path(tmpdir)
        for rel_path, content in py_files.items():
            dest = tmp_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8", errors="ignore")

        proc = await asyncio.create_subprocess_exec(
            "bandit",
            "-r",
            str(tmp_path),
            "-f",
            "json",
            "-q",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.error("bandit_bad_output", stderr=stderr.decode(errors="replace")[:500])
            return []

        findings = []
        for r in data.get("results", []):
            rel_file = str(Path(r["filename"]).relative_to(tmp_path))
            findings.append(
                {
                    "tool": "bandit",
                    "rule_id": r.get("test_id", "unknown"),
                    "severity": _BANDIT_SEVERITY_MAP.get(r.get("issue_severity", "LOW"), "LOW"),
                    "file": rel_file,
                    "line": r.get("line_number", 0),
                    "message": r.get("issue_text", ""),
                }
            )
        logger.info("bandit_complete", finding_count=len(findings))
        return findings
