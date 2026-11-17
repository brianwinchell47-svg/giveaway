import json
import os
import urllib.parse

import pytest
import yaml

from giveaway_bot import notify, rules
from giveaway_bot.config import ConfigError, Notify, Profile, Sweepstake, load_config
from giveaway_bot.runner import enter_one



# ---------- personal.yaml ----------

def test_personal_file_merged_and_locked_down(tmp_path):
    (tmp_path / "config.yaml").write_text("sweepstakes: []\nnotify: {on: [needs_manual, failed]}\n")
    personal = tmp_path / "personal.yaml"
    personal.write_text(yaml.safe_dump({
        "profile": {"first_name": "Jane", "last_name": "Doe", "email": "j@x.com", "zip": 62701},
        "notify": {"provider": "twilio", "to": "5551234567", "from": "+15550000000",
                   "twilio_account_sid": "AC1", "twilio_auth_token": "tok"},
    }))
    os.chmod(personal, 0o644)
    c = load_config(tmp_path / "config.yaml")
    assert c.profile.first_name == "Jane" and c.profile.zip == "62701"
    assert c.notify.provider == "twilio" and c.notify.from_number == "+15550000000"
    assert c.notify.on == ["needs_manual", "failed"]
    assert os.stat(personal).st_mode & 0o077 == 0


def test_missing_profile_points_to_setup(tmp_path):
    (tmp_path / "config.yaml").write_text("sweepstakes: []\n")
    with pytest.raises(ConfigError, match="setup"):
        load_config(tmp_path / "config.yaml")


def test_env_var_secret(monkeypatch):
    monkeypatch.setenv("TELNYX_API_KEY", "envkey")
    assert Notify(provider="telnyx").secret("telnyx_api_key") == "envkey"


# ---------- SMS providers (HTTP calls captured, nothing sent) ----------

@pytest.fixture
def captured(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        body = b'{"status":"success"}' if "voip.ms" in req.full_url else b'{"sid":"SM1"}'
        return Resp(body)

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_twilio_request(captured):
    n = Notify(provider="twilio", to="555-123-4567", from_number="+15550000000",
               twilio_account_sid="AC1", twilio_auth_token="tok")
    assert notify.send_sms(n, "hi") == 1
    req = captured[0]
    assert req.full_url == "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json"
    form = urllib.parse.parse_qs(req.data.decode())
    assert form == {"To": ["+15551234567"], "From": ["+15550000000"], "Body": ["hi"]}
    assert req.get_header("Authorization").startswith("Basic ")


def test_voipms_request_and_160_char_split(captured):
    n = Notify(provider="voipms", to="+1 (555) 123-4567", from_number="5550000000",
               voipms_username="me@x.com", voipms_api_password="pw")
    text = "\n".join(f"- giveaway number {i} https://example.com/sweeps/{i}" for i in range(8))
    sent = notify.send_sms(n, text)
    assert sent == len(captured) > 1
    for req in captured:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        assert q["method"] == ["sendSMS"] and q["did"] == ["5550000000"] and q["dst"] == ["5551234567"]
        assert len(q["message"][0]) <= 160


def test_telnyx_request(captured):
    n = Notify(provider="telnyx", to="5551234567", from_number="5550000000", telnyx_api_key="K")
    notify.send_sms(n, "hi")
    req = captured[0]
    assert req.full_url == "https://api.telnyx.com/v2/messages"
    assert json.loads(req.data) == {"from": "+15550000000", "to": "+15551234567", "text": "hi"}
    assert req.get_header("Authorization") == "Bearer K"


def test_notify_run_filters_and_formats(captured):
    n = Notify(provider="telnyx", to="5551234567", from_number="5550000000", telnyx_api_key="K")
    notify.notify_run(n, [
        ("entered", "A", "https://a", "confirmation detected"),
        ("needs_manual", "Grill", "https://g", "CAPTCHA present (x)"),
    ])
    text = json.loads(captured[0].data)["text"]
    assert "1 need manual entry" in text and "Grill (CAPTCHA) https://g" in text
    assert "https://a" not in text


def test_notify_failure_does_not_raise(monkeypatch):
    n = Notify(provider="twilio", to="1", from_number="2")  # no credentials
    notify.notify_run(n, [("needs_manual", "x", "u", "d")])  # logs a warning only


# ---------- eligibility ----------

def test_residency():
    p = Profile("J", "D", "e", state="IL", state_name="Illinois")
    assert rules.residency_excluded("Open only to legal residents of the U.S. and D.C.", p) is None
    assert rules.residency_excluded("Open to legal residents of Canada.", p)
    assert rules.residency_excluded("Open to residents of the 50 US, excluding Illinois.", p)
    assert rules.residency_excluded("Open to the fifty (50) United States, void in IL.", p)
    assert rules.residency_excluded("Open worldwide.", p) is None


# ---------- blog posts from feeds ----------

def test_feed_blog_post_follows_entry_link(server, ctx, cfg):
    status, detail = enter_one(ctx, cfg, Sweepstake(url=f"{server}/blog_post.html", follow_link=True))
    assert status == "entered", detail
    assert "via http://localhost" in detail


def test_never_fills_comment_or_newsletter_forms(server, ctx, cfg):
    status, detail = enter_one(ctx, cfg, Sweepstake(url=f"{server}/comment_only.html", follow_link=True))
    assert status == "needs_manual"
    assert "no entry form" in detail
