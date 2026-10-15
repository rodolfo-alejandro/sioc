(function () {
  "use strict";

  var cfg = window.CV_MAP || {};
  var map = L.map("cv-map").setView([-24.79, -65.41], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  var markers = {};
  var fittedOnce = false;
  var selectedId = null;
  var lastParticipantes = [];
  var trazaLayer = null;

  // Audio
  var listenOn = false;
  var lastAudioId = 0;
  var audioQueue = [];
  var audioPlaying = false;
  var audioPollTimer = null;
  var audioPlayer = document.getElementById("cv-audio-player");

  // Video
  var watchOn = false;
  var lastVideoId = 0;
  var videoQueue = [];
  var videoPlaying = false;
  var videoPollTimer = null;
  var videoPlayer = document.getElementById("cv-video-player");

  var elAudioLabel = document.getElementById("cv-audio-label");
  var elAudioHint = document.getElementById("cv-audio-hint");
  var elAudioStatus = document.getElementById("cv-audio-status");
  var btnListen = document.getElementById("cv-btn-listen");
  var btnListenStop = document.getElementById("cv-btn-listen-stop");
  var elVideoLabel = document.getElementById("cv-video-label");
  var elVideoStatus = document.getElementById("cv-video-status");
  var btnWatch = document.getElementById("cv-btn-watch");
  var btnWatchStop = document.getElementById("cv-btn-watch-stop");
  var elSelCard = document.getElementById("cv-selected-card");
  var elSelAlias = document.getElementById("cv-sel-alias");
  var elSelEstado = document.getElementById("cv-sel-estado");
  var elSelCoords = document.getElementById("cv-sel-coords");
  var elSelMaps = document.getElementById("cv-sel-maps");
  var elCfgStatus = document.getElementById("cv-cfg-status");

  function updateResumen(r) {
    r = r || {};
    var o = document.getElementById("cv-stat-online");
    var p = document.getElementById("cv-stat-panico");
    var t = document.getElementById("cv-stat-total");
    if (o) o.textContent = String(r.online || 0);
    if (p) p.textContent = String(r.panico || 0);
    if (t) t.textContent = String(r.total || 0);
  }

  function updateStatsText(stats, config) {
    if (!elCfgStatus) return;
    stats = stats || {};
    config = config || cfg.config || {};
    var extra = config.grabando
      ? " · GRABANDO " + (config.segundos_restantes || 0) + "s"
      : " · sin grabación";
    elCfgStatus.textContent =
      "Guardados: Audio " +
      (stats.audio_retenidos || 0) +
      " · Video " +
      (stats.video_retenidos || 0) +
      " · GPS " +
      (stats.gps_retenidos || 0) +
      extra;
  }

  function fmtCountdown(sec) {
    sec = Math.max(0, parseInt(sec || 0, 10));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function syncRecUi(config) {
    config = config || cfg.config || {};
    var idle = document.getElementById("cv-rec-idle");
    var active = document.getElementById("cv-rec-active");
    var cd = document.getElementById("cv-rec-countdown");
    var what = document.getElementById("cv-rec-what");
    if (idle) idle.hidden = !!config.grabando;
    if (active) active.hidden = !config.grabando;
    if (cd) cd.textContent = fmtCountdown(config.segundos_restantes || 0);
    if (what) {
      var parts = [];
      if (config.grabar_audio) parts.push("Audio");
      if (config.grabar_video) parts.push("Video");
      what.textContent = parts.length ? parts.join(" + ") : "—";
    }
  }

  function postConfig(body) {
    return fetch(cfg.configUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": cfg.csrfToken || "",
      },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.json();
    });
  }

  function updateSelectedCard(p) {
    if (!elSelCard || !p) return;
    elSelCard.hidden = false;
    if (elSelAlias) elSelAlias.textContent = p.alias || "—";
    if (elSelEstado) {
      elSelEstado.textContent = p.estado || "—";
      elSelEstado.className =
        "badge " +
        (p.estado === "panico"
          ? "bg-danger"
          : p.estado === "online"
            ? "bg-success"
            : "bg-secondary");
    }
    if (p.lat != null && p.lon != null) {
      if (elSelCoords) {
        elSelCoords.textContent =
          p.lat.toFixed(6) +
          ", " +
          p.lon.toFixed(6) +
          (p.accuracy != null ? " (±" + Math.round(p.accuracy) + " m)" : "");
      }
      if (elSelMaps) {
        elSelMaps.href =
          "https://www.google.com/maps?q=" + p.lat + "," + p.lon;
        elSelMaps.hidden = false;
      }
    } else {
      if (elSelCoords) elSelCoords.textContent = "Sin coordenadas aún";
      if (elSelMaps) elSelMaps.hidden = true;
    }
  }

  var btnSaveCfg = document.getElementById("cv-btn-save-cfg");
  var btnStartRec = document.getElementById("cv-btn-start-rec");
  var btnStopRec = document.getElementById("cv-btn-stop-rec");
  var btnPurge = document.getElementById("cv-btn-purge");

  if (btnSaveCfg && cfg.canManage) {
    btnSaveCfg.addEventListener("click", function () {
      btnSaveCfg.disabled = true;
      btnSaveCfg.textContent = "Guardando…";
      postConfig({
        action: "update",
        grabar_gps: !!(document.getElementById("cfg-gps") || {}).checked,
        gps_interval_sec: parseInt(
          (document.getElementById("cfg-gps-sec") || {}).value || "5",
          10
        ),
        audio_clip_sec: parseInt(
          (document.getElementById("cfg-audio-sec") || {}).value || "4",
          10
        ),
        video_clip_sec: parseInt(
          (document.getElementById("cfg-video-sec") || {}).value || "3",
          10
        ),
      })
        .then(function (data) {
          if (data.ok) {
            cfg.config = data.config;
            updateStatsText(data.stats, data.config);
            syncRecUi(data.config);
            btnSaveCfg.textContent = "Aplicado ✓";
            setTimeout(function () {
              btnSaveCfg.textContent = "Aplicar lapsos / GPS";
            }, 1500);
          } else {
            alert(data.error || "No se pudo guardar");
            btnSaveCfg.textContent = "Aplicar lapsos / GPS";
          }
        })
        .catch(function () {
          alert("Error de red");
          btnSaveCfg.textContent = "Aplicar lapsos / GPS";
        })
        .finally(function () {
          btnSaveCfg.disabled = false;
        });
    });
  }

  if (btnStartRec && cfg.canManage) {
    btnStartRec.addEventListener("click", function () {
      var mins = parseInt((document.getElementById("cfg-rec-min") || {}).value || "5", 10);
      btnStartRec.disabled = true;
      postConfig({
        action: "start_recording",
        minutos: mins,
        grabar_audio: !!(document.getElementById("cfg-rec-audio") || {}).checked,
        grabar_video: !!(document.getElementById("cfg-rec-video") || {}).checked,
      })
        .then(function (data) {
          if (!data.ok) {
            alert(data.error === "elegí_audio_o_video" ? "Elegí audio y/o video." : data.error || "Error");
            return;
          }
          cfg.config = data.config;
          syncRecUi(data.config);
          updateStatsText(data.stats, data.config);
        })
        .catch(function () {
          alert("Error de red");
        })
        .finally(function () {
          btnStartRec.disabled = false;
        });
    });
  }

  if (btnStopRec && cfg.canManage) {
    btnStopRec.addEventListener("click", function () {
      postConfig({ action: "stop_recording" }).then(function (data) {
        if (data.ok) {
          cfg.config = data.config;
          syncRecUi(data.config);
          updateStatsText(data.stats, data.config);
        }
      });
    });
  }

  if (btnPurge && cfg.canManage) {
    btnPurge.addEventListener("click", function () {
      if (
        !confirm(
          "¿Borrar TODO el audio y video guardados de este operativo? No se puede deshacer."
        )
      ) {
        return;
      }
      btnPurge.disabled = true;
      postConfig({ action: "purge_media" })
        .then(function (data) {
          if (data.ok) {
            updateStatsText(data.stats, data.config || cfg.config);
            alert(
              "Borrados: " +
                (data.purged && data.purged.audio) +
                " audios, " +
                (data.purged && data.purged.video) +
                " videos."
            );
          } else {
            alert(data.error || "No se pudo borrar");
          }
        })
        .catch(function () {
          alert("Error de red");
        })
        .finally(function () {
          btnPurge.disabled = false;
        });
    });
  }

  syncRecUi(cfg.config);

  function estadoDot(estado) {
    if (estado === "panico") return "cv-dot-panico";
    if (estado === "offline") return "cv-dot-offline";
    return "cv-dot-online";
  }

  function iconFor(p) {
    var cls = "cv-marker-label" + (p.estado === "panico" ? " cv-marker-panico" : "");
    var badge = "";
    if (p.video_vivo) badge = " 📹";
    else if (p.audio_vivo) badge = " 🎤";
    return L.divIcon({
      className: "",
      html: '<div class="' + cls + '">' + escapeHtml(p.alias) + badge + "</div>",
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    });
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function ago(iso) {
    if (!iso) return "sin dato";
    var t = Date.parse(iso);
    if (!t) return "—";
    var sec = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (sec < 60) return sec + " s";
    if (sec < 3600) return Math.floor(sec / 60) + " min";
    return Math.floor(sec / 3600) + " h";
  }

  function aliasOf(id) {
    var p = lastParticipantes.find(function (x) {
      return x.id === id;
    });
    return p ? p.alias : "#" + id;
  }

  function renderLista(participantes) {
    var ul = document.getElementById("cv-lista");
    var count = document.getElementById("cv-count");
    var alertas = document.getElementById("cv-alertas");
    if (!ul) return;
    count.textContent = String(participantes.length);

    var panicos = participantes.filter(function (p) {
      return p.estado === "panico";
    });
    alertas.innerHTML = panicos
      .map(function (p) {
        return (
          '<div class="cv-alerta-panico">🚨 PÁNICO: ' +
          escapeHtml(p.alias) +
          "</div>"
        );
      })
      .join("");

    ul.innerHTML = participantes
      .map(function (p) {
        var bat =
          p.battery != null ? " · bat " + Math.round(p.battery) + "%" : "";
        var badges = "";
        if (p.audio_vivo) badges += '<span class="cv-mic-badge">MIC</span>';
        if (p.video_vivo) badges += '<span class="cv-cam-badge">CAM</span>';
        var sel = selectedId === p.id ? " list-group-item-primary" : "";
        return (
          '<li class="list-group-item list-group-item-action py-2' +
          sel +
          '" data-id="' +
          p.id +
          '" style="cursor:pointer">' +
          '<span class="cv-dot ' +
          estadoDot(p.estado) +
          '"></span>' +
          "<strong>" +
          escapeHtml(p.alias) +
          "</strong>" +
          badges +
          '<div class="small text-muted">' +
          escapeHtml(p.estado) +
          " · hace " +
          ago(p.last_seen_at) +
          bat +
          "</div></li>"
        );
      })
      .join("");

    ul.querySelectorAll("[data-id]").forEach(function (el) {
      el.addEventListener("click", function () {
        var id = parseInt(el.getAttribute("data-id"), 10);
        focusParticipante(id, participantes);
        loadTraza(id);
        selectPerson(id);
      });
    });
  }

  function selectPerson(id) {
    selectedId = id;
    if (btnListen) btnListen.disabled = false;
    if (btnWatch) btnWatch.disabled = false;
    if (elAudioLabel) elAudioLabel.textContent = "Audio — " + aliasOf(id);
    if (elVideoLabel) elVideoLabel.textContent = "Video — " + aliasOf(id);
    if (elAudioHint) {
      elAudioHint.textContent =
        "Seleccionaste a " +
        aliasOf(id) +
        ". Escuchar audio o ver video (el efectivo debe transmitir).";
    }
    var p = lastParticipantes.find(function (x) {
      return x.id === id;
    });
    if (p) updateSelectedCard(p);
    renderLista(lastParticipantes);
  }

  function focusParticipante(id, participantes) {
    selectedId = id;
    var p = participantes.find(function (x) {
      return x.id === id;
    });
    if (p && p.lat != null && p.lon != null) {
      map.setView([p.lat, p.lon], Math.max(map.getZoom(), 16));
      if (markers[id]) markers[id].openPopup();
    }
  }

  function loadTraza(participanteId) {
    var tpl = cfg.trazaUrlTpl || "";
    var url = tpl.replace(/\/0$/, "/" + participanteId);
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (trazaLayer) {
          map.removeLayer(trazaLayer);
          trazaLayer = null;
        }
        var pts = (data.puntos || [])
          .filter(function (x) {
            return x.lat != null && x.lon != null;
          })
          .map(function (x) {
            return [x.lat, x.lon];
          });
        if (pts.length >= 2) {
          trazaLayer = L.polyline(pts, {
            color: "#0d6efd",
            weight: 3,
            opacity: 0.75,
          }).addTo(map);
          map.fitBounds(trazaLayer.getBounds(), { padding: [30, 30], maxZoom: 17 });
        }
      })
      .catch(function () {});
  }

  function updateMarkers(participantes) {
    var seen = {};
    var bounds = [];
    participantes.forEach(function (p) {
      if (p.lat == null || p.lon == null) return;
      seen[p.id] = true;
      bounds.push([p.lat, p.lon]);
      var media = "";
      if (p.video_vivo) media = " · 📹 video";
      else if (p.audio_vivo) media = " · 🎤 audio";
      var html =
        "<strong>" +
        escapeHtml(p.alias) +
        "</strong><br>" +
        escapeHtml(p.estado) +
        media +
        "<br>hace " +
        ago(p.last_seen_at);
      if (markers[p.id]) {
        markers[p.id].setLatLng([p.lat, p.lon]);
        markers[p.id].setIcon(iconFor(p));
        markers[p.id].setPopupContent(html);
      } else {
        markers[p.id] = L.marker([p.lat, p.lon], { icon: iconFor(p) })
          .addTo(map)
          .bindPopup(html);
      }
    });
    Object.keys(markers).forEach(function (id) {
      if (!seen[id]) {
        map.removeLayer(markers[id]);
        delete markers[id];
      }
    });
    if (!fittedOnce && bounds.length) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
      fittedOnce = true;
    }
  }

  // ─── Audio listen ─────────────────────────────────────────────────────────

  function setListenUi(on) {
    listenOn = on;
    if (btnListen) btnListen.disabled = !selectedId || on;
    if (btnListenStop) btnListenStop.disabled = !on;
    if (!on && elAudioStatus) elAudioStatus.textContent = "Sin escucha activa";
  }

  function playNextAudio() {
    if (!listenOn || audioPlaying) return;
    if (!audioQueue.length) {
      if (elAudioStatus) elAudioStatus.textContent = "Escuchando… esperando clips";
      return;
    }
    var clip = audioQueue.shift();
    audioPlaying = true;
    if (elAudioStatus) {
      elAudioStatus.textContent = "Audio clip #" + clip.id + " · " + aliasOf(clip.participante_id);
    }
    audioPlayer.src = clip.url;
    var p = audioPlayer.play();
    if (p && p.catch) {
      p.catch(function () {
        audioPlaying = false;
        if (elAudioStatus) elAudioStatus.textContent = "Activá el sonido / tocá play una vez.";
      });
    }
  }

  if (audioPlayer) {
    audioPlayer.addEventListener("ended", function () {
      audioPlaying = false;
      playNextAudio();
    });
    audioPlayer.addEventListener("error", function () {
      audioPlaying = false;
      playNextAudio();
    });
  }

  function pollAudio() {
    if (!listenOn || !selectedId || !cfg.audioListaUrl) return;
    var url =
      cfg.audioListaUrl +
      "?participante_id=" +
      selectedId +
      "&after_id=" +
      lastAudioId;
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        (data.clips || []).forEach(function (c) {
          if (c.id > lastAudioId) lastAudioId = c.id;
          audioQueue.push(c);
        });
        playNextAudio();
      })
      .catch(function () {});
  }

  function startListen() {
    if (!selectedId) {
      alert("Primero tocá un efectivo en la lista.");
      return;
    }
    stopWatch();
    lastAudioId = 0;
    audioQueue = [];
    audioPlaying = false;
    setListenUi(true);
    if (elAudioStatus) elAudioStatus.textContent = "Escuchando a " + aliasOf(selectedId) + "…";
    pollAudio();
    if (audioPollTimer) clearInterval(audioPollTimer);
    audioPollTimer = setInterval(pollAudio, 2500);
  }

  function stopListen() {
    if (audioPollTimer) {
      clearInterval(audioPollTimer);
      audioPollTimer = null;
    }
    audioQueue = [];
    audioPlaying = false;
    if (audioPlayer) {
      try {
        audioPlayer.pause();
        audioPlayer.removeAttribute("src");
        audioPlayer.load();
      } catch (e) {}
    }
    setListenUi(false);
  }

  // ─── Video watch ──────────────────────────────────────────────────────────

  function setWatchUi(on) {
    watchOn = on;
    if (btnWatch) btnWatch.disabled = !selectedId || on;
    if (btnWatchStop) btnWatchStop.disabled = !on;
    if (!on && elVideoStatus) elVideoStatus.textContent = "Sin video activo";
  }

  function playNextVideo() {
    if (!watchOn || videoPlaying) return;
    if (!videoQueue.length) {
      if (elVideoStatus) elVideoStatus.textContent = "Viendo… esperando clips";
      return;
    }
    // Si hay atraso, quedarse con los últimos 2 clips
    if (videoQueue.length > 2) {
      videoQueue = videoQueue.slice(-2);
      lastVideoId = Math.max.apply(
        null,
        videoQueue.map(function (c) {
          return c.id;
        })
      );
    }
    var clip = videoQueue.shift();
    videoPlaying = true;
    if (elVideoStatus) {
      elVideoStatus.textContent = "Video clip #" + clip.id + " · " + aliasOf(clip.participante_id);
    }
    videoPlayer.src = clip.url;
    var p = videoPlayer.play();
    if (p && p.catch) {
      p.catch(function () {
        videoPlaying = false;
        if (elVideoStatus) elVideoStatus.textContent = "Tocá play una vez para habilitar video.";
      });
    }
  }

  if (videoPlayer) {
    videoPlayer.addEventListener("ended", function () {
      videoPlaying = false;
      playNextVideo();
    });
    videoPlayer.addEventListener("error", function () {
      videoPlaying = false;
      playNextVideo();
    });
  }

  function pollVideo() {
    if (!watchOn || !selectedId || !cfg.videoListaUrl) return;
    var url =
      cfg.videoListaUrl +
      "?participante_id=" +
      selectedId +
      "&after_id=" +
      lastVideoId;
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        (data.clips || []).forEach(function (c) {
          if (c.id > lastVideoId) lastVideoId = c.id;
          videoQueue.push(c);
        });
        playNextVideo();
      })
      .catch(function () {});
  }

  function startWatch() {
    if (!selectedId) {
      alert("Primero tocá un efectivo en la lista.");
      return;
    }
    stopListen();
    lastVideoId = 0;
    videoQueue = [];
    videoPlaying = false;
    setWatchUi(true);
    if (elVideoStatus) elVideoStatus.textContent = "Viendo a " + aliasOf(selectedId) + "…";
    pollVideo();
    if (videoPollTimer) clearInterval(videoPollTimer);
    videoPollTimer = setInterval(pollVideo, 2000);
  }

  function stopWatch() {
    if (videoPollTimer) {
      clearInterval(videoPollTimer);
      videoPollTimer = null;
    }
    videoQueue = [];
    videoPlaying = false;
    if (videoPlayer) {
      try {
        videoPlayer.pause();
        videoPlayer.removeAttribute("src");
        videoPlayer.load();
      } catch (e) {}
    }
    setWatchUi(false);
  }

  if (btnListen) btnListen.addEventListener("click", startListen);
  if (btnListenStop) btnListenStop.addEventListener("click", stopListen);
  if (btnWatch) btnWatch.addEventListener("click", startWatch);
  if (btnWatchStop) btnWatchStop.addEventListener("click", stopWatch);

  function poll() {
    if (!cfg.positionsUrl) return;
    fetch(cfg.positionsUrl, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var list = data.participantes || [];
        lastParticipantes = list;
        renderLista(list);
        updateMarkers(list);
        updateResumen(data.resumen);
        if (data.config) {
          cfg.config = data.config;
          syncRecUi(data.config);
        }
        if (data.stats) updateStatsText(data.stats, data.config);
        if (selectedId) {
          var p = list.find(function (x) {
            return x.id === selectedId;
          });
          if (p) updateSelectedCard(p);
        }
      })
      .catch(function () {});
  }

  poll();
  if (cfg.activo) {
    setInterval(poll, 4000);
  }
})();
