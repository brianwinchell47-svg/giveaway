"""Find an entry form on a page, map its fields to your profile, fill and submit it."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

from playwright.sync_api import Frame, Page

from .config import Profile, Settings, Sweepstake

# Ordered: the first pattern that matches a field's description wins.
FIELD_PATTERNS: list[tuple[str, re.Pattern]] = [
    (k, re.compile(p, re.I))
    for k, p in [
        ("email", r"e-?mail"),
        ("birth_month", r"(birth|dob|bday).{0,15}month|month.{0,15}(birth|dob)|\bbday-month\b"),
        ("birth_day", r"(birth|dob|bday).{0,15}\bday|\bday.{0,15}(birth|dob)|\bbday-day\b"),
        ("birth_year", r"(birth|dob|bday).{0,15}year|year.{0,15}(birth|dob)|\bbday-year\b"),
        ("birthdate", r"birth|\bdob\b|\bbday\b"),
        ("age", r"^\s*age\b|\byour age\b"),
        ("first_name", r"first.?name|given.?name|\bfname\b|\bfirst\b"),
        ("last_name", r"last.?name|sur.?name|family.?name|\blname\b|\blast\b"),
        ("phone", r"phone|mobile|\btel\b|cell"),
        ("address2", r"address.?(line.?)?2|\bapt\b|suite|unit"),
        ("address1", r"address|street"),
        ("city", r"\bcity\b|town|address-level2"),
        ("state", r"\bstate\b|province|region|address-level1"),
        ("zip", r"\bzip|postal|post.?code"),
        ("country", r"country"),
        ("full_name", r"\bname\b"),
    ]
]

CHECK_MARKETING = re.compile(
    r"newsletter|marketing|promotion(al)?s?\b|offers|subscribe|partners?|sponsors? (may|to) "
    r"(contact|send)|updates|news\b|sms|text messages",
    re.I,
)
CHECK_RULES = re.compile(
    r"official rules|terms|conditions|privacy|agree|eligib|consent|confirm|certify|"
    r"years of age|i am (at least|over)|acknowledge",
    re.I,
)
CAPTCHA_FRAME = re.compile(r"recaptcha|hcaptcha|challenges\.cloudflare\.com|arkoselabs|funcaptcha", re.I)

# Annotates every visible field with data-gb-idx and returns a description of each.
COLLECT_JS = """
() => {
  const out = [];
  const els = document.querySelectorAll('input, select, textarea');
  let i = 0;
  for (const el of els) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden','submit','button','image','reset','file','password','search'].includes(type)) continue;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    const visible = (r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none')
      || type === 'checkbox' || type === 'radio';
    if (!visible || el.disabled || el.readOnly) continue;
    let label = '';
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) label = l.innerText;
    }
    if (!label && el.closest('label')) label = el.closest('label').innerText;
    if (!label && el.getAttribute('aria-labelledby')) {
      const l = document.getElementById(el.getAttribute('aria-labelledby'));
      if (l) label = l.innerText;
    }
    if (!label) {
      const p = el.parentElement;
      // Only trust parent text when this is the parent's only field.
      if (p && p.querySelectorAll('input,select,textarea').length === 1
          && p.innerText && p.innerText.length < 200) label = p.innerText;
    }
    el.setAttribute('data-gb-idx', String(i));
    const form = el.form || el.closest('form');
    out.push({
      idx: i++,
      tag: el.tagName.toLowerCase(),
      type,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      placeholder: el.getAttribute('placeholder') || '',
      aria: el.getAttribute('aria-label') || '',
      label: (label || '').trim().slice(0, 300),
      required: el.required || el.getAttribute('aria-required') === 'true',
      maxlength: el.maxLength > 0 ? el.maxLength : null,
      options: el.tagName === 'SELECT'
        ? Array.from(el.options).map(o => [o.value, o.text.trim()]) : null,
      formIdx: form ? Array.from(document.forms).indexOf(form) : -1,
    });
  }
  return out;
}
"""


@dataclass
class FillResult:
    frame: Frame | None
    filled: list[str]
    checked: list[str]
    unfilled_required: list[str]
    form_idx: int


def classify(f: dict) -> str | None:
    if f["type"] == "email":
        return "email"
    if f["type"] == "tel":
        return "phone"
    if f["type"] == "date":
        return "birthdate"
    ac = f["autocomplete"].lower()
    ac_map = {
        "given-name": "first_name", "family-name": "last_name", "name": "full_name",
        "email": "email", "tel": "phone", "address-line1": "address1",
        "street-address": "address1", "address-line2": "address2",
        "address-level2": "city", "address-level1": "state", "postal-code": "zip",
        "country": "country", "country-name": "country", "bday": "birthdate",
        "bday-month": "birth_month", "bday-day": "birth_day", "bday-year": "birth_year",
    }
    if ac in ac_map:
        return ac_map[ac]
    # Attribute names are more reliable than surrounding text; try them first.
    for desc in (
        " ".join([f["name"], f["id"]]),
        " ".join([f["placeholder"], f["aria"], f["label"][:80]]),
    ):
        desc = re.sub(r"[_\-\[\]]+", " ", desc)
        desc = re.sub(r"([a-z])([A-Z])", r"\1 \2", desc)
        for key, rx in FIELD_PATTERNS:
            if rx.search(desc):
                return key
    return None


def profile_values(p: Profile, key: str, f: dict) -> list[str]:
    """Candidate values (best first) for a field key."""
    b = p.birth
    if key == "email":
        return [p.email]
    if key in ("first_name", "last_name", "full_name", "address1", "address2", "city", "zip"):
        return [getattr(p, key)]
    if key == "phone":
        digits = re.sub(r"\D", "", p.phone)
        return [digits if (f["maxlength"] or 99) < len(p.phone) else p.phone, digits]
    if key == "state":
        return [p.state, p.state_name]
    if key == "country":
        return [p.country, p.country_code, "United States of America", "USA"] \
            if p.country_code == "US" else [p.country, p.country_code]
    if not b:
        return []
    if key == "birth_month":
        return [str(b.month), f"{b.month:02d}", calendar.month_name[b.month], calendar.month_abbr[b.month]]
    if key == "birth_day":
        return [str(b.day), f"{b.day:02d}"]
    if key == "birth_year":
        return [str(b.year)]
    if key == "birthdate":
        if f["type"] == "date":
            return [b.isoformat()]
        ph = (f["placeholder"] + f["label"]).lower()
        if "dd/mm" in ph:
            return [b.strftime("%d/%m/%Y")]
        return [b.strftime("%m/%d/%Y")]
    if key == "age":
        return [str(p.age)]
    return []


def _pick_option(options, candidates):
    cands = [c.lower() for c in candidates if c]
    for c in cands:
        for value, text in options:
            if value.lower() == c or text.lower() == c:
                return value
    for c in cands:
        if len(c) > 3:
            for value, text in options:
                if text.lower().startswith(c):
                    return value
    return None


def detect_captcha(page: Page) -> str | None:
    for fr in page.frames:
        if CAPTCHA_FRAME.search(fr.url or ""):
            return fr.url.split("?")[0]
    sel = ".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey], iframe[title*='captcha' i]"
    for fr in page.frames:
        try:
            if fr.locator(sel).count():
                return "captcha widget on page"
        except Exception:
            pass
    return None


def fill_form(page: Page, profile: Profile, sweep: Sweepstake, settings: Settings) -> FillResult:
    # Explicit selectors from config always win.
    for selector, value in sweep.fields.items():
        page.fill(selector, value)

    # Pick the form (in any frame) with the most recognisable fields.
    best_score, frame, best_fields, form_idx = 0, None, [], -1
    for fr in page.frames:
        try:
            fields = fr.evaluate(COLLECT_JS)
        except Exception:
            continue
        by_form: dict[int, list] = {}
        for f in fields:
            by_form.setdefault(f["formIdx"], []).append(f)
        for idx, ffs in by_form.items():
            score = sum(1 for f in ffs if f["type"] not in ("checkbox", "radio") and classify(f))
            if score > best_score:
                best_score, frame, best_fields, form_idx = score, fr, ffs, idx
    if frame is None:
        return FillResult(None, [], [], [], -1)

    res = FillResult(frame, [], [], [], form_idx)
    radio_groups_done: set[str] = set()
    for f in best_fields:
        loc = frame.locator(f'[data-gb-idx="{f["idx"]}"]')
        first_line = (f["label"].strip().splitlines() or [""])[0]
        desc = (first_line or f["placeholder"] or f["name"] or f["id"]).strip()[:40]
        if f["type"] in ("checkbox", "radio"):
            text = " ".join([f["label"], f["name"], f["id"], f["aria"]])
            if f["type"] == "radio":
                if f["name"] in radio_groups_done or not f["required"]:
                    continue
            wants = False
            if CHECK_MARKETING.search(text):
                wants = settings.accept_marketing
            elif CHECK_RULES.search(text) or f["required"]:
                wants = settings.accept_rules
            if wants:
                try:
                    loc.check(force=True)
                    res.checked.append(desc)
                    radio_groups_done.add(f["name"])
                except Exception:
                    pass
            continue

        key = classify(f)
        cands = profile_values(profile, key, f) if key else []
        cands = [c for c in cands if c]
        ok = False
        if cands:
            try:
                if f["tag"] == "select":
                    v = _pick_option(f["options"], cands)
                    if v is not None:
                        loc.select_option(v)
                        ok = True
                else:
                    loc.fill(cands[0])
                    ok = True
            except Exception:
                ok = False
        if ok:
            res.filled.append(f"{key}={desc}")
        elif f["required"]:
            res.unfilled_required.append(desc or f["type"])
    return res


SUBMIT_TEXT = re.compile(r"^\s*(enter|submit|enter now|enter to win|sign up|join|continue|send|i'?m in)\b", re.I)


def submit(page: Page, res: FillResult, sweep: Sweepstake) -> bool:
    if sweep.submit_selector:
        page.click(sweep.submit_selector)
        return True
    frame = res.frame
    scope = frame.locator("form").nth(res.form_idx) if res.form_idx >= 0 else frame.locator("body")
    for sel in ("button[type=submit]", "input[type=submit]", "button:not([type])", "button", "[role=button]", "a"):
        btns = scope.locator(sel)
        for i in range(min(btns.count(), 20)):
            b = btns.nth(i)
            try:
                if not b.is_visible():
                    continue
                label = (b.inner_text() if sel != "input[type=submit]" else b.get_attribute("value")) or ""
            except Exception:
                continue
            if sel in ("button[type=submit]", "input[type=submit]") or SUBMIT_TEXT.search(label):
                b.click()
                return True
    return False
