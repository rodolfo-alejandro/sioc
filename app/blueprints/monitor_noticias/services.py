"""
Servicio de recopilación de noticias por RSS (Google News + feeds directos).
Solo guarda título, resumen y link a la fuente original (sin copiar la nota completa).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from html import unescape
from urllib.parse import quote_plus

try:
    import feedparser
except Exception:  # pragma: no cover
    feedparser = None

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

_USER_AGENT = "Mozilla/5.0 (compatible; SIOC-MonitorNoticias/1.0)"
_TAG_RE = re.compile(r"<[^>]+>")


def dependencias_faltantes() -> list[str]:
    faltan = []
    if feedparser is None:
        faltan.append("feedparser")
    if requests is None:
        faltan.append("requests")
    return faltan


def link_hash(link: str) -> str:
    return hashlib.sha1((link or "").strip().encode("utf-8", "ignore")).hexdigest()


def _strip_html(texto: str, limite: int = 600) -> str:
    if not texto:
        return ""
    limpio = unescape(_TAG_RE.sub(" ", texto))
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio[:limite]


def build_google_news_url(claves: list[str], region: str = "Salta") -> str:
    """
    Arma la URL de búsqueda de Google News RSS (es-AR).
    `region` puede traer varias provincias separadas por coma (se combinan con OR).
    """
    grupo = " OR ".join(f'"{t}"' if " " in t else t for t in claves) if claves else ""
    regiones = [r.strip() for r in (region or "").split(",") if r.strip()]
    if regiones:
        if len(regiones) == 1:
            reg_expr = regiones[0] if " " not in regiones[0] else f'"{regiones[0]}"'
        else:
            reg_expr = "(" + " OR ".join(f'"{r}"' if " " in r else r for r in regiones) + ")"
        consulta = f"({grupo}) {reg_expr}" if grupo else reg_expr
    else:
        consulta = grupo
    q = quote_plus(consulta)
    return f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=AR&ceid=AR:es-419"


def _parse_fecha(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6])
            except Exception:
                continue
    return None


def _fetch_raw(url: str) -> bytes | None:
    if requests is None:
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=20)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


def fetch_feed_entries(url: str) -> list[dict]:
    """Descarga y parsea un feed RSS. Devuelve lista de dicts normalizados."""
    if feedparser is None:
        return []
    raw = _fetch_raw(url)
    parsed = feedparser.parse(raw if raw is not None else url)
    salida = []
    for e in getattr(parsed, "entries", []) or []:
        titulo = _strip_html(getattr(e, "title", ""), 600)
        link = (getattr(e, "link", "") or "").strip()
        if not titulo or not link:
            continue
        medio = ""
        src = getattr(e, "source", None)
        if src is not None:
            medio = _strip_html(getattr(src, "title", "") or "", 200)
        if not medio and " - " in titulo:
            medio = titulo.rsplit(" - ", 1)[-1].strip()[:200]
        salida.append(
            {
                "titulo": titulo,
                "link": link,
                "medio": medio,
                "resumen": _strip_html(getattr(e, "summary", "") or "", 600),
                "publicado_en": _parse_fecha(e),
            }
        )
    return salida


def _coincide(texto: str, claves: list[str]) -> bool:
    if not claves:
        return True
    t = (texto or "").lower()
    return any(c.lower() in t for c in claves)


def _excluido(texto: str, excluir: list[str]) -> bool:
    if not excluir:
        return False
    t = (texto or "").lower()
    return any(c.lower() in t for c in excluir)


def recolectar_para_tema(tema, fuentes) -> list[dict]:
    """
    Recorre las fuentes activas y devuelve items candidatos (ya filtrados por palabras del tema).
    No toca la base de datos: solo devuelve dicts.
    """
    claves = tema.lista_claves
    excluir = tema.lista_excluir
    region = (tema.region or "").strip()
    candidatos: list[dict] = []
    vistos: set[str] = set()

    for fuente in fuentes:
        if not fuente.activo:
            continue
        if fuente.tipo == "google_news":
            url = build_google_news_url(claves, region)
            filtrar_claves = False  # Google News ya busca por las claves
        else:
            url = (fuente.url or "").strip()
            filtrar_claves = True  # feed genérico: filtramos por las claves del tema
        if not url:
            continue
        for item in fetch_feed_entries(url):
            blob = f"{item['titulo']} {item['resumen']}"
            if filtrar_claves and not _coincide(blob, claves):
                continue
            if _excluido(blob, excluir):
                continue
            h = link_hash(item["link"])
            if h in vistos:
                continue
            vistos.add(h)
            item["link_hash"] = h
            item["fuente_origen"] = fuente.tipo
            candidatos.append(item)
    return candidatos
