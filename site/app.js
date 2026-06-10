'use strict';

let DATA = null;
let COLORS = {};
let TAGCOLOR = {};        // Tag name -> "rgb(...)"
let COMPONENT_TAGS = [];  // recipe-able tags excluding "Any"
let IV = '';              // (unused) icon URL suffix; kept empty — caching handled by the host

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
const esc = s => (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const rgb = c => Array.isArray(c) ? `rgb(${c[0]},${c[1]},${c[2]})` : c;

// ---------------------------------------------------------------------------
// Markup rendering: [name:colorkey] and [name] -> colored span
// ---------------------------------------------------------------------------
const MARKUP_RE = /\[([^\]:]+)(?::([^\]]+))?\]/g;
function colorFor(key) {
  if (!key) return null;
  const k = String(key).toLowerCase();
  if (COLORS[k]) return rgb(COLORS[k]);
  return null;
}
function renderMarkup(str) {
  if (!str) return '';
  let out = '', last = 0, m;
  MARKUP_RE.lastIndex = 0;
  while ((m = MARKUP_RE.exec(str)) !== null) {
    out += esc(str.slice(last, m.index));
    last = m.index + m[0].length;
    const name = m[1];
    const key = m[2] != null ? m[2] : name;
    const col = colorFor(key);
    const text = name.replace(/_/g, ' ');
    if (col) out += `<span style="color:${col};font-weight:600">${esc(text)}</span>`;
    else out += `<span style="font-weight:600">${esc(text)}</span>`;
  }
  out += esc(str.slice(last));
  return out.replace(/\n/g, '<br>');
}

// ---------------------------------------------------------------------------
// Small UI builders
// ---------------------------------------------------------------------------
function tagPill(name) {
  const col = TAGCOLOR[name] || 'var(--muted)';
  return `<span class="tag-pill" style="color:${col}">${esc(name)}</span>`;
}
function iconImg(cat, item) {
  if (item.has_icon === false) {
    return `<div class="icon placeholder">✦</div>`;
  }
  return `<img class="icon" loading="lazy" src="icons/${cat}/${esc(item.icon)}${IV}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'icon placeholder',textContent:'✦'}))">`;
}

function recipeChips(recipe) {
  return recipe.map(([tag, n]) => {
    if (tag === 'Any') return `<span class="req any"><span class="n">${n}×</span> Any</span>`;
    const col = TAGCOLOR[tag] || 'var(--muted)';
    return `<span class="req" style="color:${col}"><span class="n">${n}×</span> ${esc(tag)}</span>`;
  }).join('');
}

// --- Summoned-unit stat sheets ---------------------------------------------
let UNITS = {};
// A unit's icon is a spritesheet; show its looping idle animation (last row of
// frames) in pure CSS via background-position. ctxClass supplies the size (--d).
function unitSprite(u, ctxClass) {
  if (!u) return `<div class="sprite ${ctxClass}"></div>`;
  const cols = u.cols || 1, rows = u.rows || 1;
  const anim = cols > 1 ? ' c' + cols : '';
  return `<div class="sprite ${ctxClass}${anim}" style="--cols:${cols};--rows:${rows};background-image:url(icons/units/${esc(u.icon)})"></div>`;
}
function summonRow(summons) {
  if (!summons || !summons.length) return '';
  const chips = summons.map(n => `<span class="summon-chip" data-unit="${esc(n)}" tabindex="0">${unitSprite(UNITS[n], 'chip-sprite')}${esc(n)}</span>`).join('');
  return `<div class="summon-row"><span class="section-label">Summons</span><div class="summon-chips">${chips}</div></div>`;
}
// One steps() keyframe per distinct idle-frame count (idle loops at 5fps).
function injectSpriteKeyframes() {
  const counts = new Set(Object.values(UNITS).map(u => u.cols || 1).filter(c => c > 1));
  let css = '';
  for (const n of counts) {
    css += `@keyframes spr${n}{to{background-position-x:calc(${n} * var(--d) * -1)}}`;
    css += `.sprite.c${n}{animation:spr${n} ${(n * 0.2).toFixed(1)}s steps(${n}) infinite}`;
  }
  const st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);
}
function renderUnitSheet(name) {
  const u = UNITS[name];
  if (!u) return `<div class="unit-sheet"><div class="uname">${esc(name)}</div><div class="udesc">No stat sheet available.</div></div>`;
  const hp = u.hp ? `${u.hp} HP` : 'HP varies';
  const flags = [u.flying && 'Flying', u.stationary && 'Immobile', u.burrowing && 'Burrowing'].filter(Boolean);
  const resists = Object.entries(u.resists).sort((a, b) => b[1] - a[1])
    .map(([t, v]) => `<span class="ures" style="color:${TAGCOLOR[t] || 'var(--muted)'}">${v > 0 ? '' : ''}${v}% ${esc(t)}</span>`).join('');
  const abilities = u.abilities.map(a => {
    const bits = [];
    if (a.damage) bits.push(`<span class="udmg">${a.damage}${a.damage_type ? ' ' + a.damage_type.join('/') : ''} dmg</span>`);
    if (a.range && a.range > 1.5) bits.push(`rng ${Math.round(a.range)}`);
    else if (a.melee) bits.push('melee');
    if (a.radius) bits.push(`rad ${a.radius}`);
    if (a.cool_down) bits.push(`cd ${a.cool_down}`);
    if (a.hp_cost) bits.push(`${a.hp_cost} hp`);
    if (a.quick_cast) bits.push('quick');
    return `<div class="uab"><span class="uabn">${esc(a.name)}</span>${bits.length ? ` <span class="ubits">${bits.join(' · ')}</span>` : ''}${a.desc ? `<div class="udesc">${renderMarkup(a.desc)}</div>` : ''}</div>`;
  }).join('');
  const passives = u.passives.map(p => `<div class="upass">${renderMarkup(p)}</div>`).join('');
  return `<div class="unit-sheet">
    <div class="uhead">
      ${unitSprite(u, 'uicon-sprite')}
      <div class="uhmeta">
        <div class="uname">${esc(u.name)}</div>
        <div class="card-meta">${u.tags.map(tagPill).join('')}</div>
      </div>
    </div>
    <div class="uline"><span class="uhp">❤ ${hp}</span>${u.shields ? `<span class="ush">◆ ${u.shields} SH</span>` : ''}${flags.length ? `<span class="uflags">${flags.join(' · ')}</span>` : ''}</div>
    ${resists ? `<div class="uresists">${resists}</div>` : ''}
    ${abilities ? `<div class="usec">Abilities</div>${abilities}` : ''}
    ${passives ? `<div class="usec">Passives</div>${passives}` : ''}
  </div>`;
}

// Shared floating tooltip
let unitTip = null;
let DRAGGING = false;   // suppress hover tooltips while a component is being dragged
function ensureTip() {
  if (!unitTip) { unitTip = el('div', 'unit-tip'); unitTip.style.display = 'none'; document.body.appendChild(unitTip); }
  return unitTip;
}
function positionTip(x, y) {
  const t = unitTip, pad = 8, gap = 14;
  const w = t.offsetWidth, h = t.offsetHeight;
  let nx = x + gap, ny = y + gap;
  if (nx + w > window.innerWidth - pad) nx = x - w - gap;
  if (nx < pad) nx = pad;
  if (ny + h > window.innerHeight - pad) ny = window.innerHeight - h - pad;
  if (ny < pad) ny = pad;
  t.style.left = nx + 'px'; t.style.top = ny + 'px';
}
function showTip(html, x, y) {
  if (DRAGGING) return;
  const t = ensureTip();
  t.innerHTML = html;
  t.style.display = 'block';
  positionTip(x, y);
}
function hideTip() { if (unitTip) unitTip.style.display = 'none'; }

const TIP_SELECTOR = '.summon-chip, [data-eqtip], [data-comptip], .xref';
function tipTrigger(target) { return target.closest && target.closest(TIP_SELECTOR); }
function tipHtml(node) {
  if (node.dataset.unit != null) return renderUnitSheet(node.dataset.unit);
  if (node.dataset.eqtip != null) return renderEquipSheet(node.dataset.eqtip);
  if (node.dataset.comptip != null) return renderComponentSheet(node.dataset.comptip);
  if (node.classList && node.classList.contains('xref')) {
    const k = node.dataset.k, n = node.dataset.n;
    if (k === 'spell') return renderSpellSheet(n);
    if (k === 'equipment') return renderEquipSheet(n);
    if (k === 'unit') return renderUnitSheet(n);
  }
  return null;
}
function wireTooltips() {
  document.addEventListener('mouseover', e => {
    const c = tipTrigger(e.target);
    if (c) { const h = tipHtml(c); if (h) showTip(h, e.clientX, e.clientY); }
  });
  document.addEventListener('mousemove', e => {
    if (unitTip && unitTip.style.display === 'block' && tipTrigger(e.target)) positionTip(e.clientX, e.clientY);
  });
  document.addEventListener('mouseout', e => {
    if (tipTrigger(e.target)) hideTip();
  });
  // touch / keyboard / navigation
  document.addEventListener('click', e => {
    const xr = e.target.closest && e.target.closest('.xref');
    if (xr) { e.preventDefault(); hideTip(); gotoEntry(xr.dataset.k, xr.dataset.n); return; }
    const c = tipTrigger(e.target);
    if (c) {
      // component tile → let the build handler assign/pick; hover already showed the effect
      if (c.dataset.comptip != null) { hideTip(); return; }
      // summon chip → jump to the full monster entry; equipment-name preview → toggle tip
      if (c.dataset.unit != null) { hideTip(); gotoEntry('unit', c.dataset.unit); return; }
      const h = tipHtml(c);
      if (unitTip && unitTip.style.display === 'block') hideTip();
      else if (h) { const r = c.getBoundingClientRect(); showTip(h, e.clientX || r.left + 20, e.clientY || r.bottom); }
    } else hideTip();
  });
  document.addEventListener('focusin', e => {
    const c = tipTrigger(e.target);
    if (c) { const h = tipHtml(c); if (h) { const r = c.getBoundingClientRect(); showTip(h, r.left, r.bottom); } }
  });
  document.addEventListener('scroll', hideTip, true);
}
function renderEquipSheet(name) {
  const e = EQ_BY_NAME[name];
  if (!e) return `<div class="unit-sheet"><div class="uname">${esc(name)}</div></div>`;
  const desc = e.desc ? `<div class="udesc">${renderMarkup(e.desc)}</div>` : '';
  const bonuses = e.bonuses.length ? `<div class="bonuses">${e.bonuses.map(b => `<div class="b">${renderMarkup(b)}</div>`).join('')}</div>` : '';
  return `<div class="unit-sheet">
    <div class="uhead">
      <img class="uicon" src="icons/equipment/${esc(e.icon)}${IV}" onerror="this.style.visibility='hidden'">
      <div class="uhmeta">
        <div class="uname">${esc(e.name)}</div>
        <div class="card-meta"><span class="badge slot">${esc(e.slot)}</span>${e.tags.map(tagPill).join('')}</div>
      </div>
    </div>
    ${desc}${bonuses}
  </div>`;
}
function renderComponentSheet(name) {
  const c = CP_BY_NAME[name];
  if (!c) return `<div class="unit-sheet"><div class="uname">${esc(name)}</div></div>`;
  const badges = `<span class="badge">Tier ${c.tier}</span>`
    + (c.on_craft ? '<span class="badge oncraft">On Craft</span>' : '')
    + (c.on_pickup && !c.on_craft ? '<span class="badge onpickup">On Pickup</span>' : '')
    + (c.rare ? '<span class="badge">rare</span>' : '');
  const desc = c.desc ? `<div class="udesc">${linkify(renderMarkup(c.desc), c.refs)}</div>` : '';
  return `<div class="unit-sheet">
    <div class="uhead">
      <img class="uicon" src="icons/components/${esc(c.icon)}${IV}" onerror="this.style.visibility='hidden'">
      <div class="uhmeta">
        <div class="uname">${esc(c.name)}</div>
        <div class="card-meta">${badges}${c.tags.map(tagPill).join('')}</div>
      </div>
    </div>
    ${desc}
  </div>`;
}
let SPELL_BY_NAME = {};
function renderSpellSheet(name) {
  const s = SPELL_BY_NAME[name];
  if (!s) return `<div class="unit-sheet"><div class="uname">${esc(name)}</div></div>`;
  const stats = Object.entries(s.stats).map(([k, v]) => `<span class="stat">${STAT_LABEL[k] || k} <b>${v}</b></span>`).join('');
  return `<div class="unit-sheet">
    <div class="uhead">
      <img class="uicon" src="icons/spells/${esc(s.icon)}${IV}" onerror="this.style.visibility='hidden'">
      <div class="uhmeta">
        <div class="uname">${esc(s.name)}</div>
        <div class="card-meta"><span class="badge level" style="background:${TAGCOLOR[s.tags[0]] || '#2a3550'};color:#0c0e14">Lv ${s.level}</span>${s.tags.map(tagPill).join('')}</div>
      </div>
    </div>
    ${s.desc ? `<div class="udesc">${renderMarkup(s.desc)}</div>` : ''}
    ${stats ? `<div class="stats" style="margin-top:6px">${stats}</div>` : ''}
  </div>`;
}

// Cross-reference linking ---------------------------------------------------
// refs = [[displayName, kind], …] this entity references (from AST analysis).
// We only linkify names that are CONFIRMED references, located by position in
// the rendered text — so no false positives from common words.
function linkify(html, refs) {
  if (!html || !refs || !refs.length) return html;
  const kindOf = {};
  for (const [n, k] of refs) kindOf[n] = k;
  const names = refs.map(r => r[0]).sort((a, b) => b.length - a.length);
  const re = new RegExp('(?<![A-Za-z])(' + names.map(escapeRegex).join('|') + ')(?![A-Za-z])', 'g');
  // Only touch text between tags so we never corrupt existing markup/attributes.
  return html.split(/(<[^>]+>)/).map(seg => {
    if (!seg || seg[0] === '<') return seg;
    return seg.replace(re, m => `<span class="xref" data-k="${kindOf[m]}" data-n="${esc(m)}">${m}</span>`);
  }).join('');
}

// Stat search (modifies / scales-with) -------------------------------------
let STAT_META = {};   // stat key -> display label
const STAT_SYNONYMS = {
  damage: ['damage', 'dmg'],
  range: ['range', 'rng'],
  radius: ['radius', 'aoe', 'area', 'blast'],
  duration: ['duration', 'turns'],
  max_charges: ['max charges', 'charges', 'charge'],
  minion_damage: ['minion damage', 'minion dmg', 'summon damage'],
  minion_health: ['minion health', 'minion hp', 'summon hp', 'summon health'],
  minion_duration: ['minion duration', 'summon duration'],
  minion_range: ['minion range', 'summon range'],
  num_summons: ['num summons', 'summons', 'number of summons'],
  num_targets: ['num targets', 'targets', 'number of targets'],
  shields: ['shields', 'shield', 'sh'],
  heal: ['heal', 'healing'],
  hp_cost: ['hp cost', 'health cost', 'life cost'],
  max_channel: ['max channel', 'channel', 'channeling'],
  cascade_range: ['cascade range', 'cascade', 'chain'],
  shot_cooldown: ['shot cooldown', 'shot cd'],
  strikechance: ['strike chance', 'strikechance', 'accuracy', 'hit chance'],
  cooldown: ['cooldown', 'cd'],
};
function statMatches(q) {
  const starts = [], incl = [];
  for (const stat of Object.keys(STAT_META)) {
    const cand = [stat.replace(/_/g, ' '), (STAT_META[stat] || '').toLowerCase(), ...(STAT_SYNONYMS[stat] || [])];
    let best = 2;
    for (const c of cand) { if (c.startsWith(q)) { best = 0; break; } if (c.includes(q)) best = Math.min(best, 1); }
    if (best === 0) starts.push(stat); else if (best === 1) incl.push(stat);
  }
  return [...starts, ...incl].slice(0, 6);
}
function buildStatSuggestions(q, dataset) {
  const out = [];
  for (const stat of statMatches(q)) {
    const label = STAT_META[stat] || stat;
    const modN = dataset.reduce((a, it) => a + (it.mod_stats.includes(stat) ? 1 : 0), 0);
    const useN = dataset.reduce((a, it) => a + (it.use_stats.includes(stat) ? 1 : 0), 0);
    if (modN) out.push({ kind: 'mod', stat, label, count: modN });
    if (useN) out.push({ kind: 'use', stat, label, count: useN });
  }
  return out;
}
const KIND_LABEL = { mod: 'Modifies', use: 'Scales with' };

function makeStatSearch({ inputEl, filtersEl, state, getDataset, render }) {
  state.statFilters = [];
  const dd = el('div', 'stat-dd');
  dd.style.display = 'none';
  document.body.appendChild(dd);

  function positionDD() {
    const r = inputEl.getBoundingClientRect();
    dd.style.left = r.left + 'px';
    dd.style.top = (r.bottom + 4) + 'px';
    dd.style.width = r.width + 'px';
  }
  function updateDD() {
    const q = inputEl.value.trim().toLowerCase();
    const sugg = q.length >= 2 ? buildStatSuggestions(q, getDataset()) : [];
    if (!sugg.length) { dd.style.display = 'none'; return; }
    dd._sugg = sugg;
    dd.innerHTML = `<div class="stat-dd-head">Filter by stat</div>` + sugg.map((s, i) =>
      `<div class="stat-opt" data-i="${i}"><span class="so-kind ${s.kind}">${KIND_LABEL[s.kind]}</span><b>${esc(s.label)}</b><span class="so-count">${s.count}</span></div>`
    ).join('');
    positionDD();
    dd.style.display = 'block';
  }
  function renderFilters() {
    if (!state.statFilters.length) { filtersEl.classList.add('hidden'); filtersEl.innerHTML = ''; return; }
    filtersEl.classList.remove('hidden');
    filtersEl.innerHTML = `<span class="af-label">Active filters:</span>` + state.statFilters.map((f, i) =>
      `<span class="af-chip"><span class="af-kind ${f.kind}">${KIND_LABEL[f.kind]}</span> ${esc(STAT_META[f.stat] || f.stat)}<button data-af="${i}" title="Remove">✕</button></span>`
    ).join('');
  }
  function addFilter(s) {
    if (!state.statFilters.some(f => f.kind === s.kind && f.stat === s.stat)) state.statFilters.push({ kind: s.kind, stat: s.stat });
    inputEl.value = ''; state.search = ''; dd.style.display = 'none';
    renderFilters(); render();
  }

  inputEl.addEventListener('input', () => { state.search = inputEl.value; updateDD(); render(); });
  inputEl.addEventListener('focus', updateDD);
  inputEl.addEventListener('blur', () => setTimeout(() => { dd.style.display = 'none'; }, 150));
  dd.addEventListener('mousedown', e => {
    const o = e.target.closest('.stat-opt');
    if (o) { e.preventDefault(); addFilter(dd._sugg[+o.dataset.i]); }
  });
  filtersEl.addEventListener('click', e => {
    const b = e.target.closest('[data-af]');
    if (b) { state.statFilters.splice(+b.dataset.af, 1); renderFilters(); render(); }
  });
  window.addEventListener('scroll', () => { if (dd.style.display === 'block') positionDD(); }, true);

  renderFilters();
}
function passesStatFilters(item, filters) {
  for (const f of filters) {
    const arr = f.kind === 'mod' ? item.mod_stats : item.use_stats;
    if (!arr.includes(f.stat)) return false;
  }
  return true;
}

// Multi-select chip groups -------------------------------------------------
function buildChips(container, values, opts = {}) {
  container.innerHTML = '';
  const state = new Set();
  values.forEach(v => {
    const label = opts.label ? opts.label(v) : v;
    const chip = el('button', 'chip');
    if (opts.dot) {
      const d = el('span', 'dot');
      d.style.background = opts.dot(v);
      chip.appendChild(d);
    }
    chip.appendChild(document.createTextNode(label));
    chip.addEventListener('click', () => {
      if (state.has(v)) { state.delete(v); chip.classList.remove('active'); chip.style.background = ''; }
      else {
        state.add(v); chip.classList.add('active');
        chip.style.background = opts.activeColor ? opts.activeColor(v) : 'var(--accent)';
      }
      opts.onChange();
    });
    container.appendChild(chip);
  });
  return state;
}

// ---------------------------------------------------------------------------
// EQUIPMENT
// ---------------------------------------------------------------------------
function equipmentCard(e) {
  const card = el('div', 'card');
  card.id = 'e-' + slug(e.name);
  const recipe = recipeChips(e.recipe);
  const bonuses = e.bonuses.length
    ? `<div class="bonuses">${e.bonuses.map(b => `<div class="b">${linkify(renderMarkup(b), e.refs)}</div>`).join('')}</div>` : '';
  const desc = e.desc ? `<div class="desc">${linkify(renderMarkup(e.desc), e.refs)}</div>` : '';
  card.innerHTML = `
    <div class="card-head">
      ${iconImg('equipment', e)}
      <div class="card-title">
        <div class="name">${esc(e.name)}</div>
        <div class="card-meta">
          <span class="badge slot">${esc(e.slot)}</span>
          ${e.tags.map(tagPill).join('')}
        </div>
      </div>
      <button class="add-build${WISH.has(e.name) ? ' in' : ''}" data-add="${esc(e.name)}">${WISH.has(e.name) ? '✓ In build' : '＋ Build'}</button>
    </div>
    ${desc}${bonuses}
    ${summonRow(e.summons)}
    <div class="section-label">Recipe · cost ${e.recipe_cost}</div>
    <div class="recipe">${recipe}</div>`;
  return card;
}

const EQ = { search: '', slots: null, tags: null, sort: 'cost', craftableOnly: false, statFilters: [] };
function renderEquipment() {
  const q = EQ.search.toLowerCase();
  const slots = EQ.slots, tags = EQ.tags;
  const pool = EQ.craftableOnly ? inventoryEssences() : null;
  let list = DATA.equipment.filter(e => {
    if (slots.size && !slots.has(e.slot)) return false;
    if (EQ.statFilters && !passesStatFilters(e, EQ.statFilters)) return false;
    if (EQ.craftableOnly && evalRecipe(e.recipe, pool).missing > 0) return false;
    if (tags.size) {
      const rtags = new Set(e.recipe.map(r => r[0]));
      for (const t of tags) if (!rtags.has(t)) return false;
    }
    if (q) {
      const hay = (e.name + ' ' + e.desc + ' ' + e.bonuses.join(' ') + ' ' + e.tags.join(' ') + ' ' + e.slot + ' ' + (e.summons || []).join(' ')).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const sorters = {
    cost: (a, b) => a.recipe_cost - b.recipe_cost || a.name.localeCompare(b.name),
    'cost-desc': (a, b) => b.recipe_cost - a.recipe_cost || a.name.localeCompare(b.name),
    name: (a, b) => a.name.localeCompare(b.name),
    slot: (a, b) => a.slot.localeCompare(b.slot) || a.recipe_cost - b.recipe_cost,
  };
  list.sort(sorters[EQ.sort]);
  const grid = $('#eq-grid');
  grid.innerHTML = '';
  if (!list.length) {
    const msg = (EQ.craftableOnly && Object.keys(INVENTORY).length === 0)
      ? 'Add components on the <a class="tablink" data-goto="components">Components tab</a> to see what you can craft.'
      : 'No equipment matches those filters.';
    grid.appendChild(el('div', 'empty', msg));
  }
  list.forEach(e => grid.appendChild(equipmentCard(e)));
  const suffix = EQ.craftableOnly ? ' craftable' : '';
  $('#eq-count').textContent = `${list.length} of ${DATA.equipment.length} items${suffix}`;
}

// ---------------------------------------------------------------------------
// WISHLIST / BUILD (shopping cart)
// ---------------------------------------------------------------------------
let WISH = new Set();     // set of equipment names (each is unique → no quantities)
let EQ_BY_NAME = {};      // name -> equipment object
let EQ_ID_BY_NAME = {};   // name -> stable integer id (from data.json)
let EQ_NAME_BY_ID = {};   // stable integer id -> name

// --- Build state lives in the URL, not localStorage --------------------------
// The build is encoded in the `?b=` query param as a sorted list of stable
// equipment ids in base36, joined by '.'  (e.g. ?b=0.2x.9p). This makes builds
// shareable as plain links, lets two tabs hold different builds, and keeps the
// URL the single source of truth. Tab selection stays in the hash; component
// inventory and scroll position remain local-only.
const BUILD_PARAM = 'b';
function encodeBuild() {
  const ids = [...WISH].map(n => EQ_ID_BY_NAME[n]).filter(v => v != null).sort((a, b) => a - b);
  return ids.map(i => i.toString(36)).join('.');
}
function loadWishFromUrl() {
  WISH = new Set();
  const b = new URL(location.href).searchParams.get(BUILD_PARAM);
  if (!b) return;
  for (const tok of b.split('.')) {
    const id = parseInt(tok, 36);
    const name = EQ_NAME_BY_ID[id];
    if (name) WISH.add(name);   // unknown/removed ids are silently dropped
  }
}
function updateUrl() {
  const b = encodeBuild();
  const url = new URL(location.href);
  if (b) url.searchParams.set(BUILD_PARAM, b); else url.searchParams.delete(BUILD_PARAM);
  // replaceState (not push): toggling items shouldn't flood the back button.
  history.replaceState(null, '', url);
}
function shareBuild(e) {
  updateUrl();   // make sure the URL reflects the current build before copying
  const url = location.href;
  const btn = e && e.currentTarget;
  const done = ok => {
    if (!btn) return;
    const orig = btn.innerHTML;
    btn.innerHTML = ok ? '✓ Copied!' : '⚠ Copy failed';
    setTimeout(() => { btn.innerHTML = orig; }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(() => done(true), () => done(false));
  } else {
    // Fallback for non-secure contexts without the async clipboard API.
    const ta = el('textarea'); ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove(); done(ok);
  }
}
function wishToggle(name) {
  if (WISH.has(name)) WISH.delete(name); else WISH.add(name);
  if (!WISH.has(name)) delete ASSIGN[name];   // dropping an item frees its components
  updateUrl();
  saveAssign();
  renderBuild();
  renderEquipment();   // refresh button states
}

// ---------------------------------------------------------------------------
// MANUAL COMPONENT ASSIGNMENT (the build workspace)
// ---------------------------------------------------------------------------
// Manual is the default: the user assigns whole components to build items by
// click-to-place or drag. `ASSIGN` is the single source of truth — even the
// "Auto assign" button just overwrites it with a computed allocation. Each
// component is committed WHOLE to one item (extra essences wasted, never shared
// — §7). Persisted locally; the build itself stays in the URL.
let ASSIGN = {};          // equipment name -> [component name, …] committed to it
const ASSIGN_KEY = 'rw3_assign';
let PICK = null;          // currently "held" component: {name, from} (from=equip name | null=pool)

function loadAssign() {
  try { ASSIGN = JSON.parse(localStorage.getItem(ASSIGN_KEY)) || {}; } catch (e) { ASSIGN = {}; }
  if (!ASSIGN || typeof ASSIGN !== 'object' || Array.isArray(ASSIGN)) ASSIGN = {};
}
function saveAssign() { try { localStorage.setItem(ASSIGN_KEY, JSON.stringify(ASSIGN)); } catch (e) {} }

// Keep ASSIGN consistent with the current build + inventory: drop assignments
// for items no longer in the build, and trim any over-allocation if the owned
// count of a component dropped below what's assigned.
function reconcileAssign() {
  let changed = false;
  for (const k of Object.keys(ASSIGN)) {
    if (!WISH.has(k)) { delete ASSIGN[k]; changed = true; }
  }
  const totals = {};
  for (const k in ASSIGN) for (const cn of ASSIGN[k]) totals[cn] = (totals[cn] || 0) + 1;
  for (const cn in totals) {
    let excess = totals[cn] - (INVENTORY[cn] || 0);
    for (const k of Object.keys(ASSIGN)) {
      while (excess > 0) {
        const i = ASSIGN[k].indexOf(cn);
        if (i < 0) break;
        ASSIGN[k].splice(i, 1); excess--; changed = true;
      }
    }
  }
  for (const name of WISH) if (!ASSIGN[name]) ASSIGN[name] = [];
  if (changed) saveAssign();
}

const compEssences = name => { const c = CP_BY_NAME[name]; return c ? c.tags.filter(t => t !== 'Any') : []; };
function totalAssigned(name) { let n = 0; for (const k in ASSIGN) for (const cn of ASSIGN[k]) if (cn === name) n++; return n; }
function availableInPool(name) { return (INVENTORY[name] || 0) - totalAssigned(name); }
function poolCounts() {
  const out = {};
  for (const name in INVENTORY) { const a = availableInPool(name); if (a > 0) out[name] = a; }
  return out;
}

// Evaluate one item's assignment: map each committed component's essences onto
// the recipe's slots (specific tags first, then Any), reporting filled/empty
// slots, per-component used/wasted essences, and total waste.
function evalAssignment(recipe, assignedNames) {
  const slots = [];
  for (const [tag, n] of recipe) for (let i = 0; i < n; i++) slots.push({ req: tag, filled: false, comp: -1, essence: null });
  const comps = assignedNames.map((name, idx) => { const tags = compEssences(name); return { name, idx, tags, used: tags.map(() => false) }; });
  // Phase 1 — specific tags
  for (const slot of slots) {
    if (slot.req === 'Any') continue;
    for (const cmp of comps) {
      const j = cmp.tags.findIndex((t, k) => !cmp.used[k] && t === slot.req);
      if (j >= 0) { cmp.used[j] = true; slot.filled = true; slot.comp = cmp.idx; slot.essence = slot.req; break; }
    }
  }
  // Phase 2 — Any slots take any leftover essence
  for (const slot of slots) {
    if (slot.req !== 'Any' || slot.filled) continue;
    for (const cmp of comps) {
      const j = cmp.used.findIndex(u => !u);
      if (j >= 0) { cmp.used[j] = true; slot.filled = true; slot.comp = cmp.idx; slot.essence = cmp.tags[j]; break; }
    }
  }
  const wasted = comps.reduce((a, c) => a + c.used.filter(u => !u).length, 0);
  const filled = slots.filter(s => s.filled).length;
  return { slots, comps, wasted, filled, total: slots.length, ok: filled === slots.length };
}

// --- assignment mutations ---------------------------------------------------
function doAssign(name, from, equip) {
  if (from === equip) return false;
  if (from == null) { if (availableInPool(name) <= 0) return false; }
  else { const arr = ASSIGN[from]; const i = arr ? arr.indexOf(name) : -1; if (i < 0) return false; arr.splice(i, 1); }
  (ASSIGN[equip] = ASSIGN[equip] || []).push(name);
  saveAssign();
  return true;
}
function unassign(name, fromEquip) {
  const arr = ASSIGN[fromEquip]; if (!arr) return;
  const i = arr.indexOf(name); if (i < 0) return;
  arr.splice(i, 1);
  if (PICK && PICK.from === fromEquip && PICK.name === name) PICK = null;
  saveAssign(); renderBuild();
}
function placeOn(equip) {     // click-to-place the held component
  if (!PICK) return;
  doAssign(PICK.name, PICK.from, equip);
  PICK = null; renderBuild();
}
function togglePick(name, from) {
  PICK = (PICK && PICK.name === name && PICK.from === from) ? null : { name, from };
  renderBuild();
}
const pickMatches = (name, from) => !!PICK && PICK.name === name && PICK.from === from;

function autoAssign() {       // overwrite ASSIGN with the greedy allocation (§7)
  const plan = planBuild();
  ASSIGN = {};
  for (const name of WISH) ASSIGN[name] = (plan.status[name] && plan.status[name].ok) ? plan.status[name].usedNames.slice() : [];
  PICK = null; saveAssign(); renderBuild();
}
function clearBuilt() {       // remove finished items + the components they consumed
  const done = [];
  for (const name of WISH) {
    const e = EQ_BY_NAME[name]; if (!e) continue;
    if (evalAssignment(e.recipe, ASSIGN[name] || []).ok) done.push(name);
  }
  if (!done.length) return;
  for (const name of done) {
    for (const cn of (ASSIGN[name] || [])) {
      if (INVENTORY[cn]) { INVENTORY[cn]--; if (INVENTORY[cn] <= 0) delete INVENTORY[cn]; }
    }
    delete ASSIGN[name];
    WISH.delete(name);
  }
  PICK = null;
  saveInv(); saveAssign(); updateUrl();
  invRefresh();
}

// --- rendering --------------------------------------------------------------
// Single-letter essence codes, matching the game's crafting UI (the tag filter
// hotkeys in RiftWizard3.py). Distinct letters resolve first-letter clashes:
// Eye=Y, Dragon=R, Chaos=K, Slime=Z, Ritual=U; Any=∗. Prefer the value baked
// into data.json (extract.py) if present, else this fallback, else first letter.
const TAG_ABBR = {
  Any: '∗', Fire: 'F', Ice: 'I', Lightning: 'L', Nature: 'N', Arcane: 'A', Dark: 'D',
  Holy: 'H', Metallic: 'M', Blood: 'B', Sorcery: 'S', Enchantment: 'E', Conjuration: 'C',
  Eye: 'Y', Dragon: 'R', Orb: 'O', Chaos: 'K', Slime: 'Z', Word: 'W', Translocation: 'T', Ritual: 'U',
};
function tagAbbr(t) {
  const d = DATA.tags.all[t];
  return (d && d.abbr) || TAG_ABBR[t] || (t ? t[0].toUpperCase() : '?');
}
function essenceCell(tag, used) {
  const col = TAGCOLOR[tag] || 'var(--muted)';
  return `<span class="ess${used === false ? ' wasted' : ''}" style="--ec:${col}" title="${esc(tag)}${used === false ? ' (wasted)' : ''}">${esc(tagAbbr(tag))}</span>`;
}
function compTileHtml(name, opts) {
  const { mode, count, equip, usedFlags } = opts;
  const c = CP_BY_NAME[name];
  const tags = compEssences(name);
  const oncraft = c && c.on_craft;
  const ic = c
    ? `<img class="ct-ic" loading="lazy" src="icons/components/${esc(c.icon)}${IV}" onerror="this.style.visibility='hidden'">`
    : `<div class="ct-ic placeholder">✦</div>`;
  const ess = tags.map((t, j) => essenceCell(t, usedFlags ? usedFlags[j] : null)).join('');
  const picked = mode === 'pool' ? pickMatches(name, null) : pickMatches(name, equip);
  const badge = (mode === 'pool' && count > 1) ? `<span class="ct-count">×${count}</span>` : '';
  const rm = mode === 'assigned' ? `<button class="ct-rm" data-unassign="${esc(name)}" data-equip="${esc(equip)}" title="Unassign">✕</button>` : '';
  const fromAttr = mode === 'assigned' ? ` data-from="${esc(equip)}"` : '';
  // On-craft components show their effect in a rich hover tooltip; others get a plain title.
  const tipAttr = oncraft ? ` data-comptip="${esc(name)}"` : ` title="${esc(name)}"`;
  return `<div class="comp-tile${oncraft ? ' oncraft' : ''}${picked ? ' picked' : ''}" data-pick="${esc(name)}"${fromAttr}${tipAttr} draggable="true">
    ${badge}${rm}
    <div class="ct-name">${esc(name)}</div>
    <div class="ct-bottom">${ic}<div class="ct-ess">${ess || '<span class="ess-none">—</span>'}</div></div>
  </div>`;
}
function slotCell(s) {
  const mark = s.filled ? '✓' : '?';
  if (s.req === 'Any') {
    return `<span class="eslot any ${s.filled ? 'filled' : 'miss'}" title="Any essence${s.filled ? `, filled by ${esc(s.essence)}` : ''}">∗ ${mark}</span>`;
  }
  const col = TAGCOLOR[s.req] || 'var(--muted)';
  return `<span class="eslot ${s.filled ? 'filled' : 'miss'}" style="--ec:${col}" title="${esc(s.req)}${s.filled ? '' : ' (missing)'}">${esc(tagAbbr(s.req))} ${mark}</span>`;
}
function buildItemHtml(name, ev) {
  const e = EQ_BY_NAME[name];
  if (!e) return `<div class="build-item"><div class="bi-left"><span class="bi-name">${esc(name)}</span></div><button class="wl-remove" data-wish-remove="${esc(name)}" title="Remove">✕</button></div>`;
  const assigned = ASSIGN[name] || [];
  const ic = `<img class="bi-ic" loading="lazy" src="icons/equipment/${esc(e.icon)}${IV}" onerror="this.style.visibility='hidden'">`;
  const slotsHtml = ev.slots.map(slotCell).join('');
  const emptyHint = Object.keys(INVENTORY).length
    ? 'drop components here'
    : 'add some <a class="tablink" data-goto="components">components</a> to build this';
  const tiles = assigned.length
    ? assigned.map((cn, idx) => compTileHtml(cn, { mode: 'assigned', equip: name, usedFlags: ev.comps[idx].used })).join('')
    : `<span class="bi-drop-hint">${emptyHint}</span>`;
  // Denominator is the recipe cost, so don't repeat it. Built items show the
  // cost in green; unbuilt show filled/cost.
  const status = ev.ok
    ? `<span class="wl-built" title="Built (recipe cost ${ev.total})">✓ ${ev.total}</span>`
    : `<span class="wl-miss" title="${ev.filled} of ${ev.total} essences filled (recipe cost ${ev.total})">${ev.filled}/${ev.total}</span>`;
  const wasteBadge = ev.wasted ? `<span class="bi-waste" title="${ev.wasted} committed essence${ev.wasted !== 1 ? 's' : ''} wasted">⊘ ${ev.wasted}</span>` : '';
  return `<div class="build-item${ev.ok ? ' is-ok' : ''}${PICK ? ' droppable' : ''}" data-drop-equip="${esc(name)}">
    <button class="wl-remove" data-wish-remove="${esc(name)}" title="Remove from build">✕</button>
    <div class="bi-left">
      ${ic}
      <div class="bi-info">
        <div class="bi-row1">
          <span class="bi-name" data-eqtip="${esc(name)}" tabindex="0">${esc(name)}</span>
          <span class="badge slot">${esc(e.slot)}</span>
          ${status}${wasteBadge}
        </div>
        <div class="bi-slots" title="Recipe: ✓ filled, ? missing">${slotsHtml}</div>
      </div>
    </div>
    <div class="bi-comps" data-drop-equip="${esc(name)}">${tiles}</div>
  </div>`;
}
// The component pool is its own panel on the Equipment tab — shown whenever you
// own components, independent of whether a build is selected, so the inventory
// (and the "Craftable only" flow) is always visible.
function renderPool() {
  const pool = $('#eq-pool');
  const ownsAny = Object.keys(INVENTORY).length > 0;
  if (!ownsAny) { pool.classList.add('hidden'); pool.innerHTML = ''; pool.classList.remove('picking'); return; }
  pool.classList.remove('hidden');
  const counts = poolCounts();
  const entries = Object.entries(counts).sort((a, b) => {
    const ca = CP_BY_NAME[a[0]], cb = CP_BY_NAME[b[0]];
    return (ca && cb ? ca.tier - cb.tier : 0) || a[0].localeCompare(b[0]);
  });
  const total = Object.values(INVENTORY).reduce((a, b) => a + b, 0);
  let body;
  if (!entries.length) body = `<div class="pool-empty">Every component is assigned. Drag or click one out of an item to free it.</div>`;
  else body = entries.map(([name, cnt]) => compTileHtml(name, { mode: 'pool', count: cnt })).join('');
  const hint = PICK
    ? `<span class="pick-hint">Click equipment to assign <b>${esc(PICK.name)}</b>${PICK.from ? ', or click here to unassign' : ''}</span>`
    : (entries.length && WISH.size
      ? `<span class="pool-hint">Drag components onto build equipment to assign them.</span>`
      : '');
  pool.innerHTML = `<div class="pool-head"><span class="pool-title">My components <span class="wl-badge">${total}</span> <a class="tablink pool-edit" data-goto="components">edit</a></span>${hint}</div>
    <div class="pool-tiles">${body}</div>`;
  pool.classList.toggle('picking', !!PICK);
}
function renderBuild() {
  reconcileAssign();
  const names = [...WISH];
  if (!names.length) PICK = null;     // nothing to assign onto
  renderPool();                       // standalone components panel, independent of the build
  const panel = $('#build');
  if (!names.length) { panel.classList.add('hidden'); return; }
  panel.classList.remove('hidden');
  $('#wl-count').textContent = names.length;

  const evals = {};
  let okCount = 0, waste = 0;
  for (const name of names) {
    const e = EQ_BY_NAME[name];
    const ev = evalAssignment(e ? e.recipe : [], ASSIGN[name] || []);
    evals[name] = ev;
    if (ev.ok) okCount++;
    waste += ev.wasted;
  }
  $('#build-summary').innerHTML =
    `<span class="bs-craft ${okCount === names.length ? 'all' : ''}">${okCount}/${names.length} built</span>` +
    (waste ? `<span class="bs-waste" title="essences committed but unused">⊘ ${waste} wasted</span>` : '');
  $('#wl-clearbuilt').disabled = okCount === 0;

  $('#build-items').innerHTML = names
    .sort((a, b) => (EQ_BY_NAME[a] ? EQ_BY_NAME[a].recipe_cost : 0) - (EQ_BY_NAME[b] ? EQ_BY_NAME[b].recipe_cost : 0) || a.localeCompare(b))
    .map(name => buildItemHtml(name, evals[name])).join('');
  panel.classList.toggle('picking', !!PICK);
}

function wireBuild() {
  document.addEventListener('click', e => {
    const t = e.target;
    const add = t.closest && t.closest('.add-build[data-add]');
    if (add) { wishToggle(add.dataset.add); return; }
    const rm = t.closest && t.closest('[data-wish-remove]');
    if (rm) { wishToggle(rm.dataset.wishRemove); return; }
    const un = t.closest && t.closest('[data-unassign]');
    if (un) { unassign(un.dataset.unassign, un.dataset.equip); return; }
    const tile = t.closest && t.closest('[data-pick]');
    if (tile) { togglePick(tile.dataset.pick, tile.dataset.from || null); return; }
    const drop = t.closest && t.closest('[data-drop-equip]');
    if (drop && PICK) { placeOn(drop.dataset.dropEquip); return; }
    if (PICK && t.closest && t.closest('#eq-pool')) {   // click empty pool → unassign held / cancel
      if (PICK.from) unassign(PICK.name, PICK.from); else { PICK = null; renderBuild(); }
      return;
    }
  });
  $('#wl-clear').addEventListener('click', () => { WISH = new Set(); ASSIGN = {}; PICK = null; updateUrl(); saveAssign(); renderBuild(); renderEquipment(); });
  $('#wl-share').addEventListener('click', shareBuild);
  $('#wl-auto').addEventListener('click', autoAssign);
  $('#wl-clearbuilt').addEventListener('click', clearBuilt);
  window.addEventListener('popstate', () => { loadWishFromUrl(); PICK = null; renderBuild(); renderEquipment(); });

  // Drag and drop (enhancement; click-to-place is the primary, mobile-friendly path)
  document.addEventListener('dragstart', e => {
    const tile = e.target.closest && e.target.closest('[data-pick]');
    if (!tile) return;
    e.dataTransfer.setData('text/plain', JSON.stringify({ name: tile.dataset.pick, from: tile.dataset.from || null }));
    e.dataTransfer.effectAllowed = 'move';
    tile.classList.add('dragging');
    PICK = null;     // dragging supersedes a click-selection
    DRAGGING = true; // and suppresses the hover tooltip
    hideTip();
  });
  document.addEventListener('dragend', e => {
    DRAGGING = false;
    const tile = e.target.closest && e.target.closest('[data-pick]');
    if (tile) tile.classList.remove('dragging');
  });
  document.addEventListener('dragover', e => {
    if ((e.target.closest && (e.target.closest('[data-drop-equip]') || e.target.closest('#eq-pool')))) {
      e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    }
  });
  document.addEventListener('drop', e => {
    DRAGGING = false;   // re-render below may detach the source before dragend fires
    let payload; try { payload = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (_) { return; }
    if (!payload || !payload.name) return;
    const drop = e.target.closest && e.target.closest('[data-drop-equip]');
    if (drop) { e.preventDefault(); if (doAssign(payload.name, payload.from || null, drop.dataset.dropEquip)) renderBuild(); return; }
    if (e.target.closest && e.target.closest('#eq-pool') && payload.from) {  // drop onto pool → unassign
      e.preventDefault();
      const arr = ASSIGN[payload.from]; const i = arr ? arr.indexOf(payload.name) : -1;
      if (i >= 0) { arr.splice(i, 1); saveAssign(); renderBuild(); }
    }
  });
}

// ---------------------------------------------------------------------------
// COMPONENTS
// ---------------------------------------------------------------------------
function componentCard(c) {
  const card = el('div', 'card');
  card.innerHTML = `
    <div class="card-head">
      ${iconImg('components', c)}
      <div class="card-title">
        <div class="name">${esc(c.name)}${c.rare ? ' <span class="badge">rare</span>' : ''}</div>
        <div class="card-meta">
          <span class="badge">Tier ${c.tier}</span>
          <span class="badge ${c.on_craft ? 'oncraft' : 'onpickup'}">${c.on_craft ? 'On Craft' : 'On Pickup'}</span>
          ${c.tags.map(tagPill).join('')}
        </div>
      </div>
      <button class="add-build${INVENTORY[c.name] ? ' in' : ''}" data-addcomp="${esc(c.name)}">${INVENTORY[c.name] ? `✓ In pool ×${INVENTORY[c.name]}` : '＋ Add to pool'}</button>
    </div>
    <div class="desc">${linkify(renderMarkup(c.desc), c.refs)}</div>
    ${summonRow(c.summons)}`;
  return card;
}

const CP = { search: '', tiers: null, effects: null, tags: null };
function renderComponents() {
  const q = CP.search.toLowerCase();
  let list = DATA.components.filter(c => {
    if (CP.tiers.size && !CP.tiers.has(String(c.tier))) return false;
    if (CP.effects.size) {
      const eff = c.on_craft ? 'craft' : 'pickup';
      if (!CP.effects.has(eff)) return false;
    }
    if (CP.tags.size) { for (const t of CP.tags) if (!c.tags.includes(t)) return false; }
    if (q) {
      const hay = (c.name + ' ' + c.desc + ' ' + c.tags.join(' ') + ' ' + (c.summons || []).join(' ')).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const grid = $('#cp-grid');
  grid.innerHTML = '';
  if (!list.length) grid.appendChild(el('div', 'empty', 'No components match.'));
  list.forEach(c => grid.appendChild(componentCard(c)));
  $('#cp-count').textContent = `${list.length} of ${DATA.components.length} components`;
}

// ---------------------------------------------------------------------------
// SPELLS
// ---------------------------------------------------------------------------
const STAT_LABEL = {
  range: 'Range', max_charges: 'Charges', damage: 'Damage', radius: 'Radius',
  duration: 'Duration', minion_damage: 'Minion dmg', minion_health: 'Minion HP',
  minion_duration: 'Minion dur', num_summons: 'Summons', hp_cost: 'HP cost',
  shields: 'Shields', num_targets: 'Targets'
};
function spellCard(s) {
  const card = el('div', 'card');
  card.id = 's-' + slug(s.name);
  const stats = Object.entries(s.stats)
    .map(([k, v]) => `<span class="stat">${STAT_LABEL[k] || k} <b>${v}</b></span>`).join('');
  const dt = s.damage_type.length ? `<div class="card-meta">${s.damage_type.map(tagPill).join('')}</div>` : '';
  const upg = s.upgrades.length ? `
    <details class="upgrades"><summary>${s.upgrades.length} upgrade${s.upgrades.length > 1 ? 's' : ''}</summary>
      ${s.upgrades.map(u => `<div class="upg"><span class="uh">${esc(u.name)}</span><span class="ul">Lv ${u.level}</span><div class="desc">${linkify(renderMarkup(u.desc), s.refs)}</div></div>`).join('')}
    </details>` : '';
  card.innerHTML = `
    <div class="card-head">
      ${iconImg('spells', s)}
      <div class="card-title">
        <div class="name">${esc(s.name)}</div>
        <div class="card-meta">
          <span class="badge level" style="background:${TAGCOLOR[s.tags[0]] || '#2a3550'};color:#0c0e14">Lv ${s.level}</span>
          ${s.tags.map(tagPill).join('')}
          ${s.quick_cast ? '<span class="badge">quick cast</span>' : ''}
          ${s.melee ? '<span class="badge">melee</span>' : ''}
        </div>
      </div>
    </div>
    <div class="desc">${linkify(renderMarkup(s.desc), s.refs)}</div>
    ${stats ? `<div class="stats">${stats}</div>` : ''}
    ${dt}${summonRow(s.summons)}${upg}`;
  return card;
}

const SP = { search: '', levels: null, tags: null };
function renderSpells() {
  const q = SP.search.toLowerCase();
  let list = DATA.spells.filter(s => {
    if (SP.levels.size && !SP.levels.has(String(s.level))) return false;
    if (SP.statFilters && !passesStatFilters(s, SP.statFilters)) return false;
    if (SP.tags.size) { for (const t of SP.tags) if (!s.tags.includes(t)) return false; }
    if (q) {
      const hay = (s.name + ' ' + s.desc + ' ' + s.tags.join(' ') + ' ' + s.upgrades.map(u => u.name + ' ' + u.desc).join(' ') + ' ' + (s.summons || []).join(' ')).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const grid = $('#sp-grid');
  grid.innerHTML = '';
  if (!list.length) grid.appendChild(el('div', 'empty', 'No spells match.'));
  list.forEach(s => grid.appendChild(spellCard(s)));
  $('#sp-count').textContent = `${list.length} of ${DATA.spells.length} spells`;
}

// ---------------------------------------------------------------------------
// MONSTERS / units
// ---------------------------------------------------------------------------
const slug = s => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
const unitCardId = name => 'u-' + slug(name);
const escapeRegex = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const KIND_CARD_PREFIX = { spell: 's-', equipment: 'e-', unit: 'u-' };
const KIND_TAB = { spell: 'spells', equipment: 'equipment', unit: 'monsters' };

function flashCard(node) {
  node.classList.remove('flash');
  void node.offsetWidth;       // restart the animation
  node.classList.add('flash');
  setTimeout(() => node.classList.remove('flash'), 3200);
}
function smoothScrollTo(y, dur) {
  const startY = window.scrollY, dist = y - startY, t0 = performance.now();
  function step(now) {
    const p = Math.min(1, (now - t0) / dur);
    const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;  // easeInOutQuad
    window.scrollTo(0, startY + dist * e);
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
function scrollToCard(node) {
  const header = document.querySelector('header');
  const offset = (header ? header.offsetHeight : 0) + 12;
  const y = window.scrollY + node.getBoundingClientRect().top - offset;
  smoothScrollTo(Math.max(0, y), 260);
}
function clearChipGroup(set, sel) {
  if (set) set.clear();
  $$(sel + ' .chip').forEach(c => { c.classList.remove('active'); c.style.background = ''; });
}
function clearFilters(tab) {
  if (tab === 'equipment') {
    EQ.search = ''; const i = $('#eq-search'); if (i) i.value = ''; EQ.statFilters.length = 0;
    EQ.craftableOnly = false; const b = $('#eq-craftable'); if (b) b.classList.remove('active');
    clearChipGroup(EQ.slots, '#eq-slots'); clearChipGroup(EQ.tags, '#eq-tags');
    const f = $('#eq-filters'); if (f) { f.classList.add('hidden'); f.innerHTML = ''; }
  } else if (tab === 'spells') {
    SP.search = ''; const i = $('#sp-search'); if (i) i.value = ''; SP.statFilters.length = 0;
    clearChipGroup(SP.levels, '#sp-levels'); clearChipGroup(SP.tags, '#sp-tags');
    const f = $('#sp-filters'); if (f) { f.classList.add('hidden'); f.innerHTML = ''; }
  } else if (tab === 'monsters') {
    MON.search = ''; const i = $('#mon-search'); if (i) i.value = '';
    clearChipGroup(MON.types, '#mon-types'); clearChipGroup(MON.moves, '#mon-moves'); clearChipGroup(MON.tags, '#mon-tags');
  }
}
const TAB_RENDER = { equipment: () => renderEquipment(), spells: () => renderSpells(), monsters: () => renderMonsters() };
function gotoEntry(kind, name) {
  const tab = KIND_TAB[kind];
  const id = KIND_CARD_PREFIX[kind] + slug(name);
  switchTab(tab);
  if (!document.getElementById(id)) { clearFilters(tab); TAB_RENDER[tab](); }
  requestAnimationFrame(() => {
    const node = document.getElementById(id);
    if (node) { scrollToCard(node); flashCard(node); }
  });
}

// Build the name->kind index and the linkify() that wraps references in <span class="xref">.
function renderAbility(a, refs) {
  const bits = [];
  if (a.damage) bits.push(`<span class="udmg">${a.damage}${a.damage_type ? ' ' + a.damage_type.join('/') : ''} dmg</span>`);
  if (a.range && a.range > 1.5) bits.push(`rng ${Math.round(a.range)}`);
  else if (a.melee) bits.push('melee');
  if (a.radius) bits.push(`rad ${a.radius}`);
  if (a.cool_down) bits.push(`cd ${a.cool_down}`);
  if (a.hp_cost) bits.push(`${a.hp_cost} hp`);
  if (a.quick_cast) bits.push('quick');
  return `<div class="uab"><span class="uabn">${esc(a.name)}</span>${bits.length ? ` <span class="ubits">${bits.join(' · ')}</span>` : ''}${a.desc ? `<div class="udesc">${linkify(renderMarkup(a.desc), refs)}</div>` : ''}</div>`;
}

function monsterCard(u) {
  const card = el('div', 'card mon-card');
  card.id = unitCardId(u.name);
  const flags = [u.flying && 'Flying', u.stationary && 'Immobile', u.burrowing && 'Burrowing'].filter(Boolean);
  const resists = Object.entries(u.resists).sort((a, b) => b[1] - a[1])
    .map(([t, v]) => `<span class="ures" style="color:${TAGCOLOR[t] || 'var(--muted)'}">${v}% ${esc(t)}</span>`).join('');
  const abilities = u.abilities.map(a => renderAbility(a, u.refs)).join('');
  const passives = u.passives.map(p => `<div class="upass">${linkify(renderMarkup(p), u.refs)}</div>`).join('');
  const depthBadge = u.depth ? `<span class="badge">Depth ${u.depth}</span>` : '';
  const typeBadge = u.is_monster ? '' : '<span class="badge">summon</span>';
  const hp = u.hp ? `${u.hp} HP` : 'HP varies';
  card.innerHTML = `
    <div class="card-head">
      ${unitSprite(u, 'mon-art')}
      <div class="card-title">
        <div class="name">${esc(u.name)}</div>
        <div class="card-meta">${depthBadge}${typeBadge}${u.tags.map(tagPill).join('')}</div>
        <div class="uline"><span class="uhp">❤ ${hp}</span>${u.shields ? `<span class="ush">◆ ${u.shields} SH</span>` : ''}${flags.length ? `<span class="uflags">${flags.join(' · ')}</span>` : ''}</div>
      </div>
    </div>
    ${resists ? `<div class="uresists">${resists}</div>` : ''}
    ${abilities ? `<div class="usec">Abilities</div>${abilities}` : ''}
    ${passives ? `<div class="usec">Passives</div>${passives}` : ''}`;
  return card;
}

const MON = { search: '', types: null, moves: null, tags: null, sort: 'name' };
const MOVE_FLAG = { Flying: 'flying', Immobile: 'stationary', Burrowing: 'burrowing' };
function renderMonsters() {
  const q = MON.search.toLowerCase();
  let list = Object.values(DATA.units).filter(u => {
    if (MON.types.size) {
      const ty = u.is_monster ? 'monster' : 'summon';
      if (!MON.types.has(ty)) return false;
    }
    if (MON.moves.size) { for (const mv of MON.moves) if (!u[MOVE_FLAG[mv]]) return false; }
    if (MON.tags.size) { for (const t of MON.tags) if (!u.tags.includes(t)) return false; }
    if (q) {
      const hay = (u.name + ' ' + u.tags.join(' ') + ' '
        + u.abilities.map(a => a.name + ' ' + (a.desc || '')).join(' ') + ' '
        + u.passives.join(' ')).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const sorters = {
    name: (a, b) => a.name.localeCompare(b.name),
    depth: (a, b) => (a.depth || 99) - (b.depth || 99) || a.name.localeCompare(b.name),
    hp: (a, b) => b.hp - a.hp || a.name.localeCompare(b.name),
  };
  list.sort(sorters[MON.sort]);
  const grid = $('#mon-grid');
  grid.innerHTML = '';
  if (!list.length) grid.appendChild(el('div', 'empty', 'No monsters match.'));
  list.forEach(u => grid.appendChild(monsterCard(u)));
  $('#mon-count').textContent = `${list.length} of ${Object.keys(DATA.units).length} units`;
}

// ---------------------------------------------------------------------------
// COMPONENT INVENTORY ("I have 2 Chaos Seeds and 1 Blood Basin")
// ---------------------------------------------------------------------------
let INVENTORY = {};        // component name -> count
let CP_BY_NAME = {};       // name -> component object
const INV_KEY = 'rw3_inventory';

function loadInv() {
  try { INVENTORY = JSON.parse(localStorage.getItem(INV_KEY)) || {}; } catch (e) { INVENTORY = {}; }
}
function saveInv() {
  try { localStorage.setItem(INV_KEY, JSON.stringify(INVENTORY)); } catch (e) {}
}
function invRefresh() { renderInventory(); renderComponents(); renderBuild(); renderEquipment(); }
function invChange(name, d) {
  const n = (INVENTORY[name] || 0) + d;
  if (n <= 0) delete INVENTORY[name]; else INVENTORY[name] = n;
  saveInv();
  invRefresh();
}
function invRemove(name) { delete INVENTORY[name]; saveInv(); invRefresh(); }
function invClear() { INVENTORY = {}; saveInv(); invRefresh(); }

// Essence pool derived from the component inventory (each component contributes
// one of each of its tags per copy held).
function inventoryEssences() {
  const tot = {};
  for (const [name, n] of Object.entries(INVENTORY)) {
    const c = CP_BY_NAME[name];
    if (!c) continue;
    for (const t of c.tags) { if (t === 'Any') continue; tot[t] = (tot[t] || 0) + n; }
  }
  return tot;
}
function invChipsHtml() {
  return Object.keys(INVENTORY)
    .sort((a, b) => { const ca = CP_BY_NAME[a], cb = CP_BY_NAME[b]; return (ca && cb ? (ca.tier - cb.tier || a.localeCompare(b)) : a.localeCompare(b)); })
    .map(name => {
      const c = CP_BY_NAME[name];
      const ic = c ? `<img src="icons/components/${esc(c.icon)}${IV}" onerror="this.remove()">` : '';
      return `<span class="inv-chip">${ic}<span class="inv-name">${esc(name)}</span>
        <span class="inv-qty"><button data-inv="${esc(name)}" data-d="-1">−</button><b>${INVENTORY[name]}</b><button data-inv="${esc(name)}" data-d="1">＋</button></span>
        <button class="inv-rm" data-inv-rm="${esc(name)}" title="Remove">✕</button></span>`;
    }).join('');
}
function essenceChipsHtml() {
  const tot = inventoryEssences();
  return Object.entries(tot).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([t, n]) => `<span class="req" style="color:${TAGCOLOR[t] || 'var(--muted)'}"><span class="n">${n}×</span> ${esc(t)}</span>`).join('');
}
function renderInventory() {
  const names = Object.keys(INVENTORY);
  const has = names.length > 0;
  const count = names.reduce((a, n) => a + INVENTORY[n], 0);
  const chips = invChipsHtml();
  const essences = essenceChipsHtml();

  // Components-tab section
  const cp = $('#cp-inventory');
  if (cp) {
    if (!has) { cp.classList.add('hidden'); cp.innerHTML = ''; }
    else {
      cp.classList.remove('hidden');
      cp.innerHTML = `<div class="inv-head"><span class="inv-title">My components <span class="wl-badge">${count}</span></span><button class="btn-ghost inv-clear">Clear</button></div>
        <div class="inv-chips">${chips}</div>
        <div class="inv-essences"><span class="inv-ess-label">Essence pool:</span> ${essences || '—'}</div>
        <div class="inv-tip"><a class="tablink" data-find-craftable href="#">Find craftable equipment →</a></div>`;
    }
  }
  // The Equipment tab's component pool (renderPool) now reflects the inventory,
  // so the old compact read-only readout is gone.
}
function wireInventory() {
  document.addEventListener('click', e => {
    const inc = e.target.closest && e.target.closest('[data-inv]');
    if (inc) { invChange(inc.dataset.inv, parseInt(inc.dataset.d, 10)); return; }
    const rm = e.target.closest && e.target.closest('[data-inv-rm]');
    if (rm) { invRemove(rm.dataset.invRm); return; }
    const add = e.target.closest && e.target.closest('[data-addcomp]');
    if (add) { invChange(add.dataset.addcomp, 1); return; }
    const cl = e.target.closest && e.target.closest('.inv-clear');
    if (cl) { invClear(); return; }
    const fc = e.target.closest && e.target.closest('[data-find-craftable]');
    if (fc) {
      e.preventDefault();
      switchTab('equipment');
      if (!EQ.craftableOnly) { EQ.craftableOnly = true; const b = $('#eq-craftable'); if (b) b.classList.add('active'); renderEquipment(); }
      return;
    }
    const go = e.target.closest && e.target.closest('[data-goto]');
    if (go) { e.preventDefault(); switchTab(go.dataset.goto); return; }
  });
}

// ---------------------------------------------------------------------------
// CRAFTING LOGIC
// ---------------------------------------------------------------------------
// Single-item craftability from a flat essence pool. Because a single recipe
// may draw from the entire inventory and any unused essences of a committed
// component are simply wasted, this flat check is exact for one item.
// returns {ok, missing} where missing is how many essences short.
function evalRecipe(recipe, pool) {
  const avail = { ...pool };
  let anyNeed = 0, missing = 0;
  for (const [tag, n] of recipe) {
    if (tag === 'Any') { anyNeed += n; continue; }
    const have = avail[tag] || 0;
    const use = Math.min(have, n);
    avail[tag] = have - use;
    if (use < n) missing += (n - use);
  }
  let leftover = 0;
  for (const k in avail) leftover += avail[k];
  if (leftover < anyNeed) missing += (anyNeed - leftover);
  return { ok: missing === 0, missing };
}

function recipeNeeds(recipe) {
  const specifics = {}; let anyNeed = 0, total = 0;
  for (const [tag, n] of recipe) {
    total += n;
    if (tag === 'Any') anyNeed += n; else specifics[tag] = (specifics[tag] || 0) + n;
  }
  return { specifics, anyNeed, total };
}

// Crafting commits WHOLE components: a component's full tag set is spent on one
// recipe (extra tags wasted, never shared). Greedily satisfy one recipe from a
// pool of component instances; returns which were used + remaining shortfalls.
function satisfyFromPool(recipe, pool, avail) {
  const { specifics, total } = recipeNeeds(recipe);
  const need = { ...specifics };
  const used = [];
  let E = 0;
  // Phase 1: cover specific tags, preferring components that cover the most
  // still-needed tags with the least waste.
  while (Object.values(need).some(v => v > 0)) {
    let best = -1, bestCov = 0, bestWaste = Infinity;
    for (const i of avail) {
      const tags = pool[i].tags;
      let cov = 0;
      for (const t of tags) if (need[t] > 0) cov++;
      if (cov <= 0) continue;
      const waste = tags.length - cov;
      if (cov > bestCov || (cov === bestCov && waste < bestWaste)) { best = i; bestCov = cov; bestWaste = waste; }
    }
    if (best < 0) break;                 // cannot cover remaining specifics
    avail.delete(best); used.push(best); E += pool[best].tags.length;
    for (const t of pool[best].tags) if (need[t] > 0) need[t]--;
  }
  const specificsMet = Object.values(need).every(v => v <= 0);
  // Phase 2: commit more components (smallest first to minimize waste) until we
  // have enough total essences to also fill the Any slots.
  if (specificsMet) {
    while (E < total && avail.size) {
      let best = -1, bestLen = Infinity;
      for (const i of avail) { const l = pool[i].tags.length; if (l < bestLen) { bestLen = l; best = i; } }
      avail.delete(best); used.push(best); E += pool[best].tags.length;
    }
  }
  return { ok: specificsMet && E >= total, used, need, E, total, specificsMet };
}

function expandInventory() {
  const pool = [];
  for (const [name, n] of Object.entries(INVENTORY)) {
    const c = CP_BY_NAME[name];
    if (!c) continue;
    const tags = c.tags.filter(t => t !== 'Any');
    for (let i = 0; i < n; i++) pool.push({ name, tags });
  }
  return pool;
}

// Allocate the inventory across all build items (no component shared between
// items). Best-effort: hardest recipes first. Returns per-item status + leftovers.
function planBuild() {
  const pool = expandInventory();
  const avail = new Set(pool.map((_, i) => i));
  const names = [...WISH];
  const order = names.slice().sort((a, b) => {
    const ea = EQ_BY_NAME[a], eb = EQ_BY_NAME[b];
    return (eb ? eb.recipe_cost : 0) - (ea ? ea.recipe_cost : 0);
  });
  const status = {};
  for (const name of order) {
    const e = EQ_BY_NAME[name];
    if (!e) { status[name] = { ok: false, need: {}, E: 0, total: 0, specificsMet: false, usedNames: [] }; continue; }
    // Trial on a copy; only consume components from the real pool if it succeeds.
    const r = satisfyFromPool(e.recipe, pool, new Set(avail));
    if (r.ok) r.used.forEach(i => avail.delete(i));
    status[name] = { ...r, usedNames: r.ok ? r.used.map(i => pool[i].name) : [] };
  }
  const leftover = {};
  for (const i of avail) leftover[pool[i].name] = (leftover[pool[i].name] || 0) + 1;
  return { status, leftover, hasInventory: pool.length > 0 };
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
const TAB_SCROLL = {};
let currentTab = 'equipment';
function switchTab(name) {
  if (name === currentTab) return;
  TAB_SCROLL[currentTab] = window.scrollY;   // remember where we were
  $$('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
  currentTab = name;
  location.hash = name;
  window.scrollTo(0, TAB_SCROLL[name] || 0); // restore this tab's last position
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  DATA = await fetch('data.json').then(r => r.json());
  COLORS = DATA.colors;
  UNITS = DATA.units || {};
  for (const [name, info] of Object.entries(DATA.tags.all)) TAGCOLOR[name] = rgb(info.color);
  COMPONENT_TAGS = DATA.tags.component_tags.filter(t => t !== 'Any').sort();
  STAT_META = DATA.stat_meta || {};
  if (DATA.generated) $('#last-updated').textContent = DATA.generated;
  injectSpriteKeyframes();
  for (const e of DATA.equipment) {
    EQ_BY_NAME[e.name] = e;
    if (e.id != null) { EQ_ID_BY_NAME[e.name] = e.id; EQ_NAME_BY_ID[e.id] = e.name; }
  }
  for (const c of DATA.components) CP_BY_NAME[c.name] = c;
  for (const s of DATA.spells) SPELL_BY_NAME[s.name] = s;
  loadWishFromUrl();
  loadInv();
  loadAssign();
  wireTooltips();
  wireBuild();
  wireInventory();

  // tabs
  $$('#tabs button').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

  // --- Equipment controls ---
  EQ.slots = buildChips($('#eq-slots'), DATA.slots, { onChange: renderEquipment, activeColor: () => '#fff' });
  EQ.tags = buildChips($('#eq-tags'), COMPONENT_TAGS, {
    dot: t => TAGCOLOR[t] || 'var(--muted)',
    activeColor: t => TAGCOLOR[t] || 'var(--accent)',
    onChange: renderEquipment
  });
  makeStatSearch({ inputEl: $('#eq-search'), filtersEl: $('#eq-filters'), state: EQ, getDataset: () => DATA.equipment, render: renderEquipment });
  $('#eq-sort').addEventListener('change', e => { EQ.sort = e.target.value; renderEquipment(); });
  $('#eq-craftable').addEventListener('click', e => {
    EQ.craftableOnly = !EQ.craftableOnly;
    e.target.classList.toggle('active', EQ.craftableOnly);
    renderEquipment();
  });

  // --- Components controls ---
  CP.tiers = buildChips($('#cp-tiers'), ['1', '2', '3'], { label: t => 'Tier ' + t, onChange: renderComponents, activeColor: () => '#fff' });
  CP.effects = buildChips($('#cp-effects'), ['pickup', 'craft'], {
    label: e => e === 'pickup' ? 'On Pickup' : 'On Craft',
    activeColor: e => e === 'craft' ? '#caa24a' : '#5aa9ff',
    onChange: renderComponents
  });
  CP.tags = buildChips($('#cp-tags'), COMPONENT_TAGS, {
    dot: t => TAGCOLOR[t] || 'var(--muted)',
    activeColor: t => TAGCOLOR[t] || 'var(--accent)',
    onChange: renderComponents
  });
  $('#cp-search').addEventListener('input', e => { CP.search = e.target.value; renderComponents(); });

  // --- Spells controls ---
  const levels = [...new Set(DATA.spells.map(s => s.level))].sort((a, b) => a - b).map(String);
  SP.levels = buildChips($('#sp-levels'), levels, { label: l => 'Lv ' + l, onChange: renderSpells, activeColor: () => '#fff' });
  const spellTags = [...new Set(DATA.spells.flatMap(s => s.tags))].sort();
  SP.tags = buildChips($('#sp-tags'), spellTags, {
    dot: t => TAGCOLOR[t] || 'var(--muted)',
    activeColor: t => TAGCOLOR[t] || 'var(--accent)',
    onChange: renderSpells
  });
  makeStatSearch({ inputEl: $('#sp-search'), filtersEl: $('#sp-filters'), state: SP, getDataset: () => DATA.spells, render: renderSpells });

  // --- Monsters controls ---
  MON.types = buildChips($('#mon-types'), ['monster', 'summon'], {
    label: t => t === 'monster' ? 'Monster' : 'Summonable',
    onChange: renderMonsters, activeColor: () => '#fff'
  });
  MON.moves = buildChips($('#mon-moves'), ['Flying', 'Immobile', 'Burrowing'], {
    onChange: renderMonsters, activeColor: () => '#fff'
  });
  const monTags = [...new Set(Object.values(DATA.units).flatMap(u => u.tags))].sort();
  MON.tags = buildChips($('#mon-tags'), monTags, {
    dot: t => TAGCOLOR[t] || 'var(--muted)',
    activeColor: t => TAGCOLOR[t] || 'var(--accent)',
    onChange: renderMonsters
  });
  $('#mon-search').addEventListener('input', e => { MON.search = e.target.value; renderMonsters(); });
  $('#mon-sort').addEventListener('change', e => { MON.sort = e.target.value; renderMonsters(); });

  // render all
  renderBuild();
  renderInventory();
  renderEquipment(); renderComponents(); renderSpells(); renderMonsters();

  // initial tab from hash
  const hash = location.hash.slice(1);
  if (['equipment', 'components', 'spells', 'monsters'].includes(hash)) switchTab(hash);
}

init();
