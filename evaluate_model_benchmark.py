from pathlib import Path
from PIL import Image
from comic2video.benchmark import rectangle_mask
from comic2video.contracts import PanelGeometry
from comic2video.evaluation import mask_iou, match_masks
from comic2video.geometry import polygon_mask, reading_order
from comic2video.storage import read_json, write_json
import json
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent
MODEL_NAMES = ["koharu-yolo26s", "magiv3"]
IOU_THRESHOLDS = [0.5, 0.75, 0.9]


def summarize(rows):
    reference_count = sum(row["reference_count"] for row in rows)
    predicted_count = sum(row["predicted_count"] for row in rows)
    result = {"page_count": len(rows), "reference_panels": reference_count, "predicted_panels": predicted_count}
    for threshold in IOU_THRESHOLDS:
        name = str(threshold)
        for field, label in [("matches_at_iou", "detection"), ("box_matches_at_iou", "box_detection")]:
            matched = sum(row[field][name] for row in rows)
            precision = matched / predicted_count if predicted_count else 0
            recall = matched / reference_count if reference_count else 0
            result[f"{label}_at_iou_{threshold}"] = {"matched": matched, "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0}
    scores = [score for row in rows for score in row["matched_region_ious"]]
    result["mean_region_iou_of_matches_at_0_5"] = float(np.mean(scores)) if scores else None
    result["pages_with_exact_detection_at_0_5"] = sum(row["matches_at_iou"]["0.5"] == row["reference_count"] == row["predicted_count"] for row in rows)
    result["ownership_probes_passed"] = sum(probe["passed"] for row in rows for probe in row["ownership_probes"])
    result["ownership_probes_total"] = sum(len(row["ownership_probes"]) for row in rows)
    return result


def evaluate_page(reference, prediction):
    with Image.open(prediction["input"]["image_path"]) as image:
        width, height = image.size
    references = [polygon_mask([p["polygon"]], width, height) for p in reference["panels"]]
    predictions = [np.array(Image.open(p["mask_path"])) for p in prediction["panels"]]
    reference_boxes = [rectangle_mask([min(p[0] for p in r["polygon"]), min(p[1] for p in r["polygon"]), max(p[0] for p in r["polygon"]) + 1, max(p[1] for p in r["polygon"]) + 1], width, height) for r in reference["panels"]]
    predicted_boxes = [rectangle_mask(p["bbox"], width, height) for p in prediction["panels"]]
    matches = match_masks(references, predictions, 0.5)
    mapping = {reference["panels"][r]["key"]: p for r, p, _ in matches}
    probes = []
    for probe in reference["ownership_probes"]:
        index = mapping.get(probe["panel_key"])
        x, y = probe["point"]
        observed = bool(predictions[index][y, x]) if index is not None else None
        probes.append(dict(probe, observed_owned=observed, passed=observed == probe["owned"]))
    order = None
    if reference.get("reading_order"):
        geometries = []
        for i, panel in enumerate(prediction["panels"]):
            x0, y0, x1, y1 = panel["bbox"]
            polygon = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            geometries.append(PanelGeometry(key=str(i), layout_polygon=polygon, content_polygons=[polygon]))
        positions = {int(key): i for i, key in enumerate(reading_order(geometries, "ltr"))}
        known = [key for key in reference["reading_order"] if key in mapping]
        pairs = [(a, b) for i, a in enumerate(known) for b in known[i + 1:]]
        order = {"method": "project geometric LTR sorter, not native model reasoning", "correct_pairs": sum(positions[mapping[a]] < positions[mapping[b]] for a, b in pairs), "evaluated_pairs": len(pairs), "all_references_detected": len(matches) == len(references)}
    return {"source_file": prediction["input"]["source_file"], "kind": prediction["input"]["kind"], "reference_count": len(references), "predicted_count": len(predictions), "native_geometry": prediction["native_geometry"], "matches_at_iou": {str(t): len(match_masks(references, predictions, t)) for t in IOU_THRESHOLDS}, "box_matches_at_iou": {str(t): len(match_masks(reference_boxes, predicted_boxes, t)) for t in IOU_THRESHOLDS}, "matched_region_ious": [score for _, _, score in matches], "ownership_probes": probes, "reading_order": order, "inference_seconds": prediction["inference_seconds"], "tags": reference["tags"]}


def main():
    labels = read_json(PROJECT_ROOT / "annotations" / "model_benchmark.json")
    references = {p["source_file"]: p for p in labels["pages"]}
    fixtures = read_json(PROJECT_ROOT / "artifacts" / "benchmark_fixtures" / "manifest.json")
    references.update({p["source_file"]: p["reference"] for p in fixtures["inputs"]})
    report = {"schema_version": "1.0", "reference_status": labels["status"], "limitations": labels["notes"], "iou_definition": "One-to-one matching of original-coordinate structural regions. Koharu uses native instance masks; Magi uses rasterized native boxes, not learned masks.", "models": {}}
    for name in MODEL_NAMES:
        runs = sorted((PROJECT_ROOT / "artifacts" / "model_benchmark" / name).glob("*/run.json"), key=lambda p: p.stat().st_mtime)
        if not runs:
            raise FileNotFoundError(f"No completed run for {name}")
        run = read_json(runs[-1])
        predictions = [read_json(item["result_path"]) for item in run["results"]]
        rows = [evaluate_page(references[p["input"]["source_file"]], p) for p in predictions if p["input"]["source_file"] in references]
        real_predictions = [p for p in predictions if p["input"]["kind"] == "real"]
        counts = [{"source_file": p["input"]["source_file"], "expected": labels["expected_counts"][p["input"]["source_file"]], "predicted": len(p["panels"])} for p in real_predictions]
        timing = [p["inference_seconds"] for p in real_predictions]
        report["models"][name] = {"run_manifest": str(runs[-1]), "provenance": run["provenance"], "real_annotated": summarize([r for r in rows if r["kind"] == "real"]), "synthetic_controls": summarize([r for r in rows if r["kind"] != "real"]), "all_real_page_counts": {"exact_count_pages": sum(p["expected"] == p["predicted"] for p in counts), "page_count": len(counts), "expected_total": sum(p["expected"] for p in counts), "predicted_total": sum(p["predicted"] for p in counts), "pages": counts}, "timing": {"median_seconds_all_real_pages": float(np.median(timing)), "median_seconds_excluding_first_page": float(np.median(timing[1:])), "excludes_model_loading_artifact_writes": True}, "pages": rows}
    write_json(PROJECT_ROOT / "artifacts" / "model_benchmark" / "comparison.json", report)
    print(json.dumps({name: {"real_annotated": data["real_annotated"], "synthetic_controls": data["synthetic_controls"], "exact_count_pages": data["all_real_page_counts"]["exact_count_pages"], "timing": data["timing"]} for name, data in report["models"].items()}, indent=2))


if __name__ == "__main__":
    main()
