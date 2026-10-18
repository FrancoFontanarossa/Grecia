/* Entrecasa — service worker. Solo push y click; sin caché offline (P1). Se sirve desde /sw.js. */
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) { event.waitUntil(self.clients.claim()); });

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  var title = data.title || "Neuro";
  var url = data.url || data.deep_link || "/casa";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    tag: data.tag || undefined,
    data: { url: url }
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = new URL((event.notification.data && event.notification.data.url) || "/casa", self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      var c = list[i];
      if (c.url.indexOf(self.location.origin) === 0 && "focus" in c) {
        return c.focus().then(function (fc) { return (fc || c).navigate ? (fc || c).navigate(target) : null; })
          .catch(function () { return self.clients.openWindow(target); });
      }
    }
    return self.clients.openWindow(target);
  }));
});
