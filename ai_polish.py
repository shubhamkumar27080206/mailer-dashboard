"""Optional: rewrite the context box into one professional sentence with the Anthropic API.

Needs `pip install anthropic` and the ANTHROPIC_API_KEY environment variable.
If either is missing, available() is False and the UI hides the checkbox.
"""
from __future__ import annotations

import os


def available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def polish_context(text: str) -> str:
    """Return one polished sentence. Raises on API errors (the UI falls back to the original text)."""
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        max_tokens=200,
        system=(
            "Rewrite the user's note as ONE short, professional sentence for a job-application email, "
            "written in first person. Keep every fact (notice period, locations, skills) exactly as given; "
            "do not add new facts. Output only the sentence."
        ),
        messages=[{"role": "user", "content": text}],
    )
    out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    return out or text
