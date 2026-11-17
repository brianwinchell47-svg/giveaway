"""Command line: python -m giveaway_bot <command>"""
from __future__ import annotations

import argparse
import logging
import time

from .config import ConfigError, load_config
from .discovery import fetch_feed
from .notify import NotifyError, send_sms
from .runner import discover, run_once
from .tracker import Tracker


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="giveaway_bot", description="Find sweepstakes you can enter and text you the links.")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="discover + check everything due, text you the links")
    r.add_argument("--dry-run", action="store_true", help="show what would be checked")
    r.add_argument("--show-browser", action="store_true", help="run with a visible browser")
    lp = sub.add_parser("loop", help="run forever, every settings.loop_interval_hours")
    lp.add_argument("--show-browser", action="store_true")
    sub.add_parser("discover", help="only fetch feeds and list new giveaways")
    h = sub.add_parser("history", help="show recently checked giveaways")
    h.add_argument("-n", type=int, default=30)
    sub.add_parser("todo", help="list giveaways ready for you to enter (last 24h)")
    sub.add_parser("check", help="validate the config file")
    sub.add_parser("setup", help="enter eligibility details and SMS settings (writes personal.yaml)")
    sub.add_parser("notify-test", help="send a test text message")
    sub.add_parser("feeds", help="test each feed and show how many giveaways it lists")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
    )
    if args.cmd == "setup":
        from .setup_wizard import run_setup
        return run_setup(args.config)
    try:
        cfg = load_config(args.config)
    except (ConfigError, FileNotFoundError) as e:
        print(f"config error: {e}")
        return 2
    if getattr(args, "show_browser", False):
        cfg.settings.headless = False

    if args.cmd == "check":
        p = cfg.profile
        where = ", ".join(x for x in (p.state, p.country) if x) or "location not set"
        print(f"OK: {where}; age {p.age if p.age is not None else 'not set'}; "
              f"{len(cfg.sweepstakes)} giveaway(s), {len(cfg.feeds)} feed(s); "
              f"texts {'via ' + cfg.notify.provider if cfg.notify.enabled else 'off'}")
    elif args.cmd == "notify-test":
        if not cfg.notify.enabled:
            print("notifications are off; run `python -m giveaway_bot setup` to add a provider")
            return 1
        try:
            n = send_sms(cfg.notify, "Giveaway bot test: notifications are working.")
        except NotifyError as e:
            print(f"failed: {e}")
            return 1
        print(f"sent {n} message(s) via {cfg.notify.provider} to {cfg.notify.to}")
    elif args.cmd == "feeds":
        bad = 0
        for url in cfg.feeds:
            try:
                items = fetch_feed(url)
                print(f"OK   {len(items):3} items  {url}")
            except Exception as e:  # noqa: BLE001
                bad += 1
                print(f"FAIL {type(e).__name__}: {str(e)[:60]}  {url}")
        if bad:
            print("remove or replace failing feeds in config.yaml")
    elif args.cmd == "run":
        counts = run_once(cfg, dry_run=args.dry_run)
        if counts:
            print("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if counts.get("ready"):
            print("run `python -m giveaway_bot todo` for the links.")
    elif args.cmd == "loop":
        while True:
            try:
                run_once(cfg)
            except Exception:  # noqa: BLE001
                logging.exception("run failed; will retry next interval")
            logging.info("sleeping %.1f h", cfg.settings.loop_interval_hours)
            time.sleep(cfg.settings.loop_interval_hours * 3600)
    elif args.cmd == "discover":
        n = discover(cfg, Tracker(cfg.data_path / "entries.db"))
        print(f"{n} new giveaway(s) found")
    elif args.cmd == "history":
        for ts, status, name, url, detail in Tracker(cfg.data_path / "entries.db").history(args.n):
            print(f"{ts}  {status:22} {(name or '')[:30]:30} {url}\n{'':43}{detail}")
    elif args.cmd == "todo":
        rows = Tracker(cfg.data_path / "entries.db").todo()
        if not rows:
            print("nothing to enter right now")
        for link, name, ts in rows:
            print(f"- {name or ''}\n  {link}")
    return 0
