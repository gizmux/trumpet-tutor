"""Trumpet Tutor prototype server.

Upload a photo (or PDF) of trumpet sheet music; get back the score re-engraved
with the valve fingering above every note.

Pipeline: image -> homr (optical music recognition) -> MusicXML
          -> pieces.split_pieces (one score per tune on the page)
          -> fingering.annotate_musicxml -> Verovio -> SVG
"""

import logging
import shutil
import subprocess
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import verovio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from accidentals import add_accidentals
from beaming import add_beams
from fingering import FINGERINGS, TRANSPOSE, annotate_musicxml, name_of
from pieces import split_pieces

HERE = Path(__file__).parent
app = FastAPI(title="Trumpet Tutor")
log = logging.getLogger("uvicorn.error")


def to_page_images(upload: Path, workdir: Path) -> list[Path]:
    """Turn an uploaded PDF or photo into one upright PNG per page."""
    if upload.suffix.lower() == ".pdf":
        subprocess.run(["pdftoppm", "-r", "300", "-png", str(upload), str(workdir / "page")], check=True)
        return sorted(workdir.glob("page*.png"))
    img = ImageOps.exif_transpose(Image.open(upload)).convert("RGB")
    out = workdir / "page-1.png"
    img.save(out)
    return [out]


def recognize(image: Path) -> list[str]:
    """Run homr on one page image and return MusicXML for each piece on it."""
    result = subprocess.run(["homr", "--write-staff-positions", str(image)],
                            capture_output=True, text=True, cwd=image.parent)
    xml_path = image.with_suffix(".musicxml")
    if result.returncode != 0 or not xml_path.exists():
        raise HTTPException(422, "Couldn't find any music staves in that image. "
                                 "Try a sharper, straighter photo with the page filling the frame.")
    return split_pieces(xml_path.read_text(), image, image.with_suffix(".txt"))


def tidy(xml_text: str) -> str:
    """Beam the short notes, mark accidentals, and name the part for trumpet."""
    root = ET.fromstring(xml_text)
    add_beams(root)
    add_accidentals(root)
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


def note_svg(midi: int) -> str:
    """One whole note on a treble staff, all drawn at the same size."""
    name = name_of(midi)
    letter, octave = name[0], int(name[-1])
    accidental = {"#": "^", "b": "_"}.get(name[1:-1], "")
    abc = accidental + (letter.lower() if octave >= 5 else letter) + "'" * max(0, octave - 5) + "," * max(0, 4 - octave)
    tk = verovio.toolkit(False)
    tk.setResourcePath(str(Path(verovio.__file__).parent / "data"))
    tk.setOptions({
        "inputFrom": "abc",
        "adjustPageWidth": True,
        "pageHeight": 270,  # fixed, so every staff in the chart lines up
        "pageMarginTop": 60,
        "pageMarginBottom": 0,
        "pageMarginLeft": 20,
        "pageMarginRight": 20,
        "scale": 100,
        "header": "none",
        "footer": "none",
        "svgViewBox": True,
    })
    tk.loadData(f"X:1\nT:\nL:1\nK:C\n{abc}|\n")
    return tk.renderToSVG(1)


_chart = None


@app.get("/api/chart")
def chart():
    """The fingering chart: note name, fingering and the note on a staff."""
    global _chart
    if _chart is None:
        _chart = [{"note": name_of(m), "fingering": f, "svg": note_svg(m)} for m, f in sorted(FINGERINGS.items())]
    return _chart


# Jobs run in the background and the browser polls for the result, so a slow
# page never holds one HTTP request open long enough for a proxy (such as
# GitHub Codespaces port forwarding) to cut it off.
jobs: dict[str, dict] = {}


def run_job(job_id: str, upload: Path, mode: str) -> None:
    job = jobs[job_id]
    try:
        images = to_page_images(upload, upload.parent)
        pieces = []
        for n, image in enumerate(images, 1):
            job["progress"] = f"Reading page {n} of {len(images)}"
            for piece in recognize(image):
                xml, notes = annotate_musicxml(tidy(piece), mode)
                title = ET.fromstring(xml).findtext("work/work-title") or f"Piece {len(pieces) + 1}"
                pieces.append({"title": title, "page": n, "musicxml": xml,
                               "svg": render_svg(xml), "notes": notes})
        job.update(status="done", pieces=pieces)
    except HTTPException as e:
        job.update(status="error", detail=e.detail)
    except Exception as e:
        log.exception("Job %s failed", job_id)
        job.update(status="error", detail=f"Something went wrong on the server: {e}")
    finally:
        shutil.rmtree(upload.parent, ignore_errors=True)


@app.post("/api/annotate")
def annotate(file: UploadFile = File(...), mode: str = Form("bb_trumpet")):
    if mode not in TRANSPOSE:
        raise HTTPException(400, f"mode must be one of {list(TRANSPOSE)}")
    workdir = Path(tempfile.mkdtemp(prefix="trumpet-"))
    upload = workdir / ("upload" + Path(file.filename or "x.png").suffix.lower())
    upload.write_bytes(file.file.read())
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"status": "working", "progress": "Starting"}
    threading.Thread(target=run_job, args=(job_id, upload, mode), daemon=True).start()
    return {"job": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "That job no longer exists. The server may have restarted; please try again.")
    if job["status"] != "working":
        jobs.pop(job_id)
    return job


@app.get("/")
def index():
    # No caching, so a browser never runs an old page against a newer server.
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-store"})
