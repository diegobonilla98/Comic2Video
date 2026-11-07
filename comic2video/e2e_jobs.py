from pathlib import Path
from threading import Lock
from dotenv import dotenv_values
from comic2video.storage import canonical, digest, read_json, write_json
import httpx
import replicate
import time


MEDIA_KEYS = {"image_input", "input_images", "first_frame_image", "last_frame_image"}


class RunJobs:
    def __init__(self, root, config):
        self.folder = root / config["artifact_dir"]
        self.config = config
        self.client = replicate.Client(api_token=dotenv_values(root / ".env")["REPLICATE_API_TOKEN"].strip(), timeout=60)
        self.lock = Lock()
        self.new_predictions = len(list((self.folder / "jobs").glob("*/*/prediction.json")))
        self.descriptors = {}
        for model in config["authorized_models"]:
            path = self.folder / "models" / (model.replace("/", "_") + ".json")
            if path.exists():
                descriptor = read_json(path)
            else:
                version = self.client.models.get(model).latest_version
                descriptor = {"model": model, "version": version.id, "schema": version.openapi_schema}
                write_json(path, descriptor)
            self.descriptors[model] = descriptor

    def run(self, stage, key, request, sources):
        model = request["model"]
        if model not in self.config["authorized_models"]:
            raise PermissionError("Model outside the authorized run scope")
        request_hash = digest(canonical(request))
        folder = self.folder / "jobs" / stage / (key + "_" + request_hash[:12])
        record_path = folder / "prediction.json"
        if record_path.exists():
            record = read_json(record_path)
            if record["status"] == "succeeded":
                return record, folder
            if not record.get("prediction_id"):
                raise RuntimeError(f"Unknown submission outcome: {record_path}")
            prediction = self.client.predictions.get(record["prediction_id"])
        else:
            with self.lock:
                if self.new_predictions >= self.config["max_new_predictions"]:
                    raise RuntimeError("Run call budget reached")
                self.new_predictions += 1
            media = {name: digest(canonical(value)) for name, value in request["input"].items() if name in MEDIA_KEYS}
            write_json(folder / "request.json", {"model": model, "request_sha256": request_hash, "schema_version": self.descriptors[model]["version"], "input": {k: v for k, v in request["input"].items() if k not in MEDIA_KEYS}, "media_input_hashes": media, "sources": [{"path": str(path), "sha256": digest(Path(path).read_bytes())} for path in sources]})
            record = {"model": model, "stage": stage, "key": key, "status": "submitting", "request_sha256": request_hash}
            write_json(record_path, record)
            prediction = self.client.predictions.create(model=model, input=request["input"])
            record.update(prediction_id=prediction.id, status=prediction.status)
            write_json(record_path, record)
            print(stage, key, "submitted", prediction.id, flush=True)
        deadline = time.monotonic() + self.config["prediction_timeout_seconds"]
        while prediction.status not in {"succeeded", "failed", "canceled"}:
            if time.monotonic() >= deadline:
                record.update(status="still_running")
                write_json(record_path, record)
                raise TimeoutError(f"Still running; resume by prediction ID: {record_path}")
            time.sleep(3)
            prediction.reload()
        record.update(status=prediction.status, output=prediction.output, error=prediction.error, logs=prediction.logs, metrics=prediction.metrics, version=prediction.version, created_at=prediction.created_at, started_at=prediction.started_at, completed_at=prediction.completed_at)
        write_json(record_path, record)
        print(stage, key, prediction.status, flush=True)
        if prediction.status != "succeeded":
            raise RuntimeError(f"{stage} {key}: {prediction.error}")
        return record, folder


def output_urls(value):
    if isinstance(value, str) and value.startswith("https://"):
        return [value]
    if isinstance(value, (list, tuple)):
        return [url for item in value for url in output_urls(item)]
    if isinstance(value, dict):
        return [url for item in value.values() for url in output_urls(item)]
    return []


def download_output(record, path):
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        return path
    url = output_urls(record["output"])[0]
    temporary = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=180) as response:
        response.raise_for_status()
        with temporary.open("wb") as stream:
            for chunk in response.iter_bytes():
                stream.write(chunk)
    temporary.replace(path)
    return path
