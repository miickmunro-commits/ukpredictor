"""Data feeds for UK football (Premier League, Championship, League One,
League Two, Scottish Premiership) from fixturedownload.com JSON feeds.
Source verified: full-season fixtures/results per league, one feed each.
"""
import datetime as dt
import json
import os
import urllib.request
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
BASE = "https://fixturedownload.com/feed/json/"

# league_key, display name, country, feed stem
LEAGUES = [
    ("epl", "Premier League", "England", "epl"),
    ("ch", "Championship", "England", "championship"),
    ("l1", "League One", "England", "efl-league-one"),
    ("l2", "League Two", "England", "efl-league-two"),
    ("spl", "Scottish Premiership", "Scotland", "scottish-premiership"),
]
LEAGUE_NAMES = {k: n for k, n, _, _ in LEAGUES}
LEAGUE_COUNTRIES = {k: c for k, c, _, _ in LEAGUES}


def season_year(now=None):
    now = now or dt.datetime.now()
    y = now.year
    return y if now.month >= 7 else y - 1


def _get_json(url, timeout=45):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def fetch_league(key, stem, now=None, cache=None, ttl_hours=6):
    """Fetch one league feed. Returns list of match dicts sorted by kickoff."""
    now = now or dt.datetime.now(dt.timezone.utc)
    year = season_year(now)
    data = None
    errors = []
    for y in (year, year + 1):
        url = f"{BASE}{stem}-{y}"
        try:
            if cache:
                p = os.path.join(cache, f"{key}-{y}.json")
                if os.path.exists(p) and ttl_hours > 0:
                    age = (dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(p)))
                    if age < dt.timedelta(hours=ttl_hours):
                        with open(p) as f:
                            data = json.load(f)
                        break
            if data is None:
                data = _get_json(url)
                if cache:
                    os.makedirs(cache, exist_ok=True)
                    with open(os.path.join(cache, f"{key}-{y}.json"), "w") as f:
                        json.dump(data, f)
            break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{stem}-{y}: {e}")
    if data is None:
        raise RuntimeError(f"feed unavailable for {key}: {'; '.join(errors)}")

    out = []
    for row in data or []:
        hs, aws = row.get("HomeTeamScore"), row.get("AwayTeamScore")
        try:
            date_utc = parse_date(row.get("DateUtc"))
        except Exception:  # noqa: BLE001
            continue
        if date_utc is None:
            continue
        # a match is only 'played' if kickoff is in the past AND the feed has scores
        played = hs not in (None, "") and aws not in (None, "") and date_utc <= now + dt.timedelta(hours=6)
        if not played:
            hs, aws = None, None
        else:
            try:
                hs, aws = int(hs), int(aws)
            except Exception:  # noqa: BLE001
                hs, aws = None, None
        out.append(
            dict(
                key=key,
                date_utc=date_utc,
                home=(row.get("HomeTeam") or "").strip(),
                away=(row.get("AwayTeam") or "").strip(),
                hs=hs,
                as_=aws,
                round=row.get("RoundNumber"),
                match=int(row.get("MatchNumber") or 0),
            )
        )
    out.sort(key=lambda r: r["date_utc"])
    return out


def fetch_all(now=None, cache=None, ttl_hours=6):
    """Returns (feeds, errors) where feeds maps league_key -> match list."""
    now = now or dt.datetime.now(dt.timezone.utc)
    feeds, errors = {}, []
    for key, _name, _country, stem in LEAGUES:
        try:
            feeds[key] = fetch_league(key, stem, now=now, cache=cache, ttl_hours=ttl_hours)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{key}: {e}")
            feeds[key] = []
    return feeds, errors
