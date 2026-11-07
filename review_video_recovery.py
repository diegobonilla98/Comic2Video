from comic2video.storage import read_json, write_json
from comic2video.video_recovery import recovery_plan
from run_end_to_end import RUN_CONFIG, RUN_FOLDER, DELIVERY_FOLDER


def main():
    records = [read_json(path) for path in sorted((RUN_FOLDER / "jobs" / "video").glob("*/prediction.json"))]
    plan = recovery_plan(records, RUN_CONFIG["video_recovery"])
    run = read_json(RUN_FOLDER / "video_recovery_run.json") if (RUN_FOLDER / "video_recovery_run.json").exists() else {"targets": [], "errors": []}
    timeline_path = RUN_FOLDER / "timeline.json"
    timeline = read_json(timeline_path) if timeline_path.exists() else {"clips": []}
    report = {"fallback_order": RUN_CONFIG["video_recovery"]["fallback_models"], "eligible_failures": RUN_CONFIG["video_recovery"]["eligible_failures"], "shots": plan, "recovery_run": run, "montage_rebuilt": bool(timeline["clips"]) and all(row["failure"] is None for row in timeline["clips"]), "final_movie": timeline.get("final_video"), "new_model_calls": sum(1 for path in (RUN_FOLDER / "jobs" / "video_recovery").glob("*/prediction.json"))}
    write_json(RUN_FOLDER / "video_recovery_review.json", report)
    write_json(DELIVERY_FOLDER / "video_recovery_review.json", report)
    print("Preserved successes:", sum(row["category"] == "preserve_success" for row in plan))
    print("Fallback-eligible failures:", sum(row["eligible_for_fallback"] for row in plan))
    print("Provider content blocks:", sum(row["category"] == "provider_content_block" for row in plan))


if __name__ == "__main__":
    main()
