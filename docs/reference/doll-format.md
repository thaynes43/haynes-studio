# The doll short format

This page describes the format that worked in "Crunch Costs Extra" (OP345, Nov 2026).
Tom liked it and asked for more in the same style. Keep to it unless a title's brief
says otherwise.

## Look

- **Dolls.** Original adult fashion dolls that read clearly as toys: glossy molded
  plastic, visible joints and seams, painted eyes, exaggerated sculpted expressions.
  Big, uncanny synthetic hair (teased, frizzy, flyaways) is part of the joke.
  Never a real person and never a known toy brand.
- **Expressions are fixed.** Each doll image has one permanent molded expression.
  Changing a face means a separate image of the same doll, used from the next cut
  onward.
- **Sets.** A miniature 1:6-scale environment photographed like a product shot:
  shallow depth of field, soft light, tactile miniatures. The middle 70% of the frame
  stays empty so dolls can be composited in, and a foreground strip (a table edge, a
  log, a rock) hides where each doll's body ends.
- **No on-screen text** in the art itself: no logos, captions or speech bubbles,
  unless the brief asks for them (a team name on a jacket, for example). OP345 had no
  captions, music or banner.

## Motion

- Each shot shows one still cutout (or several, for a group shot) over a fixed
  background with a fixed camera.
- The whole doll moves as one rigid piece, translated and rotated as if an unseen
  hand lifts and rocks it. Poses hold at 12 per second inside 24 fps output, which
  gives a stop-motion feel.
- No lip-sync, blinking, mouth or eye motion, or face warping. The stiffness is the
  style, not a limitation to hide.

## Sound

- Stock synthetic voices from Kokoro, one distinct voice per doll. No voice cloning.
- Dialogue is mixed per line at about -22 dBFS RMS, with short fades at each edge.
- Each line starts a beat into its shot and ends at least 0.25 s before the cut.
  Never cut a line short to fit; change the shot length or the line.
- Sparse sound effects only: one well-placed cue beats a busy bed.
- Master to about -20 LUFS integrated, true peak at or below -3.5 dBTP before
  encoding (the delivered file must measure at or below -2.5 dBTP), no clipping.

## Delivery spec

| | |
|---|---|
| Frame | 1080x1920 (9:16 vertical), 24 fps, H.264 `yuv420p`, CRF 18 |
| Audio | AAC 192 kbit/s from a 48 kHz, 24-bit stereo master |
| Length | OP345 was 20 s: four 5 s shots. Longer stories need more or longer shots. |
| Checks | decoded frame count and duration, loudness and peak, zero clipped samples, transcript matches the script, contact sheet reviewed |

## Comedy

- Short exchanges with deadpan delivery. Each line has to fit its shot, so roughly
  6 to 12 words at Kokoro's pace.
- Expression changes land on the cuts, and the punchline usually lands on the last
  cut.
- Parody may borrow a situation from popular media, but the names, team names,
  logos and dialogue are our own.
- No violence on screen. Dark premises are played for deadpan, not shown.
