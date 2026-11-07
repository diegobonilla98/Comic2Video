from pathlib import Path
from comic2video.contracts import Page
from comic2video.evaluation import evaluate
from comic2video.extraction import export_panels, load_override
from comic2video.storage import digest, load_config, read_json, write_json
import json


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG = load_config(PROJECT_ROOT)
CORRECTION_DIRECTORY = PROJECT_ROOT / "examples" / "corrections"


def main():
    pages = {p["page_id"]: Page.model_validate(p) for p in read_json(CONFIG.artifact_dir / "ingestion.json")["pages"]}
    run = read_json(CONFIG.artifact_dir / "run_manifest.json")
    results = {p["page_id"]: p for p in run["pages"]}
    for path in sorted(CORRECTION_DIRECTORY.glob("*.json")):
        page = pages[read_json(path)["page_id"]]
        layout = load_override(path, page)
        extraction, manifest = export_panels(page, layout, CONFIG, "manual_override", {"source_sha256": page.source_sha256, "override_sha256": digest(path.read_bytes()), "note": "Provisional hand correction; not automatic model output"})
        results[page.page_id].update(panel_count=len(extraction.panels), extraction_manifest=str(manifest))
    run["pages"] = list(results.values())
    run["manual_corrections"] = True
    manifest_path = CONFIG.artifact_dir / "corrected_run_manifest.json"
    write_json(manifest_path, run)
    report = evaluate(PROJECT_ROOT, CONFIG, manifest_path, CONFIG.artifact_dir / "corrected_evaluation.json")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
