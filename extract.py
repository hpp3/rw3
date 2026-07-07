"""
Extract Rift Wizard 3 spell / equipment / component data into a JSON file
for the static browser resource. Reads ONLY from the game install dir;
writes only into this project's site/ folder.
"""
import os, sys, json, ast, inspect, textwrap, re, random, types

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

# Headless stub for SteamAdapter. The final-boss buffs (FinalBosses.ForcedRespawn,
# SnowQueenUnseated) only *store* SteamAdapter callables (unlock_achievement /
# unlock_bestiary) and never invoke them during extraction. Importing the real
# module drags in LevelGen -> Game (whose module-level achievement check is a
# circular import back into the half-initialised SteamAdapter) plus `steamworks`
# (absent from the build venv). Same headless-shim spirit as the SDL dummies.
class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        return lambda *a, **k: None
sys.modules.setdefault('SteamAdapter', _StubModule('SteamAdapter'))

GAME = r"E:\SteamLibrary\steamapps\common\Rift Wizard 3"
HERE = os.path.dirname(os.path.abspath(__file__))

import ids as ids_mod  # stable append-only id assignment (HERE-relative; safe before chdir)
import gameinfo        # Steam branch/build detection (HERE-relative; safe before chdir)
OUT_DIR = os.path.join(HERE, "site")
os.makedirs(OUT_DIR, exist_ok=True)

# Which Steam branch/build is checked out right now (live vs beta). Stamped onto
# the output and used to name the file + upsert versions.json. See gameinfo.py.
BRANCH = gameinfo.branch_info(GAME)

sys.path.insert(0, GAME)
os.chdir(GAME)  # so rl_data/loc text json loads

# Import order matters (circular imports): Equipment pulls Level/CommonContent/Monsters/Spells/Components.
import Equipment
import Spells
import Components
import text
from Level import (resolve_text, Tags, attr_colors, format_attr, tag_key, attr_key,
                   tag_label, Spell, Equipment as EquipmentBase, Component as ComponentBase,
                   Buff as BuffBase, stat_names)

# ---------------------------------------------------------------------------
# Color map: replicate RiftWizard3.tooltip_colors without importing the UI.
# ---------------------------------------------------------------------------
def to_tup(c):
    return [c.r, c.g, c.b]

COLOR_DAMAGE = type(Tags.Fire.color)(215, 0, 0)
Color = type(Tags.Fire.color)

tooltip_colors = {}
for tag in Tags:
    tooltip_colors[tag.name.lower()] = to_tup(tag.color)
for k, v in attr_colors.items():
    tooltip_colors[k] = to_tup(v)
tooltip_colors['default'] = [255, 255, 255]

# manual additions mirrored from RiftWizard3.py
_manual = {
    'petrify': Tags.Construct, 'petrified': Tags.Construct, 'petrifies': Tags.Construct,
    'frozen': Tags.Ice, 'freezes': Tags.Ice, 'freeze': Tags.Ice,
    'stunned': Tags.Physical, 'stun': Tags.Physical, 'stuns': Tags.Physical,
    'poisoned': Tags.Poison, 'poisons': Tags.Poison,
    'glassify': Tags.Glass, 'glassified': Tags.Glass, 'glassed': Tags.Glass,
    'sleep': Tags.Arcane, 'sleeps': Tags.Arcane,
    'silence': Tags.Arcane, 'silenced': Tags.Arcane, 'silences': Tags.Arcane,
    'necrosis': Tags.Dark, 'fear': Tags.Dark, 'fears': Tags.Dark, 'feared': Tags.Dark,
    'blind': Tags.Eye, 'blinds': Tags.Eye, 'blinded': Tags.Eye,
    'bleed': Tags.Blood, 'bleeds': Tags.Blood, 'bleeding': Tags.Blood, 'hemorrhage': Tags.Blood,
    'requires_los': Tags.Translocation, 'ally': Tags.Conjuration, 'hp_cost': Tags.Blood,
}
for k, tg in _manual.items():
    tooltip_colors[k] = to_tup(tg.color)
tooltip_colors['berserk'] = to_tup(COLOR_DAMAGE)
tooltip_colors['berserked'] = to_tup(COLOR_DAMAGE)
tooltip_colors['berserks'] = to_tup(COLOR_DAMAGE)
tooltip_colors['enemy'] = to_tup(COLOR_DAMAGE)
tooltip_colors['wizard'] = [2, 136, 209]
tooltip_colors['quick_cast'] = [255, 255, 255]
tooltip_colors['max_channel'] = [153, 51, 102]

# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------
SLOT_NAMES = {0: "Trinket", 1: "Head", 2: "Body", 3: "Feet", 4: "Weapon"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def rtext(value, fmt=None):
    try:
        return resolve_text(value, fmt=fmt)
    except Exception as e:
        return ""

def asset_filename(get_asset_result):
    # last element + .png, lowercased for the web
    return (get_asset_result[-1] + ".png").lower()

# --- sprite sheet dimensions (for pure-CSS idle animation) ------------------
# Read PNG width/height straight from the IHDR header — no image library needed
# (avoids an SDL/pygame DLL conflict when cwd is the game dir).
import struct
_CHAR_DIR = os.path.join(GAME, "rl_data", "char")
_char_index = None
def _char_path(icon):
    global _char_index
    if _char_index is None:
        _char_index = {}
        for fn in os.listdir(_CHAR_DIR):
            if fn.lower().endswith(".png"):
                _char_index[fn.lower()] = os.path.join(_CHAR_DIR, fn)
    return _char_index.get(icon.lower())

def _png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])   # width, height

def sheet_grid(icon, radius):
    """(columns, rows) of a char spritesheet; idle = last row, cols = idle frames."""
    p = _char_path(icon)
    if not p:
        return (1, 1)
    try:
        w, h = _png_size(p)
    except Exception:
        return (1, 1)
    base = 60 if w % 60 == 0 else 16
    fs = base * (1 + 2 * (radius or 0))
    if fs <= 0 or w % fs or h % fs:
        return (1, 1)
    return (w // fs, h // fs)

def render_bonus_lines(o):
    """Replicate the autogenerated bonus tooltip lines for an equipment/buff."""
    lines = []
    for tag, bonuses in o.tag_bonuses_pct.items():
        for attr, val in bonuses.items():
            lines.append(rtext((text.TAG_PCT_BONUS, {
                "tag_label": tag_label(tag), "tag_key": tag_key(tag),
                "val": int(val), "attr_label": format_attr(attr), "attr_key": attr_key(attr)})))
    for tag, bonuses in o.tag_bonuses.items():
        for attr, val in bonuses.items():
            lines.append(rtext((text.TAG_VAL_BONUS, {
                "tag_label": tag_label(tag), "tag_key": tag_key(tag),
                "val": int(val), "attr_label": format_attr(attr), "attr_key": attr_key(attr)})))
    for attr, val in o.global_bonuses_pct.items():
        tmpl = text.ALL_GAIN_PCT if val >= 0 else text.ALL_LOSE_PCT
        lines.append(rtext((tmpl, {"val": int(val), "attr_label": format_attr(attr), "attr_key": attr_key(attr)})))
    for attr, val in o.global_bonuses.items():
        tmpl = text.ALL_GAIN_VAL if val >= 0 else text.ALL_LOSE_VAL
        lines.append(rtext((tmpl, {"val": int(val), "attr_label": format_attr(attr), "attr_key": attr_key(attr)})))
    for tag, val in o.resists.items():
        if val:
            lines.append(rtext((text.RESIST_VAL, {"val": val, "tag_label": tag_label(tag)})))
    return [l for l in lines if l]

# Mirror of RiftWizard3.tt_attrs, in the game's own order (the UI module isn't
# importable in the build env — no steamworks — same reason tooltip_colors are
# mirrored, §2). This is the game's canonical attribute list: it's what the
# spell examine "Attributes:" section iterates, and the only new_attributes an
# upgrade tooltip surfaces as a text line. Keep it a tuple (order matters for
# spell stat-line display) — `in` membership checks still work.
TT_ATTRS = (
    'num_targets', 'damage', 'duration', 'radius', 'shields', 'shot_cooldown',
    'strikechance', 'cooldown', 'max_channel', 'num_summons', 'minion_health',
    'minion_damage', 'minion_duration', 'minion_range',
)

def upgrade_bonus_lines(u):
    """Replicate the game's auto-generated upgrade tooltip lines — the stat
    deltas the examine panel draws above an upgrade's prose. Pure-stat upgrades
    (e.g. Relentless Cascade: +2 range/+3 charges) have NO prose at all, so
    without these they render blank. Order mirrors RiftWizard3.draw_examine's
    upgrade branch; the colored-vs-plain choice keys off tooltip_colors exactly
    as the game does (attr names are never tag/status keys, so spell/global stat
    lines come out plain — matching the game)."""
    lines = []
    def add(tmpl, **kw): lines.append(rtext((tmpl, kw)))
    for tag, bonuses in u.tag_bonuses_pct.items():
        for attr, val in bonuses.items():
            add(text.TAG_PCT_BONUS, tag_label=tag_label(tag), tag_key=tag_key(tag),
                val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    for tag, bonuses in u.tag_bonuses.items():
        for attr, val in bonuses.items():
            add(text.TAG_VAL_BONUS, tag_label=tag_label(tag), tag_key=tag_key(tag),
                val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    # Per-spell bonuses: the game only shows attrs the target spell actually has.
    for spell, bonuses in u.spell_bonuses_pct.items():
        sp = spell()
        for attr, val in bonuses.items():
            if attr not in sp.stats: continue
            tmpl = text.GAIN_PCT_COLORED if attr in tooltip_colors else text.GAIN_PCT_PLAIN
            add(tmpl, name=sp.name, val=val, attr_label=format_attr(attr), attr_key=attr_key(attr))
    for spell, bonuses in u.spell_bonuses.items():
        sp = spell()
        for attr, val in bonuses.items():
            if attr not in sp.stats: continue
            tmpl = text.GAIN_VAL_COLORED if attr in tooltip_colors else text.GAIN_VAL_PLAIN
            add(tmpl, name=sp.name, val=val, attr_label=format_attr(attr), attr_key=attr_key(attr))
    prereq = getattr(u, 'prereq', None)
    if prereq is not None:
        for attr, val in getattr(u, 'new_attributes', {}).items():
            if attr in TT_ATTRS or attr == 'hp_cost':  # game always colors these
                add(text.GAIN_VAL_COLORED, name=prereq.name, val=val,
                    attr_label=format_attr(attr), attr_key=attr_key(attr))
    for attr, val in u.global_bonuses_pct.items():
        tmpl = text.ALL_GAIN_PCT if val >= 0 else text.ALL_LOSE_PCT
        add(tmpl, val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    for attr, val in u.global_bonuses.items():
        tmpl = text.ALL_GAIN_VAL if val >= 0 else text.ALL_LOSE_VAL
        add(tmpl, val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    for tag, val in u.resists.items():
        if val:
            add(text.RESIST_VAL, val=val, tag_label=tag_label(tag))
    return [l for l in lines if l]

# ---------------------------------------------------------------------------
# Stat tagging (which stats an item modifies vs. scales with)
# ---------------------------------------------------------------------------
# Canonical set of player-facing stats we tag against. stat_names + a few
# extras that show up in tag/global bonuses (shot_cooldown, minion_range, ...).
STAT_KEYS = list(dict.fromkeys(
    list(stat_names) + ['minion_range', 'shot_cooldown', 'strikechance', 'cooldown']
))
STAT_KEYS_SET = set(STAT_KEYS)

def collect_bonus_stats(obj):
    """Stats this object *grants a bonus to* (modifies), from its bonus dicts."""
    out = set()
    for dname in ('global_bonuses', 'global_bonuses_pct'):
        d = getattr(obj, dname, None)
        if d:
            out.update(d.keys())
    for dname in ('tag_bonuses', 'tag_bonuses_pct', 'spell_bonuses', 'spell_bonuses_pct'):
        d = getattr(obj, dname, None)
        if d:
            for inner in d.values():
                out.update(inner.keys())
    return out

def buffs_from_tooltips(obj):
    out = []
    fn = getattr(obj, 'get_extra_examine_tooltips', None)
    if fn:
        try:
            for t in fn():
                if isinstance(t, BuffBase):
                    out.append(t)
        except Exception:
            pass
    return out

def equipment_stat_tags(e):
    """(modifies, uses) for a piece of equipment."""
    mods = collect_bonus_stats(e)
    for b in buffs_from_tooltips(e):
        mods |= collect_bonus_stats(b)
    uses = set(getattr(e, 'stats', []))
    return sorted(mods & STAT_KEYS_SET), sorted(uses & STAT_KEYS_SET)

def spell_stat_tags(s):
    """(modifies, uses) for a spell. 'uses' = stats it has/scales with;
    'modifies' = stats its upgrades or granted buffs add bonuses to."""
    uses = set(getattr(s, 'stats', []))
    mods = set()
    for up in getattr(s, 'spell_upgrades', []):
        mods |= collect_bonus_stats(up)
    for b in buffs_from_tooltips(s):
        mods |= collect_bonus_stats(b)
    return sorted(mods & STAT_KEYS_SET), sorted(uses & STAT_KEYS_SET)

# ---------------------------------------------------------------------------
# Units (summon stat sheets)
# ---------------------------------------------------------------------------
from Level import Unit, BUFF_TYPE_PASSIVE

UNITS = {}  # name -> stat sheet (deduped)

def _unit_ability(sp):
    a = {"name": sp.name}
    dt = getattr(sp, 'damage_type', None)
    if dt is not None and not isinstance(dt, list) and hasattr(dt, 'name'):
        a["damage_type"] = [dt.name]
    elif isinstance(dt, list):
        a["damage_type"] = [t.name for t in dt if hasattr(t, 'name')]
    for k in ['damage', 'range', 'radius', 'hp_cost']:
        if hasattr(sp, k):
            try:
                v = sp.get_stat(k)
            except Exception:
                v = getattr(sp, k, 0)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
                a[k] = v
    try:
        cd = sp.get_stat('cool_down') if hasattr(sp, 'cool_down') else 0
    except Exception:
        cd = getattr(sp, 'cool_down', 0)
    if cd:
        a["cool_down"] = cd
    try:
        if sp.get_stat('quick_cast'):
            a["quick_cast"] = True
    except Exception:
        pass
    try:
        desc = sp.description or sp.get_description()
        a["desc"] = rtext(desc or "", fmt=sp.fmt_dict())
    except Exception:
        a["desc"] = ""
    # melee attacks (range<=1, no damage line) still note "melee"
    if getattr(sp, 'melee', False):
        a["melee"] = True
    return a

def _unit_passives(u):
    # The game's examine panel shows ALL buffs for a unit not in a level (our
    # case) — only filtering to BUFF_TYPE_PASSIVE for live units. So include
    # every buff that yields tooltip text; this captures innate behaviours like
    # regeneration, spawn generators, and "chance to become" transformations.
    out = []
    seen = set()
    for b in u.buffs:
        txt = ""
        try:
            fmt = b.fmt_dict() if hasattr(b, 'fmt_dict') else {}
            txt = rtext(b.get_tooltip() or "", fmt=fmt)
        except Exception:
            txt = ""
        if not txt and b.name and b.name != "Unnamed buff":
            txt = b.name
        if txt and txt not in seen:
            seen.add(txt)
            out.append(txt)
    return out

def register_unit(u):
    """Extract + store a unit's stat sheet; return its name (or None if it has
    no real name — some abilities summon a nameless placeholder/prop unit, e.g.
    the various Idols; those aren't cards and shouldn't be linked)."""
    name = u.name
    if not name or name == 'Unnamed':
        return None
    if name in UNITS:
        return name
    # Apply tag-derived default resists (Undead -> Holy -100/Dark 100/Ice 50,
    # non-living -> Poison 100, Demon/Metallic/Glass, etc.). The game does this
    # lazily when a unit enters a level or is shown in the examine panel
    # (RiftWizard3.set_default_resistances), so a freshly-constructed unit's
    # `resists` is incomplete until we run it. Idempotent (guarded by
    # `resists_applied`) and self-contained (no level needed).
    try:
        u.set_default_resistances()
    except Exception:
        pass
    sheet = {
        "name": name,
        "hp": u.max_hp,
        "shields": getattr(u, 'shields', 0) or 0,
        "tags": [t.name for t in u.tags],
        "flying": bool(getattr(u, 'flying', False)),
        "stationary": bool(getattr(u, 'stationary', False)),
        "burrowing": bool(getattr(u, 'burrowing', False)),
        "radius": int(getattr(u, 'radius', 0) or 0),
        "is_boss": bool(getattr(u, 'is_boss', False)),
        "resists": {t.name: v for t, v in u.resists.items() if v},
        "abilities": [_unit_ability(sp) for sp in u.spells],
        "passives": _unit_passives(u),
        "refs": [],
        "btips": {},
        "pool_summons": [],
        "icon": asset_filename(u.get_asset()),
    }
    cols, rows = sheet_grid(sheet["icon"], getattr(u, 'radius', 0))
    sheet["cols"] = cols     # idle-animation frame count (last row)
    sheet["rows"] = rows
    UNITS[name] = sheet
    return name

# ---------------------------------------------------------------------------
# Cross-references via static source analysis (AST)
# ---------------------------------------------------------------------------
# Instead of matching names in description prose (false positives), we read each
# class/factory's *source code* and find identifiers that are known game classes
# — e.g. Dread Lash's cast() contains `SealFate`, so it references Seal Fate.
import Monsters
import RareMonsters
import FinalBosses

FRAMEWORK_BASES = {'Spell', 'Equipment', 'Buff', 'Upgrade', 'Unit', 'Component', 'object'}
IDENT_MAP = {}     # python identifier -> (display_name, kind) ; value None == ambiguous
UNIT_FACTORY = {}  # unit display name -> its factory (for computing a unit's own refs)

def _register_factory(name, fac):
    # Display names are NOT unique (two factories can build a "Ice Drake"), so
    # this map is keyed by name only as a best-effort handle for reconstructing a
    # unit to analyse. First stable producer wins and is never overwritten — a
    # later same-named factory can't destroy an existing entry (the old code
    # marked it ambiguous/None, which silently dropped that unit's refs).
    if name and name not in UNIT_FACTORY:
        UNIT_FACTORY[name] = fac

def _register_ident(ident, name, kind):
    if not ident or not name:
        return
    cur = IDENT_MAP.get(ident, '__missing__')
    if cur == '__missing__':
        IDENT_MAP[ident] = (name, kind)
    elif cur is not None and cur != (name, kind):
        IDENT_MAP[ident] = None   # same identifier maps to >1 thing -> unusable

def build_ident_map():
    # Only spells and equipment — the two kinds that need an allowlist (a Spell
    # subclass existing doesn't make it a player spell; likewise Equipment). We
    # build these from the authoritative registries (constructed once each, all
    # deterministic). UNITS are NOT registered here: they're resolved on demand,
    # in the namespace where a reference actually occurs (see refs_for's
    # `_unit_name_of`) — so we never blind-construct every module callable, which
    # is what used to sweep up the random spawners (random_drake, ...).
    for cons in Spells.all_player_spell_constructors:
        try: _register_ident(cons.__name__, cons().name, 'spell')
        except Exception: pass
    # Forbidden spells too, so equipment that grants one (its source references
    # the spell class, e.g. BookOfChaos -> WordOfChaos) links to it.
    for s, _eq in forbidden_granted().values():
        try: _register_ident(type(s).__name__, s.name, 'spell')
        except Exception: pass
    for entry in Equipment.all_equipment:
        if isinstance(entry, type):
            try: _register_ident(entry.__name__, entry().name, 'equipment')
            except Exception: pass

def _safe_call(fac):
    try:
        return fac()
    except Exception:
        return None

_UNIT_NAME_CACHE = {}
def _unit_name_of(o):
    """If `o` is a unit — a Unit subclass, or a factory function that builds one —
    return its display name; else None. Cached by identity. We resolve units the
    same way we resolve buffs (introspect the object the reference names) rather
    than pre-constructing every module callable. Factory functions that pick a
    RANDOM unit (`random_drake`, `RandomImp`, `bat_or_ghost`: all use `random.`)
    aren't a single unit, so they're rejected by a deterministic source check —
    no sampling, so the output is stable run to run."""
    if not (inspect.isclass(o) or inspect.isfunction(o)):
        return None
    key = id(o)
    if key in _UNIT_NAME_CACHE:
        return _UNIT_NAME_CACHE[key]
    name = None
    if inspect.isclass(o) and not issubclass(o, Unit):
        name = None                                  # a class, but not a unit
    else:
        u = _safe_call(o)
        if isinstance(u, Unit) and u.name and u.name != 'Unnamed':
            name = u.name
            # A factory that uses randomness might pick a random *unit* (random_drake,
            # mushboom) or just randomize stats (HealingTotem). Only the former isn't
            # a single unit. Tell them apart by whether the NAME is stable — sampled
            # under FIXED seeds so the verdict is identical every run (a live-RNG
            # sample could occasionally mis-judge a 2-way pick like mushboom).
            if inspect.isfunction(o) and re.search(r'\brandom\.', _getsource(o) or ''):
                st = random.getstate()
                names = set()
                for seed in range(24):
                    random.seed(seed)
                    u2 = _safe_call(o)
                    names.add(u2.name if isinstance(u2, Unit) and u2.name else None)
                random.setstate(st)
                if names != {name}:
                    name = None
    _UNIT_NAME_CACHE[key] = name
    return name

def _collect_idents(srcs):
    """Return (names, attrs): bare-name identifiers vs attribute accesses.
    The split matters for buffs: a buff class is referenced by bare name
    (`Poison`, `NecrosisBuff`), whereas `Tags.Poison` is an attribute — same
    word, different meaning (the damage type). Buff resolution uses names only."""
    names, attrs = set(), set()
    for src in srcs:
        if not src:
            continue
        try:
            tree = ast.parse(textwrap.dedent(src))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                attrs.add(node.attr)
    return names, attrs

_MODULE_INDEX = {}   # module -> {qualname: source string}
def _module_index(mod):
    """{qualname: source} for every top-level class/function (and class method) in
    a module, built by parsing the module ONCE. inspect.getsource(a_class) re-parses
    the whole (huge) module every call to find the class — doing ~1200 of those was
    the build's bottleneck; a single parse per module replaces them with a lookup."""
    idx = _MODULE_INDEX.get(mod)
    if idx is not None:
        return idx
    idx = {}
    _MODULE_INDEX[mod] = idx
    try:
        src = inspect.getsource(mod)
        tree = ast.parse(src)
    except Exception:
        return idx
    lines = src.splitlines(keepends=True)
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = prefix + child.name
                # slice by line span (O(1)); starts at the `class`/`def` line, so it
                # matches inspect.getsource minus decorators (irrelevant to analysis).
                idx.setdefault(qn, ''.join(lines[child.lineno - 1:child.end_lineno]))
                if isinstance(child, ast.ClassDef):     # index methods too (Class.method)
                    walk(child, qn + '.')
    walk(tree, '')
    return idx

_SRC_CACHE = {}
def _getsource(o):
    key = id(o)
    if key in _SRC_CACHE:
        return _SRC_CACHE[key]
    src = None
    qn = getattr(o, '__qualname__', None)
    mod = sys.modules.get(getattr(o, '__module__', None))
    if qn and mod is not None and '<locals>' not in qn:   # module-level classes/fns/methods
        src = _module_index(mod).get(qn)
    if src is None:
        try:                                              # closures, or anything not indexed
            src = inspect.getsource(o)
        except Exception:
            src = None
    _SRC_CACHE[key] = src
    return src

# --- Buffs (named status effects with no card of their own) -----------------
# A unit ability like "gain a stack of Brewed Concoctions" names a Buff that's
# never explained on-screen. We surface each such buff's description as a
# hover-only glossary tooltip.
#
# We DON'T keep a global buff registry. A buff is recognised the way Python
# itself resolves the name: for each identifier the AST finds in a piece of
# source, look it up in *that source's own module namespace* and ask
# `issubclass(obj, Buff)` — so `FiendConductance` resolves to the buff, locals
# and `Tags.Poison` (an attribute, not a bare name) don't, and import aliases
# just work. On top of that we introspect each ability *instance*'s `.buff`
# attribute, which catches buffs applied by a delegated/wrapped factory the AST
# never sees (the Aether Spider Queen's `QueenMonster(PhaseSpider)`). See refs_for.

def _source_and_ns(o):
    """(source text, module namespace) for a function/class, or (None, None).
    A function resolves names in its own __globals__; a class in its module."""
    src = _getsource(o)
    if src is None:
        return None, None
    if inspect.isfunction(o):
        return src, getattr(o, '__globals__', None) or {}
    mod = sys.modules.get(getattr(o, '__module__', None))
    return src, getattr(mod, '__dict__', None) or {}

def _literal_args(call_args):
    """Python values of an ast.Call's positional args, or None if any isn't a
    literal (a variable / stat lookup we can't evaluate statically)."""
    vals = []
    for a in call_args:
        if isinstance(a, ast.Constant):
            vals.append(a.value)
        elif (isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub)
              and isinstance(a.operand, ast.Constant)):
            vals.append(-a.operand.value)
        else:
            return None
    return tuple(vals)

def _describe_buff(cls, args):
    """(display_name, {desc, color}) for a Buff subclass, or None if it has no
    usable name/description. `args` are the literal constructor args the source
    applies (so RegenBuff(1) vs RegenBuff(10) differ); fall back to filler args
    when the call wasn't literal — the name/description template don't depend on
    the values for the buffs that need this."""
    b = None
    if args is not None:
        try:
            b = cls(*args)
        except Exception:
            b = None
    if b is None:
        b = _construct_buff(cls)
    if b is None:
        return None
    name = getattr(b, 'name', None)
    if not name or name == 'Unnamed buff':
        return None
    desc = _buff_text(b)
    if not desc:
        return None
    col = getattr(b, 'color', None)
    return name, {"desc": desc, "color": to_tup(col) if isinstance(col, Color) else None}

def _construct_buff(cls):
    """Instantiate a Buff for its name/description. Many buffs need constructor
    args (e.g. RegenBuff(heal), DamageAuraBuff(damage, ...)); a zero-arg attempt
    would skip them entirely — and they'd be silently unlinkable (the Witch
    Doctor's Regeneration). Fall back to filler positional args; the name and
    description template are what we read, and those don't depend on the values."""
    for args in ((), (1,), (1, 1), (1, 1, 1), (1, 1, 1, 1)):
        try:
            return cls(*args)
        except Exception:
            continue
    return None

def _buff_text(b):
    for meth in ('get_description', 'get_tooltip'):
        f = getattr(b, meth, None)
        if not f:
            continue
        try:
            fmt = b.fmt_dict() if hasattr(b, 'fmt_dict') else {}
            txt = f()
            if txt:
                rendered = rtext(txt, fmt=fmt)
                # A standalone "None" means a fmt value was empty because we
                # filler-constructed the buff (e.g. ChannelBuff's {spell} with no
                # real spell). That description is an artifact, not real text.
                if re.search(r'(?<![A-Za-z])None(?![A-Za-z])', rendered):
                    return ""
                return rendered
        except Exception:
            continue
    # No prose: fall back to the buff's mechanical effect lines (resists / stat
    # bonuses). Many status buffs are pure stat effects with no get_description —
    # e.g. Conductivity is just -100% Lightning resist — and the game builds their
    # tooltip from these the same way it does for equipment (render_bonus_lines).
    try:
        lines = render_bonus_lines(b)
        if lines:
            return "\n".join(lines)
    except Exception:
        pass
    return ""


_MISSING = object()   # distinct-from-None sentinel for dict lookups
# Cache of the per-source AST analysis, keyed by the class/function whose source
# it is. Those are long-lived module-level objects (stable identity, hashable), and
# the same base/ability class is analysed for hundreds of units — so this turns an
# O(units × sources) reparse into one parse per distinct source. The cached tuple
# is treated as read-only by callers (they only union/read it), so sharing is safe.
_SRC_ANALYSIS = {}
def _analyze_source(o):
    """(names, attrs, buffs, units) referenced by one class/function's source:
      names/attrs — bare-name vs attribute identifiers (for IDENT_MAP lookups)
      buffs — {Buff subclass: literal ctor args or None}
      units — {unit display name: its factory}
    A pure function of the source + its module namespace, both fixed for a given
    object, so the result is cached and reused wherever this class is scanned."""
    cached = _SRC_ANALYSIS.get(o)
    if cached is not None:
        return cached
    names, attrs, buffs, units = set(), set(), {}, {}
    src, ns = _source_and_ns(o)
    tree = None
    if src is not None:
        try:
            tree = ast.parse(textwrap.dedent(src))
        except (SyntaxError, ValueError):
            tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                c = ns.get(node.func.id)         # capture literal ctor args for buffs
                if inspect.isclass(c) and issubclass(c, BuffBase):
                    lits = _literal_args(node.args)
                    if lits is not None:
                        buffs[c] = lits          # a literal call wins over a bare mention
            elif isinstance(node, ast.Name):
                names.add(node.id)
                c = ns.get(node.id)
                if inspect.isclass(c) and issubclass(c, BuffBase):
                    buffs.setdefault(c, None)
                else:
                    un = _unit_name_of(c)
                    if un:
                        units.setdefault(un, c)
            elif isinstance(node, ast.Attribute):
                attrs.add(node.attr)
    _SRC_ANALYSIS[o] = (names, attrs, buffs, units)
    return _SRC_ANALYSIS[o]

def _scan_objects(instance, entry):
    """The objects whose source we analyse for an entity: its registry entry
    (class / factory / lambda) and non-framework base classes, plus — for a unit —
    its ability-spell classes (a summon/buff applied *inside* an ability's cast(),
    e.g. BatBreath's `self.summon(Bat())`, lives there, not the unit factory)."""
    objs, seen = [], set()
    def add(o):
        if o is not None and o not in seen:
            seen.add(o)
            objs.append(o)
    add(entry)
    cls = type(instance)
    if isinstance(cls, type):
        for base in cls.__mro__:
            if base is not object and base.__name__ not in FRAMEWORK_BASES:
                add(base)
    if isinstance(instance, Unit):
        # Ability-spell classes AND buff classes: a summon/transform can live in
        # either a spell's cast() (BatBreath -> Bat) or a buff's handler (Snow
        # Queen's Unseated buff constructs SnowQueenDethroned + SnowQueensPet in
        # on_damage) — both are code the unit factory itself doesn't contain.
        for holder in (getattr(instance, 'spells', None) or []) + (getattr(instance, 'buffs', None) or []):
            hcls = type(holder)
            if isinstance(hcls, type):
                for base in hcls.__mro__:
                    if base is not object and base.__name__ not in FRAMEWORK_BASES:
                        add(base)
    return objs

# --- Unit pools: named rosters the game draws (often random) summons from -----
# e.g. Summon Wizard does `random.choice(RareMonsters.WIZARDS)`. The individual
# members are never named in the spell's source (so refs can't link them), but the
# pool *list* is — so we link the pool instead, and let the Monsters tab filter to
# its members. Each entry: (display name, the list, identifiers that name it in code).
POOL_MEMBERS = {}    # display name -> [member unit display names]  (shipped)
POOL_IDENTS = {}     # source identifier -> pool display name

def build_pools():
    import Monsters as _M, RareMonsters as _RM
    defs = [
        ("Wizard",   getattr(_RM, "WIZARDS", []),     {"WIZARDS"}),
        ("Kaiju",    getattr(_RM, "KAIJU", []),       {"KAIJU"}),
        ("Horseman", getattr(_RM, "horsemen", []),    {"horsemen"}),
        ("Slime",    getattr(_M, "slime_types", []),  {"slime_types"}),
    ]
    for disp, pool, idents in defs:
        members, seen = [], set()
        for e in pool:
            fac = e[0] if isinstance(e, (list, tuple)) else e
            u = _safe_call(fac)
            if isinstance(u, Unit) and u.name and u.name not in seen:
                seen.add(u.name)
                members.append(u.name)
        if members:
            POOL_MEMBERS[disp] = members
            for i in idents:
                POOL_IDENTS[i] = disp

def pools_referenced(instance, entry):
    """Pool display names an entity summons from — detected by its source naming a
    pool list (e.g. `WIZARDS`). Reuses the cached per-source analysis, so cheap."""
    hits = set()
    for o in _scan_objects(instance, entry):
        names, attrs, _b, _u = _analyze_source(o)
        for ident in names | attrs:
            if ident in POOL_IDENTS:
                hits.add(POOL_IDENTS[ident])
    return sorted(hits)

def refs_for(instance, entry, self_name):
    """Return (refs, btips): refs = [[display_name, kind], …] this entity
    references in its code; btips = {buff_name: {desc, color}} resolved from the
    actual class + args the source applies (so tooltips are exact, per site)."""
    scan_objs = _scan_objects(instance, entry)

    # Each name is resolved in the namespace of the source it appears in (never a
    # blind sweep of every module callable): a Buff class -> a buff ref, a unit
    # class/factory -> a unit ref. `Tags.Poison` is an *attribute*, not a bare
    # name, so it can't masquerade as the Poison status buff; locals resolve to
    # nothing. IDENT_MAP still resolves spell/equipment refs from names|attrs.
    names, attrs = set(), set()
    buff_hits = {}                               # Buff subclass -> literal args tuple or None
    unit_hits = {}                               # unit display name -> its factory
    for o in scan_objs:
        n, a, b, u = _analyze_source(o)
        names |= n
        attrs |= a
        for c, lits in b.items():
            cur = buff_hits.get(c, _MISSING)
            if cur is _MISSING or (cur is None and lits is not None):
                buff_hits[c] = lits              # first/literal call wins over a bare mention
        for un, fac in u.items():
            unit_hits.setdefault(un, fac)
    # Also read what each ability *instance* applies/summons straight off the
    # object. This survives construction the AST never sees: a buff hidden in a
    # delegated factory (`spell.buff` — the Aether Spider Queen), or a unit built
    # inline and handed to a summon spell (`spell.spawn_func` — Troll Geomancer's
    # Clay Hound, made as a local `wolf`). `_unit_name_of` still rejects random
    # summoners (Dragon Mage's random_drake) so this stays deterministic.
    if isinstance(instance, Unit):
        for sp in getattr(instance, 'spells', None) or []:
            b = getattr(sp, 'buff', None)
            b = b if inspect.isclass(b) else (type(b) if isinstance(b, BuffBase) else None)
            if b is not None and issubclass(b, BuffBase):
                buff_hits.setdefault(b, None)
            sf = getattr(sp, 'spawn_func', None)
            if callable(sf):
                un = _unit_name_of(sf)
                if un:
                    unit_hits.setdefault(un, sf)

    # Remember each referenced unit's factory so the fixpoint can card it.
    for un, fac in unit_hits.items():
        _register_factory(un, fac)

    out, seen, btips = [], set(), {}
    # Real carded entities (spell/equipment via the allowlist, units resolved
    # above) claim their name before buffs, so a real card wins a name collision.
    for ident in names | attrs:
        m = IDENT_MAP.get(ident)
        if not m:
            continue
        name, kind = m
        if name == self_name or name in seen:
            continue
        seen.add(name)
        out.append([name, kind])
    for name in unit_hits:
        if name == self_name or name in seen:
            continue
        seen.add(name)
        out.append([name, 'unit'])
    for cls_, args in buff_hits.items():
        info = _describe_buff(cls_, args)
        if not info:                             # can't describe it -> don't link it
            continue
        name, meta = info
        if name == self_name or name in seen:
            continue
        seen.add(name)
        out.append([name, 'buff'])
        btips[name] = meta
    out.sort()
    return out, btips

# ---------------------------------------------------------------------------
# Full monster roster (bestiary): base spawns + evolutions + rare rosters
# ---------------------------------------------------------------------------

MONSTER_NAMES = set()   # names that belong to the bestiary
MONSTER_DEPTH = {}      # name -> earliest spawn depth (base monsters only)

def collect_monster_factories():
    factories = {}        # factory -> earliest depth (or None)
    for entry in Monsters.spawn_options:
        base, depth = entry[0], entry[1]
        factories.setdefault(base, depth)
        if factories[base] is None or (depth and depth < factories[base]):
            factories[base] = depth
        if len(entry) > 2 and entry[2]:
            factories.setdefault(entry[2], None)
    for list_name in ['MONSTER_PACKS', 'IDOLS', 'SUPER_SPAWNERS', 'SPECIAL_MONSTERS', 'WIZARDS', 'KAIJU']:
        L = getattr(RareMonsters, list_name, None) or []
        for entry in L:
            factories.setdefault(entry[0], None)
    return factories

def extract_monsters(factories):
    for fac, depth in factories.items():
        try:
            u = fac()
        except Exception as e:
            print("skip monster", getattr(fac, '__name__', fac), e)
            continue
        if not isinstance(u, Unit):
            continue
        if register_unit(u):      # refs computed later in main()'s unit fixpoint
            # Remember the spawn factory so the fixpoint can re-derive this
            # monster's refs from its source. `_unit_name_of` returns None only for
            # a factory whose *name* is random (a random spawner like random_drake,
            # not one monster) — a monster that merely uses random for stats/cooldown
            # (Mantis Queen) has a stable name and is kept.
            if _unit_name_of(fac):
                _register_factory(u.name, fac)
            MONSTER_NAMES.add(u.name)
            if depth is not None:
                cur = MONSTER_DEPTH.get(u.name)
                MONSTER_DEPTH[u.name] = depth if cur is None else min(cur, depth)

# ---------------------------------------------------------------------------
# Companions: permanent allies bought at the Tavern (Equipment.all_companions).
# The companion is an Equipment whose examine tooltip is the (buffed) unit it
# summons, but it's neither craftable (not in all_equipment) nor part of the
# bestiary — so its unit is otherwise absent. Extract those units and flag them
# as their own Monsters-tab category ("Companion"). The buffed stats match what
# you see in-game (make_minion applies the companion's minion_* bonuses).
# ---------------------------------------------------------------------------
COMPANION_NAMES = set()

def extract_companions():
    for cons in getattr(Equipment, 'all_companions', []):
        e = _safe_call(cons)
        if e is None:
            continue
        fac = getattr(e, 'unit_fn', None)          # zero-arg factory for the base unit
        if fac:                                    # enable AST cross-refs + name links
            u = _safe_call(fac)
            if isinstance(u, Unit) and u.name:
                _register_ident(getattr(fac, '__name__', None), u.name, 'unit')
                _register_factory(u.name, fac)
        # summons_of registers the companion unit AND any units it in turn
        # summons (e.g. the Engineer's Auto Cannon, the Ranger's Giant Bear).
        # Only the companion itself is a "Companion"; its summons stay plain
        # summonables. Companion.name == the summoned unit's name (unit_ex.name).
        registered = set(summons_of(e))
        if e.name in registered:
            COMPANION_NAMES.add(e.name)

# ---------------------------------------------------------------------------
# Final bosses (floor-20 encounters) + Mordred's phases. FinalBosses.py has a
# clean registry: `final_bosses` (the rollable floor-20 roster) plus the three
# Mordred forms, which chain by ForcedRespawn (Mordred -> Unbound -> Ascendant).
# They're neither in the bestiary spawn tables (Monsters.spawn_options) nor
# summonable, so they'd be absent otherwise (this is the "no clean registry"
# exclusion ARCHITECTURE §6/§14 called out — the registry is `final_bosses`).
# The roster factories don't set is_boss themselves (roll_final_boss does, after
# construction), so we set it here, mirroring the game. Whatever a boss
# summons/transforms into (Snow Queen's Dethroned form, etc.) is carded by
# main()'s unit fixpoint, and flags itself is_boss off its own attribute.
# ---------------------------------------------------------------------------
BOSS_NAMES = set()

def extract_bosses():
    factories = list(FinalBosses.final_bosses) + [
        FinalBosses.Mordred, FinalBosses.MordredUnbound, FinalBosses.MordredAscendant]
    for fac in factories:
        u = _safe_call(fac)
        if not isinstance(u, Unit):
            print("skip boss", getattr(fac, '__name__', fac))
            continue
        u.is_boss = True                       # what roll_final_boss does post-construction
        if register_unit(u):
            # Enable AST cross-refs + name links, and let the fixpoint re-derive
            # this boss's refs (Mordred phase X names phase X+1 in its source).
            _register_ident(getattr(fac, '__name__', None), u.name, 'unit')
            _register_factory(u.name, fac)
            BOSS_NAMES.add(u.name)

def summons_of(obj):
    """Return list of distinct unit names this spell/equipment/component can summon."""
    names = []
    seen = set()

    def add(u):
        if isinstance(u, Unit) and u.name not in seen and register_unit(u):
            seen.add(u.name)
            names.append(u.name)

    fn = getattr(obj, 'get_extra_examine_tooltips', None)
    if fn:
        try:
            for t in fn():
                add(t)
        except Exception:
            pass
    gu = getattr(obj, 'get_unit', None)
    if gu:
        try:
            add(gu())
        except Exception:
            pass
    return names

# ---------------------------------------------------------------------------
# Spells
# ---------------------------------------------------------------------------
# Stat lines shown on a spell card. Mirrors the game's spell examine panel:
# the dedicated range/charges/hp_cost lines it draws first, then every TT_ATTRS
# attribute (the "Attributes:" section). Derived from TT_ATTRS so channel/minion
# stats (e.g. max_channel) can't silently drop off again as the game evolves.
SPELL_STAT_KEYS = ['range', 'max_charges', 'hp_cost'] + list(TT_ATTRS)

def _spell_entry(s, cons, forbidden=False, granted_by=None):
    fmt = s.fmt_dict()
    stats = {}
    for k in SPELL_STAT_KEYS:
        if hasattr(s, k):
            v = s.get_stat(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
                stats[k] = v
    dtypes = []
    dt = getattr(s, 'damage_type', None)
    if dt:
        if isinstance(dt, list):
            dtypes = [t.name for t in dt]
        else:
            dtypes = [dt.name]
    upgrades = []
    for u in s.spell_upgrades:
        # Game order: auto-generated stat lines first, then prose (some
        # upgrades, e.g. Relentless Cascade, are pure stat with no prose).
        prose = rtext(u.get_description() or "", fmt=u.fmt_dict())
        parts = upgrade_bonus_lines(u) + ([prose] if prose else [])
        upgrades.append({
            "name": u.name,
            "level": getattr(u, 'level', 0),
            "desc": "\n".join(parts),
        })
    mod_stats, use_stats = spell_stat_tags(s)
    refs, btips = refs_for(s, cons, s.name)
    entry = {
        "name": s.name,
        "level": s.level,
        "tags": [t.name for t in s.tags],
        "damage_type": dtypes,
        "stats": stats,
        "requires_los": bool(getattr(s, 'requires_los', True)),
        "melee": bool(getattr(s, 'melee', False)),
        "quick_cast": bool(getattr(s, 'quick_cast', False)),
        "desc": rtext(s.get_description() or "", fmt=fmt),
        "upgrades": upgrades,
        "summons": summons_of(s),
        "pool_summons": pools_referenced(s, cons),
        "refs": refs,
        "btips": btips,
        "mod_stats": mod_stats,
        "use_stats": use_stats,
        "icon": asset_filename(s.get_asset()),
    }
    if forbidden:
        # Forbidden spells aren't bought with SP — they come with a SpellBook.
        # The frontend shows "Forbidden" instead of an SP cost and links the
        # granting equipment. They're excluded from Guide SP ids (see main()).
        entry["forbidden"] = True
        if granted_by:
            entry["granted_by"] = granted_by
            entry["refs"] = sorted(set(map(tuple, entry["refs"])) | {(granted_by, "equipment")})
    return entry

_FORBIDDEN = None
def forbidden_granted():
    """Map forbidden-spell name -> (spell instance, granting equipment name).
    Forbidden spells can't be learned with SP — they're granted only by SpellBook
    equipment (e.g. Word of Chaos from Book of Chaos). Detected as equipment-
    granted spells whose name isn't in the normal player roster, so staves that
    re-grant a *normal* spell don't produce duplicates. Cached (instantiates
    every equipment once); also feeds build_ident_map so the book's description
    can link the spell."""
    global _FORBIDDEN
    if _FORBIDDEN is None:
        player_names = {cons().name for cons in Spells.all_player_spell_constructors}
        found = {}
        for cons in Equipment.all_equipment:
            try:
                e = cons()
            except Exception:
                continue
            granted = []
            sp = getattr(e, 'spell', None)
            if isinstance(sp, Spell):
                granted.append(sp)
            try:
                for t in (e.get_extra_examine_tooltips() or []):
                    if isinstance(t, Spell):
                        granted.append(t)
            except Exception:
                pass
            for s in granted:
                if s.name not in player_names and s.name not in found:
                    found[s.name] = (s, e.name)
        _FORBIDDEN = found
    return _FORBIDDEN

def extract_spells():
    out = [_spell_entry(cons(), cons) for cons in Spells.all_player_spell_constructors]
    out += [_spell_entry(s, type(s), forbidden=True, granted_by=eq)
            for s, eq in forbidden_granted().values()]
    # Forbidden spells sort to the end (they're a distinct, SP-less category).
    out.sort(key=lambda d: (bool(d.get("forbidden")), d["level"], d["name"]))
    return out

# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
def extract_equipment():
    out = []
    for cons in Equipment.all_equipment:
        try:
            e = cons()
        except Exception as ex:
            print("skip equipment", cons, ex)
            continue
        recipe = []
        for tag, amt in getattr(e, 'recipe', []):
            recipe.append([tag.name, int(amt)])
        desc = rtext(e.get_description() or "", fmt=e.fmt_dict())
        bonus_lines = render_bonus_lines(e)
        mod_stats, use_stats = equipment_stat_tags(e)
        # A SpellBook/staff delegates its examine tooltips to the spell it grants,
        # so summons_of(e) picks up the SPELL's summons (e.g. Word of Chaos's
        # Chaos Spirit) and misattributes them to the book. Those belong to the
        # spell's card; subtract them so the equipment lists only what it itself
        # summons directly.
        gs = getattr(e, 'spell', None)
        granted_units = set(summons_of(gs)) if isinstance(gs, Spell) else set()
        summons = [n for n in summons_of(e) if n not in granted_units]
        refs, btips = refs_for(e, cons, e.name)
        out.append({
            "name": e.name,
            "slot": SLOT_NAMES.get(getattr(e, 'slot', 0), "Trinket"),
            "tags": [t.name for t in e.tags],
            "recipe": recipe,
            "recipe_cost": sum(a for _, a in recipe),
            "desc": desc,
            "bonuses": bonus_lines,
            "summons": summons,
            "pool_summons": pools_referenced(e, cons),
            "refs": refs,
            "btips": btips,
            "mod_stats": mod_stats,
            "use_stats": use_stats,
            "icon": asset_filename(e.get_asset()),
        })
    out.sort(key=lambda d: (d["recipe_cost"], d["name"]))
    return out

# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def extract_components():
    out = []
    tier_of = {}
    for c in Components.t1_components: tier_of[c] = 1
    for c in Components.t2_components: tier_of[c] = 2
    for c in Components.t3_components: tier_of[c] = 3
    seen = []
    pools = [("normal", Components.all_components), ("rare", Components.rare_components)]
    for pool_name, pool in pools:
        for cons in pool:
            c = cons()
            tier = tier_of.get(cons, len(c.tags))
            has_craft = type(c).on_craft is not ComponentBase.on_craft
            has_pickup = type(c).on_pickup is not ComponentBase.on_pickup
            refs, btips = refs_for(c, cons, c.name)
            out.append({
                "name": c.name,
                "tags": [t.name for t in c.tags],
                "tier": tier,
                "rare": bool(getattr(c, 'is_rare', False)) or pool_name == "rare",
                "pool": pool_name,
                "on_craft": has_craft,
                "on_pickup": has_pickup,
                "desc": rtext(getattr(c, 'description', "") or "", fmt={}),
                "summons": summons_of(c),
                "pool_summons": pools_referenced(c, cons),
                "refs": refs,
                "btips": btips,
                "icon": asset_filename(c.get_asset()),
            })
    out.sort(key=lambda d: (d["tier"], d["name"]))
    return out

# ---------------------------------------------------------------------------
# Tags metadata
# ---------------------------------------------------------------------------
def extract_tags():
    # component_tags are the craftable/recipe tags (a set -> sort for a stable,
    # reproducible order; the frontend re-sorts it anyway).
    comp_tags = sorted(t.name for t in Components.component_tags)
    tags = {}
    for tag in Tags:
        tags[tag.name] = {"color": to_tup(tag.color)}
    # Single-letter essence codes shown in the crafting UI. The game derives them
    # from the tag-filter hotkeys (RiftWizard3.KEY_BIND_DEFS); mirrored here (UI
    # module isn't imported — same reason tooltip_colors are mirrored). Distinct
    # letters resolve first-letter clashes (Eye=Y, Dragon=R, Chaos=K, Slime=Z,
    # Ritual=U, Any=∗). Keep in sync with TAG_ABBR in app.js.
    tag_abbr = {
        "Any": "∗", "Fire": "F", "Ice": "I", "Lightning": "L", "Nature": "N",
        "Arcane": "A", "Dark": "D", "Holy": "H", "Metallic": "M", "Blood": "B",
        "Sorcery": "S", "Enchantment": "E", "Conjuration": "C", "Eye": "Y",
        "Dragon": "R", "Orb": "O", "Chaos": "K", "Slime": "Z", "Word": "W",
        "Translocation": "T", "Ritual": "U",
    }
    for name, ab in tag_abbr.items():
        if name in tags:
            tags[name]["abbr"] = ab
    return {"all": tags, "component_tags": comp_tags}

def main():
    # A handful of unit factories randomize stats/cooldowns; seed the RNG so a
    # rebuild is byte-for-byte reproducible (random *unit* pickers are still
    # excluded from refs by _unit_name_of's fixed-seed check, independent of this).
    random.seed(0)
    monster_factories = collect_monster_factories()
    build_ident_map()                           # must precede any refs_for() call
    build_pools()                               # named unit rosters (Wizard, Kaiju, …)
    spells = extract_spells()
    equipment = extract_equipment()
    components = extract_components()            # these populate UNITS via summons_of()
    extract_monsters(monster_factories)         # full bestiary into UNITS
    extract_companions()                         # Tavern companions into UNITS
    extract_bosses()                             # floor-20 final bosses + Mordred phases

    # Compute every unit's refs, and card any unit it summons that isn't already
    # carded — to a fixpoint, since a summoned unit may summon others. A unit's
    # summons come from AST (`self.summon(Bat())` inside an ability class, now
    # scanned by refs_for) and from the game's examine-tooltip hook (SimpleSummon
    # etc.); both feed the same unit refs.
    def compute_unit_refs(name):
        fac = UNIT_FACTORY.get(name)
        inst = _safe_call(fac) if fac else None
        if inst is None:
            return None
        refs, btips = refs_for(inst, fac, name)
        # (Summons a unit's abilities make are picked up by refs_for's namespace
        # resolution — `SimpleSummon(CopperImp)` names CopperImp in the source. We
        # deliberately don't fall back to summons_of here: it constructs the
        # ability's summon, which for a random summoner (Dragon Mage's random_drake)
        # would yield a different unit each run.)
        # A unit's own permanent buffs are already shown in full under Passives;
        # don't also linkify their names on the card (the Vampire Hunter's
        # "Silvered Weapons" self-link). Buffs it merely grants/applies aren't in
        # u.buffs (e.g. the Alchemist's Brewed Concoctions), so they stay.
        own = {getattr(b, 'name', None) for b in getattr(inst, 'buffs', [])}
        refs = [r for r in refs if not (r[1] == 'buff' and r[0] in own)]
        return refs, btips, pools_referenced(inst, fac)

    queue = list(UNITS.keys())
    while queue:
        name = queue.pop()
        if name not in UNITS:
            continue
        got = compute_unit_refs(name)
        if got is None:
            continue
        UNITS[name]["refs"], UNITS[name]["btips"], UNITS[name]["pool_summons"] = got
        for r in UNITS[name]["refs"]:
            if r[1] == 'unit' and r[0] not in UNITS:
                nf = UNIT_FACTORY.get(r[0])
                ni = _safe_call(nf) if nf else None
                if ni is not None and ni.name not in UNITS and register_unit(ni):
                    queue.append(ni.name)
    # Which pools each carded unit belongs to (for the Monsters-tab pool filter).
    pool_of = {}
    for disp, members in POOL_MEMBERS.items():
        for m in members:
            pool_of.setdefault(m, []).append(disp)
    for name, sheet in UNITS.items():
        sheet["is_monster"] = name in MONSTER_NAMES
        sheet["is_companion"] = name in COMPANION_NAMES
        sheet["pools"] = sorted(pool_of.get(name, []))
        if name in MONSTER_DEPTH:
            sheet["depth"] = MONSTER_DEPTH[name]
    # Prune cross-refs whose target has no card (e.g. units that are never
    # surfaced), so every link resolves to a real entry.
    valid = {'spell': {s['name'] for s in spells},
             'equipment': {e['name'] for e in equipment},
             'unit': set(UNITS.keys())}
    def finalize(entity_name, refs, btips):
        kept = []
        for r in refs:
            if r[1] == 'buff':
                # buff refs are pre-validated (only added when describable); drop a
                # buff whose name is a whole word of the entity's OWN name, whose
                # name recurs throughout its own text (e.g. "Poison Sting gains …")
                # and would self-link the shared word "Poison" onto the Poison buff.
                if r[0] in btips and not re.search(
                        r'(?<![A-Za-z])' + re.escape(r[0]) + r'(?![A-Za-z])', entity_name):
                    kept.append(r)
            elif r[0] in valid.get(r[1], ()):
                kept.append(r)
        keep_buffs = {r[0] for r in kept if r[1] == 'buff'}
        return kept, {n: v for n, v in btips.items() if n in keep_buffs}
    for it in spells + equipment + components:
        it['refs'], it['btips'] = finalize(it['name'], it['refs'], it.get('btips', {}))
    for name, sheet in UNITS.items():
        sheet['refs'], sheet['btips'] = finalize(name, sheet['refs'], sheet.get('btips', {}))
    # Stable integer ids for shareable build URLs (append-only; see ids.py).
    # Mutates ids.json on disk — it MUST be committed alongside data.json.
    idmap = ids_mod.load_ids()
    # Forbidden spells are equipment-granted (no SP cost), so they get no spell
    # id and don't enter the Guide SP track (assign_sp skips them internally).
    learnable = [s for s in spells if not s.get("forbidden")]
    ids_mod.assign(idmap, "equipment", [e["name"] for e in equipment])
    ids_mod.assign(idmap, "spell", [s["name"] for s in learnable])
    ids_mod.assign_sp(idmap, spells)   # combined spell+upgrade ids (Guide SP track)
    ids_mod.save_ids(idmap)
    for e in equipment: e["id"] = idmap["equipment"][e["name"]]
    for s in learnable: s["id"] = idmap["spell"][s["name"]]
    data = {
        "spells": spells,
        "equipment": equipment,
        "components": components,
        "units": UNITS,
        "pools": POOL_MEMBERS,
        "tags": extract_tags(),
        "colors": tooltip_colors,
        "slots": list(SLOT_NAMES.values()),
        "stat_meta": {k: format_attr(k) for k in STAT_KEYS},
        "generated": __import__("datetime").date.today().isoformat(),
        # Version stamp: which Steam branch/build this dataset was extracted from.
        "branch": BRANCH["id"],
        "branch_label": BRANCH["label"],
        "build_id": BRANCH["build_id"],
    }
    out_path = os.path.join(OUT_DIR, gameinfo.data_filename(BRANCH["id"]))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    # Record this branch in the frontend's version manifest (preserves the other
    # branch's entry — each build only tags its own).
    gameinfo.update_versions(OUT_DIR, BRANCH, data["generated"])
    monsters = sum(1 for s in UNITS.values() if s.get("is_monster"))
    companions = sum(1 for s in UNITS.values() if s.get("is_companion"))
    distinct_buffs = set()
    for it in spells + equipment + components + list(UNITS.values()):
        distinct_buffs.update(it.get("btips", {}))
    print("Wrote", out_path, "| branch:", BRANCH["id"], "build:", BRANCH["build_id"] or "?")
    print("spells:", len(data["spells"]), "equipment:", len(data["equipment"]),
          "components:", len(data["components"]), "units:", len(data["units"]),
          "(monsters:", monsters, "companions:", companions, ")",
          "distinct buffs linked:", len(distinct_buffs))

if __name__ == "__main__":
    main()
