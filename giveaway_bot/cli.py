"""Command line: python -m giveaway_bot <command>"""
from __future__ import annotations

import argparse
import logging
import time

from .config import ConfigError, load_config
from .runner import discover, run_once
from .tracker import Tracker


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="giveaway_bot", description="Autonomously enter sweepstakes.")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="discover + enter everything due, once")
    r.add_argument("--dry-run", action="store_true", help="show what would be entered")
    r.add_argument("--show-browser", action="store_true", help="run with a visible browser")
    lp = sub.add_parser("loop", help="run forever, every settings.loop_interval_hours")
    lp.add_argument("--show-browser", action="store_true")
    sub.add_parser("discover", help="only fetch feeds and list new giveaways")
    h = sub.add_parser("history", help="show recent entry attempts")
    h.add_argument("-n", type=int, default=30)
    sub.add_parser("manual", help="list giveaways you need to enter by hand")
    sub.add_parser("check", help="validate the config file")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
    )
    try:
        cfg = load_config(args.config)
    except (ConfigError, FileNotFoundError) as e:
        print(f"config error: {e}")
        return 2
    if getattr(args, "show_browser", False):
        cfg.settings.headless = False

    if args.cmd == "check":
        print(f"OK: {cfg.profile.full_name} <{cfg.profile.email}>, "
              f"{len(cfg.sweepstakes)} giveaway(s), {len(cfg.feeds)} feed(s)")
    elif args.cmd == "run":
        counts = run_once(cfg, dry_run=args.dry_run)
        if counts:
            print("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if counts.get("needs_manual"):
            print("run `python -m giveaway_bot manual` to see what needs you.")
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
    elif args.cmd == "manual":
        rows = Tracker(cfg.data_path / "entries.db").needs_manual()
        if not rows:
            print("nothing needs manual entry")
        for url, name, detail, ts in rows:
            print(f"- {name or url}\n  {url}\n  why: {detail}")
    return 0
