#!/usr/bin/env python3
"""Podcast keyword research: demand vs. competition for a list of seed phrases.

Sources (all free):
  - Google + YouTube autocomplete (no key)       -> what people actually type
  - YouTube Data API (YOUTUBE_API_KEY)           -> views on the top videos for a phrase
  - Podcast Index API (PODCASTINDEX_KEY/SECRET)  -> how many podcasts already match
  - Apple Podcasts search (no key)               -> how many Apple shows match (caps at 200)

Usage:
  python3 research.py [seeds.json] [--env path/to/.env] [--no-expand]
Outputs land in ./output/.
"""
import argparse
import csv
import hashlib
import json
import os
import statistics
import string
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

UA = "RondoPodcastResearch/0.1 (dylandrake@rondoproduction.com)"
HERE = Path(__file__).parent
OUT = HERE / "output"
CACHE_FILE = OUT / "cache.json"

session = requests.Session()
session.headers["User-Agent"] = UA
_cache = {}


def load_env(path):
    if path and Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
        time.sleep(0.12)
    return _cache[key]


def get_json(url, params=None, headers=None):
    for attempt in range(3):
        r = session.get(url, params=params, headers=headers, timeout=20)
        if r.status_code == 429:
            time.sleep(2 ** (attempt + 2))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


# ---------- autocomplete ----------

def suggest(q, ds=""):
    params = {"client": "firefox", "q": q, "hl": "en", "gl": "us"}
    if ds:
        params["ds"] = ds
    data = cached(f"sug:{ds}:{q}", lambda: get_json(
        "https://suggestqueries.google.com/complete/search", params))
    return [s for s in data[1] if s.lower() != q.lower()]


def expand(seed, ds):
    """Seed + seed a..z, deduped. Breadth of this set is a demand proxy."""
    found = []
    for q in [seed] + [f"{seed} {c}" for c in string.ascii_lowercase]:
        for s in suggest(q, ds):
            if s not in found:
                found.append(s)
    return found


# ---------- YouTube ----------

def youtube(seed):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return {}

    def run():
        search = get_json("https://www.googleapis.com/youtube/v3/search", {
            "part": "id", "q": seed, "type": "video", "maxResults": 25,
            "regionCode": "US", "relevanceLanguage": "en", "key": key})
        ids = [i["id"]["videoId"] for i in search.get("items", [])]
        if not ids:
            return []
        vids = get_json("https://www.googleapis.com/youtube/v3/videos", {
            "part": "statistics,snippet", "id": ",".join(ids), "key": key})["items"]
        return [{"title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                 "views": int(v["statistics"].get("viewCount", 0))} for v in vids]
    vids = cached(f"ytraw:{seed}", run)

    # Only count videos whose title actually matches the phrase; YouTube happily
    # returns "founder of Christianity" for "christian founder".
    relevant = [v for v in vids if is_relevant(seed, v["title"])]
    views = [v["views"] for v in relevant]
    cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    recent = sum(1 for v in relevant
                 if datetime.fromisoformat(v["published"].replace("Z", "+00:00")) > cutoff)
    top = sorted(relevant, key=lambda v: -v["views"])[:3]
    return {
        "yt_relevant": f"{len(relevant)}/{len(vids)}",
        "yt_median_views": int(statistics.median(views)) if views else 0,
        "yt_max_views": max(views, default=0),
        "yt_recent_share": round(recent / len(relevant), 2) if relevant else 0,
        "yt_top_titles": [f'{v["title"]} ({v["views"]:,})' for v in top],
    }


STOP = {"a", "an", "the", "to", "for", "my", "your", "of", "and", "how", "on", "in", "is", "i"}


def is_relevant(seed, text):
    """Every meaningful seed word appears in the text (prefix match handles plurals/-ing)."""
    words = [w for w in text.lower().replace("-", " ").split()]
    for token in seed.lower().split():
        if token in STOP:
            continue
        stem = token[:max(4, len(token) - 2)]
        if not any(w.strip("#:,.!?()'\"|").startswith(stem) for w in words):
            return False
    return True


# ---------- Podcast Index ----------

def podcastindex(seed):
    k, s = os.environ.get("PODCASTINDEX_KEY"), os.environ.get("PODCASTINDEX_SECRET")
    if not (k and s):
        return {}

    def run():
        t = str(int(time.time()))
        h = {"X-Auth-Key": k, "X-Auth-Date": t,
             "Authorization": hashlib.sha1((k + s + t).encode()).hexdigest()}
        d = get_json("https://api.podcastindex.org/api/1.0/search/byterm",
                     {"q": seed, "max": 1000}, h)
        feeds = d.get("feeds", [])
        cutoff = time.time() - 90 * 86400
        active = [f for f in feeds if (f.get("newestItemPubdate") or 0) > cutoff]
        return {
            "pi_shows": d.get("count", len(feeds)),
            "pi_active_90d": len(active),
            "pi_top_shows": [f["title"] for f in active[:5]],
        }
    return cached(f"pi:{seed}", run)


# ---------- Apple ----------

def apple(seed):
    """Best effort: Apple throttles hard (403) from some IPs."""
    def run():
        d = get_json("https://itunes.apple.com/search",
                     {"term": seed, "entity": "podcast", "limit": 200, "country": "US"})
        return {"apple_shows": d.get("resultCount", 0)}
    try:
        return cached(f"ap:{seed}", run)
    except requests.HTTPError:
        return {"apple_shows": ""}


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", nargs="?", default=str(HERE / "seeds.json"))
    ap.add_argument("--env", default=str(HERE / ".env"))
    ap.add_argument("--no-expand", action="store_true", help="skip a..z autocomplete expansion")
    args = ap.parse_args()

    load_env(args.env)
    OUT.mkdir(exist_ok=True)
    global _cache
    if CACHE_FILE.exists():
        _cache = json.loads(CACHE_FILE.read_text())

    clusters = json.loads(Path(args.seeds).read_text())
    rows, suggestions = [], {}
    try:
        for cluster, seeds in clusters.items():
            for seed in seeds:
                print(f"[{cluster}] {seed}", file=sys.stderr)
                g_direct, y_direct = suggest(seed), suggest(seed, "yt")
                g_all = g_direct if args.no_expand else expand(seed, "")
                y_all = y_direct if args.no_expand else expand(seed, "yt")
                # Expansion pulls in noise ("christian dior founder"); keep only on-topic phrases.
                g_all = [x for x in g_all if is_relevant(seed, x)]
                y_all = [x for x in y_all if is_relevant(seed, x)]
                row = {"cluster": cluster, "seed": seed,
                       "google_direct": len(g_direct), "youtube_direct": len(y_direct),
                       "google_expanded": len(g_all), "youtube_expanded": len(y_all)}
                row.update(youtube(seed))
                row.update(podcastindex(seed))
                row.update(apple(seed))
                rows.append(row)
                suggestions[seed] = {"google": g_all, "youtube": y_all}
    finally:
        CACHE_FILE.write_text(json.dumps(_cache))

    cols = ["cluster", "seed", "google_direct", "google_expanded", "youtube_direct",
            "youtube_expanded", "yt_relevant", "yt_median_views", "yt_max_views", "yt_recent_share",
            "pi_shows", "pi_active_90d", "apple_shows", "yt_top_titles", "pi_top_shows"]
    with open(OUT / "keywords.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "yt_top_titles": " | ".join(r.get("yt_top_titles", [])),
                        "pi_top_shows": " | ".join(r.get("pi_top_shows", []))})
    (OUT / "keywords.json").write_text(json.dumps(rows, indent=2))
    (OUT / "suggestions.json").write_text(json.dumps(suggestions, indent=2))
    print(f"wrote {len(rows)} rows to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
