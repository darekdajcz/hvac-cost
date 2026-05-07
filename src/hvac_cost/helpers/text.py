from __future__ import annotations

import re

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
