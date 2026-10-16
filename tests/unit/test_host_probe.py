"""The host probe reports what it read; what it cannot read is 'unknown', never a configured or guessed number."""
import json
from types import SimpleNamespace

from app.scheduler.host_probe import probe_local_host, write_probe

GIB = 1024 ** 3
ROCM = 'WARNING: low-power state\n\n' + json.dumps({"card0": {
    "VRAM Total Memory (B)": str(96 * GIB), "VRAM Total Used Memory (B)": str(48 * GIB)}})
LMS = json.dumps([{"identifier": "m1", "sizeBytes": 16 * GIB, "contextLength": 232192, "status": "idle"},
                  {"identifier": "m2", "sizeBytes": 4 * GIB, "contextLength": 8192, "status": "idle"}])


def fake_run(rocm=ROCM, lms=LMS, rocm_rc=0):
    def run(cmd, **kw):
        if cmd[0] == "rocm-smi":
            return SimpleNamespace(returncode=rocm_rc, stdout=rocm, stderr="boom")
        return SimpleNamespace(returncode=0, stdout=lms, stderr="")
    return run


def meminfo(tmp_path):
    p = tmp_path / "meminfo"
    p.write_text("MemTotal:       32486136 kB\nMemFree: 1 kB\nMemAvailable:    8245340 kB\nBuffers: 1 kB\n")
    return str(p)


def test_reads_gpu_ram_and_resident_models_and_reports_the_unexplained_gap(tmp_path):
    r = probe_local_host(run=fake_run(), meminfo_path=meminfo(tmp_path))
    assert r["status"] == "ok"
    assert (r["gpu_total_gb"], r["gpu_used_gb"], r["gpu_free_gb"]) == (96.0, 48.0, 48.0)
    assert r["system_ram_total_gb"] == 31.0 and r["system_ram_available_gb"] == 7.9
    assert [m["model"] for m in r["resident_models"]] == ["m1", "m2"]
    assert r["unexplained_gpu_gb"] == 28.0  # 48 used - (16 + 4) resident model files


def test_unreadable_gpu_is_unknown_with_reason_and_no_numbers(tmp_path):
    r = probe_local_host(run=fake_run(rocm_rc=1), meminfo_path=meminfo(tmp_path))
    assert r["status"] == "unknown" and "rocm-smi exited 1" in r["reason"]
    assert "gpu_free_gb" not in r


def test_write_probe_keeps_other_hosts(tmp_path):
    write_probe({"status": "ok"}, "a", tmp_path)
    path = write_probe({"status": "unknown"}, "b", tmp_path)
    assert set(json.loads(path.read_text())) == {"a", "b"}
