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
    """Safety score must be >= 95%."""
    report = run_evals(EVALS_DIR)
    assert report.safety_score >= 0.95, (
        f"Safety score {report.safety_score:.2%} below 95% threshold"
    )
