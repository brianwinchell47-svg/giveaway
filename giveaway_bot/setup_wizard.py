"""Interactive `setup`: writes eligibility details and SMS credentials to personal.yaml."""
from __future__ import annotations

import getpass
import os
import shutil
from datetime import date
from pathlib import Path

import yaml

# Only what's needed to skip giveaways you can't win (age / residency limits).
PROFILE_FIELDS = [
    ("state", "State, 2-letter code (e.g. IL)", False),
    ("state_name", "State, full name (e.g. Illinois)", False),
    ("country", "Country", False),
    ("country_code", "Country code (e.g. US)", False),
    ("birthdate", "Birth date YYYY-MM-DD (for age limits; optional)", False),
]

PROVIDER_SECRETS = {
    "twilio": [("twilio_account_sid", "Twilio Account SID", False),
               ("twilio_auth_token", "Twilio Auth Token", True)],
    "voipms": [("voipms_username", "voip.ms login email (API username)", False),
               ("voipms_api_password", "voip.ms API password (not your login password)", True)],
    "telnyx": [("telnyx_api_key", "Telnyx API key", True)],
}


def _ask(label: str, default: str = "", required: bool = False, secret: bool = False) -> str:
    while True:
        shown = ("****" if secret and default else default)
        prompt = f"{label}" + (f" [{shown}]" if shown else "") + ": "
        val = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        val = val or default
        if val or not required:
            return val
        print("  required")


def _valid_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def run_setup(config_path: str) -> int:
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        example = Path(__file__).resolve().parent.parent / "config.example.yaml"
        if example.exists():
            shutil.copy(example, cfg_path)
            print(f"created {cfg_path} from config.example.yaml")

    raw = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    personal_path = Path((raw or {}).get("personal_file") or "personal.yaml")
    if not personal_path.is_absolute():
        personal_path = cfg_path.parent / personal_path
    existing = yaml.safe_load(personal_path.read_text()) if personal_path.exists() else {}
    existing = existing or {}
    from .config import _OLD_PROFILE_KEYS
    # Drop details older versions collected for form filling; they're no longer used.
    prof = {k: v for k, v in (existing.get("profile") or {}).items() if k not in _OLD_PROFILE_KEYS}
    notify = dict(existing.get("notify") or {})

    print(f"\nEligibility details (saved only to {personal_path}, never committed). "
          "Enter keeps [current].\n")
    prof.setdefault("country", "United States")
    prof.setdefault("country_code", "US")
    for key, label, req in PROFILE_FIELDS:
        while True:
            v = _ask(label, str(prof.get(key, "") or ""), req)
            if key == "birthdate" and v and not _valid_date(v):
                print("  use YYYY-MM-DD")
                continue
            break
        prof[key] = v

    print("\nText-message alerts with links to giveaways you can enter")
    provider = _ask("Provider: twilio, voipms, telnyx, or none", notify.get("provider", "none")).lower()
    if provider in PROVIDER_SECRETS:
        notify["provider"] = provider
        notify["to"] = _ask("Your mobile number (gets the texts)", notify.get("to", ""), True)
        label = "voip.ms DID (your voip.ms number that sends)" if provider == "voipms" \
            else f"Your {provider} phone number that sends"
        notify["from"] = _ask(label, notify.get("from", ""), True)
        for key, lab, secret in PROVIDER_SECRETS[provider]:
            notify[key] = _ask(lab, notify.get(key, ""), True, secret)
        notify["on"] = [x for x in notify.get("on", []) if x in ("ready", "failed", "skipped")] or ["ready"]
    else:
        notify = {}

    out = {"profile": prof}
    if notify:
        out["notify"] = notify
    # Create the file owner-readable only before writing secrets into it.
    fd = os.open(personal_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("# Private: your details and SMS credentials. Do not commit or share.\n")
        yaml.safe_dump(out, f, sort_keys=False)
    os.chmod(personal_path, 0o600)
    print(f"\nsaved {personal_path}")
    if notify:
        print("send a test text with:  python -m giveaway_bot notify-test")
    return 0
