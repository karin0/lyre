import pytest

import lyre
import play

from lyre import Chart, Song


def check(presses: tuple[play.Press, ...], expected: tuple[play.Press, ...]) -> None:
    assert [k for _, k in presses] == [k for _, k in expected]
    assert [t for t, _ in presses] == pytest.approx([t for t, _ in expected])


def test_chart_presses_follow_the_tempo_line():
    song = Song((), 480, ((0, 500_000),), (4, 4))
    chart = Chart(((0, (60, 72)), (1, (72,)), (17, (79,))), 120, 4, 4, 0, song)
    presses = play.parse_chart(lyre.render(chart, 'song'))
    # 120 BPM with a sixteenth-note slot is 0.125 s per slot.
    assert presses == ((0, 'AQ'), (0.125, 'Q'), (2.125, 'T'))


def test_chart_without_tempo_line_is_rejected():
    with pytest.raises(ValueError, match='tempo'):
        play.parse_chart('```\nA\n```\n')


def test_loose_chart_ignores_text_and_times_rests():
    check(
        play.parse_loose('第一段——————\n(AD) G/H  # 作者\n'), ((0, 'AD'), (0.25, 'G'), (0.4, 'H'))
    )


def test_loose_directives():
    text = "Z\n@clear\n@bar_sep ' '\n@break_after 2\n@note_delay 0.2\n@space_delay 0.5\nAS D\n"
    check(play.parse_loose(text), ((0, 'A'), (0.2, 'S'), (0.9, 'D')))


def test_loose_bracket_run_takes_half_delays():
    check(
        play.parse_loose('{AS}D 【(WX】]Q\n'),
        ((0, 'A'), (0.075, 'S'), (0.15, 'D'), (0.4, 'W'), (0.475, 'X'), (0.55, 'Q')),
    )


def test_loose_unknown_directive_is_rejected():
    with pytest.raises(ValueError, match='@break_if'):
        play.parse_loose('@break_if len(bar) == 4\n')
