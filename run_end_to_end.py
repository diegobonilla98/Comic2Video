from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageOps
from pydantic import ValidationError
from comic2video.contracts import Page, PanelGeometry
from comic2video.e2e_contracts import PageUnderstanding
from comic2video.e2e_jobs import RunJobs, download_output
from comic2video.extraction import export_panels
from comic2video.geometry import original_coordinates, reading_order
from comic2video.cleaning import build_cleaning_request
from comic2video.prompting import build_video_request
from comic2video.provider import image_input
from comic2video.storage import canonical, digest, load_config, natural_key, read_json, write_json
import html
import imageio_ffmpeg
import json
import shutil
import subprocess
import time


PROJECT_ROOT = Path(__file__).resolve().parent
RUN_CONFIG = read_json(PROJECT_ROOT / "e2e_run_config.json")
RUN_FOLDER = PROJECT_ROOT / RUN_CONFIG["artifact_dir"]
DELIVERY_FOLDER = PROJECT_ROOT / "outputs" / ("end_to_end_" + Path(RUN_CONFIG["input_dir"]).name)


def pages_in_order():
    ingestion = read_json(PROJECT_ROOT / "artifacts" / "ingestion.json")
    by_source = {p["source_file"]: p for p in ingestion["pages"]}
    supported = {".png", ".jpg", ".jpeg", ".webp"}
    paths = sorted((p for p in (PROJECT_ROOT / RUN_CONFIG["input_dir"]).iterdir() if p.is_file() and p.suffix.lower() in supported), key=natural_key)
    source_prefix = Path(RUN_CONFIG["input_dir"]).name
    pages = []
    for path in paths:
        page = Page.model_validate(by_source[source_prefix + "/" + path.name])
        if digest(path.read_bytes()) != page.source_sha256:
            raise ValueError("Source changed since cached Magi detection")
        pages.append(page)
    return pages


def proposal_context(page, index):
    run = read_json(PROJECT_ROOT / RUN_CONFIG["magi_run"])
    result_path = next(p["result_path"] for p in run["results"] if p["source_file"] == page.source_file)
    result = read_json(result_path)
    if result["input"]["source_sha256"] != page.source_sha256:
        raise ValueError("Magi cache source hash mismatch")
    regions = []
    for number, panel in enumerate(result["panels"]):
        x0, y0, x1, y1 = panel["bbox"]
        polygon = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        regions.append(PanelGeometry(key=str(number), layout_polygon=polygon, content_polygons=[polygon]))
    order = reading_order(regions, "ltr")
    proposals = [{"key": f"p{index:02d}_{i + 1:02d}", "bbox": result["panels"][int(key)]["bbox"]} for i, key in enumerate(order)]
    return proposals, result_path


def understanding_path(index):
    folder = RUN_FOLDER / "pages" / f"{index:02d}"
    reviewed = folder / "understanding.reviewed.json"
    return reviewed if reviewed.exists() else folder / "understanding.json"


def understand(jobs, pages):
    registry = {}
    previous = None
    for index, page in enumerate(pages):
        target = understanding_path(index)
        proposals, magi_path = proposal_context(page, index)
        context = {"page_index": index, "id_prefix": f"page{index}", "width": page.width, "height": page.height, "reading_convention": "ltr", "proposals": proposals, "cached_text_boxes": read_json(magi_path)["raw_output"]["texts"], "registry": list(registry.values()), "target_aspect_ratio": RUN_CONFIG["target_aspect_ratio"], "backend": {"model": "minimax/h3-lite", "duration_seconds": [4, 15], "resolution": "768P", "native_audio_observed": True, "music": False}, "previous_page_is_identity_context_only": previous is not None}
        if target.exists():
            understanding = PageUnderstanding.model_validate(read_json(target))
            if set(understanding.layout.reading_order) != {p["key"] for p in proposals}:
                raise ValueError(f"Cached understanding mismatches verified current-page proposals: {target}")
        else:
            images = [Path(page.source_snapshot)]
            schema = PageUnderstanding.model_json_schema()
            system = (PROJECT_ROOT / "prompts" / "page_understanding.system.txt").read_text(encoding="utf-8")
            payload = {"system_prompt": system, "prompt": json.dumps({"context": context, "output_schema": schema}, ensure_ascii=False, separators=(",", ":")), "image_input": [image_input(p) for p in images], "verbosity": "low", "reasoning_effort": "low", "max_completion_tokens": RUN_CONFIG["understanding_completion_tokens"]}
            write_json(target.parent / "context.json", dict(context, cached_magi_result=magi_path, image_sources=[str(p) for p in images]))
            for attempt in range(2):
                record, folder = jobs.run("understanding" if attempt == 0 else "repair", f"page{index}", {"model": "openai/gpt-5.6-terra", "input": payload}, images)
                output = record["output"]
                text = output if isinstance(output, str) else "".join(output)
                (folder / "response.txt").write_text(text, encoding="utf-8")
                try:
                    understanding = PageUnderstanding.model_validate_json(text)
                    understanding.layout = original_coordinates(understanding.layout, page.width, page.height)
                    if set(understanding.layout.reading_order) != {p["key"] for p in proposals}:
                        raise ValueError("Current-page panel IDs must match the visually verified cached proposals; do not replace the page with another image")
                    break
                except (ValidationError, ValueError) as error:
                    write_json(folder / "validation_error.json", {"error": str(error)})
                    if attempt == 1:
                        raise
                    payload["prompt"] = json.dumps({"context": context, "output_schema": schema, "invalid_output": text, "validation_errors": str(error)}, ensure_ascii=False, separators=(",", ":"))
                    payload["system_prompt"] += "\nRepair only these validation errors; preserve exact source text and valid facts."
            write_json(target, understanding.model_dump(mode="json"))
        for character in understanding.script.character_updates:
            registry[character.character_id] = character.model_dump(mode="json")
        write_json(target.parent / "registry_after.json", registry)
        config = load_config(PROJECT_ROOT)
        config.artifact_dir = RUN_FOLDER
        extraction, manifest = export_panels(page, understanding.layout, config, "terra_owned_content", {"understanding_path": str(target), "source_sha256": page.source_sha256, "magi_proposals": magi_path})
        write_json(target.parent / "extraction_link.json", {"manifest": str(manifest), "overlay": str(manifest.parent / "overlay.jpg"), "contact_sheet": str(manifest.parent / "contact_sheet.jpg")})
        print("page", index, "panels", len(extraction.panels), "texts", len(understanding.script.texts), "shots", len(understanding.director.shots), "review", [s.shot_id for s in understanding.director.shots if s.requires_review], flush=True)
        previous = page


def all_panels(pages):
    entries = []
    for index, page in enumerate(pages):
        understanding = PageUnderstanding.model_validate(read_json(understanding_path(index)))
        extraction_path = read_json(RUN_FOLDER / "pages" / f"{index:02d}" / "extraction_link.json")["manifest"]
        extraction = read_json(extraction_path)
        for panel in extraction["panels"]:
            entries.append((index, page, panel, understanding))
    return entries


def clean_panel(jobs, entry):
    index, page, panel, understanding = entry
    key = panel["key"]
    folder = RUN_FOLDER / "frames" / key
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "clean.png"
    if output.exists():
        return {"panel_id": key, "path": str(output)}
    crop = Image.open(panel["source_crop"]).convert("RGBA")
    background = Image.new("RGB", crop.size, "white")
    background.paste(crop, mask=crop.getchannel("A"))
    source = folder / "isolated_rgb.png"
    background.save(source)
    texts = [t for t in understanding.script.texts if t.panel_id == key]
    write_json(folder / "edit_plan.json", {"source_panel": panel, "remove_text_ids": [t.text_id for t in texts if t.category in {"speech", "thought", "narration", "sound_effect"}], "preserve_text": [t.model_dump(mode="json") for t in texts if t.category in {"scene_text", "unknown"}], "target_aspect_ratio": RUN_CONFIG["target_aspect_ratio"], "unknown_ownership_requires_review": any(t.uncertain for t in texts)})
    request = build_cleaning_request(PROJECT_ROOT, [source], RUN_CONFIG["target_aspect_ratio"])
    preserve = [t.text for t in texts if t.category in {"scene_text", "unknown"} and not t.uncertain]
    if preserve:
        request["input"]["prompt"] += " Keep this scene lettering: " + json.dumps(preserve, ensure_ascii=False) + "."
    record, job_folder = jobs.run("cleaning", key, request, [source])
    download_output(record, output)
    with Image.open(output) as image:
        image.verify()
    write_json(folder / "provenance.json", {"source_page": page.source_file, "panel_id": key, "prediction": str(job_folder / "prediction.json"), "clean_sha256": digest(output.read_bytes())})
    return {"panel_id": key, "path": str(output)}


def parallel_stage(function, items):
    errors = []
    with ThreadPoolExecutor(max_workers=RUN_CONFIG["concurrency"]) as pool:
        futures = {pool.submit(function, item): item for item in items}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                item = futures[future]
                errors.append({"item": str(item)[:300], "error": str(error)})
                print("stage failure", str(error)[:300], flush=True)
    if errors:
        write_json(RUN_FOLDER / (RUN_CONFIG["phase"] + "_errors.json"), errors)
        raise RuntimeError(f"{len(errors)} jobs failed; successful jobs are cached")


def contact_sheet(pages, stage):
    entries = all_panels(pages)
    columns = 4
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 340, rows * 230), "#e0e0e0")
    draw = ImageDraw.Draw(sheet)
    for i, (_, _, panel, _) in enumerate(entries):
        key = panel["key"]
        path = RUN_FOLDER / "frames" / key / "clean.png" if stage == "cleaning" else Path(panel["source_crop"])
        x, y = (i % columns) * 340, (i // columns) * 230
        draw.text((x + 6, y + 5), key, fill="black")
        if path.exists():
            image = Image.open(path).convert("RGBA")
            thumb = ImageOps.contain(image, (330, 200))
            sheet.paste(thumb, (x + 5, y + 25), thumb)
    path = RUN_FOLDER / (stage + "_contact_sheet.jpg")
    sheet.save(path)
    print("Contact sheet:", path, flush=True)


def video_tasks(pages):
    approval = read_json(RUN_FOLDER / "frame_review.json")
    frames = {}
    for _, _, panel, _ in all_panels(pages):
        key = panel["key"]
        frames[key + "_frame"] = {"panel_id": key, "path": RUN_FOLDER / "frames" / key / "clean.png", "video_ready": approval.get(key, {}).get("approved", False)}
    tasks = []
    for index, page in enumerate(pages):
        understanding = PageUnderstanding.model_validate(read_json(understanding_path(index)))
        for shot in understanding.director.shots:
            tasks.append((index, page, shot, frames, understanding.script))
    return tasks


def generate_video(jobs, task):
    index, page, shot, frames, script = task
    request = build_video_request(PROJECT_ROOT, shot, frames, script)
    folder = RUN_FOLDER / "clips" / shot.shot_id
    write_json(folder / "shot.json", dict(shot.model_dump(mode="json"), source_page=page.source_file, page_index=index))
    sources = [frames[shot.first_frame_id]["path"]] + ([frames[shot.last_frame_id]["path"]] if shot.last_frame_id else [])
    record, job_folder = jobs.run("video", shot.shot_id, request, sources)
    download_output(record, folder / "clip.mp4")
    write_json(folder / "provenance.json", {"prediction": str(job_folder / "prediction.json"), "shot_id": shot.shot_id})


def assemble(pages):
    tasks = video_tasks(pages)
    missing = [shot.shot_id for _, _, shot, _, _ in tasks if not (RUN_FOLDER / "clips" / shot.shot_id / "clip.mp4").exists()]
    if missing:
        raise RuntimeError("Montage requires generated clips; missing: " + ", ".join(missing))
    DELIVERY_FOLDER.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    clips = []
    timeline = []
    diagnostic = False
    cursor = 0.0
    for index, page, shot, frames, script in tasks:
        folder = RUN_FOLDER / "clips" / shot.shot_id
        source = folder / "clip.mp4"
        probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(source)], capture_output=True, text=True)
        has_audio = "Audio:" in probe.stderr
        duration_text = probe.stderr.split("Duration: ", 1)[1].split(",", 1)[0]
        hours, minutes, seconds = duration_text.split(":")
        source_duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        write_json(folder / "media_probe.json", {"ffmpeg_metadata": probe.stderr, "has_audio": has_audio})
        fallback_result = folder / "fallback_result.json"
        if not has_audio and shot.dialogue and not fallback_result.exists():
            raise ValueError(f"Dialogue clip has no audio stream: {shot.shot_id}")
        normalized = folder / ("normalized_" + digest(source.read_bytes())[:12] + ".mp4")
        if not normalized.exists():
            command = [ffmpeg, "-y", "-i", str(source)]
            if not has_audio:
                command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            audio_filter = "aresample=48000,loudnorm=I=-18:TP=-2:LRA=11,apad" if shot.dialogue else "aresample=48000,alimiter=limit=0.794,apad"
            command += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,tpad=stop_mode=clone:stop_duration=2", "-af", audio_filter, "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", str(source_duration), "-movflags", "+faststart", str(normalized)]
            result = subprocess.run(command, capture_output=True, text=True)
            (folder / "normalization.log").write_text(result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"Normalization failed: {shot.shot_id}")
        duration_probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(normalized)], capture_output=True, text=True)
        duration_text = duration_probe.stderr.split("Duration: ", 1)[1].split(",", 1)[0]
        hh, mm, ss = duration_text.split(":")
        duration = int(hh) * 3600 + int(mm) * 60 + float(ss)
        clips.append(normalized)
        timeline.append({"shot_id": shot.shot_id, "source_page": page.source_file, "source_panels": shot.panel_ids, "start_seconds": cursor, "duration_seconds": duration, "kind": "model_video", "generated_audio": has_audio, "failure": None, "fallback": read_json(fallback_result) if fallback_result.exists() else None, "original_clip": str(source), "normalized_clip": str(normalized), "dialogue": [d.model_dump(mode="json") for d in shot.dialogue]})
        cursor += duration
    concat = RUN_FOLDER / "concat.txt"
    concat.write_text("\n".join("file '" + str(p).replace("\\", "/").replace("'", "'\\''") + "'" for p in clips), encoding="utf-8")
    final = DELIVERY_FOLDER / ("Comic2Video_test_data_" + Path(RUN_CONFIG["input_dir"]).name + ".mp4")
    result = subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(final)], capture_output=True, text=True)
    (RUN_FOLDER / "assembly.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Assembly failed; see assembly.log")
    write_json(RUN_FOLDER / "timeline.json", {"clips": timeline, "duration_seconds": cursor, "final_video": str(final), "diagnostic": diagnostic})
    shutil.copyfile(RUN_FOLDER / "timeline.json", DELIVERY_FOLDER / "timeline.json")
    for name in ["understanding_contact_sheet.jpg", "cleaning_contact_sheet.jpg"]:
        if (RUN_FOLDER / name).exists():
            shutil.copyfile(RUN_FOLDER / name, DELIVERY_FOLDER / name)
    print("FINAL", final, "duration", cursor, flush=True)


def main():
    pages = pages_in_order()
    RUN_FOLDER.mkdir(parents=True, exist_ok=True)
    manifest = RUN_FOLDER / "run_manifest.json"
    if not manifest.exists():
        write_json(manifest, {"run_config": RUN_CONFIG, "pages": [p.model_dump(mode="json") for p in pages], "model_defaults": read_json(PROJECT_ROOT / "config.json"), "created_at": time.time(), "note": "User authorized this bounded end-to-end run with parallel independent model jobs."})
        for source in (PROJECT_ROOT / "prompts").glob("*"):
            target = RUN_FOLDER / "prompts" / source.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, target)
    phase = RUN_CONFIG["phase"]
    jobs = RunJobs(PROJECT_ROOT, RUN_CONFIG) if phase in {"understand", "clean", "video"} else None
    if phase == "understand":
        understand(jobs, pages)
        contact_sheet(pages, "understanding")
    elif phase == "clean":
        parallel_stage(lambda entry: clean_panel(jobs, entry), all_panels(pages))
        contact_sheet(pages, "cleaning")
    elif phase == "video":
        tasks = video_tasks(pages)
        for _, _, shot, frames, script in tasks:
            build_video_request(PROJECT_ROOT, shot, frames, script)
        parallel_stage(lambda task: generate_video(jobs, task), tasks)
    elif phase == "assemble":
        assemble(pages)
    else:
        raise ValueError("Unknown run phase")


if __name__ == "__main__":
    main()
