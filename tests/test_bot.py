import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from giveaway_bot import rules
from giveaway_bot.config import Profile, Sweepstake
from giveaway_bot.discovery import parse_feed
from giveaway_bot.runner import check_one
from giveaway_bot.tracker import Tracker

from conftest import REQUESTS

PKG = Path(__file__).parent.parent / "giveaway_bot"


# ---------- the bot never fills or submits anything ----------

def test_no_form_interaction_in_source():
    """Guard against form filling creeping back in."""
    banned = re.compile(r"\.(fill|click|check|uncheck|select_option|press|type|set_input_files|tap)\(")
    for f in PKG.glob("*.py"):
        hits = [ln for ln in f.read_text().splitlines() if banned.search(ln)]
        assert not hits, f"{f.name}: {hits}"


def test_entry_form_is_left_untouched(server, ctx, cfg):
    status, link, _ = check_one(ctx, cfg, Sweepstake(url=f"{server}/autosubmit_trap.html"))
    assert status == "ready"
    assert link.endswith("/autosubmit_trap.html")
    assert not any("submitted" in r for r in REQUESTS)


# ---------- pure unit tests ----------

def test_rules_age_and_ended():
    assert rules.minimum_age("must be 21 years of age or older") == 21
    assert rules.has_ended("This sweepstakes has ended.")
    assert not rules.has_ended("Enter daily until 12/31.")


def test_residency():
    p = Profile(state="IL", state_name="Illinois")
    assert rules.residency_excluded("Open only to legal residents of the U.S. and D.C.", p) is None
    assert rules.residency_excluded("Open to legal residents of Canada.", p)
    assert rules.residency_excluded("Open to residents of the 50 US, excluding Illinois.", p)
    assert rules.residency_excluded("Open to the fifty (50) United States, void in IL.", p)
    assert rules.residency_excluded("Open worldwide.", p) is None


def test_tracker_frequency(tmp_path):
    t = Tracker(tmp_path / "db.sqlite")
    assert t.is_due("u", "daily")
    t.record("u", "ready")
    assert not t.is_due("u", "daily")
    assert t.is_due("u", "daily", now=datetime.now() + timedelta(hours=24))
    t.record("o", "skipped")
    assert not t.is_due("o", "once")
    t.record("f", "failed")
    assert t.is_due("f", "once")  # failed checks are retried
    t.record("b", "ready", name="Blog", link="https://sponsor/enter")
    assert ("https://sponsor/enter", "Blog") in [r[:2] for r in t.todo()]


def test_parse_feed():
    rss = "<rss><channel><item><title>Win A</title><link>https://a.example/x</link></item></channel></rss>"
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>B</title>'
            '<link href="https://b.example/y"/></entry></feed>')
    assert parse_feed(rss) == [("Win A", "https://a.example/x")]
    assert parse_feed(atom) == [("B", "https://b.example/y")]


# ---------- reading pages ----------

@pytest.mark.parametrize("page,expected,why", [
    ("good.html", "ready", "open"),
    ("ended.html", "skipped", "ended"),
    ("canada_only.html", "skipped", "not eligible"),
])
def test_check_pages(server, ctx, cfg, page, expected, why):
    status, _, detail = check_one(ctx, cfg, Sweepstake(url=f"{server}/{page}"))
    assert status == expected, detail
    assert why in detail


def test_age_limit_from_linked_rules(server, ctx, cfg):
    cfg.profile.birthdate = (datetime.now() - timedelta(days=365 * 19)).date().isoformat()
    status, _, detail = check_one(ctx, cfg, Sweepstake(url=f"{server}/age21.html"))
    assert (status, detail) == ("skipped", "requires age 21+")


def test_feed_blog_post_links_to_sponsor_page(server, ctx, cfg):
    status, link, _ = check_one(ctx, cfg, Sweepstake(url=f"{server}/blog_post.html", follow_link=True))
    assert status == "ready"
    assert link.startswith("http://localhost") and link.endswith("/good.html")


def test_bad_page_is_failed_not_crash(ctx, cfg):
    status, _, _ = check_one(ctx, cfg, Sweepstake(url="http://127.0.0.1:9/nothing"))
    assert status == "failed"
