function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const out = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) out[i] = rawData.charCodeAt(i);
  return out;
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms)),
  ]);
}

async function getRegistration() {
  const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  if (reg.active) return reg;
  const worker = reg.installing || reg.waiting;
  if (worker) {
    await new Promise((resolve) => {
      if (worker.state === "activated") return resolve();
      worker.addEventListener("statechange", () => {
        if (worker.state === "activated") resolve();
      });
    });
  }
  return reg;
}

function setPushUI(enabled, text) {
  const statusEl = document.getElementById("push-status");
  const btn = document.getElementById("push-enable-btn");
  if (text) statusEl.textContent = text;
  btn.disabled = false;
  if (enabled) {
    btn.textContent = "Отключить уведомления";
    btn.onclick = disablePush;
  } else {
    btn.textContent = "Включить уведомления";
    btn.onclick = enablePush;
  }
}

async function refreshPushStatus() {
  const btn = document.getElementById("push-enable-btn");
  if (!btn) return;
  btn.onclick = enablePush; // кнопка не должна быть "мёртвой", даже если проверка статуса зависнет
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    setPushUI(false, "Браузер не поддерживает push-уведомления.");
    btn.disabled = true;
    return;
  }
  try {
    const reg = await withTimeout(getRegistration(), 8000);
    const sub = await reg.pushManager.getSubscription();
    let enabled = false;
    if (sub && Notification.permission === "granted") {
      const r = await fetch("/push/status?endpoint=" + encodeURIComponent(sub.endpoint));
      enabled = (await r.json()).enabled;
    }
    setPushUI(enabled, enabled ? "Уведомления включены ✅" : "Уведомления выключены.");
  } catch (e) {
    setPushUI(false, "Уведомления выключены (не удалось проверить: " + e.message + ").");
  }
}

async function enablePush() {
  const statusEl = document.getElementById("push-status");
  const btn = document.getElementById("push-enable-btn");
  btn.disabled = true;
  statusEl.textContent = "Включаю...";
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      setPushUI(false, "Уведомления запрещены в настройках браузера/сайта.");
      return;
    }
    const reg = await withTimeout(getRegistration(), 8000);
    const { key } = await (await fetch("/push/vapid-public-key")).json();
    if (!key) {
      setPushUI(false, "На сервере не удалось получить ключ для push.");
      return;
    }
    const old = await reg.pushManager.getSubscription();
    if (old) { try { await old.unsubscribe(); } catch (e) {} }
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
    const raw = sub.toJSON();
    const resp = await fetch("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: raw.endpoint, keys: raw.keys, welcome: true }),
    });
    if (!resp.ok) throw new Error("сервер вернул " + resp.status);
    setPushUI(true, "Уведомления включены ✅");
  } catch (e) {
    setPushUI(false, "Не удалось включить: " + e.message);
  }
}

async function disablePush() {
  const btn = document.getElementById("push-enable-btn");
  btn.disabled = true;
  try {
    const reg = await withTimeout(getRegistration(), 8000);
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      // Сервер сначала шлёт push "выключены", потом удаляет подписку.
      await fetch("/push/unsubscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: sub.endpoint }),
      });
      // Локально отписываемся с задержкой, чтобы push успел дойти.
      setTimeout(() => { sub.unsubscribe().catch(() => {}); }, 5000);
    }
    setPushUI(false, "Уведомления выключены.");
  } catch (e) {
    setPushUI(true, "Не удалось выключить: " + e.message);
  }
}

document.addEventListener("DOMContentLoaded", refreshPushStatus);
