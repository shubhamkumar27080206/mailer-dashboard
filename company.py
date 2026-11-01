"""Company-name extraction from an email address, and greeting logic."""
from __future__ import annotations

import re

# Personal / free mail providers: no company can be derived from these.
GENERIC_CORES = {
    "gmail", "googlemail", "yahoo", "ymail", "outlook", "hotmail", "live", "msn",
    "rediffmail", "rediff", "icloud", "me", "proton", "protonmail", "aol", "gmx", "mail",
}
# Second-level suffixes such as .co.in, .com.au, .ac.uk
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac", "nic", "res", "ltd", "plc"}


def guess_company(email: str, overrides: dict | None = None) -> tuple[str, bool]:
    """Return (company_name, known). known=False for personal mail domains."""
    domain = email.rsplit("@", 1)[-1].lower().strip()
    parts = [p for p in domain.split(".") if p]
    if len(parts) < 2:
        return "", False
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in SECOND_LEVEL:
        core = parts[-3]
    else:
        core = parts[-2]
    if core in GENERIC_CORES:
        return "", False
    if overrides and core in overrides:
        return str(overrides[core]), True
    words = re.sub(r"[-_]+", " ", core).split()
    if not words:
        return "", False
    if len(words) == 1 and len(words[0]) <= 3:
        return words[0].upper(), True  # tcs -> TCS, ibm -> IBM
    return " ".join(w.capitalize() for w in words), True


def resolve_company(email: str, provided: str = "", overrides: dict | None = None) -> tuple[str, bool]:
    """A company given in the Excel wins; otherwise guess from the email domain."""
    provided = (provided or "").strip()
    if provided:
        return provided, True
    return guess_company(email, overrides)


def make_greeting(name: str, company: str, known: bool) -> str:
    name = (name or "").strip()
    if name:
        return f"Dear {name},"
    if known and company:
        return f"Dear Hiring Team at {company},"
    return "Dear Hiring Team,"
