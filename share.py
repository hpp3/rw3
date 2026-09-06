"""Shareable per-entry pages (the card share button's target) + their previews.

Why this exists
---------------
The site is static (GitHub Pages), so a chat client that unfurls a link only
ever sees what the server hands back. A hash like `index.html#e-treelord-staff`
never reaches the server, so every shared card would unfurl as the same generic
"Rift Wizard 3 Compendium" preview. Instead every entry gets its own tiny page
under `site/s/<kind>/<slug>/`, carrying:

  * Open Graph tags for that one entry, and
  * `s/img/<kind>/<slug>.png` -- a picture of that entry's actual card,

so Discord renders something like the screenshots people were already pasting
by hand. The page then redirects a human straight into `index.html#<card id>`,
which app.js resolves back to a gotoEntry() (right tab, scrolled to the card,
flashing).

The card pictures are shot from the real site rather than redrawn here: a
headless browser loads `index.html`, switches it into `.shotmode` (styles.css)
and screenshots each `.card`. That way a preview can never drift from the card
it previews -- there is only one renderer, and it is app.js.

Usage
-----
  python share.py                     # pages only (stdlib; what build.py runs)
  python share.py --cards             # also re-shoot every card image (needs playwright)
  python share.py --cards --limit 8   # ...just a few, for eyeballing
  python share.py --base https://example.com/rw3    # override the absolute base

`site/s/` is generated output and is gitignored: the deploy workflow rebuilds it
into the Pages artifact, so it never has to be committed -- which also means the
external data-update automation doesn't have to know it exists.
"""
import argparse, html, json, os, re, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
OUT = os.path.join(SITE, "s")
IMG = os.path.join(OUT, "img")

SITE_NAME = "Rift Wizard 3 Compendium"
FALLBACK_COLOR = "#5aa9ff"          # --accent, for entries with no tag colour
DESC_LIMIT = 300                    # Discord shows ~350 chars of og:description

# kind -> (url directory, card DOM id prefix). Both halves are a contract with
# app.js: SHARE_DIR and KIND_CARD_PREFIX there have to agree with this table.
KINDS = {
    "equipment": ("equipment", "e-"),
    "spell":     ("spell",     "s-"),
    "component": ("component", "c-"),
    "unit":      ("unit",      "u-"),
}
# kind -> the tab whose grid holds that card, for the screenshot pass.
KIND_TAB = {"equipment": "equipment", "spell": "spells",
            "component": "components", "unit": "monsters"}

STAT_LABEL = {          # mirrors app.js STAT_LABEL
    "range": "Range", "max_charges": "Charges", "damage": "Damage", "radius": "Radius",
    "duration": "Duration", "minion_damage": "Minion dmg", "minion_health": "Minion HP",
    "minion_duration": "Minion dur", "minion_range": "Minion rng", "num_summons": "Summons",
    "hp_cost": "HP cost", "shields": "Shields", "num_targets": "Targets",
    "max_channel": "Max channel", "shot_cooldown": "Shot CD", "strikechance": "Accuracy",
    "cooldown": "Cooldown",
}

MARKUP_RE = re.compile(r"\[([^\]:]+)(?::([^\]]+))?\]")


def slug(s):
    """The same slug app.js mints, so the client builds share URLs without a table."""
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def strip_markup(s):
    """[Nature:nature] -> Nature, [some_name] -> some name (app.js stripMarkup)."""
    return MARKUP_RE.sub(lambda m: m.group(1).replace("_", " "), s or "")


# ---------------------------------------------------------------------------
# Where the site lives. og: tags have to be absolute, unlike everything the page
# itself links to. CNAME first (that's what a custom domain looks like on
# Pages), then the git remote's user/repo.
# ---------------------------------------------------------------------------
def detect_base():
    env = os.environ.get("RW3_SITE_BASE")
    if env:
        return env.rstrip("/")
    cname = os.path.join(SITE, "CNAME")
    if os.path.exists(cname):
        host = open(cname, encoding="utf-8").read().strip().splitlines()
        if host and host[0].strip():
            return "https://" + host[0].strip().rstrip("/")
    try:
        url = subprocess.check_output(["git", "-C", HERE, "remote", "get-url", "origin"],
                                      stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        url = ""
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    if not m:
        sys.exit("share.py: can't work out the site's base URL -- pass --base https://...")
    user, repo = m.group(1).lower(), m.group(2)
    # <user>.github.io is served at the domain root; any other repo at /<repo>/.
    if repo.lower() == user + ".github.io":
        return "https://%s.github.io" % user
    return "https://%s.github.io/%s" % (user, repo)


# ---------------------------------------------------------------------------
# Per-kind preview text. Newlines survive into the Discord embed, so these read
# like the card does: a meta line, the effect, then the structured extras.
# ---------------------------------------------------------------------------
def _join(parts, sep=" · "):
    return sep.join(p for p in parts if p)


def _summons(item):
    names = ["Any " + p for p in item.get("pool_summons") or []] + list(item.get("summons") or [])
    return "Summons: " + ", ".join(names) if names else ""


def equipment_desc(e):
    recipe = ", ".join("%d× %s" % (n, tag) for tag, n in e["recipe"])
    return [
        _join([e.get("slot"), ", ".join(e.get("tags") or [])]),
        strip_markup(e.get("desc")),
        "\n".join("› " + strip_markup(b) for b in e.get("bonuses") or []),
        _summons(e),
        "Recipe (cost %s): %s" % (e.get("recipe_cost"), recipe) if recipe else "",
    ]


def spell_desc(s):
    level = "Forbidden" if s.get("forbidden") else "%s SP" % s.get("level")
    stats = _join("%s %s" % (STAT_LABEL.get(k, k), v) for k, v in (s.get("stats") or {}).items())
    upgrades = ", ".join(u["name"] for u in s.get("upgrades") or [])
    return [
        _join([level, ", ".join(s.get("tags") or [])]),
        strip_markup(s.get("desc")),
        stats,
        _summons(s),
        "Upgrades: " + upgrades if upgrades else "",
    ]


def component_desc(c):
    return [
        _join(["Tier %s" % c.get("tier"), "rare" if c.get("rare") else "",
               ", ".join(c.get("tags") or [])]),
        strip_markup(c.get("desc")),
        _summons(c),
    ]


def unit_desc(u):
    diff = u.get("difficulty") if u.get("difficulty") is not None else u.get("depth")
    role = ("boss" if u.get("is_boss") else "companion" if u.get("is_companion")
            else "" if u.get("is_monster") else "summon")
    rare = u.get("rare") or {}
    flags = [f for f, on in (("Flying", u.get("flying")), ("Immobile", u.get("stationary")),
                             ("Burrowing", u.get("burrowing"))) if on]
    resists = ", ".join("%d%% %s" % (v, t) for t, v in
                        sorted((u.get("resists") or {}).items(), key=lambda kv: -kv[1]))
    abilities = []
    for a in u.get("abilities") or []:
        bits = []
        if a.get("damage"):
            bits.append(_join([str(a["damage"]), "/".join(a.get("damage_type") or [])], " ") + " dmg")
        if a.get("range") and a["range"] > 1.5:
            bits.append("rng %d" % round(a["range"]))
        elif a.get("melee"):
            bits.append("melee")
        if a.get("cool_down"):
            bits.append("cd %s" % a["cool_down"])
        abilities.append(_join([a["name"], _join(bits)], " — "))
    return [
        _join(["%s HP" % u["hp"] if u.get("hp") else "HP varies",
               "%s SH" % u["shields"] if u.get("shields") else "",
               _join(flags), ", ".join(u.get("tags") or [])]),
        _join(["Difficulty %s" % diff if diff else "",
               "%s Elite (%s)" % (rare["class"], rare["group"]) if rare else "", role]),
        "Resists: " + resists if resists else "",
        "\n".join(abilities),
        "\n".join(strip_markup(p) for p in u.get("passives") or []),
    ]


DESCRIBERS = {"equipment": equipment_desc, "spell": spell_desc,
              "component": component_desc, "unit": unit_desc}


def clip(text, limit=DESC_LIMIT):
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rsplit("\n", 1)[0]                 # prefer a whole line
    if len(cut) < limit * 0.6:
        cut = head.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;·—›") + "…"


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
def hex_color(rgb):
    if not rgb:
        return FALLBACK_COLOR
    return "#%02x%02x%02x" % (rgb[0], rgb[1], rgb[2])


def collect(data, branch, seen, entries, clashes):
    """Append this dataset's entries, skipping any (kind, slug) already taken.

    Live is collected first, so a beta-only item still gets a page -- one that
    opens the site against the beta dataset (?v=beta), where its id resolves.
    A slug already claimed by the *same* name is just the other branch shipping
    the same entry; claimed by a different name it's a genuine collision.
    """
    tag_color = {name: info.get("color") for name, info in data["tags"]["all"].items()}
    groups = [("equipment", data.get("equipment") or []),
              ("spell", data.get("spells") or []),
              ("component", data.get("components") or []),
              ("unit", list((data.get("units") or {}).values()))]
    for kind, items in groups:
        for item in items:
            sl = slug(item["name"])
            key = (kind, sl)
            if key in seen:
                if seen[key] != item["name"]:
                    clashes.append((kind, sl, seen[key], item["name"]))
                continue
            seen[key] = item["name"]
            tags = item.get("tags") or []
            entries.append({
                "kind": kind, "branch": branch, "name": item["name"], "slug": sl,
                "card_id": KINDS[kind][1] + sl,
                "desc": clip("\n".join(p for p in DESCRIBERS[kind](item) if p)),
                "color": hex_color(tag_color.get(tags[0]) if tags else None),
            })


def build_entries():
    versions = []
    vpath = os.path.join(SITE, "versions.json")
    if os.path.exists(vpath):
        versions = json.load(open(vpath, encoding="utf-8"))
    if not versions:
        versions = [{"id": "live", "file": "data.json"}]
    # The default branch (live, or the first listed) goes first, so its entries
    # win the slug and every other branch only contributes what it alone has.
    default = next((v for v in versions if v["id"] == "live"), versions[0])
    ordered = [default] + [v for v in versions if v is not default]

    seen, entries, clashes = {}, [], []
    for v in ordered:
        path = os.path.join(SITE, v.get("file", "data.json"))
        if not os.path.exists(path):
            print("  ! skipping %s: %s missing" % (v["id"], v.get("file")))
            continue
        collect(json.load(open(path, encoding="utf-8")), v["id"], seen, entries, clashes)
    # slug() is not injective in principle, and app.js keys card DOM ids off it
    # too -- so a clash is already an in-app bug (two cards, one id), and here it
    # would silently leave one entry's share button pointing at the other's page.
    # Fail loudly instead; adding a disambiguator would have to be done on both
    # sides at once, since the client mints these URLs itself.
    if clashes:
        sys.exit("share.py: %d slug collision(s), e.g. %s"
                 % (len(clashes), "; ".join("%s/%s <- %r and %r" % c for c in clashes[:3])))
    blank = [e for e in entries if not e["slug"]]
    if blank:
        sys.exit("share.py: %d entr(ies) slug to nothing: %s"
                 % (len(blank), ", ".join(e["name"] for e in blank[:5])))
    return entries, default["id"]


# ---------------------------------------------------------------------------
# Page emission
# ---------------------------------------------------------------------------
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<link rel="icon" type="image/png" href="../../../favicon.png">
<link rel="canonical" href="%(url)s">
<meta name="description" content="%(desc)s">
<meta name="theme-color" content="%(color)s">
<meta property="og:site_name" content="%(site)s">
<meta property="og:type" content="article">
<meta property="og:title" content="%(name)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(url)s">
<meta property="og:image" content="%(img)s">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="%(name)s in the %(site)s">%(dims)s
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%(name)s">
<meta name="twitter:description" content="%(desc)s">
<meta name="twitter:image" content="%(img)s">
<!-- Humans get bounced into the app immediately; crawlers don't run scripts, so
     they keep the tags above. replace() rather than assign() so the redirect
     doesn't sit in history and swallow the back button. Any query already on
     the URL wins, so a hand-edited ?v= still works. -->
<script>location.replace("../../../" + (location.search || "%(query)s") + "#%(card)s");</script>
<style>
  body{margin:0;background:#0c0e14;color:#dce3f0;
       font:15px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif;
       display:flex;min-height:100vh;align-items:center;justify-content:center}
  .box{text-align:center;padding:24px}
  .box img{max-width:min(420px,90vw);border-radius:10px}
  h1{font-size:19px;margin:14px 0 4px}
  p{color:#8b97ad;font-size:13px;margin:0}
  a{color:#5aa9ff}
</style>
</head>
<body>
<div class="box">
  <img src="%(img_rel)s" alt="%(name)s"%(size)s>
  <h1>%(name)s</h1>
  <p><a href="../../../%(query)s#%(card)s">Open in the %(site)s</a></p>
</div>
</body>
</html>
"""


def png_size(path):
    """(width, height) from the IHDR, so og:image:width/height can be filled in."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def write_pages(entries, base, default_branch):
    for d, _prefix in KINDS.values():
        shutil.rmtree(os.path.join(OUT, d), ignore_errors=True)   # drop stale slugs
    for e in entries:
        d = KINDS[e["kind"]][0]
        rel = "s/%s/%s/" % (d, e["slug"])
        img_name = "s/img/%s/%s.png" % (d, e["slug"])
        size = png_size(os.path.join(SITE, img_name.replace("/", os.sep)))
        # &#10; rather than a literal newline: the description rides in an
        # attribute, and Discord honours the entity while an HTML parser can't
        # normalise it into a space.
        esc = lambda s: html.escape(str(s), quote=True).replace("\n", "&#10;")
        fields = {
            "title": esc("%s — %s" % (e["name"], SITE_NAME)),
            "name": esc(e["name"]),
            "desc": esc(e["desc"]),
            "site": esc(SITE_NAME),
            "color": e["color"],
            "url": esc(base + "/" + rel),
            "img": esc(base + "/" + img_name),
            "img_rel": "../../../" + img_name,
            "card": esc(e["card_id"]),
            # A branch-only entry has to open against its own dataset or its
            # card isn't there; the default branch needs no marker.
            "query": "" if e["branch"] == default_branch else "?v=" + esc(e["branch"]),
            # Known only once the images exist, so a pages-only run omits both
            # and lets the client measure the image itself.
            "size": ' width="%d" height="%d"' % size if size else "",
            "dims": ("\n<meta property=\"og:image:width\" content=\"%d\">"
                     "\n<meta property=\"og:image:height\" content=\"%d\">" % size) if size else "",
        }
        path = os.path.join(SITE, "s", d, e["slug"], "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(PAGE % fields)
    print("  %d share pages -> site/s/<kind>/<slug>/" % len(entries))


# ---------------------------------------------------------------------------
# Card images: drive the real site with a headless browser and clip each card.
# ---------------------------------------------------------------------------
# Runs in the page once everything has rendered. Wraps each card in a padded
# frame so the shot has a margin of site background around it (the cards have
# rounded corners; a flush crop would leave four odd notches), and makes sure
# every icon and sprite is actually decoded before we start clipping -- the
# grids ship `loading="lazy"` images and CSS background spritesheets, neither of
# which is guaranteed to be ready just because the card is on screen.
PREP_JS = """
async () => {
  document.body.classList.add('shotmode');
  // The four shareable grids only. Costume cards are .card[id] too, but they
  // are spoiler-veiled and deliberately have no share button, so no preview.
  document.querySelectorAll('#eq-grid .card[id],#cp-grid .card[id],#sp-grid .card[id],#mon-grid .card[id]').forEach(card => {
    if (card.parentNode.classList.contains('shot-frame')) return;
    const frame = document.createElement('div');
    frame.className = 'shot-frame';
    frame.id = 'frame-' + card.id;      // what the screenshot pass looks up
    card.parentNode.insertBefore(frame, card);
    frame.appendChild(card);
  });
  const waits = [];
  document.querySelectorAll('img').forEach(img => {
    img.loading = 'eager';
    if (!img.complete) waits.push(new Promise(r => { img.onload = img.onerror = r; }));
  });
  const urls = new Set();
  document.querySelectorAll('.sprite').forEach(s => {
    const m = /url\\(["']?([^"')]+)["']?\\)/.exec(s.style.backgroundImage || '');
    if (m) urls.add(m[1]);
  });
  urls.forEach(u => waits.push(new Promise(r => {
    const i = new Image(); i.onload = i.onerror = r; i.src = u;
  })));
  await Promise.all(waits);
  return document.querySelectorAll('.shot-frame').length;
}
"""


def serve_site():
    """Background HTTP server for site/ -- the page fetches data.json, which
    file:// forbids. Port 0 lets the OS pick, so this never fights devserver.py."""
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=SITE))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def render_cards(entries, limit=0):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("share.py --cards needs playwright:\n"
                 "  pip install playwright && python -m playwright install chromium")

    todo = entries[:limit] if limit else entries
    shutil.rmtree(IMG, ignore_errors=True)
    srv, port = serve_site()
    made = failed = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            # Wide enough for the fixed .shotmode card width plus its frame;
            # 2x so the pixel art and 11px badges stay legible after a chat
            # client scales the preview.
            page = browser.new_page(viewport={"width": 520, "height": 1000},
                                    device_scale_factor=2)
            # Entries are grouped by branch so each dataset is loaded once; in
            # practice only the default branch has any, unless beta is ahead.
            for branch in dict.fromkeys(e["branch"] for e in todo):
                page.goto("http://127.0.0.1:%d/?v=%s" % (port, branch))
                page.wait_for_selector("#eq-grid .card", timeout=60000)
                page.evaluate(PREP_JS)
                for kind in KINDS:
                    batch = [e for e in todo if e["branch"] == branch and e["kind"] == kind]
                    if not batch:
                        continue
                    page.evaluate("t => switchTab(t)", KIND_TAB[kind])
                    for e in batch:
                        frame = page.query_selector("#frame-" + e["card_id"])
                        if frame is None:
                            print("  ! no card for %s/%s" % (kind, e["slug"]))
                            failed += 1
                            continue
                        out = os.path.join(IMG, KINDS[kind][0], e["slug"] + ".png")
                        os.makedirs(os.path.dirname(out), exist_ok=True)
                        # animations=disabled rewinds the sprite idle loop, so a
                        # rebuild doesn't rewrite every monster image with a
                        # different frame.
                        frame.screenshot(path=out, animations="disabled")
                        made += 1
                    print("  %-9s %4d images" % (kind, len(batch)))
            browser.close()
    finally:
        srv.shutdown()
    print("  %d card images -> site/s/img/%s"
          % (made, "  (%d card(s) not found!)" % failed if failed else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cards", action="store_true",
                    help="re-shoot the card preview images (needs playwright)")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="with --cards, only shoot the first N (smoke test)")
    ap.add_argument("--base", metavar="URL",
                    help="absolute site base for the og: tags (default: from CNAME/git remote)")
    args = ap.parse_args()

    base = (args.base or detect_base()).rstrip("/")
    entries, default_branch = build_entries()
    print("== share pages for %d entries (%s) ==" % (len(entries), base))
    if args.cards:
        render_cards(entries, args.limit)
    write_pages(entries, base, default_branch)


if __name__ == "__main__":
    main()
