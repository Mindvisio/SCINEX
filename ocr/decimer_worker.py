"""DECIMER subprocess worker -- run ONLY via .venv-decimer python (TensorFlow env).
argv: [json_paths, out_json]. Loads DECIMER once, predicts SMILES for each image, writes
{path: smiles|null} to out_json. Keeps TF out of the runtime venv (called by ocr/ocsr.py).
"""
import sys, os, json
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")


def main():
    paths = json.loads(sys.argv[1]); out = sys.argv[2]; res = {}
    try:
        from DECIMER import predict_SMILES
    except Exception:
        json.dump({p: None for p in paths}, open(out, "w")); return
    for p in paths:
        try:
            s = predict_SMILES(p)
            if isinstance(s, (list, tuple)): s = s[0]
            res[p] = s
        except Exception:
            res[p] = None
    json.dump(res, open(out, "w"))


if __name__ == "__main__":
    main()
