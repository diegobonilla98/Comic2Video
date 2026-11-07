from PIL import Image
from comic2video.contracts import Layout
import cv2
import numpy as np


def polygon_mask(polygons, width, height, excluded=()):
    mask = np.zeros((height, width), dtype=np.uint8)
    for polygon in polygons:
        points = np.rint(np.asarray(polygon)).astype(np.int32)
        cv2.fillPoly(mask, [points], 255)
    for polygon in excluded:
        cv2.fillPoly(mask, [np.rint(np.asarray(polygon)).astype(np.int32)], 0)
    return mask


def original_coordinates(layout, width, height):
    layout = layout.model_copy(deep=True)
    scale = (width / 1000, height / 1000) if layout.coordinate_system == "normalized_1000" else (1, 1)
    for panel in layout.panels:
        for polygon in [panel.layout_polygon, *panel.content_polygons, *panel.excluded_polygons]:
            for index, (x, y) in enumerate(polygon):
                x, y = x * scale[0], y * scale[1]
                if not (0 <= x <= width and 0 <= y <= height):
                    raise ValueError("Polygon lies outside source dimensions")
                polygon[index] = (min(x, width - 1), min(y, height - 1))
    layout.coordinate_system = "original_pixels"
    return Layout.model_validate(layout.model_dump())


def mask_bbox(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("Owned content mask is empty")
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def isolate(image, mask):
    rgba = np.array(image.convert("RGBA"))
    rgba[:, :, 3] = mask
    return Image.fromarray(rgba).crop(mask_bbox(mask))


def reading_order(panels, convention):
    boxes = {p.key: np.asarray(p.layout_polygon) for p in panels}

    def split(keys):
        if len(keys) < 2:
            return keys
        for axis in (1, 0):
            intervals = sorted((float(boxes[k][:, axis].min()), float(boxes[k][:, axis].max()), k) for k in keys)
            right = intervals[0][1]
            candidates = []
            for index in range(1, len(intervals)):
                gap = intervals[index][0] - right
                if gap > 0:
                    candidates.append((gap, index))
                right = max(right, intervals[index][1])
            if candidates:
                _, index = max(candidates)
                first = [v[2] for v in intervals[:index]]
                last = [v[2] for v in intervals[index:]]
                if axis == 0 and convention == "rtl":
                    first, last = last, first
                return split(first) + split(last)
        return sorted(keys, key=lambda k: (boxes[k][:, 1].min(), boxes[k][:, 0].min() * (-1 if convention == "rtl" else 1)))

    return split([p.key for p in panels])
