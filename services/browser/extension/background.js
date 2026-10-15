import { appendEvent } from "./recording.js";

const KEY = "tilo_skill_recording";
const read = async () => (await chrome.storage.local.get(KEY))[KEY] || { active: false, id: null, events: [] };
const write = (state) => chrome.storage.local.set({ [KEY]: state });
let writes = Promise.resolve();

function enqueue(operation) {
  const result = writes.then(operation);
  writes = result.catch(() => {});
  return result;
}

function record(input) {
  return enqueue(async () => {
    const state = await read();
    if (!state.active) return;
    const events = appendEvent(state.events, input);
    if (events !== state.events) await write({ ...state, events });
  });
}

chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  (async () => {
    if (message?.kind === "start") {
      const state = await enqueue(async () => {
        const started = { active: true, id: crypto.randomUUID(), events: [] };
        await write(started);
        return started;
      });
      const tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
      for (const tab of tabs) chrome.tabs.sendMessage(tab.id, { recording: true }).catch(() => {});
      respond(state);
    } else if (message?.kind === "stop") {
      const stopped = await enqueue(async () => {
        const state = await read();
        const next = { ...state, active: false };
        await write(next);
        return next;
      });
      respond(stopped);
    } else if (message?.kind === "state") respond(await enqueue(read));
    else if (message?.kind === "event") {
      await record(message.event);
      respond({ ok: true });
    }
  })().catch(() => respond({ error: "Recorder unavailable" }));
  return true;
});

chrome.webNavigation.onCommitted.addListener((details) => {
  if (details.frameId === 0 && details.url.startsWith("http")) {
    void record({ kind: "navigate", url: details.url, target: "Page navigation" });
  }
});

chrome.downloads.onChanged.addListener(async (delta) => {
  if (delta.state?.current !== "complete") return;
  const [item] = await chrome.downloads.search({ id: delta.id });
  if (item) void record({ kind: "download", url: item.url, target: item.filename, destination: item.filename });
});
