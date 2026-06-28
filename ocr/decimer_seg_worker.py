"""DECIMER-Segmentation worker. Runs INSIDE .venv-decimerseg (TensorFlow + Mask R-CNN). Reads a
JSON list of rasterised page PNGs, detects molecule depictions on each, saves an expanded crop per
structure, and returns bounding boxes (y0,x0,y1,x1 in page-image pixels) + crop paths.

Invoked via subprocess from hw_chemdb/extract_schemes.py so TF never enters the runtime venv.
Usage: python decimer_seg_worker.py <in.json> <out.json>
  in.json  = {"pages": [{"png": "/path/pageN.png", "tag": "stem_pN"}], "crop_dir": "/path"}
  out.json = {"stem_pN": [{"bbox": [y0,x0,y1,x1], "crop": "/path/stem_pN_s0.png"}], ...}
"""
import json
import os
import sys


def main():
    cfg = json.load(open(sys.argv[1]))
    out_path = sys.argv[2]
    crop_dir = cfg["crop_dir"]
    os.makedirs(crop_dir, exist_ok=True)
    result = {}
    try:
        import cv2
        from decimer_segmentation import segment_chemical_structures
    except Exception as e:                               # worker must not crash the caller
        sys.stderr.write("decimer_seg import failed: %s\n" % e)
        json.dump(result, open(out_path, "w"))
        return
    for page in cfg.get("pages", []):
        png, tag = page.get("png"), page.get("tag")
        img = cv2.imread(png) if png else None
        if img is None:
            result[tag] = []
            continue
        try:
            segs, bboxes = segment_chemical_structures(img, expand=True, return_bboxes=True)
        except Exception as e:
            sys.stderr.write("segment %s: %s\n" % (tag, e))
            result[tag] = []
            continue
        items = []
        for i, (seg, bbox) in enumerate(zip(segs, bboxes)):
            crop = os.path.join(crop_dir, "%s_s%d.png" % (tag, i))
            try:
                cv2.imwrite(crop, seg)
            except Exception:
                continue
            items.append({"bbox": [int(v) for v in bbox], "crop": crop})
        result[tag] = items
    json.dump(result, open(out_path, "w"))


if __name__ == "__main__":
    main()