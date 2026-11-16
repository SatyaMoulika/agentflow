"""Extract controlled connection bindings from strict configs or permissive saved drafts."""

from typing import Any
from uuid import UUID


def node_connection_ids(node_type: str, config: Any) -> tuple[str, ...]:
    if node_type not in {"http", "agent"}:
        return ()
    if not isinstance(config, dict):
        raise ValueError("Invalid connection binding")
    values = (
        [config.get("connection_id")] if node_type == "http" else config.get("connection_ids", [])
    )
    if not isinstance(values, list) or len(values) > 10:
        raise ValueError("Invalid connection bindings")
    if any(not isinstance(value, str) for value in values):
        raise ValueError("Invalid connection identity")
    return tuple(str(UUID(value)) for value in values)
