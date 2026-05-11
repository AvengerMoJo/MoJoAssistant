#!/usr/bin/env python3
"""
Read-only storage parity checker for conversation linkage integrity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Bootstrap submodule src path for direct script execution.
REPO_ROOT = Path(__file__).resolve().parents[1]
SUBMODULE_SRC = REPO_ROOT / "submodules" / "dreaming-memory-pipeline" / "src"
if str(SUBMODULE_SRC) not in sys.path:
    sys.path.insert(0, str(SUBMODULE_SRC))

from mojo_memory.storage import create_storage_backend


def _load_conversations(backend: Any) -> List[Dict[str, Any]]:
    data = backend.read_json("conversations_multi_model.json")
    if isinstance(data, list):
        return data
    return []


def _index(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_conv: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        cid = r.get("conversation_id", "default")
        by_conv.setdefault(cid, []).append(r)
    for cid in by_conv:
        by_conv[cid].sort(key=lambda x: int(x.get("turn_index", 0)))
    return by_conv


def _hash_record(r: Dict[str, Any]) -> str:
    payload = {
        "conversation_id": r.get("conversation_id"),
        "turn_index": r.get("turn_index"),
        "role": r.get("role", r.get("message_type")),
        "content": r.get("content", r.get("text_content")),
        "pair_id": r.get("pair_id"),
        "status": r.get("status", "complete"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _check_orphans(records: List[Dict[str, Any]]) -> List[str]:
    issues: List[str] = []
    seen = set()
    for r in records:
        mid = r.get("message_id")
        if mid:
            seen.add(mid)
    for r in records:
        role = r.get("role", r.get("message_type"))
        if role == "assistant":
            parent = r.get("parent_message_id")
            if parent and parent not in seen:
                issues.append(f"assistant message {r.get('message_id')} parent missing: {parent}")
    return issues


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--primary-name", required=True)
    p.add_argument("--primary-config", default="{}")
    p.add_argument("--mirror-name", required=True)
    p.add_argument("--mirror-config", default="{}")
    p.add_argument("--report-dir", default=str(Path.home() / ".memory" / "reports" / "storage_parity"))
    args = p.parse_args()

    primary = create_storage_backend(args.primary_name, **json.loads(args.primary_config))
    mirror = create_storage_backend(args.mirror_name, **json.loads(args.mirror_config))

    p_records = _load_conversations(primary)
    m_records = _load_conversations(mirror)
    p_by = _index(p_records)
    m_by = _index(m_records)

    issues: List[str] = []
    if set(p_by.keys()) != set(m_by.keys()):
        issues.append("conversation_id sets differ")
    for cid in sorted(set(p_by.keys()) | set(m_by.keys())):
        a = p_by.get(cid, [])
        b = m_by.get(cid, [])
        if len(a) != len(b):
            issues.append(f"{cid}: turn count differs primary={len(a)} mirror={len(b)}")
            continue
        for i, (ra, rb) in enumerate(zip(a, b)):
            if int(ra.get("turn_index", -1)) != int(rb.get("turn_index", -1)):
                issues.append(f"{cid}: turn_index mismatch at pos {i}")
            if _hash_record(ra) != _hash_record(rb):
                issues.append(f"{cid}: content hash mismatch at turn {ra.get('turn_index')}")

    issues.extend(_check_orphans(p_records))
    issues.extend(_check_orphans(m_records))

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "primary": args.primary_name,
        "mirror": args.mirror_name,
        "primary_records": len(p_records),
        "mirror_records": len(m_records),
        "issue_count": len(issues),
        "issues": issues[:200],
        "status": "ok" if not issues else "error",
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / f"parity_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(str(out))
    print(f"status={report['status']} issues={report['issue_count']}")
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
