'''Convert a MIDI file into a key chart for the Genshin Impact Windsong Lyre.'''

import argparse

from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

import mido

# White keys C3..B5 in ascending pitch, the whole range of the instrument.
KEYS = 'ZXCVBNMASDFGHJQWERTYU'
WHITE = (0, 2, 4, 5, 7, 9, 11)
LOWEST = 48
HIGHEST = 83
HORN_LOWEST = 60  # C4; the horn has only the QWERTYU and ASDFGHJ rows.
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
    end: int


@dataclass(frozen=True)
class Part:
    '''The pitched notes of one channel in one track.'''

    name: str
    channel: int
    program: int | None
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class Song:
    parts: tuple[Part, ...]
    ticks_per_beat: int
    tempos: tuple[tuple[int, int], ...]  # (tick, microseconds per quarter note), from tick 0
    time_signature: tuple[int, int]

    @property
    def notes(self) -> tuple[Note, ...]:
        return tuple(
            sorted((n for p in self.parts for n in p.notes), key=lambda n: (n.tick, n.pitch))
        )


# A pitch and the slots its key stays down, 0 for a tap.
type Key = tuple[int, int]


@dataclass(frozen=True)
class Chart:
    events: tuple[tuple[int, tuple[Key, ...]], ...]  # (slot, keys in ascending pitch)
    slot_ticks: int
    slots_per_beat: int
    beats_per_bar: int
    transpose: int
    song: Song


def read_midi(path: Path) -> Song:
    midi = mido.MidiFile(path)
    parts: list[Part] = []
    tempos: list[tuple[int, int]] = []
    signatures: list[tuple[int, tuple[int, int]]] = []
    for track in midi.tracks:
        tick = 0
        notes: dict[int, list[Note]] = {}  # channel -> notes
        programs: dict[int, int] = {}
        sounding: dict[tuple[int, int], list[int]] = {}  # (channel, pitch) -> onsets
        for msg in track:
            tick += msg.time
            match msg:
                case mido.Message(type='note_on', velocity=v, channel=c, note=pitch) if (
                    v > 0 and c != DRUM_CHANNEL
                ):
                    sounding.setdefault((c, pitch), []).append(tick)
                case mido.Message(type='note_on' | 'note_off', channel=c, note=pitch) if (
                    sounding.get((c, pitch))
                ):
                    notes.setdefault(c, []).append(Note(sounding[c, pitch].pop(0), pitch, tick))
                case mido.Message(type='program_change', channel=c, program=program):
                    programs[c] = program
                case mido.MetaMessage(type='set_tempo', tempo=tempo):
                    tempos.append((tick, tempo))
                case mido.MetaMessage(type='time_signature', numerator=n, denominator=d):
                    signatures.append((tick, (n, d)))
                case _:
                    pass
        for (c, pitch), ts in sounding.items():
            notes.setdefault(c, []).extend(Note(t, pitch, tick) for t in ts)
        parts.extend(
            Part(track.name, c, programs.get(c), tuple(sorted(notes[c], key=lambda n: n.tick)))
            for c in sorted(notes)
        )
    tempos.sort(key=lambda t: t[0])
    if not tempos or tempos[0][0] > 0:
        tempos.insert(0, (0, 500_000))  # The MIDI default of 120 BPM.
    return Song(
        parts=tuple(parts),
        ticks_per_beat=midi.ticks_per_beat,
        tempos=tuple(tempos),
        time_signature=min(signatures)[1] if signatures else (4, 4),
    )


def is_white(pitch: int) -> bool:
    return pitch % 12 in WHITE


def fold(pitch: int, lowest: int) -> int:
    while pitch < lowest:
        pitch += 12
    while pitch > HIGHEST:
        pitch -= 12
    return pitch


def choose_transpose(pitches: tuple[int, ...], lowest: int) -> int:
    '''Minimize the notes on black keys, then those outside the range, then the shift.

    A black key costs more than any octave fold because resolving it changes the pitch class.
    '''

    def cost(k: int) -> tuple[int, int, int]:
        moved = [p + k for p in pitches]
        black = sum(not is_white(p) for p in moved)
        return black, sum(not lowest <= p <= HIGHEST for p in moved), abs(k)

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
        resolved.append(replace(note, pitch=pitch))
    return tuple(resolved)


def choose_slot(ticks: tuple[int, ...], beat: int, tolerance: int) -> int:
    '''The coarsest beat subdivision that places every onset within `tolerance` of a slot.'''
    slots = [beat // n for n in GRID_DIVISIONS if beat % n == 0]
    for slot in slots:
        if all(min(t % slot, slot - t % slot) <= tolerance for t in ticks):
            return slot
    return slots[-1]


def thin(pitches: tuple[int, ...], max_keys: int) -> tuple[int, ...]:
    '''Keep the top voice, then the bass, then the inner voices that add the most harmony.

    Among inner voices, octave doublings go first, then perfect fifths above another chord
    tone, then the voices nearest the top.
    '''
    if len(pitches) <= max_keys:
        return pitches
    classes = [p % 12 for p in pitches]

    def redundancy(p: int) -> tuple[bool, bool, int]:
        return classes.count(p % 12) > 1, (p - 7) % 12 in classes, p

    inner = sorted(pitches[1:-1], key=redundancy)
    return tuple(sorted([pitches[-1], pitches[0], *inner][:max_keys]))


def arrange(
    song: Song, max_keys: int | None = None, lowest: int = LOWEST, *, hold: bool = False
) -> Chart:
    '''With `hold`, a key stays down until its note ends or the key is pressed again.'''
    tpb = song.ticks_per_beat
    numerator, denominator = song.time_signature
    beat = tpb * 4 // denominator
    transpose = choose_transpose(tuple(n.pitch for n in song.notes), lowest)
    notes = tuple(replace(n, pitch=fold(n.pitch + transpose, lowest)) for n in song.notes)
    notes = resolve(notes, beat)
    slot = choose_slot(tuple(n.tick for n in notes), beat, tpb // 32)
    chords: dict[int, dict[int, int]] = {}  # slot -> pitch -> latest end tick
    for n in notes:
        ends = chords.setdefault(round(n.tick / slot), {})
        ends[n.pitch] = max(ends.get(n.pitch, n.end), n.end)
    events: list[tuple[int, tuple[Key, ...]]] = []
    next_press: dict[int, int] = {}
    for s in sorted(chords, reverse=True):
        ends = chords[s]
        keys: list[Key] = []
        for p in thin(tuple(sorted(ends)), max_keys or len(ends)):
            release = round(ends[p] / slot)
            release = min(release, next_press.get(p, release))
            keys.append((p, max(release - s, 0) if hold else 0))
            next_press[p] = s
        events.append((s, tuple(keys)))
    return Chart(
        events=tuple(reversed(events)),
        slot_ticks=slot,
        slots_per_beat=beat // slot,
        beats_per_bar=numerator,
        transpose=transpose,
        song=song,
    )


def bpm(tempo: int) -> str:
    return f'{round(mido.tempo2bpm(tempo), 2):g}'


def render(chart: Chart, title: str) -> str:
    letters: dict[int, str] = {}
    releases: dict[int, list[int]] = {}
    for slot, keys in chart.events:
        letters[slot] = ''.join(KEY_OF[p] for p, _ in keys)
        for p, length in keys:
            if length:
                releases.setdefault(slot + length, []).append(p)
    tempos: dict[int, str] = {}
    for tick, tempo in chart.song.tempos:
        tempos[round(tick / chart.slot_ticks)] = bpm(tempo)
    markers: dict[int, str] = {}
    current = tempos[0]
    for slot, value in sorted(tempos.items()):
        if value != current:
            markers[slot] = f'<{value}>'
            current = value

    def token(slot: int) -> str:
        keys = ''.join(KEY_OF[p].lower() for p in sorted(releases.get(slot, ())))
        keys += letters.get(slot, '')
        return markers.get(slot, '') + (f'({keys})' if len(keys) > 1 else keys or ' ')

    bar_slots = chart.slots_per_beat * chart.beats_per_bar
    bar_count = max((*letters, *releases), default=-1) // bar_slots + 1
    lines: list[str] = []
    for bar in range(bar_count):
        if bar and bar % BARS_PER_PARAGRAPH == 0:
            lines.append('')
        beats = (
            ''.join(token(s) for s in range(b, b + chart.slots_per_beat))
            for b in range(bar * bar_slots, (bar + 1) * bar_slots, chart.slots_per_beat)
        )
        lines.append(''.join(f'{b}/' for b in beats))

    slot_note = Fraction(chart.slot_ticks, 4 * chart.song.ticks_per_beat)
    body = '\n'.join(lines)
    return (
        f'# {title}\n\n'
        f'{tempos[0]} BPM, {chart.song.time_signature[0]}/{chart.song.time_signature[1]}, '
        f'one slot = {slot_note} note, transposed {chart.transpose:+d} semitones.\n\n'
        f'```\n{body}\n```\n'
    )


def write_midi(chart: Chart, path: Path) -> None:
    '''Render the chart as a harp track on the original tempo map.

    A held key sounds until its release, a tapped one rings for one beat.
    '''
    song = chart.song
    ring = song.ticks_per_beat
    starts: dict[int, list[tuple[int, int]]] = {}  # pitch -> (tick, held ticks)
    for slot, keys in chart.events:
        for p, length in keys:
            starts.setdefault(p, []).append((slot * chart.slot_ticks, length * chart.slot_ticks))

    events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
        (tick, 0, mido.MetaMessage('set_tempo', tempo=tempo)) for tick, tempo in song.tempos
    ]
    numerator, denominator = song.time_signature
    events.append(
        (0, 0, mido.MetaMessage('time_signature', numerator=numerator, denominator=denominator))
    )
    events.append((0, 0, mido.Message('program_change', program=LYRE_PROGRAM)))
    for pitch, presses in starts.items():
        for (start, held), following in zip(presses, [*presses[1:], None], strict=True):
            end = start + (held or ring)
            end = end if following is None else min(end, following[0])
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


PITCH_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')


def pitch_name(pitch: int) -> str:
    return f'{PITCH_NAMES[pitch % 12]}{pitch // 12 - 1}'


def describe(index: int, part: Part) -> str:
    pitches = [n.pitch for n in part.notes]
    program = '' if part.program is None else f', program {part.program}'
    return (
        f'{index}: {part.name or '(unnamed)'}, channel {part.channel}{program}, '
        f'{len(pitches)} notes, {pitch_name(min(pitches))} to {pitch_name(max(pitches))}'
    )


def default_chart_path(
    source: Path, max_keys: int | None, horn: bool, hold: bool, parts: tuple[int, ...] | None
) -> Path:
    tags = ('.horn' if horn else '') + (f'.max{max_keys}' if max_keys else '')
    tags += ('.hold' if hold else '') + (f'.parts{'+'.join(map(str, parts))}' if parts else '')
    return source.with_suffix(f'{tags}.txt')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('midi', type=Path)
    parser.add_argument(
        '-o', '--output', type=Path, help='chart path, default: named after the input and options'
    )
    parser.add_argument(
        '--max-keys', type=int, choices=range(1, 22), metavar='N', help='keys pressed at once'
    )
    parser.add_argument('--horn', action='store_true', help='play on the horn, C4 to B5')
    parser.add_argument(
        '--hold', action='store_true', help='hold keys for the note durations, for sustaining'
    )
    parser.add_argument(
        '--parts',
        type=int,
        nargs='+',
        metavar='N',
        help='arrange only these parts, see --list-parts',
    )
    parser.add_argument(
        '--list-parts', action='store_true', help='list the parts of the input and exit'
    )
    args = parser.parse_args()
    source: Path = args.midi
    song = read_midi(source)
    if args.list_parts:
        print('\n'.join(describe(i, p) for i, p in enumerate(song.parts)))
        return
    parts: tuple[int, ...] | None = args.parts and tuple(sorted(set(args.parts)))
    if parts:
        if parts[-1] >= len(song.parts) or parts[0] < 0:
            parser.error(f'the input has parts 0 to {len(song.parts) - 1}')
        song = replace(song, parts=tuple(song.parts[i] for i in parts))
    lowest = HORN_LOWEST if args.horn else LOWEST
    chart = arrange(song, args.max_keys, lowest, hold=args.hold)
    chart_path: Path = args.output or default_chart_path(
        source, args.max_keys, args.horn, args.hold, parts
    )
    preview_path = chart_path.with_suffix('.lyre.mid')
    chart_path.write_text(render(chart, source.stem), encoding='utf-8')
    write_midi(chart, preview_path)
    print(f'{chart_path}\n{preview_path}')


if __name__ == '__main__':
    main()
