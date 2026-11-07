from pathlib import Path
from PIL import Image, ImageOps
from comic2video.contracts import Config, Page
import hashlib
import json
import re
import shutil


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_config(root):
    config = Config.model_validate(read_json(root / "config.json"))
    config.input_dir = (root / config.input_dir).resolve()
    config.artifact_dir = (root / config.artifact_dir).resolve()
    return config


def natural_key(path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(path))]


def ingest(config):
    paths = sorted((p for p in config.input_dir.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}), key=natural_key)
    pages = []
    for index, source in enumerate(paths):
        relative = source.relative_to(config.input_dir).as_posix()
        source_hash = digest(source.read_bytes())
        page_id = "page_" + digest(relative.encode() + b"\0" + source_hash.encode())[:16]
        folder = config.artifact_dir / "pages" / page_id
        folder.mkdir(parents=True, exist_ok=True)
        snapshot = folder / ("source" + source.suffix.lower())
        if not snapshot.exists():
            shutil.copyfile(source, snapshot)
        if digest(snapshot.read_bytes()) != source_hash:
            raise ValueError(f"Source snapshot was modified: {snapshot}")
        with Image.open(snapshot) as image:
            if ImageOps.exif_transpose(image).size != image.size or image.getexif().get(274, 1) != 1:
                raise ValueError(f"Normalize EXIF orientation before ingestion: {source}")
            width, height = image.size
        page = Page(page_id=page_id, sequence_index=index, source_file=relative, source_sha256=source_hash, source_snapshot=str(snapshot), width=width, height=height, reading_convention=config.reading_convention)
        write_json(folder / "page.json", page.model_dump(mode="json"))
        pages.append(page)
    if not pages:
        raise ValueError(f"No images found in {config.input_dir}")
    write_json(config.artifact_dir / "ingestion.json", {"schema_version": "1.0", "pages": [p.model_dump(mode="json") for p in pages]})
    return pages
