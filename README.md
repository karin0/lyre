# lyre

`lyre.py` converts a MIDI file into a key chart for the Windsong Lyre in Genshin Impact, and renders the chart back to MIDI for listening.

```sh
uv run lyre.py song.mid                           # writes song.md and song.lyre.mid
uv run lyre.py song.mid --max-keys 2 -o easy.md   # writes easy.md and easy.lyre.mid
./check.sh                                        # ruff, pyright, pytest
```

## Instrument

The lyre has the 21 white keys C3 to B5. `QWERTYU` plays C5 to B5, `ASDFGHJ` C4 to B4, `ZXCVBNM` C3 to B3. The horn has only the upper two rows, C4 to B5.

## Chart format

A chart is a Markdown file with the song title as its heading, a line giving the tempo, time signature, slot length and transposition, and the keys in a code block. Each key, parenthesized chord, or space is one grid slot, and a space is a slot with no onset. A `/` closes every beat of the time signature, a line is one bar, and a blank line follows every four bars. With one slot per sixteenth note, the bar

```
(AQ) Q /T Q /R Q /E Q /
```

presses C4 and C5 together, then C5, G5, C5, F5, C5, E5 and C5 on the following eighth notes.

## Conversion

1. All non-drum notes are collected with their onsets. Durations are dropped because the lyre only plucks.
2. The whole song is shifted by the semitone count in -24..24 that leaves the fewest notes on black keys, then the fewest outside the range, preferring the smallest shift on remaining ties. Black keys weigh more because resolving one changes its pitch class, while an octave fold keeps it. A song that sits in one major key (or its relative minor) lands entirely on white keys this way.
3. Notes still outside the range are folded by octaves into it. The range is C3 to B5, or C4 to B5 with `--horn`.
4. Each note still on a black key moves one semitone down or up, whichever clashes less with the white-key notes whose onsets lie within one beat, weighted by time distance. The interval roughness table is `ROUGHNESS` in `lyre.py`.
5. The grid is the coarsest subdivision of the beat (1, 2, 3, 4, 6, 8, 12 or 16 slots) that puts every onset within 1/32 of a quarter note of a slot, so a straight piece gets no finer grid than it uses. Notes that fall into the same slot and key merge into one press.
6. With `--max-keys N`, a press with more than N keys keeps its top voice as the melody, then the bass, then the inner voices that add the most harmony. Among inner voices, those doubling a pitch class are removed first, then those a perfect fifth above another chord tone, then those nearest the top. Removed notes are dropped rather than delayed, so every kept note stays on its original onset.

Only the first time signature is used for bar lines.

The preview MIDI keeps the original tempo map and plays every press on a General MIDI harp, ringing for one beat or until the same key is pressed again.
