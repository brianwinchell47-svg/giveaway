"""Text-message notifications through a VoIP / SMS provider.

Supported providers:
  twilio  - https://www.twilio.com  (REST API, account SID + auth token)
  voipms  - https://voip.ms         (REST API; enable API + whitelist your IP in the portal)
  telnyx  - https://telnyx.com      (REST API v2, API key)
"""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import Notify

log = logging.getLogger("giveaway_bot")

VOIPMS_MAX = 160          # voip.ms rejects SMS bodies longer than this
LONG_SMS_MAX = 1500       # Twilio/Telnyx concatenate long messages; keep under 1600


class NotifyError(RuntimeError):
    pass


def _digits(n: str) -> str:
    return re.sub(r"\D", "", n)


def _e164(n: str) -> str:
    d = _digits(n)
    if n.strip().startswith("+"):
        return "+" + d
    return "+1" + d if len(d) == 10 else "+" + d


def _nanp10(n: str) -> str:
    """voip.ms wants 10-digit North American numbers."""
    d = _digits(n)
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def _open(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise NotifyError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise NotifyError(f"network error: {e.reason}") from e
    try:
        return json.loads(body)
    except ValueError:
        return {"raw": body}


def _send_twilio(n: Notify, text: str) -> None:
    sid, token = n.secret("twilio_account_sid"), n.secret("twilio_auth_token")
    if not (sid and token):
        raise NotifyError("twilio needs twilio_account_sid and twilio_auth_token")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode(
        {"To": _e164(n.to), "From": _e164(n.from_number), "Body": text}
    ).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    _open(urllib.request.Request(url, data=data, headers={"Authorization": f"Basic {auth}"}))


def _send_voipms(n: Notify, text: str) -> None:
    user, pw = n.secret("voipms_username"), n.secret("voipms_api_password")
    if not (user and pw):
        raise NotifyError("voipms needs voipms_username and voipms_api_password")
    q = urllib.parse.urlencode({
        "api_username": user, "api_password": pw, "method": "sendSMS",
        "did": _nanp10(n.from_number), "dst": _nanp10(n.to), "message": text,
    })
    res = _open(urllib.request.Request(f"https://voip.ms/api/v1/rest.php?{q}"))
    if res.get("status") != "success":
        raise NotifyError(f"voip.ms error: {res.get('status') or res}")


def _send_telnyx(n: Notify, text: str) -> None:
    key = n.secret("telnyx_api_key")
    if not key:
        raise NotifyError("telnyx needs telnyx_api_key")
    body = json.dumps({"from": _e164(n.from_number), "to": _e164(n.to), "text": text}).encode()
    _open(urllib.request.Request(
        "https://api.telnyx.com/v2/messages", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    ))


SENDERS = {"twilio": _send_twilio, "voipms": _send_voipms, "telnyx": _send_telnyx}


def chunk(text: str, size: int) -> list[str]:
    """Split on line boundaries into pieces no longer than size."""
    out, cur = [], ""
    for line in text.splitlines():
        while len(line) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if cur and len(cur) + 1 + len(line) > size:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def send_sms(n: Notify, text: str) -> int:
    """Send text (split into several SMS if needed). Returns messages sent."""
    if not n.enabled:
        return 0
    if not (n.to and n.from_number):
        raise NotifyError("notify.to and notify.from must both be set")
    size = VOIPMS_MAX if n.provider == "voipms" else LONG_SMS_MAX
    parts = chunk(text, size)
    for p in parts:
        SENDERS[n.provider](n, p)
    return len(parts)


SHORT_REASON = [
    (re.compile(r"captcha", re.I), "CAPTCHA"),
    (re.compile(r"prohibit automated", re.I), "no bots allowed"),
    (re.compile(r"could not fill", re.I), "extra questions"),
    (re.compile(r"no entry form", re.I), "no form found"),
    (re.compile(r"no submit", re.I), "no submit button"),
    (re.compile(r"login|sign in", re.I), "login needed"),
]


def short_reason(detail: str) -> str:
    for rx, label in SHORT_REASON:
        if rx.search(detail):
            return label
    return detail[:40]


def format_summary(items: list[tuple[str, str, str, str]]) -> str:
    """items: (status, name, url, detail) -> SMS text."""
    manual = [i for i in items if i[0] == "needs_manual"]
    other = [i for i in items if i[0] != "needs_manual"]
    lines = []
    if manual:
        lines.append(f"Giveaway bot: {len(manual)} need manual entry")
        for _, name, url, detail in manual:
            lines.append(f"- {(name or '')[:40]} ({short_reason(detail)}) {url}".replace("-  (", "- ("))
    if other:
        lines.append(f"Giveaway bot: {len(other)} failed")
        for status, name, url, detail in other:
            lines.append(f"- {(name or '')[:40]} {url}")
    return "\n".join(lines)


def notify_run(n: Notify, results: list[tuple[str, str, str, str]]) -> None:
    """Send one batched text for this run's results whose status is in notify.on."""
    if not n.enabled:
        return
    wanted = [r for r in results if r[0] in n.on]
    if not wanted:
        return
    try:
        sent = send_sms(n, format_summary(wanted))
        log.info("sent %d text message(s) via %s", sent, n.provider)
    except NotifyError as e:
        log.warning("notification failed: %s", e)
