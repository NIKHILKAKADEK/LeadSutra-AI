from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_conversation_instructions(kind: str) -> dict[str, Any]:
    """Load instruction settings for an inbound or outbound voice agent."""
    if kind not in {"inbound", "outbound"}:
        raise ValueError(f"Unsupported voice agent kind: {kind}")
    path = Path(__file__).resolve().with_name("voice.txt")
    instructions = json.loads(path.read_text(encoding="utf-8"))
    return instructions[kind]
