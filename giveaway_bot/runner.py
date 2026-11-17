"""Run one pass: discover giveaways, check which are open to you, text you the links.

Pages are only read. Nothing is typed, clicked or submitted on any site.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

from . import rules
from .config import Config, Sweepstake
from .discovery import fetch_feed
from .notify import notify_run
from .tracker import Tracker

log = logging.getLogger("giveaway_bot")

RULES_LINK = re.compile(r"official rules|^rules$|terms (and|&) conditions|sweepstakes rules", re.I)


def _page_text(page: Page) -> str:
    parts = []
    for fr in page.frames:
        try:
            parts.append(fr.locator("body").inner_text(timeout=3000))
        except Exception:
            pass
    return "\n".join(parts)


def _rules_text(ctx: BrowserContext, page: Page, timeout: int) -> str:
    """Open the 'Official Rules' link (if any) in a new tab and return its text."""
    links = page.locator("a")
    for i in range(min(links.count(), 300)):
        a = links.nth(i)
        try:
            text = a.inner_text(timeout=500).strip()
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if not RULES_LINK.search(text) or href.startswith(("javascript:", "#", "mailto:")):
            continue
        url = a.evaluate("a => a.href")
        p = ctx.new_page()
        try:
            p.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return p.locator("body").inner_text(timeout=5000)
        except Exception:
            return ""
        finally:
            p.close()
    return ""


SOCIAL = re.compile(
    r"(facebook|twitter|x|instagram|pinterest|tiktok|youtube|linkedin|reddit|whatsapp|"
    r"t|bit|feedburner|gravatar|wordpress|google|amzn|amazon)\.(com|co|ly|me)$", re.I,
)
ENTER_TEXT = re.compile(r"\b(enter|entry|click here|visit|go to|giveaway|sweepstakes|contest)\b", re.I)


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def find_entry_link(page: Page) -> str | None:
    """On a blog post about a giveaway, find the outbound link to the real entry page."""
    here = _host(page.url)
    best, best_score = None, 0
    links = page.locator("a[href]")
    for i in range(min(links.count(), 400)):
        a = links.nth(i)
        try:
            href = a.evaluate("a => a.href")
            text = a.inner_text(timeout=300).strip()
        except Exception:
            continue
        host = _host(href)
        if not href.startswith("http") or not host or host == here or SOCIAL.search(host):
            continue
        score = 0
        if re.search(r"\benter\b|enter (here|now)|click here to enter", text, re.I):
            score = 3
        elif ENTER_TEXT.search(text):
            score = 2
        elif RULES_LINK.search(text):
            score = 0
        if score > best_score:
            best, best_score = href, score
    return best


def _settle(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass


def check_one(ctx: BrowserContext, cfg: Config, sweep: Sweepstake) -> tuple[str, str, str]:
    """Read a giveaway page (and its Official Rules) without interacting with it.

    Returns (status, link, detail): status is "ready" (open and you look eligible),
    "skipped" (ended or not eligible) or "failed" (page couldn't be read). link is
    the page to open to enter: the sponsor's entry page when a blog post points to one.
    """
    if sweep.end_date and date.fromisoformat(sweep.end_date) < date.today():
        return "skipped", sweep.url, f"ended {sweep.end_date}"

    page = ctx.new_page()
    page.set_default_timeout(cfg.settings.page_timeout_ms)
    link = sweep.url
    try:
        page.goto(sweep.url, wait_until="domcontentloaded")
        _settle(page)
        if sweep.follow_link:
            target = find_entry_link(page)
            if target:
                link = target
                page.goto(target, wait_until="domcontentloaded")
                _settle(page)

        text = _page_text(page)
        if rules.has_ended(text):
            return "skipped", link, "page says giveaway has ended"
        full = text + "\n" + _rules_text(ctx, page, cfg.settings.page_timeout_ms)
        not_eligible = rules.residency_excluded(full, cfg.profile)
        if not_eligible:
            return "skipped", link, f"not eligible: {not_eligible}"
        min_age = rules.minimum_age(full)
        if min_age and cfg.profile.age is not None and cfg.profile.age < min_age:
            return "skipped", link, f"requires age {min_age}+"
        return "ready", link, "open; enter it yourself"
    except Exception as e:  # noqa: BLE001 - one bad site shouldn't stop the run
        return "failed", link, f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
    finally:
        page.close()


def launch_browser(pw, headless: bool = True):
    """Launch Chromium. Set GIVEAWAY_CHROMIUM to use a specific browser binary."""
    exe = os.environ.get("GIVEAWAY_CHROMIUM") or None
    return pw.chromium.launch(headless=headless, executable_path=exe)


def discover(cfg: Config, tracker: Tracker) -> int:
    new = 0
    for feed in cfg.feeds:
        try:
            items = fetch_feed(feed)
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", feed, e)
            continue
        for title, link in items:
            if tracker.add_discovered(link, title, feed):
                new += 1
                log.info("discovered: %s  %s", title, link)
    return new


def run_once(cfg: Config, dry_run: bool = False) -> dict[str, int]:
    tracker = Tracker(cfg.data_path / "entries.db")
    if cfg.feeds:
        log.info("checking %d feed(s)", len(cfg.feeds))
        discover(cfg, tracker)

    queue: list[tuple[Sweepstake, str]] = [
        (sw, "config") for sw in cfg.sweepstakes
        if sw.enabled and tracker.is_due(sw.url, sw.frequency)
    ]
    for url, title in tracker.pending_discovered(cfg.settings.max_discovered_per_run):
        queue.append((Sweepstake(url=url, name=title, follow_link=True), "feed"))

    counts: dict[str, int] = {}
    results: list[tuple[str, str, str, str]] = []
    if not queue:
        log.info("nothing due")
        return counts
    log.info("%d giveaway(s) to check", len(queue))
    if dry_run:
        for sw, src in queue:
            log.info("  would check [%s] %s %s", src, sw.name, sw.url)
        return counts

    with sync_playwright() as pw:
        browser = launch_browser(pw, cfg.settings.headless)
        ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        for i, (sw, src) in enumerate(queue):
            if i:
                time.sleep(cfg.settings.delay_between_checks_s)
            log.info("→ %s %s", sw.name or "", sw.url)
            status, link, detail = check_one(ctx, cfg, sw)
            tracker.record(sw.url, status, detail, sw.name, src, link)
            counts[status] = counts.get(status, 0) + 1
            results.append((status, sw.name, link, detail))
            log.info("  %s: %s%s", status, detail, f" → {link}" if link != sw.url else "")
        browser.close()
    notify_run(cfg.notify, results)
    return counts
