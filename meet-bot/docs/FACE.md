# FR-MTG-14 canvas camera

Live sessions install a 320x240 canvas camera before navigating to Meet and
enable that synthetic track after joining. Device enumeration preserves real
devices and appends one stable videoinput, Tilo Director (tilo-canvas-camera).
Repeated enumeration deduplicates that id. Video never requests a physical
camera; audio constraints still use the existing microphone path. Do not add
--use-fake-device-for-media-stream: it would replace the virtual microphone.

Idle, listening, thinking, speaking, happy and sad follow explicit transcript,
model, audio and delivery events. Only actual model calls start thinking; every
model exit clears it. First PCM playback starts speaking, playback completion
or cancellation clears it, and PCM levels move the mouth. Idle blinks at least
every 7.2 seconds. Rendering and capture stay at 15 fps. State transitions,
model/audio counters and decay remain owned by the existing event handler.

The Director bust ports the box projection, three-piece crown, white face plate
and arms from design/source/tilo-world.js (ADR-0003), using plain canvas calls.
Director orange is #E8643F; ink is #1F1D2B. The small isometric desk and figure
fit inside the central 320x180 crop (y=30..209) on a flat background. Listening
tilts the bust and adds a sound arc; thinking adds three dots; PCM level changes
the speaking mouth; happy and sad change the expression. No assets or network.

Run node --test meet-bot/tests/test_FR_MTG_14_face.cjs from the repo root.
The six golden SHA-256 values hash canvas operations, not pixels. Regressions
also cover pose details, blink, throttling, nested model calls, camera listing,
canvas capture and real microphone forwarding. Local Chromium acceptance is
separate: inspect all six native/cropped poses, hash pixels, verify captured
track dimensions/fps, and measure rendering cost under the shared heavy lock.
This does not imply live Meet or end-to-end bot CPU acceptance.
