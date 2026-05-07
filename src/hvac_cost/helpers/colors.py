from __future__ import annotations

from typing import Optional


def get_aci(doc, entity) -> Optional[int]:
    color = getattr(entity.dxf, "color", None)
    if color is None:
        return None

    try:
        color = int(color)
    except Exception:
        return None

    if color == 256:  # BYLAYER
        layer_name = getattr(entity.dxf, "layer", "")
        try:
            return int(doc.layers.get(layer_name).dxf.color)
        except Exception:
            return None

    if color == 0:  # BYBLOCK
        return None

    return color


def detect_basic_color(doc, entity) -> Optional[str]:
    aci = get_aci(doc, entity)

    if aci == 1:
        return "red"
    if aci == 3:
        return "green"
    if aci == 5:
        return "blue"

    true_color = getattr(entity.dxf, "true_color", None)
    if true_color is None:
        return None

    try:
        true_color = int(true_color)
        r = (true_color >> 16) & 0xFF
        g = (true_color >> 8) & 0xFF
        b = true_color & 0xFF
    except Exception:
        return None

    if r > 180 and g < 120 and b < 120:
        return "red"
    if g > 180 and r < 120 and b < 120:
        return "green"
    if b > 180 and r < 120 and g < 120:
        return "blue"

    return None