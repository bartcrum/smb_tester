from throughput.tools import mtu


def test_discover_payload_finds_boundary():
    # Path passes payloads up to 1472 (=> 1500 MTU).
    found = mtu.discover_payload(lambda s: s <= 1472, low=0, high=9000)
    assert found == 1472
    assert mtu.to_mtu(found) == 1500


def test_discover_payload_jumbo():
    found = mtu.discover_payload(lambda s: s <= 8972, low=0, high=9000)
    assert mtu.to_mtu(found) == 9000


def test_discover_payload_nothing_passes():
    assert mtu.discover_payload(lambda s: False, low=0, high=100) == 0


def test_build_ping_command_linux_vs_bsd():
    lin = mtu.build_ping_command("h", 1472, linux=True)
    assert "-M" in lin and lin[lin.index("-M") + 1] == "do"
    assert lin[lin.index("-s") + 1] == "1472"
    bsd = mtu.build_ping_command("h", 1472, linux=False)
    assert "-D" in bsd and "-M" not in bsd


def test_path_mtu_result_metadata(monkeypatch):
    # Drive path_mtu with a fake ping that "passes" up to 1472.
    monkeypatch.setattr(mtu, "require", lambda b: b)
    calls = {"n": 0}

    def fake_run(cmd, timeout=None):
        calls["n"] += 1
        size = int(cmd[cmd.index("-s") + 1])
        if size <= 1472:
            return "ok"
        raise RuntimeError("frag needed")

    monkeypatch.setattr(mtu, "run_capture", fake_run)
    rs = mtu.path_mtu("10.0.0.1")
    md = rs.results[0].metadata
    assert md["path_mtu"] == 1500
    assert md["standard_1500"] is True and md["jumbo"] is False
