"""Load and validate the YAML configuration."""
from __future__ import annotations

import os
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
    # Page is a blog post *about* the giveaway: follow its "enter here" link first.
    follow_link: bool = False


@dataclass
class Notify:
    provider: str = ""        # twilio | voipms | telnyx | "" (off)
    to: str = ""              # your phone, e.g. +15551234567
    from_number: str = ""     # your Twilio/Telnyx number, or voip.ms DID
    on: list[str] = field(default_factory=lambda: ["needs_manual"])
    # Credentials. Each can instead come from the env var named in brackets.
    twilio_account_sid: str = ""   # [TWILIO_ACCOUNT_SID]
    twilio_auth_token: str = ""    # [TWILIO_AUTH_TOKEN]
    voipms_username: str = ""      # [VOIPMS_USERNAME]  (your voip.ms login email)
    voipms_api_password: str = ""  # [VOIPMS_API_PASSWORD]
    telnyx_api_key: str = ""       # [TELNYX_API_KEY]

    ENV = {
        "twilio_account_sid": "TWILIO_ACCOUNT_SID",
        "twilio_auth_token": "TWILIO_AUTH_TOKEN",
        "voipms_username": "VOIPMS_USERNAME",
        "voipms_api_password": "VOIPMS_API_PASSWORD",
        "telnyx_api_key": "TELNYX_API_KEY",
    }

    def secret(self, name: str) -> str:
        return getattr(self, name) or os.environ.get(self.ENV[name], "")

    @property
    def enabled(self) -> bool:
        return bool(self.provider)


VALID_PROVIDERS = {"", "twilio", "voipms", "telnyx"}


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
    notify: Notify = field(default_factory=Notify)

    @property
    def data_path(self) -> Path:
        p = Path(self.settings.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


class ConfigError(ValueError):
    pass


DEFAULT_PERSONAL_FILE = "personal.yaml"


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = _read_yaml(path)

    # Personal details + notification credentials live in a separate private file
    # (default personal.yaml next to config.yaml; created by `giveaway_bot setup`).
    personal_path = Path(raw.get("personal_file") or DEFAULT_PERSONAL_FILE)
    if not personal_path.is_absolute():
        personal_path = path.parent / personal_path
    personal = _read_yaml(personal_path) if personal_path.exists() else {}
    if personal_path.exists() and personal_path.stat().st_mode & 0o077:
        try:
            personal_path.chmod(0o600)
        except OSError:
            pass

    prof_raw = {**(raw.get("profile") or {}), **(personal.get("profile") or {})}
    if not prof_raw:
        raise ConfigError(
            f"no profile found; run `python -m giveaway_bot setup` to create {personal_path.name}"
        )
    try:
        profile = Profile(**{k: str(v) for k, v in prof_raw.items() if v is not None})
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

    notify_raw = {}
    for src in (raw.get("notify") or {}, personal.get("notify") or {}):
        for k, v in src.items():
            # YAML 1.1 parses a bare `on:` key as boolean True.
            notify_raw["on" if k is True else k] = v
    if "from" in notify_raw:
        notify_raw["from_number"] = notify_raw.pop("from")
    try:
        notify = Notify(**{k: (str(v) if k != "on" else v) for k, v in notify_raw.items()})
    except TypeError as e:
        raise ConfigError(f"bad notify field: {e}") from e
    if notify.provider not in VALID_PROVIDERS:
        raise ConfigError("notify.provider must be one of twilio, voipms, telnyx")
    if isinstance(notify.on, str):
        notify.on = [notify.on]

    return Config(
        profile=profile,
        sweepstakes=sweeps,
        feeds=list(raw.get("feeds") or []),
        settings=settings,
        notify=notify,
    )
