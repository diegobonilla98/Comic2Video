from pathlib import Path
import os
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_DIRECTORY = PROJECT_ROOT / "work" / "benchmark_runtime"
MODEL_SCRIPTS = ["run_koharu.py", "run_magiv3.py"]


if __name__ == "__main__":
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join([str(RUNTIME_DIRECTORY), str(PROJECT_ROOT)])
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["USE_TF"] = "0"
    environment["USE_FLAX"] = "0"
    environment["PYTHONUNBUFFERED"] = "1"
    for script in MODEL_SCRIPTS:
        subprocess.run([sys.executable, str(PROJECT_ROOT / "benchmarks" / script)], cwd=PROJECT_ROOT, env=environment, check=True)
