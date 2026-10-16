"""Read-only measurement of what a host has free for inference.

Linux only for now: rocm-smi (GPU-addressable memory), /proc/meminfo (system RAM) and `lms ps --json`
(resident models). Needs no credential. A reading that cannot be taken is reported as unknown with the
reason -- never replaced by a configured or guessed number; the caller refuses cold loads on an unknown host.
The model sizes are reported next to the GPU number so a gap between them (context caches, other
programs) is visible instead of silently trusted.
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

GIB = 1024 ** 3


def _run_json(cmd: list, run: Callable) -> Any:
    proc = run(cmd, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {proc.returncode}: {proc.stderr.strip()[:200]}")
    out = proc.stdout  # rocm-smi prints a warning line before the JSON
    starts = [k for k in (out.find("{"), out.find("[")) if k >= 0]
    if not starts:
        raise RuntimeError(f"{cmd[0]} printed no JSON")
    return json.loads(out[min(starts):])


def probe_local_host(lms_command: str = "lms", run: Callable = subprocess.run,
                     meminfo_path: str = "/proc/meminfo", now: Optional[datetime] = None) -> Dict[str, Any]:
    """One reading. 'status' is 'ok' only when GPU, system RAM and resident models were all read."""
    result: Dict[str, Any] = {"measured_at": (now or datetime.now()).isoformat(timespec="seconds"), "status": "ok"}
    try:
        card = next(iter(_run_json(["rocm-smi", "--showmeminfo", "vram", "--json"], run).values()))
        total, used = int(card["VRAM Total Memory (B)"]), int(card["VRAM Total Used Memory (B)"])
        result.update(gpu_total_gb=round(total / GIB, 1), gpu_used_gb=round(used / GIB, 1),
                      gpu_free_gb=round((total - used) / GIB, 1))
        info = {l.split(":")[0]: int(l.split()[1]) for l in Path(meminfo_path).read_text().splitlines() if l[:3] == "Mem"}
        result.update(system_ram_total_gb=round(info["MemTotal"] / 1024 ** 2, 1),
                      system_ram_available_gb=round(info["MemAvailable"] / 1024 ** 2, 1))
        models = [{"model": e["identifier"], "size_gb": round(e["sizeBytes"] / GIB, 1),
                   "context": e.get("contextLength"), "status": e.get("status")}
                  for e in _run_json([lms_command, "ps", "--json"], run)]
        result["resident_models"] = models
        result["unexplained_gpu_gb"] = round(result["gpu_used_gb"] - sum(m["size_gb"] for m in models), 1)
    except Exception as e:
        result["status"] = "unknown"
        result["reason"] = f"{type(e).__name__}: {e}"
    return result


def write_probe(reading: Dict[str, Any], host_id: str, state_dir: Path) -> Path:
    path = Path(state_dir) / "host_probe.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    state[host_id] = reading
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
    return path
