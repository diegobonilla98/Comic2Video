from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from comic2video.e2e_jobs import RunJobs, download_output
from comic2video.prompting import build_video_request, check_request
from comic2video.storage import digest, read_json, write_json
from comic2video.video_recovery import recovery_plan
from run_end_to_end import PROJECT_ROOT, RUN_CONFIG, RUN_FOLDER, pages_in_order, video_tasks
import json
import shutil
import time


FALLBACK_MODELS = RUN_CONFIG["video_recovery"]["fallback_models"]
SCHEMA_FILES = {
    "kwaivgi/kling-v3-video": "kwaivgi_kling-v3-video.json",
    "bytedance/seedance-2.5": "bytedance_seedance-2.5.json",
    "prunaai/p-video-2-pro": "prunaai_p-video-2-pro.json",
    "kwaivgi/kling-v4.0": "kwaivgi_kling-v4.0.json",
    "minimax/h3-highspeed": "minimax_h3-highspeed.json",
}


def prepare_schemas():
    target = RUN_FOLDER / "models"
    target.mkdir(parents=True, exist_ok=True)
    for model, filename in SCHEMA_FILES.items():
        descriptor = read_json(PROJECT_ROOT / "docs" / "replicate_schemas" / filename)
        write_json(target / (model.replace("/", "_") + ".json"), descriptor)


def fallback_request(model, base, shot):
    source = base["input"]
    first = source["first_frame_image"]
    last = source.get("last_frame_image")
    prompt = source["prompt"].strip()
    duration = shot.duration
    if model == "kwaivgi/kling-v3-video":
        prompt += "\nUse @image_1 as the exact opening composition" + (" and @image_2 as the exact ending composition." if last else ".")
        payload = {"prompt": prompt, "start_image": first, "duration": duration, "mode": "standard", "generate_audio": True}
        if last:
            payload["end_image"] = last
    elif model == "bytedance/seedance-2.5":
        prompt += "\nAnimate from the supplied first frame to the supplied last frame while preserving the source comic artwork. Dialogue is spoken exactly as quoted; no music."
        payload = {"prompt": prompt, "image": first, "duration": duration, "resolution": "720p", "aspect_ratio": "adaptive", "generate_audio": True, "watermark": False, "output_format": "mp4"}
        if last:
            payload["last_frame_image"] = last
    elif model == "prunaai/p-video-2-pro":
        duration = max(5, duration)
        payload = {"prompt": prompt, "image": first, "duration": duration, "mode": "quality", "prompt_upsampler": "off", "resolution": "768p", "aspect_ratio": "16:9", "enable_safety_filter": True}
        if last:
            payload["last_frame_image"] = last
    elif model == "kwaivgi/kling-v4.0":
        prompt += "\nPreserve the source comic style. @image_1 is the first frame" + ("; @image_2 is the required last frame." if last else ".")
        payload = {"prompt": prompt, "start_image": first, "duration": duration, "resolution": "720p"}
        if last:
            payload["end_image"] = last
    elif model == "minimax/h3-highspeed":
        payload = {"prompt": prompt, "first_frame_image": first, "duration": duration, "ratio": "16:9"}
        if last:
            payload["last_frame_image"] = last
    else:
        raise ValueError("Unlisted fallback model")
    check_request(PROJECT_ROOT, SCHEMA_FILES[model], payload)
    return {"model": model, "input": payload}, duration


def recover_one(jobs, task):
    page_index, page, shot, frames, script = task
    folder = RUN_FOLDER / "clips" / shot.shot_id
    active = folder / "clip.mp4"
    if active.exists() and read_json(folder / "fallback_result.json").get("selected_clip") == str(active):
        return
    base = build_video_request(PROJECT_ROOT, shot, frames, script)
    attempts = []
    for model in FALLBACK_MODELS:
        request, requested_duration = fallback_request(model, base, shot)
        key = shot.shot_id + "_" + model.replace("/", "_")
        try:
            record, job_folder = jobs.run("video_recovery", key, request, [frames[shot.first_frame_id]["path"]] + ([frames[shot.last_frame_id]["path"]] if shot.last_frame_id else []))
        except RuntimeError as error:
            candidate_records = list((RUN_FOLDER / "jobs" / "video_recovery").glob(key + "_*/prediction.json"))
            if len(candidate_records) != 1:
                raise
            record = read_json(candidate_records[0])
            if record.get("status") not in {"failed", "canceled"}:
                raise
            attempts.append({"model": model, "prediction_id": record.get("prediction_id"), "status": record["status"], "error": record.get("error"), "record": str(candidate_records[0])})
            write_json(folder / "fallback_attempts.json", attempts)
            print("fallback", shot.shot_id, model, record["status"], str(error)[:220], flush=True)
            continue
        model_folder = folder / "fallback" / model.replace("/", "_")
        output_path = model_folder / "clip.mp4"
        download_output(record, output_path)
        chosen = folder / "clip.mp4"
        temporary = chosen.with_suffix(".mp4.tmp")
        shutil.copyfile(output_path, temporary)
        temporary.replace(chosen)
        receipt = {"selected_model": model, "prediction_id": record.get("prediction_id"), "status": record["status"], "version": record.get("version"), "prediction": str(job_folder / "prediction.json"), "source_clip": str(output_path), "selected_clip": str(chosen), "requested_duration": shot.duration, "model_duration": requested_duration, "native_audio_requested": model in {"kwaivgi/kling-v3-video", "bytedance/seedance-2.5"}, "image_inputs_reused": True, "fallback_order": FALLBACK_MODELS, "earlier_failures": attempts}
        write_json(folder / "fallback_attempts.json", attempts + [{"model": model, "prediction_id": record.get("prediction_id"), "status": "succeeded", "record": str(job_folder / "prediction.json")}])
        write_json(folder / "fallback_result.json", receipt)
        if (folder / "placeholder.mp4").exists():
            (folder / "placeholder.mp4").unlink()
        if (folder / "placeholder.png").exists():
            (folder / "placeholder.png").unlink()
        print("fallback", shot.shot_id, model, "succeeded", output_path, flush=True)
        return receipt
    write_json(folder / "fallback_result.json", {"selected_model": None, "status": "all_fallbacks_failed", "fallback_order": FALLBACK_MODELS, "attempts": attempts, "image_inputs_reused": True})
    print("fallback exhausted", shot.shot_id, flush=True)
    return None


def main():
    prepare_schemas()
    tasks = video_tasks(pages_in_order())
    candidates = []
    records = []
    by_key = {}
    for task in tasks:
        shot = task[2]
        original = list((RUN_FOLDER / "jobs" / "video").glob(shot.shot_id + "_*/prediction.json"))
        if len(original) != 1:
            raise ValueError("Expected one original video job: " + shot.shot_id)
        record = read_json(original[0])
        record["key"] = shot.shot_id
        records.append(record)
        by_key[shot.shot_id] = task
    plan = recovery_plan(records, RUN_CONFIG["video_recovery"])
    failed = [by_key[row["shot_id"]] for row in plan if row["eligible_for_fallback"]]
    if len(FALLBACK_MODELS) != RUN_CONFIG["video_recovery"]["max_attempts_per_shot"]:
        raise ValueError("Fallback attempt budget does not match the ordered model list")
    preflight = []
    for task in failed:
        index, page, shot, frames, script = task
        base = build_video_request(PROJECT_ROOT, shot, frames, script)
        for model in FALLBACK_MODELS:
            request, duration = fallback_request(model, base, shot)
            preflight.append({"shot_id": shot.shot_id, "model": model, "duration": duration, "first_frame_sha256": digest(Path(frames[shot.first_frame_id]["path"]).read_bytes()), "last_frame_sha256": digest(Path(frames[shot.last_frame_id]["path"]).read_bytes()) if shot.last_frame_id else None, "request": {key: value for key, value in request["input"].items() if key not in {"image", "last_frame_image", "start_image", "end_image", "first_frame_image"}}})
    write_json(RUN_FOLDER / "video_recovery_preflight.json", {"targets": [task[2].shot_id for task in failed], "fallback_order": FALLBACK_MODELS, "safety_filters": "provider defaults; never disabled", "validated_requests": preflight, "models_can_produce_audio": {"kwaivgi/kling-v3-video": True, "bytedance/seedance-2.5": True, "prunaai/p-video-2-pro": True, "kwaivgi/kling-v4.0": False, "minimax/h3-highspeed": "interface-dependent; verify returned media"}})
    jobs = RunJobs(PROJECT_ROOT, RUN_CONFIG)
    print("Recovery targets", [task[2].shot_id for task in failed], "prior successful videos reused", len(tasks) - len(failed), flush=True)
    errors = []
    with ThreadPoolExecutor(max_workers=RUN_CONFIG["concurrency"]) as pool:
        futures = {pool.submit(recover_one, jobs, task): task for task in failed}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                errors.append({"shot_id": futures[future][2].shot_id, "error": repr(error)})
                print("recovery error", futures[future][2].shot_id, repr(error), flush=True)
    write_json(RUN_FOLDER / "video_recovery_run.json", {"targets": [task[2].shot_id for task in failed], "fallback_order": FALLBACK_MODELS, "safety_filters": "provider defaults; never disabled", "parallel_shots": RUN_CONFIG["concurrency"], "errors": errors, "completed_at": time.time()})
    if errors:
        raise RuntimeError("Fallback run errors; see video_recovery_run.json")


if __name__ == "__main__":
    main()
