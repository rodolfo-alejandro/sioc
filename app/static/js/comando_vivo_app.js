(function () {
  "use strict";

  var cfg = window.CV_APP || {};
  var KEY = "sioc_comando_vivo_v1";
  var AUDIO_CLIP_MS = 4000;
  var VIDEO_CLIP_MS = 3000;
  var watchId = null;
  var lastPos = null;
  var pingTimer = null;
  var session = null;

  var mediaStream = null;
  var mediaRecorder = null;
  var audioOn = false;
  var videoOn = false;
  var mediaLoopTimer = null;
  var preferredMime = "";
  var mode = null; // "audio" | "video"

  var elJoin = document.getElementById("cv-join");
  var elLive = document.getElementById("cv-live");
  var elStatus = document.getElementById("cv-status");
  var elCoords = document.getElementById("cv-coords");
  var elPingInfo = document.getElementById("cv-ping-info");
  var elJoinErr = document.getElementById("cv-join-err");
  var elBtnPanico = document.getElementById("cv-btn-panico");
  var elBtnOk = document.getElementById("cv-btn-ok");
  var elBtnAudio = document.getElementById("cv-btn-audio");
  var elBtnVideo = document.getElementById("cv-btn-video");
  var elAudioInfo = document.getElementById("cv-audio-info");
  var elPreviewWrap = document.getElementById("cv-preview-wrap");
  var elPreview = document.getElementById("cv-preview");

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
    updateMediaButtons();
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

  function pickMime(forVideo) {
    if (!window.MediaRecorder) return "";
    var candidates = forVideo
      ? [
          "video/webm;codecs=vp8,opus",
          "video/webm;codecs=vp9,opus",
          "video/webm",
          "video/mp4",
        ]
      : [
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

  function updateMediaButtons() {
    if (elBtnAudio) {
      if (audioOn) {
        elBtnAudio.classList.add("on");
        elBtnAudio.textContent = "⏹ Detener audio";
      } else {
        elBtnAudio.classList.remove("on");
        elBtnAudio.textContent = "🎤 Transmitir audio";
      }
    }
    if (elBtnVideo) {
      if (videoOn) {
        elBtnVideo.classList.add("on");
        elBtnVideo.textContent = "⏹ Detener video";
      } else {
        elBtnVideo.classList.remove("on");
        elBtnVideo.textContent = "📹 Transmitir video";
      }
    }
    if (elPreviewWrap) elPreviewWrap.hidden = !videoOn;
    if (!audioOn && !videoOn && elAudioInfo) {
      elAudioInfo.textContent = "Audio o video: el comando te ve/escucha en clips cortos.";
    }
  }

  function uploadMedia(blob, mime, durationMs, kind) {
    if (!session || !session.token || !blob || !blob.size) return Promise.resolve();
    var fd = new FormData();
    fd.append("token", session.token);
    fd.append("mime", mime || blob.type || (kind === "video" ? "video/webm" : "audio/webm"));
    if (durationMs) fd.append("duration_ms", String(durationMs));
    var field = kind === "video" ? "video" : "audio";
    var url = kind === "video" ? cfg.videoUrl : cfg.audioUrl;
    fd.append(field, blob, kind === "video" ? "clip.webm" : "clip.webm");
    return fetch(url, { method: "POST", body: fd })
      .then(function (r) {
        return r.json().then(function (j) {
          return { okHttp: r.ok, body: j };
        });
      })
      .then(function (res) {
        if (res.okHttp && res.body.ok) {
          elAudioInfo.textContent =
            (kind === "video" ? "Video" : "Audio") +
            " enviado " +
            new Date().toLocaleTimeString();
        } else {
          elAudioInfo.textContent =
            "Error " + kind + ": " + ((res.body && res.body.error) || "red");
        }
      })
      .catch(function () {
        elAudioInfo.textContent = "Error de red al enviar " + kind + ".";
      });
  }

  function recordOneClip(kind) {
    if (!mediaStream) return Promise.resolve();
    if (kind === "audio" && !audioOn) return Promise.resolve();
    if (kind === "video" && !videoOn) return Promise.resolve();

    preferredMime = pickMime(kind === "video");
    var chunks = [];
    var opts = preferredMime ? { mimeType: preferredMime } : undefined;
    var clipMs = kind === "video" ? VIDEO_CLIP_MS : AUDIO_CLIP_MS;
    var rec;
    try {
      rec = new MediaRecorder(mediaStream, opts);
    } catch (e) {
      try {
        rec = new MediaRecorder(mediaStream);
      } catch (e2) {
        elAudioInfo.textContent = "No se pudo grabar " + kind + ".";
        return Promise.resolve();
      }
    }
    mediaRecorder = rec;
    return new Promise(function (resolve) {
      rec.ondataavailable = function (ev) {
        if (ev.data && ev.data.size) chunks.push(ev.data);
      };
      rec.onstop = function () {
        var type = preferredMime || rec.mimeType || (kind === "video" ? "video/webm" : "audio/webm");
        var blob = new Blob(chunks, { type: type.split(";")[0] });
        uploadMedia(blob, type, clipMs, kind).finally(resolve);
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
      }, clipMs);
    });
  }

  function mediaLoop(kind) {
    if (kind === "audio" && !audioOn) return;
    if (kind === "video" && !videoOn) return;
    recordOneClip(kind).finally(function () {
      if ((kind === "audio" && audioOn) || (kind === "video" && videoOn)) {
        mediaLoopTimer = setTimeout(function () {
          mediaLoop(kind);
        }, 150);
      }
    });
  }

  function stopMediaTracks() {
    if (mediaLoopTimer) {
      clearTimeout(mediaLoopTimer);
      mediaLoopTimer = null;
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
    if (elPreview) {
      elPreview.srcObject = null;
    }
  }

  function stopAudio() {
    audioOn = false;
    if (mode === "audio") {
      stopMediaTracks();
      mode = null;
    }
    updateMediaButtons();
  }

  function stopVideo() {
    videoOn = false;
    if (mode === "video") {
      stopMediaTracks();
      mode = null;
    }
    updateMediaButtons();
  }

  function stopAllMedia() {
    audioOn = false;
    videoOn = false;
    stopMediaTracks();
    mode = null;
    updateMediaButtons();
  }

  function startAudio() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Este celular no permite micrófono desde el navegador.");
      return;
    }
    if (!window.MediaRecorder) {
      alert("MediaRecorder no disponible. Probá Chrome.");
      return;
    }
    stopVideo();
    navigator.mediaDevices
      .getUserMedia({ audio: true, video: false })
      .then(function (stream) {
        mediaStream = stream;
        audioOn = true;
        mode = "audio";
        updateMediaButtons();
        setStatus("GPS + Audio", "on");
        mediaLoop("audio");
      })
      .catch(function (err) {
        alert("Permiso de micrófono denegado: " + (err.message || err.name));
      });
  }

  function startVideo() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Este celular no permite cámara desde el navegador.");
      return;
    }
    if (!window.MediaRecorder) {
      alert("MediaRecorder no disponible. Probá Chrome.");
      return;
    }
    stopAudio();
    var constraints = {
      audio: true,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 640, max: 854 },
        height: { ideal: 480, max: 480 },
        frameRate: { ideal: 15, max: 24 },
      },
    };
    navigator.mediaDevices
      .getUserMedia(constraints)
      .then(function (stream) {
        mediaStream = stream;
        videoOn = true;
        mode = "video";
        if (elPreview) {
          elPreview.srcObject = stream;
          elPreview.play().catch(function () {});
        }
        updateMediaButtons();
        setStatus("GPS + Video", "on");
        mediaLoop("video");
      })
      .catch(function () {
        // Fallback cámara frontal
        return navigator.mediaDevices
          .getUserMedia({
            audio: true,
            video: { facingMode: "user", width: { ideal: 480 }, frameRate: { ideal: 15 } },
          })
          .then(function (stream) {
            mediaStream = stream;
            videoOn = true;
            mode = "video";
            if (elPreview) {
              elPreview.srcObject = stream;
              elPreview.play().catch(function () {});
            }
            updateMediaButtons();
            setStatus("GPS + Video", "on");
            mediaLoop("video");
          });
      })
      .catch(function (err) {
        alert("Permiso de cámara denegado: " + (err.message || err.name));
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
            stopAllMedia();
            stopTracking();
            clearSession();
            showJoin();
            showErr("Operativo cerrado.");
          }
          return;
        }
        var now = new Date();
        var extra = "";
        if (videoOn) extra = " · 📹";
        else if (audioOn) extra = " · 🎤";
        elPingInfo.textContent =
          "GPS " +
          now.toLocaleTimeString() +
          (evento === "panico" ? " · PÁNICO" : "") +
          extra;
        if (res.body.estado === "panico") {
          setStatus("PÁNICO", "panic");
          elBtnOk.hidden = false;
        } else if (videoOn) {
          setStatus("GPS + Video", "on");
          elBtnOk.hidden = true;
        } else if (audioOn) {
          setStatus("GPS + Audio", "on");
          elBtnOk.hidden = true;
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
  if (elBtnVideo) {
    elBtnVideo.addEventListener("click", function () {
      if (videoOn) stopVideo();
      else startVideo();
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
        setStatus(videoOn ? "GPS + Video" : audioOn ? "GPS + Audio" : "Enviando GPS", "on");
        elBtnOk.hidden = true;
      }
    });
  });

  document.getElementById("cv-btn-salir").addEventListener("click", function () {
    stopAllMedia();
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
