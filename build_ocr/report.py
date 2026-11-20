"""Stage 5: render analysis.json as a single self-contained HTML report.

    python -I report.py --analysis OUT/analysis.json --site ../site --out report.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", type=Path, required=True)
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    a = json.loads(args.analysis.read_text(encoding="utf-8"))
    data = json.loads((args.site / "data.json").read_text(encoding="utf-8"))
    tag_color = {k: v for k, v in data["colors"].items() if isinstance(v, list) and len(v) == 3}
    spell_tags = {s["name"]: s.get("tags", []) for s in data["spells"]}
    item_slot = {e["name"]: e.get("slot") for e in data["equipment"]}
    item_tags = {e["name"]: e.get("tags", []) for e in data["equipment"]}

    def school(tags):
        for t in tags:
            if t.lower() in tag_color and t.lower() not in ("sorcery", "conjuration", "enchantment"):
                return t
        return tags[0] if tags else None

    spells = sorted(a["spells"], key=lambda r: -r["all"][0])[:80]
    for r in spells:
        r["school"] = school(spell_tags.get(r["name"], []))
    items = sorted(a["items"], key=lambda r: -r["all"][0])[:80]
    for r in items:
        r["slot"] = item_slot.get(r["name"])
        r["school"] = school(item_tags.get(r["name"], []))
    pushed = sorted(({"spell": u["spell"], "n": u["n"], "pushed": u["pushed"]} for u in a["upgrades"] if u["n"] >= 30),
                    key=lambda r: -r["pushed"] / r["n"])[:15]
    for ar in a["archetypes"]:
        ar["school"] = school(spell_tags.get(ar["carry"], item_tags.get(ar["carry"], [])))
    payload = {
        "dataset": a["dataset"], "n": a["n_builds"], "spells": spells, "items": items,
        "upgrades": a["upgrades"][:24], "pushed": pushed, "carries": a["carries"][:40],
        "coverage": a["carry_coverage"], "arch_cov": a["archetype_coverage"],
        "archetypes": a["archetypes"], "always": a["always_good"],
        "unattributed": a["unattributed_top"][:10],
        "colors": {k.lower(): "#%02x%02x%02x" % tuple(v) for k, v in tag_color.items()},
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(html) // 1024} KB)")
    return 0


TEMPLATE = r"""<meta charset="utf-8">
<title>Rift Wizard 3 Winning Builds</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Courier+Prime:wght@400;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a field report, one reading column with full-width data tables; school colours mark spells as in game */
:root {
  --bg: #eef0f4; --panel: #ffffff; --ink: #15171c; --muted: #5a6170; --rule: #d6dae2;
  --accent: #5b34c7; --accent-soft: #e9e3fb; --up: #1d7a4a; --down: #b4372b; --bar: #5b34c7; --bar2: #b9a8ee;
  --display: "Courier Prime", "Courier New", ui-monospace, monospace;
  --body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0c0e12; --panel: #14171e; --ink: #e9e7e2; --muted: #9aa1ad; --rule: #272b35;
  --accent: #a990ff; --accent-soft: #241d3d; --up: #5fd39a; --down: #ff8a7a; --bar: #a990ff; --bar2: #4a3d80; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0c0e12; --panel: #14171e; --ink: #e9e7e2; --muted: #9aa1ad; --rule: #272b35;
  --accent: #a990ff; --accent-soft: #241d3d; --up: #5fd39a; --down: #ff8a7a; --bar: #a990ff; --bar2: #4a3d80; color-scheme: dark }
body { background: var(--bg); color: var(--ink); font: 15px/1.55 var(--body); }
.wrap { max-width: 1120px; margin: 0 auto; padding-block: 28px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
h1, h2, h3 { font-family: var(--display); font-weight: 700; text-wrap: balance; margin: 0; }
h1 { font-size: clamp(30px, 5vw, 46px); line-height: 1.05; letter-spacing: -0.01em; }
h2 { font-size: 26px; margin-top: 8px; }
h3 { font-size: 18px; }
p { max-width: 68ch; margin: 0; }
.lede { color: var(--muted); font-size: 16px; }
.eyebrow { font: 500 12px/1 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }
header { display: grid; gap: 14px; padding-bottom: 22px; border-bottom: 1px solid var(--rule); }
nav { display: flex; flex-wrap: wrap; gap: 6px 18px; font: 500 13px var(--mono); }
nav a { color: var(--ink); text-decoration: none; border-bottom: 1px solid var(--rule); }
nav a:hover, nav a:focus-visible { color: var(--accent); border-color: var(--accent); outline: none; }
section { display: grid; gap: 16px; padding-block: 34px 8px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.fact { background: var(--panel); border: 1px solid var(--rule); border-radius: 6px; padding: 12px 14px; display: grid; gap: 2px; }
.fact b { font: 700 26px/1.1 var(--display); }
.fact span { color: var(--muted); font-size: 13px; }
.note { font-size: 13.5px; color: var(--muted); border-left: 3px solid var(--rule); padding: 2px 0 2px 12px; max-width: 80ch; }
.panel { background: var(--panel); border: 1px solid var(--rule); border-radius: 6px; padding: 14px; min-width: 0; }
.controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 5px; overflow: hidden; }
.seg button { font: 500 13px var(--mono); background: transparent; color: var(--muted); border: 0; padding: 6px 11px; cursor: pointer; }
.seg button[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); }
.seg button:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
input[type="search"] { font: 14px var(--body); padding: 6px 10px; border: 1px solid var(--rule); border-radius: 5px; background: var(--panel); color: var(--ink); min-width: 0; width: 220px; max-width: 100%; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th { text-align: left; font: 500 11.5px var(--mono); letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--rule); white-space: nowrap; }
td { padding: 6px 8px; border-bottom: 1px solid var(--rule); vertical-align: middle; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); font-size: 13px; }
tr:last-child td { border-bottom: 0; }
.name { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: none; box-shadow: 0 0 0 1px color-mix(in srgb, var(--ink) 25%, transparent); }
.sub { color: var(--muted); font-size: 12px; }
.barcell { min-width: 120px; }
.bar { height: 8px; border-radius: 2px; background: var(--bar); }
.track { background: color-mix(in srgb, var(--bar) 12%, transparent); border-radius: 2px; }
.pill { font: 500 11px var(--mono); padding: 1px 6px; border-radius: 9px; white-space: nowrap; }
.pill.up { color: var(--up); background: color-mix(in srgb, var(--up) 14%, transparent); }
.pill.down { color: var(--down); background: color-mix(in srgb, var(--down) 14%, transparent); }
svg text { fill: var(--muted); font: 10px var(--mono); }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 480px), 1fr)); gap: 16px; }
.upg { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 330px), 1fr)); gap: 12px; }
.upgcard { background: var(--panel); border: 1px solid var(--rule); border-radius: 6px; padding: 12px; display: grid; gap: 8px; min-width: 0; }
.upgrow { display: grid; grid-template-columns: minmax(0, 1fr) 96px 40px; gap: 8px; align-items: center; font-size: 13px; }
.upgrow .label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arch { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr)); gap: 14px; }
.card { background: var(--panel); border: 1px solid var(--rule); border-radius: 6px; padding: 14px; display: grid; gap: 10px; align-content: start; min-width: 0; border-top: 4px solid var(--school, var(--rule)); }
.card h3 { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
.card h3 small { font: 500 12px var(--mono); color: var(--muted); white-space: nowrap; }
.kv { display: grid; gap: 4px; font-size: 13.5px; }
.kv .k { font: 500 11px var(--mono); letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip { font-size: 12.5px; padding: 2px 7px; border-radius: 4px; background: color-mix(in srgb, var(--ink) 6%, transparent); white-space: nowrap; }
.chip i { font-style: normal; color: var(--muted); font-family: var(--mono); font-size: 11px; margin-left: 4px; }
.card a.guide { font: 500 13px var(--mono); color: var(--accent); text-decoration: none; border: 1px solid color-mix(in srgb, var(--accent) 40%, transparent); padding: 6px 10px; border-radius: 5px; justify-self: start; }
.card a.guide:hover, .card a.guide:focus-visible { background: var(--accent-soft); outline: none; }
details summary { cursor: pointer; font: 500 12.5px var(--mono); color: var(--muted); }
details .members { font: 11.5px/1.6 var(--mono); color: var(--muted); word-break: break-all; max-height: 160px; overflow: auto; margin-top: 6px; }
.stack { display: flex; height: 14px; border-radius: 3px; overflow: hidden; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12.5px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
ul.plain { margin: 0; padding-left: 18px; max-width: 80ch; display: grid; gap: 6px; }
@media (prefers-reduced-motion: no-preference) { .bar { transition: width .25s ease; } }
</style>

<div class="wrap">
<header>
  <div class="eyebrow">Discord #final-builds · OCR'd screenshots</div>
  <h1>Rift Wizard 3 Winning Builds</h1>
  <p class="lede" id="lede"></p>
  <nav aria-label="Sections"><a href="#picks">Pick rates</a><a href="#upgrades">Upgrades</a><a href="#carries">Carries</a><a href="#archetypes">Archetypes</a><a href="#method">Method and limits</a></nav>
</header>

<section id="overview" aria-label="Dataset">
  <div class="facts" id="facts"></div>
  <div class="grid2">
    <div class="panel"><h3>Runs per patch</h3><div id="eraChart"></div></div>
    <div class="panel"><h3>Challenge mix</h3><div id="chalChart"></div></div>
  </div>
  <p class="note">Wins only: nobody posts losses, so nothing here is a win rate. A high number means many winners took it, which mixes strength with popularity. Challenges force or randomise picks, so pick rates lead with normal (no-challenge) runs.</p>
</section>

<section id="picks">
  <div class="eyebrow">1 · What winners take</div>
  <h2>Pick rates</h2>
  <p>Share of winning builds that contain each spell or item. The small chart shows the share in each live patch (normal runs, with 95% intervals); a rising or falling tag appears only when the first and last patch intervals don't overlap.</p>
  <div class="controls">
    <div class="seg" role="group" aria-label="Runs"><button id="b-normal" aria-pressed="true">Normal runs</button><button id="b-all" aria-pressed="false">All runs</button></div>
    <div class="seg" role="group" aria-label="Kind"><button id="b-sp" aria-pressed="true">Spells</button><button id="b-it" aria-pressed="false">Items</button></div>
    <label class="sub" for="q">Filter</label><input type="search" id="q" placeholder="e.g. Fireball">
  </div>
  <div class="panel scroll"><table id="pickTable"></table></div>
</section>

<section id="upgrades">
  <div class="eyebrow">1b · Upgrades</div>
  <h2>Which upgrades winners pick</h2>
  <p>For each common spell: how often each upgrade is taken when the spell has two or fewer upgrades (the player's own choices), and how often the spell was pushed to three or more by the Shrine of Evolution, the Shrine of Perfection or the Codex of Chaotic Evolution. Wild Magic runs and cropped screenshots are left out.</p>
  <div class="panel"><h3>Most often pushed past two upgrades</h3><div id="pushedChart"></div></div>
  <div class="upg" id="upgCards"></div>
</section>

<section id="carries">
  <div class="eyebrow">2 · What did the killing</div>
  <h2>Carries</h2>
  <p>Every run summary lists the final realm's top five damage sources plus "Other". Each source is credited to the spell or item in that build that dealt it: minions go to whatever summoned them, a staff's free spell goes to the staff. <b>Top source</b> is how often it led the list when taken; <b>in top 5</b> is how often it appears at all. A spell that is taken often but rarely in the top five is a support pick, or simply not one of the five biggest sources.</p>
  <div class="panel"><h3>Where final-realm damage was credited</h3><div id="covChart"></div></div>
  <div class="panel scroll"><table id="carryTable"></table></div>
</section>

<section id="archetypes">
  <div class="eyebrow">3 · Builds that win</div>
  <h2>Archetypes</h2>
  <p id="archIntro"></p>
  <div class="arch" id="archCards"></div>
</section>

<section id="method">
  <div class="eyebrow">Method and limits</div>
  <h2>How this was made</h2>
  <ul class="plain" id="methodList"></ul>
</section>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const pct = (k, n, d = 0) => n ? (100 * k / n).toFixed(d) + '%' : '–';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const col = s => (s && D.colors[s.toLowerCase()]) || 'var(--rule)';
const ERAS = Object.keys(D.dataset.by_era);
const fmt = n => n.toLocaleString('en-US');

// ---- header + facts
const ds = D.dataset;
$('lede').textContent = `${fmt(D.n)} winning runs posted between ${ds.first_post} and ${ds.last_post}, read from screenshots of the end-of-run character sheet. Realm 21 victories only; demo wins, mid-run level clears, modded runs and reposts are excluded.`;
const facts = [
  [fmt(D.n), 'unique winning runs'],
  [fmt(ds.normal), 'normal runs (no challenge)'],
  [fmt(D.n - ds.normal), 'Archmage Trial, weekly or custom runs'],
  [fmt(ds.with_damage), 'with a final-realm damage list'],
];
$('facts').innerHTML = facts.map(([b, s]) => `<div class="fact"><b>${b}</b><span>${s}</span></div>`).join('');

// ---- simple horizontal bar chart (SVG, one scale)
function hbars(rows, opt = {}) {
  const w = 460, rh = 22, lw = opt.lw || 150, pad = opt.pad || 60, max = opt.max || Math.max(...rows.map(r => r[1] + (r[2] || 0)));
  const h = rows.length * rh + 18;
  let s = `<svg viewBox="0 0 ${w} ${h}" width="100%" role="img" aria-label="${esc(opt.label || '')}">`;
  rows.forEach(([lab, v, v2], i) => {
    const y = i * rh + 4, bw = (w - lw - pad) * v / max, bw2 = v2 ? (w - lw - pad) * v2 / max : 0;
    s += `<text x="${lw - 6}" y="${y + 13}" text-anchor="end">${esc(lab)}</text>`;
    s += `<rect x="${lw}" y="${y + 3}" width="${Math.max(bw, 1)}" height="12" rx="2" fill="var(--bar)"></rect>`;
    if (v2) s += `<rect x="${lw + bw}" y="${y + 3}" width="${bw2}" height="12" rx="2" fill="var(--bar2)"></rect>`;
    s += `<text x="${lw + bw + bw2 + 5}" y="${y + 13}">${opt.f ? opt.f(v, v2) : fmt(v + (v2 || 0))}</text>`;
  });
  return s + '</svg>';
}
$('eraChart').innerHTML = hbars(ERAS.map(e => [e + ' patch', ds.by_era[e].normal, ds.by_era[e].all - ds.by_era[e].normal]),
  {label: 'Runs per patch', lw: 110, pad: 130, f: (a, b) => `${fmt(a + b)} (${fmt(a)} normal)`}) +
  `<div class="legend"><span><i class="sw" style="background:var(--bar)"></i>normal</span><span><i class="sw" style="background:var(--bar2)"></i>with a challenge</span></div>`;
const ch = ds.challenges.slice(0, 12);
$('chalChart').innerHTML = hbars(ch.map(([n, k]) => [n, k]), {label: 'Challenge runs', lw: 150});

// ---- era sparkline with intervals
function spark(eras) {
  const vals = ERAS.map(e => eras[e]);
  const valid = vals.filter(Boolean);
  if (!valid.length) return '';
  const max = Math.max(0.05, ...valid.map(v => v[3]));
  const w = 112, h = 30, px = i => 8 + i * (w - 16) / (ERAS.length - 1), py = v => h - 4 - (h - 8) * v / max;
  let s = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">`;
  s += `<line x1="4" x2="${w - 4}" y1="${h - 4}" y2="${h - 4}" stroke="var(--rule)"></line>`;
  let path = '';
  vals.forEach((v, i) => {
    if (!v) return;
    const r = v[0] / v[1];
    s += `<line x1="${px(i)}" x2="${px(i)}" y1="${py(v[2])}" y2="${py(v[3])}" stroke="var(--bar2)" stroke-width="3" stroke-linecap="round"></line>`;
    path += (path ? 'L' : 'M') + px(i) + ',' + py(r);
  });
  s += `<path d="${path}" fill="none" stroke="var(--bar)" stroke-width="1.5"></path>`;
  vals.forEach((v, i) => { if (v) s += `<circle cx="${px(i)}" cy="${py(v[0] / v[1])}" r="2.4" fill="var(--bar)"></circle>`; });
  return s + '</svg>';
}

// ---- pick table
let mode = 'normal', kind = 'sp';
function renderPicks() {
  const q = $('q').value.trim().toLowerCase();
  let rows = (kind === 'sp' ? D.spells : D.items).filter(r => !q || r.name.toLowerCase().includes(q));
  rows = rows.slice().sort((a, b) => b[mode][0] / b[mode][1] - a[mode][0] / a[mode][1]).slice(0, q ? 80 : 40);
  const top = Math.max(...rows.map(r => r[mode][0] / r[mode][1]), 0.01);
  const eraHead = ERAS.map(e => e).join(' · ');
  $('pickTable').innerHTML = `<thead><tr><th>#</th><th>${kind === 'sp' ? 'Spell' : 'Item'}</th><th class="num">${mode === 'normal' ? 'Normal' : 'All'} runs</th><th class="barcell"></th><th>By patch <span class="sub">(${eraHead})</span></th><th></th></tr></thead><tbody>` +
    rows.map((r, i) => {
      const [k, n] = r[mode], share = k / n;
      const extra = kind === 'sp' ? (r.level ? `level ${r.level}` : '') + (r.granted_by ? ` · from ${esc(r.granted_by)}` : '') : (r.slot || '');
      const trend = r.trend ? `<span class="pill ${r.trend}">${r.trend === 'up' ? 'rising' : 'falling'}</span>` : '';
      return `<tr><td class="num">${i + 1}</td><td><div class="name"><span class="dot" style="background:${col(r.school)}"></span><span>${esc(r.name)}</span><span class="sub">${extra}</span></div></td>` +
        `<td class="num">${pct(k, n, 1)}<div class="sub">${fmt(k)} / ${fmt(n)}</div></td>` +
        `<td class="barcell"><div class="track"><div class="bar" style="width:${(100 * share / top).toFixed(1)}%"></div></div></td>` +
        `<td>${spark(r.eras)}</td><td>${trend}</td></tr>`;
    }).join('') + '</tbody>';
}
function press(on, off) { on.setAttribute('aria-pressed', 'true'); off.setAttribute('aria-pressed', 'false'); }
$('b-normal').onclick = () => { mode = 'normal'; press($('b-normal'), $('b-all')); renderPicks(); };
$('b-all').onclick = () => { mode = 'all'; press($('b-all'), $('b-normal')); renderPicks(); };
$('b-sp').onclick = () => { kind = 'sp'; press($('b-sp'), $('b-it')); renderPicks(); };
$('b-it').onclick = () => { kind = 'it'; press($('b-it'), $('b-sp')); renderPicks(); };
$('q').oninput = renderPicks;
renderPicks();

// ---- upgrades
$('pushedChart').innerHTML = hbars(D.pushed.map(r => [r.spell, r.pushed / r.n]), {label: 'Spells pushed past two upgrades', lw: 170, max: Math.max(...D.pushed.map(r => r.pushed / r.n)), f: v => (100 * v).toFixed(0) + '%'});
$('upgCards').innerHTML = D.upgrades.slice(0, 18).map(u => {
  const rows = u.take.filter(([, k]) => k > 0).slice(0, 5);
  const max = Math.max(1, ...rows.map(([, k]) => k));
  return `<div class="upgcard"><h3>${esc(u.spell)}</h3><div class="sub">${fmt(u.n)} builds · ${pct(u.pushed, u.n)} pushed to 3+ · ${pct(u.none, u.n)} with no upgrades</div>` +
    rows.map(([name, k]) => `<div class="upgrow"><span class="label" title="${esc(name)}">${esc(name)}</span><div class="track"><div class="bar" style="width:${(100 * k / max).toFixed(0)}%"></div></div><span class="num sub">${pct(k, u.chosen_n)}</span></div>`).join('') + '</div>';
}).join('');

// ---- carries
const cov = D.coverage, covKeys = [['spell', 'credited to a spell', 'var(--bar)'], ['item', 'credited to an item', 'var(--bar2)'], ['other', '"Other" bucket', '#8f97a6'], ['monster', 'monster names, not traced', '#c9a35a'], ['unattributed', 'unknown source', '#d47a6a'], ['enemy', 'enemies hurting enemies (excluded)', '#6b7280'], ['status', 'statuses', '#5aa58a']];
$('covChart').innerHTML = `<div class="stack" role="img" aria-label="Damage attribution">` + covKeys.map(([k, , c]) => `<div style="width:${(100 * (cov[k] || 0)).toFixed(2)}%;background:${c}" title="${k}"></div>`).join('') + '</div>' +
  `<div class="legend" style="margin-top:8px">` + covKeys.map(([k, l, c]) => `<span><i class="sw" style="background:${c}"></i>${l} ${(100 * (cov[k] || 0)).toFixed(0)}%</span>`).join('') + '</div>';
const cmax = Math.max(...D.carries.map(r => r.top_rate));
$('carryTable').innerHTML = `<thead><tr><th>Source</th><th class="num">Builds with it</th><th class="num">Top source</th><th class="barcell">Top-source rate</th><th class="num">In top 5</th><th class="num">Median share</th></tr></thead><tbody>` +
  D.carries.map(r => `<tr><td><div class="name"><span>${esc(r.name)}</span><span class="sub">${r.kind}</span></div></td><td class="num">${fmt(r.present)}</td><td class="num">${fmt(r.top)}</td>` +
    `<td class="barcell"><div class="track"><div class="bar" style="width:${(100 * r.top_rate / cmax).toFixed(0)}%"></div></div><span class="sub">${pct(r.top, r.present)}</span></td>` +
    `<td class="num">${(100 * r.in_top5_rate).toFixed(0)}%</td><td class="num">${(100 * r.median_share).toFixed(0)}%</td></tr>`).join('') + '</tbody>';

// ---- archetypes
const ac = D.arch_cov;
$('archIntro').innerHTML = `Each build is labelled by its biggest damage source on the final realm, when that source dealt at least 35% of the listed damage (${fmt(ac.clear_carry)} of ${fmt(ac.with_damage)} runs; the other ${fmt(ac.mixed)} spread their damage). Groups with at least 15 runs are shown, ${fmt(ac.in_listed_groups)} runs in all. <b>Core</b> spells and items are much more common in the group than overall (lift ≥ 1.5×); <b>common</b> ones appear in at least a fifth of the group without being special to it. Upgrade rates include the third and fourth upgrades, which carries often reach. Each card opens as a guide in the compendium.`;
const chip = (name, p, lift) => `<span class="chip">${esc(name)}<i>${Math.round(100 * p)}%${lift ? ' · ' + lift.toFixed(1) + '×' : ''}</i></span>`;
$('archCards').innerHTML = D.archetypes.map(a => {
  const chal = a.challenges.map(([c, k]) => `${c === 'none' ? 'normal' : esc(c)} ${k}`).join(' · ');
  const carryUp = (a.upgrades[a.carry] || []).slice(0, 5);
  const otherUps = Object.entries(a.upgrades).filter(([s]) => s !== a.carry).slice(0, 2);
  return `<article class="card" style="--school:${col(a.school)}">
    <h3><span>${esc(a.carry)}</span><small>${a.kind} · ${a.n} runs</small></h3>
    <div class="sub">median ${Math.round(100 * a.median_damage_share)}% of final-realm damage · ${chal}</div>
    ${carryUp.length ? `<div class="kv"><span class="k">${esc(a.carry)} upgrades</span><div class="chips">${carryUp.map(([u, p]) => chip(u, p)).join('')}</div></div>` : ''}
    <div class="kv"><span class="k">Core spells</span><div class="chips">${a.core_spells.filter(([s]) => s !== a.carry).map(([s, p, l]) => chip(s, p, l)).join('') || '<span class="sub">nothing beyond the carry</span>'}</div></div>
    ${otherUps.map(([s, ups]) => `<div class="kv"><span class="k">${esc(s)} upgrades</span><div class="chips">${ups.slice(0, 4).map(([u, p]) => chip(u, p)).join('')}</div></div>`).join('')}
    <div class="kv"><span class="k">Core items</span><div class="chips">${a.core_items.filter(([s]) => s !== a.carry).map(([s, p, l]) => chip(s, p, l)).join('') || '<span class="sub">none stand out</span>'}</div></div>
    ${(a.utility_spells.length || a.utility_items.length) ? `<div class="kv"><span class="k">Common, not special</span><div class="chips">${a.utility_spells.concat(a.utility_items).map(([s, p]) => chip(s, p)).join('')}</div></div>` : ''}
    <a class="guide" href="${esc(a.guide)}" target="_blank" rel="noopener">Open as compendium guide ↗</a>
    ${a.not_in_compendium.length ? `<div class="sub">Not in the compendium, so left out of the guide: ${a.not_in_compendium.map(esc).join(', ')}</div>` : ''}
    <details><summary>${a.members.length} screenshots</summary><div class="members">${a.members.map(esc).join('<br>')}</div></details>
  </article>`;
}).join('');

// ---- method
const un = D.unattributed.map(([n, k]) => `${esc(n)} (${k})`).join(', ');
$('methodList').innerHTML = [
  `Screenshots came from a Chrome network capture of the channel, ${fmt(2872)} images in total. They were read with RapidOCR and parsed against the compendium's spell, upgrade and item lists. On 22 hand-checked images every spell, upgrade and item was read correctly.`,
  `A run counts once even when its character sheet and map screenshot were posted together or it was reposted. The ${ds.assumed_victory} runs that show a realm 21 character sheet before the win screen are counted as wins.`,
  `Patches are assigned by posting date, using the dates the compendium recorded each live build. A player can post days after playing, so the boundaries are approximate. A spell or item is only compared over patches it existed in.`,
  `Carries use the final realm only, and only its top five sources. A source missing from the list may still have dealt damage.`,
  `Damage that could not be traced to the build: ${un}. These are mostly monsters' own attacks and minions summoned by other minions.`,
  `No poster names were captured, so one prolific player can tilt a small archetype. Check the screenshot list on each card.`,
].map(t => `<li>${t}</li>`).join('');
</script>
"""

if __name__ == "__main__":
    raise SystemExit(main())
