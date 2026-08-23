/* proxy-switch: 禁用 PWA 缓存（内嵌面板，始终加载最新文件） */
self.addEventListener('install', function (e) {
  self.skipWaiting();
});
self.addEventListener('activate', function (e) {
  e.waitUntil(clients.claim());
});
self.addEventListener('fetch', function (e) {
  // 不拦截任何请求，全部走网络
});
