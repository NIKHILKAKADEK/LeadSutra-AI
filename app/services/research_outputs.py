"""Persist readable text artifacts for completed research runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResearchOutputService:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def save(self, lead_id: str, research: dict[str, Any]) -> Path:
        if not lead_id or not isinstance(lead_id, str) or any(c in lead_id for c in "/\\..\0"):
            raise ValueError("Research output path is invalid.")
        path = (self.root / lead_id / "research.txt").resolve()
        if not path.is_relative_to(self.root) or path.parent == self.root:
            raise ValueError("Research output path is invalid.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(research, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
        return path
