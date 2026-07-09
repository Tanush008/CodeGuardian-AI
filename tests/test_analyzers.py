"""These tests actually invoke the semgrep/bandit binaries against small
fixture snippets with a known seeded vulnerability each. This is the start
of the benchmark harness recommended in the README: run these against a
larger fixture set and record precision/recall as your resume metric.

Requires `semgrep` and `bandit` to be installed (pip install -r requirements.txt).
Gitleaks requires the separate binary — skipped here if not on PATH.
"""
import shutil

import pytest

from app.analyzers.bandit_runner import run_bandit
from app.analyzers.gitleaks_runner import run_gitleaks
from app.analyzers.semgrep_runner import run_semgrep

# A deliberately vulnerable snippet: SQL built via string formatting.
SQLI_SNIPPET = '''
import sqlite3

def get_user(conn, username):
    query = "SELECT * FROM users WHERE username = '%s'" % username
    return conn.execute(query).fetchone()
'''

# A deliberately vulnerable snippet: eval() on external input.
EVAL_SNIPPET = '''
def run_expr(user_input):
    return eval(user_input)
'''

FAKE_SECRET_SNIPPET = '''
API_KEY = "sk_test_51H8x9aB3cD4eF5gH6iJ7kL8mN9oP0qR"
'''


@pytest.mark.asyncio
async def test_semgrep_flags_sql_injection():
    findings = await run_semgrep({"vuln.py": SQLI_SNIPPET})
    assert any("sql" in f["rule_id"].lower() or "injection" in f["message"].lower() for f in findings), (
        f"expected semgrep to flag SQL injection, got: {findings}"
    )


@pytest.mark.asyncio
async def test_bandit_flags_eval_usage():
    findings = await run_bandit({"vuln.py": EVAL_SNIPPET})
    assert any(f["rule_id"] == "B307" for f in findings), f"expected bandit B307 (eval), got: {findings}"


@pytest.mark.asyncio
async def test_bandit_ignores_non_python_files():
    findings = await run_bandit({"vuln.js": "eval('1+1')"})
    assert findings == []


@pytest.mark.asyncio
async def test_gitleaks_flags_hardcoded_secret():
    if shutil.which("gitleaks") is None:
        pytest.skip("gitleaks binary not installed on PATH")
    findings = await run_gitleaks({"config.py": FAKE_SECRET_SNIPPET})
    assert len(findings) >= 1
    assert findings[0]["severity"] == "CRITICAL"
