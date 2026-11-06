"""Stable command fingerprints without retaining raw idempotency keys."""

import hashlib
import json
import re
from uuid import UUID

from app.modules.executions.schemas import RunCreateRequest


def key_digest(key: str) -> str:
    if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key) is None:
        raise ValueError("Invalid idempotency key")
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def request_digest(workflow_id: UUID, data: RunCreateRequest, parent_run_id: UUID | None) -> str:
    payload = {
        "workflow_id": str(workflow_id),
        "parent_run_id": str(parent_run_id) if parent_run_id else None,
        **data.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
