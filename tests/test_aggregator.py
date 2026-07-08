"""Aggregator tests are pure-logic and require no API keys / network — they
should run in CI on every PR to this repo itself (dogfooding)."""
from app.agents.aggregator import aggregator_node
from app.agents.state import Finding


def _finding(**overrides) -> Finding:
    base = Finding(
        tool="semgrep",
        rule_id="test-rule",
        severity="MEDIUM",
        file="app.py",
        line=10,
        message="raw message",
        explanation="explained",
        is_likely_false_positive=False,
    )
    base.update(overrides)
    return base


def test_severity_ordering():
    state = {
        "security_findings": [
            _finding(severity="LOW", file="a.py"),
            _finding(severity="CRITICAL", file="b.py"),
            _finding(severity="MEDIUM", file="c.py"),
        ],
        "quality_findings": [],
        "errors": [],
    }
    result = aggregator_node(state)
    severities = [f["severity"] for f in result["all_findings"]]
    assert severities == ["CRITICAL", "MEDIUM", "LOW"]


def test_false_positives_are_suppressed_but_disclosed():
    state = {
        "security_findings": [
            _finding(is_likely_false_positive=True),
            _finding(is_likely_false_positive=False),
        ],
        "quality_findings": [],
        "errors": [],
    }
    result = aggregator_node(state)
    assert len(result["all_findings"]) == 1
    assert "false positive" in result["report_markdown"].lower()


def test_clean_pr_reports_no_issues():
    state = {"security_findings": [], "quality_findings": [], "errors": []}
    result = aggregator_node(state)
    assert result["all_findings"] == []
    assert "No security or quality issues" in result["report_markdown"]


def test_errors_are_surfaced_in_report():
    state = {
        "security_findings": [],
        "quality_findings": [],
        "errors": ["semgrep failed: timeout"],
    }
    result = aggregator_node(state)
    assert "semgrep failed" in result["report_markdown"]
