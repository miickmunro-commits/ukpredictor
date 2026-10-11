"""Turn feeds + model into the Saturday top-10 home/away win picks.

Two pick modes, chosen by params["mode"]:
  "gap"     (default) - league positions only: biggest gap in the table,
                        measured as a share of the table, higher team is the pick.
  "poisson"           - the original Poisson model (kept for later comparison).
Both modes only look at Saturday 3pm (UK time) kick-offs.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import model as M

LONDON = ZoneInfo("Europe/London")

LEAGUE_LABEL = {
    "epl": "Premier League", "ch": "Championship", "l1": "League One",
    "l2": "League Two", "spl": "Scottish Premiership",
}

KICKOFF_HOUR = 15  # 3pm UK time (handles BST/GMT automatically)


def next_saturday(now=None):
    """The London-local date of the upcoming Saturday (today if run on Saturday)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ld = now.astimezone(LONDON).date()
    days = (5 - ld.weekday()) % 7
    return ld + dt.timedelta(days=days)


def is_sat_3pm(m, sat):
    """True if this fixture kicks off at 15:00 UK time on the given Saturday."""
    local = m["date_utc"].astimezone(LONDON)
    return local.date() == sat and local.hour == KICKOFF_HOUR and local.minute == 0


def make_picks(feeds, params, now=None):
    """Returns (top_picks, all_picks) using the mode set in params."""
    if params.get("mode", "gap") == "poisson":
        return make_picks_poisson(feeds, params, now=now)
    return make_picks_gap(feeds, params, now=now)


def make_picks_gap(feeds, params, now=None):
    """League positions only. Gap = places apart / (teams in league - 1),
    so 0.0 = neighbours, 1.0 = top vs bottom, comparable across league sizes."""
    now = now or dt.datetime.now(dt.timezone.utc)
    sat = next_saturday(now)
    sat_str = sat.isoformat()
    all_picks = []
    for league, rows in feeds.items():
        env = M.LeagueEnv(rows)
        if not env.teams:
            continue
        stats = {t: env.build_team(t) for t in env.teams}
        ranks = M.compute_ranks(stats)
        # league size from every team in the fixture list, not just those who've played
        n_teams = len({r["home"] for r in rows} | {r["away"] for r in rows})
        if n_teams < 2:
            continue
        for m in rows:
            if m["hs"] is not None:
                continue  # already played
            if not is_sat_3pm(m, sat):
                continue
            th, ta = stats.get(m["home"]), stats.get(m["away"])
            if not th or not ta or th["games"] < 1 or ta["games"] < 1:
                continue  # need at least one played match for both teams
            rh, ra = ranks.get(m["home"], 99), ranks.get(m["away"], 99)
            if rh == ra:
                continue
            side = "H" if rh < ra else "A"
            winner = m["home"] if side == "H" else m["away"]
            gap = abs(rh - ra) / (n_teams - 1)
            fav_share = (min(rh, ra) - 1) / (n_teams - 1)  # tie-break: higher team first
            rest_h = (m["date_utc"] - th["last"]).days if th["last"] else 7
            rest_a = (m["date_utc"] - ta["last"]).days if ta["last"] else 7
            all_picks.append(dict(
                match_key=core_match_key(league, sat_str, m["home"], m["away"]),
                date=sat_str, league=league, home=m["home"], away=m["away"],
                side=side, winner=winner, prob=gap, confidence=round(gap, 4),
                rest_h=max(0, rest_h), rest_a=max(0, rest_a),
                rank_h=rh, rank_a=ra,
                form_h=round(th["form6"], 3), form_a=round(ta["form6"], 3),
                ppg_h=round(th["ppg"], 3), ppg_a=round(ta["ppg"], 3),
                h2h=env.last_result_vs(m["home"], m["away"]) or "—",
                _tiebreak=fav_share, created_at=now.isoformat(),
            ))
    all_picks.sort(key=lambda p: (-p["prob"], p["_tiebreak"]))
    top = all_picks[: params.get("top_n", 10)]
    for p in top:
        p["params"] = params
    return top, all_picks


def make_picks_poisson(feeds, params, now=None):
    """Original Poisson model picks, sorted by win probability."""
    now = now or dt.datetime.now(dt.timezone.utc)
    sat = next_saturday(now)
    sat_str = sat.isoformat()
    all_picks = []
    for league, rows in feeds.items():
        env = M.LeagueEnv(rows)
        if not env.teams:
            continue
        stats = {t: env.build_team(t) for t in env.teams}
        ranks = M.compute_ranks(stats)
        for m in rows:
            if m["hs"] is not None:
                continue  # already played
            if not is_sat_3pm(m, sat):
                continue
            th, ta = stats.get(m["home"]), stats.get(m["away"])
            if not th or not ta or th["games"] < 1 or ta["games"] < 1:
                continue  # need at least one played match for both teams
            rest_h = (m["date_utc"] - th["last"]).days if th["last"] else 7
            rest_a = (m["date_utc"] - ta["last"]).days if ta["last"] else 7
            ph, pd_, pa = M.predict(env, th, ta, params, rest_h, rest_a)
            side = "H" if ph > pa else "A"
            winner = m["home"] if side == "H" else m["away"]
            prob = max(ph, pa)
            if prob < params.get("min_prob", 0.50):
                continue
            h2h = env.last_result_vs(m["home"], m["away"])
            all_picks.append(dict(
                match_key=core_match_key(league, sat_str, m["home"], m["away"]),
                date=sat_str, league=league, home=m["home"], away=m["away"],
                side=side, winner=winner, prob=prob, confidence=round(prob, 4),
                rest_h=max(0, rest_h), rest_a=max(0, rest_a),
                rank_h=ranks.get(m["home"], 99), rank_a=ranks.get(m["away"], 99),
                form_h=round(th["form6"], 3), form_a=round(ta["form6"], 3),
                ppg_h=round(th["ppg"], 3), ppg_a=round(ta["ppg"], 3),
                h2h=h2h or "—", ph=ph, pd=pd_, pa=pa, created_at=now.isoformat(),
            ))
    all_picks.sort(key=lambda p: -p["prob"])
    top = all_picks[: params.get("top_n", 10)]
    for p in top:
        p["params"] = params
    return top, all_picks


def core_match_key(league, date_london, home, away):
    return f"{league}|{date_london}|{home}|{away}"
