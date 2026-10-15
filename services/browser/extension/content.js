let recording = false;
const clip = (value, size = 200) => String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, size);
const send = (event) => chrome.runtime.sendMessage({ kind: "event", event }).catch(() => {});
const selector = (node) => node.id ? `#${CSS.escape(node.id)}` : "";
const label = (node) => clip(node.getAttribute("aria-label") || node.getAttribute("title") || node.innerText || node.textContent);
const credentialLike = (node) => {
  const hint = [node.type, node.name, node.autocomplete, node.getAttribute("aria-label"), node.placeholder,
    node.labels && [...node.labels].map((x) => x.textContent).join(" ")].join(" ").toLowerCase();
  return /password|passwd|passcode|otp|one.time|token|secret|credential|user.?name|email|card|cvv|security.?code/.test(hint);
};
const safeTextInput = (node) => node instanceof HTMLInputElement &&
  ["text", "search"].includes(node.type.toLowerCase()) && !!node.id && !credentialLike(node);

chrome.runtime.onMessage.addListener((message) => {
  if (typeof message?.recording === "boolean") recording = message.recording;
});
chrome.storage.local.get("tilo_skill_recording", ({ tilo_skill_recording: state }) => {
  recording = state?.active === true;
});

document.addEventListener("click", (event) => {
  if (!recording || !(event.target instanceof Element)) return;
  const node = event.target.closest("button,a,[role=button],input[type=submit]");
  if (node) send({ kind: node.matches("[type=submit],button[type=submit]") ? "submit" : "click",
    url: location.href, target: label(node), selector: selector(node) });
}, true);
document.addEventListener("change", (event) => {
  if (!recording || !safeTextInput(event.target)) return;
  send({ kind: "type", url: location.href, target: label(event.target) || "Text field",
    selector: selector(event.target), value: event.target.value, safe_text: true });
}, true);
document.addEventListener("scroll", () => {
  if (recording) send({ kind: "scroll", url: location.href, target: "Page", observation: `Vertical position ${Math.round(scrollY)}` });
}, { capture: true, passive: true });
