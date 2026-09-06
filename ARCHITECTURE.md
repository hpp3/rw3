# Architecture & design notes

This is a static, fully client-side compendium for **Rift Wizard 3**. All data is
**extracted from the game's own Python source at build time** into one `site/data.json`,
which a vanilla-JS frontend renders. No server, no framework, no build toolchain beyond
a few Python scripts.

```
game install (Python source + art)  ──extract.py──▶  site/data.json
                                     ──copy_icons──▶  site/icons/**          (static host)
site/{index.html, app.js, styles.css, favicon.png, data.json, icons/}  ──▶  GitHub Pages
                     data.json  ──share.py──▶  site/s/**   (per-entry link-preview pages,
                                                            generated at deploy time; §19)
```

The rest of this doc is the stuff you **can't** easily infer from reading the code, plus the
design decisions worth knowing before you change things.

---

## 1. The build reads a live game install — this is load-bearing and fragile

`extract.py` / `copy_icons.py` have a hardcoded `GAME = r"E:\SteamLibrary\...\Rift Wizard 3"`.
The build **imports the actual game modules and instantiates every spell/item/monster** to read
their real attributes. There is no parallel "database" — the game source *is* the schema.

Non-obvious gotchas, each of which cost real debugging time:

- **Import order matters.** `import Equipment` **first**. The game has circular imports
  (`Spells` ↔ `Monsters`); importing `Spells` first throws `ImportError: cannot import name
  'LifedrainSpell' from partially initialized module`. `Equipment` transitively pulls everything
  in the order that resolves.
- **Run headless.** `SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy` env vars are set at the top
  of `extract.py` before any game import, or pygame tries to open a window.
- **`extract.py` does `os.chdir(GAME)`** so the game's `Localisation` can load `rl_data/loc/*.json`.
  A consequence: **do not `import pygame` inside extract.py.** With cwd = game dir, Windows finds
  the game's bundled `SDL2.dll` (2.28.1) and pygame (compiled against 2.28.4) raises
  *"Dynamic linking causes SDL downgrade"*. That's why sprite dimensions are read by parsing the
  PNG IHDR header by hand (`_png_size`) instead of using an image library.
- **The build's cost is dominated** by `inspect.getsource()` over every game class for the
  AST cross-reference pass (§4). There's a `_getsource` cache; it's still the bottleneck.

If the game updates and an attribute/registry moves, the build is where it breaks. The registries
relied on: `Spells.all_player_spell_constructors`, `Equipment.all_equipment`,
`Components.{t1,t2,t3,rare}_components` + `component_tags`, `Monsters.spawn_options`,
and `RareMonsters.{MONSTER_PACKS,IDOLS,SUPER_SPAWNERS,SPECIAL_MONSTERS,WIZARDS,KAIJU}`.

`all_equipment` mixes **classes and lambdas** (factory items like `FreeCastStaff(...)`,
`ElementalRobe(...)`). Calling `item()` works for both, but lambdas share a class name — see §4
and §9.

---

## 2. "Render through the game, re-parse in the browser" — the description pipeline

Descriptions are **not** hand-written or scraped. The build calls the game's own
`resolve_text(obj.get_description(), fmt=obj.fmt_dict())` (see `Level.resolve_text`,
`Localisation.T`). This does `{stat}` substitution and leaves the game's inline **markup** intact,
e.g. `Deal [9:damage] [Fire] damage in a [2:radius] tile burst`.

That markup is stored verbatim in `data.json` and re-parsed at render time by `renderMarkup()` in
`app.js`, which turns `[text:colorkey]` / `[Tagname]` into colored `<span>`s. The color lookup is
`data.colors`, a dict the build **reconstructs** from the game (all `Tags[*].color`, `attr_colors`,
and the manual status-word table mirrored from `RiftWizard3.py`'s `tooltip_colors`). If you add a
new status word color in the game, mirror it in `extract.py`'s `tooltip_colors` block.

Equipment "bonus" lines (e.g. `[Fire] spells and equipment gain [7 Damage:damage]`) are likewise
reproduced from the game's own format strings (`text.TAG_VAL_BONUS`, etc.) in `render_bonus_lines`.

**Implication:** most "missing text" bugs are because the game expresses that text through a
mechanism we didn't call, not because the text is wrong. The Brain Tree fix (§6) is the canonical
example.

---

## 3. Almost everything keys off the **display name**; Guides use stable integer IDs.

The frontend keys cross-reference links and card DOM ids (`s-<slug>`, `e-<slug>`, `u-<slug>`), the
component inventory, and the equipment build (`localStorage`), all off the **display name**. The
**one** thing that does *not* is the shareable **Guide**, whose URL uses stable integer ids (§13, §15).

Facts a future agent should know:
- Display names are **unique across all equipment and spells** (the game's own tests enforce it).
  That uniqueness is what makes the name a safe key.
- Python **class names are unique for spells** but **not** for equipment: the factory-built items
  collide (several share `FreeCastStaff`, etc.) — which is *why* we key on display name, not class
  name, both for the DOM/links and as the stable key behind the id map (§13).
- Names are stable against *content additions* (new items don't rename old ones) but not against a
  *rename*. Renames are deliberately **not** handled: a rename orphans the item's id and the new
  name gets a fresh one (old share-URLs lose that one item). This is accepted — renames are rare.

---

## 4. Cross-references are found by **AST analysis of source**, not text matching

When a spell/item/monster references another, the name links to it (`gotoEntry` → switch tab,
scroll to top, flash). The `refs` array (`[[displayName, kind], …]`, kind ∈ spell|equipment|unit|buff)
drives this. `linkify(html, refs)` only wraps names that are *confirmed references*, located by
position in the rendered text — so there are **no false positives**. `buff` refs are the exception
to "links navigate": buffs have no card, so they render as hover-only glossary tooltips (see §6).

How `refs` is computed (`refs_for` in extract.py) and **why it's done this way** — we tried three
approaches:

1. **Text matching** (link any known name found in a description): rejected. It linked "Death" inside
   "Death Bounty", "Pain" inside "Shared Pain", "Melt" in "Melt walls".
2. **Attribute introspection** (scan the instantiated object for referenced Spell/Equipment objects):
   too weak. It only finds references stored as attributes (e.g. `FreeCastStaff.spell`); it **misses
   references inside method bodies**. Dread Lash references `SealFate` only inside its `cast()` method,
   so the object at rest has no trace of it.
3. **AST of the source** (chosen): the source of the entity's class/factory, its non-framework base
   classes, and (for a unit) its ability-spell **and buff** classes, walked for `ast.Name`/`ast.Attribute`
   identifiers. This finds `SealFate` in Dread Lash's `cast()`, `Bat` in `BatBreath.per_square_effect`,
   and `SnowQueenDethroned` in the Snow Queen's `SnowQueenUnseated` buff.

**How an identifier becomes a ref** (`_analyze_source` → `refs_for`): each bare name is resolved *in
the namespace of the source it appears in* and inspected — the same principle for all three kinds:
- resolves to a **`Buff` subclass** → a buff ref (`Tags.Poison` is an *attribute*, not a bare name, so
  the Poison damage type can't masquerade as the Poison status buff);
- resolves to a **unit** (class or factory function) → a unit ref (`_unit_name_of`);
- is a spell/equipment identifier in **`IDENT_MAP`** → that ref.

`IDENT_MAP` (built by `build_ident_map`) holds **only** spells and equipment — the two kinds that need
an *allowlist* (a `Spell` subclass existing doesn't make it a player spell). Units and buffs need no
allowlist and are resolved by introspection at the reference site, so we do **not** pre-construct
every module callable to harvest names — that blind sweep used to pull in random spawners
(`random_drake`) and made the output nondeterministic.

Supporting machinery:
- **`_unit_name_of`**: a bare name → the unit's display name, or `None`. Factory functions that pick a
  *random unit* (`random_drake`, `mushboom`) aren't one unit; they're rejected by checking whether the
  name is stable **under fixed seeds** (a factory that merely randomizes *stats*, like `HealingTotem`,
  keeps its name and is kept). `main()` also `random.seed(0)`s the whole build so stats/cooldowns are
  reproducible.
- **`UNIT_FACTORY`**: unit name → factory, populated as units are referenced/carded (first stable
  producer wins; never overwritten — display names aren't unique). Lets `main()`'s fixpoint re-derive
  a unit's refs from its source and card units it summons.
- **Instance introspection**: a buff/summon applied by a delegated or inline construction the AST
  can't see is read straight off the ability object — `spell.buff` (Aether Spider Queen's Poison,
  hidden behind `QueenMonster(PhaseSpider)`) and `spell.spawn_func` (Troll Geomancer's inline Clay
  Hound). `_unit_name_of` still filters random summoners here.
- **Buff description** is resolved per reference site (`_describe_buff` — see §6's buff note).
- **Caching**: `_module_index` parses each module *once* and indexes every class/function's source by
  qualname (line-sliced), replacing `inspect.getsource`'s per-class full-module reparse; `_analyze_source`
  memoizes each source's analysis. Together these take the build from ~70s to ~2s. All caches are keyed
  by stable module-level objects and the output is byte-for-byte identical with them off.
- **Ref pruning**: in `main()`, refs whose target isn't actually in the output (units with no card)
  are dropped, so every link resolves. There should always be **0 broken refs**.

Known limitation (accepted): a reference chosen *dynamically* by non-literal args, or a genuinely
random pick, isn't linked (we prefer that over a nondeterministic or wrong link). Prose-only mentions
(a description that *names* something it doesn't invoke in code) also won't link.

---

## 5. Summons come from the game's preview hook, not from `refs`

Each spell/item/component has a `summons` array (distinct unit names) built by `summons_of`, which
calls the game's **`get_extra_examine_tooltips()`** (and `Component.get_unit()`) and keeps the
`Unit` instances. This is the same hook the game uses to draw summon previews, so it's authoritative
and handles dynamic construction that AST can't. Summon chips in the UI link via this data.

So unit cross-links have two sources: structured `summons` (chips) and AST `refs` (inline links in
prose). Both feed the same `units` catalog.

A monster can also summon/transform into units from **inside its ability-spell classes _or_ its buff
classes** — `BatBreath.per_square_effect` does `self.summon(Bat())`; Snow Queen's `SnowQueenUnseated`
buff constructs `SnowQueenDethroned()` + `SnowQueensPet()` in `on_damage` ("At 0 HP, transform into
Snow Queen, Dethroned and summon Frost Saber"). Neither the unit factory's AST nor `summons_of`
surfaces these. So `refs_for`/`_scan_objects` scans the classes of a unit's `spells` **and its
`buffs`** (same rationale — the reference is in code the factory itself doesn't contain), and
`main()`'s unit loop runs to a **fixpoint**: any unit named in a card's refs that isn't carded yet is
registered (via its `UNIT_FACTORY` entry) and processed in turn, since a summoned unit may summon
others. This is what cards Bat, Freezing Coral, Ash Imp, Vine, Snow Queen Dethroned, Frost Saber, etc.
(A summon/transform mentioned only in a buff's *prose* — not constructed in its code — still won't
link, the same accepted limitation as anywhere else; e.g. Mordred's "become Mordred's servant" is an
`onhit_description` string whose handler only reassigns `target.team`, so there's no unit to link.)

---

## 6. The monster/unit catalog and the "passives = all buffs" subtlety

`data.units` = the full bestiary (base spawns + their alphas + the rare rosters) **plus** summon-only
minions and the Tavern companions, deduped by name. Each is a stat
sheet built by `register_unit`. `is_monster` distinguishes bestiary vs summon-only; `is_companion`
flags the companions; `is_boss` flags the final bosses. The Monsters-tab type filter is
`monster` / `summon` / `companion` / `boss`, derived boss-first (a boss is none of the other
three); the `monster` chip is labelled **Regular** because it is the residual bucket, and it's
the only control that hides the ~130 units that never spawn in a rift.

**Difficulty, not depth (`extract_spawn_roles`).** `difficulty` is the middle column of
`Monsters.spawn_options`, which the game's own comment labels `Difficulty` (1–9). It is *not* a
rift depth — difficulty 9 enters the primary/secondary pool at depth 18 and can appear as an
extra elite at depth 16 — and the field was called `depth` until the rename, which is where the
mislabelled `Depth 5` badge came from. The game
compounds this: its variables call the column `level` (`monster_lvl`, `get_spawn_min_max`) while
`LevelGenerator.difficulty` means the rift depth. `data.spawn_bands` ships
`CommonContent.get_spawn_min_max` for depths 1–21 so the site derives depth ranges instead of
keeping a copy that drifts.

Three more spawn-table facts ride along. `escorted_by` / `escorts` are the third column of a
`spawn_options` row — that monster's **alpha**, one of which is placed alongside the monsters it
escorts from depth 4 (`LevelGen.add_alphas`). It is not an evolution: nothing transforms, the
alpha is usually balanced far above what it escorts (Bone Shambler is difficulty 4, its alpha
Lich is 8), the pairing is many-to-one (Dragon Mage escorts six drakes), and six units hold both
roles at once. `rare` carries a `RareMonsters` entry's coarse Easy/Medium/Hard class, its group
(one of the six lists), how many spawn together, and any affinity tag used for matched selection.
`boss_kind` separates the depth-20 roster from the Mordred forms, which only appear on 21.

**Final bosses (`extract_bosses`):** the floor-20 encounters. Contrary to the old "no clean registry"
note, `FinalBosses.py` *does* have one: `final_bosses` (the rollable roster) plus the three
Mordred forms (`Mordred` → `Mordred, Unbound` → `Mordred, Ascendant`, chained by `ForcedRespawn`).
They're neither in the spawn tables nor summonable, so they're pulled in explicitly and flagged
`is_boss`. Two wrinkles: (1) the roster factories don't set `is_boss` themselves — `roll_final_boss`
does it *after* construction — so `extract_bosses` sets it, mirroring the game; (2) the boss buffs
`import SteamAdapter` to stash `unlock_achievement`/`unlock_bestiary` (stored, never called in
extraction), and the real module drags in a `LevelGen`→`Game` circular import plus `steamworks`
(absent from the venv), so extract.py installs a no-op `SteamAdapter` stub in `sys.modules` (same
headless-shim spirit as the SDL dummies). Whatever a boss summons/transforms into is carded by
main()'s fixpoint and self-flags `is_boss` off its own attribute.

**Companions (`extract_companions`):** the Tavern allies live in `Equipment.all_companions`, a
list *separate* from `all_equipment` — each is a `Companion` equipment whose examine tooltip is the
(buffed) unit it summons. Because they're neither craftable nor in the bestiary, their units are
otherwise absent, so we pull them in via `summons_of` (which yields the in-game buffed stats — the
companion's `minion_*` bonuses applied by `make_minion`). Only the companion itself is flagged
`is_companion`; units *it* in turn summons (the Engineer's Auto Cannon, the Ranger's Giant Bear)
stay plain summonables. Registering each companion's `unit_fn` into `UNIT_FACTORY`/`IDENT_MAP`
enables its AST cross-refs and name links, same as any monster. The Monsters-tab type filter is
`monster` / `summon` / `companion`, derived companion-first.

**The non-obvious bit (`_unit_passives`):** a unit's innate behaviors (regeneration, spawn
generators, "chance to become") live in `unit.buffs`, but most are `BUFF_TYPE_BLESS`, not
`BUFF_TYPE_PASSIVE`. The game's examine panel filters to `BUFF_TYPE_PASSIVE` **only for units that
are in a level**; for a unit not in a level (exactly our freshly-constructed case) it shows **all**
buffs. So `_unit_passives` intentionally includes *every* buff that yields tooltip text. Filtering
by `BUFF_TYPE_PASSIVE` (the original bug) silently dropped Brain Tree's "spawn a Brain Sapling",
Troll's regen, etc.

**A second, identical-shaped gotcha — tag-derived resists (`set_default_resistances`):** a unit's
constructor only sets its *bespoke* resists (Vampire just sets `Fire -100`). The bulk of a creature's
resists are **tag defaults** applied lazily by `Unit.set_default_resistances()` — `Undead` →
`Holy -100`/`Dark 100`/`Ice 50`, non-living → `Poison 100`, plus `Demon`/`Metallic`/`Glass` tables.
The game runs this when a unit enters a level **and in the examine panel itself**
(`RiftWizard3.py`), so a freshly-constructed unit's `resists` dict is **incomplete** until you call it.
`register_unit` calls `u.set_default_resistances()` before reading `resists` (it's idempotent via
`resists_applied` and needs no level). Skipping it (the original bug) showed Vampire as only
`Fire -100`, hiding its Holy vulnerability — and was wrong for **over half of all units**.

**Buff glossary (per-entity `btips`, `refs_for`):** many abilities name a buff that
has no card and is never explained — e.g. Brew Concoctions says "gain a stack of *Brewed
Concoctions*" without saying what that does. A buff is recognised by resolving a bare name in its
source's namespace to a `Buff` subclass (§4) — no pre-built registry. Its description is **not** a
fixed global value, because the same buff reads differently depending on the args the source applies —
`RegenBuff(heal)` ranges from "Heals 1 HP" to "Heals 100 HP" across the game. Instead each reference is
resolved **at its call site**: `refs_for` finds the `ast.Call` that constructs the buff, reads its
literal args (`_literal_args`), constructs *that* class with *those* args, and renders the description
(`_describe_buff`). The result is attached to the referencing entity as
`btips = {name: {desc, color}}` and embedded on each link in the frontend, so `RegenBuff(1)` and
`RegenBuff(10)` show their own numbers, and a name shared by two classes (both display "Regeneration")
resolves to whichever class *that* entity references. Args that aren't literals (a stat/variable)
fall back to filler positional args; a description that still renders a standalone `None` (e.g.
`ChannelBuff`'s `{spell}`) is treated as un-describable and the buff isn't linked. When a buff has no
`get_description`/`get_tooltip` prose at all, its text falls back to its **mechanical effect lines**
(`render_bonus_lines`: resists and stat bonuses) — many status buffs are pure stat effects (e.g.
Conductivity = "-100% Resist Lightning"). A card links a buff only when its **source code references
the buff class** — for a unit this includes the classes of its **ability spells and its own buffs**
(a buff applied inside a monster spell's `cast()`, or a unit/buff constructed inside another buff's
handler, not the unit factory), same AST rigor as every other ref, so no prose false positives. The frontend renders them as hover-only tooltips (`renderBuffSheet` from the
link's `data-desc`/`data-color`), styled with a dashed underline + help cursor. Buff names match
**case-insensitively** (the game's `SimpleCurse` renders "Apply conductivity …" for the "Conductivity"
buff); unit/spell/equipment names stay case-exact, and both allow a trailing plural so "Summon 3 Ash
Imps" / "Fae Thorns" link to the singular unit.

*Disambiguating a buff from a same-named damage type ("Poison" the status vs. `[Poison]` the
element)* uses three independent signals, so we never fall back to a blanket exclusion:
1. **Bare name vs. attribute (`_collect_idents` → `refs_for`).** A buff class is referenced by bare
   name (`Poison`, `NecrosisBuff`); `Tags.Poison` is an *attribute* access. Buffs resolve from bare
   names only, so the Corrupted Lamasu's `Tags.Poison` aura never gets a spurious Poison-buff ref,
   while the Witch Doctor's literal `Poison` hex does.
2. **Markup token vs. prose (`renderMarkup` `class="mk"` → `linkify`).** `renderMarkup` tags every
   `[…]` token's output with `class="mk"`. The game writes *buff* keywords in markup too (e.g.
   `[Shared Pain:blood]`), so being inside markup isn't itself disqualifying — `linkify` skips a
   buff there only when its name is **also a Tag** (`TAGCOLOR[name]`): inside `[Poison]` that's the
   damage type, not the status. So "3 [Dark] or [Poison] damage" stays colored-but-unlinked, while
   `[Shared Pain:blood]` and a bare-prose "Necrosis, Poison, or Bleed" all link.
3. **Own-name words (`prune`).** A buff whose name is a whole word of the entity's *own* name is
   dropped from its refs — otherwise "Poison Sting gains …" would self-link "Poison" on the Poison
   Sting card (the same shape as the Vampire Hunter's "Silvered Weapons" own-buff exclusion above).

---

## 7. Crafting: whole-component commitment, and why there are two algorithms

RW3 crafting: components carry tags ("essences"); a recipe needs N essences (specific tags + `Any`).
The critical rule: **you commit a whole component to one recipe.** A `[Fire, Dark, Holy]` component
spends all three essences on that recipe; unused ones are wasted, and a component is **never shared**
between two crafts.

The frontend has two checks, and the distinction is deliberate:

- **Single-item craftability** (`evalRecipe`, flat essence bag) — used by the Equipment tab's
  "Craftable only" toggle. This is **provably exact** even under whole-component rules: a lone recipe
  can draw from the entire inventory, and any extra essences from a committed component are just
  wasted, so a flat tag-count check gives the right answer.
- **Multi-item build allocation** (`satisfyFromPool` + `planBuild`) — used by the build planner.
  Here sharing matters: components must be partitioned across the build with no reuse. This is
  bin-packing-ish; `planBuild` does a **greedy** best-effort (hardest recipes first), reports per-item
  satisfied/short with which components each consumes, plus leftovers. It is *not* guaranteed optimal.

Subtle bug already fixed, don't reintroduce: `satisfyFromPool` **mutates** the `avail` set it's
given. `planBuild` must pass it a **copy** (`new Set(avail)`) and only remove components from the real
pool when an item actually succeeds — otherwise a failed/earlier item silently consumes components a
later item needs (this manifested as a wrongly-unfilled `Any`).

The component inventory ("I have 2 Chaos Seeds…") is the single source of truth; the essence pool is
*derived* (`inventoryEssences`). Persisted in `localStorage` under `rw3_inventory`; the build/wishlist
under `rw3_wishlist`.

---

## 8. Monster sprites animate in **pure CSS** from the original spritesheets

Char art is a spritesheet, not a single image. Format (from the game's `Anim` loader): frames are
square, `frame_size = (60 if width%60==0 else 16) * (1 + 2*radius)`; the **idle animation is the last
row**, all `columns` frames; it advances every 6 game-frames at 30fps ≈ **5fps**.

We deliberately do **not** pre-render anything (an earlier APNG approach pulled in Pillow and was
reverted). Instead:
- `extract.py` records `cols`/`rows` per unit (read from the PNG header, §1).
- `unitSprite()` emits a `<div class="sprite c{cols}" style="--cols;--rows;background-image:…">`.
- CSS sizes the sheet so one frame = `--d` px, offsets `background-position-y` to the idle row, and a
  `steps(cols)` keyframe walks `background-position-x` across the row.
- `injectSpriteKeyframes()` writes one `@keyframes sprN` per distinct frame count at runtime (you
  can't pass a CSS `var()` to `steps()`, so the count must be literal — hence one rule per N, of which
  there are only two: 2 and 4).

Only **unit** icons are spritesheets. Equipment/spell/component icons are plain `<img>` (`iconImg`).

Icon filenames are **lowercased** on copy (`copy_icons.py`) because Windows is case-insensitive but
web hosts aren't; `get_asset()` already lowercases, and the copier matches case-insensitively.

---

## 9. Frontend conventions (`app.js`, ~1k lines, no modules)

- One `DATA = await fetch('data.json')` on load; everything renders from it. Lookups built in
  `init()`: `EQ_BY_NAME`, `CP_BY_NAME`, `SPELL_BY_NAME`, `UNITS`.
- Each tab has a plain state object (`EQ`, `CP`, `SP`, `MON`) with `search`, chip-filter `Set`s, etc.,
  and a `render*()` that filters `DATA.*` and rebuilds the grid's innerHTML. Cards are strings, not
  components.
- **Chips**: `buildChips()` returns a `Set` and wires toggling. **Stat search** (`makeStatSearch`)
  is a reusable autocomplete that adds removable "Modifies/Scales-with X" filter chips; the `mod_stats`
  / `use_stats` arrays come from the game's bonus dicts vs. a spell's own `stats` (programmatic, not
  text). Known boundary: effects that add damage via bespoke handlers (e.g. Boiling Blood's
  `extra_damage`) aren't tagged.
- **One shared floating tooltip** (`unitTip`, `tipHtml`) serves summon chips, build-row item names
  (`data-eqtip`), and `.xref` links; hover = preview card, click = `gotoEntry` navigation.
- `gotoEntry(kind,name)`: switch tab, and if the target card is filtered out, **clear that tab's
  filters and re-render** before scrolling — otherwise the card wouldn't exist. Then fast custom
  scroll-to-top (`smoothScrollTo`) + flash.
- **Per-tab scroll memory** lives in `switchTab` (`TAB_SCROLL`); link navigation overrides it.

---

## 10. Caching & dev

Deliberately **no cache-busting in production** — versioned `?v=` query strings and `no-cache` on
`data.json` were removed; caching is left to the host (GitHub Pages sends ETag + `max-age`). The
unused `IV` constant is kept empty.

For local dev, `devserver.py` serves `site/` with `Cache-Control: no-store`, so edits always show on
reload (the prior staleness pain). `.claude/launch.json` points the preview at it. **Do not** "fix"
dev staleness by adding cache-busting to the shipped HTML.

One transition caveat: changing an icon's bytes at the same URL can briefly mis-render for visitors
who cached the old bytes, until their cache revalidates (~10 min on Pages, or a hard refresh).

---

## 11. Build & deploy

- `python build.py` = `extract.py` → `copy_icons.py` → `tests.py` (a post-build gate). That's it —
  **no Pillow dependency** anymore. `make_favicon.py` is a one-off (favicon is a committed static
  asset); run it manually only if the source icon changes.
- **Data-integrity tests (`tests.py`)** re-derive facts from the live game and assert `site/data.json`
  matches what the game itself renders, so they need the game install and **can't run in CI** — they
  run locally as the final step of `build.py` (a failing verifier fails the build). Current verifiers:
  `verify_resists.py` rebuilds the bestiary roster, applies the game's `set_default_resistances` (§6),
  renders resist lines through the game's own examine draw logic, and compares every monster;
  `verify_descriptions.py` re-implements the game's `draw_examine_spell`/`draw_examine_upgrade` text
  assembly and compares every spell and upgrade description. Both are independent of
  `extract.py`'s assembly code (they only borrow the reconstructed `tooltip_colors`/`TT_ATTRS` color
  tables, since the UI module isn't importable here). Add a verifier here when a new extracted field
  has an authoritative game-render to check against.
- Build venv deps: `tcod numpy pygame dill` (the game's runtime). Python 3.10 to match the game.
- Deploy: `.github/workflows/deploy.yml` runs `share.py --cards` (the only step needing anything
  beyond the stdlib — it installs Playwright and screenshots each card for the link previews, §19)
  and then uploads `site/` to GitHub Pages on push to `main`. Its output lands in `site/s/`, which
  is gitignored, so nothing generated there is ever committed. Pages had
  to be enabled once via API (`gh api -X POST repos/<owner>/<repo>/pages -f build_type=workflow`)
  because the workflow's `GITHUB_TOKEN` couldn't self-enable it on a fresh repo. Git remote is **SSH**,
  which matters: the auth token lacks `workflow` scope, so an HTTPS push of workflow files would be
  rejected — SSH isn't.
- **There is an external automation** (not in this repo's scripts) that periodically commits
  *"Update data for game patch (… changed)"* and redeploys — i.e. something re-runs the build against
  an updated game install. If you change `data.json`'s schema, that job and `app.js` must stay in sync.
  Since the build no longer needs Pillow, that job's environment doesn't either. **It must also commit
  `ids.json`** — `extract.py` appends to it when the game gains content (§13); dropping that file would
  re-randomize ids and break every existing share-URL. **With the live/beta split (§17) it must build
  *both* branches** (switch Steam branch between passes) and commit `data.json`, `data.<branch>.json`,
  and `versions.json` — each pass upserts only its own branch, so order doesn't matter.

---

## 13. Stable IDs (and where state lives)

Stable integer ids exist so **shareable Guides** (§15) survive content additions with **no server/db**.
The URL is owned solely by the Guide (`?g=`); everything else is local: the equipment **build**,
component inventory, component→item assignments, scroll, and active tab (`#hash`).

- **`ids.json`** (committed, repo root) maps `display name → small int`, per category (`equipment`,
  `spell`, and `sp` — see §15), and is the source of truth for ids. **`ids.py`** maintains it
  **append-only**: an existing name never changes id, a removed name keeps its id reserved (never
  reused), a new name gets `max+1`. `extract.py` calls into `ids.py` on every full build and emits the
  resolved `id` onto each equipment/spell entry in `data.json` (the frontend never fetches `ids.json`).
  `python ids.py` re-applies ids to an existing `site/data.json` without a game rebuild (how it was
  bootstrapped — and how the `sp` category was added without re-running the game).
- **Why integers, not class names:** compact URLs, and class names aren't unique for the factory-built
  items (§3). The stable *key* behind the map is the display name (game-unique; addition-stable).
- **The equipment Wishlist is `localStorage`, not the URL.** `WISH` (a Set of equipment *names*; the
  UI labels it "Wishlist") persists under `rw3_build` via `loadBuild`/`saveBuild`; explicit actions
  (toggle, clear, clear-built) save. It deliberately does **not** touch the URL, which is reserved for
  the Guide, so the two features never fight over query params. (An earlier iteration put it in `?b=`;
  reverted once the Guide became the sharing surface. Equipment `id`s are now used only by the Guide's
  equipment track, not the Wishlist.)
- **Guide → Wishlist is an explicit, one-way action.** A guide never silently mutates the reader's
  Wishlist: the Guide's view-mode **"Send to Wishlist"** button (`sendGuideEquipToWishlist`) unions its
  equipment into `WISH` and saves. (Edit mode has the reverse: **"Import from Wishlist"** copies the
  Wishlist into the guide's Core via `importBuildEquipment`.)
- The legacy `spell` category is kept but **unused** — the Guide uses the combined `sp`
  category instead. Harmless to keep (append-only) and reserved.

---

## 14. Things deliberately not done / open ideas

- **Final bosses** in the monster tab — now **included** (see §6, `extract_bosses`). The related
  boss sub-forms a boss transforms into are carded only when AST-referenced in code, not prose.
- **Optimal build allocation** (§7) — greedy is good enough; exact bin-packing wasn't worth it.
- **Monsters' own "summons" chips** — monster cards rely on AST `refs` inline links rather than a
  separate chip row; fine because their spawn behavior is in prose/passives.
- **Per-entry share links** — now **built** (§19): a generated page per entry so Discord unfurls
  a picture of the actual card. Still not done: previews for *Guides* (`?g=` carries the whole
  build in the URL, so there is nothing static to pre-render) or for costumes (spoilers).
- **Guide freeform notes** (§15) — deliberately omitted (a single ≤40-char title is the only free
  text); prose would blow up the URL. The SP track is also a flat per-section sequence, *not* a fully
  interleaved cross-spell SP timeline — both are possible future `VER` bumps.

---

## 15. Guides — shareable build guides (`?g=`)

The **Guide tab** lets a user author a strategy guide (an SP plan of spells & upgrades + an equipment
plan) and share it as a plain link. Same serverless rule as §13: **the URL is the only store.** It is
VIEW mode when the URL carries a `?g=`, and EDIT mode otherwise (or after clicking Edit). A reader
copies the guide's equipment into their own Wishlist explicitly via the **Send to Wishlist** button
(§13) — opening a guide never auto-mutates the Wishlist.

- **Two independent "supersections":** the **SP track** (spells & upgrades, in priority/spend order
  — including equipment-granted forbidden spells; an upgrade is its *own* line item, not attached to its spell)
  and the **Equipment track**. Each is an ordered list of labeled **sections**; each section holds
  ordered **items**; each item is an **OR-group** of ids (alternatives, "A or B").
- **Stable `sp` ids** (`ids.py: assign_sp`): one combined namespace for spells *and* upgrades, keyed
  `"Spell"` for a spell and `"Spell::Upgrade"` for an upgrade (the `::` makes the two key-spaces never
  collide). `extract.py` emits `sp_id` onto each spell and each upgrade dict. Combined (vs. a separate
  upgrade category) is deliberate: the SP stream stays pure ids with **no per-token type marker** —
  `SP_BY_ID` disambiguates spell vs. upgrade at render time. Forbidden spells and their upgrades are
  included; the Guide labels the spell as equipment-granted instead of showing its internal level as
  an SP cost, while its upgrades retain their normal SP costs.
- **Encoding** (`encodeGuide`): `?g = VER _ <equipment> _ <sp> _ <title?>` (top-level sep is `_`, one
  of the few chars `URLSearchParams` leaves un-percent-encoded, so the shared URL stays clean). A
  track is sections run together; an **uppercase heading letter** both starts and labels each section
  (`C`Core `E`Early `T`Late `L`Luxury `U`Utility `D`Defensive `A`AoE `N`Not-Recommended `M`Maybe `V`/`W`/`X`Variant 1/2/3).
  Within a section, items are `.`-separated and OR-alternatives `-`-separated; ids are **base36 (lowercase)**,
  which is *why* uppercase is free for headings. Title is the trailing field left **raw** (don't `encodeURIComponent`
  — `URLSearchParams` already encodes the whole value; `slice(3).join(SEP)` on decode lets a title even
  contain `_`), ≤40 chars — the one allowed free text. The heading set and `VER` are **append-only**
  like ids — a new heading takes an unused letter, and `VER` lets a future format change branch without
  breaking old links.
- **Custom-titled sections** (`CUSTOM = 'Z'`): a section heading can be a free-text label instead of a
  fixed vocab letter. On the wire it's `Z` + a **1-char base36 length** + that many label chars (e.g.
  `Z9big-budget`). The **length prefix** (not a terminator) is load-bearing: it lets the parser *count*
  the label region instead of scanning, so the label can contain `-` (the OR-separator) and spaces
  without ambiguity — `parseTrack` is index-based for exactly this. The label alphabet is restricted to
  **`[a-z0-9]` + space + hyphen + apostrophe** (`cleanCustom`): that keeps the shared URL clean (only
  `'` ever percent-encodes; space rides as `+`) and structurally safe (no uppercase=section, `.`=item,
  or `_`=field collisions). Encoding is **raw, not bit-packed** — a denser base-65 repack (~0.88
  chars/symbol, ~3 chars saved on a 30-char label) was considered and rejected: the field is tiny and
  raw keeps the section name human-readable in the link. Edit UI: a `Custom…` dropdown option swaps the
  heading `<select>` for a text input (`data-sec-custom`); like the title input it updates model+URL on
  `input` **without** re-rendering, so focus isn't stolen mid-type. Length ≤30 (`GUIDE_CUSTOM_MAX`).
- **No id ceiling:** ids are variable-length and self-delimiting (a run of `[0-9a-z]` between the
  uppercase / `.` / `-` markers), so when `sp` grows past 36² it just spends one more char on those
  ids. Nothing migrates; unknown ids drop on decode (§13).
- **The one hard rule** (`sanitizeUpgrades`, enforced on decode *and* every edit): an upgrade is only
  legal if its parent spell appears in a **strictly earlier** SP item — you can't upgrade a spell you
  haven't learned. The editor also: only offers upgrades of present spells, cascade-removes a spell's
  upgrades, and rejects a drag that would orphan an upgrade. **Core is mandatory** (one per track,
  heading-locked); other sections are add/remove/reorder-able. Drag moves items within a supersection
  only — never across the SP↔Equipment line.

---

## 17. Versioning — live vs beta datasets (one id namespace)

The game ships two Steam branches: the default (**live**) and an opt-in **beta**. The
compendium can serve both and let the reader switch between them.

**Detecting the version (`gameinfo.py`).** The game's *own source carries no version
string* — there is no `VERSION`/`__version__`/changelog anywhere in the `.py` files. Steam,
however, records the exact build and the installed branch in the app manifest one level up
from the install dir (`<steamapps>/appmanifest_4366330.acf`): `buildid` (monotonic per push)
and `UserConfig.BetaKey` (`""`/absent = live, `"beta"` = beta). `gameinfo.branch_info(GAME)`
parses these; `extract.py` stamps `branch`/`branch_label`/`build_id` onto each data file.

**Two datasets, built one branch at a time.** `extract.py` reads a *single* live install and
Steam only checks out *one* branch into that folder at a time, so producing both datasets is a
**two-pass** job:

```
Steam on default → build.py → site/data.json        (branch "live")
Steam on beta    → build.py → site/data.beta.json   (branch "beta")
```

Live deliberately keeps the canonical `data.json` name (stable share URLs; the deploy/automation
default); every other branch is `data.<branch>.json` (`gameinfo.data_filename`). Each build
**upserts only its own entry** into `site/versions.json` (`gameinfo.update_versions`) — the other
branch's entry is preserved, so the two passes are order-independent. `copy_icons.py` reads the
branch's data file, so beta-only art is unioned into the shared `site/icons/` pool (filename is
the key; identically-named art shared by both is copied once — the §10 edge). **`copy_icons` also
*writes back* the data file** (to stamp `has_icon` flags) — it must write the **same** branch file
it read (`DATA_FILE`), never a hardcoded `data.json`. Getting this wrong makes a beta build silently
clobber live's `data.json` with beta content (a bug that bit twice: the read was branch-aware but
the write wasn't). The verifiers
(`verify_*`) also read the active branch's data file, so `build.py`'s post-build gate compares the
*checked-out* branch's game against the *matching* data file.

**One shared, append-only id namespace across branches — load-bearing.** `ids.json` is keyed by
display name and append-only (§13). It is **not** rebuilt per branch: whichever branch you build
appends only *its* new names, so a beta-only spell just gets an id that's absent from the live
dataset (and drops harmlessly on decode, §15), while a name present in both keeps **one** id in
both. Consequence: a Guide's ids mean the same thing in whichever version has that content, and a
beta rebalance that changes a spell's stats but keeps its name keeps the same id (each dataset
renders its own numbers). A beta *rename* falls under §3's accepted rename behavior. **Never make
a per-branch id space** — it would force every id to be interpreted relative to a branch.

**Frontend selection + the `v` URL param (`app.js` `initVersions`).** On load the frontend fetches
`versions.json`; if absent or single-entry it silently falls back to the legacy single-`data.json`
behavior (no selector). Otherwise it renders a header `<select>` and picks the active version from
**URL `v=` → default (`live`)**. `activeDataFile()` decides which JSON to fetch. Switching versions
does a **full `location.reload()`** — the app has ~1k lines of module-global lookup tables
(`EQ_BY_NAME`, `SP_BY_ID`, …) and a reload rebuilds them all cleanly, far safer than re-running
`init`'s wiring in place.

The branch rides in the URL as a **human-readable** `v=<branch>` param — `?g=…&v=beta` shows at a
glance that a shared Guide targets beta — kept **separate** from the `g=` guide string (so the guide
encoding, §15, is untouched and needs no `VER` bump). `syncVersionUrl` keeps it clean: `v` is
present only for a non-default branch (live omits it), written with `replaceState`. It runs *before*
the Guide reads the URL, and `updateGuideUrl` preserves other params, so `v` and `g` never fight;
`guideCopyLink` copies `location.href`, so a copied beta-guide link carries `v=beta`. Opening such a
link loads `data.beta.json` first, so the guide's ids resolve against beta.

**The automation (§11) must build both branches** to enroll beta-only names into the shared
`ids.json` and to refresh both data files + `versions.json`. If it lags on one branch, the worst
case is a not-yet-enrolled id that drops gracefully — no corruption, because everything is
append-only and keyed by name.

---

## 18. Recent changes — first-seen dates (`history.py`, `site/history.json`)

The game carries no timestamps (§17: not even a version string), so "what's new" has to be
recorded by us. `site/history.json` maps, per branch, **date → kind → names that first appeared
that day**, plus `builds` (date → Steam build id) and `baseline` (kind → the date that kind was
first imported wholesale). It is **append-only and must be committed** alongside the data file,
exactly like `ids.json`.

Two writers: `history.update()` is called by `extract.py` on every build (stamping anything new
with that build's `generated` date + build id), and `python history.py` **backfills from git** by
replaying every committed revision of `site/data*.json` oldest-first and taking each commit's
date. The backfill is idempotent and only fills gaps, so it is safe to re-run.

**Changed entries (buffs / nerfs / reworks)** are recorded too, under `changed` → date → kind →
name → a list of `{f: field, o: old, n: new}` rows. A patch is mostly *rebalance*, so tracking only
additions would miss most of it. The old values come from **the data file the build is about to
overwrite** — `extract.py` reads it just before writing, so no snapshot has to be stored. Two
consequences: a rebuild with no game change records nothing (the file it read is identical), and
change-tracking can only compare *consecutive* builds. `python history.py changes <branch> <rev>`
records a diff against a committed revision instead, for catching up a build that predates this.

Diffing skips `DERIVED` fields (`id`, `refs`, `btips`, `mod_stats`, …) — an id shuffle or a new
cross-ref is not a balance change. Lists of named dicts (upgrades, abilities) are matched **by
name**, so a reordered list doesn't read as "everything changed", and plain lists are compared as
sets. **Guard:** if more than `CHURN_LIMIT` (30%) of a kind changes in one build it is treated as
an extraction change and recorded as nothing at all — see the invariant below.

`baseline` entries are excluded from the UI: the initial bulk import, and the costumes that all
appeared the day the *extractor* learned to read the wardrobe, are not game content changes.

### ⚠️ Intended invariant (NOT yet enforced): only real game changes belong here

The screen must show **content the game added**, never churn this project caused. If a rebuild
adds or renames entries because *we* changed extraction — a parser bug fix, a new field, a
widened unit sweep — that is **not** a recent change and must not surface as one.

`baseline` only covers the case where a whole *kind* appears for the first time. It does **not**
cover a partial extraction change, and there is already one such entry in the committed history:
**live, 2026-06-09, "221 units"** — that was the extractor learning to see more units, not a
patch. (Tell-tale: the group carries no build id, because that commit predates build stamping.
A build id is good evidence of a real patch, but its absence is not proof of the opposite.)

**When you make an extraction change that shifts what gets emitted**, the fix is to write the
updated data file while *preserving the old first-seen dates* for those records — i.e. judge
whether each new name is new **content** or newly **visible**, and only let genuine content
through to `history.json`. Nothing automates that judgment today; it is a manual step, and
`history.json` can be hand-edited (it is plain, sorted, human-readable JSON) to move mistakenly
recorded names back to an earlier date or to the branch's baseline.

**Starting a branch over:** `python history.py reset <branch> [date]` collapses everything that
branch has recorded into one baseline, so its screen reads "Nothing so far" and only future
additions appear. The names are **kept** (filed under the baseline date) — that is what stops the
next build from reporting the entire catalogue as new. This was done to **live**, whose recorded
history was almost entirely extraction churn (the 2026-06-09 case above) rather than patches;
beta's history was genuine per-patch data and was left intact.

---

## 16. Essence tags have **canonical one-letter codes** (not first-initial)

Components carry essence tags (`Fire`, `Dark`, `Holy`, …). Everywhere the crafting UI shows an essence
compactly — the colored code chips on component tiles and recipe slots (`essenceCell`, `slotCell`), and
the **"Total"** readout at the bottom of the Equipment-tab components drawer (`essenceSummaryHtml` over
the *unassigned* pool, rendered as one chip per essence held — 4× Fire = `FFFF`, not "F 4") — it uses a
**single canonical letter**, the same one the game's crafting tag-filter hotkeys use
(`RiftWizard3.KEY_BIND_DEFS`).

- **These are NOT first letters.** Four pairs clash on first initial, so the game assigns distinct
  letters: **Eye=Y, Dragon=R, Chaos=K, Slime=Z, Ritual=U** (and **Any=∗**). The rest happen to
  be their first letter (`Fire`=F, `Dark`=D, `Holy`=H, …). Using a naive `tag[0]` would collide
  Chaos/Conjuration, Dark/Dragon, Enchantment/Eye, Slime/Sorcery — **don't do that.**
- **Source of truth is the game**, mirrored in two places that must stay in sync: `extract.py`'s
  `tag_abbr` (bakes `abbr` onto each tag in `data.json`) and `app.js`'s `TAG_ABBR` fallback. `tagAbbr(t)`
  prefers `DATA.tags.all[t].abbr`, then `TAG_ABBR`, then first-letter as a last resort.
- **If the game adds an essence tag**, add its canonical letter to *both* maps. If you only rely on the
  first-letter fallback it may silently clash with an existing code.

---

## 19. Share links — a real page per entry, so chat clients can unfurl a card (`site/s/`)

The share icon in every card's bottom-right copies `…/s/<kind>/<slug>/[<branch>/]`, **not**
`index.html#<card id>`. That choice is the whole feature:

- **A hash never reaches the server.** The unfurling bot (Discordbot, Slack, …) only sees what
  the URL returns, and on a static host that would be `index.html`'s one generic title for every
  card anyone shared. There is no server to render per-entry tags, so they are **pre-generated**:
  one ~3 KB page per entry carrying its own `og:*` / `twitter:*` tags, a `theme-color` (the
  entry's first tag colour — Discord paints the embed's left stripe with it), and a picture of
  that entry's card.
- **The page then hands the human off to the app**:
  `location.replace("<../ per segment>" + (location.search || "?v=<branch>") + "#e-…")`. Crawlers
  don't run scripts so they keep the tags; a reader lands on `index.html#<card id>`, which
  `init()` and the `hashchange` listener resolve through `SHARE_ENTRY` into an ordinary
  `gotoEntry()` — the same tab switch, scroll and flash a cross-reference click gives. `replace`
  and not an assignment, so the bounce doesn't sit in history and swallow the back button.
- **The embed is the picture and nothing else.** No `og:title`, no `og:description`, and no
  `<title>` for Discord to fall back to (its title chain is `og:title` → `twitter:title` →
  `<title>`, so leaving the last one in would put the name straight back). The card already *is*
  the name and the stats; an embed that repeats them above the image says everything twice. What
  stays: `og:site_name` as the one line of chrome — also insurance for a client that won't build
  an image-only embed — `theme-color`, and `og:image:alt` carrying the full card text, which is
  where a screen reader now finds it. The no-JS body keeps the name and a link.

### Versions ride in the path, as a suffix

A share link has to open the dataset you were reading, and a query string can't select a
different static page — so the branch is part of the path. It is a **suffix**
(`s/spell/seal-fate/beta/`), not a prefix:

- `s/<kind>/<slug>/` names the entry and is byte-identical whichever version you came from; the
  optional trailing `<branch>/` qualifies it. Lop the tail off a beta link and you get live's
  page for the *same* entry, rather than a path whose second segment has silently changed
  meaning from kind to branch.
- The default branch keeps the short URL, so links already in circulation don't move.
- `app.js` `shareUrlFor()` appends `ACTIVE_VERSION.id + '/'` when it isn't the default — the
  client mints these, so the shape is a contract with `page_rel()` in share.py.
- Pages are per (entry × branch), but **images are deduplicated**: `signature()` hashes each item
  (plus the units it summons, since a summon chip draws that unit's sprite) and a non-default
  branch whose signature matches just points `og:image` at live's existing picture. With the
  branches in sync that is 2,296 pages and still only 1,148 images; only what actually differs,
  or is beta-only, earns a second shot.

### The preview images are screenshots of the real card

`share.py --cards` starts a throwaway HTTP server on `site/` (the page `fetch`es `data.json`,
which `file://` forbids), drives headless Chromium over `index.html`, adds `body.shotmode` and
screenshots each `.card` at `device_scale_factor=2`. **Nothing here re-draws a card** — that is
the point. app.js's card builders stay the only renderer, so a preview cannot drift from the
card it previews, and new fields show up in previews for free.

- `.shotmode` (styles.css) strips the chrome, unstacks the grid and pins a 400 px card width.
  The renderer wraps each card in a `.shot-frame`, so the shot carries a margin of page
  background — a flush crop would leave the card's rounded corners as four bare notches.
- `loading="lazy"` icons and the CSS-background sprite sheets are force-decoded before any
  clipping starts (neither is guaranteed ready just because a card is on screen), and every
  screenshot passes `animations="disabled"` so the CSS idle loop (§8) lands on frame 0 —
  otherwise each rebuild would rewrite every monster image with a different frame.
- Spell **upgrades are forced open** (`details.open = true`) before shooting. On the site they
  collapse so they don't swamp the grid; a preview is one card with nobody to click it, and the
  upgrade list is most of why you'd share a spell.
- Tabs are switched via the app's own `switchTab`: `element.screenshot()` needs the card laid
  out, and an inactive `.tab-panel` is `display:none`.

### Contracts and gotchas

- **`slug()` is duplicated** in app.js and share.py deliberately: identical output on both sides
  is what lets the client mint a share URL from a display name with no lookup table shipped. The
  kind→directory and kind→card-id-prefix tables must also agree (`SHARE_DIR` and
  `KIND_CARD_PREFIX` in app.js vs `KINDS` in share.py) or the links 404.
- **`site/s/` is generated and gitignored.** `build.py` writes the pages — stdlib only, so the
  external data-update automation (§11) gains no dependency and doesn't need to know the
  directory exists — and `.github/workflows/deploy.yml` re-runs `share.py --cards` to shoot the
  images straight into the Pages artifact. ~2,300 pages plus ~100 MB of PNG per deploy, none of
  it in git. Every deploy regenerates both from the current `data.json`, so nothing on our side
  can go stale — but the *client* caches unfurls per URL (Discord's image proxy included), so a
  card whose stats changed can keep showing yesterday's picture in an old message for a while.
- **`og:` URLs have to be absolute**, so share.py needs the site's base URL, in order: `--base`,
  `$RW3_SITE_BASE` (the workflow passes `actions/configure-pages`' `base_url`, which is right
  even behind a custom domain), `site/CNAME`, then the `origin` remote's
  `<user>.github.io/<repo>`. Everything the page *itself* links to stays relative, so the same
  generated file works on localhost.
- Ids aren't involved — a share URL keys off the display name, so unlike a Guide link it does
  **not** survive a rename (§3). A beta-only entry simply has no live-path page, so trimming the
  `beta/` off its URL 404s, which is the honest answer.
- **Costumes are excluded on purpose.** Their art sits behind an explicit per-costume reveal;
  a link preview would show it to a whole channel at once. No share button, no page, and the
  screenshot pass is scoped to the four shareable grids rather than `.card[id]`.
