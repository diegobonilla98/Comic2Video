from pathlib import Path
from huggingface_hub import snapshot_download
from comic2video.storage import read_json, write_json
import os
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG = read_json(PROJECT_ROOT / "benchmark_config.json")
INSTALL_ISOLATED_DEPENDENCIES = True
REVISIONS = {
    "mayocream/koharu-yolo26s": "aa7b56752bc91337e0af1e44ad08b4022c9a975b",
    "ragavsachdeva/magiv3": "49c73a225122d53adbaa26d53868be81a57706e2",
}


def main():
    if set(CONFIG["authorized_models"]) != set(REVISIONS):
        raise ValueError("This preparation script supports only the two explicitly requested models")
    if INSTALL_ISOLATED_DEPENDENCIES:
        subprocess.run([sys.executable, "-m", "pip", "install", "--target", str(PROJECT_ROOT / "work" / "benchmark_runtime"), "--no-deps", "--upgrade", "-r", str(PROJECT_ROOT / "benchmark_dependencies.txt")], check=True)
    for model, revision in REVISIONS.items():
        folder = Path(CONFIG["model_cache_dir"]) / model.split("/")[-1]
        snapshot_download(model, revision=revision, local_dir=folder, allow_patterns=["*.safetensors", "*.json", "*.py", "*.yaml", "*.txt", "*.md"], token=False)
        write_json(folder / "repo.json", {"id": model, "sha": revision})
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    subprocess.run([sys.executable, str(PROJECT_ROOT / "benchmarks" / "build_fixtures.py")], cwd=PROJECT_ROOT, env=environment, check=True)


if __name__ == "__main__":
    main()
