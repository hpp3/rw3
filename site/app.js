'use strict';

let DATA = null;
let COLORS = {};
let TAGCOLOR = {};        // Tag name -> "rgb(...)"
let COMPONENT_TAGS = [];  // recipe-able tags excluding "Any"
let IV = '';              // icon cache-busting suffix (?v=<build date>), set in init

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
function summonRow(summons) {
  if (!summons || !summons.length) return '';
  const chips = summons.map(n => `<span class="summon-chip" data-unit="${esc(n)}" tabindex="0"><img src="icons/units/${esc(UNITS[n] ? UNITS[n].icon : '')}${IV}" onerror="this.remove()">${esc(n)}</span>`).join('');
  return `<div class="summon-row"><span class="section-label">Summons</span><div class="summon-chips">${chips}</div></div>`;
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
      <img class="uicon" src="icons/units/${esc(u.icon)}${IV}" onerror="this.style.visibility='hidden'">
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
  const t = ensureTip();
  t.innerHTML = html;
  t.style.display = 'block';
  positionTip(x, y);
}
function hideTip() { if (unitTip) unitTip.style.display = 'none'; }

const TIP_SELECTOR = '.summon-chip, [data-eqtip], .xref';
function tipTrigger(target) { return target.closest && target.closest(TIP_SELECTOR); }
function tipHtml(node) {
  if (node.dataset.unit != null) return renderUnitSheet(node.dataset.unit);
  if (node.dataset.eqtip != null) return renderEquipSheet(node.dataset.eqtip);
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
      ? 'Add components on the Components tab to see what you can craft.'
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
const WISH_KEY = 'rw3_wishlist';

function loadWish() {
  try {
    const a = JSON.parse(localStorage.getItem(WISH_KEY));
    WISH = new Set(Array.isArray(a) ? a : (a ? Object.keys(a) : []));
  } catch (e) { WISH = new Set(); }
}
function saveWish() {
  try { localStorage.setItem(WISH_KEY, JSON.stringify([...WISH])); } catch (e) {}
}
function wishToggle(name) {
  if (WISH.has(name)) WISH.delete(name); else WISH.add(name);
  saveWish();
  renderWishlist();
  renderEquipment();   // refresh button states
}
function wishTotals() {
  const tot = {}; let any = 0;
  for (const name of WISH) {
    const e = EQ_BY_NAME[name];
    if (!e) continue;
    for (const [tag, n] of e.recipe) {
      if (tag === 'Any') any += n;
      else tot[tag] = (tot[tag] || 0) + n;
    }
  }
  return { tot, any };
}
function compMini(name, count) {
  const c = CP_BY_NAME[name];
  const ic = c ? `<img src="icons/components/${esc(c.icon)}${IV}" onerror="this.remove()">` : '';
  const cnt = count && count > 1 ? `${count}× ` : '';
  return `<span class="comp-mini">${ic}${cnt}${esc(name)}</span>`;
}
function recipeChipsPlanned(recipe, st) {
  const { anyNeed, total } = recipeNeeds(recipe);
  const need = st.need || {};
  const anyCovered = st.specificsMet ? Math.max(0, Math.min(anyNeed, st.E - (total - anyNeed))) : 0;
  return recipe.map(([tag, n]) => {
    if (tag === 'Any') {
      const ok = anyCovered >= n;
      return `<span class="req any ${ok ? 'rok' : 'rmiss'}">${ok ? '✓ ' : ''}<span class="n">${ok ? n : anyCovered + '/' + n}×</span> Any</span>`;
    }
    const covered = n - (need[tag] || 0);
    const ok = covered >= n;
    const col = TAGCOLOR[tag] || 'var(--muted)';
    return `<span class="req ${ok ? 'rok' : 'rmiss'}"${ok ? ` style="color:${col}"` : ''}>${ok ? '✓ ' : ''}<span class="n">${ok ? n : covered + '/' + n}×</span> ${esc(tag)}</span>`;
  }).join('');
}
function renderWishlist() {
  const panel = $('#wishlist');
  const names = [...WISH];
  if (!names.length) { panel.classList.add('hidden'); return; }
  panel.classList.remove('hidden');

  $('#wl-count').textContent = names.length;

  const { tot, any } = wishTotals();
  const specific = Object.values(tot).reduce((a, b) => a + b, 0);
  const totalsHtml = Object.entries(tot)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([tag, n]) => `<span class="req" style="color:${TAGCOLOR[tag] || 'var(--muted)'}"><span class="n">${n}×</span> ${esc(tag)}</span>`)
    .join('');
  const anyHtml = any ? `<span class="req any"><span class="n">${any}×</span> Any</span>` : '';
  const totalLabel = `<span class="wl-total-label">${specific + any} essence${specific + any !== 1 ? 's' : ''} to craft all</span>`;

  const plan = planBuild();
  let summary = '';
  if (plan.hasInventory) {
    const okCount = names.filter(n => plan.status[n] && plan.status[n].ok).length;
    summary = `<span class="wl-craftcount ${okCount === names.length ? 'all' : ''}">${okCount}/${names.length} craftable with your components</span>`;
  }
  $('#wl-totals').innerHTML = totalsHtml + anyHtml + totalLabel + summary;

  $('#wl-items').innerHTML = names
    .sort((a, b) => EQ_BY_NAME[a] && EQ_BY_NAME[b] ? (EQ_BY_NAME[a].recipe_cost - EQ_BY_NAME[b].recipe_cost || a.localeCompare(b)) : 0)
    .map(name => {
      const e = EQ_BY_NAME[name];
      const slot = e ? e.slot : '';
      const ic = e ? iconImg('equipment', e).replace('class="icon"', 'class="wl-ic"').replace('class="icon ', 'class="wl-ic ') : '';
      const st = plan.status[name];
      const planned = plan.hasInventory && e;
      const rcp = planned ? recipeChipsPlanned(e.recipe, st) : (e ? recipeChips(e.recipe) : '');
      const badge = planned ? (st.ok ? '<span class="wl-ok">✓ craftable</span>' : '<span class="wl-miss">✗ short</span>') : '';
      const uses = (planned && st.ok && st.usedNames.length)
        ? `<div class="wl-uses"><span class="wl-uses-label">uses</span> ${st.usedNames.map(n => compMini(n)).join('')}</div>` : '';
      return `<div class="wl-item${planned ? (st.ok ? ' is-ok' : ' is-miss') : ''}">
        ${ic}
        <div class="wl-info">
          <div class="wl-row1">
            <span class="wl-name" data-eqtip="${esc(name)}" tabindex="0">${esc(name)}</span>
            <span class="badge slot">${esc(slot)}</span>
            <span class="wl-cost">cost ${e ? e.recipe_cost : '?'}</span>
            ${badge}
          </div>
          <div class="wl-recipe">${rcp}</div>
          ${uses}
        </div>
        <button class="wl-remove" data-wish-remove="${esc(name)}" title="Remove from build">✕</button>
      </div>`;
    }).join('');

  const loEl = $('#wl-leftover');
  if (loEl) {
    const lo = plan.hasInventory ? Object.entries(plan.leftover) : [];
    if (lo.length) {
      loEl.classList.remove('hidden');
      loEl.innerHTML = `<span class="wl-uses-label">Unused</span> ${lo.sort((a, b) => a[0].localeCompare(b[0])).map(([n, c]) => compMini(n, c)).join('')}`;
    } else { loEl.classList.add('hidden'); loEl.innerHTML = ''; }
  }
}

function wireWishlist() {
  // Add buttons on equipment cards (delegated; cards are re-rendered)
  document.addEventListener('click', e => {
    const add = e.target.closest && e.target.closest('.add-build[data-add]');
    if (add) { wishToggle(add.dataset.add); return; }
    const rm = e.target.closest && e.target.closest('.wl-remove');
    if (rm) { wishToggle(rm.dataset.wishRemove); return; }
  });
  $('#wl-clear').addEventListener('click', () => { WISH = new Set(); saveWish(); renderWishlist(); renderEquipment(); });
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
    </div>
    <div class="desc">${linkify(renderMarkup(c.desc), c.refs)}</div>
    ${summonRow(c.summons)}
    <div class="recipe"><button class="add-build${INVENTORY[c.name] ? ' in' : ''}" data-addcomp="${esc(c.name)}">${INVENTORY[c.name] ? `✓ In pool ×${INVENTORY[c.name]}` : '＋ Add to pool'}</button></div>`;
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
      <img class="mon-art" loading="lazy" src="icons/units/${esc(u.icon)}${IV}" onerror="this.style.visibility='hidden'">
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
function invRefresh() { renderInventory(); renderComponents(); renderWishlist(); renderEquipment(); }
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
        <div class="inv-tip">On the <a class="tablink" data-goto="equipment">Equipment</a> tab, toggle <b>Craftable only</b> to see what these can make.</div>`;
    }
  }

  // Compact read-only readout on the Equipment tab
  const eq = $('#eq-inv');
  if (eq) {
    if (!has) { eq.classList.add('hidden'); eq.innerHTML = ''; }
    else {
      eq.classList.remove('hidden');
      const essTotal = Object.values(inventoryEssences()).reduce((a, b) => a + b, 0);
      const comps = Object.keys(INVENTORY)
        .sort((a, b) => { const ca = CP_BY_NAME[a], cb = CP_BY_NAME[b]; return (ca && cb ? (ca.tier - cb.tier || a.localeCompare(b)) : a.localeCompare(b)); })
        .map(name => {
          const c = CP_BY_NAME[name];
          const ic = c ? `<img src="icons/components/${esc(c.icon)}${IV}" onerror="this.remove()">` : '';
          return `<span class="eq-comp" title="${esc(name)}">${ic}<span class="eq-comp-n">${esc(name)}</span><span class="eq-comp-q">×${INVENTORY[name]}</span></span>`;
        }).join('');
      eq.innerHTML = `<span class="eq-inv-label">My components</span><div class="eq-inv-comps">${comps}</div>`
        + `<span class="eq-inv-label">${essTotal} essence${essTotal !== 1 ? 's' : ''}</span><div class="eq-inv-ess">${essences || '—'}</div>`
        + `<a class="tablink eq-inv-edit" data-goto="components">edit</a>`;
    }
  }
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
  DATA = await fetch('data.json', { cache: 'no-cache' }).then(r => r.json());
  COLORS = DATA.colors;
  UNITS = DATA.units || {};
  for (const [name, info] of Object.entries(DATA.tags.all)) TAGCOLOR[name] = rgb(info.color);
  COMPONENT_TAGS = DATA.tags.component_tags.filter(t => t !== 'Any').sort();
  STAT_META = DATA.stat_meta || {};
  IV = '?v=' + (DATA.generated || '1');
  if (DATA.generated) $('#last-updated').textContent = DATA.generated;
  for (const e of DATA.equipment) EQ_BY_NAME[e.name] = e;
  for (const c of DATA.components) CP_BY_NAME[c.name] = c;
  for (const s of DATA.spells) SPELL_BY_NAME[s.name] = s;
  loadWish();
  loadInv();
  wireTooltips();
  wireWishlist();
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
  renderWishlist();
  renderInventory();
  renderEquipment(); renderComponents(); renderSpells(); renderMonsters();

  // initial tab from hash
  const hash = location.hash.slice(1);
  if (['equipment', 'components', 'spells', 'monsters'].includes(hash)) switchTab(hash);
}

init();
