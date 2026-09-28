'''Convert a MIDI file or a community chart into a key chart for the Windsong Lyre.'''

import argparse
import ast
import math
import re

from collections import Counter
from collections.abc import Iterable
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
PITCH_OF = {k: p for p, k in KEY_OF.items()}

# Roughness of each interval class 0..6 (unison through tritone).
ROUGHNESS = (0, 1, 0.5, 0.1, 0.1, 0.1, 0.8)
GRID_DIVISIONS = (1, 2, 3, 4, 6, 8, 12, 16)
DRUM_CHANNEL = 9
LYRE_PROGRAM = 46  # General MIDI orchestral harp, the closest timbre to the lyre.
BARS_PER_PARAGRAPH = 4
MIDI_SUFFIXES = ('.mid', '.midi')

SLOT_PATTERN = rf'\([{KEYS}]+\)|[{KEYS}]| '
LOOSE_TOKEN = re.compile(rf'{SLOT_PATTERN}|[{{【\[]|[}}】\]]')
SLOT = re.compile(SLOT_PATTERN)
TEMPO_MARKER = re.compile(r'<([\d.]+)>')
BEAT_TOKEN = re.compile(rf'{TEMPO_MARKER.pattern}|{SLOT_PATTERN}')
NOTE_DELAY = Fraction('0.15')
SPACE_DELAY = Fraction('0.1')
LOOSE_TICKS_PER_BEAT = 480


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


# A pitch and the beats its key stays down, 0 for a tap.
type Key = tuple[int, Fraction]


@dataclass(frozen=True)
class Chart:
    '''Times are in beats of the time signature, on the grid chosen for each beat.'''

    events: tuple[tuple[Fraction, tuple[Key, ...]], ...]  # (time, keys in ascending pitch)
    tempos: tuple[tuple[Fraction, int], ...]  # (time, microseconds per quarter note)
    beat_ticks: int
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


def read_loose(text: str) -> Song:
    '''Read a community chart as one part of taps in 4/4.

    With fixed delays, a key takes a sixteenth note at the tempo its delay implies. From a
    tempo marker on, each separator closes a beat that splits evenly among its slots.
    '''
    tpb = LOOSE_TICKS_PER_BEAT
    notes: list[Note] = []
    tempos: list[tuple[int, int]] = []
    beats: list[tuple[int, str, int, bool]] = []  # (line, text, slots, key after the first slot)
    now = Fraction(0)  # In beats.
    note_delay, space_delay = NOTE_DELAY, SPACE_DELAY
    bpm: Fraction | None = None  # Set while reading beats.
    bar_sep = '/'
    break_after = None
    pending = ''  # The unclosed beat.

    def press(token: str, at: Fraction) -> None:
        tick = round(at * tpb)
        notes.extend(Note(tick, PITCH_OF[k], tick) for k in token.strip('()'))

    def set_tempo(at: Fraction) -> None:
        tempo = round(4 * note_delay * 1_000_000) if bpm is None else round(60_000_000 / bpm)
        tick = round(at * tpb)
        if tempos and tempos[-1][0] == tick:
            tempos.pop()
        if not tempos or tempos[-1][1] != tempo:
            tempos.append((tick, tempo))

    def read_timed(text: str) -> None:
        nonlocal now
        beat_seconds = 4 * note_delay
        depth = 0
        for bar in text.split(bar_sep):
            for token in LOOSE_TOKEN.findall(bar):
                match token:
                    case '{' | '【' | '[':
                        depth += 1
                    case '}' | '】' | ']':
                        depth = max(depth - 1, 0)
                    case ' ':
                        now += space_delay / beat_seconds
                    case _:
                        press(token, now)
                        now += (note_delay / 2 if depth else note_delay) / beat_seconds
            if break_after and break_after.fullmatch(bar):
                now += space_delay / beat_seconds

    def close_beat(beat: str, line: int) -> None:
        nonlocal now, bpm
        slots = SLOT.findall(beat)
        beats.append((line, beat, len(slots), any(s != ' ' for s in slots[1:])))
        i = 0
        for token in BEAT_TOKEN.finditer(beat):
            at = now + Fraction(i, len(slots) or 1)
            if token[1]:
                bpm = Fraction(token[1])
                set_tempo(at)
            else:
                if token[0] != ' ':
                    press(token[0], at)
                i += 1
        now += 1

    def close_pending(line: int) -> None:
        nonlocal pending
        if SLOT.search(pending):
            close_beat(pending, line)
        pending = ''

    set_tempo(now)
    number = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.partition('#')[0].strip()
        if not line:
            continue
        if line.startswith('@'):
            close_pending(number)
            match line.split(maxsplit=1):
                case ['@clear']:
                    notes.clear()
                    tempos.clear()
                    beats.clear()
                    now = Fraction(0)
                    set_tempo(now)
                case ['@bar_sep', arg]:
                    bar_sep = ast.literal_eval(arg)
                case ['@break_after', arg]:
                    if bpm is not None:
                        raise ValueError(f'line {number}: @break_after after a tempo marker')
                    break_after = re.compile(f'[{KEYS} ]{{{int(arg)}}}')
                case ['@note_delay', arg]:
                    note_delay, bpm = Fraction(arg), None
                    set_tempo(now)
                case ['@space_delay', arg]:
                    space_delay, bpm = Fraction(arg), None
                    set_tempo(now)
                case _:
                    raise ValueError(f'unknown directive: {line}')
            continue
        if bpm is None:
            marker = TEMPO_MARKER.search(line)
            split = marker.start() if marker else len(line)
            read_timed(line[:split])
            if not marker:
                continue
            line = line[split:]
        *closed, pending = (pending + line).split(bar_sep)
        for beat in closed:
            close_beat(beat, number)
    close_pending(number)

    # A beat off the common slot count most likely lost spaces in the copy, which could have
    # stood anywhere in it.
    counts = Counter(slots for _, _, slots, _ in beats)
    if counts:
        grid = counts.most_common(1)[0][0]
        if off := [f'line {n}: {t!r}' for n, t, slots, late in beats if slots != grid and late]:
            raise ValueError(f'beats off the grid of {grid} slots: {'; '.join(off)}')
    return Song(
        parts=(Part('', 0, None, tuple(notes)),),
        ticks_per_beat=tpb,
        tempos=tuple(tempos),
        time_signature=(4, 4),
    )


def is_white(pitch: int) -> bool:
    return pitch % 12 in WHITE


def fold(pitch: int, lowest: int) -> int:
    while pitch < lowest:
        pitch += 12
    while pitch > HIGHEST:
        pitch -= 12
    return pitch


def choose_transpose(notes: tuple[Note, ...], lowest: int) -> int:
    '''Minimize the notes on black keys, then the top notes of onsets outside the range, then
    all notes outside the range, then the shift.

    A black key costs more than any octave fold because resolving it changes the pitch class.
    Folding the top voice before the others keeps the melody's intervals when the song spans
    more octaves than the range.
    '''
    pitches = tuple(n.pitch for n in notes)
    tops: dict[int, int] = {}
    for n in notes:
        tops[n.tick] = max(tops.get(n.tick, n.pitch), n.pitch)

    def outside(k: int, moved: Iterable[int]) -> int:
        return sum(not lowest <= p + k <= HIGHEST for p in moved)

    def cost(k: int) -> tuple[int, int, int, int]:
        black = sum(not is_white(p + k) for p in pitches)
        return black, outside(k, tops.values()), outside(k, pitches), abs(k)

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


def choose_division(offsets: tuple[int, ...], beat: int, tolerance: int) -> int:
    '''The coarsest beat subdivision that places every offset within `tolerance` of a slot.'''
    for n in GRID_DIVISIONS:
        if all(abs(o * n - round(Fraction(o * n, beat)) * beat) <= tolerance * n for o in offsets):
            return n
    return GRID_DIVISIONS[-1]


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
    song: Song,
    max_keys: int | None = None,
    lowest: int = LOWEST,
    *,
    hold: bool = False,
    uniform: bool = False,
) -> Chart:
    '''With `hold`, a key stays down until its note ends or the key is pressed again.
    With `uniform`, every beat shares one grid.'''
    tpb = song.ticks_per_beat
    numerator, denominator = song.time_signature
    beat = tpb * 4 // denominator
    transpose = choose_transpose(song.notes, lowest)
    notes = tuple(replace(n, pitch=fold(n.pitch + transpose, lowest)) for n in song.notes)
    notes = resolve(notes, beat)
    offsets: dict[int, list[int]] = {}  # beat -> offsets in ticks of the onsets and releases
    for tick in (
        (n.tick for n in notes) if not hold else (t for n in notes for t in (n.tick, n.end))
    ):
        offsets.setdefault(tick // beat, []).append(tick % beat)
    divisions = {b: choose_division(tuple(o), beat, tpb // 32) for b, o in offsets.items()}
    if uniform:
        every = tuple(o for beat_offsets in offsets.values() for o in beat_offsets)
        divisions = dict.fromkeys(offsets, choose_division(every, beat, tpb // 32))

    def snap(tick: int) -> Fraction:
        b, offset = divmod(tick, beat)
        n = divisions.get(b, 1)
        return b + Fraction(round(Fraction(offset * n, beat)), n)

    chords: dict[Fraction, dict[int, int]] = {}  # time -> pitch -> latest end tick
    for n in notes:
        ends = chords.setdefault(snap(n.tick), {})
        ends[n.pitch] = max(ends.get(n.pitch, n.end), n.end)
    events: list[tuple[Fraction, tuple[Key, ...]]] = []
    next_press: dict[int, Fraction] = {}
    for at in sorted(chords, reverse=True):
        ends = chords[at]
        keys: list[Key] = []
        for p in thin(tuple(sorted(ends)), max_keys or len(ends)):
            release = snap(ends[p])
            release = min(release, next_press.get(p, release))
            keys.append((p, max(release - at, Fraction(0)) if hold else Fraction(0)))
            next_press[p] = at
        events.append((at, tuple(keys)))
    return Chart(
        events=tuple(reversed(events)),
        tempos=tuple((snap(tick), tempo) for tick, tempo in song.tempos),
        beat_ticks=beat,
        beats_per_bar=numerator,
        transpose=transpose,
        song=song,
    )


def bpm(tempo: int) -> str:
    return f'{round(mido.tempo2bpm(tempo), 2):g}'


def render(chart: Chart, title: str, *, human: bool = False) -> str:
    '''Write each beat as the slots of its grid, the finest one its presses, releases and
    tempo changes need.

    For a human, every beat has the slots of the finest grid in the song, and tempo changes
    are left out.
    '''
    presses: dict[Fraction, str] = {}
    releases: dict[Fraction, list[int]] = {}
    for at, keys in chart.events:
        presses[at] = ''.join(KEY_OF[p] for p, _ in keys)
        for p, length in keys:
            if length:
                releases.setdefault(at + length, []).append(p)
    tempos = sorted(dict(chart.tempos).items())  # The last tempo at one time wins.
    start = bpm(tempos[0][1])
    markers: dict[Fraction, str] = {}
    current = start
    for at, tempo in tempos if not human else ():
        if (value := bpm(tempo)) != current:
            markers[at] = f'<{value}>'
            current = value
    beats: dict[int, list[Fraction]] = {}
    for at in (*presses, *releases, *markers):
        beats.setdefault(math.floor(at), []).append(at - math.floor(at))

    def cell(at: Fraction) -> str:
        keys = ''.join(KEY_OF[p].lower() for p in sorted(releases.get(at, ())))
        keys += presses.get(at, '')
        return markers.get(at, '') + (f'({keys})' if len(keys) > 1 else keys or ' ')

    song_slots = math.lcm(*(offset.denominator for o in beats.values() for offset in o))

    def beat_text(b: int) -> str:
        n = song_slots if human else math.lcm(*(offset.denominator for offset in beats.get(b, ())))
        return ''.join(cell(b + Fraction(k, n)) for k in range(n))

    bar_count = max(beats, default=-1) // chart.beats_per_bar + 1
    lines: list[str] = []
    for bar in range(bar_count):
        if bar and bar % BARS_PER_PARAGRAPH == 0:
            lines.append('')
        first = bar * chart.beats_per_bar
        lines.append(''.join(f'{beat_text(b)}/' for b in range(first, first + chart.beats_per_bar)))

    body = '\n'.join(lines)
    numerator, denominator = chart.song.time_signature
    slot = f'one slot = {Fraction(1, song_slots * denominator)} note, ' if human else ''
    return (
        f'# {title}\n\n'
        f'{start} BPM, {numerator}/{denominator}, {slot}'
        f'transposed {chart.transpose:+d} semitones.\n\n'
        f'```\n{body}\n```\n'
    )


def write_midi(chart: Chart, path: Path) -> None:
    '''Render the chart as a harp track on the original tempo map.

    A held key sounds until its release, a tapped one rings for one beat.
    '''
    song = chart.song
    ring = song.ticks_per_beat
    starts: dict[int, list[tuple[int, int]]] = {}  # pitch -> (tick, held ticks)
    for at, keys in chart.events:
        for p, length in keys:
            starts.setdefault(p, []).append(
                (round(at * chart.beat_ticks), round(length * chart.beat_ticks))
            )

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
    source: Path,
    max_keys: int | None,
    horn: bool,
    hold: bool,
    parts: tuple[int, ...] | None,
    human: bool,
) -> Path:
    tags = ('.horn' if horn else '') + (f'.max{max_keys}' if max_keys else '')
    tags += ('.hold' if hold else '') + (f'.parts{'+'.join(map(str, parts))}' if parts else '')
    return source.with_suffix(tags + ('.human' if human else '') + '.md')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='a MIDI file or a community chart')
    parser.add_argument(
        '-o', '--output', type=Path, help='chart path, default: named after the input and options'
    )
    parser.add_argument(
        '--human', action='store_true', help='write a chart to read and play by hand'
    )
    parser.add_argument(
        '--midi', action='store_true', help='also write a MIDI preview beside the chart'
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
    source: Path = args.source
    song = (
        read_midi(source)
        if source.suffix.lower() in MIDI_SUFFIXES
        else read_loose(source.read_text(encoding='utf-8'))
    )
    if args.list_parts:
        print('\n'.join(describe(i, p) for i, p in enumerate(song.parts)))
        return
    parts: tuple[int, ...] | None = args.parts and tuple(sorted(set(args.parts)))
    if parts:
        if parts[-1] >= len(song.parts) or parts[0] < 0:
            parser.error(f'the input has parts 0 to {len(song.parts) - 1}')
        song = replace(song, parts=tuple(song.parts[i] for i in parts))
    human: bool = args.human
    if human and args.hold:
        parser.error('--hold does not apply to --human')
    lowest = HORN_LOWEST if args.horn else LOWEST
    chart = arrange(song, args.max_keys, lowest, hold=args.hold, uniform=human)
    chart_path: Path = args.output or default_chart_path(
        source, args.max_keys, args.horn, args.hold, parts, human
    )
    if chart_path.resolve() == source.resolve():
        parser.error('the chart would overwrite the input, pass -o')
    chart_path.write_text(render(chart, source.stem, human=human), encoding='utf-8')
    print(chart_path)
    if args.midi:
        preview_path = chart_path.with_suffix('.lyre.mid')
        write_midi(chart, preview_path)
        print(preview_path)


if __name__ == '__main__':
    main()
