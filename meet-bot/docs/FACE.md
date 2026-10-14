# FR-MTG-14 canvas camera

Live sessions install a 320x240 canvas camera before navigating to Meet and
enable that synthetic track after joining. Video never requests a physical
camera; audio constraints still use the existing microphone path.

Idle, listening, thinking, speaking, happy and sad follow explicit transcript,
model, audio and delivery events. Only actual model calls start thinking; every
model exit clears it. First PCM playback starts speaking, playback completion
or cancellation clears it, and PCM levels move the mouth. Idle blinks at least
every 7.2 seconds. Rendering and capture stay at 15 fps.

Local state tests are separate from Chromium acceptance. Pixel hashes, playback
timing and CPU overhead must pass browser acceptance under the shared heavy
lock before this slice is marked ready; no real Meet acceptance is implied.
