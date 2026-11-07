from pathlib import Path
from dotenv import dotenv_values
from jsonschema import Draft202012Validator
from comic2video.storage import canonical, digest, read_json, write_json
import base64
import mimetypes
import os
import replicate
import time


def image_input(path):
    path = Path(path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{media_type};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


class ReplicateProvider:
    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.created_predictions = 0
        self.client = None

    def connect(self):
        if self.client is None:
            token = os.environ.get("REPLICATE_API_TOKEN") or dotenv_values(self.root / ".env").get("REPLICATE_API_TOKEN")
            if not token or not token.strip():
                raise ValueError("REPLICATE_API_TOKEN is missing")
            self.client = replicate.Client(api_token=token.strip(), timeout=30)
        return self.client

    def predict(self, model, inputs, source_files=()):
        if not self.config.allow_model_execution:
            raise PermissionError("Model execution is disabled in config.json")
        model_folder = self.config.artifact_dir / "models"
        schema_file = model_folder / (model.replace("/", "_") + ".json")
        if schema_file.exists():
            descriptor = read_json(schema_file)
        else:
            version = self.connect().models.get(model).latest_version
            if version is None:
                raise ValueError(f"No accessible version for {model}")
            descriptor = {"model": model, "version": version.id, "schema": version.openapi_schema}
            write_json(schema_file, descriptor)
        schema = dict(descriptor["schema"], **{"$ref": "#/components/schemas/Input"})
        unknown = set(inputs) - set(schema["components"]["schemas"]["Input"]["properties"])
        if unknown:
            raise ValueError(f"Unsupported input fields for {model}: {sorted(unknown)}")
        Draft202012Validator(schema).validate(inputs)
        request_hash = digest(canonical({"model": model, "version": descriptor["version"], "input": inputs}))
        record_path = self.config.artifact_dir / "predictions" / (request_hash + ".json")
        if record_path.exists():
            record = read_json(record_path)
            if record["status"] == "succeeded":
                return record
            if record.get("prediction_id") is None:
                raise RuntimeError("Previous submission has unknown outcome; reconcile on Replicate before resubmitting")
            if record["status"] in {"failed", "canceled"}:
                raise RuntimeError(f"Cached prediction {record['prediction_id']} {record['status']}")
            prediction = self.connect().predictions.get(record["prediction_id"])
        else:
            if self.created_predictions >= self.config.max_new_predictions:
                raise RuntimeError("Configured new-prediction limit reached")
            current_version = self.connect().models.get(model).latest_version
            if current_version is None or current_version.id != descriptor["version"]:
                raise RuntimeError("Model schema changed; review the stored descriptor before submitting")
            media_keys = {"images", "image", "last_frame", "reference_images", "image_input", "input_images", "first_frame_image", "last_frame_image", "start_image", "end_image", "reference_image_urls", "reference_video_urls", "reference_audio_urls"}
            record = {"provider": "replicate", "model": model, "version": descriptor["version"], "request_sha256": request_hash, "status": "submitting", "prediction_id": None, "source_files": [str(p) for p in source_files], "settings": {k: v for k, v in inputs.items() if k not in media_keys}}
            write_json(record_path, record)
            self.created_predictions += 1
            prediction = self.connect().predictions.create(model=model, input=inputs)
            record.update(prediction_id=prediction.id, status=prediction.status, executed_version=prediction.version)
            write_json(record_path, record)
        deadline = time.monotonic() + self.config.prediction_timeout_seconds
        while prediction.status not in {"succeeded", "failed", "canceled"}:
            if time.monotonic() >= deadline:
                prediction.cancel()
                record.update(status="cancel_requested")
                write_json(record_path, record)
                raise TimeoutError(f"Prediction {prediction.id} exceeded the configured deadline; cancellation requested")
            time.sleep(self.config.poll_seconds)
            prediction.reload()
        record.update(status=prediction.status, output=prediction.output, error=prediction.error, metrics=prediction.metrics, created_at=prediction.created_at, completed_at=prediction.completed_at)
        write_json(record_path, record)
        if prediction.status != "succeeded":
            raise RuntimeError(f"Prediction {prediction.id} {prediction.status}; see {record_path}")
        return record
