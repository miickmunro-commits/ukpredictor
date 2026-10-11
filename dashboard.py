"""Self-contained HTML dashboard generated from the SQLite history."""
import datetime as dt
import html


def _esc(x):
    return html.escape(str(x if x is not None else "—"))


def render(c, all_picks, errors=None, generated=None):
    generated = generated or dt.datetime.now(dt.timezone.utc)
    from core import accuracy, current_params, get_state, history_rows

    n_total, n_hits, acc = accuracy(c)
    acc_str = f"{acc:.1%}" if acc is not None else "—"
    params = current_params(c)
    refit = get_state(c, "refit_info")
    rows = history_rows(c, 60)
    gap_mode = params.get("mode", "gap") == "gap"
    score_hdr = "Table gap" if gap_mode else "Win prob"

    def conf_bar(p):
        w = min(100, int(p * 100))
        color = "#21c55d" if p >= 0.58 else ("#eab308" if p >= 0.52 else "#f97316")
        return (f'<div class="bar"><div class="fill" style="width:{w}%;background:{color}"></div></div>'
                f'<span class="conf">{p:.0%}</span>')

    def sr(side):
        return {"H": "🏠 Home", "A": "✈️ Away", "D": "Draw"}.get(side, side)

    picks_html = ""
    for i, p in enumerate(all_picks, 1):
        picks_html += f"""<tr>
          <td class="c">{i}</td>
          <td><div class="team">{_esc(p['home'])}</div><div class="sub">vs {_esc(p['away'])}</div></td>
          <td class="c"><span class="badge">{_esc(p['league'])}</span></td>
          <td class="c"><b class="pick">{sr(p['side'])}</b><div class="sub">{_esc(p['winner'])}</div></td>
          <td class="c">{conf_bar(p['prob'])}</td>
          <td class="c">#{p['rank_h']} / #{p['rank_a']}</td>
          <td class="c">{'%.2f' % p['ppg_h']} / {'%.2f' % p['ppg_a']}</td>
          <td class="c">{'%d%%' % (p['form_h'] * 100)} / {'%d%%' % (p['form_a'] * 100)}</td>
          <td class="c">{p['rest_h']}d / {p['rest_a']}d</td>
        </tr>"""

    hist_html = ""
    for date, league, home, away, side, prob, actual, ah, aa, mark in rows:
        hist_html += f"""<tr>
          <td>{_esc(date)}</td><td class="c"><span class="badge">{_esc(league)}</span></td>
          <td>{_esc(home)} <span class="sub">v</span> {_esc(away)}</td>
          <td class="c">{sr(side)}</td><td class="c">{'%.0f%%' % (prob * 100)}</td>
          <td class="c">{sr(actual) if actual else '—'}</td>
          <td class="c">{f'{ah}–{aa}' if ah is not None else '—'}</td>
          <td class="c">{mark if mark in ('✓','✗') else '—'}</td>
        </tr>"""

    if gap_mode:
        foot_method = ("pick method: league position only — the ten Saturday 3pm games with the biggest "
                       "gap in the table (as a share of the table, so 100% = top vs bottom), picking the higher team; "
                       "PPG, form and rest are shown for context only")
    else:
        foot_method = ("pick method: Poisson model on this season's goals, recent form and rest days, "
                       "two parameters re-tuned from a backtest")
    err_html = ""
    if errors:
        err_html = '<div class="warn">⚠️ Feed warnings: ' + _esc("; ".join(errors)) + "</div>"

    refit_html = ""
    if refit and not gap_mode:
        refit_html = (f'<div class="chip">Last self-tune: {_esc(refit.get("date"))} — '
                      f'backtest accuracy {refit.get("acc"):.1%} with '
                      f'w_form={refit.get("params", {}).get("w_form")}, '
                      f'shrink={refit.get("params", {}).get("shrink")}</div>')

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UKPredictor — Saturday Top 10</title>
<style>
:root {{ --bg:#0b1220; --card:#111a2e; --line:#1e2a44; --tx:#e6edf7; --mut:#8ba0bf; --grn:#21c55d; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--tx); font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:28px 20px 60px; }}
h1 {{ font-size:26px; margin:0 0 4px; letter-spacing:.2px; }}
h1 span {{ color:#4f8cff; }}
.sub {{ color:var(--mut); font-size:12px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin:20px 0; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 18px; }}
.card .num {{ font-size:30px; font-weight:700; }}
.card .lbl {{ color:var(--mut); font-size:12px; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
th {{ text-align:left; color:var(--mut); font-size:11px; text-transform:uppercase; letter-spacing:.6px; padding:10px 12px; border-bottom:1px solid var(--line); }}
td {{ padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
tr:last-child td {{ border-bottom:none; }}
.c {{ text-align:center; }}
.team {{ font-weight:600; }}
.badge {{ background:#1c2a4a; border:1px solid #2a3c66; border-radius:20px; padding:2px 10px; font-size:11px; color:#c9d9f5; white-space:nowrap; }}
.pick {{ color:var(--grn); }}
.bar {{ display:inline-block; width:70px; height:8px; background:#22304f; border-radius:6px; vertical-align:middle; overflow:hidden; margin-right:6px; }}
.fill {{ height:100%; }}
.conf {{ font-weight:700; }}
.warn {{ background:#3a2a10; border:1px solid #6b4c1a; color:#ffd88a; border-radius:10px; padding:10px 14px; margin:14px 0; }}
.chip {{ background:#0f2a1c; border:1px solid #1f5c3a; color:#9fe8c0; border-radius:10px; padding:8px 14px; margin:8px 0; display:inline-block; }}
h2 {{ font-size:17px; margin:26px 0 10px; }}
.foot {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style></head><body><div class="wrap">
<h1>UK<span>Predictor</span></h1>
<div class="sub">Top 10 UK home / away wins · Saturday 3pm kick-offs only · generated {generated.strftime('%A %d %B %Y, %H:%M %Z')}</div>
{err_html}{refit_html}
<div class="cards">
  <div class="card"><div class="num">{n_total}</div><div class="lbl">Predictions graded</div></div>
  <div class="card"><div class="num">{n_hits}</div><div class="lbl">Correct</div></div>
  <div class="card"><div class="num">{acc_str}</div><div class="lbl">Overall hit rate</div></div>
  <div class="card"><div class="num">{params['top_n']}</div><div class="lbl">Max picks per Saturday</div></div>
  <div class="card"><div class="num">{'Gap' if gap_mode else 'Poisson'}</div><div class="lbl">Pick method</div></div>
</div>
<h2>This Saturday's picks</h2>
<div style="overflow-x:auto"><table>
<tr><th>#</th><th>Match</th><th>League</th><th>Pick</th><th>{score_hdr}</th><th>Table pos</th><th>PPG</th><th>Form L6</th><th>Rest</th></tr>
{picks_html or '<tr><td colspan="9" class="c">No qualifying Saturday 3pm picks this week (runs Friday 09:00).</td></tr>'}
</table></div>
<h2>Prediction history &amp; results</h2>
<div style="overflow-x:auto"><table>
<tr><th>Date</th><th>League</th><th>Match</th><th>Pick</th><th>Gap / prob</th><th>Actual</th><th>Score</th><th>Hit</th></tr>
{hist_html or '<tr><td colspan="8" class="c">No graded predictions yet.</td></tr>'}
</table></div>
<div class="foot">UKPredictor · data: fixturedownload.com full-season feeds (refreshed at run time) · {foot_method} · results graded Monday 10:00.</div>
</div></body></html>"""
