/* Service worker mínimo — cache de shell para abrir offline corto */
var CACHE = "sioc-campo-v6";
var ASSETS = [
  "/comando-vivo/app",
  "/static/css/comando_vivo.css",
  "/static/js/comando_vivo_app.js",
  "/static/comando_vivo/manifest.json",
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return c.addAll(ASSETS).catch(function () {});
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (e) {
  e.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  if (url.pathname.indexOf("/comando-vivo/api/") === 0) {
    return;
  }
  e.respondWith(
    fetch(e.request).catch(function () {
      return caches.match(e.request);
    })
  );
});
