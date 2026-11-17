# Giveaway Automation

A bot that enters sweepstakes and giveaways for you on a schedule. It opens each giveaway in a headless browser, fills the entry form with your details, ticks the "I agree to the Official Rules" box, submits, and confirms the entry. It also keeps a log so it never enters the same giveaway twice in one period.

## What it does on each run

1. **Discovers** new giveaways from any RSS/Atom feeds you list (optional).
2. **Picks what's due**: `once` giveaways not yet attempted, `daily`/`weekly` ones whose period has elapsed, and anything past its `end_date` is skipped.
3. For each giveaway:
   - Skips it if the page says it has **ended**, or you've **already entered** today.
   - Reads the page **and its linked Official Rules**. If they ban automated/scripted entries, it does **not** enter and flags it for you instead (automated entries there would just get you disqualified).
   - Skips it if the rules' minimum age is above yours.
   - If there's a **CAPTCHA**, it flags it for manual entry (it does not try to solve or bypass them).
   - Otherwise it finds the entry form, maps fields (name, email, phone, address, state, ZIP, country, birth date/month/day/year, age) using labels, `name`/`id`, placeholders and `autocomplete`. It fills them, ticks the rules checkbox, leaves newsletter/partner opt-ins **unticked** (configurable), and submits.
   - Checks for a confirmation message and saves a screenshot.
4. Logs every attempt to `data/entries.db`.

Statuses: `entered`, `submitted_unconfirmed` (submitted, but no "thanks" text found; check the screenshot), `needs_manual`, `skipped`, `failed`.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml   # then edit it with your details
python -m giveaway_bot check         # validate config
python -m giveaway_bot run --dry-run # see what would be entered
python -m giveaway_bot run           # enter everything that's due
```

## Running it without you

Either leave it running:

```bash
python -m giveaway_bot loop          # runs every settings.loop_interval_hours
```

or schedule it with cron (recommended; survives reboots). Run `crontab -e` and add:

```cron
# every day at 9:17am
17 9 * * * cd /path/to/giveaway && /usr/bin/python3 -m giveaway_bot run >> data/cron.log 2>&1
```

On Windows, use Task Scheduler with the action `python -m giveaway_bot run` and "Start in" set to this folder.

## Other commands

| Command | Purpose |
|---|---|
| `python -m giveaway_bot manual` | Giveaways it couldn't enter (CAPTCHA, rules ban automation, unknown required fields) with the reason. Enter these yourself. |
| `python -m giveaway_bot history -n 50` | Recent attempts and outcomes |
| `python -m giveaway_bot discover` | Fetch feeds only |
| `python -m giveaway_bot run --show-browser` | Watch it work in a visible browser (good for debugging a site) |

## Fixing a site the auto-detection gets wrong

Add overrides to that giveaway in `config.yaml`:

```yaml
  - url: https://example.com/sweeps
    frequency: daily
    fields:
      "#promo-code": "WINTER"        # CSS selector: value
    submit_selector: "button.enter-btn"
    success_text: ["You're entered"]
```

## Notes and limits

- **Discovered giveaways aren't entered unless you opt in** (`auto_enter_discovered: true`). Feeds often include giveaways for other countries or ones that require social follows. Start by reviewing them with `discover`.
- It can't do entries that need a login, a social-media action (follow/retweet), a photo/essay upload, or a CAPTCHA. Those land in `manual`.
- One identity only: it uses the single profile in your config. Extra emails/identities break nearly every sweepstakes' rules and void all of your entries.
- Keep `config.yaml` private; it's git-ignored by default.
- Set `GIVEAWAY_CHROMIUM=/path/to/chrome` to use a specific Chromium binary.

## Development

```bash
pip install pytest
python -m pytest -q    # uses local test pages in tests/fixtures; no internet needed
```
