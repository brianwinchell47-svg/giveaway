# Giveaway Automation

A bot that enters sweepstakes and giveaways for you on a schedule. It opens each giveaway in a headless browser, fills the entry form with your details, ticks the "I agree to the Official Rules" box, submits, and confirms the entry. It also keeps a log so it never enters the same giveaway twice in one period.

## What it does on each run

1. **Discovers** new giveaways from any RSS/Atom feeds you list (optional).
2. **Picks what's due**: `once` giveaways not yet attempted, `daily`/`weekly` ones whose period has elapsed, and anything past its `end_date` is skipped.
3. For each giveaway:
   - Skips it if the page says it has **ended**, or you've **already entered** today.
   - Reads the page **and its linked Official Rules**. If they ban automated/scripted entries, it does **not** enter and flags it for you instead (automated entries there would just get you disqualified).
   - Skips it if the rules' minimum age is above yours, or the residency rules exclude you.
   - If there's a **CAPTCHA**, it flags it for manual entry (it does not try to solve or bypass them).
   - Otherwise it finds the entry form, maps fields (name, email, phone, address, state, ZIP, country, birth date/month/day/year, age) using labels, `name`/`id`, placeholders and `autocomplete`. It fills them, ticks the rules checkbox, leaves newsletter/partner opt-ins **unticked** (configurable), and submits.
   - Checks for a confirmation message and saves a screenshot.
4. Logs every attempt to `data/entries.db`.
5. Texts you a list of anything that needs manual entry (optional).

Statuses: `entered`, `submitted_unconfirmed` (submitted, but no "thanks" text found; check the screenshot), `needs_manual`, `skipped`, `failed`.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
python -m giveaway_bot setup         # asks for your details + SMS settings
python -m giveaway_bot check         # validate config
python -m giveaway_bot feeds         # see which giveaway feeds work for you
python -m giveaway_bot run --dry-run # see what would be entered
python -m giveaway_bot run           # enter everything that's due
```

## Your personal information

Your name, email, address, birth date and SMS credentials go in **`personal.yaml`**, separate from `config.yaml`, so you can share or commit your giveaway list without exposing your details.

- `python -m giveaway_bot setup` asks for everything and writes the file (re-run any time; Enter keeps the current value). Or copy `personal.example.yaml` and edit it.
- The file is git-ignored and set to owner-only permissions (`chmod 600`).
- SMS credentials can come from environment variables instead (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `VOIPMS_USERNAME`, `VOIPMS_API_PASSWORD`, `TELNYX_API_KEY`).

## Text alerts to your phone

After each run the bot sends **one batched text** listing giveaways that need you (CAPTCHA, rules ban bots, extra questions), with links so you can tap and enter. Choose which outcomes alert you with `notify.on` in `config.yaml` (`needs_manual`, `failed`, `entered`, `submitted_unconfirmed`).

| Provider | What you need | Notes |
|---|---|---|
| **Twilio** | Account SID, Auth Token, a Twilio number | US numbers need A2P 10DLC registration before texts deliver. |
| **VoIP.ms** | API username (login email), API password, an SMS-enabled DID | Enable the API and **whitelist your computer's IP** at *Main Menu → SOAP and REST/JSON API*. Long texts are split into 160-character messages. |
| **Telnyx** | API key, a Telnyx number with a messaging profile | |

Test it with `python -m giveaway_bot notify-test`. A failed text never stops the bot; it's logged as a warning.

## Giveaway feeds

`config.example.yaml` comes with five sweepstakes-blog RSS feeds. Run `python -m giveaway_bot feeds` to see which ones work from your connection, and remove any that fail. Feed posts are usually *articles about* a giveaway, so for those the bot:

- follows the post's "click here to enter" link to the sponsor's real entry page, and
- **never** fills comment, search, login, newsletter or contact forms, even on the entry page itself.

It also skips giveaways whose rules say they're open only to residents of somewhere else, or that exclude your state.

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
| `python -m giveaway_bot feeds` | Test each feed and show how many items it lists |
| `python -m giveaway_bot setup` | Enter or update your details and SMS settings |
| `python -m giveaway_bot notify-test` | Send a test text |
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
- `config.yaml` and `personal.yaml` are both git-ignored.
- Set `GIVEAWAY_CHROMIUM=/path/to/chrome` to use a specific Chromium binary.

## Development

```bash
pip install pytest
python -m pytest -q    # uses local test pages in tests/fixtures; no internet needed
```
