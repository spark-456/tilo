# Tilo Skill Recorder extension

Load this directory as an unpacked extension in Chrome or Edge at `chrome://extensions` or `edge://extensions`. Start and stop capture from the toolbar popup; use Export JSON to save the current recording locally.

The Manifest V3 recorder observes top-level navigation, clicks, submit clicks, scroll position, completed downloads, and text/search fields with an element id. It keeps at most 200 events in extension local storage. It removes URL credentials, query strings, and fragments, masks common secret patterns, and skips fields that look like credentials or payment data.

Exports are untrusted input. They are not replayable until the browser worker imports each event through `RecordingSession`, rechecks typed fields, pauses for sign-in, and applies the existing side-effect approval gate. The extension does not sign in, submit data, or replay actions.
