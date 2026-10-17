// Service worker mínimo del arnés de desarrollo (el de la app es de Juanpe, en app/web/static/sw.js).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = { title: "Entrecasa", body: "", url: "/dev/" };
  try { data = { ...data, ...event.data.json() }; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title, { body: data.body, data: { url: data.url } }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow(event.notification.data.url || "/dev/"));
});
