from __future__ import annotations

from evals.workloads import WORKLOAD_NAMES, run_workload_corpus


def test_deterministic_workload_corpus_reports_all_five_workloads():
    report = run_workload_corpus(iterations=2)

    assert report["schema_version"] == 1
    assert report["iterations"] == 2
    assert tuple(report["workloads"]) == WORKLOAD_NAMES
    for name in WORKLOAD_NAMES:
        workload = report["workloads"][name]
        assert len(workload["samples_ms"]) == 2
        assert workload["p95_ms"] >= workload["p50_ms"]
        assert workload["metrics"]
