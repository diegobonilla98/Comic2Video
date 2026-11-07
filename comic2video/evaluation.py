from pathlib import Path
from PIL import Image
from comic2video.contracts import Extraction, Page
from comic2video.geometry import polygon_mask
from comic2video.storage import read_json, write_json
import numpy as np


def mask_iou(first, second):
    first, second = first > 0, second > 0
    union = np.count_nonzero(first | second)
    return np.count_nonzero(first & second) / union if union else 0.0


def match_masks(references, predictions, minimum_iou):
    scores = np.array([[mask_iou(a, b) for b in predictions] for a in references])
    owners = {}

    def visit(reference, seen):
        for prediction in sorted(range(len(predictions)), key=lambda p: -scores[reference, p]):
            if scores[reference, prediction] < minimum_iou or prediction in seen:
                continue
            seen.add(prediction)
            if prediction not in owners or visit(owners[prediction], seen):
                owners[prediction] = reference
                return True
        return False

    for reference in range(len(references)):
        visit(reference, set())
    return [(r, p, float(scores[r, p])) for p, r in owners.items()]


def evaluate(root, config, run_manifest_path=None, output_path=None):
    annotation = read_json(root / "annotations" / "development.json")
    ingestion = read_json(config.artifact_dir / "ingestion.json")
    run = read_json(run_manifest_path or config.artifact_dir / "run_manifest.json")
    pages = {p["source_file"]: Page.model_validate(p) for p in ingestion["pages"]}
    manifests = {p["source_file"]: p["extraction_manifest"] for p in run["pages"]}
    results = []
    for reference in annotation["pages"]:
        page = pages[reference["source_file"]]
        extraction = Extraction.model_validate(read_json(manifests[page.source_file]))
        masks = [polygon_mask([p["polygon"]], page.width, page.height) for p in reference["panels"]]
        predicted_masks = [np.array(Image.open(p.layout_mask)) for p in extraction.panels]
        matches = match_masks(masks, predicted_masks, 0.5)
        assignments = {reference["panels"][r]["key"]: extraction.panels[p] for r, p, _ in matches}
        predicted_order = {p.key: p.order_index for p in extraction.panels}
        known_order = [key for key in reference["reading_order"] if key in assignments]
        pairs = [(a, b) for i, a in enumerate(known_order) for b in known_order[i + 1:]]
        correct_pairs = sum(predicted_order[assignments[a].key] < predicted_order[assignments[b].key] for a, b in pairs)
        probes = []
        for probe in reference["ownership_probes"]:
            match = assignments.get(probe["panel_key"])
            x, y = probe["point"]
            observed = bool(np.array(Image.open(match.owned_content_mask))[y, x]) if match else None
            probes.append(dict(probe, observed_owned=observed, passed=observed == probe["owned"]))
        result = {"source_file": page.source_file, "reference_count": len(masks), "predicted_count": len(predicted_masks), "matched_count_at_iou_0_5": len(matches), "matched_mask_ious": [score for _, _, score in matches], "recall_at_iou_0_5": len(matches) / len(masks), "precision_at_iou_0_5": len(matches) / len(predicted_masks), "correct_order_pairs": correct_pairs, "evaluated_order_pairs": len(pairs), "all_panels_matched": len(matches) == len(masks), "ownership_probes": probes, "extraction_manifest": manifests[page.source_file]}
        results.append(result)
    reference_count = sum(p["reference_count"] for p in results)
    predicted_count = sum(p["predicted_count"] for p in results)
    matched = sum(p["matched_count_at_iou_0_5"] for p in results)
    order_pairs = sum(p["evaluated_order_pairs"] for p in results)
    probe_count = sum(len(p["ownership_probes"]) for p in results)
    report = {"schema_version": "1.0", "reference_status": annotation["status"], "limitations": annotation["notes"], "method": "Maximum-cardinality one-to-one matching at structural mask IoU >= 0.5; order accuracy only for matched panels", "summary": {"reference_panels": reference_count, "predicted_panels": predicted_count, "matched_panels": matched, "recall_at_iou_0_5": matched / reference_count, "precision_at_iou_0_5": matched / predicted_count, "matched_pair_order_accuracy": sum(p["correct_order_pairs"] for p in results) / order_pairs if order_pairs else None, "pages_with_all_references_matched": sum(p["all_panels_matched"] for p in results), "pages_with_exact_detection": sum(p["all_panels_matched"] and p["predicted_count"] == p["reference_count"] for p in results), "ownership_probes_passed": sum(probe["passed"] for p in results for probe in p["ownership_probes"]), "ownership_probes_total": probe_count}, "pages": results}
    write_json(output_path or config.artifact_dir / "evaluation.json", report)
    return report
