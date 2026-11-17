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
    """Only what's needed to check eligibility. Nothing here is sent anywhere."""
    state: str = ""          # two-letter code, e.g. "CA"
    state_name: str = ""     # full name, e.g. "California"
    country: str = "United States"
    country_code: str = "US"
    birthdate: str = ""      # YYYY-MM-DD; used only to compare against minimum ages

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
    end_date: str = ""       # YYYY-MM-DD; skipped after this date
    enabled: bool = True
    # Page is a blog post *about* the giveaway: follow its "enter here" link first.
    follow_link: bool = False


@dataclass
class Notify:
    provider: str = ""        # twilio | voipms | telnyx | "" (off)
    to: str = ""              # your phone, e.g. +15551234567
    from_number: str = ""     # your Twilio/Telnyx number, or voip.ms DID
    on: list[str] = field(default_factory=lambda: ["ready"])
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
    delay_between_checks_s: float = 3.0
    # How many newly discovered feed giveaways to check (and include in the text) per run.
    max_discovered_per_run: int = 10
    loop_interval_hours: float = 24.0


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


# Keys from older versions (when the bot filled in forms). Ignored if present.
_OLD_PROFILE_KEYS = {"first_name", "last_name", "email", "phone", "address1", "address2", "city", "zip"}
_OLD_SWEEP_KEYS = {"fields", "submit_selector", "success_text"}
_OLD_SETTINGS_KEYS = {"accept_rules", "accept_marketing", "auto_enter_discovered", "screenshots",
                      "delay_between_entries_s"}


def _drop(d: dict, keys: set) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


DEFAULT_PERSONAL_FILE = "personal.yaml"


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = _read_yaml(path)

    # Eligibility details + notification credentials live in a separate private file
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
    try:
        profile = Profile(**{k: str(v) for k, v in _drop(prof_raw, _OLD_PROFILE_KEYS).items()
                             if v is not None})
    except TypeError as e:
        raise ConfigError(f"bad profile field: {e}") from e
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
            sw = Sweepstake(**_drop(s, _OLD_SWEEP_KEYS))
        except TypeError as e:
            raise ConfigError(f"sweepstakes[{i}]: {e}") from e
        if sw.frequency not in VALID_FREQUENCIES:
            raise ConfigError(
                f"sweepstakes[{i}].frequency must be one of {sorted(VALID_FREQUENCIES)}"
            )
        sweeps.append(sw)

    try:
        settings = Settings(**_drop(raw.get("settings") or {}, _OLD_SETTINGS_KEYS))
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
    # Older versions used needs_manual for "go enter this yourself".
    notify.on = list(dict.fromkeys(
        "ready" if x == "needs_manual" else x for x in notify.on
        if x in ("ready", "failed", "skipped", "needs_manual")
    ))

    return Config(
        profile=profile,
        sweepstakes=sweeps,
        feeds=list(raw.get("feeds") or []),
        settings=settings,
        notify=notify,
    )
