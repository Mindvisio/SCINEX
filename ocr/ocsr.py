"""Optical Chemical Structure Recognition (OCSR): figure image -> SMILES.

A structure crop is read by one or more engines (MolScribe / DECIMER / vision); each SMILES is
canonicalized by RDKit (the deterministic arbiter) and reconciled by InChIKey:
  - both engines agree (same InChIKey, RDKit-valid) -> status "ok"       (high confidence)
  - only one valid / single-engine mode             -> status "review"   (single-engine is unsafe:
        emits valid-but-WRONG SMILES on cages/fused rings -- empirically, morphinans)
  - both valid but disagree                         -> status "disagree" (alternatives kept)
  - neither valid                                   -> status "failed"

TTA rescue: structures that come back non-'ok' are retried under test-time augmentation (upscale +
90/270 rotation -- 180 omitted, empirically worst), with a majority InChIKey vote across variants.
This recovers fused polycyclics that fail upright (e.g. naltrindole: rot90/rot270 agree where the
upright crop yields garbage). Only the hard subset pays the extra cost.

DECIMER lives in a TensorFlow venv (.venv-decimer); we shell out to ocr/decimer_worker.py so TF
never enters the runtime venv. MolScribe likewise in .venv-molscribe via ocr/molscribe_worker.py.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Optional

_DEF_DECIMER = "/root/scinex/.venv-decimer/bin/python"
DECIMER_PY = os.environ.get("DECIMER_PYTHON") or (_DEF_DECIMER if os.path.exists(_DEF_DECIMER) else sys.executable)
_DEF_MOLSCRIBE = "/root/scinex/.venv-molscribe/bin/python"
MOLSCRIBE_PY = os.environ.get("MOLSCRIBE_PYTHON") or (_DEF_MOLSCRIBE if os.path.exists(_DEF_MOLSCRIBE) else sys.executable)
VISION_MODEL = "claude-opus"            # vision OCSR reader; "gemini-pro" is an alternate
_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decimer_worker.py")
_MS_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "molscribe_worker.py")


@dataclass
class Mol:
    smiles: str                         # RDKit-canonical when valid, else best raw
    inchikey: Optional[str] = None
    confidence: Optional[float] = None
    status: str = "unknown"             # ok | review | disagree | failed
    backend: str = ""
    bbox: Optional[tuple] = None        # (x0,y0,x1,y1) in source figure, if available
    alternatives: list = field(default_factory=list)   # other valid SMILES on disagreement


@dataclass
class Reaction:
    reactants: list = field(default_factory=list)
    products: list = field(default_factory=list)
    conditions: dict = field(default_factory=dict)
    backend: str = ""


# ---- RDKit arbiter -------------------------------------------------------------
def _canon(smiles):
    if not smiles:
        return None
    try:
        from rdkit import Chem
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
    except Exception:
        return None
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    return Chem.MolToSmiles(m), Chem.MolToInchiKey(m)


def _first_smiles(text):
    """First RDKit-parseable token in free text (vision may add stray words)."""
    if not text:
        return None
    try:
        from rdkit import Chem
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
    except Exception:
        return text.strip().split()[0] if text.strip() else None
    for c in [text.strip()] + text.replace("`", " ").replace("\n", " ").split():
        c = c.strip().strip("`").strip()
        if c and Chem.MolFromSmiles(c) is not None:
            return c
    return None


# ---- engines -------------------------------------------------------------------
def _vision_smiles(image_path, model=VISION_MODEL):
    from lib.llm_clients import call_vision, LLMError
    prompt = ("This image shows ONE chemical structure. Reply with ONLY its SMILES string "
              "- no words, no markdown.")
    try:
        r = call_vision(model, prompt, [image_path], max_tokens=400,
                        temperature=0, reasoning_effort="low")
        return _first_smiles(r.text)
    except LLMError:
        return None


def _decimer_smiles(paths, timeout=300):
    """Batch DECIMER via subprocess to the TF venv. Returns {path: smiles|None}.
    Batching amortizes the one-time model load; single-image callers pay one load."""
    paths = list(paths)
    if not paths:
        return {}
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        subprocess.run([DECIMER_PY, _WORKER, json.dumps(paths), out],
                       capture_output=True, text=True, timeout=timeout, check=False)
        with open(out) as f:
            return json.load(f)
    except Exception:
        return {p: None for p in paths}
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


def _molscribe_smiles(paths, timeout=600):
    """Batch MolScribe via subprocess to its torch venv -> {path: smiles|None}. MolScribe (Qian
    et al., 2023) is a strong no-LLM OCSR model; RDKit stays the downstream arbiter."""
    paths = list(paths)
    if not paths:
        return {}
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        subprocess.run([MOLSCRIBE_PY, _MS_WORKER, json.dumps(paths), out],
                       capture_output=True, text=True, timeout=timeout, check=False)
        with open(out) as f:
            return json.load(f)
    except Exception:
        return {p: None for p in paths}
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


# ---- RDKit reconciliation ------------------------------------------------------
def _reconcile(raw: dict, engines) -> Mol:
    """raw = {engine: smiles|None} -> Mol. Canonicalize each via RDKit, reconcile by InChIKey.
    Single valid engine -> 'review' (single-engine is unsafe: valid-but-wrong on cages)."""
    cands = {e: _canon(raw.get(e)) for e in engines}
    valid = {e: c for e, c in cands.items() if c}
    if not valid:
        best = next((raw[e] for e in engines if raw.get(e)), "") or ""
        return Mol(smiles=best, status="failed", confidence=0.0, backend="+".join(engines))
    by_key = {}
    for e, (c, ik) in valid.items():
        by_key.setdefault(ik, []).append((e, c))
    if len(by_key) == 1:
        ik = next(iter(by_key))
        engs = [e for e, _ in by_key[ik]]
        agreed = len(engs) >= 2
        return Mol(smiles=by_key[ik][0][1], inchikey=ik,
                   confidence=0.95 if agreed else 0.6,
                   status="ok" if agreed else "review", backend="+".join(engs))
    order = [e for e in ("molscribe", "vision", "decimer") if e in valid]
    primary = order[0]
    p_can, p_ik = valid[primary]
    alts = [valid[e][0] for e in order if e != primary and valid[e][1] != p_ik]
    return Mol(smiles=p_can, inchikey=p_ik, confidence=0.3, status="disagree",
               backend=primary, alternatives=alts)


# ---- test-time augmentation (TTA) rescue for hard / fused structures -----------
_STATUS_RANK = {"failed": 0, "unknown": 0, "disagree": 1, "review": 2, "ok": 3}


def _tta_variants(path, workdir):
    """orig + 2x-upscale + rot90 + rot270 (rot180 omitted: empirically worst). PIL only.
    -> list of variant image paths (orig first). Best-effort; on any error returns [path]."""
    try:
        from PIL import Image
    except Exception:
        return [path]
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return [path]
    base = os.path.splitext(os.path.basename(path))[0]
    w, h = im.size
    out = [path]
    specs = {
        "up2": lambda: im.resize((w * 2, h * 2), Image.LANCZOS),
        "rot90": lambda: im.rotate(90, expand=True, fillcolor=(255, 255, 255)),
        "rot270": lambda: im.rotate(270, expand=True, fillcolor=(255, 255, 255)),
    }
    for tag, fn in specs.items():
        vp = os.path.join(workdir, "%s__%s.png" % (base, tag))
        try:
            fn().save(vp)
            out.append(vp)
        except Exception:
            pass
    return out


def _vote(smiles_list):
    """Majority InChIKey vote over a structure's TTA-variant SMILES.
    -> (canonical_smiles, inchikey, confidence) or None. confidence = winners / n_variants."""
    n = len(smiles_list)
    tally = {}
    for s in smiles_list:
        c = _canon(s)
        if not c:
            continue
        can, ik = c
        slot = tally.setdefault(ik, [0, can])
        slot[0] += 1
    if not tally:
        return None
    ik, (cnt, can) = max(tally.items(), key=lambda kv: kv[1][0])
    return can, ik, round(cnt / max(n, 1), 2)


def _engine_vote(var_map, engine_fn):
    """var_map = {img: [variant_paths]}; engine_fn(list)->{path:smiles}. One batched engine call.
    -> {img: (smiles, ik, conf)} for images that produced a valid vote."""
    all_paths = [v for vs in var_map.values() for v in vs]
    if not all_paths:
        return {}
    res = engine_fn(all_paths)
    out = {}
    for img, vs in var_map.items():
        voted = _vote([res.get(v) for v in vs])
        if voted:
            out[img] = voted
    return out


# ---- public: structure -> SMILES (consensus, RDKit-arbitrated, TTA-rescued) ----
def images_to_smiles(image_paths, *, engines=("vision", "decimer"),
                     vision_model: str = VISION_MODEL, tta: bool = True,
                     tta_workdir: Optional[str] = None) -> dict:
    """BATCH OCSR: list of crops -> {path: Mol}. Each model runs ONCE over all paths (one load,
    ~50s amortized). Non-'ok' crops are then retried under TTA (upscale + 90/270 rotation) with a
    majority InChIKey vote; a rescue replaces the result only if it raises the status rank, tagged
    '+tta' with the vote fraction as confidence. Set tta=False to disable."""
    paths = list(image_paths)
    if not paths:
        return {}
    dec = _decimer_smiles(paths) if "decimer" in engines else {}      # one model load
    ms = _molscribe_smiles(paths) if "molscribe" in engines else {}   # one model load
    out = {}
    for p in paths:
        raw = {}
        if "vision" in engines:
            raw["vision"] = _vision_smiles(p, vision_model)
        if "decimer" in engines:
            raw["decimer"] = dec.get(p)
        if "molscribe" in engines:
            raw["molscribe"] = ms.get(p)
        out[p] = _reconcile(raw, engines)
    # ---- TTA fallback on the hard subset only (image-file engines: molscribe/decimer) ----
    tta_engines = [e for e in engines if e in ("molscribe", "decimer")]
    hard = [p for p in paths if out[p].status != "ok"] if (tta and tta_engines) else []
    if hard:
        wd = tta_workdir or tempfile.mkdtemp(prefix="ocsr_tta_")
        os.makedirs(wd, exist_ok=True)
        var_map = {p: _tta_variants(p, wd) for p in hard}
        votes = {}
        if "molscribe" in tta_engines:
            votes["molscribe"] = _engine_vote(var_map, _molscribe_smiles)
        if "decimer" in tta_engines:
            votes["decimer"] = _engine_vote(var_map, _decimer_smiles)
        for p in hard:
            voted = {e: votes[e][p] for e in votes if p in votes.get(e, {})}
            if not voted:
                continue
            m = _reconcile({e: voted[e][0] for e in voted}, list(voted))
            if m.status != "failed" and _STATUS_RANK[m.status] > _STATUS_RANK[out[p].status]:
                m.backend = (m.backend + "+tta").strip("+")
                m.confidence = max(v[2] for v in voted.values())
                out[p] = m
        if tta_workdir is None:                      # clean only the variants we generated
            for p, vs in var_map.items():
                for v in vs[1:]:
                    try:
                        os.unlink(v)
                    except OSError:
                        pass
            try:
                os.rmdir(wd)
            except OSError:
                pass
    return out


def image_to_smiles(image_path: str, *, engines=("vision", "decimer"),
                    vision_model: str = VISION_MODEL, tta: bool = True, backend=None) -> Mol:
    """Single crop -> Mol. Thin wrapper over images_to_smiles; for many crops prefer the batch form
    to amortize the model load. `backend` ignored (back-compat)."""
    m = images_to_smiles([image_path], engines=engines, vision_model=vision_model,
                         tta=tta).get(image_path)
    return m or Mol(smiles="", status="failed", confidence=0.0, backend="+".join(engines))


def extract_reactions(image_path: str, backend: str = "rxnscribe") -> list:
    """reaction-scheme image -> list[Reaction]. Now provided by OpenChemIE (RxnScribe); see
    the OpenChemIE integration rather than this stub."""
    raise NotImplementedError("reaction extraction moved to the OpenChemIE path")