"""Database, grading, backtesting, self-improvement (parameter refitting)."""
import datetime as dt
import itertools
import json
import os
import sqlite3

DEFAULT_PARAMS = {"mode": "gap", "w_form": 0.35, "shrink": 0.8, "min_prob": 0.50, "top_n": 10}
PARAM_GRID = {"w_form": [0.0, 0.25, 0.35, 0.5], "shrink": [0.65, 0.8, 0.95]}

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_key TEXT UNIQUE,
  date TEXT, league TEXT, home TEXT, away TEXT,
  side TEXT, winner TEXT, prob REAL, confidence REAL,
  rest_h INTEGER, rest_a INTEGER, rank_h INTEGER, rank_a INTEGER,
  form_h REAL, form_a REAL, ppg_h REAL, ppg_a REAL, h2h TEXT,
  params TEXT, created_at TEXT,
  graded INTEGER DEFAULT 0, actual_side TEXT,
  actual_home INTEGER, actual_away INTEGER, graded_at TEXT);
CREATE TABLE IF NOT EXISTS model_state(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS accuracy_history(
  batch TEXT, date TEXT, n INTEGER, hits INTEGER, acc REAL, side TEXT);
CREATE TABLE IF NOT EXISTS backtest(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT, n INTEGER, hits INTEGER,
  acc REAL, top10_n INTEGER, top10_hits INTEGER, top10_acc REAL, params TEXT);
"""


def connect(db_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    c = sqlite3.connect(db_path)
    c.executescript(SCHEMA)
    return c


def get_state(c, key, default=None):
    row = c.execute("SELECT v FROM model_state WHERE k=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except Exception:  # noqa: BLE001
        return row[0]


def set_state(c, key, val):
    c.execute("INSERT OR REPLACE INTO model_state(k,v) VALUES(?,?)",
              (key, json.dumps(val) if not isinstance(val, str) else val))
    c.commit()


def current_params(c):
    p = dict(DEFAULT_PARAMS)
    saved = get_state(c, "params")
    if isinstance(saved, dict):
        p.update(saved)
    return p


def match_key(league, date_london, home, away):
    return f"{league}|{date_london}|{home}|{away}"


def save_predictions(c, picks):
    n = 0
    for p in picks:
        try:
            c.execute(
                """INSERT OR IGNORE INTO predictions
                   (match_key,date,league,home,away,side,winner,prob,confidence,
                    rest_h,rest_a,rank_h,rank_a,form_h,form_a,ppg_h,ppg_a,h2h,params,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (p["match_key"], p["date"], p["league"], p["home"], p["away"],
                 p["side"], p["winner"], p["prob"], p["confidence"],
                 p["rest_h"], p["rest_a"], p["rank_h"], p["rank_a"],
                 p["form_h"], p["form_a"], p["ppg_h"], p["ppg_a"], p["h2h"],
                 json.dumps(p["params"]), p["created_at"]),
            )
            n += 1
        except Exception:  # noqa: BLE001
            continue
    c.commit()
    return n


def grade_pending(c, feeds, now=None):
    """Grade stored ungraded predictions against fresh results from the feeds."""
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = c.execute(
        "SELECT id, league, date, home, away FROM predictions WHERE graded=0",
    ).fetchall()
    by_league = {}
    for league, matches in feeds.items():
        by_league[league] = {(r["date_utc"].date().isoformat(), r["home"], r["away"]): r
                             for r in matches if r["hs"] is not None}
    graded = hits = 0
    for pid, league, date, home, away in rows:
        r = by_league.get(league, {}).get((date, home, away))
        if r is None:
            continue
        actual = "H" if r["hs"] > r["as_"] else ("A" if r["as_"] > r["hs"] else "D")
        pred = c.execute("SELECT side FROM predictions WHERE id=?", (pid,)).fetchone()
        hit = 1 if pred and pred[0] == actual else 0
        c.execute(
            "UPDATE predictions SET graded=1, actual_side=?, actual_home=?, actual_away=?, graded_at=? WHERE id=?",
            (actual, r["hs"], r["as_"], now.isoformat(), pid),
        )
        graded += 1
        hits += hit
    c.commit()
    return graded, hits


def record_accuracy(c, batch, graded, hits):
    acc = (hits / graded) if graded else None
    if graded:
        c.execute("INSERT INTO accuracy_history(batch,date,n,hits,acc,side) VALUES(?,?,?,?,?,?)",
                  (batch, dt.date.today().isoformat(), graded, hits, acc, "H/A top10"))
        c.commit()
    return acc


def accuracy(c):
    row = c.execute("SELECT COUNT(*), COALESCE(SUM(hits),0), COALESCE(SUM(n),0) FROM accuracy_history").fetchone()
    n, hits = row[2], row[1]
    return n, hits, (hits / n) if n else None


def history_rows(c, limit=100):
    return c.execute(
        """SELECT date, league, home, away, side, prob, actual_side, actual_home, actual_away,
                  CASE WHEN graded=1 AND side=actual_side THEN '✓' WHEN graded=1 THEN '✗' ELSE '—' END
           FROM predictions ORDER BY id DESC LIMIT ?""", (limit,)
    ).fetchall()


def backtest(c, feeds, params=None, record=True):
    """Predict every played round using ONLY data from earlier rounds, grade the
    picks against the real results. This is how the model is validated and how
    the parameters get re-fitted (self-improvement)."""
    import model as M

    params = params or current_params(c)
    total_n = total_hits = 0
    all_picks = []
    for key, rows in feeds.items():
        played = [r for r in rows if r["hs"] is not None and r["round"] is not None]
        rounds = sorted({r["round"] for r in played})
        for rnd in rounds[1:]:
            prior = [r for r in played if r["round"] < rnd]
            env = M.LeagueEnv(prior)
            if len(env.played) < 4:
                continue
            stats = {t: env.build_team(t) for t in env.teams}
            ranks = M.compute_ranks(stats)
            for m in [r for r in played if r["round"] == rnd]:
                th, ta = stats.get(m["home"]), stats.get(m["away"])
                if not th or not ta or th["games"] < 1 or ta["games"] < 1:
                    continue
                rest_h = (m["date_utc"] - th["last"]).days if th["last"] else 7
                rest_a = (m["date_utc"] - ta["last"]).days if ta["last"] else 7
                ph, _pd, pa = M.predict(env, th, ta, params, rest_h, rest_a)
                side = "H" if ph > pa else "A"
                prob = max(ph, pa)
                if prob < params.get("min_prob", 0.50):
                    continue
                actual = "H" if m["hs"] > m["as_"] else ("A" if m["as_"] > m["hs"] else "D")
                total_n += 1
                total_hits += 1 if side == actual else 0
                all_picks.append((prob, side == actual))
    all_picks.sort(key=lambda x: -x[0])
    top = all_picks[: params.get("top_n", 10)]
    top_hits = sum(1 for p in top if p[1])
    res = dict(n=total_n, hits=total_hits, acc=(total_hits / total_n) if total_n else None,
               top_n=len(top), top_hits=top_hits,
               top_acc=(top_hits / len(top)) if top else None)
    if record:
        c.execute(
            "INSERT INTO backtest(run_at,n,hits,acc,top10_n,top10_hits,top10_acc,params) VALUES(?,?,?,?,?,?,?,?)",
            (dt.datetime.now(dt.timezone.utc).isoformat(), res["n"], res["hits"], res["acc"],
             res["top_n"], res["top_hits"], res["top_acc"], json.dumps(params)))
        c.commit()
    return res


def refit(c, feeds):
    """Grid-search model knobs against the backtest and keep the best scoring set."""
    best, best_acc = None, -1.0
    for wf, sh in itertools.product(PARAM_GRID["w_form"], PARAM_GRID["shrink"]):
        trial = dict(DEFAULT_PARAMS, w_form=wf, shrink=sh)
        res = backtest(c, feeds, params=trial, record=False)
        if res["acc"] is not None and res["acc"] > best_acc:
            best, best_acc = trial, res["acc"]
    if best is None:
        return None
    set_state(c, "params", best)
    set_state(c, "refit_info", {"date": dt.date.today().isoformat(),
                                "acc": best_acc, "params": best})
    return best
