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
