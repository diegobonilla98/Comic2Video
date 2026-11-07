from pathlib import Path
from PIL import Image
from transformers import AutoModelForCausalLM, AutoProcessor
from comic2video.benchmark import benchmark_inputs, file_sha256, rectangle_mask, result_folder, save_result
from comic2video.storage import digest, read_json, write_json
import importlib.metadata
import time
import torch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = read_json(PROJECT_ROOT / "benchmark_config.json")
MODEL_ID = "ragavsachdeva/magiv3"
MODEL_DIRECTORY = Path(CONFIG["model_cache_dir"]) / "magiv3"


def main():
    if MODEL_ID not in CONFIG["authorized_models"]:
        raise PermissionError("Model is not authorized for this benchmark")
    torch.manual_seed(CONFIG["seed"])
    revision = read_json(MODEL_DIRECTORY / "repo.json")["sha"]
    settings = {"interface": CONFIG["magi_interface"], "dtype": CONFIG["magi_dtype"], "device": CONFIG["device"], "generation": CONFIG["magi_generation"]}
    folder = result_folder(PROJECT_ROOT, MODEL_ID, revision, settings)
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIRECTORY, torch_dtype=torch.float16, trust_remote_code=True, local_files_only=True, attn_implementation="eager").to(CONFIG["device"]).eval()
    processor = AutoProcessor.from_pretrained(MODEL_DIRECTORY, trust_remote_code=True, local_files_only=True)
    provenance = {"model": MODEL_ID, "revision": revision, "weights_sha256": file_sha256(MODEL_DIRECTORY / "model.safetensors"), "settings": settings, "packages": {p: importlib.metadata.version(p) for p in ["transformers", "torch", "timm"]}, "gpu": torch.cuda.get_device_name(0)}
    results = []
    for item in benchmark_inputs(PROJECT_ROOT):
        path = folder / item["input_id"] / "result.json"
        if path.exists() and read_json(path)["input"]["source_sha256"] == item["source_sha256"]:
            result = read_json(path)
        else:
            with Image.open(item["image_path"]) as source:
                image = source.convert("RGB")
            torch.cuda.synchronize()
            start = time.perf_counter()
            with torch.inference_mode():
                prediction = model.predict_detections_and_associations([image], processor)[0]
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - start
            detections = [{"label": "frame" if category == "panels" else category, "bbox": box, "confidence": None} for category in ["panels", "texts", "characters", "tails"] for box in prediction[category]]
            masks = [rectangle_mask(d["bbox"], image.width, image.height) for d in detections]
            result = save_result(folder, item, detections, masks, "bounding_box_only", elapsed, prediction, provenance)
        results.append({"result_path": str(path), "source_file": item["source_file"], "panel_count": len(result["panels"]), "kind": item["kind"]})
        print(item["source_file"], len(result["panels"]), f"{result['inference_seconds']:.2f}s", flush=True)
    write_json(folder / "run.json", {"provenance": provenance, "results": results})
    print("Saved", folder, flush=True)


if __name__ == "__main__":
    main()
