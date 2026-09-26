function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

async function enablePush() {
  const statusEl = document.getElementById("push-status");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    statusEl.textContent = "Браузер не поддерживает push-уведомления.";
    return;
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      statusEl.textContent = "Уведомления не разрешены в браузере.";
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    const keyResp = await fetch("/push/vapid-public-key");
    const { key } = await keyResp.json();
    if (!key) {
      statusEl.textContent = "Push пока не настроен на сервере.";
      return;
    }
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
    const raw = sub.toJSON();
    await fetch("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: raw.endpoint, keys: raw.keys }),
    });
    statusEl.textContent = "Уведомления включены ✅";
  } catch (e) {
    statusEl.textContent = "Не удалось включить уведомления.";
  }
}
