'use strict';

let DATA = null;
let COLORS = {};
let TAGCOLOR = {};        // Tag name -> "rgb(...)"
let COMPONENT_TAGS = [];  // recipe-able tags excluding "Any"

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
  return `<img class="icon" loading="lazy" src="icons/${cat}/${esc(item.icon)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'icon placeholder',textContent:'✦'}))">`;
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
  const chips = summons.map(n => `<span class="summon-chip" data-unit="${esc(n)}" tabindex="0"><img src="icons/units/${esc(UNITS[n] ? UNITS[n].icon : '')}" onerror="this.remove()">${esc(n)}</span>`).join('');
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
      <img class="uicon" src="icons/units/${esc(u.icon)}" onerror="this.style.visibility='hidden'">
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

const TIP_SELECTOR = '.summon-chip, [data-eqtip]';
function tipTrigger(target) { return target.closest && target.closest(TIP_SELECTOR); }
function tipHtml(node) {
  if (node.dataset.unit != null) return renderUnitSheet(node.dataset.unit);
  if (node.dataset.eqtip != null) return renderEquipSheet(node.dataset.eqtip);
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
  // touch / keyboard
  document.addEventListener('click', e => {
    const c = tipTrigger(e.target);
    if (c) {
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
      <img class="uicon" src="icons/equipment/${esc(e.icon)}" onerror="this.style.visibility='hidden'">
      <div class="uhmeta">
        <div class="uname">${esc(e.name)}</div>
        <div class="card-meta"><span class="badge slot">${esc(e.slot)}</span>${e.tags.map(tagPill).join('')}</div>
      </div>
    </div>
    ${desc}${bonuses}
  </div>`;
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
  const recipe = recipeChips(e.recipe);
  const bonuses = e.bonuses.length
    ? `<div class="bonuses">${e.bonuses.map(b => `<div class="b">${renderMarkup(b)}</div>`).join('')}</div>` : '';
  const desc = e.desc ? `<div class="desc">${renderMarkup(e.desc)}</div>` : '';
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

const EQ = { search: '', slots: null, tags: null, sort: 'cost' };
function renderEquipment() {
  const q = EQ.search.toLowerCase();
  const slots = EQ.slots, tags = EQ.tags;
  let list = DATA.equipment.filter(e => {
    if (slots.size && !slots.has(e.slot)) return false;
    if (EQ.statFilters && !passesStatFilters(e, EQ.statFilters)) return false;
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
  if (!list.length) grid.appendChild(el('div', 'empty', 'No equipment matches those filters.'));
  list.forEach(e => grid.appendChild(equipmentCard(e)));
  $('#eq-count').textContent = `${list.length} of ${DATA.equipment.length} items`;
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
  const totalLabel = `<span class="wl-total-label">${specific + any} essence${specific + any !== 1 ? 's' : ''} (${specific} specific${any ? ` + ${any} any` : ''})</span>`;
  $('#wl-totals').innerHTML = totalsHtml + anyHtml + totalLabel;

  $('#wl-items').innerHTML = names
    .sort((a, b) => EQ_BY_NAME[a] && EQ_BY_NAME[b] ? (EQ_BY_NAME[a].recipe_cost - EQ_BY_NAME[b].recipe_cost || a.localeCompare(b)) : 0)
    .map(name => {
      const e = EQ_BY_NAME[name];
      const slot = e ? e.slot : '';
      const ic = e ? iconImg('equipment', e).replace('class="icon"', 'class="wl-ic"').replace('class="icon ', 'class="wl-ic ') : '';
      const rcp = e ? recipeChips(e.recipe) : '';
      return `<div class="wl-item">
        ${ic}
        <div class="wl-info">
          <div class="wl-row1">
            <span class="wl-name" data-eqtip="${esc(name)}" tabindex="0">${esc(name)}</span>
            <span class="badge slot">${esc(slot)}</span>
            <span class="wl-cost">cost ${e ? e.recipe_cost : '?'}</span>
          </div>
          <div class="wl-recipe">${rcp}</div>
        </div>
        <button class="wl-remove" data-wish-remove="${esc(name)}" title="Remove from build">✕</button>
      </div>`;
    }).join('');
}

function wireWishlist() {
  // Add buttons on equipment cards (delegated; cards are re-rendered)
  document.addEventListener('click', e => {
    const add = e.target.closest && e.target.closest('.add-build');
    if (add) { wishToggle(add.dataset.add); return; }
    const rm = e.target.closest && e.target.closest('.wl-remove');
    if (rm) { wishToggle(rm.dataset.wishRemove); return; }
  });
  $('#wl-clear').addEventListener('click', () => { WISH = new Set(); saveWish(); renderWishlist(); renderEquipment(); });
  $('#wl-tocraft').addEventListener('click', () => {
    const { tot, any } = wishTotals();
    for (const k in POOL) delete POOL[k];
    for (const [tag, n] of Object.entries(tot)) POOL[tag] = n;
    syncPoolUI();
    switchTab('craft');
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
    </div>
    <div class="desc">${renderMarkup(c.desc)}</div>
    ${summonRow(c.summons)}
    <div class="recipe"><button class="chip" data-addpool>＋ Add tags to craft pool</button></div>`;
  card.querySelector('[data-addpool]').addEventListener('click', () => {
    c.tags.forEach(t => { if (t !== 'Any') POOL[t] = (POOL[t] || 0) + 1; });
    syncPoolUI();
    switchTab('craft');
  });
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
  const stats = Object.entries(s.stats)
    .map(([k, v]) => `<span class="stat">${STAT_LABEL[k] || k} <b>${v}</b></span>`).join('');
  const dt = s.damage_type.length ? `<div class="card-meta">${s.damage_type.map(tagPill).join('')}</div>` : '';
  const upg = s.upgrades.length ? `
    <details class="upgrades"><summary>${s.upgrades.length} upgrade${s.upgrades.length > 1 ? 's' : ''}</summary>
      ${s.upgrades.map(u => `<div class="upg"><span class="uh">${esc(u.name)}</span><span class="ul">Lv ${u.level}</span><div class="desc">${renderMarkup(u.desc)}</div></div>`).join('')}
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
    <div class="desc">${renderMarkup(s.desc)}</div>
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
// CRAFT CALCULATOR
// ---------------------------------------------------------------------------
const POOL = {};            // tag -> count
const CRAFT = { search: '', slots: null, slack: 0 };

// returns {ok, missing} where missing is how many tags short (0 = exact craftable)
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

function buildPoolSteppers() {
  const box = $('#pool-steppers');
  box.innerHTML = '';
  COMPONENT_TAGS.forEach(tag => {
    const row = el('div', 'stepper');
    row.dataset.tag = tag;
    const col = TAGCOLOR[tag] || 'var(--muted)';
    row.innerHTML = `
      <span class="lbl"><span class="dot" style="background:${col}"></span>${esc(tag)}</span>
      <button data-d="-1">−</button>
      <span class="val">0</span>
      <button data-d="1">＋</button>`;
    row.querySelector('[data-d="-1"]').addEventListener('click', () => { POOL[tag] = Math.max(0, (POOL[tag] || 0) - 1); syncPoolUI(); });
    row.querySelector('[data-d="1"]').addEventListener('click', () => { POOL[tag] = (POOL[tag] || 0) + 1; syncPoolUI(); });
    box.appendChild(row);
  });
}
function syncPoolUI() {
  $$('#pool-steppers .stepper').forEach(row => {
    const tag = row.dataset.tag;
    const v = POOL[tag] || 0;
    row.querySelector('.val').textContent = v;
    row.classList.toggle('has', v > 0);
  });
  renderCraft();
}
function renderCraft() {
  const total = Object.values(POOL).reduce((a, b) => a + b, 0);
  const slack = CRAFT.slack;
  const q = CRAFT.search.toLowerCase();
  const grid = $('#craft-grid');
  grid.innerHTML = '';
  if (total === 0) {
    grid.appendChild(el('div', 'empty', 'Add some tags to your pool (left) or click “Add tags to craft pool” on a component.'));
    $('#craft-count').textContent = '';
    return;
  }
  let results = [];
  for (const e of DATA.equipment) {
    if (CRAFT.slots.size && !CRAFT.slots.has(e.slot)) continue;
    if (q) {
      const hay = (e.name + ' ' + e.desc + ' ' + e.bonuses.join(' ')).toLowerCase();
      if (!hay.includes(q)) continue;
    }
    const r = evalRecipe(e.recipe, POOL);
    if (r.missing <= slack) results.push({ e, missing: r.missing });
  }
  results.sort((a, b) => a.missing - b.missing || b.e.recipe_cost - a.e.recipe_cost || a.e.name.localeCompare(b.e.name));
  if (!results.length) {
    grid.appendChild(el('div', 'empty', 'Nothing craftable from this pool yet.'));
  } else {
    results.forEach(({ e, missing }) => {
      const card = equipmentCard(e);
      const tag = el('div', 'craftable-tag' + (missing ? ' slack' : ''));
      tag.textContent = missing ? `missing ${missing}` : 'craftable';
      card.appendChild(tag);
      grid.appendChild(card);
    });
  }
  const exact = results.filter(r => r.missing === 0).length;
  $('#craft-count').textContent = `${total} tags in pool · ${exact} craftable now` + (slack ? ` · ${results.length - exact} within reach` : '');
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
function switchTab(name) {
  $$('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
  location.hash = name;
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
  if (DATA.generated) $('#last-updated').textContent = DATA.generated;
  for (const e of DATA.equipment) EQ_BY_NAME[e.name] = e;
  loadWish();
  wireTooltips();
  wireWishlist();

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

  // --- Craft calculator ---
  CRAFT.slots = buildChips($('#craft-slots'), DATA.slots, { onChange: renderCraft, activeColor: () => '#fff' });
  $('#craft-search').addEventListener('input', e => { CRAFT.search = e.target.value; renderCraft(); });
  $('#craft-slack').addEventListener('change', e => { CRAFT.slack = parseInt(e.target.value, 10); renderCraft(); });
  $('#pool-clear').addEventListener('click', () => { for (const k in POOL) delete POOL[k]; syncPoolUI(); });
  buildPoolSteppers();

  // render all
  renderWishlist();
  renderEquipment(); renderComponents(); renderSpells(); renderCraft();

  // initial tab from hash
  const hash = location.hash.slice(1);
  if (['equipment', 'craft', 'components', 'spells'].includes(hash)) switchTab(hash);
}

init();
