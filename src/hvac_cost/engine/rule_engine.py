from rules.models import Rule
from helpers.ezdxf_patch import apply_ezdxf_patch
from ezdxf import colors as ezdxf_colors
apply_ezdxf_patch()

import re
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional, Tuple

from helpers.colors import detect_basic_color
from helpers.geometry import (
    Pt,
    quant_center,
    unique_radii,
    classify_polygon_shape,
    polygon_center,
    dist,
)
from helpers.text import normalize_mtext, extract_text_from_entity


class RuleEngine:
    def __init__(self, rules: List[Rule]):
        self.rules = [r for r in rules if r.enabled]

    def run(self, doc) -> Dict[str, Any]:
        print("Running rules... ==>")
        out: Dict[str, Any] = {}
        for rule in self.rules:
            if rule.type == "block_count":
                out[rule.id] = self._run_block_count(doc, rule)
            elif rule.type == "symbol_count":
                out[rule.id] = self._run_symbol_count(doc, rule)
            else:
                out[rule.id] = {"error": f"Unknown rule type: {rule.type}"}
        return out

    # ---------------- block_count ----------------

    def _run_block_count(self, doc, rule: Rule) -> Dict[str, Any]:
        ms = doc.modelspace()
        block_name = (rule.params.get("block_name") or "").upper()
        layer = (rule.params.get("layer") or "").upper()

        if not block_name:
            return {"name": rule.name, "count": 0, "note": "block_name empty -> ignored"}

        cnt = 0
        for ins in ms.query("INSERT"):
            if (ins.dxf.name or "").upper() != block_name:
                continue

            if layer:
                l = (getattr(ins.dxf, "layer", "") or "").upper()
                if l != layer:
                    continue

            ip = ins.dxf.insert
            if not rule.roi.contains_xy(float(ip.x), float(ip.y)):
                continue

            cnt += 1

        return {
            "name": rule.name,
            "count": cnt,
            "block": block_name,
            "layer": layer or None,
            "roi": rule.roi.__dict__,
        }

    # ---------------- symbol_count ----------------

    def _run_symbol_count(self, doc, rule: Rule) -> Dict[str, Any]:
        text_cfg = rule.params.get("text")
        shape = (rule.params.get("shape") or "").lower().strip()

        print("Running rule... ==>")
        print("RULE ==> ", rule)
        print("block_name ==> ", shape)
        print("block_name ==> ", text_cfg)

        if isinstance(text_cfg, dict) and text_cfg.get("pattern"):
            return self._run_text_regex(doc, rule, text_cfg)

        if shape:
            return self._run_symbol_shape_count(doc, rule)

        return {
            "name": rule.name,
            "count_total": 0,
            "note": "No matcher configured. Use params.text or params.shape."
        }

    # ---------------- text regex ----------------

    def _run_text_regex(self, doc, rule: Rule, text_cfg: Dict[str, Any]) -> Dict[str, Any]:
        ms = doc.modelspace()
        pattern = text_cfg.get("pattern") or ""
        if not pattern:
            return {"name": rule.name, "count_total": 0, "note": "pattern empty -> ignored"}

        flags = re.IGNORECASE if text_cfg.get("ignore_case", True) else 0
        rx = re.compile(pattern, flags)

        cnt_model = 0
        for t in ms.query("TEXT MTEXT"):
            raw_n = normalize_mtext(extract_text_from_entity(t))
            ins = getattr(t.dxf, "insert", None)
            if ins is not None and not rule.roi.contains_xy(float(ins.x), float(ins.y)):
                continue
            if rx.search(raw_n):
                cnt_model += 1

        cnt_blocks = 0
        if text_cfg.get("scan_block_definitions", False):
            for blk in doc.blocks:
                bn = (blk.name or "").upper()
                if bn.startswith("*MODEL_SPACE") or bn.startswith("*PAPER_SPACE"):
                    continue
                for t in blk.query("TEXT MTEXT"):
                    raw_n = normalize_mtext(extract_text_from_entity(t))
                    if rx.search(raw_n):
                        cnt_blocks += 1

        return {
            "name": rule.name,
            "count_total": cnt_model + cnt_blocks,
            "count_modelspace": cnt_model,
            "count_block_defs": cnt_blocks,
            "pattern": pattern,
            "roi": rule.roi.__dict__,
        }

    # ---------------- symbol shape count ----------------

    def _run_symbol_shape_count(self, doc, rule: Rule) -> Dict[str, Any]:
        ms = doc.modelspace()

        shape = (rule.params.get("shape") or "").lower().strip()
        count_required = int(rule.params.get("count", 1))

        color_raw = rule.params.get("color")
        expected_color = str(color_raw).lower().strip() if color_raw is not None and str(color_raw).strip() else None

        tr_text_raw = rule.params.get("tr_text")
        tr_text = str(tr_text_raw).upper().strip() if tr_text_raw is not None and str(tr_text_raw).strip() else None

        tr_max_dist_raw = rule.params.get("tr_max_dist")
        tr_max_dist = float(tr_max_dist_raw) if tr_max_dist_raw is not None else None

        radius_merge_tol_raw = rule.params.get("radius_merge_tol")
        radius_merge_tol = float(radius_merge_tol_raw) if radius_merge_tol_raw is not None else 0.5

        center_merge_tol_raw = rule.params.get("center_merge_tol")
        center_merge_tol = float(center_merge_tol_raw) if center_merge_tol_raw is not None else 5.0

        print("Running _run_symbol_shape_count ==>")
        print("rule ==> ", rule)
        print("shape ==> ", shape)
        print("count_required ==> ", count_required)
        print("expected_color ==> ", expected_color)
        print("tr_text ==> ", tr_text)
        print("tr_max_dist ==> ", tr_max_dist)
        print("radius_merge_tol ==> ", radius_merge_tol)
        print("center_merge_tol ==> ", center_merge_tol)

        if shape != "circle":
            return {
                "name": rule.name,
                "error": f"Unsupported shape for current backend: {shape}. Currently supported: circle"
            }

        use_color_filter = expected_color is not None
        use_tr_filter = tr_text is not None

        print("use_color_filter ==> ", use_color_filter)
        print("use_tr_filter ==> ", use_tr_filter)

        tr_pts: List[Pt] = []
        if use_tr_filter:
            for t in ms.query("TEXT MTEXT"):
                raw = normalize_mtext(extract_text_from_entity(t)).upper().strip()
                if raw != tr_text:
                    continue

                ins = getattr(t.dxf, "insert", None)
                if ins is None:
                    continue

                p = Pt(float(ins.x), float(ins.y))
                if not rule.roi.contains_pt(p):
                    continue

                tr_pts.append(p)

        print("helper_points_count ==> ", len(tr_pts))

        circle_groups = defaultdict(list)
        all_circles = list(ms.query("CIRCLE"))
        print("all_modelspace_circles ==> ", len(all_circles))

        for c in all_circles:
            cp = Pt(float(c.dxf.center.x), float(c.dxf.center.y))
            if not rule.roi.contains_pt(cp):
                continue

            k = quant_center(cp, center_merge_tol)
            circle_groups[k].append(c)

        print("circle_groups_count ==> ", len(circle_groups))

        group_center: Dict[Tuple[int, int], Pt] = {}
        for k, circles in circle_groups.items():
            cc = circles[0].dxf.center
            group_center[k] = Pt(float(cc.x), float(cc.y))

        detected_before_color = 0
        detected_after_color = 0
        detected_after_tr = 0

        matches = []

        for k, circles in circle_groups.items():
            center = group_center[k]
            radii = unique_radii(circles, radius_merge_tol)
            ring_count = len(radii)

            print(
                f"[GROUP] center=({center.x:.2f}, {center.y:.2f}) "
                f"circle_count={len(circles)} "
                f"ring_count={ring_count} "
                f"radii={radii}"
            )

            if ring_count != count_required:
                continue

            detected_before_color += 1

            if use_color_filter:
                if not self._all_circles_match_color(doc, circles, expected_color):
                    continue

            detected_after_color += 1

            if use_tr_filter:
                max_dist = tr_max_dist if tr_max_dist is not None else 500.0

                ok = False
                min_found_dist = None

                for tp in tr_pts:
                    current_dist = dist(center, tp)
                    if min_found_dist is None or current_dist < min_found_dist:
                        min_found_dist = current_dist

                    if current_dist <= max_dist:
                        ok = True
                        break

                print(
                    f"[GROUP-TR] center=({center.x:.2f}, {center.y:.2f}) "
                    f"nearest_tr_dist={min_found_dist} "
                    f"max_dist={max_dist} "
                    f"ok={ok}"
                )

                if not ok:
                    continue

            detected_after_tr += 1

            matches.append({
                "center": {"x": center.x, "y": center.y},
                "color": expected_color if use_color_filter else None,
                "ring_count": ring_count,
                "circle_count_in_group": len(circles),
            })

        return {
            "name": rule.name,
            "count_total": len(matches),
            "shape": shape,
            "color": expected_color,
            "count": count_required,
            "tr_text": tr_text,
            "tr_max_dist": tr_max_dist,
            "debug": {
                "use_color_filter": use_color_filter,
                "use_tr_filter": use_tr_filter,
                "helper_points_count": len(tr_pts),
                "detected_before_color": detected_before_color,
                "detected_after_color": detected_after_color,
                "detected_after_tr": detected_after_tr,
            },
            "matches": matches,
            "roi": rule.roi.__dict__,
        }

    # ---------------- helpers ----------------

    def _all_circles_match_color(self, doc, circles, expected_color: str) -> bool:
        for c in circles:
            detected = self._detect_basic_color(doc, c)
            print(
                "[CIRCLE]",
                "handle=", getattr(c.dxf, "handle", ""),
                "layer=", getattr(c.dxf, "layer", ""),
                "entity_color=", getattr(c.dxf, "color", None),
                "true_color=", getattr(c.dxf, "true_color", None),
                "detected=", detected,
                "expected=", expected_color,
            )
            if detected != expected_color:
                return False
        return True

    def _detect_basic_color(self, doc, entity) -> Optional[str]:
        # 1. true_color ma pierwszeństwo
        tc = getattr(entity.dxf, "true_color", None)
        if tc is not None:
            try:
                tc = int(tc)
                r = (tc >> 16) & 0xFF
                g = (tc >> 8) & 0xFF
                b = tc & 0xFF
                return self._rgb_to_basic_color(r, g, b)
            except Exception:
                pass

        # 2. fallback na ACI
        aci = self._get_aci(doc, entity)
        if aci is None:
            return None

        try:
            rgb = ezdxf_colors.aci2rgb(abs(int(aci)))
            if isinstance(rgb, tuple):
                r, g, b = rgb
            else:
                r, g, b = rgb.r, rgb.g, rgb.b

            print(f"[ACI->RGB] aci={aci} rgb=({r},{g},{b})")
            return self._rgb_to_basic_color(r, g, b)
        except Exception as e:
            print(f"[ACI->RGB-ERROR] aci={aci} err={e}")
            return None

    def _rgb_to_basic_color(self, r: int, g: int, b: int) -> Optional[str]:
        if r > g and r > b:
            return "red"
        if g > r and g > b:
            return "green"
        if b > r and b > g:
            return "blue"
        return None

    def _get_aci(self, doc, entity) -> Optional[int]:
        c = getattr(entity.dxf, "color", None)
        layer_name = getattr(entity.dxf, "layer", "")

        if c is None:
            print("[ACI] no entity color", "layer=", layer_name)
            return None

        try:
            c = int(c)
        except Exception:
            print("[ACI] invalid entity color", c, "layer=", layer_name)
            return None

        if c == 256:  # BYLAYER
            try:
                layer = doc.layers.get(layer_name)
                layer_color_raw = int(layer.dxf.color)
                layer_color = abs(layer_color_raw)
                print(
                    "[ACI-BYLAYER]",
                    "handle=", getattr(entity.dxf, "handle", ""),
                    "layer=", layer_name,
                    "layer_color_raw=", layer_color_raw,
                    "layer_color_abs=", layer_color,
                )
                return layer_color
            except Exception as e:
                print(
                    "[ACI-BYLAYER-ERROR]",
                    "handle=", getattr(entity.dxf, "handle", ""),
                    "layer=", layer_name,
                    "err=", e,
                )
                return None

        if c == 0:
            print("[ACI-BYBLOCK]", "handle=", getattr(entity.dxf, "handle", ""), "layer=", layer_name)
            return None

        print(
            "[ACI-DIRECT]",
            "handle=", getattr(entity.dxf, "handle", ""),
            "layer=", layer_name,
            "entity_color=", c,
            "abs=", abs(c),
        )
        return abs(c)