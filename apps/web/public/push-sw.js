// FR-CHN-17d: the service worker that shows a web push notice. It fetches nothing and imports nothing: it shows the
// title and body tilo-channels sent (bounded again here) and, on a tap, focuses a Tilo tab or opens the app's root.
// The payload carries no address, so a notice can never send the person to a page of someone else's choosing.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  const text = (v, max) => (typeof v === "string" ? v.trim().slice(0, max) : "");
  const title = text(data.title, 80) || "Tilo";
  const options = { body: text(data.body, 200) };
  const tag = text(data.tag, 64);
  if (tag) options.tag = tag;
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      const open = tabs.find((t) => "focus" in t);
      return open ? open.focus() : self.clients.openWindow("/");
    }),
  );
});
