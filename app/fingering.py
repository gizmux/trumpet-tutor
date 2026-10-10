"""Valve fingerings for B-flat trumpet, keyed by written pitch.

Trumpet parts are written transposed, so the chart below is indexed by the
note as printed on a B-flat (or C) trumpet part. "0" means open (no valves).
"""

import xml.etree.ElementTree as ET

STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# MIDI number of the written note -> standard fingering.
# Range: F#3 (lowest note with all valves) to C6 (high C).
FINGERINGS = {
    54: "123",  # F#3 / Gb3
    55: "13",   # G3
    56: "23",   # G#3 / Ab3
    57: "12",   # A3
    58: "1",    # A#3 / Bb3
    59: "2",    # B3
    60: "0",    # C4 (middle C)
    61: "123",  # C#4 / Db4
    62: "13",   # D4
    63: "23",   # D#4 / Eb4
    64: "12",   # E4
    65: "1",    # F4
    66: "2",    # F#4 / Gb4
    67: "0",    # G4
    68: "23",   # G#4 / Ab4
    69: "12",   # A4
    70: "1",    # A#4 / Bb4
    71: "2",    # B4
    72: "0",    # C5
    73: "12",   # C#5 / Db5
    74: "1",    # D5
    75: "2",    # D#5 / Eb5
    76: "0",    # E5
    77: "1",    # F5
    78: "2",    # F#5 / Gb5
    79: "0",    # G5
    80: "23",   # G#5 / Ab5
    81: "12",   # A5
    82: "1",    # A#5 / Bb5
    83: "2",    # B5
    84: "0",    # C6 (high C)
}

NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# How many semitones to shift the printed note before looking up the fingering.
TRANSPOSE = {
    "bb_trumpet": 0,  # part written for B-flat trumpet (the usual case)
    "concert": 2,     # concert-pitch music (piano, flute, voice) played on B-flat trumpet
}


def midi_of(step: str, alter: float, octave: int) -> int:
    return 12 * (octave + 1) + STEP_SEMITONE[step] + int(round(alter))


def name_of(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def fingering_for(midi: int) -> str | None:
    return FINGERINGS.get(midi)


def annotate_musicxml(xml_text: str, mode: str = "bb_trumpet") -> tuple[str, list[dict]]:
    """Add a <fingering> above every pitched note.

    Returns the annotated MusicXML and a list of the notes found, in order.
    MusicXML <alter> already includes the key signature and any accidental
    carried through the measure, so the pitch can be read directly.
    """
    shift = TRANSPOSE[mode]
    root = ET.fromstring(xml_text)
    notes = []
    for measure in root.iter("measure"):
        for note in measure.findall("note"):
            pitch = note.find("pitch")
            if pitch is None:
                continue
            step = pitch.findtext("step")
            alter = float(pitch.findtext("alter") or 0)
            octave = int(pitch.findtext("octave"))
            midi = midi_of(step, alter, octave) + shift
            fing = fingering_for(midi)
            notes.append({
                "measure": measure.get("number"),
                "note": name_of(midi),
                "fingering": fing,
                "in_range": fing is not None,
            })
            _add_fingering(note, fing if fing is not None else "?")
    return ET.tostring(root, encoding="unicode", xml_declaration=True), notes


def _add_fingering(note: ET.Element, text: str) -> None:
    notations = note.find("notations")
    if notations is None:
        notations = ET.SubElement(note, "notations")
    technical = notations.find("technical")
    if technical is None:
        technical = ET.SubElement(notations, "technical")
    for old in technical.findall("fingering"):
        technical.remove(old)
    fing = ET.SubElement(technical, "fingering", placement="above")
    fing.text = text
