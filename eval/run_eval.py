"""Eval harness: macro-F1 per record type + null baseline. SPEC.md section 5.

Scoring is real; wire run_pipeline / run_baseline to your extractor when gold exists:
    python -m eval.run_eval
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import GOLD_DIR                                 # noqa: E402
from extraction.schema import ExtractedRecord, _entity_id   # noqa: E402


def _n(s):
    return (s or "").strip().lower()


def _gold_key(rec: dict) -> tuple:
    """Mirror ExtractedRecord.key() exactly (operates on a gold dict)."""
    n = rec.get("normalized", {})
    et = rec["entity_type"]
    if et == "entity":
        return (et, n.get("type") or "", _entity_id(n, rec["value"]))
    if et == "relation":
        return (et, _n(n.get("subject")), _n(n.get("relation")), _n(n.get("object")))
    if et == "claim":
        return (et, _n(n.get("subject")), _n(n.get("predicate")), _n(n.get("object")), n.get("polarity"))
    if et == "method":
        return (et, _n(n.get("name")), _n((n.get("params") or {}).get("functional")))
    return (et, _n(n.get("metric") or rec["value"]), rec.get("unit"))   # measurement


def score(pred: list, gold: list) -> dict:
    """Per-type tp/fp/fn -> precision/recall/F1, plus macro-F1."""
    by_type = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    gold_keys = defaultdict(set)
    for g in gold:
        gold_keys[g["entity_type"]].add(_gold_key(g))
    seen = defaultdict(set)
    for p in pred:
        et = p.entity_type.value
        k = p.key()
        if k in gold_keys[et] and k not in seen[et]:
            by_type[et]["tp"] += 1
            seen[et].add(k)
        else:
            by_type[et]["fp"] += 1
    for et, keys in gold_keys.items():
        by_type[et]["fn"] += len(keys - seen[et])
    out, f1s = {}, []
    for et, c in by_type.items():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        out[et] = {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3), **c}
        f1s.append(f1)
    out["macro_f1"] = round(sum(f1s) / len(f1s), 3) if f1s else 0.0
    return out


def load_gold() -> dict:
    g = {}
    for f in sorted(Path(GOLD_DIR).glob("*.json")):
        if f.name.startswith("_"):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        g[d["paper_id"]] = d.get("records", [])
    return g


if __name__ == "__main__":
    gold = load_gold()
    print(f"gold papers: {len(gold)}")
    # TODO: per paper -> run_pipeline(text) and run_baseline(text); score both; aggregate;
    #       print macro-F1(verified) vs macro-F1(baseline) and dF1.
