"""
Shared utilities for AI response parsing across analysis modules.
"""

from __future__ import annotations

import json


def extract_json_object(raw: str) -> dict:
    """
    Robustly extract the first complete JSON object from an AI response string.

    Handles all common failure modes that arise with verbose AI responses:
    - Extra prose before the JSON (e.g., "Here is my analysis:\\n{...}")
    - Extra prose after the JSON (e.g., "{...}\\nNote: consider {country} risk")
    - Markdown code fences (```json ... ```)
    - Curly braces inside JSON string values (e.g., "returns {5-8}% annually")
    - Nested JSON objects or arrays

    The approach is a one-pass balanced-brace walk that respects string context,
    so it correctly ignores `{` and `}` inside quoted strings.

    Args:
        raw: Raw string returned by the AI provider.

    Returns:
        Parsed dict from the first complete JSON object found.

    Raises:
        ValueError: If no complete JSON object can be extracted.
        json.JSONDecodeError: If the extracted candidate is structurally invalid JSON.
    """
    text = raw.strip()

    # Strip markdown code fences if present (e.g. ```json ... ```)
    if text.startswith("```"):
        text = "\n".join(line for line in text.split("\n") if not line.startswith("```")).strip()

    # Happy path: the whole response IS the JSON object
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Balanced-brace walk: try each `{` position as a potential JSON start.
    # We iterate rather than assuming the first `{` is the JSON opening brace,
    # because prose before the JSON may also contain `{...}` fragments.
    pos = 0
    last_exc: Exception = ValueError("No JSON object found in AI response")

    while True:
        start = text.find("{", pos)
        if start == -1:
            raise last_exc

        depth = 0
        in_string = False
        escape_next = False

        for i in range(start, len(text)):
            c = text[i]

            # Handle escape sequences inside strings (e.g. \", \\)
            if escape_next:
                escape_next = False
                continue
            if c == "\\" and in_string:
                escape_next = True
                continue

            # Toggle string mode on unescaped double-quotes
            if c == '"':
                in_string = not in_string
                continue

            # Characters inside a string are inert for brace counting
            if in_string:
                continue

            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError as exc:
                        # This `{...}` block was not valid JSON; try the next `{`
                        last_exc = exc
                        pos = start + 1
                        break
        else:
            # Inner for-loop exhausted without finding a matching `}` — no more candidates
            raise ValueError("AI response contains an incomplete JSON object (unmatched braces)")
