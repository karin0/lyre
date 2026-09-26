# Long rests after held chords

Status: open, nothing implemented.

## Observation

Some charts leave rests of several beats after a chord, and the preview MIDI falls silent there. In "A World Without Danger", bars 73 to 78 hold five such rests of 2 to 4 beats, each after a chord of two or three notes. At 99 BPM the longest one is about 1.8 seconds of silence in the preview.

## Causes

The source MIDI of that song gives every note a sixteenth-note duration and has no sustain pedal, so it records onsets only. A chord that the original music holds for a bar arrives as a single strike. The chart keeps onsets faithfully, so the rest is in the source.

The preview rings each press for one beat, a length chosen without measuring how long the in-game lyre sounds. The preview therefore goes silent earlier than the game may.

## Candidate changes

1. Ring each press in the preview until the same key is pressed again, capped at the lyre's actual decay. This changes only the preview. Dense passages would blur more. The decay length has to be measured in the game first.
2. Behind a switch such as `--sustain`, re-strike the chord on every beat of a rest of two beats or more, up to the next onset. The same song re-strikes a held dyad on every beat in bar 80, so this follows the transcriber's own idiom; for bars 73 to 78 it adds 10 presses that are absent from the source. It would run before `--max-keys` so the added presses obey the cap, and it would skip rests that follow a single note, where repeating a melody note sounds abrupt. It stays opt-in because a MIDI recorded with real durations already holds its chords, and re-striking would double them.
