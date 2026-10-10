"""Add beams to quavers, semiquavers and shorter notes.

The OMR step gives note values but drops the beams, so they are rebuilt here
the way engravers normally group them: one beam group per beat (a crotchet in
2/4, 3/4, 4/4 and 2/2; a dotted crotchet in 6/8, 9/8 and 12/8). A rest, a
longer note, or a note that crosses into the next beat breaks the group.
"""

import xml.etree.ElementTree as ET
from fractions import Fraction

# Note type -> how many beam lines it carries.
BEAM_LEVELS = {"eighth": 1, "16th": 2, "32nd": 3, "64th": 4}


def add_beams(root: ET.Element) -> None:
    divisions = 1
    beats, beat_type = 4, 4
    for measure in root.iter("measure"):
        for attrs in measure.findall("attributes"):
            divisions = int(attrs.findtext("divisions") or divisions)
            time = attrs.find("time")
            if time is not None:
                beats = int(time.findtext("beats"))
                beat_type = int(time.findtext("beat-type"))
        beat = _beat_length(beats, beat_type, divisions)

        groups, current, offset = [], [], Fraction(0)
        for note in measure.findall("note"):
            if note.find("chord") is not None or note.find("grace") is not None:
                continue
            duration = Fraction(int(note.findtext("duration") or 0))
            level = BEAM_LEVELS.get(note.findtext("type"), 0)
            same_beat = (offset // beat) == ((offset + duration - Fraction(1, 1000)) // beat)
            beamable = level > 0 and note.find("rest") is None and same_beat
            if beamable and current and (offset // beat) == current[-1][2]:
                current.append((note, level, offset // beat))
            else:
                groups.append(current)
                current = [(note, level, offset // beat)] if beamable else []
            offset += duration
        groups.append(current)

        for group in groups:
            if len(group) >= 2:
                _write_beams([(note, level) for note, level, _ in group])


def _beat_length(beats: int, beat_type: int, divisions: int) -> Fraction:
    quarter = Fraction(divisions)
    if beat_type == 8 and beats % 3 == 0 and beats > 3:
        return quarter * 3 / 2          # compound time: dotted crotchet
    return quarter                      # simple time: crotchet


def _write_beams(group: list[tuple[ET.Element, int]]) -> None:
    beams = [[] for _ in group]
    for number in range(1, max(level for _, level in group) + 1):
        i = 0
        while i < len(group):
            if group[i][1] < number:
                i += 1
                continue
            j = i
            while j + 1 < len(group) and group[j + 1][1] >= number:
                j += 1
            if j > i:
                beams[i].append((number, "begin"))
                for k in range(i + 1, j):
                    beams[k].append((number, "continue"))
                beams[j].append((number, "end"))
            elif number > 1:
                # A lone semiquaver next to a dotted quaver gets a short stub.
                beams[i].append((number, "forward hook" if i == 0 else "backward hook"))
            i = j + 1

    for (note, _), note_beams in zip(group, beams):
        for old in note.findall("beam"):
            note.remove(old)
        notations = note.find("notations")
        index = list(note).index(notations) if notations is not None else len(note)
        for n, (number, kind) in enumerate(note_beams):
            beam = ET.Element("beam", number=str(number))
            beam.text = kind
            note.insert(index + n, beam)
