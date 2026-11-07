from pathlib import Path
from comic2video.provider import image_input
from comic2video.storage import read_json


def build_cleaning_request(root, panel_paths, final_video_ar):
    root = Path(root)
    config = read_json(root / "generation_research_config.json")
    schema = read_json(root / "docs" / "replicate_schemas" / "black-forest-labs_flux-2-dev.json")
    supported = schema["schema"]["components"]["schemas"]["aspect_ratio"]["enum"]
    if final_video_ar not in supported or final_video_ar in {"custom", "match_input_image"}:
        raise ValueError("Supply an explicit supported final video aspect ratio")
    if not 1 <= len(panel_paths) <= 4:
        raise ValueError("FLUX requires one to four isolated panel/reference images here")
    vignette_cleaning_prompt = (root / config["cleaning_prompt_file"]).read_text(encoding="utf-8").replace("{aspect_ratio}", final_video_ar)
    images64 = [image_input(path) for path in panel_paths]
    return {"model": config["cleaning_model"], "input": dict(config["cleaning_settings"], prompt=vignette_cleaning_prompt, aspect_ratio=final_video_ar, input_images=images64)}
