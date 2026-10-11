"""Pipeline: the Friday 09:00 'predict' job and the Monday 10:00 'grade' job."""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import feeds as F
import core
import predictors as P
import dashboard as D


def default_data_dir():
    base = os.environ.get("UKPREDICTOR_DATA")
    if base:
        return base
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/UKPredictor")
    return os.path.expanduser("~/.ukpredictor")


def ensure_layout(data_dir):
    os.makedirs(os.path.join(data_dir, "cache"), exist_ok=True)
    return os.path.join(data_dir, "cache"), os.path.join(data_dir, "app.db")


def fetch():
    data_dir = default_data_dir()
    cache, _db = ensure_layout(data_dir)
    return F.fetch_all(cache=cache, ttl_hours=6)


def run_predict(now=None, data_dir=None):
    """Friday 09:00 — fetch everything, pick the top-10, store, render dashboard."""
    data_dir = data_dir or default_data_dir()
    cache, db_path = ensure_layout(data_dir)
    now = now or dt.datetime.now(dt.timezone.utc)
    feeds, errors = F.fetch_all(now=now, cache=cache, ttl_hours=6)
    c = core.connect(db_path)
    params = core.current_params(c)
    top, all_picks = P.make_picks(feeds, params, now=now)
    n_new = core.save_predictions(c, top)
    generated = now.astimezone(P.LONDON)
    html = D.render(c, top, errors=errors, generated=generated)
    with open(os.path.join(data_dir, "dashboard.html"), "w") as f:
        f.write(html)
    c.close()
    return dict(date=P.next_saturday(now).isoformat(), errors=errors,
                n_new=n_new, n_eligible=len(all_picks), picks=top, db=db_path,
                mode=params.get("mode", "gap"),
                dashboard=os.path.join(data_dir, "dashboard.html"))


def run_grade(now=None, data_dir=None):
    """Monday 10:00 — fetch results, grade stored picks, record accuracy.
    In Poisson mode it also backtests and (with enough data) re-tunes."""
    data_dir = data_dir or default_data_dir()
    cache, db_path = ensure_layout(data_dir)
    now = now or dt.datetime.now(dt.timezone.utc)
    feeds, errors = F.fetch_all(now=now, cache=cache, ttl_hours=6)
    c = core.connect(db_path)
    graded, hits = core.grade_pending(c, feeds, now=now)
    acc = core.record_accuracy(c, f"sat-{dt.date.today().isoformat()}", graded, hits)
    params = core.current_params(c)
    bt = new_params = None
    if params.get("mode", "gap") == "poisson":
        bt = core.backtest(c, feeds, params=params, record=True)
        # Only re-tune once there is a real track record to learn from.
        # Below this, the grid search fits noise and lands on the edge of its grid.
        REFIT_MIN_GRADED = 60
        n_graded = c.execute("SELECT COUNT(*) FROM predictions WHERE graded=1").fetchone()[0]
        new_params = core.refit(c, feeds) if n_graded >= REFIT_MIN_GRADED else None
        if new_params:  # refit builds from defaults, so keep us in Poisson mode
            new_params["mode"] = "poisson"
            core.set_state(c, "params", new_params)
        params = core.current_params(c)
    _top, all_picks = P.make_picks(feeds, params, now=now)
    html = D.render(c, all_picks[: params.get("top_n", 10)], errors=errors, generated=now.astimezone(P.LONDON))
    with open(os.path.join(data_dir, "dashboard.html"), "w") as f:
        f.write(html)
    c.close()
    return dict(graded=graded, hits=hits, acc=acc, backtest=bt,
                refit=new_params, errors=errors, dashboard=os.path.join(data_dir, "dashboard.html"))
