# lyre

`lyre.py` converts a MIDI file or a chart copied from the community into a key chart for the Windsong Lyre in Genshin Impact, written for `play.py` or for a human to read, and optionally renders the chart back to MIDI for listening. `play.py` plays a chart in the game.

```sh
uv run lyre.py song.mid                             # writes song.md
uv run lyre.py song.mid --human                     # writes song.human.md
uv run lyre.py song.mid --midi                      # writes song.md and song.lyre.mid
uv run lyre.py song.mid --horn --max-keys 2 --hold  # writes song.horn.max2.hold.md
uv run lyre.py song.mid --max-keys 2 -o easy.md     # writes easy.md
uv run lyre.py song.mid --list-parts                # lists the parts to pick with --parts
uv run lyre.py copy.sh                              # reads a community chart, writes copy.md
uv run lyre.py song.mid --parts 0 5                 # writes song.parts0+5.md
uv run play.py song.md                              # plays song.md in the focused window
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

`--human` writes a chart to read and play by hand. Every beat has the same slots, the tempo line also gives the length of a slot, all keys are taps, and tempo changes are left out, so `--hold` is rejected. The bar above with the triplet becomes

```
(AQ)  Q  /T  Q  /R     /E F G /
```

with one slot a 1/24 note. `play.py` reads both formats.

## Conversion

1. Each channel of each track is a part, and channel 10 holds drums, which are left out. All notes of the parts chosen with `--parts`, or of every part by default, are collected with their onsets and ends.
2. The whole song is shifted by the semitone count in -24..24 that leaves the fewest notes on black keys, then the fewest outside the range, preferring the smallest shift on remaining ties. Black keys weigh more because resolving one changes its pitch class, while an octave fold keeps it. A song that sits in one major key (or its relative minor) lands entirely on white keys this way.
3. Notes still outside the range are folded by octaves into it. The range is C3 to B5, or C4 to B5 with `--horn`.
4. Each note still on a black key moves one semitone down or up, whichever clashes less with the white-key notes whose onsets lie within one beat, weighted by time distance. The interval roughness table is `ROUGHNESS` in `lyre.py`.
5. Each beat gets the coarsest grid (1, 2, 3, 4, 6, 8, 12 or 16 slots) that puts every onset in the beat within 1/32 of a quarter note of a slot, and with `--hold` every note end in it as well. A passage gets no finer grid than it uses, and a few irregular notes widen only their own beats. With `--human`, the whole song gets the one grid that fits every onset, so that a slot always has the same length. Notes that fall into the same slot and key merge into one press. Tempo changes move to the nearest slot of their beat.
6. With `--max-keys N`, a press with more than N keys keeps its top voice as the melody, then the bass, then the inner voices that add the most harmony. Among inner voices, those doubling a pitch class are removed first, then those a perfect fifth above another chord tone, then those nearest the top. Removed notes are dropped rather than delayed, so every kept note stays on its original onset.
7. Every press is a tap, or with `--hold` the key stays down until the latest end among its merged notes, placed on the grid like an onset. A key pressed again is released at that press, and a note that ends within the grid tolerance of its onset stays a tap. `--max-keys` limits the keys pressed in one slot, and keys held from earlier slots do not count toward it.

Only the first time signature is used for bar lines.

## Community charts

An input without a `.mid` or `.midi` suffix is a chart copied from the community, which has no durations. Each line is stripped, and only the capital letters of the 21 keys, chords of them in parentheses and spaces count, so headings, dashes and other text in the copy are ignored, and `#` starts a comment. A key or chord takes 0.15 s, a space 0.1 s. Keys inside `{}`, `【】` or `[]` take half the key time, on the guess that they mark a fast run or an arpeggio. A key becomes a sixteenth note, so the chart gets the tempo at which four keys fill a beat, 100 BPM by default.

A tempo marker such as `<73>`, written as in the chart format above, reads the rest of the chart as beats from that slot on. Each separator closes a beat, which splits evenly among its keys, chords and spaces, and brackets change nothing. Further markers change the tempo at their slot, so a ritardando is written as in a key chart. Markers are written by hand, since many copies with separators lost too many spaces to be read as beats. A beat whose slot count differs from the most common one and that has a key after its first slot stops the conversion with its line, because its missing spaces could have stood anywhere in it. A beat with only its first slot pressed is a rest and passes.

Lines starting with `@` are directives:

- `@note_delay S` and `@space_delay S` set the time of a key and a space in seconds, and return from beats to fixed times.
- `@clear` drops everything before it.
- `@bar_sep 'S'` sets the separator, `/` by default. It splits bars for `@break_after`, and beats after a tempo marker.
- `@break_after N` adds a space after each bar made of exactly N keys and spaces, which separates runs of single notes. It is rejected in beats.

The keys then go through steps 2 to 7 above as one part in 4/4. Onsets that would need more than 16 slots in a beat, such as a space and a bracketed key in one beat at the default times, move by up to 1/32 beat. A chart whose default path is its input, such as `copy.md`, needs `-o`.

The preview MIDI written with `--midi` is named after the chart, such as `song.human.lyre.mid` beside `song.human.md`. It follows the grid of the chart, keeps the original tempo map and plays every press on a General MIDI harp. A held key sounds until its release, and a tap rings for one beat or until the same key is pressed again.

## Playing

`play.py` sends key presses to the focused window. The game runs on Windows and only accepts them from a process with administrator rights. The keys of a chord go down together. The song plays while Scroll Lock is on and pauses while it is off, and it starts one second of playing time after launch to leave time to switch to the game. A pause releases the held keys, and they stay up after it. A song played to its end turns Scroll Lock off, so the next song waits for it. With `-k`, each press of `K`, `,` or space sends the next key or chord together with the releases before it, rests are skipped, `` ` `` quits, and Scroll Lock has no effect. The releases after the last press need one more trigger. Keys still down are released when playing stops.

Open design questions are recorded under `docs/`.
