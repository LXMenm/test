from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from state import CropDiseaseState


def append_trace(
    state: CropDiseaseState,
    agent: str,
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    decision: str | None = None,
) -> None:
    trace_events = state.get("trace_events")
    if trace_events is None:
        trace_events = []
        state["trace_events"] = trace_events
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "inputs": inputs,
        "outputs": outputs,
    }
    if decision:
        event["decision"] = decision
    trace_events.append(event)
