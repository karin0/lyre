from fractions import Fraction
from pathlib import Path

import mido
import pytest

import lyre
import play

from lyre import Chart, Note, Part, Song

TPB = 480


def song(notes: tuple[Note, ...], tempos: tuple[tuple[int, int], ...] = ((0, 500_000),)) -> Song:
    return Song((Part('', 0, None, notes),), TPB, tempos, (4, 4))


def tap(tick: int, pitch: int) -> Note:
    return Note(tick, pitch, tick + TPB // 4)


def chart(
    events: tuple[tuple[Fraction | int, tuple[tuple[int, Fraction | int], ...]], ...],
    tempos: tuple[tuple[Fraction | int, int], ...] = ((0, 500_000),),
) -> Chart:
    return Chart(
        tuple((Fraction(at), tuple((p, Fraction(n)) for p, n in keys)) for at, keys in events),
        tuple((Fraction(at), tempo) for at, tempo in tempos),
        TPB,
        4,
        0,
        song(()),
    )


def test_key_map_covers_white_keys_c3_to_b5():
    assert lyre.KEY_OF[48] == 'Z'
    assert lyre.KEY_OF[60] == 'A'
    assert lyre.KEY_OF[71] == 'J'
    assert lyre.KEY_OF[72] == 'Q'
    assert lyre.KEY_OF[83] == 'U'
    assert len(lyre.KEY_OF) == 21


def test_g_major_moves_to_c_major():
    g_major = tuple(tap(i * TPB, p) for i, p in enumerate((55, 57, 59, 60, 62, 64, 66, 67)))
    assert lyre.choose_transpose(g_major, lyre.LOWEST) == 5


def test_out_of_range_is_folded_by_octaves():
    assert lyre.fold(36, lyre.LOWEST) == 48
    assert lyre.fold(95, lyre.LOWEST) == 83
    assert lyre.fold(60, lyre.LOWEST) == 60
    assert lyre.fold(50, lyre.HORN_LOWEST) == 62


def test_accidental_takes_the_consonant_neighbour():
    # A#3 under F5: A3 forms a major third with F, B3 a tritone.
    notes = (tap(0, 58), tap(0, 77))
    assert lyre.resolve(notes, TPB) == (tap(0, 57), tap(0, 77))


def test_grid_is_the_coarsest_that_fits_every_onset():
    assert lyre.choose_division((0, 240), TPB, TPB // 32) == 2
    assert lyre.choose_division((0, 120), TPB, TPB // 32) == 4
    assert lyre.choose_division((0, 160, 320), TPB, TPB // 32) == 3
    assert lyre.choose_division((5, 470), TPB, TPB // 32) == 1


def test_each_beat_gets_its_own_grid():
    notes = (tap(0, 60), tap(0, 64), tap(240, 67), tap(TPB + 160, 65), tap(4 * TPB, 72))
    body = lyre.render(lyre.arrange(song(notes)), 't').split('```\n')[1]
    assert body == '(AD)G/ F / / /\nQ/ / / /\n'


def test_human_chart_shares_one_grid_and_leaves_out_tempo_changes():
    notes = (tap(0, 60), tap(0, 64), tap(240, 67), tap(TPB + 160, 65), tap(4 * TPB, 72))
    chart = lyre.arrange(song(notes, ((0, 500_000), (TPB, 400_000))), uniform=True)
    text = lyre.render(chart, 't', human=True)
    assert text.split('\n')[2] == '120 BPM, 4/4, one slot = 1/24 note, transposed +0 semitones.'
    assert (
        text.split('```\n')[1] == '(AD)  G  /  F   /      /      /\nQ     /      /      /      /\n'
    )


def test_preview_midi_matches_chart(tmp_path: Path):
    path = tmp_path / 'out.mid'
    lyre.write_midi(chart(((0, ((60, 0), (64, 3))), (1, ((60, 0),)), (4, ((72, 0),)))), path)
    tick = 0
    starts: list[tuple[int, int]] = []
    ends: dict[int, list[int]] = {}
    for msg in mido.MidiFile(path).tracks[0]:
        tick += msg.time
        match msg:
            case mido.Message(type='note_on', note=pitch):
                starts.append((tick, pitch))
            case mido.Message(type='note_off', note=pitch):
                ends.setdefault(pitch, []).append(tick)
            case _:
                pass
    assert sorted(starts) == [(0, 60), (0, 64), (TPB, 60), (4 * TPB, 72)]
    # A repeated key cuts off its own ring, and a held key sounds until its release.
    assert ends[60] == [TPB, 2 * TPB]
    assert ends[64] == [3 * TPB]


def test_thin_keeps_outer_voices():
    assert lyre.thin((52, 57, 60), 2) == (52, 60)
    assert lyre.thin((57, 60, 72), 2) == (57, 72)
    assert lyre.thin((52, 57, 60), 1) == (60,)
    assert lyre.thin((60, 64), 2) == (60, 64)


def test_thin_drops_doublings_then_fifths():
    # C3 E3 G3 C4 E4: E3 and C4 are doublings, the one nearer the top goes first.
    assert lyre.thin((48, 52, 55, 60, 64), 4) == (48, 52, 55, 64)
    assert lyre.thin((48, 55, 57, 64), 3) == (48, 57, 64)


def test_max_keys_caps_every_press():
    notes = tuple(tap(0, p) for p in (48, 52, 55, 60))
    assert lyre.arrange(song(notes), 2).events == ((0, ((48, 0), (60, 0))),)


def test_black_keys_outweigh_octave_folds():
    # A G major bass line under a melody with one F sharp and one C. Shifting by 10 folds nothing
    # but puts the C on a black key; shifting by 17 folds two notes and keeps every key white.
    pitches = (50, 52, 55, 59) * 5 + (60, 64, 66, 67, 71)
    g_major = tuple(tap(i * TPB, p) for i, p in enumerate(pitches))
    assert lyre.choose_transpose(g_major, lyre.HORN_LOWEST) == 17


@pytest.mark.parametrize('length', [0, TPB // 4])
def test_horn_folds_the_accompaniment_before_the_melody(length: int):
    # A melody over C4..B5 above a C3 triad at every onset, also as the zero-length taps of a
    # community chart. Shifting by 12 would fold fewer notes but split the melody at C5.
    melody = (60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83)
    notes = tuple(
        Note(i * TPB, p, i * TPB + length)
        for i, top in enumerate(melody)
        for p in (48, 52, 55, top)
    )
    assert lyre.choose_transpose(notes, lyre.HORN_LOWEST) == 0


def test_held_melody_folds_after_the_arpeggio_under_it():
    # Each melody note of C5..C6 is held for a beat over an arpeggio of G2, B2 and D3. Counting
    # the arpeggio as the top of its onsets would shift by 12 and fold most of the melody.
    melody = (72, 74, 76, 77, 79, 81, 83, 84)
    notes = tuple(
        n
        for i, top in enumerate(melody)
        for n in (
            Note(i * TPB, top, (i + 1) * TPB),
            *(tap(i * TPB + j * TPB // 4, p) for j, p in enumerate((43, 47, 50), 1)),
        )
    )
    assert lyre.choose_transpose(notes, lyre.LOWEST) == -12


def test_horn_keeps_every_key_on_the_upper_rows():
    notes = (tap(0, 43), tap(0, 67), tap(TPB, 50))
    chart = lyre.arrange(song(notes), lowest=lyre.HORN_LOWEST)
    assert all(p >= lyre.HORN_LOWEST for _, keys in chart.events for p, _ in keys)


def test_default_chart_path_names_the_options():
    source = Path('dir/song.mid')
    assert lyre.default_chart_path(source, None, False, False, None, False) == Path('dir/song.md')
    assert lyre.default_chart_path(source, 2, True, False, (0, 6), True) == Path(
        'dir/song.horn.max2.parts0+6.human.md'
    )


def test_read_midi_pairs_note_ends_and_starts_at_the_default_tempo(tmp_path: Path):
    messages = (
        (0, mido.Message('note_on', note=60, velocity=80)),
        (TPB, mido.MetaMessage('set_tempo', tempo=400_000)),
        (0, mido.Message('note_on', note=64, velocity=80)),
        (TPB, mido.Message('note_off', note=60)),
        (0, mido.Message('note_on', note=64, velocity=0)),
        (0, mido.Message('note_on', note=67, velocity=80)),
    )
    track = mido.MidiTrack(msg.copy(time=delta) for delta, msg in messages)
    midi = mido.MidiFile(ticks_per_beat=TPB)
    midi.tracks.append(track)
    path = tmp_path / 'in.mid'
    midi.save(path)
    result = lyre.read_midi(path)
    # A note left sounding ends with its track.
    assert result.notes == (
        Note(0, 60, 2 * TPB),
        Note(TPB, 64, 2 * TPB),
        Note(2 * TPB, 67, 2 * TPB),
    )
    assert result.tempos == ((0, 500_000), (TPB, 400_000))


def test_parts_split_tracks_and_channels_without_drums(tmp_path: Path):
    midi = mido.MidiFile(ticks_per_beat=TPB)
    midi.tracks.append(mido.MidiTrack([mido.Message('note_on', note=60, velocity=80)]))
    midi.tracks.append(
        mido.MidiTrack(
            [
                mido.MetaMessage('track_name', name='Band'),
                mido.Message('program_change', channel=3, program=40),
                mido.Message('note_on', channel=3, note=72, velocity=80),
                mido.Message('note_on', channel=1, note=48, velocity=80),
                mido.Message('note_on', channel=9, note=36, velocity=80),
            ]
        )
    )
    path = tmp_path / 'in.mid'
    midi.save(path)
    parts = lyre.read_midi(path).parts
    assert [(p.name, p.channel, p.program) for p in parts] == [
        ('', 0, None),
        ('Band', 1, None),
        ('Band', 3, 40),
    ]
    assert lyre.describe(2, parts[2]) == '2: Band, channel 3, program 40, 1 notes, C5 to C5'


def test_hold_keeps_keys_down_until_the_note_ends_or_the_key_repeats():
    notes = (
        Note(0, 60, 2 * TPB),
        Note(0, 72, 4 * TPB),
        Note(TPB, 72, 3 * TPB),
        Note(TPB, 64, TPB + 10),
    )
    # C4 holds two beats, C5 is cut by its repeat, and E4 ends within the grid tolerance.
    assert lyre.arrange(song(notes), hold=True).events == (
        (0, ((60, 2), (72, 1))),
        (1, ((64, 0), (72, 2))),
    )
    assert lyre.arrange(song(notes)).events == ((0, ((60, 0), (72, 0))), (1, ((64, 0), (72, 0))))


def test_render_writes_releases_and_tempo_changes():
    tempos = ((0, 500_000), (1, 500_000), (Fraction(5, 2), 400_000))
    text = lyre.render(chart(((0, ((60, 2), (72, 1))), (1, ((72, 0),))), tempos), 't')
    assert text.split('```\n')[1] == '(AQ)/(qQ)/a<150> / /\n'
    assert text.split('\n')[2].startswith('120 BPM,')


def test_cli_writes_the_preview_only_with_midi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    midi = mido.MidiFile(ticks_per_beat=TPB)
    midi.tracks.append(mido.MidiTrack([mido.Message('note_on', note=60, velocity=80)]))
    midi.save(tmp_path / 'in.mid')
    for argv in (['in.mid', '--human'], ['in.mid', '--midi']):
        monkeypatch.setattr('sys.argv', ['lyre.py', str(tmp_path / argv[0]), *argv[1:]])
        lyre.main()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        'in.human.md',
        'in.lyre.mid',
        'in.md',
        'in.mid',
    ]


def loose(text: str) -> list[tuple[Fraction, str]]:
    '''Onsets in beats and keys of a community chart, which holds only taps.'''
    song = lyre.read_loose(text)
    tpb = song.ticks_per_beat
    assert all(n.end == n.tick for n in song.notes)
    return [(Fraction(n.tick, tpb), lyre.KEY_OF[n.pitch]) for n in song.notes]


def test_loose_key_is_a_sixteenth_at_the_tempo_of_its_delay():
    # 0.15 s per key makes a beat 0.6 s, and a space of 0.1 s is 1/6 beat.
    assert loose('第一段OIL——————\n(AD) G/H  # 作者\n') == [
        (0, 'A'),
        (0, 'D'),
        (Fraction(5, 12), 'G'),
        (Fraction(2, 3), 'H'),
    ]
    assert lyre.read_loose('A').tempos == ((0, 600_000),)


def test_loose_directives():
    text = "Z\n@clear\n@bar_sep ' '\n@break_after 2\n@note_delay 0.2\n@space_delay 0.5\nAS D\n"
    # A beat of 0.8 s puts D at 0.9 s.
    assert loose(text) == [(0, 'A'), (Fraction(1, 4), 'S'), (Fraction(9, 8), 'D')]
    assert lyre.read_loose(text).tempos == ((0, 800_000),)


def test_loose_bracket_run_takes_half_delays():
    assert loose('{AS}D 【(WX】]Q\n') == [
        (0, 'A'),
        (Fraction(1, 8), 'S'),
        (Fraction(1, 4), 'D'),
        (Fraction(2, 3), 'W'),
        (Fraction(19, 24), 'X'),
        (Fraction(11, 12), 'Q'),
    ]


def test_loose_unknown_directive_is_rejected():
    with pytest.raises(ValueError, match='@break_if'):
        lyre.read_loose('@break_if len(bar) == 4\n')


def test_loose_beats_after_a_tempo_marker_split_evenly_across_lines():
    # A beat holding only a key on its first slot is a rest, whatever its slot count.
    text = '<120>(AQ) Q /T{QR}E/\n(NH)/G Q\nH/\n'
    assert loose(text) == [
        (0, 'A'),
        (0, 'Q'),
        (Fraction(1, 2), 'Q'),
        (1, 'T'),
        (Fraction(5, 4), 'Q'),
        (Fraction(3, 2), 'R'),
        (Fraction(7, 4), 'E'),
        (2, 'N'),
        (2, 'H'),
        (3, 'G'),
        (Fraction(7, 2), 'Q'),
        (Fraction(15, 4), 'H'),
    ]
    assert lyre.read_loose(text).tempos == ((0, 500_000),)


def test_loose_beat_that_lost_spaces_is_rejected():
    with pytest.raises(ValueError, match=r"line 3: '\(YZN\)C '"):
        lyre.read_loose('<73>(TZ) B /(EA)   /\n(YZN)\nC /N M /\n')


def test_loose_tempo_marker_changes_the_tempo_at_its_slot():
    text = '<60>A <120>B /<90>  C /\n'
    assert loose(text) == [(0, 'A'), (Fraction(1, 2), 'B'), (Fraction(3, 2), 'C')]
    assert lyre.read_loose(text).tempos == ((0, 1_000_000), (240, 500_000), (TPB, 666_667))


def test_loose_switches_between_beats_and_delays():
    # At the default 100 BPM, a key takes a quarter of a beat.
    text = 'AB<120>C /\n@note_delay 0.25\nDE\n'
    assert loose(text) == [
        (0, 'A'),
        (Fraction(1, 4), 'B'),
        (Fraction(1, 2), 'C'),
        (Fraction(3, 2), 'D'),
        (Fraction(7, 4), 'E'),
    ]
    assert lyre.read_loose(text).tempos == ((0, 600_000), (240, 500_000), (720, 1_000_000))
    with pytest.raises(ValueError, match='@break_after'):
        lyre.read_loose('<120>A/\n@break_after 4\n')


def test_cli_converts_a_community_chart_to_its_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / 'in.sh').write_text('(AD) G/H\n', encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['lyre.py', str(tmp_path / 'in.sh')])
    lyre.main()
    notes = play.parse_chart((tmp_path / 'in.md').read_text(encoding='utf-8'))
    assert [(k, t) for t, _, k in notes] == [
        ('A', 0),
        ('D', 0),
        ('G', pytest.approx(0.25)),
        ('H', pytest.approx(0.4)),
    ]


def test_cli_refuses_to_overwrite_the_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / 'in.md').write_text('A\n', encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['lyre.py', str(tmp_path / 'in.md')])
    with pytest.raises(SystemExit):
        lyre.main()
    assert (tmp_path / 'in.md').read_text(encoding='utf-8') == 'A\n'
