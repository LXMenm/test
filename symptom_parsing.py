from __future__ import annotations

import json
import re
from typing import Any

_SPLIT_PATTERN = re.compile(r"[,，、;；\n]+")


def dedupe_preserve_order(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def split_symptom_text(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    tokens = [item.strip() for item in _SPLIT_PATTERN.split(text)]
    return [item for item in tokens if item]


def parse_symptoms_input(raw: Any) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, list):
        tokens: list[str] = []
        for item in raw:
            tokens.extend(split_symptom_text(str(item)))
        return dedupe_preserve_order(tokens)

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            tokens: list[str] = []
            for item in parsed:
                tokens.extend(split_symptom_text(str(item)))
            return dedupe_preserve_order(tokens)
        return dedupe_preserve_order(split_symptom_text(text))

    return dedupe_preserve_order(split_symptom_text(str(raw)))
