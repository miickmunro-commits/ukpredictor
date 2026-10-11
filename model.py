"""Prediction model: per-league environment, per-team ratings, Poisson match odds.

Every team's attacking/defensive strength is derived from this season's played
matches (goals scored/conceded per game, shrunk toward the league average),
adjusted by recent form (last-6 points), venue (home/away PPG), league position
(rank by points & goal difference) and rest days.  The Poisson model then turns
those strengths into home/draw/away probabilities.
"""
import math


def _poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _poisson_probs(lam_home, lam_away, max_goals=9):
    lam_home = min(max(lam_home, 0.10), 4.5)
    lam_away = min(max(lam_away, 0.10), 4.5)
    ph = pd_ = pa = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = _poisson_pmf(i, lam_home) * _poisson_pmf(j, lam_away)
            if i > j:
                ph += p
            elif i == j:
                pd_ += p
            else:
                pa += p
    s = ph + pd_ + pa
    return ph / s, pd_ / s, pa / s


class LeagueEnv:
    """Everything derived from a league's played matches so far this season."""

    def __init__(self, rows):
        self.played = [r for r in rows if r["hs"] is not None]
        self.teams = set()
        for r in self.played:
            self.teams.add(r["home"])
            self.teams.add(r["away"])
        self.team_rows = {t: [r for r in self.played if r["home"] == t or r["away"] == t]
                          for t in self.teams}
        total_g, total_gf, home_g, home_gf = 0, 0, 0, 0
        for r in self.played:
            total_g += 1
            total_gf += r["hs"] + r["as_"]
            home_g += 1
            home_gf += r["hs"]
        self.avg_goals = (total_gf / total_g) if total_g else 1.3
        self.avg_home_goals = (home_gf / home_g) if home_g else 0.65
        self.avg_away_goals = max(self.avg_goals - self.avg_home_goals, 0.25)

    def build_team(self, team):
        rows = self.team_rows.get(team, [])
        g = len(rows)
        if g == 0:
            return dict(team=team, games=0, pts=0, gf=0, ga=0, gd=0, ppg=1.5, rank=99,
                        form6=0.5, gf_game=1.0, ga_game=1.0, att=1.0, deff=1.0,
                        home_ppg=1.5, away_ppg=1.5, wins=0, losses=0, draws=0, last=None)
        pts = gf = ga = wins = draws = losses = 0
        home_pts = away_pts = home_n = away_n = 0
        for r in rows:
            home = r["home"] == team
            sc, co = (r["hs"], r["as_"]) if home else (r["as_"], r["hs"])
            gf += sc
            ga += co
            if sc > co:
                wins += 1
                pts += 3
                if home:
                    home_pts += 3
            elif sc == co:
                draws += 1
                pts += 1
                if home:
                    home_pts += 1
                else:
                    away_pts += 1
            else:
                losses += 1
                if not home:
                    away_pts += 0
            if home:
                home_n += 1
            else:
                away_n += 1
                away_pts += 3 if sc > co else (1 if sc == co else 0)
        last6 = sorted(rows, key=lambda r: r["date_utc"])[-6:]
        f6 = 0.0
        for r in last6:
            home = r["home"] == team
            sc, co = (r["hs"], r["as_"]) if home else (r["as_"], r["hs"])
            f6 += 3 if sc > co else (1 if sc == co else 0)
        form6 = f6 / (3 * len(last6)) if last6 else 0.5
        home_ppg = home_pts / home_n if home_n else 1.5
        away_ppg = away_pts / away_n if away_n else 1.5
        # pre-compute away draws fix (drawn away games add a point to away_pts)
        return dict(team=team, games=g, pts=pts, gf=gf, ga=ga, gd=gf - ga,
                    ppg=pts / g, rank=99, form6=form6, gf_game=gf / g, ga_game=ga / g,
                    att=(gf / g) / self.avg_goals if g else 1.0,
                    deff=(ga / g) / self.avg_goals if g else 1.0,
                    home_ppg=home_ppg, away_ppg=away_ppg,
                    wins=wins, losses=losses, draws=draws,
                    last=max(r["date_utc"] for r in rows) if rows else None)

    def last_result_vs(self, team, opponent):
        """Season head-to-head for team at home to this opponent: W/D/L string."""
        for r in self.team_rows.get(team, []):
            if r["home"] == team and r["away"] == opponent:
                sc, co = r["hs"], r["as_"]
            elif r["away"] == team and r["home"] == opponent:
                sc, co = r["as_"], r["hs"]
            else:
                continue
            return "W" if sc > co else ("D" if sc == co else "L")
        return None


def compute_ranks(stats):
    """League position by points, then goal difference, then goals scored."""
    ordered = sorted(stats.values(), key=lambda s: (-s["pts"], -s["gd"], -s["gf"]))
    return {s["team"]: i + 1 for i, s in enumerate(ordered)}


def home_advantage(env):
    if not env.played:
        return 0.46, env.avg_home_goals, env.avg_away_goals
    hw = sum(1 for r in env.played if r["hs"] > r["as_"])
    return hw / len(env.played), env.avg_home_goals, env.avg_away_goals


def predict(env, th, ta, params, rest_h=7, rest_a=7):
    """th/ta: home/away team stat dicts. Returns (p_home, p_draw, p_away)."""
    shrink = params.get("shrink", 0.8)
    w_form = params.get("w_form", 0.35)

    def strength(t):
        return 1.0 + (t["att"] - 1.0) * shrink, 1.0 + (t["deff"] - 1.0) * shrink

    att_h, def_h = strength(th)
    att_a, def_a = strength(ta)

    fh = 1.0 + w_form * (th["form6"] - 0.5) * 2.0
    fa = 1.0 + w_form * (ta["form6"] - 0.5) * 2.0
    # short rest slightly depresses performance
    if rest_h < 4:
        fh *= 0.97
    if rest_a < 4:
        fa *= 0.97

    lam_h = env.avg_home_goals * att_h * def_a * fh
    lam_a = env.avg_away_goals * att_a * def_h * fa
    return _poisson_probs(lam_h, lam_a)
