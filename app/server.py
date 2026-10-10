"""Trumpet Tutor prototype server.

Upload a photo (or PDF) of trumpet sheet music; get back the score re-engraved
with the valve fingering above every note.

Pipeline: image -> homr (optical music recognition) -> MusicXML
          -> fingering.annotate_musicxml -> Verovio -> SVG
"""

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import verovio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from beaming import add_beams
from fingering import TRANSPOSE, annotate_musicxml

HERE = Path(__file__).parent
app = FastAPI(title="Trumpet Tutor")


def to_page_images(upload: Path, workdir: Path) -> list[Path]:
    """Turn an uploaded PDF or photo into one upright PNG per page."""
    if upload.suffix.lower() == ".pdf":
        subprocess.run(["pdftoppm", "-r", "300", "-png", str(upload), str(workdir / "page")], check=True)
        return sorted(workdir.glob("page*.png"))
    img = ImageOps.exif_transpose(Image.open(upload)).convert("RGB")
    out = workdir / "page-1.png"
    img.save(out)
    return [out]


def recognize(image: Path) -> str:
    """Run homr on one image and return the MusicXML it wrote."""
    result = subprocess.run(["homr", str(image)], capture_output=True, text=True, cwd=image.parent)
    xml_path = image.with_suffix(".musicxml")
    if result.returncode != 0 or not xml_path.exists():
        raise HTTPException(422, "Couldn't find any music staves in that image. "
                                 "Try a sharper, straighter photo with the page filling the frame.")
    return xml_path.read_text()


def tidy(xml_text: str) -> str:
    """Beam the short notes and name the part for trumpet instead of 'Voice'."""
    root = ET.fromstring(xml_text)
    add_beams(root)
    for name in root.iter("part-name"):
        name.text = ""
    for name in root.iter("instrument-name"):
        name.text = "Trumpet in Bb"
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def render_svg(xml_text: str) -> list[str]:
    tk = verovio.toolkit(False)
    # Set explicitly: the default lookup fails inside FastAPI's worker threads.
    tk.setResourcePath(str(Path(verovio.__file__).parent / "data"))
    tk.setOptions({
        "pageWidth": 2800,
        "scale": 40,
        "adjustPageHeight": True,
        "footer": "none",
        "spacingNonLinear": 0.7,
        "spacingLinear": 0.35,
        "svgViewBox": True,
        "breaks": "encoded",  # keep the original's line breaks
    })
    tk.loadData(xml_text)
    return [tk.renderToSVG(p) for p in range(1, tk.getPageCount() + 1)]


@app.post("/api/annotate")
def annotate(file: UploadFile = File(...), mode: str = Form("bb_trumpet")):
    if mode not in TRANSPOSE:
        raise HTTPException(400, f"mode must be one of {list(TRANSPOSE)}")
    workdir = Path(tempfile.mkdtemp(prefix="trumpet-"))
    try:
        upload = workdir / ("upload" + Path(file.filename or "x.png").suffix.lower())
        upload.write_bytes(file.file.read())
        pages = []
        for image in to_page_images(upload, workdir):
            xml, notes = annotate_musicxml(tidy(recognize(image)), mode)
            pages.append({"musicxml": xml, "svg": render_svg(xml), "notes": notes})
        return {"pages": pages}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")
