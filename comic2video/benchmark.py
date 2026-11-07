from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from comic2video.storage import canonical, digest, read_json, write_json
import cv2
import hashlib
import numpy as np


def benchmark_inputs(root):
    pages = read_json(root / "artifacts" / "ingestion.json")["pages"]
    inputs = [{"input_id": page["page_id"], "source_file": page["source_file"], "image_path": page["source_snapshot"], "source_sha256": page["source_sha256"], "kind": "real"} for page in pages]
    fixtures = root / "artifacts" / "benchmark_fixtures" / "manifest.json"
    if fixtures.exists():
        inputs.extend(read_json(fixtures)["inputs"])
    return inputs


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def result_folder(root, model, revision, settings):
    signature = digest(canonical({"model": model, "revision": revision, "settings": settings}))[:16]
    return root / "artifacts" / "model_benchmark" / model.split("/")[-1] / signature


def save_result(folder, item, detections, masks, native_geometry, elapsed, raw, provenance):
    folder = folder / item["input_id"]
    folder.mkdir(parents=True, exist_ok=True)
    with Image.open(item["image_path"]) as source:
        image = source.convert("RGB")
    overlay = image.convert("RGBA")
    drawing = ImageDraw.Draw(overlay)
    tint = np.zeros((image.height, image.width, 4), dtype=np.uint8)
    panels = []
    for index, detection in enumerate(detections):
        detection_mask_path = folder / f"detection_{index:03d}_{detection['label']}.png"
        Image.fromarray(masks[index]).save(detection_mask_path)
        detection["mask_path"] = str(detection_mask_path)
        if detection["label"] != "frame":
            continue
        key = f"p{len(panels) + 1:03d}"
        mask = masks[index]
        path = folder / (key + "_mask.png")
        Image.fromarray(mask).save(path)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        polygons = [cv2.approxPolyDP(c, 1, True).reshape(-1, 2).tolist() for c in contours if cv2.contourArea(c) > 0]
        color = (35, 150, 220)
        tint[mask > 0] = (*color, 35)
        for polygon in polygons:
            points = [tuple(p) for p in polygon]
            drawing.line(points + points[:1], fill=(*color, 255), width=4)
        box = detection["bbox"]
        drawing.text((max(0, box[0] + 5), max(0, box[1] + 5)), key, fill="red", stroke_width=1)
        rgba = np.array(image.convert("RGBA"))
        rgba[:, :, 3] = mask
        positions = np.argwhere(mask > 0)
        if len(positions):
            y0, x0 = positions.min(axis=0)
            y1, x1 = positions.max(axis=0) + 1
            Image.fromarray(rgba).crop((int(x0), int(y0), int(x1), int(y1))).save(folder / (key + "_isolated.png"))
        panels.append(dict(detection, key=key, native_geometry=native_geometry, polygons=polygons, mask_path=str(path)))
    Image.alpha_composite(overlay, Image.fromarray(tint)).convert("RGB").save(folder / "overlay.jpg")
    result = {"schema_version": "1.0", "input": item, "native_geometry": native_geometry, "inference_seconds": elapsed, "detections": detections, "panels": panels, "raw_output": raw, "provenance": provenance, "ownership_associations": "not inferred from structural masks"}
    write_json(folder / "result.json", result)
    return result


def rectangle_mask(box, width, height):
    x0, y0, x1, y1 = box
    mask = np.zeros((height, width), dtype=np.uint8)
    left, top = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
    right, bottom = min(width, int(np.ceil(x1))), min(height, int(np.ceil(y1)))
    mask[top:bottom, left:right] = 255
    return mask
