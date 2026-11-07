from pathlib import Path
from collections import Counter
from PIL import Image, ImageDraw, ImageOps
from comic2video.storage import read_json, write_json, digest
from run_end_to_end import PROJECT_ROOT, RUN_CONFIG, RUN_FOLDER, DELIVERY_FOLDER, pages_in_order, all_panels, understanding_path
import html
import imageio_ffmpeg
import shutil
import subprocess
import zipfile


def copy_artifact(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target.relative_to(DELIVERY_FOLDER).as_posix()


def build_review():
    timeline = read_json(RUN_FOLDER / "timeline.json")
    pages = pages_in_order()
    records = [(path, read_json(path)) for path in (RUN_FOLDER / "jobs").glob("*/*/prediction.json")]
    counts = Counter((record["stage"], record["status"]) for _, record in records)
    panel_entries = {panel["key"]: (page, panel) for _, page, panel, _ in all_panels(pages)}
    expected_panels = set(panel_entries)
    actual_panels = [key for row in timeline["clips"] for key in row["source_panels"]]
    if set(actual_panels) != expected_panels:
        raise ValueError("Timeline must cover every source panel")
    expected_order = list(panel_entries)
    positions = [expected_order.index(key) for key in actual_panels]
    if positions != sorted(positions):
        raise ValueError("Timeline panel order changed")
    previous_recovery = RUN_FOLDER / "video_recovery_review.json"
    preserved_recovery = RUN_FOLDER / "video_recovery_review_pre_fallback.json"
    if previous_recovery.exists() and not preserved_recovery.exists():
        shutil.copyfile(previous_recovery, preserved_recovery)
    recovery_run_path = RUN_FOLDER / "video_recovery_run.json"
    executed_fallback_order = read_json(recovery_run_path)["fallback_order"] if recovery_run_path.exists() else RUN_CONFIG["video_recovery"]["fallback_models"]
    recovery_rows = []
    for row in timeline["clips"]:
        original = list((RUN_FOLDER / "jobs" / "video").glob(row["shot_id"] + "_*/prediction.json"))
        fallback = read_json(RUN_FOLDER / "clips" / row["shot_id"] / "fallback_attempts.json") if (RUN_FOLDER / "clips" / row["shot_id"] / "fallback_attempts.json").exists() else []
        recovery_rows.append({"shot_id": row["shot_id"], "original_status": read_json(original[0])["status"] if original else "missing", "original_error": read_json(original[0]).get("error") if original else None, "fallback_attempts": fallback, "selected_model": (row["fallback"] or {}).get("selected_model") if row["fallback"] else None, "status": "succeeded" if row["failure"] is None else "unresolved", "generated_audio": row["generated_audio"]})
    recovery_report = {"fallback_order_used": executed_fallback_order, "fallback_order_next_run": RUN_CONFIG["video_recovery"]["fallback_models"], "safety_filters": "provider defaults; never disabled", "targets": [row["shot_id"] for row in recovery_rows if row["original_status"] in {"failed", "canceled"}], "model_calls": len([job for path, job in records if job["stage"] == "video_recovery"]), "shots": recovery_rows, "montage_rebuilt": True, "final_movie": timeline["final_video"], "placeholders": sum(row["kind"] == "failed_shot_still" for row in timeline["clips"])}
    write_json(RUN_FOLDER / "video_recovery_review.json", recovery_report)
    write_json(DELIVERY_FOLDER / "video_recovery_review.json", recovery_report)
    copy_artifact(PROJECT_ROOT / "docs" / "video_fallback_hierarchy.md", DELIVERY_FOLDER / "video_fallback_hierarchy.md")
    quality_path = RUN_FOLDER / "quality_review.json"
    quality = read_json(quality_path) if quality_path.exists() else {"reviewed": False, "known_issues": []}
    corrections = RUN_FOLDER / "agent_review_corrections.json"
    limitations = []
    if corrections.exists():
        limitations.append("Agent corrections were required for page geometry, OCR, character identity, or local shot planning; see correction receipts.")
    if not quality.get("reviewed"):
        limitations.append("Cleaned frames have not been marked as visually reviewed.")
    limitations += ["Exact generated speech, lip synchronization, voice continuity, and absence of music still require listening review."] + list(quality.get("known_issues", []))
    if any(row["failure"] for row in timeline["clips"]):
        limitations.append("Some video providers rejected shots; any unresolved shots are explicitly labeled in the timeline.")
    manifest = {"run_id": RUN_FOLDER.name, "source_order": [p.source_file for p in pages], "panel_count": len(expected_panels), "shot_count": len(timeline["clips"]), "model_jobs": [{"stage": stage, "status": status, "count": count} for (stage, status), count in sorted(counts.items())], "fully_automatic": False, "agent_reviewed": bool(quality.get("reviewed")), "limitations": limitations, "timeline": timeline, "sources": [{"file": p.source_file, "sha256": p.source_sha256} for p in pages], "project_artifacts": str(RUN_FOLDER)}
    manifest["predictions"] = [{"stage": record["stage"], "key": record["key"], "prediction_id": record.get("prediction_id"), "status": record["status"], "version": record.get("version"), "metrics": record.get("metrics"), "request": "run/" + (path.parent / "request.json").relative_to(RUN_FOLDER).as_posix(), "record": "run/" + path.relative_to(RUN_FOLDER).as_posix()} for path, record in records]
    manifest["final_video_sha256"] = digest(Path(timeline["final_video"]).read_bytes())
    manifest["panels"] = [{"panel_id": key, "source_page": page.source_file, "source_crop_sha256": digest((RUN_FOLDER / "frames" / key / "isolated_rgb.png").read_bytes()), "selected_clean_sha256": digest((RUN_FOLDER / "frames" / key / "clean.png").read_bytes()), "metadata": ["run/" + path.relative_to(RUN_FOLDER).as_posix() for path in (RUN_FOLDER / "frames" / key).glob("*.json")]} for key, (page, panel) in panel_entries.items()]
    write_json(DELIVERY_FOLDER / "traceability.json", manifest)
    movie_name = Path(timeline["final_video"]).name
    sections = []
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    sheet_rows = (len(timeline["clips"]) + 3) // 4
    sheet = Image.new("RGB", (4 * 320, sheet_rows * 205), "#dddddd")
    draw = ImageDraw.Draw(sheet)
    for number, row in enumerate(timeline["clips"]):
        shot_id = row["shot_id"]
        shot_folder = RUN_FOLDER / "clips" / shot_id
        media = Path(row["original_clip"])
        media_link = copy_artifact(media, DELIVERY_FOLDER / "clips" / (shot_id + ".mp4"))
        preview = shot_folder / "preview.jpg"
        result = subprocess.run([ffmpeg, "-y", "-ss", str(min(2, row["duration_seconds"] / 2)), "-i", str(media), "-frames:v", "1", str(preview)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Cannot extract preview: " + shot_id)
        preview_link = copy_artifact(preview, DELIVERY_FOLDER / "previews" / (shot_id + ".jpg"))
        x, y = number % 4 * 320, number // 4 * 205
        thumb = ImageOps.contain(Image.open(preview), (314, 176))
        sheet.paste(thumb, (x + 3, y + 24))
        draw.text((x + 5, y + 5), shot_id + (" BLOCKED" if row["failure"] else ""), fill="black")
        panels = []
        for key in row["source_panels"]:
            page, panel = panel_entries[key]
            original = copy_artifact(RUN_FOLDER / "frames" / key / "isolated_rgb.png", DELIVERY_FOLDER / "panels" / (key + "_source.png"))
            cleaned = copy_artifact(RUN_FOLDER / "frames" / key / "clean.png", DELIVERY_FOLDER / "panels" / (key + "_clean.png"))
            panels.append(f'<div><b>{html.escape(key)}</b><div class="pair"><a href="{original}"><img loading="lazy" src="{original}" alt="source panel"></a><a href="{cleaned}"><img loading="lazy" src="{cleaned}" alt="cleaned panel"></a></div></div>')
        dialogue = "<br>".join(html.escape(event["text"]) for event in row["dialogue"]) or "Silent / effects only in plan"
        failure = '<p class="error">' + html.escape(row["failure"]["error"]) + '</p>' if row["failure"] else ""
        sections.append(f'<article id="{shot_id}"><h2>{shot_id} · {html.escape(row["source_page"])} · {row["start_seconds"]:.1f}s</h2><p>{html.escape(row["kind"])} · {row["duration_seconds"]:.2f}s · <a href="{media_link}">Individual clip</a></p>{failure}<details><summary>Play clip</summary><video controls preload="none" poster="{preview_link}" src="{media_link}"></video></details><p>{dialogue}</p>{"".join(panels)}</article>')
    sheet.save(DELIVERY_FOLDER / "video_contact_sheet.jpg")
    page_links = []
    for index, page in enumerate(pages):
        source = copy_artifact(Path(page.source_snapshot), DELIVERY_FOLDER / "pages" / Path(page.source_file).name)
        page_links.append(f'<a href="{source}">Page {index}</a>')
    generated_count = sum(row["kind"] == "model_video" for row in timeline["clips"])
    blocked_count = sum(row["failure"] is not None for row in timeline["clips"])
    review = f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Comic2Video run review</title><style>body{{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;background:#16191d;color:#eee}}a{{color:#8fcaff}}video{{width:100%;max-height:75vh;background:#000}}article{{border-top:1px solid #555;margin-top:32px;padding:20px 0}}.pair{{display:flex;gap:12px;align-items:center}}.pair a{{width:50%}}img{{width:100%;max-height:460px;object-fit:contain;background:#ddd}}.error{{color:#ffb8a6}}summary{{cursor:pointer}}li{{margin:8px 0}}</style><h1>Comic2Video: ordered end-to-end review</h1><p>{len(pages)} pages · {len(expected_panels)} panels · {len(timeline["clips"])} shots · {generated_count} generated videos · {blocked_count} unresolved shots · {timeline["duration_seconds"]:.1f} seconds</p><video controls preload="metadata" src="{movie_name}"></video><p><a href="{movie_name}">Movie</a> · <a href="traceability.json">Traceability manifest</a> · <a href="video_recovery_review.json">Fallback results</a> · <a href="video_fallback_hierarchy.md">Fallback hierarchy</a> · <a href="trace_metadata.zip">Prompts, requests, raw responses and corrections</a> · <a href="video_contact_sheet.jpg">Video contact sheet</a></p><p>{" · ".join(page_links)}</p><h2>Run limitations</h2><ul>{"".join("<li>" + html.escape(note) + "</li>" for note in manifest["limitations"])}</ul><p>Each pair below shows the isolated source panel on the left and the selected cleaned frame on the right. Original model outputs, fallback attempts, and agent corrections are retained in the trace archive.</p>{"".join(sections)}</html>'
    (DELIVERY_FOLDER / "review.html").write_text(review, encoding="utf-8")
    with zipfile.ZipFile(DELIVERY_FOLDER / "trace_metadata.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in RUN_FOLDER.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".json", ".txt", ".log"}:
                archive.write(path, "run/" + path.relative_to(RUN_FOLDER).as_posix())
        for path in [PROJECT_ROOT / "run_end_to_end.py", PROJECT_ROOT / "recover_failed_videos.py", PROJECT_ROOT / "review_video_recovery.py", PROJECT_ROOT / "review_e2e_inputs.py", PROJECT_ROOT / "repair_e2e_frames.py", PROJECT_ROOT / "build_e2e_review.py", PROJECT_ROOT / "e2e_run_config.json", PROJECT_ROOT / "prompts" / "page_understanding.system.txt", PROJECT_ROOT / "vignette_cleaning_prompt.txt"]:
            archive.write(path, "implementation/" + path.relative_to(PROJECT_ROOT).as_posix())
        for parent in [PROJECT_ROOT / "comic2video", PROJECT_ROOT / "tests", PROJECT_ROOT / "docs"]:
            for path in parent.glob("*"):
                if path.is_file() and path.suffix in {".py", ".md"}:
                    archive.write(path, "implementation/" + path.relative_to(PROJECT_ROOT).as_posix())
        archive.write(DELIVERY_FOLDER / "traceability.json", "traceability.json")
    print("Review", DELIVERY_FOLDER / "review.html", flush=True)


if __name__ == "__main__":
    build_review()
