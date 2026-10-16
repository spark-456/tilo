# FR-MTG-14 canvas camera

Live sessions install a 320x240 canvas camera before navigating to Meet,
append `Tilo camera` to the device list, and enable that synthetic track after
joining. Video never requests a physical camera; audio constraints still use
the existing microphone path. The 16:9-safe tile follows the Tilo T Meet and
Buddy boards: a coral Director bust (`#E8643F`) behind a small desk on a
light lime background, with a cup, paper and current pose label. It uses plain
canvas calls without external assets or network requests.

Idle, listening, thinking, speaking, happy and sad follow explicit transcript,
model, audio and delivery events. Only actual model calls start thinking; every
model exit clears it. First PCM playback starts speaking, playback completion
or cancellation clears it, and PCM levels move the mouth. A heard event tilts
the head and draws sound arcs; a model call shows three dots; success and
failure set static happy and sad faces. Idle blinks every 7.2 seconds; reduced
motion keeps it open. Rendering and capture stay at 15 fps.

Local state tests are separate from Chromium acceptance. Pixel hashes, playback
timing and CPU overhead must pass browser acceptance under the shared heavy
lock before this slice is marked ready; no real Meet acceptance is implied.
