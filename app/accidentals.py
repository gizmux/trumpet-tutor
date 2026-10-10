"""Mark which notes need a printed sharp, flat or natural.

homr writes each note's true pitch (<alter>) but not the <accidental> sign,
and Verovio only draws the signs that are marked. So the usual engraving rule
is applied here: a note gets a sign when its pitch differs from what the key
signature, or an earlier accidental in the same bar, already implies.
"""

import xml.etree.ElementTree as ET

SHARP_ORDER = "FCGDAEB"
SIGNS = {-2: "flat-flat", -1: "flat", 0: "natural", 1: "sharp", 2: "double-sharp"}


def add_accidentals(root: ET.Element) -> None:
    key = {}
    for measure in root.iter("measure"):
        for attrs in measure.findall("attributes"):
            fifths = attrs.findtext("key/fifths")
            if fifths is not None:
                key = _key_alters(int(fifths))
        in_bar = {}  # (step, octave) -> alter set by an accidental earlier in this bar
        for note in measure.findall("note"):
            pitch = note.find("pitch")
            if pitch is None:
                continue
            step, octave = pitch.findtext("step"), pitch.findtext("octave")
            alter = int(round(float(pitch.findtext("alter") or 0)))
            expected = in_bar.get((step, octave), key.get(step, 0))
            for old in note.findall("accidental"):
                note.remove(old)
            if alter != expected:
                _insert_accidental(note, SIGNS.get(alter, "natural"))
                in_bar[(step, octave)] = alter


def _key_alters(fifths: int) -> dict[str, int]:
    if fifths >= 0:
        return {step: 1 for step in SHARP_ORDER[:fifths]}
    return {step: -1 for step in SHARP_ORDER[::-1][:-fifths]}


def _insert_accidental(note: ET.Element, sign: str) -> None:
    # MusicXML order: ... type, dot, accidental, time-modification, stem ...
    children = list(note)
    index = max((i for i, c in enumerate(children) if c.tag in ("type", "dot")), default=len(children) - 1) + 1
    accidental = ET.Element("accidental")
    accidental.text = sign
    note.insert(index, accidental)
