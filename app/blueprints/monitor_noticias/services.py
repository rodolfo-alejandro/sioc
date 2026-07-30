"""
Servicio de recopilación de noticias por RSS (Google News + feeds) y sitios HTML oficiales.
Solo guarda título, resumen y link a la fuente original (sin copiar la nota completa).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, datetime, timedelta
from html import unescape
from urllib.parse import quote_plus, urljoin, urlparse

try:
    import feedparser
except Exception:  # pragma: no cover
    feedparser = None

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None

_log = logging.getLogger(__name__)
_USER_AGENT = (
    "Mozilla/5.0 (compatible; SIOC-MonitorNoticias/1.1; +https://sioc.sistemas-msa.com)"
)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")


def dependencias_faltantes() -> list[str]:
    faltan = []
    if feedparser is None:
        faltan.append("feedparser")
    if requests is None:
        faltan.append("requests")
    if BeautifulSoup is None:
        faltan.append("beautifulsoup4")
    return faltan


def link_hash(link: str) -> str:
    return hashlib.sha1((link or "").strip().encode("utf-8", "ignore")).hexdigest()


def _strip_html(texto: str, limite: int = 600) -> str:
    if not texto:
        return ""
    limpio = unescape(_TAG_RE.sub(" ", texto))
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio[:limite]


def build_google_news_url(claves: list[str], region: str = "Salta", dias: int | None = None) -> str:
    """
    Arma la URL de búsqueda de Google News RSS (es-AR).
    `region` puede traer varias provincias separadas por coma (se combinan con OR).
    `dias` limita la antigüedad (operador when:Nd de Google News).
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
    if dias and int(dias) > 0:
        consulta = f"{consulta} when:{int(dias)}d".strip()
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


def _parse_fecha_texto(texto: str) -> datetime | None:
    if not texto:
        return None
    m = _DATE_RE.search(texto)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    try:
        return datetime(y, mo, d, hh, mm)
    except ValueError:
        return None


def _fetch_raw(url: str, timeout: int = 25) -> bytes | None:
    if requests is None:
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        _log.warning("Fetch falló %s: %s", url, e)
        return None


def _fetch_text(url: str) -> str | None:
    raw = _fetch_raw(url)
    if raw is None:
        return None
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


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


def _en_periodo(dt: datetime | None, fecha_desde: date | None, fecha_hasta: date | None) -> bool:
    if fecha_desde is None and fecha_hasta is None:
        return True
    if dt is None:
        # Sin fecha: incluir solo si no hay filtro estricto de "desde"
        return fecha_desde is None
    d = dt.date() if isinstance(dt, datetime) else dt
    if fecha_desde and d < fecha_desde:
        return False
    if fecha_hasta and d > fecha_hasta:
        return False
    return True


def _dias_desde_hasta(fecha_desde: date | None, fecha_hasta: date | None, dias: int | None) -> int | None:
    if dias and int(dias) > 0:
        return int(dias)
    if fecha_desde:
        fin = fecha_hasta or date.today()
        return max(1, (fin - fecha_desde).days + 1)
    return None


def scrape_html_site(url: str, medio_default: str = "", max_articulos: int = 40) -> list[dict]:
    """
    Scraper genérico orientado a sitios oficiales de Salta.
    - Policía/WordPress: enlaces a ?p= o permalinks
    - salta.gob.ar: enlaces /prensa/noticias/...
    """
    if BeautifulSoup is None or requests is None:
        return []
    html = _fetch_text(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    host = (urlparse(url).netloc or "").lower()

    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        full = urljoin(url, href)
        path = urlparse(full).path or ""
        if "salta.gob.ar" in host:
            # Artículos reales: .../slug-109230 (id numérico largo). Excluye listados/secciones.
            if re.search(r"/prensa/noticias/[a-z0-9-]+-\d{5,}/?$", path, re.I):
                links.append(full.split("#")[0])
        else:
            # WordPress prensa policial u otros
            if re.search(r"[?&]p=\d+", full) or re.search(r"/\d{4}/\d{2}/", path):
                links.append(full.split("#")[0])
            elif path.count("/") >= 2 and not any(
                x in path.lower() for x in ("/cat/", "/tag/", "/page/", "/author/", "wp-")
            ):
                # permalinks tipo /titulo-noticia/
                if full.startswith(base) and path not in ("/", ""):
                    titulo_a = _strip_html(a.get_text(" ", strip=True), 200)
                    if len(titulo_a) >= 25:
                        links.append(full.split("#")[0])

    # Dedup preservando orden
    vistos: set[str] = set()
    unicos: list[str] = []
    for link in links:
        if link in vistos:
            continue
        vistos.add(link)
        unicos.append(link)
        if len(unicos) >= max_articulos:
            break

    medio = medio_default or host.replace("www.", "")
    salida: list[dict] = []
    for i, link in enumerate(unicos):
        if i:
            time.sleep(0.35)  # no saturar el sitio oficial
        art_html = _fetch_text(link)
        if not art_html:
            continue
        art = BeautifulSoup(art_html, "html.parser")
        h1 = art.find("h1")
        titulo = _strip_html(h1.get_text(" ", strip=True) if h1 else "", 600)
        if not titulo:
            og = art.find("meta", property="og:title")
            titulo = _strip_html((og.get("content") if og else "") or "", 600)
        if not titulo:
            continue
        resumen = ""
        desc = art.find("meta", attrs={"name": "description"}) or art.find(
            "meta", property="og:description"
        )
        if desc and desc.get("content"):
            resumen = _strip_html(desc.get("content"), 600)
        if not resumen:
            p = art.find("p")
            if p:
                resumen = _strip_html(p.get_text(" ", strip=True), 600)
        publicado = None
        time_el = art.find("time")
        if time_el:
            publicado = _parse_fecha_texto(time_el.get("datetime") or time_el.get_text(" ", strip=True))
        if not publicado:
            publicado = _parse_fecha_texto(art.get_text(" ", strip=True)[:2500])
        salida.append(
            {
                "titulo": titulo,
                "link": link,
                "medio": medio[:200],
                "resumen": resumen,
                "publicado_en": publicado,
            }
        )
    return salida


def recolectar_para_tema(
    tema,
    fuentes,
    dias: int | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    solo_oficiales: bool = False,
) -> list[dict]:
    """
    Recorre las fuentes activas y devuelve items candidatos (filtrados por tema y período).
    No toca la base de datos: solo devuelve dicts.
    """
    claves = tema.lista_claves
    excluir = tema.lista_excluir
    region = (tema.region or "").strip()
    dias_eff = _dias_desde_hasta(fecha_desde, fecha_hasta, dias)
    candidatos: list[dict] = []
    vistos: set[str] = set()

    for fuente in fuentes:
        if not getattr(fuente, "activo", True):
            continue
        tipo = (fuente.tipo or "").strip()
        if solo_oficiales and tipo not in ("rss", "html_site"):
            # Oficiales = RSS/HTML configurados (Policía/Ministerio), no Google News
            continue
        if tipo == "google_news":
            url = build_google_news_url(claves, region, dias_eff)
            items = fetch_feed_entries(url)
            filtrar_claves = False
        elif tipo == "rss":
            url = (fuente.url or "").strip()
            if not url:
                continue
            items = fetch_feed_entries(url)
            # Feeds ya temáticos (ej. cat=DROGAS) no exigen match estricto de todas las claves
            filtrar_claves = True
        elif tipo == "html_site":
            url = (fuente.url or "").strip()
            if not url:
                continue
            items = scrape_html_site(url, medio_default=fuente.nombre or "")
            filtrar_claves = True
        else:
            continue

        for item in items:
            blob = f"{item['titulo']} {item['resumen']}"
            if filtrar_claves and claves and not _coincide(blob, claves):
                # Feeds ya temáticos (cat DROGAS / nombre con droga|policía) se aceptan sin match estricto
                nombre_f = (fuente.nombre or "").lower()
                url_f = (getattr(fuente, "url", None) or "").lower()
                tematico = (
                    "droga" in nombre_f
                    or "polic" in nombre_f
                    or "cat=40" in url_f
                    or "drogas" in url_f
                )
                if not tematico:
                    continue
            if _excluido(blob, excluir):
                continue
            if not _en_periodo(item.get("publicado_en"), fecha_desde, fecha_hasta):
                continue
            # Si pedimos "últimos N días" sin fechas absolutas
            if dias_eff and fecha_desde is None and fecha_hasta is None and item.get("publicado_en"):
                if item["publicado_en"] < datetime.utcnow() - timedelta(days=dias_eff):
                    continue
            h = link_hash(item["link"])
            if h in vistos:
                continue
            vistos.add(h)
            item["link_hash"] = h
            item["fuente_origen"] = tipo
            if not item.get("medio"):
                item["medio"] = fuente.nombre
            candidatos.append(item)
    return candidatos
