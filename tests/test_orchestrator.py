from throughput.results import BenchmarkResult, ResultSet, MB
from throughput import orchestrator


def fake_probe(label, val):
    return ResultSet([BenchmarkResult("fake", "t", label, "op",
                                      int(val * MB), 1, 1.0)])


def test_run_plan_merges_results():
    reg = {
        "a": lambda: fake_probe("a", 5),
        "b": lambda: fake_probe("b", 10),
    }
    plan = [{"tool": "a"}, {"tool": "b"}]
    res = orchestrator.run_plan(plan, registry=reg)
    assert res.ok
    assert len(res.results) == 2
    assert {r.bucket for r in res.results} == {"a", "b"}


def test_run_plan_passes_args():
    reg = {"a": lambda val: fake_probe("a", val)}
    res = orchestrator.run_plan([{"tool": "a", "args": {"val": 42}}], registry=reg)
    assert res.results.results[0].mb_per_s == 42.0


def test_failing_probe_is_captured_not_fatal():
    def boom():
        raise RuntimeError("iperf3 not found")

    reg = {"a": lambda: fake_probe("a", 5), "boom": boom}
    res = orchestrator.run_plan([{"tool": "boom"}, {"tool": "a"}], registry=reg)
    assert res.ok is False
    assert len(res.results) == 1                 # 'a' still ran
    assert res.errors[0]["tool"] == "boom"
    assert "iperf3 not found" in res.errors[0]["error"]


def test_unknown_probe_recorded():
    res = orchestrator.run_plan([{"tool": "does-not-exist"}], registry={})
    assert res.errors[0]["error"] == "unknown probe"


def test_default_registry_has_core_probes():
    for name in ("iperf3", "latency", "mtu", "filesweep", "s3", "http"):
        assert name in orchestrator.PROBES
