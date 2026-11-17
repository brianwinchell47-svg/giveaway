"""Run one pass: discover new giveaways, then enter everything that's due."""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

from . import rules
from .config import Config, Sweepstake
from .discovery import fetch_feed
from .filler import detect_captcha, fill_form, submit
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


def enter_one(ctx: BrowserContext, cfg: Config, sweep: Sweepstake) -> tuple[str, str]:
    """Returns (status, detail)."""
    s = cfg.settings
    if sweep.end_date and date.fromisoformat(sweep.end_date) < date.today():
        return "skipped", f"ended {sweep.end_date}"

    page = ctx.new_page()
    page.set_default_timeout(s.page_timeout_ms)
    try:
        page.goto(sweep.url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass

        text = _page_text(page)
        if rules.has_ended(text):
            return "skipped", "page says giveaway has ended"
        if rules.already_entered(text):
            return "entered", "page says already entered this period"

        full = text + "\n" + _rules_text(ctx, page, s.page_timeout_ms)
        banned = rules.automation_banned(full)
        if banned:
            return "needs_manual", f"rules prohibit automated entry: \"{banned}\""
        min_age = rules.minimum_age(full)
        if min_age and cfg.profile.age is not None and cfg.profile.age < min_age:
            return "skipped", f"requires age {min_age}+"

        cap = detect_captcha(page)
        if cap:
            return "needs_manual", f"CAPTCHA present ({cap})"

        res = fill_form(page, cfg.profile, sweep, s)
        if res.frame is None:
            return "needs_manual", "no entry form recognised (may need a login or social action)"
        if res.unfilled_required:
            return "needs_manual", "could not fill required: " + ", ".join(res.unfilled_required[:5])
        log.info("  filled %s; checked %s", res.filled, res.checked)

        before_url = page.url
        if not submit(page, res, sweep):
            return "needs_manual", "no submit button found"
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
        page.wait_for_timeout(2000)

        # A CAPTCHA that pops up only after clicking submit.
        cap = detect_captcha(page)
        after = _page_text(page)
        if rules.looks_successful(after, sweep.success_text) or rules.already_entered(after):
            status, detail = "entered", "confirmation detected"
        elif cap:
            status, detail = "needs_manual", f"CAPTCHA appeared on submit ({cap})"
        else:
            invalid = 0
            try:
                invalid = res.frame.locator("input:invalid, select:invalid, [aria-invalid=true]").count()
            except Exception:
                pass
            if invalid:
                status, detail = "failed", f"{invalid} field(s) rejected by the form"
            elif page.url != before_url:
                status, detail = "submitted_unconfirmed", f"navigated to {page.url}"
            else:
                status, detail = "submitted_unconfirmed", "submitted, no confirmation text found"
        if s.screenshots:
            shots = cfg.data_path / "screenshots"
            shots.mkdir(exist_ok=True)
            slug = re.sub(r"\W+", "_", sweep.name or sweep.url)[:60]
            page.screenshot(path=str(shots / f"{datetime.now():%Y%m%d-%H%M%S}_{slug}.png"), full_page=True)
        return status, detail
    except Exception as e:  # noqa: BLE001 - one bad site shouldn't stop the run
        return "failed", f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
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
    if cfg.settings.auto_enter_discovered:
        for url, title in tracker.pending_discovered(cfg.settings.max_discovered_per_run):
            queue.append((Sweepstake(url=url, name=title), "feed"))

    counts: dict[str, int] = {}
    if not queue:
        log.info("nothing due")
        return counts
    log.info("%d giveaway(s) due", len(queue))
    if dry_run:
        for sw, src in queue:
            log.info("  would enter [%s] %s %s", src, sw.name, sw.url)
        return counts

    with sync_playwright() as pw:
        browser = launch_browser(pw, cfg.settings.headless)
        ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        for i, (sw, src) in enumerate(queue):
            if i:
                time.sleep(cfg.settings.delay_between_entries_s)
            log.info("→ %s %s", sw.name or "", sw.url)
            status, detail = enter_one(ctx, cfg, sw)
            tracker.record(sw.url, status, detail, sw.name, src)
            counts[status] = counts.get(status, 0) + 1
            log.info("  %s: %s", status, detail)
        browser.close()
    return counts
