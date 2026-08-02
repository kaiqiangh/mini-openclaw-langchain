"""Meta-test: the eval harness cases must all pass against current code."""
from pathlib import Path
from evals.runner import run_evals, EVALS_DIR


def test_all_safety_evals_pass():
    """All tool safety eval cases must pass."""
    report = run_evals(EVALS_DIR)
    assert report.failed == 0, (
        f"{report.failed}/{report.total} safety evals failed: "
        + ", ".join(r.name for r in report.results if not r.passed)
    )


def test_safety_score_above_threshold():
    """The fixed safety corpus is a complete hard gate."""
    report = run_evals(EVALS_DIR)
    assert report.total == 52, f"Safety corpus changed: expected 52, got {report.total}"
    assert report.safety_score == 1.0, (
        f"Safety score {report.safety_score:.2%} is not a complete pass"
    )
