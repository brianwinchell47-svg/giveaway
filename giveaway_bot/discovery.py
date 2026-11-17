"""Discover giveaways from RSS / Atom feeds the user chooses."""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (X11; Linux x86_64) giveaway-bot/0.1"


def parse_feed(xml_text: str) -> list[tuple[str, str]]:
    """Return (title, link) pairs from an RSS 2.0 or Atom document."""
    root = ET.fromstring(xml_text)
    items = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title, link = "", ""
        for child in el:
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "title":
                title = (child.text or "").strip()
            elif ctag == "link":
                href = child.get("href")
                if href and child.get("rel", "alternate") == "alternate":
                    link = href
                elif not href and child.text:
                    link = child.text.strip()
        if link:
            items.append((title, link))
    return items


def fetch_feed(url: str, timeout: int = 20) -> list[tuple[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_feed(resp.read().decode("utf-8", "replace"))
