#!/usr/bin/env python3
"""
Metropol -> Meta (Facebook/Instagram) product catalog feed builder.

Reads the live inventory that metropol.ge embeds in its /results page
(Next.js RSC payload), keeps available apartments, and writes RSS 2.0 XML
feeds in the format Meta Commerce Manager accepts:

    feed.xml      – Georgian titles/descriptions
    feed_en.xml   – English titles/descriptions

Standard library only; no pip install needed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from xml.sax.saxutils import escape

BASE = "https://www.metropol.ge"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 MetropolFeedBot/1.0"
)

# Which flatTypeName values go into the catalog
INCLUDE_TYPES = {"residential", "აპარტამენტი"}
AVAILABLE_STATUS = "თავისუფალი"

# Which projects (site slugs) go into the catalog. Empty env value = all projects.
INCLUDE_PROJECTS = {
    x.strip() for x in os.environ.get("INCLUDE_PROJECTS", "kavtaradze,ortachala").split(",") if x.strip()
}

# Price in the site data is USD. Set PRICE_CURRENCY=GEL to convert with /api/rate.
PRICE_CURRENCY = os.environ.get("PRICE_CURRENCY", "GEL").upper()
MIN_ITEMS = int(os.environ.get("MIN_ITEMS", "50"))
# Only list flats that have a 3D interior render (no 2D plans / exterior fallbacks)
REQUIRE_INTERIOR_RENDER = os.environ.get("REQUIRE_INTERIOR_RENDER", "1") == "1"  # safety net: don't publish an empty feed

# Fallback images for units that have no render in the CRM
PROJECT_FALLBACK_IMAGE = {
    "lisi": "/uploads/lisi_proeqtebis-gverdi-g0l12ivpbl5NCQuh6dlx43v5BitpPw.jpg",
    "kavtaradze": "/uploads/MP-03-111111-c9x6wDLLYNQji5KvTL2utZwHFAkWLN.jpg",
    "ortachala": "/uploads/Untitlexxd-2-Zl85DHwb3xMaC7Vm8NiFt6bMKNybwk.png",
    "shindisi": "/uploads/Tabaxmela%20photo-h8OM57tBcggTInOOgdVPkxyaVwXQmq.png",
    "bagebi": "/uploads/metropol-bagebi-pg6tlPZjSSii5zqF6bFAxP55eVAkP8.jpg",
    "parallel": "/uploads/Untitled-8-yq1s5dUhONEJu32IIIENbkvCJqhps0.jpg",
    "batumi-cube": "/uploads/Metropol-cube-5MB24MCYQLLa2APB0EqThjfSEPOAjz.jpg",
    "batumi-oval": "/uploads/metropol-oval-6uLFk27BFAGFUvKWjzDPflKtojRJ2k.jpg",
}
DEFAULT_IMAGE = "/og-default.jpg"

# Project exterior renders: fallback main image for flats without a CRM 3D render,
# and an additional image for the rest. Paths on www.metropol.ge.
PROJECT_RENDERS = {
    "kavtaradze": [
        "/uploads/MP-03-111111-c9x6wDLLYNQji5KvTL2utZwHFAkWLN.jpg",
        "/uploads/Web-21-OsAKQKRymL6WHyIMqDnsq1HkGIqj0K.png",
        "/uploads/%25E1%2583%259A%25E1%2583%259D%25E1%2583%2591%25E1%2583%2598-nfKuf60vDLnPXAfawO4MpoyvM3Dq2Y.jpg",
    ],
    "ortachala": [
        "/uploads/Blocks%20Ortachala-Wvp15UG93BmTXVT5XczTTNcra43AML.webp",
        "/uploads/Untitlexxd-2-Zl85DHwb3xMaC7Vm8NiFt6bMKNybwk.png",
    ],
}
# Renders are re-encoded as JPG into images/ and served from GitHub (Meta-friendly format).
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")
RENDER_URLS: dict[str, list[str]] = {}  # filled by prepare_renders()
FLAT_IMAGE_URLS: dict[str, str] = {}  # flatID -> mirrored interior render URL


def _safe_url(u: str) -> str:
    from urllib.parse import quote
    return quote(u, safe=":/?&=%#@+,;~")


def mirror_flat_renders(out_dir: str, flats: list[dict]) -> None:
    """Copy each flat's CRM interior render into images/flats/ as JPG (Meta-friendly host/format).
    Already-mirrored files are reused; files of flats no longer listed are removed."""
    if not IMAGE_BASE_URL:
        return
    try:
        from io import BytesIO
        from PIL import Image  # type: ignore
    except ImportError:
        print("warn: Pillow missing; using CRM render URLs directly", file=sys.stderr)
        return
    from concurrent.futures import ThreadPoolExecutor
    import threading

    decode_lock = threading.Lock()  # renders are 8-10 MB PNGs: download in parallel, decode one at a time

    d = os.path.join(out_dir, "images", "flats")
    os.makedirs(d, exist_ok=True)
    jobs = []
    for f in flats:
        src = f.get("render") or ""
        if not src.startswith("http"):
            continue
        # file name changes when the CRM image changes
        tag = re.sub(r"[^A-Za-z0-9]", "", src.rsplit("/", 1)[-1].rsplit(".", 1)[0])[-20:]
        jobs.append((str(f["flatID"]), _safe_url(src), f"MP-{f['flatID']}-{tag}.jpg"))

    def work(job):
        fid, src, name = job
        path = os.path.join(d, name)
        if os.path.exists(path):
            return fid, name, "cached"
        try:
            req = urllib.request.Request(src, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            with decode_lock:
                im = Image.open(BytesIO(raw))
                im.load()
                if max(im.size) > 1600:
                    im.thumbnail((1600, 1600))
                if im.mode != "RGB":
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.convert("RGBA").split()[-1])
                    im = bg
                im.save(path, "JPEG", quality=85, optimize=True, progressive=True)
                del raw
            return fid, name, "new"
        except Exception as e:
            print(f"warn: flat render {src}: {e}", file=sys.stderr)
            return fid, name, "failed"

    from PIL import ImageStat  # type: ignore

    def is_flat_drawing(path: str) -> bool:
        """2D technical plans are near-greyscale; 3D interior renders are colourful."""
        with Image.open(path) as im:
            return ImageStat.Stat(im.convert("HSV").resize((200, 200))).mean[1] < 8

    keep, stats = set(), {"cached": 0, "new": 0, "failed": 0, "plan_2d": 0}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for fid, name, st in ex.map(work, jobs):
            stats[st] += 1
            if st != "failed":
                keep.add(name)
                if is_flat_drawing(os.path.join(d, name)):
                    stats["plan_2d"] += 1
                    continue
                FLAT_IMAGE_URLS[fid] = f"{IMAGE_BASE_URL}/images/flats/{name}"
    removed = 0
    for fn in os.listdir(d):
        if fn not in keep:
            os.remove(os.path.join(d, fn))
            removed += 1
    print(f"flat renders: {len(keep)} mirrored {stats}, {removed} removed")


def prepare_renders(out_dir: str) -> None:
    """Download project renders, convert to JPG (needs Pillow), and map slug -> public URLs."""
    img_dir = os.path.join(out_dir, "images")
    for slug, paths in PROJECT_RENDERS.items():
        if INCLUDE_PROJECTS and slug not in INCLUDE_PROJECTS:
            continue
        urls = []
        for n, path in enumerate(paths, 1):
            src = BASE + path
            name = f"{slug}-{n}.jpg"
            dest = os.path.join(img_dir, name)
            try:
                if not IMAGE_BASE_URL:
                    raise RuntimeError("IMAGE_BASE_URL not set")
                from io import BytesIO
                from PIL import Image  # type: ignore

                req = urllib.request.Request(src, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    im = Image.open(BytesIO(r.read()))
                    im.load()
                if im.mode != "RGB":
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.convert("RGBA").split()[-1])
                    im = bg
                if max(im.size) > 2000:
                    im.thumbnail((2000, 2000))
                os.makedirs(img_dir, exist_ok=True)
                im.save(dest, "JPEG", quality=88, optimize=True, progressive=True)
                urls.append(f"{IMAGE_BASE_URL}/images/{name}")
            except Exception as e:
                print(f"warn: render {src} -> {e}; using original URL", file=sys.stderr)
                if not path.endswith(".webp"):
                    urls.append(src)
        if urls:
            RENDER_URLS[slug] = urls

CITY_EN = {"თბილისი": "Tbilisi", "ბათუმი": "Batumi", "ბაგები": "Bagebi"}


# --------------------------------------------------------------------------- #
# Fetching & parsing
# --------------------------------------------------------------------------- #
def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ka,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)


def rsc_payload(html: str) -> str:
    """Concatenate the string chunks Next.js streams into self.__next_f."""
    parts = []
    for m in PUSH_RE.finditer(html):
        try:
            arr = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if len(arr) > 1 and isinstance(arr[1], str):
            parts.append(arr[1])
    return "".join(parts)


def extract_json_array(text: str, key: str) -> list:
    """Find `"key":[ ... ]` in text and return the parsed list."""
    m = re.search(r'"%s"\s*:\s*\[' % re.escape(key), text)
    if not m:
        return []
    start = m.end() - 1
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    return []


def load_inventory(html: str) -> tuple[list[dict], list[dict]]:
    payload = rsc_payload(html)
    return extract_json_array(payload, "projects"), extract_json_array(payload, "apartments")


def usd_gel_rate() -> float:
    return float(json.loads(fetch(f"{BASE}/api/rate"))["usdRate"])


# --------------------------------------------------------------------------- #
# Item building
# --------------------------------------------------------------------------- #
def num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "."))
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def fmt_num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def bedrooms_label(b: str, lang: str) -> str:
    b = (b or "").strip()
    if not b:
        return ""
    if b in ("სტუდიო", "studio", "Studio"):
        return "სტუდიო" if lang == "ka" else "Studio"
    return f"{b}-საძინებლიანი" if lang == "ka" else f"{b}-bedroom"


def unit_word(flat: dict, lang: str) -> str:
    apt = flat.get("flatTypeName") == "აპარტამენტი"
    if lang == "ka":
        return "აპარტამენტი" if apt else "ბინა"
    return "Apartment" if apt else "Flat"


def price_bucket(usd: float) -> str:
    for limit, label in ((50_000, "<50k"), (80_000, "50-80k"), (120_000, "80-120k"),
                         (200_000, "120-200k"), (350_000, "200-350k")):
        if usd < limit:
            return label
    return "350k+"


def build_item(flat: dict, project: dict, project_title: str, lang: str, rate: float) -> dict | None:
    price_usd = num(flat.get("price"))
    area = num(flat.get("WHOLE_AREA"))
    if not price_usd or not area:
        return None

    slug = project["slug"]
    building = (flat.get("buildingName") or "").strip().lower()
    if building:
        link = f"{BASE}{'/en' if lang == 'en' else ''}/projects/{slug}-{building}/floor-{flat['floor']}/apartment-{flat['flatNum']}"
    else:
        link = f"{BASE}{'/en' if lang == 'en' else ''}/projects"

    plan = flat.get("render") or ""
    plan = plan if plan.startswith("http") else ""
    renders = RENDER_URLS.get(slug) or [BASE + PROJECT_FALLBACK_IMAGE.get(slug, DEFAULT_IMAGE)]
    # Main image = the flat's own 3D interior render from the CRM; project renders as extras.
    # Flats without one fall back to the project exterior render.
    image = FLAT_IMAGE_URLS.get(str(flat.get("flatID"))) or (_safe_url(plan) if plan else renders[0])
    extra_imgs = []  # interior render only; no exterior shots

    city_ka = flat.get("city") or ""
    city = city_ka if lang == "ka" else CITY_EN.get(city_ka, city_ka)
    beds = bedrooms_label(flat.get("BEDROOM"), lang)
    word = unit_word(flat, lang)
    sqm = "მ²" if lang == "ka" else "m²"

    # Title – short, front-loaded (Meta truncates ~65 chars in ads)
    head = f"{beds} {word.lower()}" if beds else word
    title = f"{head}, {fmt_num(area)} {sqm} – {project_title}, {city}"

    # Description
    ppsm = num(flat.get("kvmPrice"))
    if ppsm:
        if PRICE_CURRENCY == "GEL":
            ppsm_txt = f"{round(ppsm * rate):,} ₾".replace(",", " ")
        else:
            ppsm_txt = f"${round(ppsm):,}".replace(",", " " if lang == "ka" else ",")
    bits = []
    if lang == "ka":
        bits.append(f"{word} N{flat['flatNum']}, სართული {flat['floor']}, {fmt_num(area)} {sqm}")
        if beds:
            bits.append(beds)
        if num(flat.get("LIVING_AREA")):
            bits.append(f"საცხოვრებელი ფართი {fmt_num(num(flat['LIVING_AREA']))} {sqm}")
        if num(flat.get("BALCONY_AREA")):
            bits.append(f"აივანი {fmt_num(num(flat['BALCONY_AREA']))} {sqm}")
        if flat.get("view"):
            bits.append(f"ხედი: {flat['view']}")
        if ppsm:
            bits.append(f"{ppsm_txt} / {sqm}")
        if flat.get("projectFinishDate"):
            bits.append(f"ჩაბარება: {flat['projectFinishDate']}")
        desc = f"„მეტროპოლის“ პროექტი „{project_title}“, {city}. " + ". ".join(bits) + "."
        extra = flat.get("flatDiscrGE")
    else:
        bits.append(f"{word} #{flat['flatNum']}, floor {flat['floor']}, {fmt_num(area)} {sqm}")
        if beds:
            bits.append(beds)
        if num(flat.get("LIVING_AREA")):
            bits.append(f"Living area {fmt_num(num(flat['LIVING_AREA']))} {sqm}")
        if num(flat.get("BALCONY_AREA")):
            bits.append(f"Balcony {fmt_num(num(flat['BALCONY_AREA']))} {sqm}")
        if flat.get("view"):
            bits.append(f"View: {flat['view']}")
        if ppsm:
            bits.append(f"{ppsm_txt} per {sqm}")
        if flat.get("projectFinishDate"):
            bits.append(f"Completion: {flat['projectFinishDate']}")
        desc = f"Metropol – {project_title}, {city}. " + ". ".join(bits) + "."
        extra = flat.get("flatDiscrEN")
    if extra:
        desc += " " + extra.strip()

    if PRICE_CURRENCY == "GEL":
        price = f"{round(price_usd * rate)}.00 GEL"
    else:
        price = f"{price_usd:.2f} USD"

    purpose = flat.get("flatTypeNameInvestment") or ""
    return {
        "id": f"MP-{flat['flatID']}",
        "title": title[:150],
        "description": desc[:5000],
        "availability": "in stock",
        "condition": "new",
        "price": price,
        "link": link,
        "image_link": image,
        "additional_image_link": ",".join(extra_imgs[:10]),
        "brand": "Metropol",
        "product_type": " > ".join(x for x in (city, project_title, beds or word) if x),
        "google_product_category": "",
        "custom_label_0": project_title,
        "custom_label_1": city,
        "custom_label_2": beds or word,
        "custom_label_3": price_bucket(price_usd),
        "custom_label_4": purpose,
    }


# --------------------------------------------------------------------------- #
# XML
# --------------------------------------------------------------------------- #
def to_xml(items: list[dict], lang: str) -> str:
    title = "Metropol – ბინები" if lang == "ka" else "Metropol – Apartments"
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{BASE}</link>",
        f"<description>{escape(title)}</description>",
    ]
    for it in items:
        out.append("<item>")
        for k, v in it.items():
            if v in ("", None):
                continue
            out.append(f"<g:{k}>{escape(str(v))}</g:{k}>")
        out.append("</item>")
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


# --------------------------------------------------------------------------- #
def main(out_dir: str = ".") -> int:
    prepare_renders(out_dir)
    html_ka = fetch(f"{BASE}/results")
    projects_ka, flats = load_inventory(html_ka)
    try:
        projects_en, _ = load_inventory(fetch(f"{BASE}/en/results"))
    except Exception as e:  # English titles are nice-to-have
        print(f"warn: English page failed: {e}", file=sys.stderr)
        projects_en = []

    if not projects_ka or not flats:
        print("ERROR: could not find inventory in /results page (site structure changed?)", file=sys.stderr)
        return 1

    proj = {p["projectId"]: p for p in projects_ka}
    title_en = {p["projectId"]: p["title"] for p in projects_en}
    rate = usd_gel_rate() if PRICE_CURRENCY == "GEL" else 1.0

    selected = [
        f for f in flats
        if f.get("flatStatus") == AVAILABLE_STATUS
        and f.get("flatTypeName") in INCLUDE_TYPES
        and f.get("projectID") in proj
        and (not INCLUDE_PROJECTS or proj[f["projectID"]]["slug"] in INCLUDE_PROJECTS)
    ]
    mirror_flat_renders(out_dir, selected)
    if FLAT_IMAGE_URLS and REQUIRE_INTERIOR_RENDER:
        dropped = [f for f in selected if str(f["flatID"]) not in FLAT_IMAGE_URLS]
        selected = [f for f in selected if str(f["flatID"]) in FLAT_IMAGE_URLS]
        print(f"skipped {len(dropped)} flats without a 3D interior render: "
              + ", ".join(f"MP-{f['flatID']}" for f in dropped))

    stats = {}
    for lang, fname in (("ka", "feed.xml"), ("en", "feed_en.xml")):
        items, seen = [], set()
        for f in selected:
            p = proj[f["projectID"]]
            ptitle = p["title"] if lang == "ka" else title_en.get(f["projectID"], p["slug"].replace("-", " ").title())
            it = build_item(f, p, ptitle, lang, rate)
            if it and it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
        items.sort(key=lambda x: x["id"])
        if len(items) < MIN_ITEMS:
            print(f"ERROR: only {len(items)} items for {fname} (< MIN_ITEMS={MIN_ITEMS}); not writing", file=sys.stderr)
            return 1
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as fh:
            fh.write(to_xml(items, lang))
        stats[fname] = len(items)

    print(f"inventory: {len(flats)} units, selected {len(selected)}; written: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
