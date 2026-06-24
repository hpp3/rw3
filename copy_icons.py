"""Copy referenced icon PNGs from the game's rl_data into site/icons/,
normalizing filenames to lowercase. Reads only from the game dir."""
import os, json, shutil

GAME = r"E:\SteamLibrary\steamapps\common\Rift Wizard 3"
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")

SOURCES = {
    "spells":     os.path.join(GAME, "rl_data", "UI", "spell skill icons"),
    "equipment":  os.path.join(GAME, "rl_data", "tiles", "items", "equipment"),
    "components": os.path.join(GAME, "rl_data", "tiles", "crafting"),
    "units":      os.path.join(GAME, "rl_data", "char"),
}

def build_index(d):
    idx = {}
    if not os.path.isdir(d):
        return idx
    for fn in os.listdir(d):
        if fn.lower().endswith(".png"):
            idx[fn.lower()] = os.path.join(d, fn)
    return idx

def main():
    data = json.load(open(os.path.join(SITE, "data.json"), encoding="utf-8"))
    stats = {}
    for cat, key in [("spells", "spells"), ("equipment", "equipment"),
                     ("components", "components"), ("units", "units")]:
        src_idx = build_index(SOURCES[cat])
        dest = os.path.join(SITE, "icons", cat)
        os.makedirs(dest, exist_ok=True)
        found = missing = 0
        missing_names = []
        collection = data[key]
        items = collection.values() if isinstance(collection, dict) else collection
        for item in items:
            icon = item["icon"]  # already lowercase
            src = src_idx.get(icon)
            if src:
                shutil.copyfile(src, os.path.join(dest, icon))
                found += 1
            else:
                missing += 1
                item["has_icon"] = False
                missing_names.append(item["name"])
            if src:
                item["has_icon"] = True
        stats[cat] = (found, missing, missing_names[:15])
    # re-write data.json with has_icon flags
    json.dump(data, open(os.path.join(SITE, "data.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    for cat, (f, m, names) in stats.items():
        print(f"{cat}: {f} copied, {m} missing")
        if names:
            print("   missing e.g.:", ", ".join(names))

if __name__ == "__main__":
    main()
