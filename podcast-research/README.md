# Podcast keyword research

Scores seed phrases on **demand** (what people type and watch) vs. **competition** (how many podcasts already cover it), using free sources only.

| Column | Source | Meaning |
|---|---|---|
| `google_direct` / `youtube_direct` | Autocomplete | Suggestions (0–10) for the exact phrase. 0 = almost nobody types it. |
| `google_expanded` / `youtube_expanded` | Autocomplete, phrase + a..z | On-topic long-tail phrases found. Breadth of demand. |
| `yt_relevant` | YouTube Data API | Top-25 results whose title actually matches the phrase. |
| `yt_median_views` / `yt_max_views` | YouTube Data API | Views on the matching videos. Proxy for audience size. |
| `yt_recent_share` | YouTube Data API | Share of matching videos published in the last 12 months. |
| `pi_shows` / `pi_active_90d` | Podcast Index | Podcasts matching the phrase / ones that published in the last 90 days. |
| `apple_shows` | Apple Podcasts search | Matching shows (caps at 200; blank if Apple throttled the request). |

None of these are search *volume*. For real volume ranges, export Google Keyword Planner and compare.

## Run

```
# .env (not committed)
YOUTUBE_API_KEY=...
PODCASTINDEX_KEY=...
PODCASTINDEX_SECRET=...

python3 research.py seeds.json --env .env
```

Edit `seeds.json` to change phrases. Results go to `output/` (`keywords.csv`, `suggestions.json`). Responses are cached in `output/cache.json`, so re-runs only fetch new phrases. YouTube's free quota (10k units/day) covers about 90 phrases a day.
