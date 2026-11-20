"""Stage 2: turn cached OCR boxes into structured RW3 builds.

    python -I parse.py --cache CACHE_DIR --images DIR [DIR ...] --out OUT_DIR

Layout is located from the text itself (no pixel-border detection), so crops, letterboxing,
ultrawide captures and phone photos work as long as the text is legible:

  left panel     middle panel (character sheet)            right panel
  Realm 21, Turn Spells              Equipment              Realm 21 / <challenge>
  Spells (S)       Spell               Item                 Outcome: VICTORY
  1 Spell  n         Upgrade           Item                 Turns taken: 10 (L) 560 (G)
                   Learn a Spell (S)   Craft Equipment (E)  Spell Casts: ...

Every image gets a `kind`:
  victory_sheet      character sheet + Outcome: VICTORY            (full build)
  in_progress_sheet  character sheet, no outcome yet               (full build, run unfinished)
  defeat_sheet       character sheet + another outcome
  victory_map        map view + Outcome: VICTORY                   (spell names only, no upgrades/equipment)
  defeat_map / in_progress_map
  non_build          anything else
Nothing is snapped silently: each line keeps its raw text, match score and runner-up.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz, process

HERE = Path(__file__).resolve().parent
MATCH_OK = 84          # >= this: confident match
MATCH_LOW = 72         # >= this: accepted but flagged low_confidence
EXTS = {".webp", ".png", ".jpg", ".jpeg", ".bmp", ".gif"}


# ----------------------------------------------------------------------------- text helpers

def norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("`", "'")
    return re.sub(r"[^a-z0-9]+", "", s)


def norm_name(s: str) -> str:
    """Normalisation for matching names: OCR digit/letter confusions folded to letters."""
    s = norm(s)
    return s.translate(str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "|": "l"}))


def to_int(s: str) -> int | None:
    s = s.translate(str.maketrans({"l": "1", "I": "1", "|": "1", "O": "0", "o": "0", "S": "5", "B": "8"}))
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits) if digits else None


def weekly_number(text: str) -> int | None:
    """weekly_273 -> 273. The underscore is often read as a digit, and weekly seeds are 3 digits."""
    n = to_int(text)
    return int(str(n)[-3:]) if n else None


NAME_LIKE = re.compile(r"^[A-Z][\w'.-]*(?: (?:of|the|and|in|to|a|[A-Z0-9][\w'.-]*))*$")


def name_like(text: str) -> bool:
    """Plausible item name (Title Case words, no stray digits, not a shouted banner or a sentence)."""
    t = text.strip(" *.:")
    return bool(NAME_LIKE.match(t)) and not t.isupper() and not re.search(r"\d", t)


class Matcher:
    def __init__(self, names: list[str]):
        self.names = list(names)
        self.keys = [norm_name(n) for n in self.names]

    def best(self, text: str) -> tuple[str | None, float, float]:
        """(name, score, margin over the runner-up)."""
        key = norm_name(text)
        if not key or not self.keys:
            return None, 0.0, 0.0
        top = process.extract(key, self.keys, scorer=fuzz.ratio, limit=2)
        if not top:
            return None, 0.0, 0.0
        name, score = self.names[top[0][2]], top[0][1]
        margin = score - (top[1][1] if len(top) > 1 else 0)
        return name, round(score, 1), round(margin, 1)


# ----------------------------------------------------------------------------- layout

class Box:
    __slots__ = ("x0", "y0", "x1", "y1", "text", "score", "key")

    def __init__(self, b: dict):
        self.x0, self.y0, self.x1, self.y1 = b["box"]
        self.text = b["text"].strip()
        self.score = b["score"]
        self.key = norm(self.text)

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


def find(boxes, pred):
    return [b for b in boxes if pred(b)]


def is_word(b: Box, word: str, min_ratio: float = 85) -> bool:
    return fuzz.ratio(b.key, word) >= min_ratio


def rows_of(boxes: list[Box], lh: float) -> list[list[Box]]:
    """Group boxes into text rows by vertical centre, left-to-right inside a row."""
    rows: list[list[Box]] = []
    for b in sorted(boxes, key=lambda b: b.yc):
        if rows and abs(b.yc - statistics.mean(x.yc for x in rows[-1])) < lh * 0.45:
            rows[-1].append(b)
        else:
            rows.append([b])
    return [sorted(r, key=lambda b: b.x0) for r in rows]


def row_text(row: list[Box]) -> str:
    return " ".join(b.text for b in row)


# ----------------------------------------------------------------------------- parser

class Parser:
    def __init__(self, vocab: dict):
        self.vocab = vocab
        self.alias = vocab.get("spell_aliases", {})
        self.spell_m = Matcher(list(vocab["spells"]) + list(self.alias))
        self.upg_by_spell = {s: Matcher(v["upgrades"]) for s, v in vocab["spells"].items()}
        all_upgrades = sorted({u for v in vocab["spells"].values() for u in v["upgrades"]})
        self.upg_any = Matcher(all_upgrades)
        self.upg_owner = defaultdict(list)
        for s, v in vocab["spells"].items():
            for u in v["upgrades"]:
                self.upg_owner[u].append(s)
        self.equip_m = Matcher(list(vocab["equipment"]))
        self.trial_m = Matcher(vocab["trials"])

    # -- anchors ---------------------------------------------------------------
    def anchors(self, boxes: list[Box]) -> dict:
        a: dict = {}
        sp = find(boxes, lambda b: is_word(b, "spells") and "(" not in b.text)
        eq = find(boxes, lambda b: is_word(b, "equipment") and "(" not in b.text)
        best = None
        for s in sp:
            for e in eq:
                if e.x0 > s.x1 and abs(e.yc - s.yc) < max(s.h, e.h) * 0.8:
                    gap = e.x0 - s.x0
                    if best is None or gap < best[2]:
                        best = (s, e, gap)
        if best:
            a["mid_spells"], a["mid_equipment"] = best[0], best[1]
        a["outcome"] = next(iter(find(boxes, lambda b: b.key.startswith("outcome") or fuzz.partial_ratio(b.key, "outcome") >= 90 and len(b.key) <= 22)), None)
        a["turns"] = next(iter(find(boxes, lambda b: fuzz.partial_ratio(b.key, "turnstaken") >= 88)), None)
        # compare the start of the line: a bare "Spells" / "Equipment (E)" header would
        # otherwise partially match "Learn a Spell (S)" / "Craft Equipment (E)"
        a["learn"] = find(boxes, lambda b: fuzz.ratio(b.key[:11], "learnaspell") >= 80)
        a["craft"] = find(boxes, lambda b: fuzz.ratio(b.key[:14], "craftequipment") >= 80)
        a["left_realm"] = next(iter(find(boxes, lambda b: re.search(r"r\w{2,4}m\s*[0-9lIO|]{1,3}\s*,?\s*turn", b.text, re.I) or fuzz.partial_ratio(b.key, "realm21turn") >= 85)), None)
        # "Spells (S)"; the letter is the player's key binding, so any single key
        a["left_spells"] = next(iter(find(boxes, lambda b: re.fullmatch(r"spells?[a-z0-9]{0,2}", b.key) and "(" in b.text)), None)
        return a

    # -- spells column ---------------------------------------------------------
    def parse_spells(self, rows: list[list[Box]], col_x: float, lh: float, warnings: list[str]) -> tuple[list[dict], list[dict]]:
        spells: list[dict] = []
        lines: list[dict] = []
        # the game indents upgrades by a fixed 18 internal px, which does not scale with the font
        indent_px = max(3.0, lh * 0.15)
        cur = None
        for row in rows:
            text = row_text(row)
            k = norm(text)
            if not k:
                continue
            if (re.search(r"upgrades?avai", k) or re.fullmatch(r"\d*upgrades?available", k) or fuzz.ratio(k, "spells") >= 80
                    or fuzz.ratio(norm(row[0].text), "spells") >= 80):  # header (possibly merged with an overlay)
                continue
            indent = row[0].x0 - col_x
            ocr_conf = min(b.score for b in row)
            legible = len(k) >= 4 and ocr_conf >= 0.85
            sp_name, sp_score, sp_margin = self.spell_m.best(text)
            # a fuzzy (72-84) match is only trusted when the OCR itself was unsure; a clean read
            # that matches nothing well is more likely a name we do not know
            sp_ok = sp_score >= MATCH_OK or (sp_score >= MATCH_LOW and ocr_conf < 0.9)
            own = self.upg_by_spell.get(cur["name"]) if cur and not cur.get("unknown") else None
            up_name, up_score, up_margin = own.best(text) if own else (None, 0.0, 0.0)
            any_name, any_score, any_margin = self.upg_any.best(text)
            indented = indent > indent_px
            line = {"text": text, "indent": round(indent, 1), "ocr_conf": ocr_conf, "spell": [sp_name, sp_score],
                    "own_upgrade": [up_name, up_score], "any_upgrade": [any_name, any_score]}
            choice = None
            if cur and up_score >= MATCH_LOW and (indented or up_score > sp_score + 5):
                choice = ("upgrade", up_name, up_score)
                if indent < lh * 0.08:
                    warnings.append(f"upgrade_without_indent:{up_name}")
            elif sp_ok and (not indented or sp_score >= 95 and sp_score > any_score + 5):
                choice = ("spell", sp_name, sp_score)
                if indent > lh * 0.45:
                    warnings.append(f"spell_with_indent:{sp_name}")
            elif cur and indented and any_score >= MATCH_OK:
                choice = ("upgrade", any_name, any_score)
                cur.setdefault("foreign", []).append(any_name)
            elif sp_ok:
                choice = ("spell", sp_name, sp_score)
            elif not indented and legible:
                choice = ("unknown_spell", text, 0)
            line["chosen"] = list(choice) if choice else None
            lines.append(line)
            if not choice:
                if cur and indented and legible:
                    # an upgrade name from an older build (renamed since): keep the raw text
                    cur["upgrades"].append(text)
                    cur.setdefault("unknown_upgrades", []).append(text)
                    line["chosen"] = ["unknown_upgrade", text, 0]
                    warnings.append(f"unknown_upgrade:{cur['name']}<-{text}")
                else:
                    warnings.append(f"unmatched_spell_line:{text}")
                continue
            kind, name, score = choice
            if kind == "spell":
                name = self.alias.get(name, name)
                if score < MATCH_OK:
                    warnings.append(f"low_confidence_spell:{text}->{name}:{score}")
                cur = {"name": name, "upgrades": [], "confidence": round(score / 100, 3)}
                spells.append(cur)
            elif kind == "unknown_spell":
                cur = {"name": text, "upgrades": [], "confidence": 0.0, "unknown": True}
                spells.append(cur)
            elif name not in cur["upgrades"]:
                if score < MATCH_OK:
                    warnings.append(f"low_confidence_upgrade:{text}->{name}:{score}")
                cur["upgrades"].append(name)
        # a spell renamed since the screenshot: if its upgrades all belong to one other known
        # spell, it is that spell (e.g. Shatterstar -> Dream the Starwhale)
        for s in spells:
            foreign = s.pop("foreign", [])
            if not foreign:
                continue
            owners = set.intersection(*(set(self.upg_owner.get(u, [])) for u in foreign))
            if (s.get("unknown") or s["confidence"] < MATCH_OK / 100) and len(owners) == 1:
                new = owners.pop()
                warnings.append(f"spell_inferred_from_upgrades:{s['name']}->{new}")
                s.update(name=new, inferred_from_upgrades=True)
                s.pop("unknown", None)
            else:
                warnings += [f"foreign_upgrade:{s['name']}<-{u}" for u in foreign]
        for s in spells:
            if s.get("unknown"):
                warnings.append(f"unknown_spell:{s['name']}")
        return spells, lines

    def parse_equipment(self, rows: list[list[Box]], warnings: list[str]) -> tuple[list[dict], list[dict]]:
        items, lines = [], []
        for row in rows:
            text = row_text(row)
            if not norm(text) or fuzz.ratio(norm(text), "equipment") >= (60 if not lines else 75):
                continue  # empty, or a half-cropped column header (badly OCR'd when cut off)
            name, score, margin = self.equip_m.best(text)
            lines.append({"text": text, "match": [name, score, margin]})
            ocr_conf = min(b.score for b in row)
            if score >= MATCH_OK or (score >= MATCH_LOW and ocr_conf < 0.9):
                items.append({"name": name, "known": True, "confidence": round(score / 100, 3)})
                if score < MATCH_OK:
                    warnings.append(f"low_confidence_equipment:{text}->{name}:{score}")
            else:
                warnings.append(f"unmatched_equipment_line:{text}")
                if len(norm(text)) >= 4 and min(b.score for b in row) >= 0.8 and name_like(text):
                    items.append({"name": text, "known": False, "confidence": round(min(b.score for b in row), 3)})
        return items, lines

    def split_across(self, boxes: list[Box], sx: float, ex: float, lh: float, warnings: list[str]) -> list[Box]:
        """OCR sometimes fuses a spell-column line with the equipment line beside it
        ("Orb of Assimilation Venomancer's Vial"). Split at the word boundary that best
        explains the left part as a spell/upgrade and the right part as an item."""
        out = []
        for b in boxes:
            words = b.text.split()
            # only lines that start where spells/upgrades start and run well into the item column
            if not (sx - lh * 0.6 <= b.x0 <= sx + lh * 1.5 and b.x1 > ex + lh) or len(words) < 2:
                out.append(b)
                continue
            best = None
            for k in range(1, len(words)):
                left, right = " ".join(words[:k]), " ".join(words[k:])
                ls = max(self.spell_m.best(left)[1], self.upg_any.best(left)[1])
                rs = self.equip_m.best(right)[1]
                if best is None or ls + rs > best[0]:
                    best = (ls + rs, left, right)
            score, left, right = best
            if self.equip_m.best(right)[1] < MATCH_OK or max(self.spell_m.best(left)[1], self.upg_any.best(left)[1]) < MATCH_OK:
                out.append(b)
                continue
            xs = b.x0 + (b.x1 - b.x0) * len(left) / max(1, len(b.text))
            out.append(Box({"box": [b.x0, b.y0, min(xs, ex - lh), b.y1], "text": left, "score": b.score}))
            out.append(Box({"box": [max(xs, ex), b.y0, b.x1, b.y1], "text": right, "score": b.score}))
            warnings.append(f"split_merged_line:{b.text}")
        return out

    # -- right panel -------------------------------------------------------------
    def parse_summary(self, rows: list[list[Box]]) -> dict:
        texts = [row_text(r) for r in rows]
        out: dict = {"realm": None, "challenge": None, "challenge_raw": None, "outcome": None,
                     "turns_taken": None, "spell_casts": [], "summary_lines": texts}
        realm_i = outcome_i = None
        for i, t in enumerate(texts):
            m = re.match(r"\s*R\w{2,4}m\s*([0-9lIO|]{1,3})\b", t)
            if m and realm_i is None:
                out["realm"] = to_int(m.group(1)); realm_i = i
            if re.match(r"\s*Outcome", t, re.I) or norm(t).startswith("outcome"):
                outcome_i = i
                tail = re.sub(r"^\s*Outcome[s]?\s*[:;.,]?\s*", "", t, flags=re.I).strip()
                out["outcome"] = "VICTORY" if fuzz.ratio(norm(tail), "victory") >= 75 else (tail.upper() or None)
        if realm_i is not None:
            stop = outcome_i if outcome_i is not None and outcome_i > realm_i else min(len(texts), realm_i + 3)
            between = [t for t in texts[realm_i + 1: stop] if norm(t)]
            if between:
                raw = " ".join(between)
                out["challenge_raw"] = raw
                name, score, _ = self.trial_m.best(raw)
                if score >= MATCH_OK:
                    out["challenge"] = name
                elif re.search(r"week", raw, re.I):
                    n = weekly_number(raw)
                    out["challenge"] = f"weekly_{n}" if n else "weekly"
                elif re.search(r"mutat", raw, re.I):
                    out["challenge"] = "Mutated Run"
                elif re.search(r"custom", raw, re.I):
                    out["challenge"] = "Custom Run"
                else:
                    out["challenge"] = raw
        turns_i = next((i for i, t in enumerate(texts) if fuzz.partial_ratio(norm(t), "turnstaken") >= 88), None)
        if turns_i is not None:
            tt = {}
            for t in texts[turns_i: turns_i + 4]:
                for val, kind in re.findall(r"([0-9lIO|.]+)\s*[(\[{]\s*([LGQC0-9]{1,2})\s*[)\]}]?", t):
                    v = to_int(val.split(".")[0]) if "." not in val else float(re.sub(r"[^0-9.]", "", val) or 0)
                    key = "local" if kind.upper() in ("L", "1") else "global"
                    tt.setdefault(key, v)
            out["turns_taken"] = tt or None
        casts_i = next((i for i, t in enumerate(texts) if fuzz.partial_ratio(norm(t), "spellcasts") >= 88), None)
        if casts_i is not None:
            for t in texts[casts_i + 1: casts_i + 12]:
                m = re.match(r"\s*([0-9lIO|]+)\s+(.+)$", t)
                if not m or re.search(r"damage|purchase", t, re.I):
                    break
                name, score, _ = self.spell_m.best(m.group(2))
                out["spell_casts"].append([to_int(m.group(1)), name if score >= MATCH_LOW else m.group(2)])
        return out

    # -- left panel --------------------------------------------------------------
    def left_footer_challenge(self, boxes: list[Box], right_edge: float, lh: float) -> str | None:
        """The trial name printed just above "View Combat Log" at the foot of the left panel."""
        log = [b for b in boxes if b.x0 < right_edge and fuzz.partial_ratio(b.key, "viewcombatlog") >= 85]
        if not log:
            return None
        top = min(log, key=lambda b: b.y0)
        above = [b for b in boxes if b.x0 < right_edge and top.y0 - lh * 2.2 < b.y0 < top.y0 - lh * 0.4 and abs(b.x0 - top.x0) < lh * 2]
        for b in sorted(above, key=lambda b: -b.y0):
            name, score, _ = self.trial_m.best(b.text)
            if score >= MATCH_OK:
                return name
            if re.search(r"week", b.text, re.I):
                n = weekly_number(b.text)
                return f"weekly_{n}" if n else "weekly"
            if re.search(r"mutat", b.text, re.I):
                return "Mutated Run"
        return None

    def parse_left(self, boxes: list[Box], a: dict, right_edge: float, lh: float) -> dict:
        out = {"realm": None, "turn": None, "spells": [], "challenge": self.left_footer_challenge(boxes, right_edge, lh)}
        lr = a.get("left_realm")
        if lr is not None:
            m = re.search(r"R\w{2,4}m\s*([0-9lIO|]{1,3})\s*,?\s*Turn\s*([0-9lIO|.]+)", lr.text, re.I)
            if m:
                out["realm"] = to_int(m.group(1))
                t = m.group(2)
                out["turn"] = float(re.sub(r"[^0-9.]", "", t.translate(str.maketrans("lIO|", "1101"))) or 0) if "." in t else to_int(t)
        hdr = a.get("left_spells")
        if hdr is not None:
            col = [b for b in boxes if hdr.y1 - lh * 0.2 < b.y0 < hdr.y1 + lh * 16 and hdr.x0 - lh < b.x0 < right_edge]
            for row in rows_of(col, lh):
                text = row_text(row)
                if re.match(r"\s*Equipment", text, re.I) or fuzz.partial_ratio(norm(text), "equipmente") >= 90:
                    break
                body = re.sub(r"^\s*[0-9lI|]{1,2}\s+", "", text)
                body = re.sub(r"\s+[0-9lIO|]{1,3}\s*$", "", body)
                name, score, _ = self.spell_m.best(body)
                if score >= MATCH_OK:
                    out["spells"].append(name)
        return out

    # -- one image ---------------------------------------------------------------
    def parse(self, rec: dict) -> dict:
        boxes = [Box(b) for b in rec.get("boxes", []) if b["text"].strip()]
        res: dict = {"image": rec.get("image"), "size": rec.get("size"), "kind": "non_build", "status": "unusable",
                     "reason": None, "warnings": []}
        if rec.get("error"):
            res["reason"] = "ocr_error:" + rec["error"]
            return res
        if len(boxes) < 5:
            res["reason"] = "too_little_text"
            return res
        good = [b.h for b in boxes if b.score >= 0.85 and len(b.key) >= 4]
        lh = statistics.median(good) if good else statistics.median(b.h for b in boxes)
        a = self.anchors(boxes)
        warnings: list[str] = res["warnings"]

        # right panel: everything right of the equipment column, anchored on Outcome/Turns/Realm
        right_x = None
        for key in ("outcome", "turns"):
            if a.get(key) is not None:
                right_x = a[key].x0 if right_x is None else min(right_x, a[key].x0)
        if "mid_spells" not in a:
            # headers cropped off the top: locate the columns from their terminators instead
            pairs = [(l, c) for l in a["learn"] for c in a["craft"] if c.x0 > l.x1 and c.x0 - l.x0 > lh * 6]
            if pairs:
                l, c = min(pairs, key=lambda p: p[1].x0 - p[0].x0)
                top = min((b.y0 for b in boxes if l.x0 - lh * 0.6 <= b.x0 < c.x0 + (c.x0 - l.x0)), default=0) - 1
                a["mid_spells"] = Box({"box": [l.x0, top - 1, l.x0 + lh * 3, top], "text": "Spells", "score": 1.0})
                a["mid_equipment"] = Box({"box": [c.x0, top - 1, c.x0 + lh * 4, top], "text": "Equipment", "score": 1.0})
                warnings.append("sheet_headers_missing_columns_from_terminators")
        mid = "mid_spells" in a
        if mid and right_x is not None and right_x < a["mid_equipment"].x0:
            right_x = None  # outcome found left of the sheet: not a summary pane
        summary = {}
        if right_x is not None:
            top = (a["outcome"] or a["turns"]).y0 - lh * 4
            col = [b for b in boxes if b.x0 >= right_x - lh * 0.6 and b.y0 >= top]
            summary = self.parse_summary(rows_of(col, lh))
        left_edge = a["mid_spells"].x0 - lh * 0.8 if mid else (right_x if right_x is not None else rec["size"][0])
        left = self.parse_left(boxes, a, left_edge, lh)

        res.update({
            "realm": summary.get("realm") or left["realm"],
            "challenge": summary.get("challenge") or left["challenge"],
            "challenge_raw": summary.get("challenge_raw"),
            "outcome": summary.get("outcome"),
            "turns_taken": summary.get("turns_taken"),
            "current_turn": left["turn"],
            "spell_casts": summary.get("spell_casts", []),
            "line_height": round(lh, 1),
        })
        if left["realm"] and summary.get("realm") and left["realm"] != summary["realm"]:
            warnings.append(f"realm_conflict:{summary['realm']}/{left['realm']}")

        if mid:
            sx, ex = a["mid_spells"].x0, a["mid_equipment"].x0
            hdr_y = max(a["mid_spells"].y1, a["mid_equipment"].y1)
            # the equipment column is as wide as the spells column; without a summary pane the
            # right panel holds other text (examine pane), so never read past that width
            rx = min(right_x if right_x is not None else 1e9, ex + (ex - sx) * 0.95)
            learn = [b for b in a["learn"] if abs(b.x0 - sx) < lh * 1.5 and b.y0 > hdr_y]
            craft = [b for b in a["craft"] if abs(b.x0 - ex) < lh * 1.5 and b.y0 > hdr_y]
            sp_end = min((b.y0 for b in learn), default=rec["size"][1] + 1)
            eq_end = min((b.y0 for b in craft), default=rec["size"][1] + 1)
            boxes = self.split_across(boxes, sx, ex, lh, warnings)
            sp_boxes = [b for b in boxes if sx - lh * 0.6 <= b.x0 < ex - lh * 0.6 and hdr_y - lh * 0.2 < b.y0 < sp_end - lh * 0.3
                        and b not in learn]
            eq_boxes = [b for b in boxes if ex - lh * 0.6 <= b.x0 < rx - lh * 0.6 and hdr_y - lh * 0.2 < b.y0 < eq_end - lh * 0.3
                        and b not in craft]
            sp_rows, eq_rows = rows_of(sp_boxes, lh), rows_of(eq_boxes, lh)
            spells, sp_lines = self.parse_spells(sp_rows, sx, lh, warnings)
            equipment, eq_lines = self.parse_equipment(eq_rows, warnings)
            if not learn:
                warnings.append("no_learn_a_spell_terminator")
            if not craft:
                warnings.append("no_craft_equipment_terminator")
            for name, rows in (("spells", sp_rows), ("equipment", eq_rows)):
                ys = [statistics.mean(b.yc for b in r) for r in rows]
                if len(ys) >= 3:
                    pitch = statistics.median(b - a_ for a_, b in zip(ys, ys[1:]))
                    gaps = [round((b - a_) / pitch, 1) for a_, b in zip(ys, ys[1:]) if pitch > 0 and (b - a_) > pitch * 1.6]
                    if gaps:
                        warnings.append(f"row_gap_{name}:{gaps}")
            res.update({"spells": spells, "equipment": equipment, "lines": {"spells": sp_lines, "equipment": eq_lines}})
            if left["spells"]:
                missing = [s for s in left["spells"] if s not in {x["name"] for x in spells}]
                if missing:
                    warnings.append(f"left_panel_spells_missing_from_sheet:{missing}")
                    if not learn:
                        # the spell column is cut off at the bottom: the left panel still lists
                        # every spell, so add the missing ones (their upgrades are unknown)
                        for name in missing:
                            spells.append({"name": name, "upgrades": [], "confidence": None, "from_left_panel": True})
            if not learn or not craft or any(w.startswith("row_gap") for w in warnings):
                res["incomplete"] = True
            outcome = res["outcome"]
            if outcome == "VICTORY":
                res["kind"] = "victory_sheet"
            elif outcome:
                res["kind"] = "defeat_sheet"
            else:
                res["kind"] = "in_progress_sheet"
        else:
            res.update({"spells": [{"name": s, "upgrades": None, "confidence": None} for s in left["spells"]], "equipment": None})
            if left["spells"] or left["realm"] or res["outcome"]:
                res["kind"] = {"VICTORY": "victory_map", None: "in_progress_map"}.get(res["outcome"], "defeat_map")

        # status (July-compatible): full victory build = usable
        if res["kind"] == "victory_sheet":
            if res["spells"] or res["equipment"]:
                res["status"] = "usable"
            else:
                res["reason"] = "empty_build"
        elif res["kind"] == "in_progress_sheet" and (res["realm"] or 0) >= 21 and (res["spells"] or res["equipment"]):
            res["status"] = "usable"
            res["assumed_victory"] = True
            res["reason"] = "assumed_victory_from_final_realm_in_progress"
        else:
            res["reason"] = res["reason"] or res["kind"]
        # modded runs: the Roguelite mod marks its rare variants with a leading "*", and items
        # that exist in neither the game nor the vocabulary come from other mods
        if res.get("lines"):
            texts = [x["text"] for x in res["lines"]["spells"]] + [x["text"] for x in res["lines"]["equipment"]]
            signs = [t for t in texts if t.strip().startswith("*")]
            signs += [e["name"] for e in res.get("equipment") or [] if not e["known"]]
            if signs:
                res["modded"] = signs[:6]
                warnings.append(f"modded:{signs[:6]}")
                if res["status"] == "usable":
                    res["status"] = "unusable"
                    res["reason"] = "modded_run"
        trivial = ("unknown_upgrade", "split_merged_line", "spell_inferred_from_upgrades")
        res["quality"] = "flagged" if any(not w.startswith(trivial) for w in warnings) else "clean"
        return res


# ----------------------------------------------------------------------------- run fingerprint / grouping

def snowflake_ms(name: str) -> int | None:
    head = name.split("_", 1)[0]
    return ((int(head) >> 22) + 1420070400000) if head.isdigit() else None


FINAL_REALM = 21
DEMO_END_MS = 1782864000000  # 2026-07-01 UTC: earlier posts include demo wins, whose last realm was 20


def apply_final_realm(r: dict) -> None:
    """The right pane is a per-level summary: "Outcome: VICTORY" also follows a mid-run level
    clear. Only the final realm is a run win. Demo wins (realm 20, posts before July 2026) are
    recognised but excluded: the user doesn't want demo-era builds in the analysis."""
    if not r["kind"].startswith("victory_") or r.get("realm") is None:
        return
    realm = r["realm"]
    if realm >= FINAL_REALM:
        return
    if realm == FINAL_REALM - 1 and (r.get("posted") or 0) < DEMO_END_MS:
        r["demo_final_realm"] = True
        if r["status"] == "usable":
            r["status"] = "unusable"
            r["reason"] = "demo_win"
        return
    r["kind"] = "level_clear_" + r["kind"].split("_", 1)[1]
    if r["status"] == "usable":
        r["status"] = "unusable"
        r["reason"] = f"level_clear_realm_{realm}"


def fingerprint(r: dict) -> tuple | None:
    tt = r.get("turns_taken") or {}
    casts = tuple(tuple(c) for c in r.get("spell_casts") or [])
    if tt.get("global") is None and not casts:
        return None
    return (r.get("realm"), tt.get("local"), tt.get("global"), casts[:4])


def build_key(r: dict) -> tuple | None:
    if not r.get("spells") and not r.get("equipment"):
        return None
    sp = tuple(sorted((s["name"], tuple(sorted(s["upgrades"] or []))) for s in r.get("spells") or []))
    eq = tuple(sorted(e["name"] for e in r.get("equipment") or []))
    return (sp, eq)


KIND_RANK = {"victory_sheet": 0, "in_progress_sheet": 1, "defeat_sheet": 2, "level_clear_sheet": 3, "victory_map": 4,
             "in_progress_map": 5, "defeat_map": 6, "level_clear_map": 7, "non_build": 9}


def group_runs(results: list[dict]) -> None:
    """Mark images showing the same run (same post pair, or a repost) with run_id / duplicate_of."""
    parent = {r["image"]: r["image"] for r in results}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_fp, by_build = defaultdict(list), defaultdict(list)
    for r in results:
        if r["kind"] == "non_build":
            continue
        fp = fingerprint(r)
        if fp and fp[2] is not None:  # needs the global turn count to be a safe identity
            by_fp[fp].append(r["image"])
        bk = build_key(r)
        if bk and r["kind"].endswith("_sheet") and (len(bk[0]) + len(bk[1])) >= 6:
            by_build[(bk, (r.get("turns_taken") or {}).get("global"))].append(r["image"])
    for group in list(by_fp.values()) + list(by_build.values()):
        for img in group[1:]:
            union(group[0], img)
    # same-post pairs (char sheet + finish map) posted within 3s that agree on spells
    seq = sorted((r for r in results if r["kind"] != "non_build" and snowflake_ms(r["image"])), key=lambda r: snowflake_ms(r["image"]))
    for a, b in zip(seq, seq[1:]):
        if snowflake_ms(b["image"]) - snowflake_ms(a["image"]) <= 3000:
            sa = {s["name"] for s in a.get("spells") or []}
            sb = {s["name"] for s in b.get("spells") or []}
            ta, tb = (a.get("turns_taken") or {}), (b.get("turns_taken") or {})
            same_turns = ta.get("global") is not None and ta.get("global") == tb.get("global")
            if same_turns or (sa and sb and (sa <= sb or sb <= sa) and len(sa & sb) >= 2):
                union(a["image"], b["image"])
    groups = defaultdict(list)
    for r in results:
        groups[root(r["image"])].append(r)
    for members in groups.values():
        if len(members) == 1:
            continue
        members.sort(key=lambda r: (KIND_RANK[r["kind"]], snowflake_ms(r["image"]) or 0))
        rep = members[0]["image"]
        for r in members:
            r["run_group"] = rep
            if r["image"] != rep:
                r["duplicate_of"] = rep


# ----------------------------------------------------------------------------- main

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--images", type=Path, nargs="+", required=True, help="image folders (to know each file's batch/folder)")
    ap.add_argument("--vocab", type=Path, default=HERE / "vocab.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    import hashlib
    parser = Parser(json.loads(args.vocab.read_text(encoding="utf-8")))
    cache = {}
    for f in args.cache.glob("*.json"):
        rec = json.loads(f.read_text(encoding="utf-8"))
        cache[rec["sha256"]] = rec
    results = []
    missing = 0
    for root in args.images:
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() not in EXTS or not p.is_file():
                continue
            rel = p.relative_to(root)
            if {"duplicates", "dedupe_review", "har_preview"} & set(rel.parts[:-1]):
                continue
            if args.only and p.name not in args.only:
                continue
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            rec = cache.get(sha)
            if rec is None:
                missing += 1
                continue
            r = parser.parse(rec)
            r["image"] = p.name
            r["batch"] = root.name
            r["folder"] = str(rel.parent) if str(rel.parent) != "." else ""
            r["posted"] = snowflake_ms(p.name)
            apply_final_realm(r)
            results.append(r)
    group_runs(results)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    # one row per unique usable run, for analysis (char sheet preferred over its finish map)
    with (args.out / "builds.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            if r["status"] != "usable" or r.get("duplicate_of"):
                continue
            fh.write(json.dumps({k: r.get(k) for k in (
                "image", "batch", "posted", "kind", "realm", "challenge", "outcome", "turns_taken", "spells",
                "equipment", "assumed_victory", "incomplete", "quality", "warnings", "run_group")}, ensure_ascii=False) + "\n")
    kinds = Counter(r["kind"] for r in results)
    unique_usable = [r for r in results if r["status"] == "usable" and not r.get("duplicate_of")]
    unmatched = Counter()
    for r in results:
        for w in r["warnings"]:
            if w.startswith("unmatched_"):
                unmatched[w] += 1
    with (args.out / "unmatched.tsv").open("w", encoding="utf-8") as fh:
        for w, n in unmatched.most_common():
            fh.write(f"{n}\t{w}\n")
    summary = {"images": len(results), "not_yet_ocrd": missing, "kinds": dict(kinds.most_common()),
               "usable": sum(r["status"] == "usable" for r in results), "usable_unique_runs": len(unique_usable),
               "by_batch": {b: dict(Counter(r["kind"] for r in results if r["batch"] == b)) for b in sorted({r["batch"] for r in results})}}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
