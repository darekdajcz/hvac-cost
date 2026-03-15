from __future__ import annotations

from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import hypot
from typing import Optional, Dict, Any, List, Tuple
import re

import ezdxf
import ezdxf.tools.crypt
from ezdxf import recover


# ======================================================================================
# EZDXF workaround (ACIS/SAT non-ascii)
# ======================================================================================

def _patched_decode(text_lines):
    def _safe_decode_line(text):
        try:
            b = bytes(text, "ascii")
        except UnicodeEncodeError:
            b = bytes(text, "latin-1", errors="replace")

        dectab = ezdxf.tools.crypt._decode_table
        s = []
        skip = False
        for c in b:
            if skip:
                skip = False
                continue
            if c in dectab:
                s += dectab[c]
                skip = (c == 0x5E)
            else:
                s += chr(c ^ 0x5F)
        return "".join(s)
    return (_safe_decode_line(line) for line in text_lines)


ezdxf.tools.crypt.decode = _patched_decode


# ======================================================================================
# Common helpers
# ======================================================================================

def normalize_mtext(s: str) -> str:
    s = re.sub(r"\\[A-Za-z]+[^;]*;", " ", s)
    s = s.replace("\\P", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def extract_text_from_entity(e) -> str:
    if e.dxftype() == "TEXT":
        return e.dxf.text or ""
    if e.dxftype() == "MTEXT":
        return e.text or ""
    return ""


@dataclass(frozen=True)
class Pt:
    x: float
    y: float


def dist(a: Pt, b: Pt) -> float:
    return hypot(a.x - b.x, a.y - b.y)


def quant_center(p: Pt, tol: float) -> Tuple[int, int]:
    if tol <= 0:
        return (round(p.x), round(p.y))
    return (int(round(p.x / tol)), int(round(p.y / tol)))


def unique_radii(circles, tol: float) -> List[float]:
    rs = sorted(float(c.dxf.radius) for c in circles)
    uniq: List[float] = []
    for r in rs:
        if not uniq or abs(r - uniq[-1]) > tol:
            uniq.append(r)
    return uniq


# ======================================================================================
# ROI + Rule model
# ======================================================================================

@dataclass
class ROI:
    enabled: bool = False
    xmin: float = 0.0
    xmax: float = 0.0
    ymin: float = 0.0
    ymax: float = 0.0
    margin: float = 0.0

    def contains_xy(self, x: float, y: float) -> bool:
        if not self.enabled:
            return True
        xmin = self.xmin - self.margin
        xmax = self.xmax + self.margin
        ymin = self.ymin - self.margin
        ymax = self.ymax + self.margin
        return xmin <= x <= xmax and ymin <= y <= ymax

    def contains_pt(self, p: Pt) -> bool:
        return self.contains_xy(p.x, p.y)


@dataclass
class Rule:
    id: str
    name: str
    type: str  # "block_count" | "text_regex" | "sprinklers"
    enabled: bool = True
    roi: ROI = field(default_factory=ROI)
    params: Dict[str, Any] = field(default_factory=dict)


# ======================================================================================
# RuleEngine
# ======================================================================================

class RuleEngine:
    def __init__(self, rules: List[Rule]):
        self.rules = [r for r in rules if r.enabled]

    def run(self, doc) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for rule in self.rules:
            if rule.type == "block_count":
                out[rule.id] = self._run_block_count(doc, rule)
            elif rule.type == "text_regex":
                out[rule.id] = self._run_text_regex(doc, rule)
            elif rule.type == "sprinklers":
                out[rule.id] = self._run_sprinklers(doc, rule)
            else:
                out[rule.id] = {"error": "Unknown rule type: %s" % rule.type}
        return out

    # ---------------- block_count ----------------

    def _run_block_count(self, doc, rule: Rule) -> Dict[str, Any]:
        ms = doc.modelspace()
        block_name = (rule.params.get("block_name") or "").upper()
        layer = (rule.params.get("layer") or "").upper()

        if not block_name:
            return {"count": 0, "note": "block_name empty -> ignored"}

        cnt = 0
        for ins in ms.query("INSERT"):
            if (ins.dxf.name or "").upper() != block_name:
                continue

            if layer:
                l = (getattr(ins.dxf, "layer", "") or "").upper()
                if l != layer:
                    continue

            if rule.roi.enabled:
                ip = ins.dxf.insert
                if not rule.roi.contains_xy(float(ip.x), float(ip.y)):
                    continue

            cnt += 1

        return {
            "count": cnt,
            "block": block_name,
            "layer": layer or None,
            "roi": rule.roi.__dict__,
        }

    # ---------------- text_regex ----------------

    def _run_text_regex(self, doc, rule: Rule) -> Dict[str, Any]:
        ms = doc.modelspace()
        pattern = rule.params.get("pattern") or ""
        if not pattern:
            return {"count": 0, "note": "pattern empty -> ignored"}

        flags = re.IGNORECASE if rule.params.get("ignore_case", True) else 0
        rx = re.compile(pattern, flags)

        cnt_model = 0
        for t in ms.query("TEXT MTEXT"):
            raw_n = normalize_mtext(extract_text_from_entity(t))
            if rule.roi.enabled:
                ins = getattr(t.dxf, "insert", None)
                if ins is not None:
                    if not rule.roi.contains_xy(float(ins.x), float(ins.y)):
                        continue
            if rx.search(raw_n):
                cnt_model += 1

        cnt_blocks = 0
        if rule.params.get("scan_block_definitions", False):
            for blk in doc.blocks:
                # pomiń techniczne
                bn = (blk.name or "").upper()
                if bn.startswith("*MODEL_SPACE") or bn.startswith("*PAPER_SPACE"):
                    continue
                for t in blk.query("TEXT MTEXT"):
                    raw_n = normalize_mtext(extract_text_from_entity(t))
                    if rx.search(raw_n):
                        cnt_blocks += 1

        return {
            "count_total": cnt_model + cnt_blocks,
            "count_modelspace": cnt_model,
            "count_block_defs": cnt_blocks,
            "pattern": pattern,
            "roi": rule.roi.__dict__,
        }

    # ---------------- sprinklers ----------------

    def _run_sprinklers(self, doc, rule: Rule) -> Dict[str, Any]:
        ms = doc.modelspace()

        # params (co nie podasz -> default)
        tr_text = (rule.params.get("tr_text") or "TR").upper()
        ring_count_required = int(rule.params.get("ring_count", 4))
        radius_merge_tol = float(rule.params.get("radius_merge_tol", 0.5))
        center_merge_tol = float(rule.params.get("center_merge_tol", 5.0))
        tr_max_dist = float(rule.params.get("tr_max_dist", 500.0))
        pair_max_dist = float(rule.params.get("pair_max_dist", 2500.0))
        require_tr_for_existing_new = bool(rule.params.get("require_tr_for_existing_new", True))

        # ACI map
        aci_red = int(rule.params.get("aci_designed_red", 1))
        aci_green = int(rule.params.get("aci_new_green", 3))
        aci_blue = int(rule.params.get("aci_existing_blue", 5))

        # keywords layer-state (ALL layers, ale tylko jeśli podasz listy)
        kw_existing = [k.upper() for k in (rule.params.get("kw_existing") or [])]
        kw_new = [k.upper() for k in (rule.params.get("kw_new") or [])]
        kw_designed = [k.upper() for k in (rule.params.get("kw_designed") or [])]

        def layer_state(layer_upper: str) -> Optional[str]:
            lu = layer_upper.upper()
            if kw_existing and any(k in lu for k in kw_existing):
                return "existing"
            if kw_new and any(k in lu for k in kw_new):
                return "new"
            if kw_designed and any(k in lu for k in kw_designed):
                return "designed"
            return None

        def get_aci(entity) -> Optional[int]:
            c = getattr(entity.dxf, "color", None)
            if c is None:
                return None
            try:
                c = int(c)
            except Exception:
                return None
            if c == 256:  # BYLAYER
                layer_name = getattr(entity.dxf, "layer", "")
                try:
                    return int(doc.layers.get(layer_name).dxf.color)
                except Exception:
                    return None
            if c == 0:  # BYBLOCK
                return None
            return c

        def state_by_color(entity) -> Optional[str]:
            # ACI
            aci = get_aci(entity)
            if aci == aci_red:
                return "designed"
            if aci == aci_green:
                return "new"
            if aci == aci_blue:
                return "existing"

            # true_color fallback
            tc = getattr(entity.dxf, "true_color", None)
            if tc is None:
                return None
            try:
                tc = int(tc)
                r = (tc >> 16) & 0xFF
                g = (tc >> 8) & 0xFF
                b = tc & 0xFF
            except Exception:
                return None

            if r > 180 and g < 120 and b < 120:
                return "designed"
            if g > 180 and r < 120 and b < 120:
                return "new"
            if b > 180 and r < 120 and g < 120:
                return "existing"
            return None

        # TR points (ROI per rule)
        tr_pts: List[Pt] = []
        for t in ms.query("TEXT MTEXT"):
            raw = normalize_mtext(extract_text_from_entity(t)).upper().strip()
            if raw != tr_text:
                continue
            ins = getattr(t.dxf, "insert", None)
            if ins is None:
                continue
            p = Pt(float(ins.x), float(ins.y))
            if rule.roi.enabled and (not rule.roi.contains_pt(p)):
                continue
            tr_pts.append(p)

        # circle groups
        circle_groups = defaultdict(list)
        for c in ms.query("CIRCLE"):
            cp = Pt(float(c.dxf.center.x), float(c.dxf.center.y))
            k = quant_center(cp, center_merge_tol)
            circle_groups[k].append(c)

        group_center: Dict[Tuple[int, int], Pt] = {}
        for k, circles in circle_groups.items():
            cc = circles[0].dxf.center
            group_center[k] = Pt(float(cc.x), float(cc.y))

        sprinklers: List[Tuple[Pt, str]] = []  # (center, state)

        for k, circles in circle_groups.items():
            center = group_center[k]

            # ROI per rule (ważne)
            if rule.roi.enabled and (not rule.roi.contains_pt(center)):
                continue

            # rings
            rc = len(unique_radii(circles, radius_merge_tol))
            if rc != ring_count_required:
                continue

            # state by color (vote)
            votes_c = Counter()
            for c in circles:
                s = state_by_color(c)
                if s:
                    votes_c[s] += 1
            st_color = votes_c.most_common(1)[0][0] if votes_c else None

            # red designed: bez TR
            if st_color == "designed":
                sprinklers.append((center, "designed"))
                continue

            # layer voting (tylko jeśli masz keywordy)
            votes_l = Counter()
            if kw_existing or kw_new or kw_designed:
                for c in circles:
                    layer = (getattr(c.dxf, "layer", "") or "").upper()
                    s = layer_state(layer)
                    if s:
                        votes_l[s] += 1
            st_layer = votes_l.most_common(1)[0][0] if votes_l else None

            state = st_layer or st_color
            if not state:
                continue

            # existing/new: wymagaj TR (jeśli włączone)
            if require_tr_for_existing_new and state in ("existing", "new"):
                ok = False
                for tp in tr_pts:
                    if dist(center, tp) <= tr_max_dist:
                        ok = True
                        break
                if not ok:
                    continue

            sprinklers.append((center, state))

        existing = [p for p, s in sprinklers if s == "existing"]
        designed = [p for p, s in sprinklers if s == "designed"]
        new = [p for p, s in sprinklers if s == "new"]

        # relocations: greedy nearest neighbour existing->designed
        used_des = set()
        reloc = 0
        for ex in existing:
            best_j = None
            best_d = 1e18
            for j, de in enumerate(designed):
                if j in used_des:
                    continue
                d = dist(ex, de)
                if d < best_d:
                    best_d = d
                    best_j = j
            if best_j is not None and best_d <= pair_max_dist:
                used_des.add(best_j)
                reloc += 1

        return {
            "existing": len(existing),
            "designed": len(designed),
            "new": len(new),
            "relocations": reloc,
            "roi": rule.roi.__dict__,
        }


# ======================================================================================
# Project root finder
# ======================================================================================

def find_project_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p, *p.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Nie znalazłem root projektu (pyproject.toml).")


PROJECT_ROOT = find_project_root(Path(__file__))

ROI_COMMON = ROI(
    enabled=True,
    xmin=-825.1893,
    xmax=7059.0927,
    ymin=-5397.8793,
    ymax=-175.4045,
    margin=20.0,
)

RULES: List[Rule] = [
    Rule(
        id="sprinklers_roi",
        name="Tryskacze (ROI): 4 ringi + kolor + TR",
        type="sprinklers",
        roi=ROI_COMMON,
        params={
            "ring_count": 4,
            "tr_text": "TR",
            "require_tr_for_existing_new": True,
            "aci_existing_blue": 5,
            "aci_designed_red": 1,
            "aci_new_green": 3,
            "tr_max_dist": 500.0,
            "pair_max_dist": 2500.0,
            "kw_existing": ["ISTN"],
            "kw_new": ["NOW", "NEW"],
            "kw_designed": ["PRZENIES", "PROJ", "ZMIAN"],
        },
    ),
    Rule(
        id="fcu_text",
        name="FCU (global): regex w tekście + definicje bloków",
        type="text_regex",
        roi=ROI(enabled=False),
        params={
            "pattern": r"\bFCU\d*\s*/\s*\d+\b",
            "ignore_case": True,
            "scan_block_definitions": True,
        },
    ),
    Rule(
        id="diffuser_roi",
        name="Nawiewnik (ROI): blok A$C6755CF63 na IS_VA_POW_NAWIEWANE",
        type="block_count",
        roi=ROI_COMMON,
        params={
            "block_name": "A$C6755CF63",
            "layer": "IS_VA_POW_NAWIEWANE",
        },
    ),
]


# ======================================================================================
# Main
# ======================================================================================

def main():
    root = PROJECT_ROOT / "data" / "raw" / "projekt2"
    dxf_files = sorted(root.rglob("*.dxf"))

    if not dxf_files:
        print("Brak DXF w:", root.resolve())
        return

    engine = RuleEngine(RULES)

    for f in dxf_files:
        print("\n" + "=" * 100)
        print("DXF:", f)

        try:
            doc, _auditor = recover.readfile(f)
        except UnicodeEncodeError:
            doc, _auditor = recover.readfile(f, errors="ignore")

        result = engine.run(doc)

        print("\n=== RULES RESULT ===")
        for rid, payload in result.items():
            rule_name = next((r.name for r in RULES if r.id == rid), rid)
            print(f"\n[{rid}] {rule_name}")
            for k, v in payload.items():
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
