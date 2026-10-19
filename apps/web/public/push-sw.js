// FR-CHN-17d: the service worker that shows a web push notice. It fetches and imports nothing and caches nothing. It
// shows plain text only (a bounded title and body: no buttons, pictures or markup from the payload),
// and a tap opens only an allowlisted same-origin relative path: the Needs-you page on Home, which needs the signed-in
// session. A payload that is not the expected shape shows nothing of its own.
const OPEN_PATH = /^\/park\/home(\?card=[A-Za-z0-9_-]{1,64})?$/;
const HOME = "/park/home";

const text = (v, max) => (typeof v === "string" ? v.trim().slice(0, max) : "");

self.addEventListener("push", (event) => {
  let data = null;
  try {
    data = event.data ? event.data.json() : null;
  } catch {
    data = null;
  }
  if (data === null || typeof data !== "object" || Array.isArray(data)) return;
  const title = text(data.title, 80);
  if (!title) return;
  const options = {
    body: text(data.body, 200),
    data: { path: OPEN_PATH.test(data.path) ? data.path : HOME },
  };
  const tag = text(data.tag, 64);
  if (/^[A-Za-z0-9_-]+$/.test(tag)) options.tag = tag;
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const asked = event.notification.data?.path;
  const path = typeof asked === "string" && OPEN_PATH.test(asked) ? asked : HOME;
  event.waitUntil(self.clients.openWindow(path));
});
