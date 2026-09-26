'''Convert a MIDI file into a key chart for the Genshin Impact Windsong Lyre.'''

import argparse

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import mido

# White keys C3..B5 in ascending pitch, the whole range of the instrument.
KEYS = 'ZXCVBNMASDFGHJQWERTYU'
WHITE = (0, 2, 4, 5, 7, 9, 11)
LOWEST = 48
HIGHEST = 83
KEY_OF = {LOWEST + 12 * (i // 7) + WHITE[i % 7]: k for i, k in enumerate(KEYS)}

# Roughness of each interval class 0..6 (unison through tritone).
ROUGHNESS = (0, 1, 0.5, 0.1, 0.1, 0.1, 0.8)
GRID_DIVISIONS = (1, 2, 3, 4, 6, 8, 12, 16)
DRUM_CHANNEL = 9
LYRE_PROGRAM = 46  # General MIDI orchestral harp, the closest timbre to the lyre.
BARS_PER_PARAGRAPH = 4


@dataclass(frozen=True)
class Note:
    tick: int
    pitch: int


@dataclass(frozen=True)
class Song:
    notes: tuple[Note, ...]
    ticks_per_beat: int
    tempos: tuple[tuple[int, int], ...]  # (tick, microseconds per quarter note)
    time_signature: tuple[int, int]


@dataclass(frozen=True)
class Chart:
    events: tuple[tuple[int, tuple[int, ...]], ...]  # (slot, ascending pitches)
    slot_ticks: int
    slots_per_beat: int
    beats_per_bar: int
    transpose: int
    song: Song


def read_midi(path: Path) -> Song:
    midi = mido.MidiFile(path)
    notes: list[Note] = []
    tempos: list[tuple[int, int]] = []
    signatures: list[tuple[int, tuple[int, int]]] = []
    for track in midi.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            match msg:
                case mido.Message(type='note_on', velocity=v, channel=c, note=pitch) if (
                    v > 0 and c != DRUM_CHANNEL
                ):
                    notes.append(Note(tick, pitch))
                case mido.MetaMessage(type='set_tempo', tempo=tempo):
                    tempos.append((tick, tempo))
                case mido.MetaMessage(type='time_signature', numerator=n, denominator=d):
                    signatures.append((tick, (n, d)))
                case _:
                    pass
    return Song(
        notes=tuple(sorted(notes, key=lambda n: (n.tick, n.pitch))),
        ticks_per_beat=midi.ticks_per_beat,
        tempos=tuple(sorted(tempos)) or ((0, 500_000),),
        time_signature=min(signatures)[1] if signatures else (4, 4),
    )


def is_white(pitch: int) -> bool:
    return pitch % 12 in WHITE


def fold(pitch: int) -> int:
    while pitch < LOWEST:
        pitch += 12
    while pitch > HIGHEST:
        pitch -= 12
    return pitch


def choose_transpose(pitches: tuple[int, ...]) -> int:
    '''Minimize the notes that land on black keys or outside the range, then the shift.'''

    def cost(k: int) -> tuple[int, int]:
        moved = [p + k for p in pitches]
        bad = sum(not is_white(p) for p in moved) + sum(not LOWEST <= p <= HIGHEST for p in moved)
        return bad, abs(k)

    return min(range(-24, 25), key=cost)


def roughness(a: int, b: int) -> float:
    ic = abs(a - b) % 12
    return ROUGHNESS[min(ic, 12 - ic)]


def clash(pitch: int, tick: int, context: list[Note], window: int) -> float:
    return sum((1 - abs(n.tick - tick) / window) * roughness(pitch, n.pitch) for n in context)


def resolve(notes: tuple[Note, ...], window: int) -> tuple[Note, ...]:
    '''Move each black-key note to the white neighbour that clashes least with nearby notes.

    Nearby notes are the white ones (original or already resolved) with onsets within
    `window` ticks, weighted linearly down to zero at the window edge.
    '''
    resolved: list[Note] = []
    for i, note in enumerate(notes):
        if is_white(note.pitch):
            resolved.append(note)
            continue
        context = [n for n in resolved if note.tick - n.tick < window] + [
            n for n in notes[i + 1 :] if n.tick - note.tick < window and is_white(n.pitch)
        ]
        pitch = min(
            (note.pitch - 1, note.pitch + 1), key=lambda p: clash(p, note.tick, context, window)
        )
        resolved.append(Note(note.tick, pitch))
    return tuple(resolved)


def choose_slot(ticks: tuple[int, ...], beat: int, tolerance: int) -> int:
    '''The coarsest beat subdivision that places every onset within `tolerance` of a slot.'''
    slots = [beat // n for n in GRID_DIVISIONS if beat % n == 0]
    for slot in slots:
        if all(min(t % slot, slot - t % slot) <= tolerance for t in ticks):
            return slot
    return slots[-1]


def arrange(song: Song) -> Chart:
    tpb = song.ticks_per_beat
    numerator, denominator = song.time_signature
    beat = tpb * 4 // denominator
    transpose = choose_transpose(tuple(n.pitch for n in song.notes))
    notes = tuple(Note(n.tick, fold(n.pitch + transpose)) for n in song.notes)
    notes = resolve(notes, beat)
    slot = choose_slot(tuple(n.tick for n in notes), beat, tpb // 32)
    chords: dict[int, set[int]] = {}
    for n in notes:
        chords.setdefault(round(n.tick / slot), set()).add(n.pitch)
    return Chart(
        events=tuple((s, tuple(sorted(chords[s]))) for s in sorted(chords)),
        slot_ticks=slot,
        slots_per_beat=beat // slot,
        beats_per_bar=numerator,
        transpose=transpose,
        song=song,
    )


def render(chart: Chart, title: str) -> str:
    tokens: dict[int, str] = {}
    for slot, pitches in chart.events:
        keys = ''.join(KEY_OF[p] for p in pitches)
        tokens[slot] = keys if len(keys) == 1 else f'({keys})'
    bar_slots = chart.slots_per_beat * chart.beats_per_bar
    bar_count = chart.events[-1][0] // bar_slots + 1 if chart.events else 0
    lines: list[str] = []
    for bar in range(bar_count):
        if bar and bar % BARS_PER_PARAGRAPH == 0:
            lines.append('')
        beats = (
            ''.join(tokens.get(s, ' ') for s in range(b, b + chart.slots_per_beat))
            for b in range(bar * bar_slots, (bar + 1) * bar_slots, chart.slots_per_beat)
        )
        lines.append(''.join(f'{b}/' for b in beats))

    bpm = round(mido.tempo2bpm(chart.song.tempos[0][1]), 2)
    slot_note = Fraction(chart.slot_ticks, 4 * chart.song.ticks_per_beat)
    body = '\n'.join(lines)
    return (
        f'# {title}\n\n'
        f'{bpm:g} BPM, {chart.song.time_signature[0]}/{chart.song.time_signature[1]}, '
        f'one slot = {slot_note} note, transposed {chart.transpose:+d} semitones.\n\n'
        f'```\n{body}\n```\n'
    )


def write_midi(chart: Chart, path: Path) -> None:
    '''Render the chart as a harp track on the original tempo map, one beat of ring per note.'''
    song = chart.song
    ring = song.ticks_per_beat
    starts: dict[int, list[int]] = {}
    for slot, pitches in chart.events:
        for p in pitches:
            starts.setdefault(p, []).append(slot * chart.slot_ticks)

    events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
        (tick, 0, mido.MetaMessage('set_tempo', tempo=tempo)) for tick, tempo in song.tempos
    ]
    numerator, denominator = song.time_signature
    events.append(
        (0, 0, mido.MetaMessage('time_signature', numerator=numerator, denominator=denominator))
    )
    events.append((0, 0, mido.Message('program_change', program=LYRE_PROGRAM)))
    for pitch, ticks in starts.items():
        for start, following in zip(ticks, [*ticks[1:], None], strict=True):
            end = start + ring if following is None else min(start + ring, following)
            events.append((start, 2, mido.Message('note_on', note=pitch, velocity=80)))
            events.append((end, 1, mido.Message('note_off', note=pitch)))

    track = mido.MidiTrack()
    now = 0
    for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        track.append(msg.copy(time=tick - now))
        now = tick
    midi = mido.MidiFile(ticks_per_beat=song.ticks_per_beat)
    midi.tracks.append(track)
    midi.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('midi', type=Path)
    args = parser.parse_args()
    source: Path = args.midi
    chart = arrange(read_midi(source))
    chart_path = source.with_suffix('.md')
    preview_path = source.with_suffix('.lyre.mid')
    chart_path.write_text(render(chart, source.stem), encoding='utf-8')
    write_midi(chart, preview_path)
    print(f'{chart_path}\n{preview_path}')


if __name__ == '__main__':
    main()
