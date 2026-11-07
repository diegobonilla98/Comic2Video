from pathlib import Path
from PIL import Image
from jsonschema import Draft202012Validator
from comic2video.prompt_contracts import OUTPUT_CONTRACTS, ShotPlan, ScriptPlan
from comic2video.provider import image_input
from comic2video.storage import read_json
import json


def prompt_text(root, name):
    return (Path(root) / "prompts" / name).read_text(encoding="utf-8").strip()


def check_request(root, schema_file, payload):
    schema = read_json(Path(root) / "docs" / "replicate_schemas" / schema_file)["schema"]
    properties = schema["components"]["schemas"]["Input"]["properties"]
    if set(payload) - set(properties):
        raise ValueError("Request contains unsupported model inputs")
    Draft202012Validator(dict(schema, **{"$ref": "#/components/schemas/Input"})).validate(payload)


def build_llm_request(root, stage, context, image_paths=None):
    root = Path(root)
    if stage not in OUTPUT_CONTRACTS:
        raise ValueError("Unknown reasoning stage")
    config = read_json(root / "config.json")
    if stage != "layout" and len(context.get("panels", [])) > 3:
        raise ValueError("Use at most three neighboring panels per reasoning call")
    images = image_paths or {}
    if len(images) > 4:
        raise ValueError("Select at most four relevant visual inputs per call")
    instructions = prompt_text(root, "common.system.txt") + "\n" + prompt_text(root, stage + ".system.txt")
    data = {"context": context, "images": [{"index": i + 1, "id": key} for i, key in enumerate(images)], "output_schema": OUTPUT_CONTRACTS[stage].model_json_schema()}
    settings = dict(config["llm_settings"], max_completion_tokens=config["prompt_completion_limits"][stage])
    payload = dict(settings, system_prompt=instructions, prompt=json.dumps(data, ensure_ascii=False, separators=(",", ":")), image_input=[image_input(p) for p in images.values()])
    check_request(root, "openai_gpt-5.6-terra.json", payload)
    return {"model": config["llm_model"], "input": payload}


def parse_llm_response(stage, output):
    text = output if isinstance(output, str) else "".join(output)
    return OUTPUT_CONTRACTS[stage].model_validate_json(text)


def build_repair_request(root, stage, bad_output, validation_errors, context, image_paths=None):
    request = build_llm_request(root, stage, context, image_paths)
    original = json.loads(request["input"]["prompt"])
    original.update(invalid_output=bad_output, validation_errors=validation_errors)
    request["input"]["system_prompt"] += "\n" + prompt_text(root, "repair.system.txt")
    request["input"]["prompt"] = json.dumps(original, ensure_ascii=False, separators=(",", ":"))
    config = read_json(Path(root) / "config.json")
    request["input"]["max_completion_tokens"] = config["prompt_completion_limits"]["repair"]
    return request


def build_video_request(root, shot, frames, script):
    root = Path(root)
    config = read_json(root / "config.json")
    capabilities = read_json(root / "prompts" / "h3_lite.capabilities.json")
    if config["video_model"] != capabilities["model"]:
        raise ValueError("Selected model needs its own video serializer")
    shot = ShotPlan.model_validate(shot)
    script = ScriptPlan.model_validate(script)
    if shot.requires_review:
        raise ValueError("Resolve shot uncertainties before generation")
    texts = {item.text_id: item for item in script.texts}
    dialogue = []
    for event in shot.dialogue:
        source = texts.get(event.text_id)
        if source is None or event.text != source.text or event.speaker_id != source.speaker_id:
            raise ValueError("Shot dialogue must match source text and speaker exactly")
        if source.uncertain or source.category not in {"speech", "thought", "narration"} or source.speaker_status == "unknown":
            raise ValueError("Resolve uncertain dialogue before generation")
        if source.category in {"thought", "narration"} or source.speaker_status in {"narrator", "off_panel"}:
            if event.placement == "on_screen":
                raise ValueError("Off-screen dialogue, thought and narration cannot drive visible lip movement")
        label = f"{event.placement} {event.speaker_description}"
        dialogue.append(f"{event.start_seconds:g}-{event.end_seconds:g}s: {label} says {json.dumps(event.text, ensure_ascii=False)} ({event.delivery}).")
    if not dialogue:
        dialogue.append("No dialogue or vocalizations.")
    else:
        dialogue.append("Only these voices, in this order; natural delivery and matching lip movement for on-screen speakers only.")
    keys = [shot.first_frame_id] + ([shot.last_frame_id] if shot.last_frame_id else [])
    ratios = []
    for key in keys:
        frame = frames[key]
        if not frame.get("video_ready") or frame["panel_id"] not in shot.panel_ids:
            raise ValueError("Conditioning requires reviewed clean frames linked to this shot")
        with Image.open(frame["path"]) as image:
            if "A" in image.getbands():
                raise ValueError("Composite transparent extraction masks before conditioning video")
            ratios.append(image.width / image.height)
    if len(ratios) == 2 and abs(ratios[0] - ratios[1]) > 0.005:
        raise ValueError("First and last frames must have matching aspect ratios")
    conditioning = "Animate from the first frame to the supplied last frame." if shot.last_frame_id else "Animate the supplied first frame."
    prompt = prompt_text(root, "h3_lite.prompt.txt").format(duration=shot.duration, conditioning=conditioning, camera=shot.camera, action=shot.action, invariants=shot.invariants, dialogue=" ".join(dialogue), sound=shot.sound)
    payload = {"prompt": prompt, "first_frame_image": image_input(frames[shot.first_frame_id]["path"]), "duration": shot.duration, "resolution": config["video_settings"]["resolution"]}
    if shot.last_frame_id:
        payload["last_frame_image"] = image_input(frames[shot.last_frame_id]["path"])
    check_request(root, "minimax_h3-lite.json", payload)
    return {"model": config["video_model"], "input": payload}
