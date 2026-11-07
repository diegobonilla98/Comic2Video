from pathlib import Path
from comic2video.contracts import Extraction, Layout, Page, Panel
from comic2video.extraction import extract_local
from comic2video.storage import ingest, load_config, write_json
import importlib.metadata
import platform


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG = load_config(PROJECT_ROOT)


def main():
    pages = ingest(CONFIG)
    write_json(CONFIG.artifact_dir / "environment.json", {"python": platform.python_version(), "packages": {name: importlib.metadata.version(name) for name in ["replicate", "pydantic", "Pillow", "opencv-python", "numpy", "python-dotenv", "jsonschema"]}})
    for contract in (Page, Panel, Layout, Extraction):
        write_json(CONFIG.artifact_dir / "schemas" / f"{contract.__name__.lower()}.json", contract.model_json_schema())
    results = []
    for page in pages:
        extraction, manifest = extract_local(page, CONFIG)
        results.append({"page_id": page.page_id, "source_file": page.source_file, "panel_count": len(extraction.panels), "extraction_manifest": str(manifest), "video_ready": extraction.video_ready})
        print(f"{page.source_file}: {len(extraction.panels)} panel candidates")
    write_json(CONFIG.artifact_dir / "run_manifest.json", {"schema_version": "1.0", "provider": CONFIG.provider, "model_execution": False, "pages": results})
    print(f"Ingested {len(pages)} pages. No model calls. Review: {CONFIG.artifact_dir / 'run_manifest.json'}")


if __name__ == "__main__":
    main()
