"""Dead-letter records (contracts/bigquery/ops/dead_letter.json)."""

import json
from datetime import datetime, timezone

DEAD_LETTER = "dead_letter"  # Beam output tag


class RejectedRecord(Exception):
    """Raised by adapters and validators; carries a machine-readable error code."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def make_dead_letter(source: str, stage: str, code: str, detail: str, raw, event_id: str | None = None) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    elif not isinstance(raw, str):
        raw = json.dumps(raw, default=str)
    return {
        "source": source,
        "stage": stage,
        "error_code": code,
        "error_detail": detail,
        "event_id": event_id,
        "raw_payload": raw,
        "failed_ts": datetime.now(timezone.utc).isoformat(),
    }
