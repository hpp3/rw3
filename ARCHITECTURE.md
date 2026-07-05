# Architecture & design notes

This is a static, fully client-side compendium for **Rift Wizard 3**. All data is
**extracted from the game's own Python source at build time** into one `site/data.json`,
which a vanilla-JS frontend renders. No server, no framework, no build toolchain beyond
a few Python scripts.

```
game install (Python source + art)  ──extract.py──▶  site/data.json
                                     ──copy_icons──▶  site/icons/**          (static host)
site/{index.html, app.js, styles.css, favicon.png, data.json, icons/}  ──▶  GitHub Pages
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
- **The build is slow (~2 min)** — dominated by `inspect.getsource()` over ~900 classes for the
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
- Display names are currently **unique across all 350 equipment and 196 spells** (the game's own
  tests enforce it). That uniqueness is what makes the name a safe key.
- Python **class names are unique for spells** and for ~288/350 equipment, but **not** for the 62
  factory-built items (11 share `FreeCastStaff`, etc.) — which is *why* we key on display name, not
  class name, both for the DOM/links and as the stable key behind the id map (§13).
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
3. **AST of the source** (chosen): `inspect.getsource()` of the entity's class/factory **and its
   non-framework base classes**, walked for `ast.Name`/`ast.Attribute` identifiers, intersected with
   `IDENT_MAP` (python identifier → display name). This finds `SealFate` in Dread Lash's `cast()`.

Supporting machinery:
- `IDENT_MAP`: built in `build_ident_map`. Maps **every** spell class, equipment class, monster
  factory, **and every zero-arg unit-producing function** in `Monsters`/`RareMonsters` (so
  summon-only units like `BrainSapling` resolve). Ambiguous identifiers (one name → two things) map
  to `None` and are dropped.
- `UNIT_FACTORY`: name → factory, so a unit's *own* refs can be computed from its factory source
  (a summon-only unit isn't in the monster roster loop, so its refs are filled in `main()`).
- `BUFF_IDENT` / `BUFF_CLASS`: buff class identifier → display name / class, built by `build_buff_map`
  by walking the `Buff` subclass tree (`_all_subclasses`, not any module's `__dict__` — so it's
  import-order independent and stable across rebuilds). Kept **separate** from `IDENT_MAP` on purpose:
  a buff class sharing a name with a real spell/unit must never neutralize that identifier via the
  collision rule. `refs_for` consults them as a fallback after `IDENT_MAP` and resolves each buff's
  description per call site (see §6's buff-glossary note).
- **Ref pruning**: in `main()`, refs whose target isn't actually in the output (units with no card)
  are dropped, so every link resolves. There should always be **0 broken refs**.

Known limitation (accepted): references chosen *dynamically* — `random.choice([SpellA, SpellB])`,
lookups by tag/string — aren't caught. This is rare and preferred over false positives. Prose-only
mentions (a description that *names* a spell it doesn't actually invoke in code) also won't link.

---

## 5. Summons come from the game's preview hook, not from `refs`

Each spell/item/component has a `summons` array (distinct unit names) built by `summons_of`, which
calls the game's **`get_extra_examine_tooltips()`** (and `Component.get_unit()`) and keeps the
`Unit` instances. This is the same hook the game uses to draw summon previews, so it's authoritative
and handles dynamic construction that AST can't. Summon chips in the UI link via this data.

So unit cross-links have two sources: structured `summons` (chips) and AST `refs` (inline links in
prose). Both feed the same `units` catalog.

---

## 6. The monster/unit catalog and the "passives = all buffs" subtlety

`data.units` (437 entries) = the full bestiary (351 monsters: base spawns + evolutions + the rare
rosters) **plus** summon-only minions and the 13 Tavern companions, deduped by name. Each is a stat
sheet built by `register_unit`. `is_monster` distinguishes bestiary vs summon-only; `is_companion`
flags the companions; `depth` is the earliest spawn depth for base monsters. Final bosses
(`FinalBosses.py`) are **not** included — no clean registry.

**Companions (`extract_companions`):** the 13 Tavern allies live in `Equipment.all_companions`, a
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
`Fire -100`, hiding its Holy vulnerability — and was wrong for **214 of 412** units.

**Buff glossary (per-entity `btips`, `build_buff_map`/`refs_for`):** many abilities name a buff that
has no card and is never explained — e.g. Brew Concoctions says "gain a stack of *Brewed
Concoctions*" without saying what that does. `build_buff_map` walks every `Buff` subclass and records
`BUFF_IDENT` (identifier → display name) and `BUFF_CLASS` (identifier → class); it does **not**
finalize a description, because the same buff reads differently depending on the args the source
applies — `RegenBuff(heal)` ranges from "Heals 1 HP" to "Heals 100 HP" across the game. Instead each
reference is resolved **at its call site**: `refs_for` finds the `ast.Call` that constructs the buff,
reads its literal args (`_literal_args`/`_buff_call_args`), constructs *that* class with *those* args,
and renders the description (`_resolve_buff`). The result is attached to the referencing entity as
`btips = {name: {desc, color}}` and embedded on each link in the frontend, so `RegenBuff(1)` and
`RegenBuff(10)` show their own numbers, and a name shared by two classes (both display "Regeneration")
resolves to whichever class *that* entity references. Args that aren't literals (a stat/variable)
fall back to filler positional args; a description that still renders a standalone `None` (e.g.
`ChannelBuff`'s `{spell}`) is treated as un-describable and the buff isn't linked. A card links a buff
only when its **source code references the buff class** (the `BUFF_IDENT` fallback in `refs_for`) —
same AST rigor as every other ref, so no prose false positives. The frontend renders them as
hover-only tooltips (`renderBuffSheet` from the link's `data-desc`/`data-color`), styled with a dashed
underline + help cursor so they read as glossary terms, not navigable links.

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
  renders resist lines through the game's own examine draw logic, and compares all 351 monsters;
  `verify_descriptions.py` re-implements the game's `draw_examine_spell`/`draw_examine_upgrade` text
  assembly and compares every spell (196) and upgrade (788) description. Both are independent of
  `extract.py`'s assembly code (they only borrow the reconstructed `tooltip_colors`/`TT_ATTRS` color
  tables, since the UI module isn't importable here). Add a verifier here when a new extracted field
  has an authoritative game-render to check against.
- Build venv deps: `tcod numpy pygame dill` (the game's runtime). Python 3.10 to match the game.
- Deploy: `.github/workflows/deploy.yml` uploads `site/` to GitHub Pages on push to `main`. Pages had
  to be enabled once via API (`gh api -X POST repos/<owner>/<repo>/pages -f build_type=workflow`)
  because the workflow's `GITHUB_TOKEN` couldn't self-enable it on a fresh repo. Git remote is **SSH**,
  which matters: the auth token lacks `workflow` scope, so an HTTPS push of workflow files would be
  rejected — SSH isn't.
- **There is an external automation** (not in this repo's scripts) that periodically commits
  *"Update data for game patch (… changed)"* and redeploys — i.e. something re-runs the build against
  an updated game install. If you change `data.json`'s schema, that job and `app.js` must stay in sync.
  Since the build no longer needs Pillow, that job's environment doesn't either. **It must also commit
  `ids.json`** — `extract.py` appends to it when the game gains content (§13); dropping that file would
  re-randomize ids and break every existing share-URL.

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
- **Why integers, not class names:** compact URLs, and class names aren't unique for the 62 factory
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
- The legacy `spell` category (0–185) is kept but **unused** — the Guide uses the combined `sp`
  category instead. Harmless to keep (append-only) and reserved.

---

## 14. Things deliberately not done / open ideas

- **Final bosses** in the monster tab — excluded (no clean registry in `FinalBosses.py`).
- **Optimal build allocation** (§7) — greedy is good enough; exact bin-packing wasn't worth it.
- **Monsters' own "summons" chips** — monster cards rely on AST `refs` inline links rather than a
  separate chip row; fine because their spawn behavior is in prose/passives.
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

- **Two independent "supersections", because they're separate currencies:** the **SP track** (spells
  & upgrades, in priority/spend order — an upgrade is its *own* line item, not attached to its spell)
  and the **Equipment track**. Each is an ordered list of labeled **sections**; each section holds
  ordered **items**; each item is an **OR-group** of ids (alternatives, "A or B").
- **Stable `sp` ids** (`ids.py: assign_sp`): one combined namespace for spells *and* upgrades, keyed
  `"Spell"` for a spell and `"Spell::Upgrade"` for an upgrade (the `::` makes the two key-spaces never
  collide). `extract.py` emits `sp_id` onto each spell and each upgrade dict. Combined (vs. a separate
  upgrade category) is deliberate: the SP stream stays pure ids with **no per-token type marker** —
  `SP_BY_ID` disambiguates spell vs. upgrade at render time.
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

## 16. Essence tags have **canonical one-letter codes** (not first-initial)

Components carry essence tags (`Fire`, `Dark`, `Holy`, …). Everywhere the crafting UI shows an essence
compactly — the colored code chips on component tiles and recipe slots (`essenceCell`, `slotCell`), and
the **"Total"** readout at the bottom of the Equipment-tab components drawer (`essenceSummaryHtml` over
the *unassigned* pool, rendered as one chip per essence held — 4× Fire = `FFFF`, not "F 4") — it uses a
**single canonical letter**, the same one the game's crafting tag-filter hotkeys use
(`RiftWizard3.KEY_BIND_DEFS`).

- **These are NOT first letters.** Four pairs clash on first initial, so the game assigns distinct
  letters: **Eye=Y, Dragon=R, Chaos=K, Slime=Z, Ritual=U** (and **Any=∗**). The remaining 15 happen to
  be their first letter (`Fire`=F, `Dark`=D, `Holy`=H, …). Using a naive `tag[0]` would collide
  Chaos/Conjuration, Dark/Dragon, Enchantment/Eye, Slime/Sorcery — **don't do that.**
- **Source of truth is the game**, mirrored in two places that must stay in sync: `extract.py`'s
  `tag_abbr` (bakes `abbr` onto each tag in `data.json`) and `app.js`'s `TAG_ABBR` fallback. `tagAbbr(t)`
  prefers `DATA.tags.all[t].abbr`, then `TAG_ABBR`, then first-letter as a last resort.
- **If the game adds an essence tag**, add its canonical letter to *both* maps. If you only rely on the
  first-letter fallback it may silently clash with an existing code.
