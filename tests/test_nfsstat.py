from throughput.tools import nfsstat

NFSSTAT_M = """\
/mnt/nas from nas01:/export/share
 Flags: rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,namlen=255,hard,\
proto=tcp,timeo=600,retrans=2,sec=sys,clientaddr=10.0.0.9

/mnt/other from nas02:/export/other
 Flags: rw,vers=3,rsize=32768,wsize=32768,proto=udp,timeo=7,retrans=3
"""

NFSSTAT_C = """\
Client rpc stats:
calls      retrans    authrefrsh
100000     250        100000
"""


def test_parse_nfs_mounts_extracts_server_export_and_options():
    mounts = nfsstat.parse_nfs_mounts(NFSSTAT_M)
    assert set(mounts) == {"/mnt/nas", "/mnt/other"}
    nas = mounts["/mnt/nas"]
    assert nas["server"] == "nas01"
    assert nas["export"] == "/export/share"
    opts = nas["options"]
    assert opts["vers"] == "4.2"
    assert opts["proto"] == "tcp"
    assert opts["rsize"] == 1048576       # coerced to int
    assert opts["wsize"] == 1048576
    assert opts["hard"] is True           # valueless flag
    assert mounts["/mnt/other"]["options"]["proto"] == "udp"


def test_parse_nfsstat_client_computes_retrans_pct():
    stats = nfsstat.parse_nfsstat_client(NFSSTAT_C)
    assert stats["calls"] == 100000
    assert stats["retrans"] == 250
    assert stats["retrans_pct"] == 0.25


def test_parse_nfsstat_client_handles_no_calls():
    stats = nfsstat.parse_nfsstat_client(
        "Client rpc stats:\ncalls      retrans    authrefrsh\n0          0          0\n")
    assert stats["retrans_pct"] == 0.0


def test_parse_empty_output_is_graceful():
    assert nfsstat.parse_nfs_mounts("") == {}
    assert nfsstat.parse_nfsstat_client("") == {}


def test_collect_context_none_when_nfsstat_missing(monkeypatch):
    # Simulate nfsstat not on PATH -> graceful None (degrade like SMB tool).
    import throughput.tools._proc as proc
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert nfsstat.collect_context("/mnt/nas") is None
    assert proc  # import used
