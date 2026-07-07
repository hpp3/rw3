"""Detect which Steam branch/build of the game is currently installed, so each
build can be tagged and the frontend can offer a live/beta version selector.

The game's own source carries NO version string (grep it — there's no
`VERSION`/`__version__`/changelog). Steam records the exact build and the
installed branch in the app manifest one level up from the install dir:

    <steamapps>/appmanifest_4366330.acf
      "buildid"     "24066992"           -> exact build, monotonic per push
      "UserConfig" { "BetaKey" "beta" }  -> installed branch ("" / absent = live)

extract.py stamps `branch`/`branch_label`/`build_id` onto each data file and
upserts `site/versions.json`; the frontend renders the selector from that.

Only ONE branch is ever checked out into the install dir at a time, so producing
both datasets is a two-pass job: build on the default branch (-> data.json),
switch Steam to beta, build again (-> data.beta.json). Each build tags only its
own branch in versions.json; the other branch's entry is preserved. ids.json is
append-only and keyed by display name, so the two builds share one id namespace
regardless of order (see ARCHITECTURE.md §3/§13).
"""
import os, re, json

APP_ID = "4366330"


def _acf_path(game_dir):
    # game_dir = <steamapps>/common/Rift Wizard 3  ->  <steamapps>/appmanifest_<id>.acf
    steamapps = os.path.dirname(os.path.dirname(os.path.abspath(game_dir)))
    return os.path.join(steamapps, f"appmanifest_{APP_ID}.acf")


def _acf_value(text, key):
    # VDF lines are  "key"\t\t"value" . BetaKey lives inside the UserConfig block,
    # but a flat search is unambiguous (only UserConfig carries a BetaKey); take
    # the last occurrence in case Steam duplicates it.
    m = re.findall(r'"%s"\s+"([^"]*)"' % re.escape(key), text, re.IGNORECASE)
    return m[-1].strip() if m else ""


# Steam names for the game's DEFAULT (non-beta) branch. RW3's manifest reports
# BetaKey "public" when on the default branch (not an empty key), so map that — and
# an absent/empty key — to our canonical "live" id (-> data.json, the default).
DEFAULT_BRANCH_KEYS = {"", "public", "default"}


def branch_info(game_dir):
    """{id,label,build_id} for the branch currently checked out in game_dir.
    Falls back to the 'live' branch (empty build id) if the manifest is absent."""
    beta = build = ""
    try:
        with open(_acf_path(game_dir), encoding="utf-8") as f:
            txt = f.read()
        beta = _acf_value(txt, "BetaKey")
        build = _acf_value(txt, "buildid")
    except OSError:
        pass
    if beta.lower() in DEFAULT_BRANCH_KEYS:
        return {"id": "live", "label": "Live", "build_id": build}
    return {"id": beta, "label": beta[:1].upper() + beta[1:], "build_id": build}


def data_filename(branch_id):
    """Live keeps the canonical data.json (stable share URLs / automation default);
    every other branch gets data.<branch>.json."""
    return "data.json" if branch_id == "live" else f"data.{branch_id}.json"


def update_versions(site_dir, info, generated):
    """Upsert this branch's entry into site/versions.json. Each build tags only
    its own branch; any other branch's entry is left untouched. Live sorts first
    so it's the frontend's default. Returns the full version list."""
    path = os.path.join(site_dir, "versions.json")
    versions = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                versions = json.load(f)
        except (OSError, ValueError):
            versions = []
    entry = {
        "id": info["id"],
        "label": info["label"],
        "file": data_filename(info["id"]),
        "build_id": info["build_id"],
        "generated": generated,
    }
    versions = [v for v in versions if v.get("id") != info["id"]]
    versions.append(entry)
    versions.sort(key=lambda v: (v.get("id") != "live", v.get("id", "")))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(versions, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return versions
