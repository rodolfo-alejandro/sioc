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
    """Descarga bytes. Si el cert SSL del sitio oficial falla, reintenta sin verify."""
    if requests is None:
        return None
    headers = {"User-Agent": _USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except requests.exceptions.SSLError:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
            resp.raise_for_status()
            _log.info("Fetch OK sin verify SSL: %s", url)
            return resp.content
        except Exception as e2:
            _log.warning("Fetch falló (SSL retry) %s: %s", url, e2)
            return None
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
    if raw is None:
        return []
    parsed = feedparser.parse(raw)
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


def _url_con_pagina(url: str, page: int) -> str:
    """Agrega paged=N (WordPress) preservando query existente."""
    if page <= 1:
        return url
    parsed = urlparse(url)
    from urllib.parse import parse_qsl, urlencode

    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    qs["paged"] = str(page)
    return parsed._replace(query=urlencode(qs)).geturl()


def fetch_feed_entries_rango(
    url: str,
    fecha_desde: date | None = None,
    max_pages: int = 15,
) -> list[dict]:
    """
    Recorre páginas del RSS (WordPress paged=) hasta cubrir fecha_desde
    o agotar páginas. Un solo RSS suele traer ~10 ítems recientes.
    """
    acumulado: list[dict] = []
    vistos: set[str] = set()
    for page in range(1, max(1, max_pages) + 1):
        page_url = _url_con_pagina(url, page)
        items = fetch_feed_entries(page_url)
        if not items:
            break
        nuevos = 0
        oldest: datetime | None = None
        for it in items:
            h = link_hash(it["link"])
            if h in vistos:
                continue
            vistos.add(h)
            acumulado.append(it)
            nuevos += 1
            pub = it.get("publicado_en")
            if pub and (oldest is None or pub < oldest):
                oldest = pub
        if nuevos == 0:
            break
        if fecha_desde and oldest and oldest.date() < fecha_desde:
            break
        if page < max_pages:
            time.sleep(0.2)
    return acumulado


def _coincide(texto: str, claves: list[str]) -> bool:
    if not claves:
        return True
    t = (texto or "").lower()
    return any(c.lower() in t for c in claves)


def _coincide_flexible(texto: str, claves: list[str]) -> bool:
    """
    Match flexible: además de la frase completa, prueba cada palabra significativa
    (útil para Ministerio, donde 'incautaron ... droga' no matchea 'incautación').
    """
    if not claves:
        return True
    if _coincide(texto, claves):
        return True
    t = (texto or "").lower()
    tokens: set[str] = set()
    for c in claves:
        for w in re.split(r"[\s,;/|-]+", (c or "").lower()):
            w = w.strip()
            if len(w) >= 4 and w not in ("para", "sobre", "como", "este", "esta", "desde"):
                tokens.add(w)
    return any(tok in t for tok in tokens)


def _fuente_ya_tematica(fuente) -> bool:
    nombre_f = (getattr(fuente, "nombre", None) or "").lower()
    url_f = (getattr(fuente, "url", None) or "").lower()
    return (
        "droga" in nombre_f
        or "polic" in nombre_f
        or "cat=40" in url_f
        or "drogas" in url_f
    )


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
    # Las fechas absolutas tienen prioridad sobre "últimos N días"
    if fecha_desde or fecha_hasta:
        if fecha_desde:
            fin = fecha_hasta or date.today()
            return max(1, (fin - fecha_desde).days + 1)
        return None
    if dias and int(dias) > 0:
        return int(dias)
    return None


def _resolver_periodo(
    fecha_desde: date | None,
    fecha_hasta: date | None,
    dias: int | None,
) -> tuple[date | None, date | None]:
    """Normaliza a (desde, hasta). Si hay fechas, ignoran 'dias'."""
    if fecha_desde or fecha_hasta:
        d1 = fecha_desde
        d2 = fecha_hasta or (date.today() if fecha_desde else None)
        return d1, d2
    if dias and int(dias) > 0:
        d2 = date.today()
        d1 = d2 - timedelta(days=int(dias))
        return d1, d2
    return None, None


def _es_articulo_salta(path: str) -> bool:
    return bool(re.search(r"/prensa/noticias/[a-z0-9-]+-\d{5,}/?$", path or "", re.I))


def _links_lista_noticias(soup, base_url: str) -> list[str]:
    """Solo notas del listado principal (evita destacados/sidebar)."""
    links: list[str] = []
    contenedores = soup.select("ul.lista-noticias a[href]") if soup else []
    if not contenedores:
        contenedores = soup.select("a[href]") if soup else []
    for a in contenedores:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = urljoin(base_url, href).split("#")[0]
        if _es_articulo_salta(urlparse(full).path or ""):
            links.append(full)
    return links


def _parse_articulo_html(art_html: str, link: str, medio: str) -> dict | None:
    art = BeautifulSoup(art_html, "html.parser")
    h1 = art.find("h1")
    titulo = _strip_html(h1.get_text(" ", strip=True) if h1 else "", 600)
    if not titulo:
        og = art.find("meta", property="og:title")
        titulo = _strip_html((og.get("content") if og else "") or "", 600)
    if not titulo:
        return None
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
    return {
        "titulo": titulo,
        "link": link,
        "medio": (medio or "")[:200],
        "resumen": resumen,
        "publicado_en": publicado,
    }


def scrape_salta_organismo(
    list_url: str,
    medio_default: str = "",
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    max_pages: int = 40,
    max_articulos: int = 250,
) -> list[dict]:
    """Listado paginado del Ministerio: .../organismos/.../pagina-N."""
    if BeautifulSoup is None or requests is None:
        return []
    if "/prensa/noticias/organismos/" not in list_url and "ministerio-de-seguridad" in list_url:
        list_url = "https://www.salta.gob.ar/prensa/noticias/organismos/ministerio-de-seguridad-6"
    base = list_url.split("?")[0].rstrip("/")
    base = re.sub(r"/pagina-\d+$", "", base)
    medio = medio_default or "Ministerio de Seguridad - Salta"
    salida: list[dict] = []
    vistos: set[str] = set()
    pages_sin_nuevos = 0

    for page in range(1, max(1, max_pages) + 1):
        page_url = base if page == 1 else f"{base}/pagina-{page}"
        html = _fetch_text(page_url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        page_links = _links_lista_noticias(soup, page_url)
        nuevos_links: list[str] = []
        for link in page_links:
            if link in vistos:
                continue
            vistos.add(link)
            nuevos_links.append(link)
        if not nuevos_links:
            pages_sin_nuevos += 1
            if pages_sin_nuevos >= 2:
                break
            continue
        pages_sin_nuevos = 0

        oldest_en_pagina: date | None = None
        for i, link in enumerate(nuevos_links):
            if len(salida) >= max_articulos:
                return salida
            if i or page > 1:
                time.sleep(0.15)
            art_html = _fetch_text(link)
            if not art_html:
                continue
            item = _parse_articulo_html(art_html, link, medio)
            if not item:
                continue
            pub = item.get("publicado_en")
            if pub:
                pd = pub.date() if isinstance(pub, datetime) else pub
                if oldest_en_pagina is None or pd < oldest_en_pagina:
                    oldest_en_pagina = pd
                if fecha_hasta and pd > fecha_hasta:
                    continue
                if fecha_desde and pd < fecha_desde:
                    continue
            salida.append(item)

        if fecha_desde and oldest_en_pagina and oldest_en_pagina < fecha_desde:
            break
        time.sleep(0.1)
    return salida


def scrape_html_site(
    url: str,
    medio_default: str = "",
    max_articulos: int = 40,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    max_pages: int | None = None,
    extra_list_urls: list[str] | None = None,
) -> list[dict]:
    """Scraper oficiales. Ministerio Salta usa /pagina-N."""
    if BeautifulSoup is None or requests is None:
        return []

    if "salta.gob.ar" in (url or "") and (
        "ministerio-de-seguridad" in (url or "") or "/prensa/noticias/organismos/" in (url or "")
    ):
        span = 30
        if fecha_desde:
            span = max(1, ((fecha_hasta or date.today()) - fecha_desde).days + 1)
        pages = max_pages or min(60, max(10, span // 4 + 6))
        return scrape_salta_organismo(
            url,
            medio_default=medio_default,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            max_pages=pages,
            max_articulos=max(max_articulos, pages * 12),
        )

    html = _fetch_text(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    host = (urlparse(url).netloc or "").lower()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        full = urljoin(url, href).split("#")[0]
        path = urlparse(full).path or ""
        if "salta.gob.ar" in host:
            if _es_articulo_salta(path):
                links.append(full)
        else:
            if re.search(r"[?&]p=\d+", full) or re.search(r"/\d{4}/\d{2}/", path):
                links.append(full)
            elif path.count("/") >= 2 and not any(
                x in path.lower() for x in ("/cat/", "/tag/", "/page/", "/author/", "wp-")
            ):
                if full.startswith(f"{urlparse(url).scheme}://{urlparse(url).netloc}"):
                    titulo_a = _strip_html(a.get_text(" ", strip=True), 200)
                    if len(titulo_a) >= 25:
                        links.append(full)

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
            time.sleep(0.2)
        art_html = _fetch_text(link)
        if not art_html:
            continue
        item = _parse_articulo_html(art_html, link, medio)
        if item:
            salida.append(item)
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
    # Unificar período: fechas absolutas ganan; "últimos N" → rango desde/hasta
    d1, d2 = _resolver_periodo(fecha_desde, fecha_hasta, dias)
    dias_eff = _dias_desde_hasta(d1, d2, None if (d1 or d2) else dias)
    candidatos: list[dict] = []
    vistos: set[str] = set()

    # Más páginas si el rango es amplio
    span_days = dias_eff or 7
    max_rss_pages = min(20, max(3, span_days // 5 + 2))
    max_html = min(300, max(40, span_days * 2))

    for fuente in fuentes:
        if not getattr(fuente, "activo", True):
            continue
        tipo = (fuente.tipo or "").strip()
        if solo_oficiales and tipo not in ("rss", "html_site"):
            continue
        if tipo == "google_news":
            url = build_google_news_url(claves, region, dias_eff)
            items = fetch_feed_entries(url)
            filtrar_claves = False
        elif tipo == "rss":
            url = (fuente.url or "").strip()
            if not url:
                continue
            items = fetch_feed_entries_rango(url, fecha_desde=d1, max_pages=max_rss_pages)
            filtrar_claves = True
        elif tipo == "html_site":
            url = (fuente.url or "").strip()
            if not url:
                continue
            items = scrape_html_site(
                url,
                medio_default=fuente.nombre or "",
                max_articulos=max_html,
                fecha_desde=d1,
                fecha_hasta=d2,
            )
            filtrar_claves = True
        else:
            continue

        for item in items:
            blob = f"{item['titulo']} {item['resumen']}"
            if filtrar_claves and claves:
                if _fuente_ya_tematica(fuente):
                    pass
                elif tipo == "html_site":
                    if not _coincide_flexible(blob, claves):
                        continue
                elif not _coincide(blob, claves):
                    continue
            if _excluido(blob, excluir):
                continue
            if not _en_periodo(item.get("publicado_en"), d1, d2):
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
