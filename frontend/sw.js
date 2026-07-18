/* =====================================================================
   SARP-Naval · Service Worker propio (sin Workbox, sin CDN)
   - App shell (HTML/CSS/JS/vendor/manifest/íconos): cache-first.
   - /api/*: network-first con respaldo a caché (última respuesta buena).
   Tras la primera carga la app funciona sin conexión.
   ===================================================================== */
"use strict";

const VERSION = "sipao-v2.0.0";  // v1.1: costeo v2 doctrinario + fix helpers globales
const SHELL_CACHE = "sarp-shell-" + VERSION;
const API_CACHE = "sarp-api-" + VERSION;

// Rutas relativas al scope (frontend/)
const SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./estilos.css",
  "./manifest.webmanifest",
  "./vendor/chart.umd.min.js",
  "./reporte_pedido.html",
  "./reporte_ejecutivo.html",
  "./icons/icono-192.png",
  "./icons/icono-512.png",
  "./icons/icono-512-maskable.png",
  "./plantillas/plantilla_maestro_items.csv",
  "./plantillas/plantilla_movimientos.csv",
  "./plantillas/plantilla_stock_actual.csv"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      // addAll falla en bloque si un recurso no está; usamos add tolerante
      .then(cache => Promise.all(SHELL.map(u => cache.add(u).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(claves => Promise.all(
      claves.filter(c => c !== SHELL_CACHE && c !== API_CACHE).map(c => caches.delete(c))
    )).then(() => self.clients.claim())
  );
});

function esApi(url) { return url.pathname.startsWith("/api/"); }

// GET /api/bitacora es la SONDA de conexión de la pestaña Registro:
// jamás debe responderse desde caché (un 200 viejo simularía backend en
// línea, dejaría los formularios habilitados sin conexión y mostraría
// una bitácora obsoleta sin marca alguna). Solo red.
function esSondaBitacora(url) { return url.pathname.startsWith("/api/bitacora"); }

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return; // POST /api/importar siempre va a la red
  const url = new URL(req.url);

  if (esSondaBitacora(url)) {
    // solo red, sin respaldo de caché: si falla, 503 honesto (r.ok = false)
    event.respondWith(
      fetch(req).catch(() => new Response(
        JSON.stringify({ error: "Sin conexión: la bitácora y el registro requieren el backend en línea." }),
        { status: 503, headers: { "Content-Type": "application/json" } }
      ))
    );
    return;
  }

  if (esApi(url)) {
    // network-first: intenta la red, cachea la buena, si falla usa caché
    event.respondWith(
      fetch(req).then(res => {
        if (res && res.ok) {
          const copia = res.clone();
          caches.open(API_CACHE).then(c => c.put(req, copia));
        }
        return res;
      }).catch(() => caches.match(req).then(hit => hit || new Response(
        JSON.stringify({ error: "Sin conexión y sin copia en caché para esta ruta." }),
        { status: 503, headers: { "Content-Type": "application/json" } }
      )))
    );
    return;
  }

  // App shell: cache-first, con actualización en segundo plano
  event.respondWith(
    caches.match(req).then(hit => {
      if (hit) return hit;
      return fetch(req).then(res => {
        if (res && res.ok && (url.origin === self.location.origin)) {
          const copia = res.clone();
          caches.open(SHELL_CACHE).then(c => c.put(req, copia));
        }
        return res;
      }).catch(() => caches.match("./index.html"));
    })
  );
});
