# app/services/report_store.py
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def report_json_path(reports_dir: Path, report_id: str) -> Path:
    return reports_dir / f"{report_id}.json"

def report_pdf_path(reports_dir: Path, report_id: str) -> Path:
    return reports_dir / f"{report_id}.pdf"

def write_report_meta(reports_dir: Path, report_id: str, meta: Dict[str, Any]) -> None:
    p = report_json_path(reports_dir, report_id)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

def read_report_meta(reports_dir: Path, report_id: str) -> Optional[Dict[str, Any]]:
    p = report_json_path(reports_dir, report_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

def update_report_meta(reports_dir: Path, report_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    meta = read_report_meta(reports_dir, report_id) or {}
    meta.update(patch)
    write_report_meta(reports_dir, report_id, meta)
    return meta