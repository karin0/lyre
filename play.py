'''Play a key chart on the Windsong Lyre by sending key presses to the focused window.'''

import argparse
import ast
import queue
import re
import time

from fractions import Fraction
from pathlib import Path

import keyboard

# Seconds from the start, and the keys pressed together.
type Press = tuple[float, str]

HEADER = re.compile(r'([\d.]+) BPM, .* one slot = (\d+(?:/\d+)?) note')
TOKEN = re.compile(r'\([A-Z]+\)|[A-Z]| ')
LOOSE_TOKEN = re.compile(r'\([A-Z]+\)|[A-Z]| |[{【\[]|[}】\]]')
NOTE_DELAY = 0.15
SPACE_DELAY = 0.1
START_DELAY = 1  # Time to switch to the game window.
TRIGGERS = frozenset(('k', ',', 'space'))
QUIT = '`'


def parse_chart(text: str) -> tuple[Press, ...]:
    '''Time the presses of a chart written by lyre.py at the tempo on its header line.'''
    header = HEADER.search(text)
    if header is None:
        raise ValueError('chart has no tempo line')
    slot = 240 / float(header[1]) * float(Fraction(header[2]))
    tokens = TOKEN.findall(text.split('```')[1].replace('\n', ''))
    return tuple((i * slot, t.strip('()')) for i, t in enumerate(tokens) if t != ' ')


def parse_loose(text: str) -> tuple[Press, ...]:
    '''Time the presses of a community chart, which gives no durations, at fixed delays.

    Keys inside `{}`, `【】` or `[]` form a fast run at half the note delay.
    '''
    presses: list[Press] = []
    now = 0.0
    note_delay, space_delay = NOTE_DELAY, SPACE_DELAY
    bar_sep = '/'
    break_after = None
    for raw in text.splitlines():
        line = raw.partition('#')[0].strip()
        match line.split(maxsplit=1):
            case []:
                continue
            case ['@clear']:
                presses.clear()
                now = 0.0
                continue
            case ['@bar_sep', arg]:
                bar_sep = ast.literal_eval(arg)
                continue
            case ['@break_after', arg]:
                break_after = re.compile(f'[A-Z ]{{{int(arg)}}}')
                continue
            case ['@note_delay', arg]:
                note_delay = float(arg)
                continue
            case ['@space_delay', arg]:
                space_delay = float(arg)
                continue
            case [directive, *_] if directive.startswith('@'):
                raise ValueError(f'unknown directive: {line}')
            case _:
                pass
        depth = 0
        for bar in line.split(bar_sep):
            for token in LOOSE_TOKEN.findall(bar):
                match token:
                    case '{' | '【' | '[':
                        depth += 1
                    case '}' | '】' | ']':
                        depth = max(depth - 1, 0)
                    case ' ':
                        now += space_delay
                    case _:
                        presses.append((now, token.strip('()')))
                        now += note_delay / 2 if depth else note_delay
            if break_after and break_after.fullmatch(bar):
                now += space_delay
    return tuple(presses)


def send(keys: str) -> None:
    keyboard.send('+'.join(keys.lower()))


def play(presses: tuple[Press, ...]) -> None:
    start = time.monotonic() + START_DELAY
    for at, keys in presses:
        time.sleep(max(0, start + at - time.monotonic()))
        send(keys)


def step(presses: tuple[Press, ...]) -> None:
    '''Send the next press on each trigger key, ignoring the key repeat of a held trigger.'''
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
    for _, keys in presses:
        while (name := downs.get()) not in TRIGGERS:
            if name == QUIT:
                return
        send(keys)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('chart', type=Path)
    parser.add_argument(
        '--loose', action='store_true', help='read a community chart, timed by fixed delays'
    )
    parser.add_argument(
        '-k', '--step', action='store_true', help='press on each K, comma or space; ` quits'
    )
    args = parser.parse_args()
    chart: Path = args.chart
    text = chart.read_text(encoding='utf-8')
    presses = parse_loose(text) if args.loose else parse_chart(text)
    if args.step:
        step(presses)
    else:
        play(presses)


if __name__ == '__main__':
    main()
