import pytest

import lyre
import play

from lyre import Chart, Song


def check(notes: tuple[play.Note, ...], expected: tuple[tuple[float, str], ...]) -> None:
    '''Compare taps by their press times and keys.'''
    assert all(press == release for press, release, _ in notes)
    assert [k for _, _, k in notes] == [k for _, k in expected]
    assert [t for t, _, _ in notes] == pytest.approx([t for t, _ in expected])


def test_chart_presses_follow_the_tempo_line():
    song = Song((), 480, ((0, 500_000),), (4, 4))
    chart = Chart(((0, ((60, 0), (72, 0))), (1, ((72, 0),)), (17, ((79, 0),))), 120, 4, 4, 0, song)
    notes = play.parse_chart(lyre.render(chart, 'song'))
    # 120 BPM with a sixteenth-note slot is 0.125 s per slot.
    assert notes == ((0, 0, 'A'), (0, 0, 'Q'), (0.125, 0.125, 'Q'), (2.125, 2.125, 'T'))


def test_chart_holds_and_tempo_changes_survive_rendering():
    song = Song((), 480, ((0, 500_000), (960, 250_000)), (4, 4))
    chart = Chart(((0, ((60, 2), (72, 1))), (1, ((72, 0),)), (2, ((64, 0),))), 480, 1, 4, 0, song)
    notes = play.parse_chart(lyre.render(chart, 'song'))
    # A slot is 0.5 s at 120 BPM and 0.25 s from slot 2 at 240 BPM.
    assert notes == ((0, 1, 'A'), (0, 0.5, 'Q'), (0.5, 0.5, 'Q'), (1, 1, 'D'))


def test_chart_release_without_press_is_rejected():
    with pytest.raises(ValueError, match='Q released'):
        play.parse_chart('120 BPM, 4/4, one slot = 1/4 note\n```\nA q/\n```\n')


def test_chart_without_tempo_line_is_rejected():
    with pytest.raises(ValueError, match='tempo'):
        play.parse_chart('```\nA\n```\n')


def test_loose_chart_ignores_text_and_times_rests():
    check(
        play.parse_loose('第一段——————\n(AD) G/H  # 作者\n'),
        ((0, 'A'), (0, 'D'), (0.25, 'G'), (0.4, 'H')),
    )


def test_loose_directives():
    text = "Z\n@clear\n@bar_sep ' '\n@break_after 2\n@note_delay 0.2\n@space_delay 0.5\nAS D\n"
    check(play.parse_loose(text), ((0, 'A'), (0.2, 'S'), (0.9, 'D')))


def test_loose_bracket_run_takes_half_delays():
    check(
        play.parse_loose('{AS}D 【(WX】]Q\n'),
        ((0, 'A'), (0.075, 'S'), (0.15, 'D'), (0.4, 'W'), (0.475, 'X'), (0.55, 'Q')),
    )


def test_timeline_releases_held_keys_first_and_taps_last():
    notes = ((0, 1, 'Q'), (1, 1, 'Q'), (1, 1, 'A'))
    assert [(t, k, down) for t, _, k, down in play.timeline(notes)] == [
        (0, 'Q', True),
        (1, 'Q', False),
        (1, 'A', True),
        (1, 'Q', True),
        (1, 'A', False),
        (1, 'Q', False),
    ]


def test_perform_releases_held_keys_when_stopped(monkeypatch: pytest.MonkeyPatch):
    sent: list[tuple[str, bool]] = []

    def press(key: str) -> None:
        sent.append((key, True))

    def release(key: str) -> None:
        sent.append((key, False))

    monkeypatch.setattr(play.keyboard, 'press', press)
    monkeypatch.setattr(play.keyboard, 'release', release)
    play.perform(((0, 2, 'Q'), (1, 1, 'A')), lambda at: at < 1)
    assert sent == [('q', True), ('q', False)]


def test_loose_unknown_directive_is_rejected():
    with pytest.raises(ValueError, match='@break_if'):
        play.parse_loose('@break_if len(bar) == 4\n')
