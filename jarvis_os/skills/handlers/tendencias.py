"""Skill handler: tendencias (RSS/feed trend analysis).

Usage::

    result = tendencias.run({"action": "fetch", "hours_back": 24})
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the tendencias skill.

    Args:
        input_data: Skill input matching ``.skills/tendencias.md`` schema.

    Returns:
        A dict with ``success`` and ``data`` per the output schema.
    """
    action = input_data.get("action", "fetch")
    vault_path = Path(input_data.get("context", {}).get("vault_path", "/app/vault"))

    try:
        if action == "fetch":
            return _fetch(input_data, vault_path)
        elif action == "analyze":
            return {"success": True, "data": {"analyzed_count": 0}}
        elif action == "report":
            return _report(vault_path)
        elif action == "configure":
            return _configure(input_data, vault_path)
        elif action == "list_feeds":
            return _list_feeds(vault_path)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("tendencias skill failed")
        return {"success": False, "error": str(exc)}


def _fetch(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    hours_back = int(input_data.get("hours_back", 24))
    max_items = int(input_data.get("max_items_per_feed", 20))
    keywords = [k.lower() for k in input_data.get("keywords", [])]
    min_score = float(input_data.get("min_relevance_score", 0.3))
    enqueue = input_data.get("enqueue_async", True)

    feeds = input_data.get("feed_urls") or _default_feeds()
    fetched = 0
    relevant = 0
    feeds_processed = []
    raw_items = []

    for feed in feeds:
        url = feed if isinstance(feed, str) else feed.get("url", "")
        title = feed if isinstance(feed, str) else feed.get("name", url)
        items_fetched = 0
        items_relevant = 0
        try:
            import urllib.request
            import xml.etree.ElementTree as ET

            req = urllib.request.Request(url, headers={"User-Agent": "jarvis-os/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode("utf-8", errors="replace")
            root = ET.fromstring(data)
            items = _parse_feed_items(root)
            for item in items[:max_items]:
                score = _relevance(item, keywords)
                if score >= min_score:
                    items_relevant += 1
                    raw_items.append({**item, "score": score, "feed_title": title})
            items_fetched = len(items)
            fetched += items_fetched
            relevant += items_relevant
        except Exception as exc:
            logger.warning("Failed to fetch feed %s: %s", url, exc)

        feeds_processed.append(
            {
                "url": url,
                "title": title,
                "items_fetched": items_fetched,
                "items_relevant": items_relevant,
                "error": None if items_fetched else str(exc),
            }
        )

    sqs_events: list[dict[str, Any]] = []
    if enqueue and raw_items:
        sqs_events.append(
            {
                "queue": "jarvis-async-tasks",
                "message": {"type": "deep_analyze", "items": raw_items[:20]},
                "delay_seconds": 0,
            }
        )

    if raw_items:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = vault_path / "raw" / f"tendencias_{today}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        lines = "\n".join(json.dumps(item, default=str) for item in raw_items)
        out_path.write_text(lines, encoding="utf-8")

    return {
        "success": True,
        "data": {
            "fetched_count": fetched,
            "analyzed_count": 0,
            "enqueued_count": relevant if enqueue else 0,
            "feeds_processed": feeds_processed,
            "top_topics": _top_topics(raw_items),
        },
        "sqs_events": sqs_events,
    }


def _report(vault_path: Path) -> dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "success": True,
        "data": {
            "report_path": f"wiki/tendencias_{today}.md",
            "top_topics": [],
        },
    }


def _configure(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    feeds = input_data.get("feeds", [])
    out_path = vault_path / "wiki" / "tendencias_feeds.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["feeds:"]
    for feed in feeds:
        url = feed.get("url", "")
        name = feed.get("name", url)
        category = feed.get("category", "tech")
        lines.append(f'  - url: "{url}"')
        lines.append(f'    name: "{name}"')
        lines.append(f'    category: "{category}"')
        lines.append("    enabled: true")
        lines.append("    fetch_interval_hours: 6")
    lines.append(f'updated: "{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}"')
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"success": True, "data": {"feeds": feeds}}


def _list_feeds(vault_path: Path) -> dict[str, Any]:
    return {"success": True, "data": {"feeds": _default_feeds()}}


def _default_feeds() -> list[str]:
    return [
        "https://news.ycombinator.com/rss",
        "https://lobste.rs/rss",
        "https://www.reddit.com/r/programming/.rss",
        "https://blog.golang.org/feed.atom",
        "https://rust-lang.org/blog/feed.xml",
        "https://kubernetes.io/blog/feed.xml",
    ]


def _parse_feed_items(root: Any) -> list[dict[str, Any]]:
    items = []
    ns = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}
    for item in root.iter("item"):
        title = _text(item, "title")
        link = _text(item, "link")
        pub = _text(item, "pubDate") or _text(item, "published")
        desc = _text(item, "description") or _text(item, "summary")
        items.append({"title": title, "link": link, "published": pub, "summary": desc})
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title = _text(entry, "{http://www.w3.org/2005/Atom}title")
        link_el = entry.find("{http://www.w3.org/2005/Atom}link[@rel='alternate']")
        link = link_el.get("href") if link_el is not None else ""
        pub = _text(entry, "{http://www.w3.org/2005/Atom}published") or _text(entry, "{http://www.w3.org/2005/Atom}updated")
        desc = _text(entry, "{http://www.w3.org/2005/Atom}summary") or _text(entry, "{http://www.w3.org/2005/Atom}content")
        items.append({"title": title, "link": link, "published": pub, "summary": desc})
    return items


def _text(parent: Any, tag: str) -> str:
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _relevance(item: dict[str, Any], keywords: list[str]) -> float:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    score = 0.1
    for kw in keywords:
        if kw in text:
            score += 0.2
    return min(score, 1.0)


def _top_topics(items: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        title = item.get("title", "").lower()
        for word in title.split():
            if len(word) > 4:
                counts[word] = counts.get(word, 0) + 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"topic": k, "count": v, "avg_relevance": 0.5} for k, v in top]
