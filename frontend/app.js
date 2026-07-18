/* =====================================================================
   SARP-Naval · App conectada (tareas 2.4-2.7)
   Consume el backend FastAPI (/api/*) del mismo origen. Offline-first:
   guarda un snapshot en IndexedDB y, si un fetch falla, muestra el
   banner "sin conexión" y usa el último snapshot. Sin red en runtime:
   Chart.js del vendor local; ninguna URL externa.
   Todas las cifras provienen de /api/* o del snapshot; nada inventado.
   ===================================================================== */
(function () {
"use strict";

/* ==================================================================
   Clave de operación (solo en la instancia publicada)
   ------------------------------------------------------------------
   En el servidor, la CONSULTA es libre y la ESCRITURA exige la clave
   de operación (ver backend/app/seguridad.py). En local no hay clave
   configurada y esto no se activa nunca: el comportamiento es idéntico
   al de siempre.

   Se envuelve `fetch` una sola vez, en lugar de tocar cada llamada:
   así queda cubierta toda escritura —incluidas las que se añadan
   después— sin que nadie tenga que acordarse de hacerlo. Si el
   servidor responde 401, se pide la clave, se guarda en el navegador
   y se reintenta la MISMA petición una vez.
   ================================================================== */
const CLAVE_LS = "sipao_clave_operacion";
const SIN_CUERPO = { GET: 1, HEAD: 1, OPTIONS: 1 };

(function instalarClaveDeOperacion() {
  const original = window.fetch.bind(window);
  window.fetch = async function (entrada, opciones) {
    opciones = opciones || {};
    const metodo = (opciones.method || "GET").toUpperCase();
    if (SIN_CUERPO[metodo]) return original(entrada, opciones);

    const conClave = clave => {
      if (!clave) return opciones;
      const cab = new Headers(opciones.headers || {});
      cab.set("X-Sipao-Token", clave);
      return Object.assign({}, opciones, { headers: cab });
    };

    let respuesta = await original(entrada, conClave(localStorage.getItem(CLAVE_LS)));
    if (respuesta.status !== 401) return respuesta;

    const clave = window.prompt(
      "Esta plataforma está publicada en internet: la consulta es libre, " +
      "pero para GUARDAR cambios se necesita la clave de operación.\n\n" +
      "Ingrésela una sola vez; el navegador la recordará.");
    if (!clave) return respuesta;
    localStorage.setItem(CLAVE_LS, clave.trim());

    respuesta = await original(entrada, conClave(clave.trim()));
    if (respuesta.status === 401) {
      localStorage.removeItem(CLAVE_LS);   // no dejar una clave errada guardada
      alert("La clave de operación no es correcta. La consulta sigue disponible.");
    }
    return respuesta;
  };
})();

const $ = s => document.querySelector(s);
const fmt$ = n => "$" + Math.round(n || 0).toLocaleString("es-EC");
const fmtN = n => (Math.round((n || 0) * 10) / 10).toLocaleString("es-EC");
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const NIVEL_SERVICIO = { V: 99, E: 95, D: 90 };
const CRIT_LARGO = { V: "VITAL", E: "ESENCIAL", D: "DESEABLE" };
const CC = { navy: "#13315c", gold: "#c6a441", grid: "#e4eaf2", red: "#b3261e", green: "#1e7d4f", mut: "#9fb3cf" };

// Estado en memoria (se llena del backend o del snapshot)
const S = { salud: null, kpis: null, items: [], alertas: [], plantilla: null, detalles: new Map(), offline: false, mando: null };
// Quien abre la plataforma por primera vez entra al TABLERO DE COMANDO,
// no a la cola de repuestos del almacenista: SIPAO-Naval es un sistema de
// decisión de mando, y el listado de ítems es uno de sus módulos, no su
// portada. Si el usuario elige otra vista, se respeta su elección.
let ROL = localStorage.getItem("sarp_rol") || "ejecutivo";

/* ==================================================================
   IndexedDB: snapshot offline (kv) + detalles por ítem
   ================================================================== */
const IDB = (function () {
  let dbp = null;
  function open() {
    if (dbp) return dbp;
    dbp = new Promise((res, rej) => {
      const r = indexedDB.open("sarp-naval", 1);
      r.onupgradeneeded = e => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv");
        if (!db.objectStoreNames.contains("detalles")) db.createObjectStore("detalles");
      };
      r.onsuccess = e => res(e.target.result);
      r.onerror = e => rej(e.target.error);
    });
    return dbp;
  }
  function tx(store, mode, fn) {
    return open().then(db => new Promise((res, rej) => {
      const t = db.transaction(store, mode), st = t.objectStore(store);
      const out = fn(st);
      t.oncomplete = () => res(out && out.result !== undefined ? out.result : out);
      t.onerror = () => rej(t.error);
    }));
  }
  return {
    set: (store, key, val) => tx(store, "readwrite", st => st.put(val, key)).catch(() => {}),
    get: (store, key) => tx(store, "readonly", st => st.get(key)).catch(() => undefined),
    getAll: (store) => open().then(db => new Promise((res) => {
      const t = db.transaction(store, "readonly"), st = t.objectStore(store), out = new Map();
      const cur = st.openCursor();
      cur.onsuccess = e => { const c = e.target.result; if (c) { out.set(c.key, c.value); c.continue(); } else res(out); };
      cur.onerror = () => res(out);
    })).catch(() => new Map())
  };
})();

/* ==================================================================
   Fetch con fallback a snapshot
   ================================================================== */
async function pedir(path, kvKey) {
  try {
    const r = await fetch(path, { headers: { "Accept": "application/json" } });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    if (kvKey) IDB.set("kv", kvKey, data);
    return { data, live: true };
  } catch (e) {
    if (kvKey) {
      const cache = await IDB.get("kv", kvKey);
      if (cache !== undefined) { marcarOffline(); return { data: cache, live: false }; }
    }
    throw e;
  }
}
function marcarOffline() { if (!S.offline) { S.offline = true; $("#bannerOffline").classList.add("show"); } }

/* ==================================================================
   Arranque
   ================================================================== */
async function iniciar() {
  registrarSW();
  try {
    const [salud, kpis, items, alertas, plantilla] = await Promise.all([
      pedir("/api/salud", "salud"),
      pedir("/api/kpis", "kpis"),
      pedir("/api/items", "items"),
      pedir("/api/alertas", "alertas"),
      pedir("/api/importar/plantilla", "plantilla").catch(() => ({ data: null }))
    ]);
    S.salud = salud.data; S.kpis = kpis.data;
    S.items = (items.data && items.data.items) || [];
    S.alertas = (alertas.data && alertas.data.alertas) || [];
    S.plantilla = plantilla.data;
  } catch (e) {
    // Sin backend y sin snapshot: modo degradado total
    marcarOffline();
    $("#bannerCorte").innerHTML = "No hay conexión con el backend ni snapshot local. Arranque el servidor (iniciar_sarp.bat) y recargue.";
  }
  bannerCorte();
  poblarFiltroCat();
  actualizarBadges();
  aplicarRol(ROL, true);
  renderInventario();
  renderAlertas();
  renderPlantilla();
  snapshotParaReportes();
  prefetchDetalles();      // en segundo plano: llena modal offline, MAPE, gráficos
}

function bannerCorte() {
  const fecha = (S.salud && S.salud.fecha_datos) || (S.kpis && S.kpis.generado) || "—";
  const reparto = (S.kpis && S.kpis.reparto) || "—";
  const n = (S.salud && S.salud.items_cargados) != null ? S.salud.items_cargados : (S.items.length || "—");
  $("#bannerCorte").innerHTML = `Datos al corte: <b>${esc(fecha)}</b> · Reparto: <b>${esc(reparto)}</b> · ${esc(n)} ítems · fuente /api (tiempo real honesto: foto al corte, sin <i>push</i>)`;
}

/* ==================================================================
   Navegación de pestañas
   ================================================================== */
function go(v) {
  document.querySelectorAll("section.view").forEach(s => s.classList.toggle("act", s.id === "v-" + v));
  document.querySelectorAll("nav.tabs button, nav.bnav button").forEach(b => b.classList.toggle("act", b.dataset.v === v));
  window.scrollTo({ top: 0 });
  // La pestaña Validación se carga de forma diferida: consulta /api/validacion
  // la primera vez que se entra (la sección ya está visible → el gráfico mide bien).
  if (v === "validacion") ensureValidacion();
  // Alistamiento (RBS): también diferida, mismo motivo del canvas
  if (v === "alistamiento") ensureAlistamiento();
  if (v === "costeo") ensureCosteo();
  if (v === "config") ensureConfig();
  // Registro directo (C1.2): al entrar se refresca bitácora y estado online
  if (v === "registro") refrescarRegistro();
}
document.querySelectorAll("nav.tabs button, nav.bnav button").forEach(b => b.addEventListener("click", () => go(b.dataset.v)));

function actualizarBadges() {
  const n = S.alertas.filter(a => a.estado === "QUIEBRE" || a.estado === "REPONER").length;
  $("#tabBadge").textContent = n; $("#navBadge").textContent = n;
}

/* ==================================================================
   Cola de alertas priorizada (ya viene ordenada por el backend)
   ================================================================== */
function alertasReponer() { return S.alertas.filter(a => a.estado === "QUIEBRE" || a.estado === "REPONER"); }
function alertasExceso() { return S.alertas.filter(a => a.estado === "EXCESO"); }

/* ==================================================================
   VISTAS POR ROL (selector, no login)
   ================================================================== */
const ROLES = {
  operador: { ic: "🧰", tit: "Determinación de necesidades", sub: "Cola de trabajo del día — almacenista (terminología SABARE)", sim: false },
  jefe: { ic: "📋", tit: "Jefatura de Abastecimientos del reparto", sub: "Estado del mes: quiebres, exceso, MAPE por clase y pendientes", sim: false },
  gestion: { ic: "🌐", tit: "Gestión DIGLOG/DIRABA", sub: "Capital inmovilizado y candidatos a redistribución multi-reparto", sim: true },
  ejecutivo: { ic: "⚓", tit: "Tablero de comando", sub: "KPIs comprometidos y acciones prioritarias — una pantalla", sim: false }
};
$("#selRol").value = ROL;
$("#selRol").addEventListener("change", e => aplicarRol(e.target.value));

function aplicarRol(rol, silent) {
  ROL = rol; localStorage.setItem("sarp_rol", rol);
  const r = ROLES[rol];
  $("#roleIc").textContent = r.ic;
  $("#roleTit").textContent = r.tit;
  $("#roleSub").textContent = r.sub;
  $("#roleSim").style.display = r.sim ? "" : "none";
  // Registro directo (C1.2): solo para operador y jefe (quienes registran)
  const verRegistro = rol === "operador" || rol === "jefe";
  document.querySelectorAll('button[data-v="registro"]').forEach(b => { b.style.display = verRegistro ? "" : "none"; });
  renderHome();
  go("inicio");
  if (!silent) toast("Vista: " + r.tit);
}

function renderHome() {
  const box = $("#roleHome");
  if (ROL === "operador") box.innerHTML = homeOperador();
  else if (ROL === "jefe") box.innerHTML = homeJefe();
  else if (ROL === "gestion") box.innerHTML = homeGestion();
  else box.innerHTML = homeEjecutivo();
  // gráficos y cálculos diferidos que dependen de detalles
  if (ROL === "jefe") { pintarMapePorClase(); }
  if (ROL === "ejecutivo") {
    pintarDoughnutABC("chEjeABC");
    // los indicadores de mando llegan de /api/costeo y /api/alistamiento:
    // se pintan primero con lo que hay y se refrescan al llegar
    if (!S.mando) cargarMando().then(() => { if (ROL === "ejecutivo") renderHome(); });
  }
  if (ROL === "gestion") { pintarDoughnutABC("chGesABC"); }
}

/* ---- OPERADOR: determinación de necesidades ---- */
function homeOperador() {
  const cola = alertasReponer();
  if (!cola.length) return `<div class="card">Sin necesidades de reposición pendientes hoy. 👍 Todos los ítems sobre su punto de reorden.</div>`;
  const filas = cola.map(a => {
    const q = a.estado === "QUIEBRE";
    const margen = Math.max(0, a.dias_a_quiebre - a.lead_time_dias);
    const accion = q ? "Emitir pedido HOY (quiebre activo)" : `Programar pedido — margen ${margen} ${margen === 1 ? "día" : "días"} antes del quiebre`;
    return `<div class="acard ${q ? "q" : ""}">
      <div onclick="SARPUI.abrir('${esc(a.codigo_item)}')">
        <div class="t">${esc(a.nombre)}</div>
        <div class="m">${q ? "⛔ QUIEBRE ACTIVO" : "⚠ Bajo punto de reorden"} · Criticidad <span class="crit crit${a.criticidad}">${a.criticidad}</span> · quiebre en ${a.dias_a_quiebre} d · LT ${a.lead_time_dias} d<br><b>Acción sugerida:</b> ${accion}</div>
      </div>
      <div class="qty">
        <div class="n">${a.cantidad_sugerida}</div><div class="c">u a pedir · ≈ ${fmt$(a.costo_estimado)}</div>
        <button class="btn primary" style="margin-top:6px;padding:6px 12px;font-size:12px" onclick="SARPUI.draft('${esc(a.codigo_item)}')">＋ Generar pedido</button>
      </div></div>`;
  }).join("");
  return `<div class="card" style="margin-bottom:12px"><h3>Prioridad de atención <small>${cola.length} ítems · ordenados por el backend (estado › criticidad › margen)</small></h3>
    <p style="font-size:12.5px;color:var(--mut)">Trabaje de arriba hacia abajo. Cada tarjeta abre el análisis del ítem con su explicación en lenguaje llano.</p></div>${filas}`;
}

/* ---- JEFE: estado del mes ---- */
function homeJefe() {
  const k = S.kpis || {};
  const dispon = k.disponibilidad != null ? k.disponibilidad + "%" : "—";
  return `<div class="kgrid k4">
      <div class="kpi ok"><div class="v">${dispon}</div><div class="l">Alistamiento (familia ancla)</div><div class="s">proxy por vitales en quiebre</div></div>
      <div class="kpi bad"><div class="v">${k.quiebres ?? "—"}</div><div class="l">Quiebres activos</div><div class="s">fill rate real: con datos migrados o del registro directo</div></div>
      <div class="kpi warn"><div class="v">${k.reponer ?? "—"}</div><div class="l">Ítems bajo ROP</div></div>
      <div class="kpi exc"><div class="v">${k.excesos ?? "—"}</div><div class="l">Ítems en exceso sobre máximo</div><div class="s">capital exceso ${fmt$(k.capitalExceso)}</div></div>
    </div>
    <div class="notec">El <b>fill rate</b> y el MAPE requieren la serie real de despachos — migrada de la base histórica de SISLOG o registrada directamente en SARP (pestaña Registro). Con el dataset simulado se muestran los KPIs que sí se pueden calcular honestamente (disponibilidad proxy, quiebres, exceso) y el MAPE de pronóstico por clase.</div>
    <div class="grid2b">
      <div class="card"><h3>MAPE de pronóstico por clase <small>ítems regulares (Holt)</small></h3><div id="mapeClase"><div class="nochart" style="height:120px">Calculando MAPE por clase…</div></div></div>
      <div class="card"><h3>Pendientes de atención <small>cola priorizada</small></h3><div class="twrap" style="max-height:320px;overflow:auto">${tablaPendientes()}</div></div>
    </div>`;
}
function tablaPendientes() {
  const cola = alertasReponer();
  if (!cola.length) return `<div style="padding:14px;color:var(--mut)">Sin pendientes.</div>`;
  return `<table><thead><tr><th>#</th><th>Ítem</th><th>Crit.</th><th>Estado</th><th class="num">Pedir</th><th class="num">Costo</th></tr></thead><tbody>${cola.map((a, i) => `<tr onclick="SARPUI.abrir('${esc(a.codigo_item)}')"><td class="num">${i + 1}</td><td class="itname" title="${esc(a.nombre)}">${esc(a.nombre)}</td><td class="crit crit${a.criticidad}">${a.criticidad}</td><td><span class="badge s${a.estado}">${a.estado}</span></td><td class="num">${a.cantidad_sugerida}</td><td class="num">${fmt$(a.costo_estimado)}</td></tr>`).join("")}</tbody></table>`;
}
async function pintarMapePorClase() {
  await prefetchDetalles();
  const cont = $("#mapeClase"); if (!cont) return;
  const acc = { A: [], B: [], C: [] };
  S.detalles.forEach(d => {
    const cl = d.clasificacion && d.clasificacion.abc;
    const pr = d.pronostico && d.pronostico[0];
    if (cl && pr && pr.modelo === "holt" && pr.mape != null) acc[cl].push(pr.mape);
  });
  const prom = cl => acc[cl].length ? Math.round(acc[cl].reduce((a, b) => a + b, 0) / acc[cl].length) : null;
  const rows = ["A", "B", "C"].map(cl => {
    const m = prom(cl), meta = cl === "A" ? 25 : null;
    const ok = m != null && meta != null ? (m <= meta) : null;
    return `<div class="repline"><span class="tag ${ok === true ? "ok" : ok === false ? "adv" : ""}" style="min-width:64px;text-align:center">Clase ${cl}</span>
      <div style="flex:1">MAPE promedio: <b>${m != null ? m + " %" : "n/d"}</b> ${acc[cl].length ? `(${acc[cl].length} ítems regulares)` : "(sin ítems regulares)"} ${meta ? `· meta ≤ ${meta} %` : ""}</div></div>`;
  }).join("");
  cont.innerHTML = rows || `<div class="nochart" style="height:80px">Sin datos de MAPE.</div>`;
}

/* ---- GESTIÓN DIGLOG/DIRABA (SIMULADA) ---- */
function homeGestion() {
  const k = S.kpis || {};
  const exc = alertasExceso();
  const candidatos = exc.map(a => `<div class="acard e">
      <div onclick="SARPUI.abrir('${esc(a.codigo_item)}')"><div class="t">${esc(a.nombre)}</div>
      <div class="m">EXCESO sobre nivel máximo · Criticidad <span class="crit crit${a.criticidad}">${a.criticidad}</span> · candidato a redistribución hacia repartos con déficit</div></div>
      <div class="qty"><div class="n">${a.cantidad_sugerida || "—"}</div><div class="c">u redistribuibles</div></div></div>`).join("") || `<div class="card">Sin ítems en exceso en este reparto.</div>`;
  return `<div class="notec"><b>DATOS SIMULADOS — visión fase 2 (multi-reparto).</b> Esta vista ilustra la gestión central: hoy deriva de los datos de un <b>solo reparto</b> (${esc((k.reparto) || "—")}). La redistribución real entre repartos es una capacidad de la fase 2, cuando SARP integre varios inventarios.</div>
    <div class="kgrid k4">
      <div class="kpi"><div class="v">${fmt$(k.capitalStock)}</div><div class="l">Capital inmovilizado (reparto)</div></div>
      <div class="kpi exc"><div class="v">${fmt$(k.capitalExceso)}</div><div class="l">Capital en exceso</div><div class="s">candidato a liberar/redistribuir</div></div>
      <div class="kpi gold"><div class="v">${fmt$(k.ahorroPotencial)}</div><div class="l">Ahorro potencial / año</div></div>
      <div class="kpi"><div class="v">${fmt$(k.valorAnualDemanda)}</div><div class="l">Valor anual de demanda</div></div>
    </div>
    <div class="grid2b">
      <div class="card"><h3>Distribución del valor (ABC)</h3><div class="chartbox"><canvas id="chGesABC"></canvas></div></div>
      <div class="card"><h3>Candidatos a redistribución <small>ítems en exceso (ilustrativo)</small></h3>${candidatos}</div>
    </div>`;
}

/* ---- EJECUTIVO: una pantalla sin scroll ---- */
/* ---- EJECUTIVO / MANDO: tablero gerencial de la plataforma ----
   Panel principal de SIPAO-Naval: decisión de mando arriba (presupuesto,
   alistamiento, operaciones sostenibles) y acceso a los tres módulos.
   NO lista repuestos: el detalle de abastecimiento vive en su módulo. */
function homeEjecutivo() {
  const k = S.kpis || {};
  const m = S.mando || {};                    // /api/costeo + /api/alistamiento
  const pend = k.quiebres != null ? k.quiebres : "—";
  const val = (x, suf) => x == null ? "—" : (typeof x === "number" ? Math.round(x) + (suf || "") : x);

  const modulo = (icono, titulo, vista, desc, dato) => `
    <div class="card modcard" onclick="go('${vista}')" style="cursor:pointer">
      <h3>${icono} ${titulo}</h3>
      <p style="font-size:12.5px;color:var(--mut);line-height:1.5;margin:4px 0 8px">${desc}</p>
      <div style="font-size:13px"><b>${dato}</b></div>
    </div>`;

  return `<div class="kgrid k4">
      <div class="kpi ok"><div class="v">${val(m.alistamiento_pct, "%")}</div><div class="l">Alistamiento de la fuerza</div><div class="s">con el presupuesto vigente</div></div>
      <div class="kpi gold"><div class="v">${m.plan_operativo != null ? fmt$(m.plan_operativo) : "—"}</div><div class="l">Presupuesto del plan / año</div><div class="s">operativo requerido</div></div>
      <div class="kpi"><div class="v">${val(m.cobertura_plan_pct, "%")}</div><div class="l">Cobertura del plan de operaciones</div><div class="s">días de mar financiables</div></div>
      <div class="kpi bad"><div class="v">${pend}</div><div class="l">Alertas críticas de material</div><div class="s">impiden operar</div></div>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3>Situación de decisión <small>qué sostengo con lo asignado</small></h3>
      <div id="mandoResumen" style="font-size:13px;line-height:1.6">${m.resumen || "Calculando la situación de mando…"}</div>
    </div>

    <div class="grid3mod">
      ${modulo("⚓", "Alistamiento operativo", "alistamiento",
        "Cuántas unidades quedan listas para operar con el presupuesto asignado, y cuánto alistamiento cuesta cada recorte.",
        m.alistamiento_pct != null ? `Alistamiento actual: ${Math.round(m.alistamiento_pct)}%` : "Abrir módulo")}
      ${modulo("💲", "Costeo de operación", "costeo",
        "Qué unidades pueden operar, cuántos días de mar sostengo y qué operaciones quedan cubiertas.",
        m.plan_operativo != null ? `Plan completo: ${fmt$(m.plan_operativo)}/año` : "Abrir módulo")}
      ${modulo("📦", "Abastecimiento predictivo (SARP)", "alertas",
        "Qué pedir, cuánto y con qué urgencia. Pronóstico, punto de reorden y alertas explicadas.",
        `${pend} alertas críticas · ${fmt$(k.capitalStock)} inmovilizados`)}
    </div>

    <div class="grid2" style="margin-top:14px">
      <div class="card"><h3>Capital del inventario por clase (ABC)</h3><div class="chartbox" style="height:210px"><canvas id="chEjeABC"></canvas></div></div>
      <div class="card"><h3>Indicadores del abastecimiento <small>módulo SARP</small></h3>
        <div style="font-size:13px;line-height:1.9">
          Capital inmovilizado: <b>${fmt$(k.capitalStock)}</b><br>
          Ahorro potencial estimado: <b>${fmt$(k.ahorroPotencial)}</b>/año<br>
          Ítems en quiebre: <b>${k.quiebres ?? "—"}</b> · bajo reorden: <b>${k.reponer ?? "—"}</b> · en exceso: <b>${k.excesos ?? "—"}</b>
        </div>
        <div style="margin-top:10px"><button class="btn ghost" onclick="go('alertas')">Ver cola de reposición →</button></div>
      </div>
    </div>
    <div style="text-align:right;margin-top:10px"><button class="btn ghost" onclick="window.open('reporte_ejecutivo.html','_blank')">🖨 Resumen ejecutivo imprimible</button></div>`;
}

/* Carga los indicadores de mando (costeo + alistamiento) para el tablero. */
async function cargarMando() {
  try {
    const [rc, ra] = await Promise.all([
      fetch("/api/costeo", { headers: { Accept: "application/json" } }),
      fetch("/api/alistamiento", { headers: { Accept: "application/json" } }),
    ]);
    const c = await rc.json(), a = await ra.json();
    const sinRecorte = (c.escenario_recorte && (c.escenario_recorte["0"] || c.escenario_recorte[0])) || null;
    const pr = sinRecorte && sinRecorte.priorizado;
    const insignia = pr && pr.operaciones && (pr.operaciones.VIDA_HUMANA || Object.values(pr.operaciones)[0]);
    const aPct = a && a.alistamiento_actual != null ? 100 * a.alistamiento_actual : null;
    S.mando = {
      alistamiento_pct: aPct,
      plan_operativo: c.presupuesto_plan && c.presupuesto_plan.operativo_minimo,
      cobertura_plan_pct: pr ? 100 * pr.cobertura_ponderada : null,
      resumen: pr ? `Con el presupuesto del plan (<b>${fmt$(c.presupuesto_plan.operativo_minimo)}</b> operativos al año) la fuerza sostiene
        <b>${Object.values(pr.dias_por_clase).reduce((x, y) => x + y, 0).toLocaleString("es-EC")} días de mar</b>
        y cubre el <b>${Math.round(100 * pr.cobertura_ponderada)}%</b> del plan de operaciones, con la
        <b>salvaguarda de la vida humana en el mar al ${Math.round(100 * (insignia ? insignia.cobertura : 0))}%</b>.
        ${pr.unidades_bajo_minimo && pr.unidades_bajo_minimo.length
          ? `⚠️ Clases bajo su presencia mínima: <b>${pr.unidades_bajo_minimo.join(", ")}</b>.`
          : "Todas las clases sostienen su presencia mínima."}
        <br><span style="color:var(--mut)">Abra <b>Costeo de operación</b> para simular un recorte y ver qué operaciones se sostienen.</span>` : "",
    };
  } catch (e) { S.mando = {}; }
}

/* ==================================================================
   Gráficos (Chart.js vendor local; degradación elegante)
   ================================================================== */
function chartDisponible() { return !window.__noChart && typeof Chart !== "undefined"; }
function noChart(id) { const c = document.getElementById(id); if (c) c.parentElement.innerHTML = '<div class="nochart">Gráfico no disponible (Chart.js local no cargó). Las cifras y tablas funcionan igual.</div>'; }

async function pintarDoughnutABC(id) {
  await prefetchDetalles();
  if (!chartDisponible()) return noChart(id);
  const el = document.getElementById(id); if (!el) return;
  const val = { A: 0, B: 0, C: 0 };
  S.detalles.forEach(d => { const c = d.clasificacion; if (c && val[c.abc] != null) val[c.abc] += c.valor_anual || 0; });
  const data = [val.A, val.B, val.C], tot = data.reduce((a, b) => a + b, 0) || 1;
  new Chart(el, {
    type: "doughnut",
    data: { labels: ["Clase A", "Clase B", "Clase C"], datasets: [{ data, backgroundColor: [CC.navy, CC.gold, CC.mut], borderWidth: 2 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 13, font: { size: 11 } } }, tooltip: { callbacks: { label: c => ` ${c.label}: ${fmt$(c.parsed)} (${Math.round(c.parsed * 100 / tot)}%)` } } } }
  });
}

/* ==================================================================
   Inventario
   ================================================================== */
function poblarFiltroCat() {
  const cats = [...new Set(S.items.map(i => i.categoria))].sort();
  cats.forEach(c => { const o = document.createElement("option"); o.textContent = c; $("#fCat").appendChild(o); });
}
const ORDEN_ESTADO = { QUIEBRE: 0, REPONER: 1, OK: 2, EXCESO: 3 };
function renderInventario() {
  const q = $("#q").value.toLowerCase(), fe = $("#fEstado").value, fc = $("#fCat").value, fa = $("#fABC").value;
  const rows = S.items.filter(i =>
    (!q || i.nombre.toLowerCase().includes(q) || i.codigo.toLowerCase().includes(q)) &&
    (!fe || i.estado === fe) && (!fc || i.categoria === fc) && (!fa || i.abc === fa))
    .sort((a, b) => (ORDEN_ESTADO[a.estado] - ORDEN_ESTADO[b.estado]) || (b.valor_stock - a.valor_stock));
  $("#tbInv").innerHTML = rows.map(i => `<tr onclick="SARPUI.abrir('${esc(i.codigo)}')">
    <td style="font-family:Consolas,monospace;font-size:12px">${esc(i.codigo)}</td>
    <td class="itname" title="${esc(i.nombre)}">${esc(i.nombre)}</td>
    <td>${esc(i.categoria)}</td>
    <td class="crit crit${i.criticidad}">${i.criticidad}</td>
    <td><b>${esc(i.abc || "—")}</b></td>
    <td class="num">${i.existencia}</td>
    <td class="num">${i.rop}</td>
    <td class="num">${i.dias_a_quiebre >= 999 ? "—" : i.dias_a_quiebre + " d"}</td>
    <td><span class="badge s${i.estado}">${i.estado}</span></td>
    <td class="num">${fmt$(i.valor_stock)}</td></tr>`).join("") || `<tr><td colspan="10" style="padding:14px;color:var(--mut)">Sin resultados.</td></tr>`;
}
["q", "fEstado", "fCat", "fABC"].forEach(id => $("#" + id).addEventListener("input", renderInventario));

/* ==================================================================
   Alertas + pedido borrador (persistente en localStorage)
   ================================================================== */
const draft = new Map(JSON.parse(localStorage.getItem("sarp_draft") || "[]"));
function guardarDraft() { localStorage.setItem("sarp_draft", JSON.stringify([...draft])); }
function alertaDe(cod) { return S.alertas.find(a => a.codigo_item === cod); }
function costoDraft() { let t = 0; draft.forEach(d => t += d.costo_estimado || 0); return t; }

function renderAlertas() {
  const cola = alertasReponer();
  $("#alertList").innerHTML = cola.map(a => {
    const inD = draft.has(a.codigo_item), q = a.estado === "QUIEBRE";
    const lim = Math.max(0, a.dias_a_quiebre - a.lead_time_dias);
    return `<div class="acard ${q ? "q" : ""}">
      <div onclick="SARPUI.abrir('${esc(a.codigo_item)}')">
        <div class="t">${esc(a.nombre)}</div>
        <div class="m">${q ? "⛔ QUIEBRE ACTIVO" : "⚠ Bajo punto de reorden"} · Criticidad <span class="crit crit${a.criticidad}">${a.criticidad}</span> · Stock hacia quiebre en ${a.dias_a_quiebre} d · Lead time ${a.lead_time_dias} d · ${q ? "<b style='color:var(--bad)'>pedir HOY</b>" : "margen para pedir: <b>" + lim + (lim === 1 ? " día" : " días") + "</b>"}</div>
      </div>
      <div class="qty">
        <div class="n">${a.cantidad_sugerida} <span style="font-size:11px;font-weight:600">u</span></div>
        <div class="c">≈ ${fmt$(a.costo_estimado)}</div>
        <button class="btn ${inD ? "ghost" : "primary"}" style="margin-top:6px;padding:6px 12px;font-size:12px" onclick="SARPUI.draft('${esc(a.codigo_item)}')">${inD ? "✓ En pedido" : "＋ Pedido"}</button>
      </div></div>`;
  }).join("") || '<div class="card">Sin alertas activas de reposición. 👍</div>';
  $("#draftN").textContent = draft.size + " ítems";
  $("#draftUSD").textContent = fmt$(costoDraft());
}
function toggleDraft(cod) {
  if (draft.has(cod)) { draft.delete(cod); toast("Retirado del pedido"); }
  else {
    const a = alertaDe(cod);
    if (!a) { toast("Ítem sin alerta activa"); return; }
    draft.set(cod, { codigo: cod, nombre: a.nombre, cantidad: a.cantidad_sugerida, costo_unit: a.costo_unitario, costo_estimado: a.costo_estimado, criticidad: a.criticidad, estado: a.estado, lead_time_dias: a.lead_time_dias });
    toast("Añadido al pedido borrador");
  }
  guardarDraft(); renderAlertas(); if (ROL === "operador") renderHome();
}
$("#btnClear").addEventListener("click", () => { draft.clear(); guardarDraft(); renderAlertas(); if (ROL === "operador") renderHome(); });

/* ---- CSV (Blob, sin librerías) ---- */
function descargar(nombre, texto) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + texto], { type: "text/csv;charset=utf-8" }));
  a.download = nombre; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1500);
}
$("#btnCSVinv").addEventListener("click", () => {
  const h = "codigo;item;categoria;criticidad;clase;stock;ROP;dias_a_quiebre;estado;valor_stock_usd";
  descargar("SARP_inventario.csv", [h, ...S.items.map(i => [i.codigo, i.nombre, i.categoria, i.criticidad, i.abc || "", i.existencia, i.rop, i.dias_a_quiebre, i.estado, i.valor_stock].join(";"))].join("\n"));
  toast("Inventario exportado (CSV)");
});
$("#btnCSVped").addEventListener("click", () => {
  const src = draft.size ? [...draft.values()] : alertasReponer().map(a => ({ codigo: a.codigo_item, nombre: a.nombre, cantidad: a.cantidad_sugerida, costo_unit: a.costo_unitario, costo_estimado: a.costo_estimado, lead_time_dias: a.lead_time_dias, estado: a.estado }));
  const h = "codigo;item;cantidad_sugerida;costo_unit_usd;subtotal_usd;lead_time_dias;prioridad";
  descargar("SARP_pedido_reposicion.csv", [h, ...src.map(i => [i.codigo, i.nombre, i.cantidad, i.costo_unit, Math.round(i.costo_estimado), i.lead_time_dias, i.estado === "QUIEBRE" ? "URGENTE" : "NORMAL"].join(";"))].join("\n"));
  toast(draft.size ? "Pedido borrador exportado" : "Sin selección: se exportaron todas las alertas");
});
$("#btnReporte").addEventListener("click", () => {
  const src = draft.size ? [...draft.values()] : alertasReponer().map(a => ({ codigo: a.codigo_item, nombre: a.nombre, cantidad: a.cantidad_sugerida, costo_unit: a.costo_unitario, costo_estimado: a.costo_estimado, lead_time_dias: a.lead_time_dias, criticidad: a.criticidad, estado: a.estado }));
  if (!src.length) { toast("No hay ítems para el pedido"); return; }
  const payload = { generado: (S.salud && S.salud.fecha_datos) || "", reparto: (S.kpis && S.kpis.reparto) || "", items: src, total: src.reduce((s, i) => s + (i.costo_estimado || 0), 0), borrador: !!draft.size };
  localStorage.setItem("sarp_pedido_reporte", JSON.stringify(payload));
  window.open("reporte_pedido.html", "_blank");
});

/* ==================================================================
   Detalle de ítem + explicabilidad (I-4)
   ================================================================== */
let chItem = null, actual = null;
async function obtenerDetalle(cod) {
  if (S.detalles.has(cod)) return S.detalles.get(cod);
  try {
    const { data } = await pedir("/api/items/" + encodeURIComponent(cod));
    S.detalles.set(cod, data); IDB.set("detalles", cod, data);
    return data;
  } catch (e) {
    const cache = await IDB.get("detalles", cod);
    if (cache) { S.detalles.set(cod, cache); marcarOffline(); return cache; }
    throw e;
  }
}
async function abrir(cod) {
  let d;
  try { d = await obtenerDetalle(cod); }
  catch (e) { toast("No se pudo cargar el detalle (sin backend ni snapshot)"); return; }
  actual = d;
  const it = d.item, cl = d.clasificacion || {}, p = d.parametros || {}, al = d.alerta || {};
  const estado = d.estado || "OK";
  const pr0 = (d.pronostico && d.pronostico[0]) || {};
  const dAvg = cl.demanda_mensual, metodo = pr0.modelo || (cl.xyz === "Z" ? "croston" : "holt");
  $("#mTit").textContent = it.nombre;
  $("#mCode").innerHTML = `${esc(it.codigo)} · ${esc(it.categoria)} · <span class="badge s${estado}">${estado}</span>`;

  // (a) Explicación en lenguaje llano — plantilla determinista (sin IA)
  const existencia = d.stock ? d.stock.existencia : "—";
  const dias = al.dias_a_quiebre != null ? al.dias_a_quiebre : (cl.dias_quiebre >= 999 ? "—" : cl.dias_quiebre);
  const nivel = NIVEL_SERVICIO[it.criticidad_ved] || 95;
  let frase;
  if (estado === "QUIEBRE" || estado === "REPONER") {
    frase = `Este ítem <b>${CRIT_LARGO[it.criticidad_ved]}</b> se repone porque el consumo promedio es <b>${fmtN(dAvg)} ${esc(it.unidad)}/mes</b>, el proveedor tarda <b>${it.lead_time_dias} días</b> y el stock actual (${existencia}) cubre <b>${dias} días</b>; con <b>${nivel}%</b> de confianza se requieren <b>${p.ss} ${esc(it.unidad)}</b> de seguridad; punto de reorden <b>${p.rop}</b>. Cantidad sugerida a pedir: <b>${al.cantidad_sugerida}</b>.`;
  } else if (estado === "EXCESO") {
    frase = `Este ítem <b>${CRIT_LARGO[it.criticidad_ved]}</b> está en <b>exceso</b>: la existencia (${existencia}) supera el nivel máximo (ROP ${p.rop} + EOQ ${p.eoq} = ${p.nivel_max}). Consumo promedio <b>${fmtN(dAvg)} ${esc(it.unidad)}/mes</b>; es candidato a liberar o redistribuir capital.`;
  } else {
    frase = `Este ítem <b>${CRIT_LARGO[it.criticidad_ved]}</b> está <b>en nivel adecuado</b>: la existencia (${existencia}) está sobre el punto de reorden (${p.rop}) y bajo el nivel máximo (${p.nivel_max}). Consumo promedio <b>${fmtN(dAvg)} ${esc(it.unidad)}/mes</b>, lead time ${it.lead_time_dias} días.`;
  }
  // (a2) régimen de política + esencialidad de misión (selector doctrinario)
  const rg = d.regimen || null;
  if (rg) {
    const esn = rg.esencialidad || {};
    const badge = rg.elegible_rbs
      ? '<span class="badge sQUIEBRE">ALISTAMIENTO</span>'
      : '<span class="badge sOK">EOQ/ROP</span>';
    const patron = rg.patron ? ` · patrón <b>${esc(rg.patron)}</b> (ADI ${rg.adi} · CV² ${rg.cv2})` : "";
    frase += `<div style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--mut)">
      <b>Régimen del motor:</b> ${badge}${patron}<br>
      <span style="font-size:12px">${esc(rg.razon || "")}</span><br>
      <span style="font-size:12px;color:var(--mut)">Esencialidad de misión: ${esc(esn.explicacion || "sin código")}</span></div>`;
  }
  $("#mExplica").innerHTML = frase;

  // parámetros
  const mape = pr0.mape != null ? Math.round(pr0.mape) + " %" : "n/d (interm.)";
  const cells = [
    ["Demanda media", fmtN(dAvg) + " " + it.unidad + "/mes"], ["σ error pron.", fmtN(pr0.sigma)], ["MAPE", mape], ["Clase", (cl.abc || "—") + (cl.xyz || "") + " · " + it.criticidad_ved],
    ["Stock actual", existencia + " " + it.unidad], ["Stock seguridad", p.ss], ["Punto reorden", p.rop], ["Lote económico", p.eoq],
    ["Lead time", it.lead_time_dias + " días"], ["Días a quiebre", dias], ["Sugerido pedir", (al.cantidad_sugerida != null ? al.cantidad_sugerida : 0) + " " + it.unidad], ["Costo unitario", fmt$(it.costo_unitario)]
  ];
  $("#mParams").innerHTML = cells.map(x => `<div class="pcell"><div class="v">${esc(x[1])}</div><div class="l">${esc(x[0])}</div></div>`).join("");

  // (b) desglose técnico expandible: cadena de cálculo
  const st = (l, v) => `<span class="st">${l} <b>${esc(v)}</b></span>`;
  const ar = '<span class="ar">→</span>';
  $("#mFlow").innerHTML = [
    st("serie", (d.historico ? d.historico.length : 36) + " m"),
    st("método", metodo), st("d̄", fmtN(dAvg)), st("σ", fmtN(pr0.sigma)),
    st("LT", it.lead_time_dias + " d"), st("z(" + it.criticidad_ved + ")", fmtN(p.z_servicio)),
    st("SS", p.ss), st("ROP", p.rop), st("EOQ", p.eoq), st("MAPE", mape)
  ].join(ar);

  $("#mPedir").style.display = (estado === "QUIEBRE" || estado === "REPONER") ? "" : "none";
  // Mostrar el modal ANTES de dibujar: Chart.js mide el contenedor al construirse
  // y si el modal está oculto (display:none) el canvas queda en 0×0. Al aplicar
  // .act (display:flex) el contenedor ya tiene tamaño; pintarChartItem fuerza el
  // reflujo al medirlo, así que se dibuja bien sin depender de requestAnimationFrame
  // (que no se dispara si la pestaña está en segundo plano).
  $("#modal").classList.add("act");
  pintarChartItem(d);
}
function pintarChartItem(d) {
  const cont = $("#chItem");
  if (!chartDisponible()) { cont.parentElement.innerHTML = '<div class="nochart">Gráfico no disponible (Chart.js local no cargó).</div>'; return; }
  const hist = (d.historico || []).map(x => x.cantidad);
  const labelsH = (d.historico || []).map(x => x.mes);
  const fc = (d.pronostico || []).map(x => x.demanda_prevista);
  const labelsF = (d.pronostico || []).map(x => x.mes);
  const p = d.parametros || {};
  const labels = [...labelsH, ...labelsF];
  const N = labels.length;
  if (chItem) chItem.destroy();
  chItem = new Chart(cont, {
    type: "line",
    data: {
      labels, datasets: [
        { label: "Consumo", data: [...hist, ...Array(fc.length).fill(null)], borderColor: "#13315c", backgroundColor: "rgba(19,49,92,.07)", fill: true, tension: .25, pointRadius: 0, borderWidth: 2 },
        { label: "Pronóstico", data: [...Array(hist.length - 1).fill(null), hist[hist.length - 1], ...fc], borderColor: "#c6a441", borderDash: [6, 4], pointRadius: 0, borderWidth: 2.5, tension: .25 },
        { label: "ROP", data: Array(N).fill(p.rop), borderColor: "#b3261e", borderDash: [3, 3], pointRadius: 0, borderWidth: 1.4 },
        { label: "SS", data: Array(N).fill(p.ss), borderColor: "#1e7d4f", borderDash: [3, 3], pointRadius: 0, borderWidth: 1.4 }
      ]
    },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { labels: { boxWidth: 12, font: { size: 10.5 } } } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, font: { size: 10 } } }, y: { grid: { color: "#e4eaf2" }, ticks: { font: { size: 10 } } } } }
  });
}
$("#mX").addEventListener("click", () => $("#modal").classList.remove("act"));
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") $("#modal").classList.remove("act"); });
$("#mPedir").addEventListener("click", () => { if (actual) { toggleDraft(actual.item.codigo); $("#modal").classList.remove("act"); go("alertas"); } });

/* ==================================================================
   Importación (dry-run + aplicar)
   ================================================================== */
function renderPlantilla() {
  const el = $("#impPlantilla");
  if (!S.plantilla) { el.textContent = "No disponible sin backend."; return; }
  try { el.textContent = JSON.stringify(S.plantilla, null, 2); }
  catch (e) { el.textContent = "No disponible."; }
}
let ultimaValidacionOK = false;
async function llamarImportar(aplicar) {
  const files = $("#fileImport").files;
  if (!files || !files.length) { toast("Seleccione uno o más archivos"); return; }
  const fd = new FormData();
  for (const f of files) fd.append("archivos", f, f.name);
  const cont = $("#impReporte");
  cont.innerHTML = `<div class="card"><p style="color:var(--mut)">${aplicar ? "Aplicando importación…" : "Validando…"}</p></div>`;
  let rep;
  try {
    const r = await fetch("/api/importar?aplicar=" + (aplicar ? "true" : "false"), { method: "POST", body: fd, headers: { "X-Rol-Demo": ROL } });
    rep = await r.json();
  } catch (e) {
    cont.innerHTML = `<div class="card"><p style="color:var(--bad)">No se pudo contactar el backend para importar. Verifique que el servidor esté corriendo.</p></div>`;
    return;
  }
  pintarReporteImport(rep, aplicar);
  if (aplicar && rep.aplicado) {
    toast("Importación aplicada — recargando datos");
    await recargarTodo();
  }
}
function pintarReporteImport(rep, aplicado) {
  const cont = $("#impReporte");
  const res = rep.resumen || {};
  let html = `<div class="card"><h3>Reporte de ${aplicado && rep.aplicado ? "importación aplicada" : "validación (dry-run)"} <small>${rep.valido ? "VÁLIDO" : "CON ERRORES"}</small></h3>`;
  html += `<div class="repline"><span class="tag ${rep.valido ? "ok" : "err"}">${rep.valido ? "OK" : "ERROR"}</span><div>Ítems: <b>${res.items ?? "—"}</b> · Movimientos: <b>${res.movimientos ?? "—"}</b> · Meses de historia: <b>${res.meses_historia ?? "—"}</b> · Reparto: <b>${esc(res.reparto || "—")}</b>${res.rango_fechas ? ` · Rango: ${esc(res.rango_fechas.desde)} a ${esc(res.rango_fechas.hasta)}` : ""}</div></div>`;
  (rep.errores || []).forEach(e => {
    const t = typeof e === "string" ? e : `[${esc(e.archivo || "")}${e.fila != null ? " fila " + e.fila : ""}${e.columna ? " · col " + esc(e.columna) : ""}] ${esc(e.mensaje || JSON.stringify(e))}`;
    html += `<div class="repline"><span class="tag err">ERROR</span><div>${t}</div></div>`;
  });
  (rep.advertencias || []).forEach(a => {
    html += `<div class="repline"><span class="tag adv">AVISO</span><div>${typeof a === "string" ? esc(a) : esc(JSON.stringify(a))}</div></div>`;
  });
  if (rep.aplicado && rep.kpi) {
    html += `<div class="repline"><span class="tag ok">APLICADO</span><div>Nuevos KPIs — quiebres: <b>${rep.kpi.quiebres}</b>, bajo ROP: <b>${rep.kpi.reponer}</b>, capital: <b>${fmt$(rep.kpi.capitalStock)}</b></div></div>`;
  }
  html += `</div>`;
  cont.innerHTML = html;
  ultimaValidacionOK = !!rep.valido && !rep.aplicado;
  $("#btnAplicar").disabled = !ultimaValidacionOK;
}
async function recargarTodo() {
  S.detalles.clear();
  prefetchProm = null; // los detalles cacheados quedaron obsoletos: se re-prefetchan
  const [kpis, items, alertas, salud] = await Promise.all([
    pedir("/api/kpis", "kpis"), pedir("/api/items", "items"), pedir("/api/alertas", "alertas"), pedir("/api/salud", "salud")
  ]);
  S.kpis = kpis.data; S.items = items.data.items || []; S.alertas = alertas.data.alertas || []; S.salud = salud.data;
  bannerCorte(); actualizarBadges(); renderInventario(); renderAlertas(); renderHome();
  poblarDatalistRegistro();
  snapshotParaReportes(); prefetchDetalles();
  $("#btnAplicar").disabled = true;
}
$("#btnValidar").addEventListener("click", () => llamarImportar(false));
$("#btnAplicar").addEventListener("click", () => llamarImportar(true));
$("#fileImport").addEventListener("change", () => { $("#btnAplicar").disabled = true; $("#impReporte").innerHTML = ""; });

/* ==================================================================
   Prefetch de detalles (para modal offline, MAPE, gráficos ABC)
   ================================================================== */
let prefetchProm = null;
function prefetchDetalles() {
  if (prefetchProm) return prefetchProm;
  prefetchProm = (async () => {
    // primero intenta rellenar desde IndexedDB (rápido, offline)
    const cache = await IDB.getAll("detalles");
    cache.forEach((v, k) => { if (!S.detalles.has(k)) S.detalles.set(k, v); });
    // luego refresca desde el backend en pequeños lotes
    const pend = S.items.map(i => i.codigo);
    for (let i = 0; i < pend.length; i += 6) {
      const lote = pend.slice(i, i + 6);
      await Promise.all(lote.map(async cod => {
        try {
          const r = await fetch("/api/items/" + encodeURIComponent(cod));
          if (r.ok) { const d = await r.json(); S.detalles.set(cod, d); IDB.set("detalles", cod, d); }
        } catch (e) { /* offline: se queda con lo de IndexedDB */ }
      }));
    }
    snapshotParaReportes(); // ahora con valorización ABC ya disponible
  })();
  return prefetchProm;
}

/* ==================================================================
   Snapshot compacto para los reportes imprimibles (localStorage)
   ================================================================== */
function snapshotParaReportes() {
  try {
    let abcValor = null;
    if (S.detalles.size) {
      abcValor = { A: 0, B: 0, C: 0 };
      S.detalles.forEach(d => { const c = d.clasificacion; if (c && abcValor[c.abc] != null) abcValor[c.abc] += c.valor_anual || 0; });
    }
    localStorage.setItem("sarp_snapshot", JSON.stringify({
      kpis: S.kpis, salud: S.salud,
      abcValor,
      topRiesgo: alertasReponer().slice(0, 10).map(a => ({ codigo: a.codigo_item, nombre: a.nombre, criticidad: a.criticidad, estado: a.estado, cantidad: a.cantidad_sugerida, costo: a.costo_estimado })),
      ts: Date.now()
    }));
  } catch (e) { /* cuota: ignorar */ }
}

/* ==================================================================
   VALIDACIÓN (rigor científico · jurado técnico)
   Lee EN VIVO /api/validacion?t0=&horizonte= (backtesting rolling-origin).
   Carga diferida; cachea cada respuesta en el snapshot (IDB kv) para que
   la pestaña muestre el último cálculo sin backend (banner offline).
   ================================================================== */
const CAP = { holt: "Holt", croston: "Croston" };
let valCargada = false, chVal = null;

function ensureValidacion() { if (!valCargada) { valCargada = true; renderValidacion(); } }

function clampT0(v) {
  let n = parseInt(v, 10);
  if (isNaN(n)) n = 24;
  if (n < 12) n = 12;
  if (n > 30) n = 30;
  return n;
}

async function renderValidacion() {
  const t0 = clampT0($("#valT0").value);
  $("#valT0").value = t0;                       // validación suave: refleja el clamp
  const h = parseInt($("#valH").value, 10) || 3;
  const estado = $("#valEstado");
  estado.textContent = "Calculando backtesting…";
  let resp;
  try {
    const { data, live } = await pedir(`/api/validacion?t0=${t0}&horizonte=${h}`, `validacion_t${t0}_h${h}`);
    resp = data;
    estado.textContent = live ? "" : "Mostrando el último cálculo en caché (sin backend).";
  } catch (e) {
    estado.textContent = "";
    $("#valKPIs").innerHTML = `<div class="card"><p style="color:var(--bad)">No se pudo calcular la validación para t₀=${t0}, horizonte=${h}: sin backend y sin copia en caché para estos parámetros. Arranque el servidor (iniciar_sarp.bat) y reintente.</p></div>`;
    $("#valTablaWrap").innerHTML = `<div class="nochart" style="height:120px">Sin datos.</div>`;
    $("#valNota").textContent = "";
    if (chVal) { chVal.destroy(); chVal = null; }
    $("#valChartBox").innerHTML = `<div class="nochart">Sin datos para graficar.</div>`;
    return;
  }
  try {
    pintarValKPIs(resp);
    pintarValTabla(resp);
    $("#valNota").textContent = (resp && resp.nota_metodologica) || "Nota metodológica no disponible.";
    renderSensibilidad(t0);
  } catch (e) {
    console.error("[validacion] fallo al pintar:", e);
    estado.textContent = "No se pudo mostrar la validación (error al renderizar).";
    $("#valKPIs").innerHTML = `<div class="card"><p style="color:var(--bad)">Error al renderizar la validación: ${esc(String(e && e.message || e))}</p></div>`;
  }
}

function pintarValKPIs(resp) {
  const r = (resp && resp.resumen) || {};
  const items = (resp && resp.por_item) || [];
  const mape = r.mape_clase_a_regular;
  const pct = r.pct_intermitentes_mase_bajo_1;
  const nA = items.filter(x => x.abc === "A" && x.tipo === "regular" && !x.omitido && x.mape != null).length;
  const nInt = r.n_intermitentes_evaluados != null ? r.n_intermitentes_evaluados
    : items.filter(x => x.tipo === "intermitente" && !x.omitido && x.mase != null).length;

  const mapeOk = mape != null && mape <= 25;
  const mapeCls = mape == null ? "" : (mapeOk ? "ok" : "bad");
  const mapeVal = mape != null ? Math.round(mape) + " %" : "n/d";
  const mapeSub = mape == null
    ? `sin ítems A regulares evaluables con este t₀`
    : `meta ≤ 25 % · ${mapeOk ? "cumple" : "por encima de la meta"} · ${nA} ítem${nA === 1 ? "" : "s"} A regular${nA === 1 ? "" : "es"}`;

  const pctCls = pct == null ? "" : (pct >= 100 ? "ok" : pct > 0 ? "warn" : "bad");
  const pctVal = pct != null ? Math.round(pct) + " %" : "n/d";
  const pctSub = pct == null
    ? `sin ítems intermitentes evaluables`
    : `MASE &lt; 1 = mejor que el pronóstico ingenuo (naïve-1) · ${nInt} ítem${nInt === 1 ? "" : "s"} evaluado${nInt === 1 ? "" : "s"}`;

  const omit = r.n_omitidos != null ? r.n_omitidos : items.filter(x => x.omitido).length;
  const evaluados = r.n_items_evaluados != null ? r.n_items_evaluados : items.filter(x => !x.omitido).length;

  $("#valKPIs").innerHTML = `<div class="valkpis">
      <div class="kpi ${mapeCls}"><div class="v">${mapeVal}</div><div class="l">MAPE clase A (demanda regular)</div><div class="s">${mapeSub}</div></div>
      <div class="kpi ${pctCls}"><div class="v">${pctVal}</div><div class="l">Intermitentes con MASE &lt; 1</div><div class="s">${pctSub}</div></div>
    </div>
    <p style="font-size:11.5px;color:var(--mut);margin:-4px 0 14px">${evaluados} ítems evaluados · ${omit} omitidos por serie corta (len &lt; t₀ + horizonte). El MAPE ponderado equivale al MAPE agrupado de todos los pares (real, pronóstico).</p>`;
}

function pintarValTabla(resp) {
  const items = (resp && resp.por_item) || [];
  if (!items.length) { $("#valTablaWrap").innerHTML = `<div class="nochart" style="height:120px">Sin ítems para mostrar.</div>`; return; }
  const nombre = new Map(S.items.map(i => [i.codigo, i.nombre]));

  const filas = items.map(x => {
    const esInt = x.tipo === "intermitente";
    const vital = x.crit === "V";
    let metrica, cumple, tit = "";
    if (x.omitido) { metrica = "—"; cumple = null; tit = x.motivo || "omitido"; }
    else if (esInt) { metrica = x.mase != null ? "MASE " + x.mase.toFixed(2) : "MASE n/d"; cumple = x.mase != null ? x.mase < 1 : null; }
    else { metrica = x.mape != null ? "MAPE " + Math.round(x.mape) + " %" : "MAPE n/d"; cumple = x.mape != null ? x.mape <= 25 : null; }
    const riesgo = vital && cumple === false;         // VITAL que no cumple → revisión de modelo
    const tag = cumple === true ? '<span class="tag ok">cumple</span>'
      : cumple === false ? '<span class="tag err">no cumple</span>'
        : x.omitido ? '<span class="tag" style="background:var(--bg);color:var(--mut)">omitido</span>'
          : '<span class="tag adv">n/d</span>';
    // Prioridad de orden: incidencias primero (riesgo vital, luego no cumple, luego n/d/omitido, luego cumple)
    const prio = riesgo ? 0 : cumple === false ? 1 : (cumple === null ? 2 : 3);
    const nm = nombre.get(x.codigo) || "—";
    const html = `<tr class="${riesgo ? "val-riesgo" : ""}">
      <td style="font-family:Consolas,monospace;font-size:12px">${esc(x.codigo)}</td>
      <td class="itname" title="${esc(nm)}">${esc(nm)}</td>
      <td><b>${esc(x.abc || "—")}</b></td>
      <td class="crit crit${esc(x.crit || "")}">${esc(x.crit || "—")}</td>
      <td>${esInt ? "Intermitente" : "Regular"}</td>
      <td>${esc(CAP[x.metodo] || x.metodo || "—")}</td>
      <td class="num" title="${esc(tit)}">${esc(metrica)}</td>
      <td>${tag}</td></tr>`;
    return { prio, abc: x.abc || "Z", html };
  });
  const ordenABC = { A: 0, B: 1, C: 2, Z: 3 };
  filas.sort((a, b) => (a.prio - b.prio) || (ordenABC[a.abc] - ordenABC[b.abc]));

  $("#valTablaWrap").innerHTML = `<table>
    <thead><tr><th>Código</th><th>Ítem</th><th>Clase</th><th>Crit.</th><th>Tipo</th><th>Método</th><th class="num">Exactitud (backtest)</th><th>Cumple meta</th></tr></thead>
    <tbody>${filas.map(f => f.html).join("")}</tbody></table>`;
}

async function renderSensibilidad(t0) {
  const box = $("#valChartBox");
  const hs = [1, 2, 3];
  const vals = [];
  for (const h of hs) {
    try {
      const { data } = await pedir(`/api/validacion?t0=${t0}&horizonte=${h}`, `validacion_t${t0}_h${h}`);
      vals.push(data && data.resumen ? data.resumen.mape_clase_a_regular : null);
    } catch (e) { vals.push(null); }
  }
  if (chVal) { chVal.destroy(); chVal = null; }
  const resumenTxt = hs.map((h, i) => `h${h}=${vals[i] != null ? Math.round(vals[i]) + "%" : "n/d"}`).join(" · ");
  if (!chartDisponible()) {
    box.innerHTML = `<div class="nochart">Gráfico no disponible (Chart.js local no cargó). MAPE clase A regular por horizonte: ${resumenTxt}.</div>`;
    return;
  }
  box.innerHTML = '<canvas id="chVal"></canvas>';
  const cont = $("#chVal");
  const y = vals.map(v => v != null ? Math.round(v * 10) / 10 : null);
  const colores = y.map(v => v == null ? CC.mut : (v <= 25 ? CC.navy : CC.red));
  chVal = new Chart(cont, {
    type: "bar",
    data: {
      labels: hs.map(h => "h = " + h + (h === 1 ? " mes" : " meses")),
      datasets: [
        { type: "bar", label: "MAPE clase A regular (%)", data: y, backgroundColor: colores, borderWidth: 0, order: 1, maxBarThickness: 90 },
        { type: "line", label: "Meta ≤ 25 %", data: hs.map(() => 25), borderColor: CC.gold, borderDash: [6, 4], borderWidth: 2, pointRadius: 0, fill: false, order: 0 }
      ]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { boxWidth: 12, font: { size: 10.5 } } },
        tooltip: { callbacks: { label: c => c.dataset.type === "line" ? " Meta ≤ 25 %" : (c.parsed.y != null ? ` MAPE: ${c.parsed.y} %` : " n/d (sin ítems A regulares)") } }
      },
      scales: {
        y: { beginAtZero: true, grid: { color: CC.grid }, ticks: { font: { size: 10 }, callback: v => v + " %" } },
        x: { grid: { display: false }, ticks: { font: { size: 10 } } }
      }
    }
  });
}
$("#valRefrescar").addEventListener("click", renderValidacion);
$("#valH").addEventListener("change", renderValidacion);
$("#valT0").addEventListener("change", renderValidacion);

/* ==================================================================
   REGISTRO DIRECTO (C1.2 — SARP como sistema primario del reparto)
   Escribe SOLO en la base propia de SARP vía /api/registro/*; cada
   acción queda en la bitácora y el backend recalcula todo al instante.
   Requiere backend en línea (sin cola offline en v1 — mejora futura).
   Todo render va en try/catch que muestra el error (lección aprendida).
   ================================================================== */
function hoyISO() {
  const d = new Date();
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

function poblarDatalistRegistro() {
  try {
    const dl = $("#dlItems"), dc = $("#dlCats");
    if (!dl || !dc) return;
    dl.innerHTML = S.items.map(i => `<option value="${esc(i.codigo)}">${esc(i.nombre)}</option>`).join("");
    dc.innerHTML = [...new Set(S.items.map(i => i.categoria))].sort().map(c => `<option value="${esc(c)}"></option>`).join("");
  } catch (e) { console.error("[registro] datalist:", e); }
}

function itemDeEntrada(texto) {
  const t = String(texto || "").trim().toLowerCase();
  if (!t) return null;
  return S.items.find(i => i.codigo.toLowerCase() === t) ||
    S.items.find(i => i.nombre.toLowerCase() === t) || null;
}

function pintarInfoItem() {
  try {
    const info = $("#movInfo");
    const it = itemDeEntrada($("#movItem").value);
    if (!it) { info.innerHTML = "Elija un ítem para ver su existencia actual."; return; }
    info.innerHTML = `<b>${esc(it.nombre)}</b> · existencia actual: <b>${it.existencia}</b> · ROP ${it.rop} · <span class="badge s${it.estado}">${it.estado}</span>`;
  } catch (e) { console.error("[registro] info ítem:", e); }
}

function pintarErroresRegistro(cont, data) {
  try {
    const lineas = (data && data.errores && data.errores.length)
      ? data.errores.map(e => `<div class="repline"><span class="tag err">${esc(e.campo)}</span><div>${esc(e.mensaje)}</div></div>`)
      : [`<div class="repline"><span class="tag err">ERROR</span><div>${esc((data && data.error) || "Error desconocido del backend.")}</div></div>`];
    cont.innerHTML = lineas.join("");
  } catch (e) { cont.textContent = "Error al mostrar los errores: " + e; }
}

function formsRegistroDeshabilitados(dis) {
  document.querySelectorAll("#formMov input, #formMov select, #formMov button, #formAlta input, #formAlta select, #formAlta button")
    .forEach(el => { el.disabled = dis; });
  const off = $("#regOffline"); if (off) off.style.display = dis ? "" : "none";
}

async function cargarBitacora() {
  const wrap = $("#bitacoraWrap");
  try {
    const r = await fetch("/api/bitacora?limite=20", { headers: { "Accept": "application/json" } });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    const regs = data.registros || [];
    wrap.innerHTML = regs.length
      ? `<table><thead><tr><th>Fecha y hora</th><th>Rol</th><th>Acción</th><th>Ítem</th><th>Detalle</th></tr></thead><tbody>` +
        regs.map(b => `<tr><td>${esc(b.fecha_formato || b.fecha_hora)}</td><td>${esc(b.rol)}</td><td><b>${esc(b.accion)}</b></td><td style="font-family:Consolas,monospace;font-size:12px">${esc(b.codigo_item || "—")}</td><td style="white-space:normal;min-width:260px">${esc(b.detalle)}</td></tr>`).join("") +
        `</tbody></table>`
      : `<div class="nochart" style="height:80px">Bitácora vacía: aún no hay registros directos.</div>`;
    return true;
  } catch (e) {
    wrap.innerHTML = `<div class="nochart" style="height:80px">Bitácora no disponible sin backend.</div>`;
    return false;
  }
}

async function refrescarRegistro() {
  try {
    $("#movFecha").max = hoyISO();
    if (!$("#movFecha").value) $("#movFecha").value = hoyISO();
    poblarDatalistRegistro();
    pintarInfoItem();
    const enLinea = await cargarBitacora();   // sonda: bitácora responde ⇒ backend en línea
    formsRegistroDeshabilitados(!enLinea);
  } catch (e) {
    console.error("[registro] refrescar:", e);
    toast("Error al preparar la pestaña Registro: " + (e && e.message || e));
  }
}

async function enviarRegistro(url, cuerpo, contErrores) {
  let r, data;
  try {
    r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Rol-Demo": ROL },
      body: JSON.stringify(cuerpo)
    });
    data = await r.json();
  } catch (e) {
    contErrores.innerHTML = `<div class="repline"><span class="tag err">SIN CONEXIÓN</span><div>No se pudo contactar el backend. Verifique que el servidor esté corriendo (iniciar_sarp.bat).</div></div>`;
    formsRegistroDeshabilitados(true);
    return null;
  }
  if (!r.ok) { pintarErroresRegistro(contErrores, data); return null; }
  contErrores.innerHTML = "";
  return data;
}

function iniciarRegistro() {
  try {
    $("#movItem").addEventListener("input", pintarInfoItem);
    $("#movTipo").addEventListener("change", () => {
      const ajuste = $("#movTipo").value === "ajuste";
      $("#lblMotivo").style.display = ajuste ? "" : "none";
      $("#lblReferencia").style.display = ajuste ? "none" : "";
      $("#lblCantidad").firstChild.textContent = ajuste ? "Existencia real contada" : "Cantidad";
    });

    $("#formMov").addEventListener("submit", async ev => {
      ev.preventDefault();
      try {
        const btn = $("#btnMov"); btn.disabled = true;
        const it = itemDeEntrada($("#movItem").value);
        const cuerpo = {
          codigo: it ? it.codigo : $("#movItem").value.trim(),
          tipo: $("#movTipo").value,
          cantidad: $("#movCantidad").value,
          fecha: $("#movFecha").value || undefined,
          referencia: $("#movReferencia").value.trim() || undefined,
          motivo: $("#movMotivo").value.trim() || undefined
        };
        const data = await enviarRegistro("/api/registro/movimiento", cuerpo, $("#movErrores"));
        btn.disabled = false;
        if (!data) return;
        toast(`✓ ${data.movimiento.tipo} registrado — existencia: ${data.existencia_anterior} → ${data.existencia_nueva}`);
        $("#movCantidad").value = ""; $("#movMotivo").value = ""; $("#movReferencia").value = "";
        await recargarTodo();          // KPIs/alertas/inventario reflejan el registro al instante
        pintarInfoItem();
        cargarBitacora();
      } catch (e) {
        console.error("[registro] movimiento:", e);
        $("#movErrores").innerHTML = `<div class="repline"><span class="tag err">ERROR</span><div>${esc(String(e && e.message || e))}</div></div>`;
        $("#btnMov").disabled = false;
      }
    });

    $("#formAlta").addEventListener("submit", async ev => {
      ev.preventDefault();
      try {
        const btn = $("#btnAlta"); btn.disabled = true;
        const cuerpo = {
          codigo: $("#altaCodigo").value.trim(),
          nombre: $("#altaNombre").value.trim(),
          categoria: $("#altaCategoria").value.trim(),
          unidad: $("#altaUnidad").value.trim(),
          costo_unitario: $("#altaCosto").value,
          criticidad: $("#altaCriticidad").value,
          lead_time_dias: $("#altaLT").value,
          importado: $("#altaImportado").value,
          proveedor: $("#altaProveedor").value.trim() || undefined
        };
        const data = await enviarRegistro("/api/registro/item", cuerpo, $("#altaErrores"));
        btn.disabled = false;
        if (!data) return;
        toast(`✓ Ítem ${data.item.codigo} dado de alta (política de mínimos)`);
        $("#formAlta").reset();
        await recargarTodo();
        cargarBitacora();
      } catch (e) {
        console.error("[registro] alta:", e);
        $("#altaErrores").innerHTML = `<div class="repline"><span class="tag err">ERROR</span><div>${esc(String(e && e.message || e))}</div></div>`;
        $("#btnAlta").disabled = false;
      }
    });
  } catch (e) { console.error("[registro] no se pudo iniciar el módulo:", e); }
}
iniciarRegistro();

/* ==================================================================
   Toast
   ================================================================== */
let tmr = null;
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); clearTimeout(tmr); tmr = setTimeout(() => t.classList.remove("show"), 2200); }

/* ==================================================================
   Service worker
   ================================================================== */
function registrarSW() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(err => console.warn("SW no registrado:", err));
  }
}

/* API pública mínima para los onclick inline */
window.SARPUI = { abrir, draft: toggleDraft };

iniciar();
})();

/* ==================================================================
   Helpers compartidos de las pestañas de decisión (18-jul-2026).
   Las secciones Alistamiento y Costeo viven FUERA del módulo (IIFE)
   principal; sin estas copias, `$("#alSlider")` lanzaba ReferenceError
   al cargar y ambas pestañas quedaban en blanco (defecto detectado en
   el QA visual del 18-jul; la v1 publicada lo padecía).
   ================================================================== */
const $ = s => document.querySelector(s);
const fmt$ = n => "$" + Math.round(n || 0).toLocaleString("es-EC");
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ==================================================================
   Alistamiento operativo (RBS) — /api/alistamiento (17-jul-2026)
   ================================================================== */
let alistCargado = false, alistDatos = null, chAlist = null;
function ensureAlistamiento() { if (!alistCargado) { alistCargado = true; renderAlistamiento(); } }

async function renderAlistamiento() {
  try {
    const r = await fetch("/api/alistamiento", { headers: { "Accept": "application/json" } });
    alistDatos = await r.json();
  } catch (e) {
    $("#alFrontera").textContent = "Sin datos de alistamiento disponibles (¿snapshot offline sin regenerar?).";
    return;
  }
  const d = alistDatos;
  if (!d.elegibles) { $("#alFrontera").textContent = d.frontera || "Sin ítems elegibles."; return; }
  $("#alFrontera").innerHTML = `<b>Frontera declarada:</b> ${esc(d.frontera)} ` +
    `Alistamiento con los niveles vigentes: <b>${(100 * d.alistamiento_actual).toFixed(1)} %</b>.`;
  $("#alBase").textContent = fmt$(d.presupuesto_base);

  const filas = d.recortes.filas;
  const labels = filas.map(f => "−" + f.recorte_pct + " %");
  if (chAlist) chAlist.destroy();
  chAlist = new Chart($("#chAlist"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Recorte lineal (práctica actual)", data: filas.map(f => 100 * f.alistamiento_lineal),
        borderColor: "#e5484d", backgroundColor: "transparent", tension: .25, pointRadius: 4 },
      { label: "Optimizado (mismo presupuesto)", data: filas.map(f => 100 * f.alistamiento_optimizado),
        borderColor: "#30a46c", backgroundColor: "transparent", tension: .25, pointRadius: 4 },
    ]},
    options: { maintainAspectRatio: false, scales: { y: { min: 0, max: 100,
      title: { display: true, text: "Alistamiento (%)" } } },
      plugins: { legend: { position: "bottom" } } }
  });
  pintarRecorte(0);
  pintarPlanAlist();
}

function pintarRecorte(pct) {
  const f = alistDatos && alistDatos.recortes.filas.find(x => x.recorte_pct === pct);
  if (!f) return;
  $("#alPct").textContent = pct + " %";
  $("#alLineal").textContent = (100 * f.alistamiento_lineal).toFixed(1) + " %";
  $("#alOpt").textContent = (100 * f.alistamiento_optimizado).toFixed(1) + " %";
  $("#alGan").textContent = "+" + f.ganancia_puntos.toFixed(1) + " pts";
}

function pintarPlanAlist() {
  const filas = alistDatos.plan.slice(0, 14).map(p => `<tr>
    <td>${esc(p.codigo)}</td><td>${esc(p.nombre)}</td><td>${fmt$(p.costo)}</td>
    <td style="text-align:center">${p.rop_actual} → <b>${p.r_recorte20}</b></td>
    <td style="text-align:center">${p.servicio_actual} %</td>
    <td style="text-align:center"><b>${p.servicio_recorte20} %</b></td></tr>`).join("");
  $("#alPlan").innerHTML = `<thead><tr><th>Código</th><th>Ítem</th><th>Costo u.</th>
    <th>Nivel: vigente → óptimo (−20 %)</th><th>Servicio hoy</th><th>Servicio óptimo (−20 %)</th></tr></thead>
    <tbody>${filas}</tbody>`;
}

$("#alSlider").addEventListener("input", e => pintarRecorte(+e.target.value));
/* ==================================================================
   Matriz de costeo de operación — /api/costeo (17-jul-2026)
   ================================================================== */
let costeoCargado = false, costeoDatos = null, chCosteo = null;
function ensureCosteo() { if (!costeoCargado) { costeoCargado = true; renderCosteo(); } }

async function renderCosteo() {
  try {
    const r = await fetch("/api/costeo", { headers: { "Accept": "application/json" } });
    costeoDatos = await r.json();
  } catch (e) {
    $("#coPlan").textContent = "Sin datos de costeo disponibles.";
    return;
  }
  const d = costeoDatos;
  const filas = d.modelos.map(m => `<tr>
    <td><b>${esc(m.modelo)}</b></td><td>${esc(m.nombre)}<br><small style="color:var(--mut)">${esc(m.denominacion_tipo)} · ${m.eslora_m} m</small></td>
    <td style="text-align:center">${m.unidades}</td>
    <td style="text-align:right">${fmt$(m.costo_marginal_dia)}</td>
    <td style="text-align:right">${fmt$(m.costo_pleno_dia)}</td></tr>`).join("");
  $("#coTarifas").innerHTML = `<thead><tr><th>Modelo</th><th>Unidad guardacostas</th><th>N.º</th>
    <th>Costo marginal/día<br><small>para DECIDIR</small></th><th>Costo pleno/día<br><small>para JUSTIFICAR</small></th></tr></thead>
    <tbody>${filas}</tbody>`;
  const pp = d.presupuesto_plan, pa = d.puente_alistamiento;
  $("#coPlan").innerHTML = `Para sostener el plan completo se necesita un presupuesto <b>operativo</b> de <b>${fmt$(pp.operativo_minimo)}</b>/año ` +
    `(el costo fijo de tener las unidades en alistamiento —${fmt$(pp.costo_fijo_contexto)}— es una asignación aparte, ya comprometida). ` +
    (pa && pa.a_c != null ? `<br>Puente con el abastecimiento: el alistamiento del material crítico del tipo ${esc(pa.tipo)} es <b>${(100 * pa.a_c).toFixed(1)}%</b>, y fija los días de mar que esa clase puede entregar.` : "");

  const c = d.curva;
  const labels = c.map(p => fmt$(p.presupuesto_operativo));
  if (chCosteo) chCosteo.destroy();
  chCosteo = new Chart($("#chCosteo"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Vida humana (SAR) — priorizado por doctrina", data: c.map(p => 100 * p.sar_priorizada),
        borderColor: "#30a46c", backgroundColor: "transparent", tension: .2, pointRadius: 0, borderWidth: 3 },
      { label: "Vida humana (SAR) — reparto parejo", data: c.map(p => 100 * p.sar_pareja),
        borderColor: "#e5484d", backgroundColor: "transparent", tension: .2, pointRadius: 0, borderWidth: 2, borderDash: [5, 4] },
    ] },
    options: { maintainAspectRatio: false,
      scales: { y: { min: 0, max: 100, title: { display: true, text: "Cobertura de la operación SAR (%)" } },
                x: { title: { display: true, text: "Presupuesto operativo anual (USD)" }, ticks: { maxTicksLimit: 6 } } },
      plugins: { legend: { position: "bottom" } } }
  });
  pintarCosteoBarras(0);
  renderEscalera();
  initRubroSelector();
  initFichaSelector();
}

function pintarCosteoBarras(pct) {
  const em = costeoDatos.escenario_recorte;
  const obj = em[String(pct)] || em[pct];
  $("#coPct").textContent = "recorte " + pct + " %";
  $("#coPctL").textContent = pct + " %";
  if (!obj) { $("#coBarras").innerHTML = "<p class='valintro'>Escenario no disponible.</p>"; return; }
  const pr = obj.priorizado.operaciones, pa = obj.parejo.operaciones;
  const orden = Object.keys(pr).sort((a, b) => pr[b].peso - pr[a].peso);
  const barra = (v, color) => `<div style="background:${color};height:14px;width:${v}%;border-radius:3px;min-width:2px"></div>`;
  $("#coBarras").innerHTML = orden.map(o => `<div style="margin:8px 0">
    <div style="font-size:12.5px;margin-bottom:3px"><b>${esc(pr[o].nombre)}</b> <small style="color:var(--mut)">(prioridad ${pr[o].peso})</small></div>
    <div style="display:grid;grid-template-columns:110px 1fr 42px;gap:6px;align-items:center;font-size:11.5px">
      <span>Priorizado</span>${barra(100 * pr[o].cobertura, "#30a46c")}<span>${Math.round(100 * pr[o].cobertura)}%</span>
      <span style="color:var(--mut)">Parejo</span>${barra(100 * pa[o].cobertura, "#e5484d")}<span>${Math.round(100 * pa[o].cobertura)}%</span>
    </div></div>`).join("");
  const bm = obj.priorizado.unidades_bajo_minimo || [];
  const dc = obj.priorizado.dias_por_clase || {};
  const resumenClases = Object.keys(dc).map(c => `${c}: ${dc[c]} d`).join(" · ");
  $("#coBajoMin").innerHTML = (bm.length
    ? `⚠️ <b>Clases bajo su presencia mínima:</b> ${bm.map(esc).join(", ")} — con este presupuesto no sostienen la presencia que el mando fijó para su zona.`
    : `✅ <b>Todas las clases sostienen su presencia mínima</b> con este presupuesto.`)
    + `<br><small style="color:var(--mut)">Días de mar por clase (priorizado): ${esc(resumenClases)}</small>`;
}

document.getElementById("coSlider").addEventListener("input", e => pintarCosteoBarras(+e.target.value));

/* Escalera marginal unificada — /api/costeo/escalera */
async function renderEscalera() {
  let d;
  try {
    const r = await fetch("/api/costeo/escalera", { headers: { "Accept": "application/json" } });
    d = await r.json();
  } catch (e) { $("#coEscalera").textContent = "Escalera no disponible."; return; }
  const e = d.escalera;
  const compras = e.decisiones.filter(x => x.tipo === "repuesto");
  const primeras = e.decisiones.slice(0, 14);
  $("#coEscalera").innerHTML = `
    <p style="font-size:12.5px">Con <b>${fmt$(e.presupuesto_total)}</b> de presupuesto único, la escalera ejecutó
    <b>${e.repuestos_comprados}</b> compras de repuestos (alistamiento LGI: ${(100 * (d.escenario.alistamiento_base.LGI)).toFixed(0)}% → <b>${(100 * e.a_lgi_final).toFixed(1)}%</b>)
    intercaladas con los días de mar, y alcanzó una cobertura ponderada del <b>${(100 * e.cobertura_ponderada).toFixed(1)}%</b>.</p>
    <div style="overflow-x:auto"><table><thead><tr><th>#</th><th>Decisión</th><th style="text-align:right">Costo</th><th style="text-align:right">Acumulado</th></tr></thead>
    <tbody>${primeras.map((x, i) => `<tr style="${x.tipo === "repuesto" ? "background:rgba(48,164,108,.12);font-weight:600" : ""}">
      <td class="num">${i + 1}</td><td>${x.tipo === "repuesto" ? "🔧 " : ""}${esc(x.detalle)}</td>
      <td class="num">${fmt$(x.costo)}</td><td class="num">${fmt$(x.acumulado)}</td></tr>`).join("")}</tbody></table></div>
    <p style="font-size:11.5px;color:var(--mut);margin-top:6px">${esc(e.nota)}</p>`;
}

/* Ficha logística digital — /api/costeo/ficha/{clase} */
async function renderFicha(modelo) {
  let f;
  try {
    const r = await fetch("/api/costeo/ficha/" + modelo, { headers: { Accept: "application/json" } });
    f = await r.json();
  } catch (e) { $("#coFicha").textContent = "Ficha no disponible."; return; }
  const c = f.caracteristicas, u = f.unidades || [];
  $("#coFicha").innerHTML = `
    <p style="font-size:12.5px"><b>${esc(f.nombre)}</b> — ${esc(f.denominacion_tipo)} (${esc(f.tipo)})<br>
    <small style="color:var(--mut)">Constructor: ${esc(f.constructor || "—")} · ${u.length} unidad(es)</small></p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:12px">
      <div><b>Características</b><br><small>
        Eslora <b>${c.eslora_m} m</b> · tripulación <b>${c.tripulacion}</b><br>
        Velocidad máx. <b>${c.velocidad_max_kt} kt</b> · económica <b>${c.velocidad_economica_kt} kt</b><br>
        Autonomía <b>${c.autonomia_mn} mn</b> · ${c.num_motores} motores · ${c.potencia_hp} HP<br>
        Días operables/año: <b>${c.dias_operables}</b></small></div>
      <div><b>Costeo y alistamiento</b><br><small>
        Costo pleno/día: <b>${fmt$(f.tarifas.pleno_dia)}</b> (justificar)<br>
        Costo marginal/día: <b>${fmt$(f.tarifas.marginal_dia)}</b> (decidir)<br>
        ${f.alistamiento_repuestos != null ? `Alistamiento del material: <b>${(100 * f.alistamiento_repuestos).toFixed(1)}%</b><br>` : ""}
        </small></div>
    </div>
    <div style="margin-top:10px;font-size:12px"><b>Unidades de este modelo:</b>
      ${u.map(x => `<span style="display:inline-block;margin:2px 4px 2px 0;padding:2px 8px;background:var(--bg2,#eef2f7);border-radius:10px">${esc(x.numeral)} ${esc(x.nombre)} <small style="color:var(--mut)">${esc(x.subcomando)}</small></span>`).join("")}</div>
    <div style="margin-top:10px;font-size:12px"><b>Niveles logísticos doctrinarios → sistema</b><br>
      <small style="color:var(--mut)">${esc(f.niveles_logisticos.equivalencia)}</small></div>
    <p style="font-size:11.5px;color:var(--mut);margin-top:8px"><i>${esc(f.nota || "")}</i></p>`;
}

/* Desglose del día de mar por rubros — /api/costeo/rubros/{modelo} */
async function renderRubros(modelo) {
  let d;
  try {
    const r = await fetch("/api/costeo/rubros/" + modelo, { headers: { Accept: "application/json" } });
    d = await r.json();
  } catch (e) { $("#coRubros").textContent = "Desglose no disponible."; return; }
  const filaVar = x => `<tr><td><b>${esc(x.codigo)}</b></td><td>${esc(x.nombre)}</td>
    <td style="font-size:11.5px;color:var(--mut)">${esc(x.base || "")}</td>
    <td class="num"><b>${fmt$(x.usd_dia)}</b></td></tr>`;
  const comb = d.variables.find(x => x.codigo === "A1");
  const detalleComb = comb && comb.detalle ? `
    <div style="margin:8px 0 12px;padding:8px;background:#f4f6f9;border-radius:6px">
      <div style="font-size:12px;font-weight:600;margin-bottom:4px">Combustible por régimen de velocidad</div>
      <table style="font-size:11.5px"><thead><tr><th>Régimen</th><th class="num">h/día</th><th class="num">gal/h</th><th class="num">galones</th><th class="num">USD</th></tr></thead>
      <tbody>${comb.detalle.map(r => `<tr><td>${esc(r.regimen)}</td><td class="num">${r.horas}</td>
        <td class="num">${r.gal_h}</td><td class="num">${r.galones}</td><td class="num">${fmt$(r.usd)}</td></tr>`).join("")}</tbody></table>
      <div style="font-size:11px;color:var(--mut);margin-top:4px">El salto entre el régimen económico y el máximo es de un orden de magnitud: por eso el perfil del día de mar es un parámetro de mando, no un detalle técnico.</div>
    </div>` : "";
  $("#coRubros").innerHTML = `
    <div style="overflow-x:auto"><table>
      <thead><tr><th colspan="4" style="background:#0b2545;color:#fff">VARIABLES — se devengan solo si la unidad zarpa (tarifa marginal, para DECIDIR)</th></tr>
      <tr><th>Cód.</th><th>Rubro</th><th>Cálculo</th><th class="num">USD/día de mar</th></tr></thead>
      <tbody>${d.variables.map(filaVar).join("")}
        <tr style="border-top:2px solid #0b2545"><td colspan="3"><b>Costo marginal del día de mar</b></td><td class="num"><b>${fmt$(d.cv_dia)}</b></td></tr></tbody>
    </table></div>
    ${detalleComb}
    <div style="overflow-x:auto"><table>
      <thead><tr><th colspan="2" style="background:#5a6678;color:#fff">FIJOS ANUALES — se devengan navegue o no (solo entran a la tarifa plena, para JUSTIFICAR)</th></tr>
      <tr><th>Rubro</th><th class="num">USD/año por unidad</th></tr></thead>
      <tbody>${d.fijos.map(x => `<tr><td>${esc(x.nombre)}</td><td class="num">${fmt$(x.usd_anual)}</td></tr>`).join("")}
        <tr style="border-top:2px solid #5a6678"><td><b>Costo fijo anual</b></td><td class="num"><b>${fmt$(d.cf_anual)}</b></td></tr></tbody>
    </table></div>
    <p style="font-size:11.5px;color:var(--mut);margin-top:8px">${esc(d.nota || "")}
      · Horas de navegación del día: <b>${d.h_nav_dia}</b> · Galones/día: <b>${d.galones_dia}</b></p>`;
}

function initRubroSelector() {
  const sel = document.getElementById("coRubroSel");
  if (!sel || sel.options.length) return;
  (costeoDatos ? costeoDatos.modelos : []).forEach(m => {
    const o = document.createElement("option");
    o.value = m.modelo; o.textContent = `${m.modelo} — ${m.nombre} (${m.tipo})`;
    sel.appendChild(o);
  });
  sel.addEventListener("change", () => renderRubros(sel.value));
  if (sel.options.length) renderRubros(sel.options[0].value);
}

function initFichaSelector() {
  const sel = document.getElementById("coFichaSel");
  if (!sel || sel.options.length) return;
  (costeoDatos ? costeoDatos.modelos : []).forEach(m => {
    const o = document.createElement("option");
    o.value = m.modelo; o.textContent = `${m.modelo} — ${m.nombre}`;
    sel.appendChild(o);
  });
  sel.addEventListener("change", () => renderFicha(sel.value));
  if (sel.options.length) renderFicha(sel.options[0].value);
}

/* ==================================================================
   PANEL DE CONFIGURACIÓN — /api/config (18-jul-2026)
   Aquí el reparto reemplaza los valores referenciales por los suyos.
   Patrón «revisar antes de confirmar»: nada se guarda sin que el
   oficial vea el impacto de su cambio en los indicadores de mando.
   ================================================================== */
let configCargada = false, configDatos = null, cambiosPendientes = [];
function ensureConfig() { if (!configCargada) { configCargada = true; renderConfig(); } }

const ORIGEN_COLOR = {
  referencial: "#9fb3cf", literatura: "#6b8fb5", institucional: "#1e7d4f",
  medido: "#13315c", estimado: "#c6a441"
};
const insigniaOrigen = o => `<span title="Procedencia del dato" style="display:inline-block;padding:1px 7px;border-radius:9px;font-size:10.5px;color:#fff;background:${ORIGEN_COLOR[o] || "#888"}">${esc(o || "referencial")}</span>`;

async function renderConfig() {
  let d;
  try {
    const r = await fetch("/api/config", { headers: { Accept: "application/json" } });
    d = await r.json(); configDatos = d;
  } catch (e) { $("#cfParametros").textContent = "Configuración no disponible."; return; }

  const mv = d.madurez.vector;
  $("#cfMadurez").innerHTML = `
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:12.5px">
      <div><b>${d.madurez.pct_institucional_o_medido}%</b> de los parámetros locales ya son institucionales o medidos</div>
      <div>${Object.entries(mv).filter(([, n]) => n > 0).map(([o, n]) => `${insigniaOrigen(o)} ${n}`).join(" &nbsp; ")}</div>
    </div>
    ${d.madurez.pendientes.length ? `<div style="font-size:11.5px;color:var(--mut);margin-top:6px">
      <b>Pendientes de cargar con dato propio:</b> ${d.madurez.pendientes.slice(0, 6).map(esc).join(" · ")}${d.madurez.pendientes.length > 6 ? ` y ${d.madurez.pendientes.length - 6} más` : ""}</div>` : ""}
    <div style="font-size:11px;color:var(--mut);margin-top:4px">${esc(d.madurez.nota)}</div>`;

  $("#cfParametros").innerHTML = `<div style="overflow-x:auto"><table>
    <thead><tr><th>Parámetro</th><th class="num">Valor</th><th>Unidad</th><th>Procedencia</th><th>Fuente</th></tr></thead>
    <tbody>${Object.entries(d.parametros).map(([k, p]) => `<tr>
      <td>${esc(p.etiqueta)}</td>
      <td class="num"><input data-sec="parametros" data-clave="${esc(k)}" data-campo="valor" class="cfInput"
        type="number" step="any" value="${p.valor}" style="width:110px;padding:4px;text-align:right"></td>
      <td style="font-size:11.5px">${esc(p.unidad)}</td>
      <td>${insigniaOrigen(p.origen)}</td>
      <td style="font-size:11px;color:var(--mut)">${esc(p.fuente || "—")}</td></tr>`).join("")}</tbody></table></div>`;

  $("#cfOperaciones").innerHTML = `<div style="overflow-x:auto"><table>
    <thead><tr><th>Operación</th><th class="num">Prioridad</th><th class="num">Días mínimos</th><th class="num">Días del plan</th></tr></thead>
    <tbody>${Object.entries(d.operaciones).map(([k, o]) => `<tr>
      <td>${esc(o.nombre)}<br><small style="color:var(--mut)">${esc(o.responde_a)}</small></td>
      <td class="num">${o.peso}</td>
      <td class="num"><input data-sec="operaciones" data-clave="${esc(k)}" data-campo="min_dias" class="cfInput"
        type="number" value="${o.min_dias}" style="width:90px;padding:4px;text-align:right"></td>
      <td class="num"><input data-sec="operaciones" data-clave="${esc(k)}" data-campo="req_dias" class="cfInput"
        type="number" value="${o.req_dias}" style="width:90px;padding:4px;text-align:right"></td></tr>`).join("")}</tbody></table></div>
    <p style="font-size:11.5px;color:var(--mut);margin-top:6px">La prioridad la fija la doctrina de empleo y no se edita aquí. Los días mínimos no pueden superar los del plan.</p>`;

  $("#cfModelos").innerHTML = `<div style="overflow-x:auto"><table>
    <thead><tr><th>Modelo</th><th class="num">Unid.</th><th class="num">Días operables</th>
      <th class="num">Mantto. USD/h</th><th class="num">Repuestos USD/día</th><th>Procedencia</th></tr></thead>
    <tbody>${Object.entries(d.modelos).map(([k, m]) => `<tr>
      <td><b>${esc(k)}</b> ${esc(m.nombre)}<br><small style="color:var(--mut)">${esc(m.tipo)} · ${esc(m.constructor)}</small></td>
      <td class="num">${m.unidades.length}</td>
      <td class="num"><input data-sec="modelos" data-clave="${esc(k)}" data-campo="dias_operables" class="cfInput"
        type="number" value="${m.dias_operables}" style="width:80px;padding:4px;text-align:right"></td>
      <td class="num"><input data-sec="modelos" data-clave="${esc(k)}" data-campo="mantto_prev_usd_h" class="cfInput"
        type="number" step="any" value="${m.mantto_prev_usd_h}" style="width:90px;padding:4px;text-align:right"></td>
      <td class="num"><input data-sec="modelos" data-clave="${esc(k)}" data-campo="repuestos_usd_dia" class="cfInput"
        type="number" step="any" value="${m.repuestos_usd_dia}" style="width:90px;padding:4px;text-align:right"></td>
      <td>${insigniaOrigen(m.origen)}</td></tr>`).join("")}</tbody></table></div>`;

  document.querySelectorAll(".cfInput").forEach(inp => {
    inp.dataset.original = inp.value;
    inp.addEventListener("change", recogerCambios);
  });
  renderBitacoraConfig();
}

function recogerCambios() {
  cambiosPendientes = [...document.querySelectorAll(".cfInput")]
    .filter(i => i.value !== i.dataset.original && i.value !== "")
    .map(i => ({ seccion: i.dataset.sec, clave: i.dataset.clave,
                 campo: i.dataset.campo, valor: parseFloat(i.value) }));
  if (!cambiosPendientes.length) { $("#cfRevisarCard").style.display = "none"; return; }
  previsualizarCambios();
}

async function previsualizarCambios() {
  const card = $("#cfRevisarCard"); card.style.display = "";
  $("#cfRevisar").innerHTML = "Calculando el impacto…";
  let r;
  try {
    const resp = await fetch("/api/config/impacto", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cambiosPendientes) });
    r = await resp.json();
    if (!resp.ok) {
      $("#cfRevisar").innerHTML = `<div class="notec" style="background:var(--warnbg);border-left-color:var(--warn)"><b>No se puede aplicar:</b> ${esc(r.detail || "valor inválido")}</div>`;
      return;
    }
  } catch (e) { $("#cfRevisar").textContent = "No se pudo calcular el impacto."; return; }

  const ETQ = {
    presupuesto_operativo_plan: "Presupuesto operativo del plan",
    costo_fijo_anual: "Costo fijo anual",
    dias_de_mar_del_plan: "Días de mar del plan",
    cobertura_ponderada: "Cobertura del plan",
    cobertura_vida_humana: "Cobertura de vida humana (SAR)",
    tipos_bajo_presencia_minima: "Tipos bajo presencia mínima",
  };
  const fmtInd = (k, v) => k.startsWith("cobertura") ? Math.round(100 * v) + "%"
    : (k.includes("presupuesto") || k.includes("costo")) ? fmt$(v) : Math.round(v).toLocaleString("es-EC");
  $("#cfRevisar").innerHTML = `
    <div style="overflow-x:auto"><table><thead><tr><th>Parámetro</th><th class="num">Antes</th><th class="num">Después</th></tr></thead>
      <tbody>${r.cambios.map(c => `<tr><td>${esc(c.seccion)} · ${esc(c.clave)} · ${esc(c.campo)}</td>
        <td class="num">${esc(String(c.antes))}</td><td class="num"><b>${esc(String(c.despues))}</b></td></tr>`).join("")}</tbody></table></div>
    <div style="margin-top:10px;font-weight:600;font-size:13px">Impacto en los indicadores de mando</div>
    <div style="overflow-x:auto"><table><thead><tr><th>Indicador</th><th class="num">Antes</th><th class="num">Después</th><th class="num">Variación</th></tr></thead>
      <tbody>${Object.keys(ETQ).map(k => {
        const a = r.antes[k], b = r.despues[k], dif = b - a;
        const color = Math.abs(dif) < 1e-9 ? "var(--mut)" : (dif > 0 ? "#1e7d4f" : "#b3261e");
        return `<tr><td>${ETQ[k]}</td><td class="num">${fmtInd(k, a)}</td><td class="num"><b>${fmtInd(k, b)}</b></td>
          <td class="num" style="color:${color}">${Math.abs(dif) < 1e-9 ? "—" : (dif > 0 ? "▲" : "▼") + " " + fmtInd(k, Math.abs(dif))}</td></tr>`;
      }).join("")}</tbody></table></div>`;
}

async function confirmarCambios() {
  const motivo = $("#cfMotivo").value.trim();
  if (motivo.length < 3) { toast("Escriba el motivo del cambio (queda en bitácora)"); $("#cfMotivo").focus(); return; }
  try {
    const resp = await fetch("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cambios: cambiosPendientes, motivo,
                             responsable: $("#cfResponsable").value.trim() }) });
    const r = await resp.json();
    if (!resp.ok) { toast("No se guardó: " + (r.detail || "valor inválido")); return; }
    toast(`${r.guardados} parámetro(s) guardado(s)`);
    cambiosPendientes = []; $("#cfRevisarCard").style.display = "none";
    $("#cfMotivo").value = ""; configCargada = false; costeoCargado = false;
    S.mando = null; renderConfig();
  } catch (e) { toast("No se pudo guardar la configuración"); }
}

async function renderBitacoraConfig() {
  try {
    const r = await fetch("/api/config/bitacora?limite=15", { headers: { Accept: "application/json" } });
    const d = await r.json();
    $("#cfBitacora").innerHTML = d.eventos.length ? `<div style="overflow-x:auto"><table>
      <thead><tr><th>Fecha</th><th>Parámetro</th><th class="num">Antes</th><th class="num">Después</th><th>Motivo</th><th>Responsable</th></tr></thead>
      <tbody>${d.eventos.map(e => `<tr>
        <td style="font-size:11.5px">${esc((e.fecha_hora || "").replace("T", " "))}</td>
        <td style="font-size:11.5px">${esc(e.clave)} · ${esc(e.campo)}</td>
        <td class="num">${esc(e.valor_previo || "—")}</td><td class="num"><b>${esc(e.valor_nuevo || "—")}</b></td>
        <td style="font-size:11.5px">${esc(e.motivo || "")}</td>
        <td style="font-size:11.5px">${esc(e.responsable || "")}</td></tr>`).join("")}</tbody></table></div>`
      : `<p style="font-size:12.5px;color:var(--mut)">Sin cambios registrados: la plataforma opera con los valores referenciales.</p>`;
  } catch (e) { $("#cfBitacora").textContent = "Bitácora no disponible."; }
}

document.getElementById("cfConfirmar").addEventListener("click", confirmarCambios);
document.getElementById("cfCancelar").addEventListener("click", () => {
  document.querySelectorAll(".cfInput").forEach(i => { i.value = i.dataset.original; });
  cambiosPendientes = []; $("#cfRevisarCard").style.display = "none";
});
document.getElementById("cfRestaurar").addEventListener("click", async () => {
  if (!confirm("¿Restaurar todos los parámetros a sus valores referenciales?\n\nLa bitácora NO se borra: la restauración queda registrada como un evento más.")) return;
  try {
    await fetch("/api/config/restaurar", { method: "POST" });
    toast("Valores referenciales restaurados");
    configCargada = false; costeoCargado = false; S.mando = null; renderConfig();
  } catch (e) { toast("No se pudo restaurar"); }
});
