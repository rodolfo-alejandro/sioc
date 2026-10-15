(function () {
  "use strict";

  var cfg = window.CV_APP || {};
  var KEY = "sioc_comando_vivo_v1";
  var CLIP_MS = 4000;
  var watchId = null;
  var lastPos = null;
  var pingTimer = null;
  var session = null;

  var mediaStream = null;
  var mediaRecorder = null;
  var audioOn = false;
  var audioLoopTimer = null;
  var preferredMime = "";

  var elJoin = document.getElementById("cv-join");
  var elLive = document.getElementById("cv-live");
  var elStatus = document.getElementById("cv-status");
  var elCoords = document.getElementById("cv-coords");
  var elPingInfo = document.getElementById("cv-ping-info");
  var elJoinErr = document.getElementById("cv-join-err");
  var elBtnPanico = document.getElementById("cv-btn-panico");
  var elBtnOk = document.getElementById("cv-btn-ok");
  var elBtnAudio = document.getElementById("cv-btn-audio");
  var elAudioInfo = document.getElementById("cv-audio-info");

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
    setAudioUi(false);
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

  function pickMime() {
    if (!window.MediaRecorder) return "";
    var candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    for (var i = 0; i < candidates.length; i++) {
      if (MediaRecorder.isTypeSupported(candidates[i])) return candidates[i];
    }
    return "";
  }

  function setAudioUi(on) {
    audioOn = on;
    if (!elBtnAudio) return;
    if (on) {
      elBtnAudio.classList.add("on");
      elBtnAudio.textContent = "⏹ Detener audio";
      elAudioInfo.textContent = "Transmitiendo… el comando te escucha en clips de ~4 s.";
    } else {
      elBtnAudio.classList.remove("on");
      elBtnAudio.textContent = "🎤 Transmitir audio";
      elAudioInfo.textContent = "El comando podrá escucharte casi en vivo.";
    }
  }

  function uploadBlob(blob, mime, durationMs) {
    if (!session || !session.token || !blob || !blob.size) return Promise.resolve();
    var fd = new FormData();
    fd.append("token", session.token);
    fd.append("mime", mime || blob.type || "audio/webm");
    if (durationMs) fd.append("duration_ms", String(durationMs));
    fd.append("audio", blob, "clip.webm");
    return fetch(cfg.audioUrl, { method: "POST", body: fd })
      .then(function (r) {
        return r.json().then(function (j) {
          return { okHttp: r.ok, body: j };
        });
      })
      .then(function (res) {
        if (res.okHttp && res.body.ok) {
          elAudioInfo.textContent =
            "Audio enviado " + new Date().toLocaleTimeString();
        } else {
          elAudioInfo.textContent =
            "Error audio: " + ((res.body && res.body.error) || "red");
        }
      })
      .catch(function () {
        elAudioInfo.textContent = "Error de red al enviar audio.";
      });
  }

  function recordOneClip() {
    if (!audioOn || !mediaStream) return Promise.resolve();
    preferredMime = preferredMime || pickMime();
    var chunks = [];
    var opts = preferredMime ? { mimeType: preferredMime } : undefined;
    var rec;
    try {
      rec = new MediaRecorder(mediaStream, opts);
    } catch (e) {
      try {
        rec = new MediaRecorder(mediaStream);
      } catch (e2) {
        elAudioInfo.textContent = "No se pudo iniciar el micrófono.";
        return Promise.resolve();
      }
    }
    mediaRecorder = rec;
    return new Promise(function (resolve) {
      rec.ondataavailable = function (ev) {
        if (ev.data && ev.data.size) chunks.push(ev.data);
      };
      rec.onstop = function () {
        var type = preferredMime || rec.mimeType || "audio/webm";
        var blob = new Blob(chunks, { type: type.split(";")[0] });
        uploadBlob(blob, type, CLIP_MS).finally(resolve);
      };
      try {
        rec.start();
      } catch (e) {
        resolve();
        return;
      }
      setTimeout(function () {
        if (rec.state !== "inactive") {
          try {
            rec.stop();
          } catch (e) {
            resolve();
          }
        }
      }, CLIP_MS);
    });
  }

  function audioLoop() {
    if (!audioOn) return;
    recordOneClip().finally(function () {
      if (audioOn) {
        audioLoopTimer = setTimeout(audioLoop, 200);
      }
    });
  }

  function startAudio() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Este celular no permite micrófono desde el navegador.");
      return;
    }
    if (!window.MediaRecorder) {
      alert("MediaRecorder no disponible en este navegador. Probá Chrome.");
      return;
    }
    preferredMime = pickMime();
    navigator.mediaDevices
      .getUserMedia({ audio: true, video: false })
      .then(function (stream) {
        mediaStream = stream;
        setAudioUi(true);
        setStatus("GPS + Audio", "on");
        audioLoop();
      })
      .catch(function (err) {
        alert("Permiso de micrófono denegado: " + (err.message || err.name));
      });
  }

  function stopAudio() {
    audioOn = false;
    if (audioLoopTimer) {
      clearTimeout(audioLoopTimer);
      audioLoopTimer = null;
    }
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      try {
        mediaRecorder.stop();
      } catch (e) {}
    }
    mediaRecorder = null;
    if (mediaStream) {
      mediaStream.getTracks().forEach(function (t) {
        t.stop();
      });
      mediaStream = null;
    }
    setAudioUi(false);
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
            stopAudio();
            stopTracking();
            clearSession();
            showJoin();
            showErr("Operativo cerrado.");
          }
          return;
        }
        var now = new Date();
        elPingInfo.textContent =
          "GPS " +
          now.toLocaleTimeString() +
          (evento === "panico" ? " · PÁNICO" : "") +
          (audioOn ? " · 🎤" : "");
        if (res.body.estado === "panico") {
          setStatus("PÁNICO", "panic");
          elBtnOk.hidden = false;
        } else if (!audioOn) {
          setStatus("Enviando GPS", "on");
          elBtnOk.hidden = true;
        } else {
          setStatus("GPS + Audio", "on");
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

  if (elBtnAudio) {
    elBtnAudio.addEventListener("click", function () {
      if (audioOn) stopAudio();
      else startAudio();
    });
  }

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
        setStatus(audioOn ? "GPS + Audio" : "Enviando GPS", "on");
        elBtnOk.hidden = true;
      }
    });
  });

  document.getElementById("cv-btn-salir").addEventListener("click", function () {
    stopAudio();
    stopTracking();
    clearSession();
    showJoin();
  });

  var prev = loadSession();
  if (prev && prev.token && prev.operativo) {
    session = prev;
    showLive(prev.operativo);
    setStatus("Reconectando…");
    startTracking();
  }

  if ("serviceWorker" in navigator && cfg.swUrl) {
    navigator.serviceWorker.register(cfg.swUrl).catch(function () {});
  }
})();
