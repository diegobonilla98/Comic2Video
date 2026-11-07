from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from comic2video.geometry import polygon_mask
from comic2video.storage import digest, write_json
import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "artifacts" / "benchmark_fixtures"
SIZE = (1100, 1400)


def rectangle(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def panel_art(canvas, source, polygon):
    x0, y0 = np.min(polygon, axis=0)
    x1, y1 = np.max(polygon, axis=0)
    artwork = ImageOps.fit(source, (x1 - x0 + 1, y1 - y0 + 1))
    image = Image.new("RGB", SIZE, "white")
    image.paste(artwork, (x0, y0))
    mask = polygon_mask([polygon], *SIZE)
    canvas.paste(image, (0, 0), Image.fromarray(mask))
    ImageDraw.Draw(canvas).line(polygon + polygon[:1], fill="black", width=5)


def persist(name, image, panels, probes, tags, source_files):
    path = OUTPUT_DIRECTORY / (name + ".png")
    image.save(path)
    for panel in panels:
        mask = polygon_mask(panel["content_polygons"], *SIZE, panel.get("excluded_polygons", []))
        mask_path = OUTPUT_DIRECTORY / f"{name}_{panel['key']}_reference_content.png"
        Image.fromarray(mask).save(mask_path)
        panel["content_mask_path"] = str(mask_path)
    return {"input_id": "synthetic_" + name, "source_file": "synthetic/" + name, "image_path": str(path), "source_sha256": digest(path.read_bytes()), "kind": "synthetic_control", "reference": {"panels": panels, "ownership_probes": probes, "tags": tags, "reading_order": None, "source_files": source_files, "notes": "Artificial layout made from supplied comic artwork; diagnostic evidence only, not natural-page generalization."}}


def main():
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    splash = Image.open(PROJECT_ROOT / "test_data" / "2" / "0.webp").convert("RGB")
    page = Image.open(PROJECT_ROOT / "test_data" / "2" / "1.webp").convert("RGB")
    first = page.crop((46, 75, 489, 481))
    second = page.crop((514, 75, 951, 480))
    third = page.crop((46, 510, 952, 818))
    inputs = []
    outer = rectangle(60, 60, 1040, 1340)
    inset = rectangle(650, 120, 1000, 510)
    image = Image.new("RGB", SIZE, "white")
    panel_art(image, splash, outer)
    ImageDraw.Draw(image).rectangle((638, 108, 1012, 522), fill="white")
    panel_art(image, second, inset)
    panels = [{"key": "outer", "polygon": outer, "content_polygons": [outer], "excluded_polygons": [rectangle(638, 108, 1012, 522)]}, {"key": "inset", "polygon": inset, "content_polygons": [inset]}]
    probes = [{"panel_key": "outer", "point": [800, 300], "owned": False}, {"panel_key": "inset", "point": [800, 300], "owned": True}, {"panel_key": "outer", "point": [300, 600], "owned": True}]
    inputs.append(persist("nested_inset", image, panels, probes, ["nested_panels"], ["2/0.webp", "2/1.webp"]))
    shapes = [[(60, 60), (450, 60), (650, 650), (60, 650)], [(490, 60), (1040, 60), (1040, 650), (690, 650)], rectangle(60, 720, 1040, 1340)]
    image = Image.new("RGB", SIZE, "white")
    for source, shape in zip([first, second, third], shapes):
        panel_art(image, source, shape)
    panels = [{"key": key, "polygon": shape, "content_polygons": [shape]} for key, shape in zip(["left", "right", "bottom"], shapes)]
    probes = [{"panel_key": "left", "point": [630, 150], "owned": False}, {"panel_key": "left", "point": [530, 600], "owned": True}, {"panel_key": "right", "point": [520, 600], "owned": False}]
    inputs.append(persist("diagonal_gutter", image, panels, probes, ["nonrectangular_panels"], ["2/1.webp"]))
    shapes = [rectangle(60, 60, 500, 650), rectangle(600, 60, 1040, 650), rectangle(60, 720, 1040, 1340)]
    image = Image.new("RGB", SIZE, "white")
    for source, shape in zip([first, second, third], shapes):
        panel_art(image, source, shape)
    fist = [(650, 125), (710, 118), (750, 153), (810, 167), (835, 215), (865, 240), (900, 300), (919, 355), (882, 406), (864, 463), (815, 499), (754, 512), (696, 482), (656, 448), (595, 432), (568, 406), (538, 360), (550, 302), (579, 273), (612, 251), (615, 195)]
    sprite_mask = polygon_mask([fist], splash.width, splash.height)
    cutout = splash.convert("RGBA")
    cutout.putalpha(Image.fromarray(sprite_mask))
    sprite = cutout.crop((530, 110, 925, 520)).resize((277, 287), Image.Resampling.LANCZOS)
    image.paste(sprite, (420, 260), sprite)
    content_fist = [(420 + (x - 530) * 277 / 395, 260 + (y - 110) * 287 / 410) for x, y in fist]
    panels = [{"key": key, "polygon": shape, "content_polygons": [shape]} for key, shape in zip(["left", "right", "bottom"], shapes)]
    panels[0]["content_polygons"].append(content_fist)
    panels[1]["excluded_polygons"] = [content_fist]
    foreground = polygon_mask([content_fist], *SIZE)
    interior = cv2.distanceTransform(foreground, cv2.DIST_L2, 3)
    interior[:, :620] = 0
    y, x = np.unravel_index(interior.argmax(), interior.shape)
    probes = [{"panel_key": "left", "point": [int(x), int(y)], "owned": True}, {"panel_key": "right", "point": [int(x), int(y)], "owned": False}, {"panel_key": "left", "point": [800, 150], "owned": False}]
    inputs.append(persist("foreground_overlap", image, panels, probes, ["foreground_crosses_panel_boundary"], ["2/0.webp", "2/1.webp"]))
    write_json(OUTPUT_DIRECTORY / "manifest.json", {"schema_version": "1.0", "inputs": inputs})
    print("Saved three controlled synthetic layouts", flush=True)


if __name__ == "__main__":
    main()
