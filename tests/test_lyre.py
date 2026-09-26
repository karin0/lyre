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
    assert lyre.choose_transpose(g_major) == 5


def test_out_of_range_is_folded_by_octaves():
    assert lyre.fold(36) == 48
    assert lyre.fold(95) == 83
    assert lyre.fold(60) == 60


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
