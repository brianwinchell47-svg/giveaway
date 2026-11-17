"""Load and validate the YAML configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

VALID_FREQUENCIES = {"once", "daily", "weekly"}


@dataclass
class Profile:
    first_name: str
    last_name: str
    email: str
    phone: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""          # two-letter code, e.g. "CA"
    state_name: str = ""     # full name, e.g. "California"
    zip: str = ""
    country: str = "United States"
    country_code: str = "US"
    birthdate: str = ""      # YYYY-MM-DD

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def birth(self) -> date | None:
        return date.fromisoformat(self.birthdate) if self.birthdate else None

    @property
    def age(self) -> int | None:
        b = self.birth
        if not b:
            return None
        t = date.today()
        return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


@dataclass
class Sweepstake:
    url: str
    name: str = ""
    frequency: str = "once"
    # Extra explicit field values: CSS selector -> value. Overrides heuristics.
    fields: dict[str, str] = field(default_factory=dict)
    submit_selector: str = ""
    success_text: list[str] = field(default_factory=list)
    end_date: str = ""       # YYYY-MM-DD; skipped after this date
    enabled: bool = True


@dataclass
class Settings:
    headless: bool = True
    data_dir: str = "data"
    page_timeout_ms: int = 30000
    delay_between_entries_s: float = 20.0
    # Agree to official rules / terms checkboxes (required to enter).
    accept_rules: bool = True
    # Opt in to marketing / newsletter checkboxes. Off by default.
    accept_marketing: bool = False
    # Auto-enter giveaways found via feeds (not just list them).
    auto_enter_discovered: bool = False
    max_discovered_per_run: int = 10
    loop_interval_hours: float = 24.0
    screenshots: bool = True


@dataclass
class Config:
    profile: Profile
    sweepstakes: list[Sweepstake]
    feeds: list[str]
    settings: Settings

    @property
    def data_path(self) -> Path:
        p = Path(self.settings.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if "profile" not in raw:
        raise ConfigError("config is missing a 'profile' section")
    try:
        profile = Profile(**{k: str(v) for k, v in raw["profile"].items()})
    except TypeError as e:
        raise ConfigError(f"bad profile field: {e}") from e
    for req in ("first_name", "last_name", "email"):
        if not getattr(profile, req):
            raise ConfigError(f"profile.{req} is required")
    if profile.birthdate:
        try:
            profile.birth
        except ValueError as e:
            raise ConfigError("profile.birthdate must be YYYY-MM-DD") from e

    sweeps = []
    for i, s in enumerate(raw.get("sweepstakes") or []):
        if isinstance(s, str):
            s = {"url": s}
        try:
            sw = Sweepstake(**s)
        except TypeError as e:
            raise ConfigError(f"sweepstakes[{i}]: {e}") from e
        if sw.frequency not in VALID_FREQUENCIES:
            raise ConfigError(
                f"sweepstakes[{i}].frequency must be one of {sorted(VALID_FREQUENCIES)}"
            )
        if isinstance(sw.success_text, str):
            sw.success_text = [sw.success_text]
        sweeps.append(sw)

    try:
        settings = Settings(**(raw.get("settings") or {}))
    except TypeError as e:
        raise ConfigError(f"bad settings field: {e}") from e

    return Config(
        profile=profile,
        sweepstakes=sweeps,
        feeds=list(raw.get("feeds") or []),
        settings=settings,
    )
