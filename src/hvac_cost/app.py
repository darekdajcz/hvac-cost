from __future__ import annotations

import json
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ezdxf import recover

from rules.parser import parse_rules
from engine.rule_engine import RuleEngine
from helpers.ezdxf_patch import apply_ezdxf_patch

apply_ezdxf_patch()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/scan")
async def scan(file: UploadFile = File(...), rules_json: str = Form(...)):
    if not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="Only .dxf supported")

    try:
        rules_raw = json.loads(rules_json)
        rules = parse_rules(rules_raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid rules_json: {e}")

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

    return {
        "file": file.filename,
        "result": result,
    }