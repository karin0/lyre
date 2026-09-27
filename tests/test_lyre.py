from pathlib import Path

import mido

import lyre

from lyre import Chart, Note, Song

TPB = 480


def song(notes: tuple[Note, ...]) -> Song:
    return Song(notes, TPB, ((0, 500_000),), (4, 4))


def test_key_map_covers_white_keys_c3_to_b5():
    assert lyre.KEY_OF[48] == 'Z'
    assert lyre.KEY_OF[60] == 'A'
    assert lyre.KEY_OF[71] == 'J'
    assert lyre.KEY_OF[72] == 'Q'
    assert lyre.KEY_OF[83] == 'U'
    assert len(lyre.KEY_OF) == 21


def test_g_major_moves_to_c_major():
    g_major = (55, 57, 59, 60, 62, 64, 66, 67)
    assert lyre.choose_transpose(g_major, lyre.LOWEST) == 5


def test_out_of_range_is_folded_by_octaves():
    assert lyre.fold(36, lyre.LOWEST) == 48
    assert lyre.fold(95, lyre.LOWEST) == 83
    assert lyre.fold(60, lyre.LOWEST) == 60
    assert lyre.fold(50, lyre.HORN_LOWEST) == 62


def test_accidental_takes_the_consonant_neighbour():
    # A#3 under F5: A3 forms a major third with F, B3 a tritone.
    notes = (Note(0, 58), Note(0, 77))
    assert lyre.resolve(notes, TPB) == (Note(0, 57), Note(0, 77))


def test_grid_is_the_coarsest_that_fits_every_onset():
    assert lyre.choose_slot((0, 240, 480), TPB, TPB // 32) == 240
    assert lyre.choose_slot((0, 120, 480), TPB, TPB // 32) == 120
    assert lyre.choose_slot((0, 160, 320), TPB, TPB // 32) == 160


def test_render_groups_beats_and_bars():
    chart = lyre.arrange(song((Note(0, 60), Note(0, 64), Note(240, 67), Note(4 * TPB, 72))))
    body = lyre.render(chart, 't').split('```\n')[1]
    assert body == '(AD)G/  /  /  /\nQ /  /  /  /\n'


def test_preview_midi_matches_chart(tmp_path: Path):
    chart = Chart(((0, (60, 64)), (1, (60,)), (4, (72,))), TPB, 1, 4, 0, song(()))
    path = tmp_path / 'out.mid'
    lyre.write_midi(chart, path)
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
    # A repeated key cuts off its own ring.
    assert ends[60] == [TPB, 2 * TPB]


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
    notes = tuple(Note(0, p) for p in (48, 52, 55, 60))
    assert lyre.arrange(song(notes), 2).events == ((0, (48, 60)),)


def test_black_keys_outweigh_octave_folds():
    # A G major bass line under a melody with one F sharp and one C. Shifting by 10 folds nothing
    # but puts the C on a black key; shifting by 17 folds two notes and keeps every key white.
    g_major = (50, 52, 55, 59) * 5 + (60, 64, 66, 67, 71)
    assert lyre.choose_transpose(g_major, lyre.HORN_LOWEST) == 17


def test_horn_keeps_every_key_on_the_upper_rows():
    notes = (Note(0, 43), Note(0, 67), Note(TPB, 50))
    chart = lyre.arrange(song(notes), lowest=lyre.HORN_LOWEST)
    assert all(p >= lyre.HORN_LOWEST for _, pitches in chart.events for p in pitches)


def test_default_chart_path_names_the_options():
    source = Path('dir/song.mid')
    assert lyre.default_chart_path(source, None, False) == Path('dir/song.txt')
    assert lyre.default_chart_path(source, 2, True) == Path('dir/song.horn.max2.txt')
