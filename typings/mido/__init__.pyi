# The subset of mido used by this project; mido ships no type information.
from pathlib import Path
from typing import Self

class Message:
    type: str
    time: int
    channel: int
    note: int
    velocity: int
    program: int
    def __init__(
        self,
        type: str,
        *,
        channel: int = ...,
        note: int = ...,
        velocity: int = ...,
        program: int = ...,
    ) -> None: ...
    def copy(self, *, time: int) -> Self: ...

class MetaMessage:
    type: str
    time: int
    tempo: int
    numerator: int
    denominator: int
    name: str
    def __init__(
        self,
        type: str,
        *,
        tempo: int = ...,
        numerator: int = ...,
        denominator: int = ...,
        name: str = ...,
    ) -> None: ...
    def copy(self, *, time: int) -> Self: ...

class MidiTrack(list[Message | MetaMessage]):
    name: str

class MidiFile:
    ticks_per_beat: int
    tracks: list[MidiTrack]
    def __init__(self, filename: Path | None = None, *, ticks_per_beat: int = ...) -> None: ...
    def save(self, filename: Path) -> None: ...

def tempo2bpm(tempo: int) -> float: ...
