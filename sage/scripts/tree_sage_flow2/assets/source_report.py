"""Asset source reporting for TreeSAGE Flow 2.

This module keeps asset provenance accounting outside the large flow runner.
It is intentionally read-only: it inspects per-object metadata emitted by the
asset generation stage and summarizes which route produced each mesh.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tree_sage_flow2.io import extract_json


def _asset_source_bucket(meta: dict[str, Any]) -> str:
    source = str(meta.get("source") or "").strip().lower()
    route = str(meta.get("route") or "").strip().lower()
    if route == "parametric" or "parametric" in source:
        return "parametric"
    if route == "articraft" or "articraft" in source:
        return "articraft"
    if "procedural" in source or "fallback" in source:
        return "procedural_fallback"
    if "trellis" in source or "bridge_metadata" in meta or meta.get("job_id"):
        return "trellis2"
    if source:
        return "other"
    return "unknown"


def build_asset_source_report(plan: dict[str, Any], asset_dir: Path | None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "tree_sage_asset_source_report_v1",
        "enabled": bool(asset_dir),
        "asset_dir": str(asset_dir) if asset_dir else None,
        "objects": [],
        "counts": {},
        "non_trellis_ids": [],
        "ok": True,
    }
    if not asset_dir:
        report["reason"] = "assets_not_prepared"
        return report
    for obj in plan.get("objects", []):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        object_id = str(obj["id"])
        meta_path = asset_dir / f"{object_id}.json"
        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = extract_json(meta_path.read_text(encoding="utf-8"))
            except Exception as exc:
                meta = {"source": "unreadable_metadata", "error": str(exc)}
                report["ok"] = False
        else:
            meta = {"source": "missing_metadata"}
            report["ok"] = False
        bucket = _asset_source_bucket(meta if isinstance(meta, dict) else {})
        report["counts"][bucket] = int(report["counts"].get(bucket, 0)) + 1
        if bucket != "trellis2":
            report["non_trellis_ids"].append(object_id)
        report["objects"].append(
            {
                "id": object_id,
                "category": obj.get("category", ""),
                "bucket": bucket,
                "source": meta.get("source") if isinstance(meta, dict) else None,
                "route": meta.get("route") if isinstance(meta, dict) else None,
                "metadata": str(meta_path),
            }
        )
    return report
