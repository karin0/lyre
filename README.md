# lyre

`lyre.py` converts a MIDI file into a key chart for the Windsong Lyre in Genshin Impact, and renders the chart back to MIDI for listening. `play.py` plays a chart in the game.

```sh
uv run lyre.py song.mid                             # writes song.txt and song.lyre.mid
uv run lyre.py song.mid --horn --max-keys 2 --hold  # writes song.horn.max2.hold.txt and song.horn.max2.hold.lyre.mid
uv run lyre.py song.mid --max-keys 2 -o easy.txt    # writes easy.txt and easy.lyre.mid
uv run lyre.py song.mid --list-parts                # lists the parts to pick with --parts
uv run lyre.py song.mid --parts 0 5                 # writes song.parts0+5.txt and song.parts0+5.lyre.mid
uv run play.py song.txt                             # plays song.txt in the focused window
./check.sh                                          # ruff, pyright, pytest
```

## Instrument

The lyre has the 21 white keys C3 to B5. `QWERTYU` plays C5 to B5, `ASDFGHJ` C4 to B4, `ZXCVBNM` C3 to B3. The horn has only the upper two rows, C4 to B5. The lyre plucks, while the horn sounds for as long as a key is held, and each held key releases on its own.

## Chart format

A chart is a text file in Markdown, with the song title as its heading, a line giving the starting tempo, time signature and transposition, and the keys in a code block. A `/` closes every beat of the time signature, a line is one bar, and a blank line follows every four bars. Each key, parenthesized chord, or space is one slot, and a space is a slot with nothing pressed. A beat is split evenly among its slots, so each beat has its own grid. An uppercase letter presses a key. A lowercase letter releases that key, which stays down from its press until then, and a press with no release before the next press of the same key is a tap. In a slot, releases come before presses. A marker such as `<150>` before a slot sets the tempo in BPM, in quarter notes per minute as MIDI counts it, from that slot on. In 4/4, the bar

```
(AQ)Q/TQ/R/EFG/
```

presses C4 and C5 together, then C5, G5 and C5 on the following eighth notes, F5 for a beat, and E5, F5 and G5 as a triplet, all as taps. The bar

```
(AQ)(aq)Qq/Q(qW)/ w/ /
```

presses C4 and C5 together and then C5 again, each held for a sixteenth note, then holds C5 for an eighth note and D5 for a quarter note.

## Conversion

1. Each channel of each track is a part, and channel 10 holds drums, which are left out. All notes of the parts chosen with `--parts`, or of every part by default, are collected with their onsets and ends.
2. The whole song is shifted by the semitone count in -24..24 that leaves the fewest notes on black keys, then the fewest outside the range, preferring the smallest shift on remaining ties. Black keys weigh more because resolving one changes its pitch class, while an octave fold keeps it. A song that sits in one major key (or its relative minor) lands entirely on white keys this way.
3. Notes still outside the range are folded by octaves into it. The range is C3 to B5, or C4 to B5 with `--horn`.
4. Each note still on a black key moves one semitone down or up, whichever clashes less with the white-key notes whose onsets lie within one beat, weighted by time distance. The interval roughness table is `ROUGHNESS` in `lyre.py`.
5. Each beat gets the coarsest grid (1, 2, 3, 4, 6, 8, 12 or 16 slots) that puts every onset in the beat within 1/32 of a quarter note of a slot, and with `--hold` every note end in it as well. A passage gets no finer grid than it uses, and a few irregular notes widen only their own beats. Notes that fall into the same slot and key merge into one press. Tempo changes move to the nearest slot of their beat.
6. With `--max-keys N`, a press with more than N keys keeps its top voice as the melody, then the bass, then the inner voices that add the most harmony. Among inner voices, those doubling a pitch class are removed first, then those a perfect fifth above another chord tone, then those nearest the top. Removed notes are dropped rather than delayed, so every kept note stays on its original onset.
7. Every press is a tap, or with `--hold` the key stays down until the latest end among its merged notes, placed on the grid like an onset. A key pressed again is released at that press, and a note that ends within the grid tolerance of its onset stays a tap. `--max-keys` limits the keys pressed in one slot, and keys held from earlier slots do not count toward it.

Only the first time signature is used for bar lines.

The preview MIDI keeps the original tempo map and plays every press on a General MIDI harp. A held key sounds until its release, and a tap rings for one beat or until the same key is pressed again.

## Playing

`play.py` sends key presses to the focused window, so it starts one second after launch to leave time to switch to the game. The game only accepts them from a process with administrator rights. The keys of a chord go down together. With `-k`, each press of `K`, `,` or space sends the next key or chord together with the releases before it, rests are skipped, and `` ` `` quits. The releases after the last press need one more trigger. Keys still down are released when playing stops.

With `--loose`, the file is a chart copied from the community, which has no durations. Only parenthesized chords, capital letters and spaces count, so headings, dashes, `/` and other text in the copy are ignored, and `#` starts a comment. A key or chord takes 0.15 s, a space 0.1 s. Keys inside `{}`, `【】` or `[]` take half the key time, on the guess that they mark a fast run or an arpeggio. Lines starting with `@` are directives:

- `@note_delay S` and `@space_delay S` set the time of a key and a space in seconds.
- `@clear` drops everything before it.
- `@bar_sep 'S'` splits lines into bars at `S`, `/` by default.
- `@break_after N` adds a space after each bar made of exactly N keys and spaces, which separates runs of single notes.

Open design questions are recorded under `docs/`.
