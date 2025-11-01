# Light Show Track Format (LSTF)

This document proposes a binary-and-stream friendly container for synchronising
Lego Dimensions portal pad light sequences with optional audio playback.  The
goal is to encode the full state of all three pads (centre, left, right) at any
point on a shared timeline while allowing tempo changes, overlapping actions,
and eventual extension to synchronised sound effects.

## Design Goals

* **Deterministic playback** – given a timestamp, the active command on each pad
  is known and can be reconstructed to support seeking and looped playback.
* **Support all known light commands** – `switch_pad`, `fade_pad`, `flash_pad`
  as well as their group variants must be expressible.
* **Flexible colour addressing** – every event can reference either an explicit
  RGB triplet or a palette colour, ensuring broad compatibility with simple
  tooling as well as advanced editors.
* **Tempo-aware timing** – actions are positioned on a tempo grid while still
  offering sub-second precision down to 1/20 s and slow events up to 10 s.
* **Streaming friendly** – the format can be emitted/consumed incrementally
  without scanning entire files, and embeds enough metadata to resume mid-track.
* **Extensible** – future pad effects or an audio track can be introduced
  without breaking older decoders.

## High-level Structure

An `.lstf` file is a sequence of typed chunks, similar to RIFF or MIDI, so that
readers can skip chunks they do not understand.  The overall layout is:

```
+-------------------+
| Header chunk      |
+-------------------+
| Tempo map chunk   |
+-------------------+
| Pad track chunk 0 |
+-------------------+
| Pad track chunk 1 |
+-------------------+
| Pad track chunk 2 |
+-------------------+
| Audio track chunk |
+-------------------+
| Optional extras   |
+-------------------+
```

Each chunk begins with a 4-byte ASCII type tag, a 32-bit little-endian payload
length, then the payload bytes.  Multiple chunks of the same type may appear; a
streaming producer may interleave chunks, although encoders should emit the
header first.

An optional global chunk captures shared colour information referenced by pad events:

* `PAL0` – Replaces entries in the standard 32-colour palette with custom RGB values.

`PAL0` payloads contain a list of overrides: `[u8 entry_count][entry…]` where each entry is `[u8 index][u8 r][u8 g][u8 b]`.  Encoders may include multiple `PAL0` chunks; later overrides replace earlier ones.

### Header (`HEAD`)

The header establishes global metadata:

| Offset | Type      | Meaning                                                         |
|-------:|-----------|-----------------------------------------------------------------|
| 0      | `u32`     | Magic value `0x4C535446` (`LSTF`) for validation                |
| 4      | `u16`     | Format version (currently `0x0001`)                             |
| 6      | `u16`     | Ticks per beat (resolution). Default recommendation: `960`.     |
| 8      | `u32`     | Initial tempo in microseconds per beat (MIDI-compatible).       |
| 12     | `u16`     | Number of declared tracks (should be ≥ 4).                      |
| 14     | `u16`     | Flags (bit 0: loopable, bit 1: includes state keyframes, etc.). |

The ticks-per-beat resolution of 960 provides 0.5 ms granularity at 120 BPM,
allowing comfortable placement from 1/20 s (50 ms) up to long events without
floating point rounding.

Optional UTF-8 key/value metadata pairs may follow using length-prefixed
strings (e.g., title, author).  Because the format is chunk-based, future
metadata chunks (e.g., `META`) can be appended without affecting players that
ignore them.

### Tempo Map (`TEMP`)

The tempo map is a series of delta-timed events sorted by playback order.  Each
entry consists of a variable-length integer `delta_ticks` followed by a tempo
opcode and its payload:

* `0x01 SetTempo`: payload `u32 microseconds_per_beat`.  This matches the MIDI
  tempo convention, so existing tempo tools can be re-used.
* `0x02 SetTimebase`: payload `u16 ticks_per_beat`.  Allows run-time resolution
  changes if desired; most sequences will keep the header value.

Players accumulate deltas to obtain absolute tick positions, apply the tempo
changes, then schedule pad track events against wall-clock time.  A streaming
source can send `TEMP` events ahead of audio/pad data so the tempo is known.

## Pad Tracks (`PAD0`, `PAD1`, `PAD2`)

There are three mandatory pad tracks, one per physical pad (centre, left,
right).  Track `PAD0` is the centre pad, `PAD1` the left pad, `PAD2` the right.

Track payloads follow the same delta-time event encoding used by MIDI:

```
[delta_ticks varint][event opcode][event payload] ...
```

The delta is measured in ticks relative to the previous event on *the same
track*.  Events implicitly cut short any prior command still in progress when a
new one begins, providing the requested “replace on overlap” behaviour.

Supported opcodes and payloads:

| Opcode | Name                   | Payload                                                                 | Notes |
|-------:|------------------------|-------------------------------------------------------------------------|-------|
| `0x10` | `SwitchColour`         | `u16 transition_ticks, ColourSpec colour, u16 hold_ticks`               | Uses `switch_pad`; `transition_ticks = 0` performs an immediate switch, otherwise the player approximates the ramp with hardware fades before dwelling for `hold_ticks`. |
| `0x11` | `FadeToColour`         | `u16 ramp_ticks, u8 pulses, ColourSpec colour, u16 hold_ticks`          | Maps to `fade_pad` (`pulse_time`, `pulse_count`, colour). `ramp_ticks` converts to hardware pulse time. |
| `0x12` | `FlashColour`          | `u16 on_ticks, u16 off_ticks, u8 pulses, ColourSpec colour, u16 hold_ticks` | Maps to `flash_pad`. Hold covers the dwell period after the last pulse. |
| `0x13` | `Blackout`             | `u16 transition_ticks, u16 hold_ticks`                                  | Convenience for fading or cutting to black without encoding a colour literal. |
| `0x14` | `SetDefaultTransition` | `u16 transition_ticks`                                                  | Sets a per-track default transition applied when later events use the sentinel `transition_ticks = 0xFFFF`. |
| `0x1F` | `KeyframeState`        | `u8 state_id`                                                           | Points to a `STAT` chunk snapshot for fast seeking. |

`hold_ticks` defines when the command is considered complete.  If the hardware
command finishes earlier (e.g., `flash_pad` pulses) the sequence remains in the
resulting colour for the remainder of the hold period unless interrupted.
Setting a duration longer than the hardware limit is permitted; the decoder
clamps to the nearest legal values and treats the remaining ticks as dwell
time.  When `transition_ticks` is non-zero (or set to the sentinel `0xFFFF` to
use the track default), the player linearly ramps brightness and colour from the
current pad state to the new `ColourSpec` before executing the rest of the
command, enabling smooth overlaps between “notes”.

### Colour Specification

All pad opcodes reference colours through a shared encoding so that sequences can mix palette entries and literal RGB values without ambiguity.

```
ColourSpec := [u8 mode][payload]

mode bit layout:
  bits 0-4 : palette index (0-31)
  bit 5    : payload type (0 = palette reference, 1 = literal RGB)
  bits 6-7 : reserved, set to 0

payload:
  if bit5 = 0 -> no extra bytes; the index in bits0-4 selects the palette entry
  if bit5 = 1 -> [u8 r][u8 g][u8 b]
```

With this encoding, palette entry *n* uses `mode = n` (bit 5 clear).  Literal colours set bit 5 and typically zero the lower bits, e.g., `mode = 0x20` followed by `r`, `g`, `b`.

### Standard 32-colour Palette

The default palette spans the full hue circle plus useful white/neutral values. Encoders may reference entries by index or override specific colours with a `PAL0` chunk. Colours are expressed in sRGB hex for documentation clarity.

| Index | Name            | RGB Hex | Description |
|------:|-----------------|---------|-------------|
| 0     | Black           | #000000 | Off/blackout |
| 1     | White           | #FFFFFF | Neutral white |
| 2     | Warm White      | #FFD8B0 | Incandescent tint |
| 3     | Cool White      | #D6F0FF | Cool bluish white |
| 4     | Deep Red        | #FF0000 | Primary red |
| 5     | Scarlet         | #FF3300 | Red-orange |
| 6     | Orange          | #FF6600 | Classic orange |
| 7     | Amber           | #FF9900 | Warm amber |
| 8     | Golden Yellow   | #FFCC00 | Bright yellow-orange |
| 9     | Sun Yellow      | #FFFF00 | Primary yellow |
| 10    | Lemon           | #CCFF00 | Yellow-green |
| 11    | Chartreuse      | #99FF00 | Electric yellow-green |
| 12    | Spring Green    | #66FF00 | Greenish yellow |
| 13    | Neon Green      | #33FF00 | Vivid green |
| 14    | Emerald         | #00FF00 | Primary green |
| 15    | Mint            | #00FF66 | Green-cyan |
| 16    | Aqua            | #00FFCC | Cyan-leaning green |
| 17    | Cyan            | #00FFFF | Primary cyan |
| 18    | Sky Blue        | #00CCFF | Cyan-blue |
| 19    | Azure           | #0099FF | Bright blue |
| 20    | Electric Blue   | #0066FF | Saturated blue |
| 21    | Royal Blue      | #0033FF | Deep blue |
| 22    | Indigo          | #0000FF | Primary blue/violet |
| 23    | Violet          | #3300FF | Blue-purple |
| 24    | Purple          | #6600FF | Purple |
| 25    | Magenta         | #9900FF | Violet-magenta |
| 26    | Hot Pink        | #CC00FF | Bright magenta |
| 27    | Fuchsia         | #FF00FF | Primary magenta |
| 28    | Rose            | #FF0099 | Magenta-red |
| 29    | Cerise          | #FF0066 | Pinkish red |
| 30    | Crimson         | #FF0033 | Deep pink-red |
| 31    | Warm Red        | #FF1919 | Slightly desaturated red |

The palette order follows increasing hue from red through the spectrum and back to red for predictable indexing.

To convert tempo and transition ticks into the byte ranges accepted by the USB protocol (0–255), the player uses the current tempo to obtain milliseconds per tick and performs clamping/scaling.  Implementations should document their mapping (e.g., how `transition_ticks` map onto `fade_pad`’s `pulse_time`).  Palette indices are converted into RGB using the active table before commands are emitted.

### Group Actions (`GRP0`)

When simultaneous fades or flashes across multiple pads are desired, encoders
may emit optional group chunks `GRP0`, each containing delta-timed events whose
payloads describe all three pad slots at once.  A group event overrides any
individual pad events scheduled over the same interval.

Payload format mirrors the pad command:

* `0x20 GroupFade`: `[u16 ramp_ticks, u8 pulses, ((u8 enable, ColourSpec)×3), u16 hold_ticks]`
* `0x21 GroupFlash`: `[u16 on_ticks, u16 off_ticks, u8 pulses, ((u8 enable, ColourSpec)×3), u16 hold_ticks]`
* `0x22 GroupSwitch`: `[u16 transition_ticks, ((u8 enable, ColourSpec)×3), u16 hold_ticks]`

Each colour entry carries an enable flag so unused pads may keep their prior state.  When `transition_ticks` fields are non-zero (or 0xFFFF for “use default”) the player performs the same ramping behaviour as individual pad events before applying the shared command.  Players resolve conflicts by prioritising the most recently started command (group or pad-specific) at any timestamp.

## Audio Track (`AUD0`)

The optional fourth track carries synchronised audio triggers.  Its event stream
is also delta-based and currently defines:

| Opcode | Payload                                                                  |
|-------:|--------------------------------------------------------------------------|
| `0x40` | `u16 sample_id, u16 start_offset_ticks, u16 fade_in_ticks, u16 fade_out_ticks` |

Sample metadata (file paths, lengths) live in a `SAMP` chunk:

```
[u16 sample_id][u8 encoding][u32 sample_rate][u32 length_ticks][u16 loop_start][u16 loop_end][path string]
```

The `length_ticks` field ensures the overall track duration respects sample
play time when calculating sequence length.

## State Snapshots (`STAT`)

To guarantee that playback may begin at arbitrary points without scanning from
zero, encoders can periodically emit `STAT` chunks.  Each snapshot records the
wall-clock time, absolute tick, and current command (including remaining
hardware parameters) for every pad and audio sample.  A `KeyframeState` event on
a track references the snapshot ID to indicate that the state is exactly as
recorded there.  Decoders may ignore snapshots if they prefer to recompute state
from the beginning.

## Streaming Considerations

* Chunks are self-delimiting; a streaming sender can write them sequentially as
  they are produced.  Consumers must buffer enough tempo information to map
  tick deltas into real time.  The header and tempo chunk should be sent first.
* Events are delta-timed, so missing data manifests as gaps rather than
  permanent desynchronisation.  Late-arriving tempo changes are applied from the
  point they are received.
* Because every event specifies an explicit duration/hold, the state of each pad
  at any tick can be computed by locating the latest command whose start time is
  at or before the tick and checking whether its duration has expired.

## Example Timeline

The following pseudo-encoding demonstrates a simple two-beat flash on the
centre pad while the right pad fades in:

```
HEAD: version=1, ticks_per_beat=960, tempo=500000 (120 BPM)
TEMP: delta=0  -> SetTempo 500000
PAL0: override index 4 -> #FF0000 (deep red), index 14 -> #00FF00 (emerald)
PAD0: delta=0  -> FlashColour(on=120, off=120, pulses=4, colour=palette[4], hold=240)
       delta=960 -> SwitchColour(transition=0, colour=palette[0], hold=0)
PAD2: delta=0  -> FadeToColour(ramp=480, pulses=1, colour=palette[14], hold=960)
```

## Extensibility

* New pad effect opcodes can be added in unused opcode space (`0x30`–`0x3F`).
* Additional tracks (e.g., fog machines, DMX fixtures) can be introduced with
  their own chunk tags without disturbing existing readers.
* Alternate serialisations (JSON, protobuf) can represent the same conceptual
  model by mirroring the track/event schema defined above.

This specification provides the timing and command vocabulary needed for
sophisticated light shows, while remaining compact enough for embedded playback
or live streaming control.
