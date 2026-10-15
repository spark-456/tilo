const status = document.querySelector("#status");
const request = (kind) => chrome.runtime.sendMessage({ kind });
function render(state) {
  status.textContent = state.error || `${state.active ? "Recording" : "Stopped"} · ${state.events?.length || 0} events`;
  document.querySelector("#start").disabled = state.active;
  document.querySelector("#stop").disabled = !state.active;
  document.querySelector("#export").disabled = !state.events?.length;
}
request("state").then(render).catch(() => { status.textContent = "Recorder unavailable"; });
document.querySelector("#start").addEventListener("click", () => request("start").then(render));
document.querySelector("#stop").addEventListener("click", () => request("stop").then(render));
document.querySelector("#export").addEventListener("click", async () => {
  const state = await request("state");
  const blob = new Blob([JSON.stringify({ version: 1, events: state.events }, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `tilo-recording-${state.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});
