"""Repair bars that are too long because of a stray dot.

The note reader sometimes takes the two dots of a start-repeat sign |: for
the dot after the next note, which makes that bar half a beat (or so) too
long. When a bar overflows by exactly what one note's dot adds, that dot is
removed, preferring the first note of the bar. If the bar is right after an
end-repeat, the start-repeat sign that was misread is put back.
"""

import xml.etree.ElementTree as ET


def fix_stray_dots(root: ET.Element) -> None:
    divisions, beats, beat_type = 1, 4, 4
    previous = None
    for measure in root.iter("measure"):
        for attrs in measure.findall("attributes"):
            divisions = int(attrs.findtext("divisions") or divisions)
            if attrs.find("time") is not None:
                beats = int(attrs.findtext("time/beats"))
                beat_type = int(attrs.findtext("time/beat-type"))
        capacity = beats * divisions * 4 // beat_type
        notes = [n for n in measure.findall("note") if n.find("chord") is None and n.find("grace") is None]
        overflow = sum(int(n.findtext("duration") or 0) for n in notes) - capacity
        if overflow > 0:
            for i, note in enumerate(notes):
                duration = int(note.findtext("duration") or 0)
                dots = note.findall("dot")
                # One dot adds a third of a singly dotted note's length.
                if len(dots) == 1 and duration % 3 == 0 and duration // 3 == overflow:
                    note.remove(dots[0])
                    note.find("duration").text = str(duration - overflow)
                    if i == 0 and _ends_with_repeat(previous):
                        _add_start_repeat(measure)
                    break
        previous = measure


def _ends_with_repeat(measure: ET.Element | None) -> bool:
    if measure is None:
        return False
    return any(r.get("direction") == "backward" for r in measure.iter("repeat"))


def _add_start_repeat(measure: ET.Element) -> None:
    barline = ET.Element("barline", location="left")
    ET.SubElement(barline, "bar-style").text = "heavy-light"
    ET.SubElement(barline, "repeat", direction="forward")
    # A left barline goes before the notes, after any print/attributes.
    index = sum(1 for c in measure if c.tag in ("print", "attributes"))
    measure.insert(index, barline)
