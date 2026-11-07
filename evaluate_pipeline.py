from pathlib import Path
from comic2video.evaluation import evaluate
from comic2video.storage import load_config
import json


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG = load_config(PROJECT_ROOT)


if __name__ == "__main__":
    report = evaluate(PROJECT_ROOT, CONFIG)
    print(json.dumps(report["summary"], indent=2))
