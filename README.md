# Giveaway Finder

Finds sweepstakes and giveaways, checks which ones are still open and that you're eligible for, and **texts you the links so you can enter them yourself**.

It only reads web pages. It never fills in, clicks or submits any form, so every entry you make is your own.

## What it does on each run

1. **Discovers** new giveaways from the RSS/Atom feeds in your config (sweepstakes blogs).
2. **Picks what's due**: new feed posts, plus giveaways from your own list. `daily`/`weekly` giveaways come back once per period; `once` giveaways are sent once.
3. **Checks each page** (read-only), including its linked Official Rules:
   - skips it if the page says it has **ended**, or it's past your `end_date`,
   - skips it if the rules are only open to residents of somewhere else, exclude your state, or set a minimum age above yours,
   - for blog posts, finds the "click here to enter" link and sends you the **sponsor's entry page** instead of the article.
4. **Texts you** one message listing the giveaways that are ready, with links.
5. Logs everything to `data/entries.db`.

Statuses: `ready` (open, and you look eligible), `skipped` (ended or not eligible), `failed` (page couldn't be loaded; retried next run).

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml   # your giveaway list + feeds
python -m giveaway_bot setup         # eligibility details + SMS settings
python -m giveaway_bot check         # validate config
python -m giveaway_bot feeds         # see which feeds work for you
python -m giveaway_bot run           # check everything due, text you the links
```

## Your personal information

`personal.yaml` holds only what's needed to filter out giveaways you can't win, plus your SMS credentials:

- **state** and **country**, for residency rules,
- **birth date** (optional), for minimum-age rules.

None of it is typed into any website. The file is git-ignored and set to owner-only permissions (`chmod 600`). Create it with `python -m giveaway_bot setup`, or copy `personal.example.yaml`. If you have a `personal.yaml` from the earlier form-filling version, re-run `setup`. It drops the name, email, phone and address it no longer needs.

SMS credentials can come from environment variables instead (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `VOIPMS_USERNAME`, `VOIPMS_API_PASSWORD`, `TELNYX_API_KEY`).

## Text alerts to your phone

After each run you get **one batched text**, for example:

```
3 giveaway(s) to enter:
- Win a Grill from Acme https://acme.example/sweeps
- $500 Gift Card Daily https://brand.example/win
- Kitchen Makeover https://sponsor.example/enter
```

Choose what's included with `notify.on` in `config.yaml`: `ready` (default), `failed`, `skipped`.

| Provider | What you need | Notes |
|---|---|---|
| **Twilio** | Account SID, Auth Token, a Twilio number | US numbers need A2P 10DLC registration before texts deliver. |
| **VoIP.ms** | API username (login email), API password, an SMS-enabled DID | Enable the API and **whitelist your computer's IP** at *Main Menu → SOAP and REST/JSON API*. Long texts are split into 160-character messages. |
| **Telnyx** | API key, a Telnyx number with a messaging profile | |

Test it with `python -m giveaway_bot notify-test`. A failed text never stops the bot; it's logged as a warning.

## Giveaway feeds

`config.example.yaml` comes with five sweepstakes-blog RSS feeds. Run `python -m giveaway_bot feeds` to see which ones work from your connection, and remove any that fail. To keep texts short, each run checks up to `max_discovered_per_run` new feed posts (default 10). The rest wait for later runs.

## Running it on a schedule

Cron (Linux/macOS). Run `crontab -e` and add:

```cron
# every day at 8:17am
17 8 * * * cd /path/to/giveaway && /usr/bin/python3 -m giveaway_bot run >> data/cron.log 2>&1
```

On Windows, use Task Scheduler with the action `python -m giveaway_bot run` and "Start in" set to this folder. Or leave `python -m giveaway_bot loop` running.

## Commands

| Command | Purpose |
|---|---|
| `python -m giveaway_bot run` | Discover, check, and text you what's ready (`--dry-run` to preview) |
| `python -m giveaway_bot todo` | Giveaways marked ready in the last 24 hours, with links |
| `python -m giveaway_bot history -n 50` | Recent checks and results |
| `python -m giveaway_bot discover` | Fetch feeds only |
| `python -m giveaway_bot feeds` | Test each feed and show how many items it lists |
| `python -m giveaway_bot setup` | Enter or update eligibility details and SMS settings |
| `python -m giveaway_bot notify-test` | Send a test text |
| `python -m giveaway_bot loop` | Run forever, every `loop_interval_hours` |

## Notes

- Eligibility checks read the rules' wording and can miss unusual phrasing. Always skim the Official Rules before you enter.
- `config.yaml` and `personal.yaml` are both git-ignored.
- Set `GIVEAWAY_CHROMIUM=/path/to/chrome` to use a specific Chromium binary.

## Development

```bash
pip install pytest
python -m pytest -q    # uses local test pages in tests/fixtures; no internet needed
```

The tests include a guard that fails if any form-interaction call (`fill`, `click`, `check`, `select_option`, …) appears in the code. A second test checks that a page's form is never submitted.
