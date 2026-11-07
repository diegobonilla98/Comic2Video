from pathlib import Path
from PIL import Image
from safetensors.torch import load_file
from ultralytics import YOLO
from comic2video.benchmark import benchmark_inputs, file_sha256, result_folder, save_result
from comic2video.storage import digest, read_json, write_json
import importlib.metadata
import numpy as np
import time
import torch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = read_json(PROJECT_ROOT / "benchmark_config.json")
MODEL_ID = "mayocream/koharu-yolo26s"
MODEL_DIRECTORY = Path(CONFIG["model_cache_dir"]) / "koharu-yolo26s"


def main():
    if MODEL_ID not in CONFIG["authorized_models"]:
        raise PermissionError("Model is not authorized for this benchmark")
    torch.manual_seed(CONFIG["seed"])
    revision = read_json(MODEL_DIRECTORY / "repo.json")["sha"]
    settings = {"imgsz": CONFIG["koharu_image_size"], "conf": CONFIG["koharu_confidence"], "retina_masks": CONFIG["koharu_retina_masks"], "device": CONFIG["device"]}
    folder = result_folder(PROJECT_ROOT, MODEL_ID, revision, settings)
    model = YOLO(MODEL_DIRECTORY / "yolo26s-seg.yaml", task="segment")
    model.model.load_state_dict(load_file(MODEL_DIRECTORY / "model.safetensors"), strict=True)
    model.model.names = {int(k): v for k, v in read_json(MODEL_DIRECTORY / "config.json")["names"].items()}
    provenance = {"model": MODEL_ID, "revision": revision, "weights_sha256": file_sha256(MODEL_DIRECTORY / "model.safetensors"), "settings": settings, "packages": {p: importlib.metadata.version(p) for p in ["ultralytics", "torch", "safetensors"]}, "gpu": torch.cuda.get_device_name(0)}
    results = []
    for item in benchmark_inputs(PROJECT_ROOT):
        path = folder / item["input_id"] / "result.json"
        if path.exists() and read_json(path)["input"]["source_sha256"] == item["source_sha256"]:
            result = read_json(path)
        else:
            torch.cuda.synchronize()
            start = time.perf_counter()
            prediction = model.predict(item["image_path"], **settings, save=False, verbose=False)[0]
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - start
            detections = [{"label": prediction.names[int(box.cls.item())], "bbox": box.xyxy[0].cpu().tolist(), "confidence": float(box.conf.item())} for box in prediction.boxes]
            masks = [np.uint8(mask.cpu().numpy() > 0) * 255 for mask in prediction.masks.data] if prediction.masks is not None else []
            result = save_result(folder, item, detections, masks, "instance_mask", elapsed, {"speed_ms": prediction.speed}, provenance)
        results.append({"result_path": str(path), "source_file": item["source_file"], "panel_count": len(result["panels"]), "kind": item["kind"]})
        print(item["source_file"], len(result["panels"]), f"{result['inference_seconds']:.2f}s", flush=True)
    write_json(folder / "run.json", {"provenance": provenance, "results": results})
    print("Saved", folder, flush=True)


if __name__ == "__main__":
    main()
