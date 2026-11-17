"""Text checks run against a giveaway page and its official rules.

The bot skips a giveaway (and flags it for you) whenever these say an
automated entry would be invalid. Entering anyway gets you disqualified.
"""
from __future__ import annotations

import re

_AUTO = r"(?:automat\w*|robotic|bots?\b|script\w*|macros?\b|third[- ]party (?:entry )?services?)"
_BAD = r"(?:prohibit\w*|not (?:be )?(?:permitted|allowed|accepted|eligible|valid)|void|disqualif\w*|invalid|forbidden)"

AUTOMATION_BANNED = [
    re.compile(rf"{_AUTO}[^.]{{0,120}}(?:entr|particip|submi)[^.]{{0,120}}{_BAD}", re.I),
    re.compile(rf"(?:entr|particip|submi)\w*[^.]{{0,120}}{_AUTO}[^.]{{0,120}}{_BAD}", re.I),
    re.compile(rf"{_BAD}[^.]{{0,40}}(?:use of )?(?:any )?{_AUTO}", re.I),
]

ENDED = re.compile(
    r"(?:this|the) (?:sweepstakes|giveaway|contest|promotion) (?:has|is) "
    r"(?:now )?(?:ended|closed|over|expired)|no longer accepting entries|entry period has ended",
    re.I,
)

ALREADY_ENTERED = re.compile(
    r"already entered|you(?:'ve| have) already (?:been )?(?:entered|submitted)|"
    r"come back tomorrow|one entry per (?:person|day)[^.]{0,40}(?:already|reached)",
    re.I,
)

SUCCESS = re.compile(
    r"thank(?:s| you)[^.]{0,40}(?:entr|enter|particip|submi)|you(?:'re| are| have been)? "
    r"(?:now |successfully )?entered|entry (?:has been )?(?:received|submitted|confirmed|recorded)|"
    r"good luck|successfully (?:entered|submitted)|you're in\b",
    re.I,
)

MIN_AGE = re.compile(r"\b(1[3-9]|2[01])\s*(?:\+|years? (?:of age )?or older|years of age)", re.I)


def automation_banned(text: str) -> str | None:
    for rx in AUTOMATION_BANNED:
        m = rx.search(text)
        if m:
            return m.group(0)[:200]
    return None


def has_ended(text: str) -> bool:
    return bool(ENDED.search(text))


def already_entered(text: str) -> bool:
    return bool(ALREADY_ENTERED.search(text))


def looks_successful(text: str, extra: list[str] | None = None) -> bool:
    low = text.lower()
    if extra and any(s.lower() in low for s in extra):
        return True
    return bool(SUCCESS.search(text))


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
