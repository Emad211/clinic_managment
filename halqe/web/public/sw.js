/**
 * sw.js — Service Worker سادهٔ آفلاین برای حلقه
 *
 * استراتژی: cache-first برای فونت‌ها و فایل‌های استاتیک Next.js.
 * network-first برای درخواست‌های API (هیچ‌گاه cache نمی‌شوند).
 *
 * بدونِ CDN — همهٔ asset‌ها از خودِ origin سرو می‌شوند.
 */

const CACHE_NAME = "halqe-v1";

/** پیشوندهایی که cache-first هستند */
const CACHE_FIRST_PATTERNS = [
  /\/fonts\//,
  /\/_next\/static\//,
  /\/icons\//,
];

/** درخواست‌هایی که هرگز cache نمی‌شوند */
const NEVER_CACHE_PATTERNS = [
  /\/api\//,
];

self.addEventListener("install", (event) => {
  // pre-cache فونت‌ها
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll([
        "/fonts/Vazirmatn-Regular.woff2",
        "/fonts/Vazirmatn-Medium.woff2",
        "/fonts/Vazirmatn-SemiBold.woff2",
        "/fonts/Vazirmatn-Bold.woff2",
      ]).catch(() => {
        // اگر فونت‌ها در دسترس نبودند، install را block نکن
      })
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // cache‌های قدیمی را پاک کن
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = request.url;

  // فقط GET را مدیریت کن
  if (request.method !== "GET") return;

  // API → هرگز cache نکن
  if (NEVER_CACHE_PATTERNS.some((p) => p.test(url))) return;

  // cache-first برای فونت + static
  if (CACHE_FIRST_PATTERNS.some((p) => p.test(url))) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // بقیه: network با fallback به cache (برای offline)
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.status === 200 && response.type === "basic") {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
