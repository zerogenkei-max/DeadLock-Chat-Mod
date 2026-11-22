"""Validation for the local app. Mirrors normalize() in src/panorama/scripts/switchboard_shared.vts."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
SCHEMA = json.loads((ROOT / "themes/schema.json").read_text(encoding="utf-8"))
WORD_KEYS = ("objectiveWords", "calloutWords", "responseWords")
# Characters removed by JavaScript's String.prototype.trim().
JS_WHITESPACE = "\t\n\v\f\r                  　﻿"


def js_length(text: str) -> int:
    """Length in UTF-16 code units, as JavaScript counts it."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def normalize(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("A theme must be a settings object.")
    if "version" in value and (type(value["version"]) not in (int, float) or value["version"] != 1):
        raise ValueError("This theme uses an unsupported format version.")
    out = dict(SCHEMA["defaults"])
    for key, default in out.items():
        if key not in value or key == "version":
            continue
        v = value[key]
        if key in SCHEMA["numeric"]:
            try:
                finite = type(v) in (float, int) and math.isfinite(v)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{key} must be a number.")
            low, high = SCHEMA["numeric"][key]
            out[key] = math.floor(max(low, min(high, v)) + .5)
        elif key in SCHEMA["enums"]:
            if not isinstance(v, str) or v not in SCHEMA["enums"][key]:
                raise ValueError(f"Unrecognised {key}.")
            out[key] = v
        elif type(default) is bool:
            if type(v) is not bool:
                raise ValueError(f"{key} must be true or false.")
            out[key] = v
        elif key in WORD_KEYS:
            if not isinstance(v, str) or js_length(v) > 400 or re.search(r"[<>\r\n]", v):
                raise ValueError("Matching words must be a short comma-separated list.")
            out[key] = v.strip(JS_WHITESPACE)
        else:
            if not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                raise ValueError(f"{key} must be a six-digit hex colour.")
            out[key] = v.lower()
    return out
