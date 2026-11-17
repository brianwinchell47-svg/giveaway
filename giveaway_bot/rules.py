"""Text checks run against a giveaway page and its Official Rules:
has it ended, and are you eligible (age, residency)?"""
from __future__ import annotations

import re

ENDED = re.compile(
    r"(?:this|the) (?:sweepstakes|giveaway|contest|promotion) (?:has|is) "
    r"(?:now )?(?:ended|closed|over|expired)|no longer accepting entries|entry period has ended",
    re.I,
)

MIN_AGE = re.compile(r"\b(1[3-9]|2[01])\s*(?:\+|years? (?:of age )?or older|years of age)", re.I)


def has_ended(text: str) -> bool:
    return bool(ENDED.search(text))


def minimum_age(text: str) -> int | None:
    ages = [int(m.group(1)) for m in MIN_AGE.finditer(text)]
    return max(ages) if ages else None


RESIDENTS = re.compile(
    r"(?:open|available)\s+(?:only\s+)?to\s+(?:legal\s+|permanent\s+)*residents\s+of\s+((?:[^.;]|\.(?=\S)){3,200})",
    re.I,
)
EXCLUDING = re.compile(r"(?:excluding|except(?: for)?|void in|not open to residents of)\s+((?:[^.;]|\.(?=\S)){2,200})", re.I)
US_ALIASES = ("united states", "u.s.", "usa", "the us ", "50 states", "contiguous", "continental u")


def residency_excluded(text: str, profile) -> str | None:
    """Return a reason if the rules clearly exclude where the profile lives."""
    country = (profile.country or "").lower()
    code = (profile.country_code or "").lower()
    state = (profile.state_name or "").lower()
    st = (profile.state or "").upper()
    is_us = code == "us" or country in ("united states", "usa", "united states of america")

    def mentions_me(phrase: str) -> bool:
        p = " " + phrase.lower() + " "
        if "worldwide" in p or "all countries" in p:
            return True
        if country and country in p:
            return True
        if code and re.search(rf"\b{re.escape(code)}\b", p) and code != "us":
            return True
        if is_us and (any(a in p for a in US_ALIASES) or re.search(r"\bu\.?s\.?\b", p)):
            return True
        if state and state in p:
            return True
        return False

    m = RESIDENTS.search(text)
    if m and not mentions_me(m.group(1)):
        return f"open to residents of {m.group(1).strip()[:80]}"
    for m in EXCLUDING.finditer(text):
        phrase = m.group(1).lower()
        if (state and state in phrase) or (st and re.search(rf"\b{re.escape(st)}\b", m.group(1))):
            return f"excludes {m.group(1).strip()[:80]}"
    return None
