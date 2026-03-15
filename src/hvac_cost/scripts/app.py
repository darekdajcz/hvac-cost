from __future__ import annotations

import json
import tempfile
from typing import Any, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ezdxf import recover

from scan_dxf_overview import RuleEngine, Rule, ROI


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def py(rules_raw: Any) -> List[Rule]:
    if not isinstance(rules_raw, list):
        raise ValueError("rules_json must be a list")

    rules: List[Rule] = []
    for r in rules_raw:
        roi_raw = r.get("roi") or {}
        roi = ROI(
            enabled=bool(roi_raw.get("enabled", False)),
            xmin=float(roi_raw.get("xmin", 0.0)),
            xmax=float(roi_raw.get("xmax", 0.0)),
            ymin=float(roi_raw.get("ymin", 0.0)),
            ymax=float(roi_raw.get("ymax", 0.0)),
            margin=float(roi_raw.get("margin", 0.0)),
        )
        rules.append(
            Rule(
                id=str(r.get("id")),
                name=str(r.get("name", "")),
                type=str(r.get("type")),
                enabled=bool(r.get("enabled", True)),
                roi=roi,
                params=dict(r.get("params") or {}),
            )
        )
    return rules


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/scan")
async def scan(file: UploadFile = File(...), rules_json: str = Form(...)):
    if not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="Only .dxf supported")

    try:
        rules_raw = json.loads(rules_json)
        rules = _parse_rules(rules_raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid rules_json: {e}")

    # upload -> temp
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        try:
            doc, _aud = recover.readfile(tmp_path)
        except UnicodeEncodeError:
            doc, _aud = recover.readfile(tmp_path, errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DXF read failed: {e}")

    engine = RuleEngine(rules)
    result = engine.run(doc)
    return {"file": file.filename, "result": result}