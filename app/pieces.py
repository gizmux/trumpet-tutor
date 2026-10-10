"""Split a page that holds several pieces into one score per piece.

homr reads a whole page as a single piece, so a page with two tunes comes back
as one long score under one (often wrong) title. Using the staff positions
homr writes, staves separated by a much bigger gap than usual start a new
piece; the MusicXML is cut at that system, and each piece's title is read
with OCR from the space above its first staff.
"""

import copy
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from statistics import median

import cv2
import numpy as np
from PIL import Image

# A gap this many times the usual gap between staves starts a new piece.
NEW_PIECE_GAP = 1.8

_ocr = None
_ocr_lock = threading.Lock()


def read_staffs(txt_path: Path) -> list[tuple[float, float]]:
    """(top, bottom) of each staff as a fraction of page height, top to bottom."""
    staffs = []
    for line in txt_path.read_text().split("\n"):
        parts = line.split()
        if len(parts) == 5:
            cy, h = float(parts[2]), float(parts[4])
            staffs.append((cy - h / 2, cy + h / 2))
    return sorted(staffs)


def group_staffs(staffs: list[tuple[float, float]]) -> list[list[int]]:
    """Indexes of the staves in each piece."""
    if len(staffs) < 3:
        return [list(range(len(staffs)))]
    gaps = [staffs[i + 1][0] - staffs[i][1] for i in range(len(staffs) - 1)]
    usual = median(gaps)
    groups = [[0]]
    for i, gap in enumerate(gaps, 1):
        if gap > NEW_PIECE_GAP * usual:
            groups.append([])
        groups[-1].append(i)
    return groups


def split_pieces(xml_text: str, image: Path, staffs_txt: Path) -> list[str]:
    """Return one MusicXML string per piece found on the page."""
    staffs = read_staffs(staffs_txt) if staffs_txt.exists() else []
    root = ET.fromstring(xml_text)
    part = root.find("part")
    systems = _systems(part)
    groups = group_staffs(staffs) if len(systems) == len(staffs) else [list(range(len(systems)))]

    page = Image.open(image).convert("L")
    pieces = []
    for n, group in enumerate(groups):
        above = staffs[groups[n - 1][-1]][1] if n > 0 else 0.0
        title = read_title(page, above, staffs[group[0]][0]) if staffs else None
        measures = [m for i in group for m in systems[i]]
        pieces.append(_build_piece(root, part, measures, title))
    return pieces


def _systems(part: ET.Element) -> list[list[ET.Element]]:
    systems = []
    for measure in part.findall("measure"):
        starts_system = any(p.get("new-system") == "yes" for p in measure.findall("print"))
        if not systems or starts_system:
            systems.append([])
        systems[-1].append(measure)
    return systems


def _build_piece(root: ET.Element, part: ET.Element, measures: list[ET.Element], title: str | None) -> str:
    """A copy of the score holding only these measures, renumbered from 1."""
    # Carry clef, key, time and divisions in force before the first measure.
    carried = {}
    for measure in part.findall("measure"):
        if measure is measures[0]:
            break
        for attrs in measure.findall("attributes"):
            for child in attrs:
                carried[child.tag] = child

    new_root = copy.deepcopy(root)
    new_part = new_root.find("part")
    for m in new_part.findall("measure"):
        new_part.remove(m)
    for number, measure in enumerate(measures, 1):
        m = copy.deepcopy(measure)
        m.set("number", str(number))
        if number == 1:
            for p in m.findall("print"):
                m.remove(p)
            present = {child.tag for attrs in m.findall("attributes") for child in attrs}
            missing = [copy.deepcopy(c) for tag, c in carried.items() if tag not in present]
            if missing:
                attrs = ET.Element("attributes")
                order = ["divisions", "key", "time", "clef"]
                attrs.extend(sorted(missing, key=lambda c: order.index(c.tag) if c.tag in order else 9))
                m.insert(0, attrs)
        new_part.append(m)

    if title:
        work = new_root.find("work")
        if work is None:
            work = ET.Element("work")
            new_root.insert(0, work)
        work_title = work.find("work-title")
        if work_title is None:
            work_title = ET.SubElement(work, "work-title")
        work_title.text = title
    return ET.tostring(new_root, encoding="unicode", xml_declaration=True)


def read_title(page: Image.Image, top: float, bottom: float) -> str | None:
    """The largest line of text between two heights (fractions of the page)."""
    w, h = page.size
    y0, y1 = int(top * h), int(bottom * h)
    if y1 - y0 < 20:
        return None
    region = np.asarray(page.crop((0, y0, w, y1)))
    region = cv2.cvtColor(np.where(region < 140, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2RGB)
    ocr = _get_ocr()
    found = ocr(region, use_det=True, use_cls=True, use_rec=True)  # flags persist between calls
    if found.boxes is None or not len(found.boxes):
        return None
    best, best_height = None, 0
    for box in found.boxes:
        x0, by0 = box.min(0).astype(int)
        x1, by1 = box.max(0).astype(int)
        # Generous padding above and below, little to the sides so a
        # neighbouring word (like a number beside the title) stays out.
        crop = region[max(0, by0 - 40):by1 + 40, max(0, x0 - 12):x1 + 12]
        # Recognising each line on its own is much more reliable for big title type.
        text = (ocr(crop, use_det=False, use_cls=False).txts or ("",))[0].strip()
        if _looks_like_title(text) and by1 - by0 > best_height:
            best, best_height = text, by1 - by0
    return best


def _looks_like_title(text: str) -> bool:
    letters = sum(c.isalpha() for c in text)
    return letters >= 4 and "=" not in text and not re.fullmatch(r"\(.*\)", text)


def _get_ocr():
    global _ocr
    with _ocr_lock:
        if _ocr is None:
            from rapidocr import RapidOCR  # installed with homr
            _ocr = RapidOCR()
    return _ocr
