// The five-minute cap of the screen capture is a real timer, so the recorder lives outside this page folder, where
// nothing may wait on a timer (Skills.static.test.ts, STUDIO-4). This file keeps the page's import path.
export { recordScreen, type ScreenRecording } from "../../shared/screenRecorder";
