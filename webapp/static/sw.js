// Минимальный service worker — нужен только для того, чтобы браузер считал
// сайт устанавливаемым приложением (PWA). Никакого офлайн-кеша/логики не
// добавляет — сайт как работал через сеть, так и работает, просто теперь его
// можно поставить на главный экран телефона как обычное приложение.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});

self.addEventListener("push", (event) => {
  let data = { title: "BR Management", body: "", url: "/" };
  try { data = { ...data, ...event.data.json() }; } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(clients.openWindow(url));
});
