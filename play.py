'''Play a key chart on the Windsong Lyre by sending key presses to the focused window.'''

import argparse
import ctypes
import math
import queue
import re
import time

from collections.abc import Callable
from pathlib import Path

import keyboard

# Press and release in seconds from the start, and the key. A tap releases where it presses.
type Note = tuple[float, float, str]

HEADER = re.compile(r'([\d.]+) BPM, \d+/(\d+)')
TOKEN = re.compile(r'<([\d.]+)>|\(([A-Za-z]+)\)|([A-Za-z ])')
START_DELAY = 1  # Time to switch to the game window.
POLL = 0.02
TRIGGERS = frozenset(('k', ',', 'space'))
QUIT = '`'
VK_SCROLL = 0x91
SCROLL_SCAN = 0x46
KEYEVENTF_KEYUP = 0x2


def parse_chart(text: str) -> tuple[Note, ...]:
    '''Time the notes of a chart written by lyre.py from its header tempo and tempo markers.

    Each beat is split evenly among its slots. A lowercase key releases the key pressed
    before it, and a key pressed with no release before its next press is a tap.
    '''
    header = HEADER.search(text)
    if header is None:
        raise ValueError('chart has no tempo line')
    quarters_per_beat = 4 / int(header[2])
    bpm = float(header[1])
    now = 0.0
    notes: list[Note] = []
    held: dict[str, int] = {}  # key -> index of its latest press in notes
    for beat in text.split('```')[1].replace('\n', '').split('/'):
        tokens = TOKEN.findall(beat)
        slots = sum(1 for marker, _, _ in tokens if not marker)
        for marker, chord, single in tokens:
            if marker:
                bpm = float(marker)
                continue
            for key in chord or single.strip():
                if key.isupper():
                    held[key] = len(notes)
                    notes.append((now, now, key))
                elif (i := held.pop(key.upper(), None)) is not None:
                    notes[i] = (notes[i][0], now, key.upper())
                else:
                    raise ValueError(f'{key.upper()} released without a press')
            now += 60 / bpm * quarters_per_beat / slots
    return tuple(notes)


def timeline(notes: tuple[Note, ...]) -> list[tuple[float, int, str, bool]]:
    '''Key actions (seconds, order, key, down) sorted by time.

    At one moment, held keys release before new presses so that a key can be pressed again,
    and taps release after all presses so that a chord goes down together.
    '''
    actions: list[tuple[float, int, str, bool]] = []
    for press, release, key in notes:
        actions.append((press, 1, key, True))
        actions.append((release, 2 if release == press else 0, key, False))
    return sorted(actions)


def release(down: set[str]) -> None:
    for key in down:
        keyboard.release(key.lower())
    down.clear()


def perform(notes: tuple[Note, ...], wait: Callable[[float, set[str]], bool]) -> None:
    '''Send each key action once `wait` returns for its time, stopping when it returns False.

    `wait` receives the keys held down and may release them, and a later release of a key
    that is up is skipped.
    '''
    down: set[str] = set()
    try:
        for at, _, key, press in timeline(notes):
            if not wait(at, down):
                return
            if press:
                keyboard.press(key.lower())
                down.add(key)
            elif key in down:
                keyboard.release(key.lower())
                down.discard(key)
    finally:
        release(down)


def scroll_lock() -> bool:
    return bool(ctypes.windll.user32.GetKeyState(VK_SCROLL) & 1)


def toggle_scroll_lock() -> None:
    # keyboard.send('scroll lock') sends the extended scan code 0xE046 first, which is Ctrl+Break.
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_SCROLL, SCROLL_SCAN, 0, 0)
    user32.keybd_event(VK_SCROLL, SCROLL_SCAN, KEYEVENTF_KEYUP, 0)


def play(notes: tuple[Note, ...], playing: Callable[[], bool]) -> None:
    '''Send the notes on a clock that runs while `playing` holds, from START_DELAY before 0.

    A pause releases the held keys, and they stay up after it.
    '''
    clock = -START_DELAY
    last = time.monotonic()

    def wait(at: float, down: set[str]) -> bool:
        nonlocal clock, last
        while True:
            now = time.monotonic()
            if playing():
                clock += now - last
            else:
                release(down)
            last = now
            if clock >= at:
                return True
            time.sleep(min(at - clock, POLL))

    perform(notes, wait)


def step(notes: tuple[Note, ...]) -> None:
    '''Advance to the next press on each trigger key, ignoring the key repeat of a held trigger.

    Releases between two presses are sent with the later press, and those after the last
    press on one more trigger.
    '''
    downs: queue.SimpleQueue[str] = queue.SimpleQueue()
    held: set[str] = set()

    def on_event(event: keyboard.KeyboardEvent) -> None:
        name = event.name or ''
        if event.event_type == keyboard.KEY_UP:
            held.discard(name)
        elif name not in held:
            held.add(name)
            downs.put(name)

    keyboard.hook(on_event)
    presses = iter(sorted({press for press, _, _ in notes}))
    reached = -math.inf

    def wait(at: float, _: set[str]) -> bool:
        nonlocal reached
        while at > reached:
            while (name := downs.get()) not in TRIGGERS:
                if name == QUIT:
                    return False
            reached = next(presses, math.inf)
        return True

    perform(notes, wait)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('chart', type=Path)
    parser.add_argument(
        '-k', '--step', action='store_true', help='press on each K, comma or space; ` quits'
    )
    args = parser.parse_args()
    chart: Path = args.chart
    notes = parse_chart(chart.read_text(encoding='utf-8'))
    if args.step:
        step(notes)
    else:
        play(notes, scroll_lock)
        if scroll_lock():
            toggle_scroll_lock()


if __name__ == '__main__':
    main()
