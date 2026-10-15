(function () {
  "use strict";

  var cfg = window.CV_APP || {};
  var KEY = "sioc_comando_vivo_v1";
  var watchId = null;
  var lastPos = null;
  var pingTimer = null;
  var session = null;

  var elJoin = document.getElementById("cv-join");
  var elLive = document.getElementById("cv-live");
  var elStatus = document.getElementById("cv-status");
  var elCoords = document.getElementById("cv-coords");
  var elPingInfo = document.getElementById("cv-ping-info");
  var elJoinErr = document.getElementById("cv-join-err");
  var elBtnPanico = document.getElementById("cv-btn-panico");
  var elBtnOk = document.getElementById("cv-btn-ok");

  function deviceId() {
    var k = "sioc_cv_device";
    var id = localStorage.getItem(k);
    if (!id) {
      id = "d_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(k, id);
    }
    return id;
  }

  function saveSession(s) {
    session = s;
    localStorage.setItem(KEY, JSON.stringify(s));
  }

  function loadSession() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || "null");
    } catch (e) {
      return null;
    }
  }

  function clearSession() {
    session = null;
    localStorage.removeItem(KEY);
  }

  function setStatus(text, cls) {
    elStatus.textContent = text;
    elStatus.className = "cv-app-badge" + (cls ? " " + cls : "");
  }

  function showErr(msg) {
    elJoinErr.hidden = !msg;
    elJoinErr.textContent = msg || "";
  }

  function showLive(op) {
    elJoin.hidden = true;
    elLive.hidden = false;
    document.getElementById("cv-op-nombre").textContent = op.nombre || "Operativo";
    document.getElementById("cv-op-codigo").textContent = op.codigo || "";
  }

  function showJoin() {
    elJoin.hidden = false;
    elLive.hidden = true;
    setStatus("Desconectado");
  }

  function batteryPromise() {
    if (!navigator.getBattery) return Promise.resolve(null);
    return navigator
      .getBattery()
      .then(function (b) {
        return Math.round(b.level * 100);
      })
      .catch(function () {
        return null;
      });
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.json().then(function (j) {
        return { okHttp: r.ok, status: r.status, body: j };
      });
    });
  }

  function sendPing(evento) {
    if (!session || !session.token || !lastPos) return Promise.resolve();
    var url = evento === "panico" ? cfg.panicoUrl : cfg.pingUrl;
    return batteryPromise().then(function (bat) {
      return postJson(url, {
        token: session.token,
        lat: lastPos.lat,
        lon: lastPos.lon,
        accuracy: lastPos.accuracy,
        speed: lastPos.speed,
        heading: lastPos.heading,
        battery: bat,
      }).then(function (res) {
        if (!res.okHttp) {
          elPingInfo.textContent = "Error envío: " + (res.body.error || res.status);
          if (res.status === 409) {
            stopTracking();
            clearSession();
            showJoin();
            showErr("Operativo cerrado.");
          }
          return;
        }
        var now = new Date();
        elPingInfo.textContent =
          "Último envío " +
          now.toLocaleTimeString() +
          (evento === "panico" ? " · PÁNICO" : "");
        if (res.body.estado === "panico") {
          setStatus("PÁNICO", "panic");
          elBtnOk.hidden = false;
        } else {
          setStatus("Enviando GPS", "on");
          elBtnOk.hidden = true;
        }
      });
    });
  }

  function onPosition(pos) {
    lastPos = {
      lat: pos.coords.latitude,
      lon: pos.coords.longitude,
      accuracy: pos.coords.accuracy,
      speed: pos.coords.speed,
      heading: pos.coords.heading,
    };
    elCoords.textContent =
      lastPos.lat.toFixed(6) +
      ", " +
      lastPos.lon.toFixed(6) +
      " (±" +
      Math.round(lastPos.accuracy || 0) +
      " m)";
  }

  function onPosError(err) {
    elCoords.textContent = "GPS: " + (err.message || "sin permiso / sin señal");
    setStatus("Sin GPS");
  }

  function startTracking() {
    if (!navigator.geolocation) {
      showErr("Este celular no soporta geolocalización.");
      return;
    }
    if (watchId != null) return;
    watchId = navigator.geolocation.watchPosition(onPosition, onPosError, {
      enableHighAccuracy: true,
      maximumAge: 3000,
      timeout: 15000,
    });
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(function () {
      sendPing("ping");
    }, 5000);
    // primer ping apenas haya coords
    var tries = 0;
    var boot = setInterval(function () {
      tries += 1;
      if (lastPos) {
        clearInterval(boot);
        sendPing("ping");
      } else if (tries > 20) {
        clearInterval(boot);
      }
    }, 500);
  }

  function stopTracking() {
    if (watchId != null) {
      navigator.geolocation.clearWatch(watchId);
      watchId = null;
    }
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  document.getElementById("cv-btn-join").addEventListener("click", function () {
    showErr("");
    var codigo = (document.getElementById("cv-codigo").value || "").trim();
    var alias = (document.getElementById("cv-alias").value || "").trim();
    if (!codigo || !alias) {
      showErr("Completá código y nombre.");
      return;
    }
    postJson(cfg.joinUrl, {
      codigo: codigo,
      alias: alias,
      device_id: deviceId(),
    })
      .then(function (res) {
        if (!res.okHttp || !res.body.ok) {
          showErr(
            res.body.error === "codigo_invalido_o_cerrado"
              ? "Código inválido o operativo cerrado."
              : res.body.error || "No se pudo unir."
          );
          return;
        }
        saveSession({
          token: res.body.token,
          participante_id: res.body.participante_id,
          operativo: res.body.operativo,
        });
        showLive(res.body.operativo);
        setStatus("Conectando…");
        startTracking();
      })
      .catch(function () {
        showErr("Error de red.");
      });
  });

  elBtnPanico.addEventListener("click", function () {
    if (!confirm("¿Enviar alerta de PÁNICO al centro de comando?")) return;
    if (!lastPos) {
      alert("Todavía no hay posición GPS.");
      return;
    }
    sendPing("panico");
  });

  elBtnOk.addEventListener("click", function () {
    if (!session) return;
    postJson(cfg.okUrl, { token: session.token }).then(function (res) {
      if (res.okHttp) {
        setStatus("Enviando GPS", "on");
        elBtnOk.hidden = true;
      }
    });
  });

  document.getElementById("cv-btn-salir").addEventListener("click", function () {
    stopTracking();
    clearSession();
    showJoin();
  });

  // Restaurar sesión
  var prev = loadSession();
  if (prev && prev.token && prev.operativo) {
    session = prev;
    showLive(prev.operativo);
    setStatus("Reconectando…");
    startTracking();
  }

  // Service worker PWA (opcional)
  if ("serviceWorker" in navigator && cfg.swUrl) {
    navigator.serviceWorker.register(cfg.swUrl).catch(function () {});
  }
})();
