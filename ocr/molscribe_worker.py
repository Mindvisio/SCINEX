"""MolScribe worker. Runs INSIDE .venv-molscribe (torch). Reads a JSON list of image paths,
emits {path: SMILES|None}. The checkpoint is fetched once from the HuggingFace Hub and cached.
Invoked via subprocess from ocr/ocsr.py so torch never enters the runtime venv.

Usage: python molscribe_worker.py '<json paths>' <out.json>
"""
import json
import os
import sys

_CKPT_REPO = "yujieq/MolScribe"
_CKPT_FILE = "swin_base_char_aux_1m.pth"


def _load_model():
    import torch
    from molscribe import MolScribe
    from huggingface_hub import hf_hub_download
    ckpt = hf_hub_download(_CKPT_REPO, _CKPT_FILE)
    return MolScribe(ckpt, device=torch.device("cpu"))


def main():
    paths = json.loads(sys.argv[1])
    outp = sys.argv[2]
    res = {}
    try:
        model = _load_model()
        for p in paths:
            try:
                out = model.predict_image_file(p)
                res[p] = out.get("smiles") if isinstance(out, dict) else None
            except Exception as e:
                sys.stderr.write("molscribe predict %s: %s\n" % (p, e))
                res[p] = None
    except Exception as e:
        sys.stderr.write("molscribe load: %s\n" % e)
        res = {p: None for p in paths}
    with open(outp, "w") as f:
        json.dump(res, f)


if __name__ == "__main__":
    main()