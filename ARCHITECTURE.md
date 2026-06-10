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

`extract.py` / `copy_icons.py` have a hardcoded `GAME = r"E:\SteamLibrary\...\Rift Wizard 3 Demo"`.
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

## 3. Almost everything keys off the **display name**; builds use stable integer IDs.

The frontend keys cross-reference links and card DOM ids (`s-<slug>`, `e-<slug>`, `u-<slug>`), plus
the component inventory (`localStorage`), all off the **display name**. The **one** thing that does
*not* is the shareable build, which uses stable integer ids (§13).

Facts a future agent should know:
- Display names are currently **unique across all 350 equipment and 186 spells** (the game's own
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
scroll to top, flash). The `refs` array (`[[displayName, kind], …]`, kind ∈ spell|equipment|unit)
drives this. `linkify(html, refs)` only wraps names that are *confirmed references*, located by
position in the rendered text — so there are **no false positives**.

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

`data.units` (412 entries) = the full bestiary (340 monsters: base spawns + evolutions + the rare
rosters) **plus** ~72 summon-only minions, deduped by name. Each is a stat sheet built by
`register_unit`. `is_monster` distinguishes bestiary vs summon-only; `depth` is the earliest spawn
depth for base monsters. Final bosses (`FinalBosses.py`) are **not** included — no clean registry.

**The non-obvious bit (`_unit_passives`):** a unit's innate behaviors (regeneration, spawn
generators, "chance to become") live in `unit.buffs`, but most are `BUFF_TYPE_BLESS`, not
`BUFF_TYPE_PASSIVE`. The game's examine panel filters to `BUFF_TYPE_PASSIVE` **only for units that
are in a level**; for a unit not in a level (exactly our freshly-constructed case) it shows **all**
buffs. So `_unit_passives` intentionally includes *every* buff that yields tooltip text. Filtering
by `BUFF_TYPE_PASSIVE` (the original bug) silently dropped Brain Tree's "spawn a Brain Sapling",
Troll's regen, etc.

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

- `python build.py` = `extract.py` → `copy_icons.py`. That's it — **no Pillow dependency** anymore.
  `make_favicon.py` is a one-off (favicon is a committed static asset); run it manually only if the
  source icon changes.
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

## 13. Stable IDs & shareable build URLs

Builds are shareable as plain links with **no server/db**: the URL is the single source of truth for
the build (component inventory, scroll, and active tab stay local — tab is in the `#hash`).

- **`ids.json`** (committed, repo root) maps `display name → small int`, per category (`equipment`,
  `spell`), and is the source of truth for ids. **`ids.py`** maintains it **append-only**: an existing
  name never changes id, a removed name keeps its id reserved (never reused), a new name gets
  `max+1`. `extract.py` calls into `ids.py` on every full build and emits the resolved `id` onto each
  equipment/spell entry in `data.json` (the frontend never fetches `ids.json`). `python ids.py`
  re-applies ids to an existing `site/data.json` without a game rebuild (how it was bootstrapped).
- **Why integers, not class names:** compact URLs, and class names aren't unique for the 62 factory
  items (§3). The stable *key* behind the map is the display name (game-unique; addition-stable).
- **URL encoding** (`app.js`): the build is the `?b=` query param — sorted equipment ids in **base36**
  joined by `.` (e.g. `?b=0.2x.9p`). `encodeBuild`/`loadWishFromUrl` round-trip it; unknown ids
  (removed content / a newer link) are silently dropped. `updateUrl` uses `history.replaceState` so
  toggling items doesn't flood the back button; a `popstate` handler re-derives the build on
  back/forward. **No more `localStorage` for the build** — two tabs can hold different builds, and the
  🔗 Copy-link button just copies `location.href`.
- **Spells get ids too** even though the build UI is equipment-only today — reserved so a future
  spell/loadout sharing feature can extend `?b=` without renumbering.

---

## 14. Things deliberately not done / open ideas

- **Final bosses** in the monster tab — excluded (no clean registry in `FinalBosses.py`).
- **Optimal build allocation** (§7) — greedy is good enough; exact bin-packing wasn't worth it.
- **Monsters' own "summons" chips** — monster cards rely on AST `refs` inline links rather than a
  separate chip row; fine because their spawn behavior is in prose/passives.
