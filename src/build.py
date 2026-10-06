#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор статического сайта emkosti.market из выгрузки WooCommerce."""
import json, glob, os, re, html, unicodedata, shutil, urllib.parse
from collections import OrderedDict, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))          # src/ — данные и генератор
SITE = os.path.dirname(ROOT)                               # корень репозитория = готовый сайт
BASE = "https://emkosti.market"

PHONE_TEL = "+79119225732"
PHONE_HUMAN = "+7 (911) 922-57-32"
PHONE2_HUMAN = "+7 (812) 922-57-32"
EMAIL = "emkosti.market@yandex.ru"
ADDRESS = "Санкт-Петербург, улица Плесецкая 20"
WORK_HOURS = "Пн–Пт, 9:00–18:00"
COMPANY = "ООО «ЕМКОСТИ МАРКЕТ»"
INN = "ИНН 7814814481, ОГРН 1227800132130"

# ---------------------------------------------------------------- данные

def load_products():
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "products_p*.json"))):
        out += json.load(open(f, encoding="utf-8"))
    for p in out:
        # слаги с кириллицей приходят %-кодированными
        if "%" in p["slug"]:
            p["slug"] = urllib.parse.unquote(p["slug"])
    return out

def load_categories():
    cats = json.load(open(os.path.join(ROOT, "cats.json"), encoding="utf-8"))
    by_id = {c["id"]: c for c in cats}
    for c in cats:
        c["children"] = []
    for c in cats:
        p = c.get("parent") or 0
        if p in by_id:
            by_id[p]["children"].append(c)
    for c in cats:
        c["children"].sort(key=lambda x: x["name"])
    return cats

def load_img_map():
    return json.load(open(os.path.join(ROOT, "img_map.json"), encoding="utf-8"))

def load_pages():
    return json.load(open(os.path.join(ROOT, "pages_full.json"), encoding="utf-8"))

# ---------------------------------------------------------------- очистка

ALLOWED = "p br strong b em i ul ol li table thead tbody tr th td h2 h3 h4 h5 h6 a img div span sup del"

def clean_html(s, drop_h1=True):
    if not s:
        return ""
    s = render_shortcodes(s)
    s = re.sub(r'<a[^>]*data-fancybox[^>]*>(.*?)</a>', r'\1', s, flags=re.S)
    s = re.sub(r'<a[^>]*href="[^"]*\?attachment_id=\d+"[^>]*>(.*?)</a>', r'\1', s, flags=re.S|re.I)
    s = re.sub(r'<img[^>]*class="[^"]*wp-image[^"]*"[^>]*/?>', '', s, flags=re.I)
    if drop_h1:
        s = re.sub(r'<h1[^>]*>(.*?)</h1>', '', s, flags=re.S)
    s = re.sub(r'<div class="vc_[^"]*"[^>]*>', '<div>', s)
    s = re.sub(r'<span class="screen-reader-text">.*?</span>', '', s, flags=re.S)
    s = s.replace('data-src="#hidden-content', 'href="#')
    s = re.sub(r'<a data-fancybox="" href="#[^"]*">([^<]*)</a>', r'\1', s)
    # ссылки на чужой домен переписываем / убираем
    s = re.sub(r'href="https?://(?:www\.)?emkosti\.market[^"]*"', 'href="/"', s)
    s = re.sub(r'href="https?://192\.168\.0\.212[^"]*"', 'href="/"', s)
    s = re.sub(r'<a[^>]*href="/"[^>]*>(<img[^>]*>)</a>', r'\1', s)
    # картинки: путь WP -> локальный webp
    s = fix_img_srcs(s)
    s = fix_html(s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def strip_tags(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s or "")).strip()

# ------------------------------------------- парсер шорткодов WPBakery

TOKEN_RE = re.compile(r"\[(/?)([a-zA-Z_][\w-]*)((?:[^\[\]])*)\]")
QUOTES = "»«“”\"'″„"

def parse_attrs(s):
    attrs = {}
    if not s or not s.strip():
        return attrs
    ms = list(re.finditer(r"([a-zA-Z_][\w-]*)=", s))
    for i, m in enumerate(ms):
        start = m.end()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(s)
        v = s[start:end].strip().strip(QUOTES).strip()
        attrs[m.group(1)] = v
    return attrs

def parse_sc(s):
    root = []
    frames = [(None, root, root)]
    cur = root
    pos = 0
    # какие шорткоды вообще имеют закрывающую пару
    closing = set(re.findall(r"\[/([a-zA-Z_][\w-]*)\]", s))
    for m in TOKEN_RE.finditer(s):
        txt = s[pos:m.start()]
        if txt:
            cur.append(txt)
        pos = m.end()
        cflag, name, raw = m.group(1), m.group(2), m.group(3)
        if cflag:
            idx = None
            for i in range(len(frames) - 1, 0, -1):
                if frames[i][0] == name:
                    idx = i
                    break
            if idx is None:
                cur.append(m.group(0))
                continue
            del frames[idx + 1:]
            frames.pop()
            cur = frames[-1][2]
        else:
            node = {"name": name, "attrs": parse_attrs(raw), "children": []}
            cur.append(node)
            if name in closing and not raw.rstrip().endswith("/"):
                frames.append((name, node, node["children"]))
                cur = node["children"]
    tail = s[pos:]
    if tail:
        cur.append(tail)
    return root

ID_TO_SRC = {}     # id вложения -> путь WP
STEM_TO_FILE = {}  # имя файла без расширения -> локальный webp

def resolve_img(path):
    if not path:
        return None
    p = urllib.parse.unquote(path)
    full = p if p.startswith("http") else "http://192.168.0.212" + (p if p.startswith("/") else "/" + p)
    if full in IMG_MAP:
        return "/img/" + IMG_MAP[full]
    m = re.search(r"wp-content/uploads/(.+)$", p)
    rel = m.group(1) if m else p.rsplit("/", 1)[-1]
    stem = os.path.splitext(rel.rsplit("/", 1)[-1])[0]
    if stem in STEM_TO_FILE:
        return "/img/" + STEM_TO_FILE[stem]
    for k, v in STEM_TO_FILE.items():
        if k.endswith(stem) or stem.endswith(k):
            return "/img/" + v
    return None

def img_by_id(att_id):
    src = ID_TO_SRC.get(str(att_id))
    return resolve_img(src) if src else None

def render_sc(nodes):
    out = []
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
            continue
        name = n["name"]
        a = n["attrs"]
        if name in ("vc_row", "vc_column", "vc_column_inner", "vc_row_inner",
                    "vc_column_text", "vc_raw_html", "vc_text_block"):
            out.append(render_sc(n["children"]))
        elif name in ("vc_empty_space", "vc_separator", "yith_woocompare_table",
                      "tbay_custom_image_list_categories", "vc_googleplus",
                      "vc_progress_bar", "vc_button", "vc_msgbox"):
            pass
        elif name == "vc_single_image":
            src = img_by_id(a.get("image", ""))
            if src:
                out.append('<p><img src="%s" alt="" loading="lazy"></p>' % src)
        elif name == "tbay_gallery":
            ids = [x for x in a.get("images", "").split(",") if x]
            pics = [img_by_id(i) for i in ids]
            pics = [x for x in pics if x]
            if pics:
                out.append('<div class="gallery">' + "".join(
                    '<img src="%s" alt="" loading="lazy">' % x for x in pics) + "</div>")
        elif name == "tbay_title_heading":
            t = html.escape(a.get("title", ""))
            out.append("<h2>%s</h2>" % t if t else "")
        elif name == "vc_text_separator":
            out.append('<p class="note center">%s</p>' % html.escape(a.get("title", "")))
        elif name == "vc_toggle":
            t = html.escape(a.get("title", ""))
            inner = render_sc(n["children"])
            out.append("<details open><summary>%s</summary><div>%s</div></details>" % (t, inner))
        elif name == "vc_cta":
            link = a.get("btn_link", "")
            m = re.search(r"url:([^|]+)", link)
            href = urllib.parse.unquote(m.group(1)) if m else "/contacts/"
            if href.startswith("https://max.ru") or href.startswith("https://max.ru"):
                href = "tel:" + PHONE_TEL
            t = html.escape(a.get("btn_title", "Подобрать ёмкость"))
            out.append('<p><a class="btn btn-primary" href="%s">%s</a></p>' % (href, t))
        elif name == "tbay_features":
            out.append(render_features(a))
        else:
            out.append(render_sc(n["children"]))
    return "".join(out)

def render_features(a):
    title = a.get("title", "")
    items = []
    raw = a.get("items", "")
    if raw:
        try:
            items = json.loads(urllib.parse.unquote(raw))
        except Exception:
            items = []
    h = ""
    if title:
        h += "<h2>%s</h2>" % html.escape(title)
    if not items:
        return h
    body = []
    for it in items:
        t = (it.get("title") or "").strip()
        d = it.get("description") or ""
        d = d.strip()
        cls = "feat"
        if "<iframe" in d:
            cls += " feat-map"
        cell = '<div class="%s">' % cls
        if t:
            cell += "<b>%s</b>" % html.escape(t)
        if d:
            if "<iframe" in d:
                m = re.search(r'src="([^"]+)"', d)
                if m:
                    cell += ('<iframe src="' + html.escape(m.group(1)) +
                             '" loading="lazy" width="100%" height="300" '
                             'frameborder="0" allowfullscreen></iframe>')
                else:
                    cell += "<p>%s</p>" % d
            else:
                cell += "<p>%s</p>" % d
        cell += "</div>"
        body.append(cell)
    return h + '<div class="feats">' + "".join(body) + "</div>"

def render_shortcodes(s):
    return render_sc(parse_sc(html.unescape(s or "")))

# ------------------------------------------- чистка итогового HTML

PARA_BLOCK_RE = re.compile(r"<p[^>]*>\s*((?:(?!</p>).)*?<(?:h1|h2|h3|h4|div|ul|ol|table|details|section|figure)[\s>].*?)</p>", re.S)

def fix_html(s):
    # <p>, внутри которого есть блочный тег, раскрываем
    prev = None
    while prev != s:
        prev = s
        s = PARA_BLOCK_RE.sub(r"\1", s)
    s = re.sub(r"<p>\s*(?:&nbsp;|\s)*</p>", "", s)
    s = re.sub(r"<h1([^>]*)>(.*?)</h1>", r"<h2\1>\2</h2>", s, flags=re.S)
    return s

def fix_img_srcs(s):
    def repl(m):
        tag = m.group(0)
        src = m.group(1)
        local = resolve_img(src)
        if local:
            return tag.replace('"%s"' % src, '"%s"' % local, 1)
        if src.startswith("http") and "yandex" not in src and "maps" not in src:
            return ""  # чужие/недоступные картинки убираем целиком
        return tag
    return re.sub(r'<img[^>]*\ssrc="([^"]+)"[^>]*/?>', repl, s)

def money(minor, unit=2):
    if not minor:
        return ""
    v = int(minor) / (10 ** unit)
    return "{:,.0f}".format(v).replace(",", " ")

def slugify(s):
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "item"

# ---------------------------------------------------------------- картинки

IMG_MAP = None

def img_tag(src_wp, alt, cls="", lazy=True, sizes="(max-width:600px) 100vw, 400px"):
    name = IMG_MAP.get(src_wp)
    if not name:
        base = src_wp.rsplit("/", 1)[-1]
        stem = os.path.splitext(base)[0]
        for k, v in IMG_MAP.items():
            if k.endswith("/" + base) or os.path.splitext(k.rsplit("/", 1)[-1])[0] == stem:
                name = v
                break
    if not name:
        return '<div class="noimg" role="img" aria-label="%s"></div>' % html.escape(alt or "")
    la = ' loading="lazy"' if lazy else ' fetchpriority="high"'
    return ('<img src="/img/%s" alt="%s" class="%s" width="600" height="600"%s decoding="async">'
            % (name, html.escape(alt or ""), cls, la))

# ---------------------------------------------------------------- шаблоны

def head(title, desc, canonical, extra=""):
    t = html.escape(title)
    d = html.escape(desc)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{BASE}{canonical}">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:type" content="website">
<meta property="og:url" content="{BASE}{canonical}">
<meta property="og:image" content="{BASE}/img/og.jpg">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/css/style.css">
{extra}</head>
<body>
<header class="hdr">
  <div class="wrap hdr-in">
    <a class="logo" href="/" aria-label="Емкости Маркет — на главную">
      <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true"><path d="M8 4h16l-2 24H10L8 4zm3.2 3 1.5 15h6.6L20.8 7H11.2z" fill="currentColor"/></svg>
      <span>Емкости<em>Маркет</em></span>
    </a>
    <nav class="nav" id="nav">
      <a href="/catalog/">Каталог</a>
      <a href="/about/">О компании</a>
      <a href="/delivery/">Доставка</a>
      <a href="/payment/">Оплата</a>
      <a href="/contacts/">Контакты</a>
    </nav>
    <div class="hdr-contacts">
      <a class="hdr-phone" href="tel:{PHONE_TEL}">{PHONE_HUMAN}</a>
      <button class="burger" id="burger" aria-label="Меню" aria-expanded="false"><span></span><span></span><span></span></button>
    </div>
  </div>
</header>
<main>
"""

FOOT = f"""</main>
<footer class="ftr">
  <div class="wrap ftr-in">
    <div class="ftr-col">
      <div class="ftr-brand">Емкости<em>Маркет</em></div>
      <p class="ftr-addr">{ADDRESS}<br>{WORK_HOURS}</p>
      <div class="soc" aria-label="Мы в соцсетях">
        <a href="#" class="soc-i" title="ВКонтакте (скоро)" aria-label="ВКонтакте (скоро)"><svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M12.8 17.5c-5 0-8.2-3.6-8.3-9.6h2.6c.1 4.5 2.1 6.4 3.7 6.8V7.9h2.5v3.8c1.5-.2 3.1-2 3.7-3.8h2.5c-.4 2.2-2.1 4-3.3 4.7 1.2.6 3.2 2.2 3.9 4.9h-2.7c-.6-1.8-2-3.2-4.1-3.4v3.4h-.5z"/></svg></a>
        <a href="#" class="soc-i" title="Telegram (скоро)" aria-label="Telegram (скоро)"><svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M20.7 4.3 3.6 10.9c-.9.4-.9 1.6 0 1.9l4.2 1.4 1.6 4.9c.2.7 1.1.9 1.6.4l2.3-2.3 4.4 3.2c.6.5 1.5.1 1.7-.6l3-14.2c.2-.8-.6-1.5-1.7-1.3zM9.7 14.1l-.2 3.1-1-3.1 7.5-5.4-6.3 5.4z"/></svg></a>
        <a href="#" class="soc-i" title="WhatsApp (скоро)" aria-label="WhatsApp (скоро)"><svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M12 2a10 10 0 0 0-8.6 15L2 22l5.2-1.4A10 10 0 1 0 12 2zm0 2a8 8 0 1 1-4.1 14.9l-.3-.2-2.6.7.7-2.5-.2-.3A8 8 0 0 1 12 4zm-3 4.2c-.2 0-.5.1-.7.4-.2.3-.9.9-.9 2.1s.9 2.4 1 2.6c.1.2 1.8 2.9 4.5 3.9 2.2.9 2.6.7 3.1.7.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.1-1.2l-.6-.3-1.5-.8c-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1-.2-.1-1.1-.4-2.1-1.3-.8-.7-1.3-1.5-1.4-1.7-.1-.2 0-.4.1-.5l.4-.5.3-.5v-.4l-.7-1.7c-.2-.4-.4-.4-.6-.4H9z"/></svg></a>
        <a href="#" class="soc-i" title="YouTube (скоро)" aria-label="YouTube (скоро)"><svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M21.6 7.2c-.2-.9-.9-1.6-1.8-1.8C18.2 5 12 5 12 5s-6.2 0-7.8.4c-.9.2-1.6.9-1.8 1.8C2 8.8 2 12 2 12s0 3.2.4 4.8c.2.9.9 1.6 1.8 1.8 1.6.4 7.8.4 7.8.4s6.2 0 7.8-.4c.9-.2 1.6-.9 1.8-1.8.4-1.6.4-4.8.4-4.8s0-3.2-.4-4.8zM10 15V9l5.2 3L10 15z"/></svg></a>
      </div>
    </div>
    <div class="ftr-col">
      <div class="ftr-h">Каталог</div>
      <a href="/catalog/plastikovie-emkosti/">Пластиковые емкости</a>
      <a href="/catalog/mini-azs-dlya-dizelnogo-topliva/">Мини АЗС</a>
      <a href="/catalog/septiki-dlya-kanalizatsii/">Септики</a>
      <a href="/catalog/podzemnie/">Подземные емкости</a>
      <a href="/catalog/">Весь каталог</a>
    </div>
    <div class="ftr-col">
      <div class="ftr-h">Покупателям</div>
      <a href="/delivery/">Доставка</a>
      <a href="/payment/">Способы оплаты</a>
      <a href="/about/">О компании</a>
      <a href="/contacts/">Контакты и адреса</a>
      <a href="/docs/">Документы</a>
    </div>
    <div class="ftr-col ftr-cta">
      <div class="ftr-h">Связаться</div>
      <a class="ftr-phone" href="tel:{PHONE_TEL}">{PHONE_HUMAN}</a>
      <a class="ftr-mail" href="mailto:{EMAIL}">{EMAIL}</a>
      <a class="btn btn-primary ftr-btn" href="tel:{PHONE_TEL}">Заказать звонок</a>
    </div>
  </div>
  <div class="wrap ftr-legal">
    <span>© 2007–2026 {COMPANY}. {INN}.</span>
    <span>Информация на сайте не является публичной офертой.</span>
    <a href="/docs/privacy/">Политика конфиденциальности</a>
  </div>
</footer>
<script src="/js/main.js" defer></script>
</body>
</html>
"""

def write(path, content):
    # Относительные пути: сайт одинаково работает и в корне домена, и в подпапке
    # GitHub Pages (/emkostimarket_dev/), и при открытии файла с диска.
    if path.endswith(".html"):
        prefix = "../" * path.count("/")
        content = re.sub(r'((?:href|src|data-full)=")/(?!/)',
                         lambda m: m.group(1) + prefix, content)
    full = os.path.join(SITE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)

# ---------------------------------------------------------------- карточки

def product_card(p, lazy=True):
    img = p["images"][0]["src"] if p.get("images") else ""
    price = int(p["prices"]["price"] or 0)
    reg = int(p["prices"]["regular_price"] or 0)
    sale = p.get("on_sale") and reg > price
    cats = ", ".join(c["name"] for c in p.get("categories", []))
    h = '<a class="card" href="/product/%s/">' % p["slug"]
    h += '<div class="card-img">' + img_tag(img, p["name"], "card-pic", lazy) + (
        '<span class="badge">Хит</span>' if sale else "") + "</div>"
    h += '<div class="card-body">'
    h += '<div class="card-cat">%s</div>' % html.escape(cats)
    h += '<div class="card-title">%s</div>' % html.escape(p["name"])
    h += '<div class="card-price">'
    if sale:
        h += '<span class="old">%s ₽</span> ' % money(reg)
    h += '<span class="now">%s ₽</span>' % money(price)
    h += "</div>"
    h += '<span class="card-cta">Подробнее →</span>'
    h += "</div></a>"
    return h

def breadcrumbs(items):
    h = '<nav class="crumbs" aria-label="Хлебные крошки"><a href="/">Главная</a>'
    for i, (title, url) in enumerate(items):
        if i == len(items) - 1:
            h += '<span class="sep">/</span><span class="cur">%s</span>' % html.escape(title)
        else:
            h += '<span class="sep">/</span><a href="%s">%s</a>' % (url, html.escape(title))
    return h + "</nav>"

# ---------------------------------------------------------------- страницы

def build_home(products, cats):
    top = sorted(cats, key=lambda c: -len(collect(c, products)))[:8]
    sect = ""
    for c in top:
        items = collect(c, products)[:4]
        if not items:
            continue
        sect += '<section class="sec"><div class="sec-h"><h2>%s</h2><a class="more" href="/catalog/%s/">Все →</a></div><div class="grid">' % (
            html.escape(c["name"]), c["slug"])
        sect += "".join(product_card(p) for p in items)
        sect += "</div></section>"

    cats_list = ""
    for c in sorted([x for x in cats if not (x.get("parent") or 0)], key=lambda x: x["name"]):
        n = len(collect(c, products))
        if n:
            cats_list += '<li><a href="/catalog/%s/">%s <span>%d</span></a></li>' % (
                c["slug"], html.escape(c["name"]), n)

    body = f"""
<section class="hero">
  <div class="wrap hero-in">
    <div class="hero-txt">
      <h1>Пластиковые емкости, мини АЗС и септики с доставкой по всей России</h1>
      <p>Производим и продаём ёмкости для воды, дизтоплива и пищевых продуктов. Подземные и наземные резервуары, мобильные заправочные комплексы, септики. Помогаем подобрать и быстро отгружаем со склада в Санкт-Петербурге.</p>
      <div class="hero-btns">
        <a class="btn btn-primary" href="/catalog/">Смотреть каталог</a>
        <a class="btn btn-ghost" href="tel:{PHONE_TEL}">{PHONE_HUMAN}</a>
      </div>
      <ul class="hero-facts">
        <li><b>166</b><span>товаров в наличии</span></li>
        <li><b>17</b><span>лет на рынке</span></li>
        <li><b>РФ</b><span>доставка по стране</span></li>
      </ul>
    </div>
    <div class="hero-pic">{img_tag("http://192.168.0.212/wp-content/uploads/2019/04/2-2.jpg", "Пластиковые емкости", "hero-img", lazy=False)}</div>
  </div>
</section>

<section class="wrap sec">
  <div class="sec-h"><h2>Каталог</h2></div>
  <ul class="cat-list">{cats_list}</ul>
</section>

{sect}

<section class="wrap cta-band">
  <div>
    <h2>Нужна ёмкость под задачу?</h2>
    <p>Подберём объём, материал и комплектацию. Рассчитаем доставку по России.</p>
  </div>
  <a class="btn btn-primary" href="tel:{PHONE_TEL}">Позвонить {PHONE_HUMAN}</a>
</section>
"""
    write("index.html", head(
        "Пластиковые емкости для воды и топлива | Емкости Маркет",
        "Пластиковые ёмкости, мини АЗС для ДТ, септики и подземные резервуары. "
        "166 товаров, доставка по всей России. ООО «Емкости Маркет», Санкт-Петербург.",
        "/", extra='<meta name="theme-color" content="#0d5c46">\n') + body + FOOT)

def collect(cat, products):
    """товары категории и всех потомков"""
    ids = {cat["id"]}
    stack = [cat["id"]]
    by_id = {c["id"]: c for c in cat.get("_all") or []}
    # потомки ищем через parent-ссылки
    changed = True
    while changed:
        changed = False
        for c in (cat.get("_all") or []):
            if (c.get("parent") or 0) in ids and c["id"] not in ids:
                ids.add(c["id"]); changed = True
    res = [p for p in products if any(c["id"] in ids for c in p["categories"])]
    return res

def build_catalog(products, cats):
    write("catalog/index.html", head(
        "Каталог пластиковых ёмкостей, мини АЗС и септиков | Емкости Маркет",
        "Все категории каталога: пластиковые ёмкости, мини АЗС, септики, подземные "
        "и наземные резервуары. 166 товаров с ценами.",
        "/catalog/") + breadcrumbs([("Каталог", "/catalog/")]).replace(
            '<nav class="crumbs"', '<nav class="crumbs wrap"') + """
<section class="wrap sec">
  <h1 class="h1">Каталог</h1>
  <p class="lead">166 товаров в наличии с доставкой по России.</p>
""" + "".join(cat_block(c, products) for c in sorted(cats, key=lambda x: x["name"]) if collect(c, products)) + """
</section>""" + FOOT)

def cat_block(c, products):
    items = collect(c, products)
    if not items:
        return ""
    h = '<div class="cat-block" id="%s"><h2><a href="/catalog/%s/">%s</a> <span class="cnt">%d</span></h2><div class="grid">' % (
        c["slug"], c["slug"], html.escape(c["name"]), len(items))
    h += "".join(product_card(p) for p in sorted(items, key=lambda p: p["name"])[:8])
    if len(items) > 8:
        h += '<a class="card card-all" href="/catalog/%s/"><div class="card-body"><div class="card-title">Все %d товаров →</div></div></a>' % (
            c["slug"], len(items))
    h += "</div></div>"
    return h

def build_category(cat, products, all_cats):
    items = collect(cat, products)
    if not items:
        return
    desc = strip_tags(cat.get("description") or "")
    body = breadcrumbs([("Каталог", "/catalog/"), (cat["name"], "/catalog/%s/" % cat["slug"])])
    body = body.replace('<nav class="crumbs"', '<nav class="crumbs wrap"')
    body += '<section class="wrap sec">'
    body += '<h1 class="h1">%s</h1>' % html.escape(cat["name"])
    if desc:
        body += '<p class="lead">%s</p>' % html.escape(desc[:400])
    # подкатегории
    subs = [c for c in all_cats if (c.get("parent") or 0) == cat["id"] and collect(c, products)]
    if subs:
        body += '<div class="subs">' + "".join(
            '<a class="sub" href="/catalog/%s/">%s <span>%d</span></a>' % (
                c["slug"], html.escape(c["name"]), len(collect(c, products)))
            for c in subs) + "</div>"
    body += '<div class="grid">' + "".join(
        product_card(p) for p in sorted(items, key=lambda p: p["name"])) + "</div>"
    body += "</section>"
    write("catalog/%s/index.html" % cat["slug"],
          head("%s — купить | Емкости Маркет" % cat["name"],
               "%s: %d товаров с ценами. Доставка по всей России." % (cat["name"], len(items)),
               "/catalog/%s/" % cat["slug"]) + body + FOOT)

def build_product(p, all_cats):
    imgs = [i["src"] for i in p.get("images", [])]
    gal = "".join(
        '<button class="thumb" data-full="/img/%s">%s</button>' % (
            IMG_MAP.get(s, ""), img_tag(s, p["name"], "thumb-pic"))
        for s in imgs if IMG_MAP.get(s))
    price = int(p["prices"]["price"] or 0)
    reg = int(p["prices"]["regular_price"] or 0)
    sale = p.get("on_sale") and reg > price

    specs = clean_html(p.get("short_description") or "")
    # из short_description обычно h1 + список характеристик
    specs = re.sub(r'<h1[^>]*>.*?</h1>', '', specs, flags=re.S)
    long = clean_html(p.get("description") or "")

    cr = [("Каталог", "/catalog/")]
    if p["categories"]:
        c0 = p["categories"][0]
        cr.append((c0["name"], "/catalog/%s/" % c0["slug"]))
    cr.append((p["name"], "/product/%s/" % p["slug"]))
    body = breadcrumbs(cr).replace('<nav class="crumbs"', '<nav class="crumbs wrap"')

    body += '<section class="wrap prod">'
    body += '<div class="prod-gal"><div class="main-pic" id="mainPic">%s</div><div class="thumbs">%s</div></div>' % (
        img_tag(imgs[0] if imgs else "", p["name"], "main-pic-img", lazy=False) if imgs
        else '<div class="noimg big"></div>', gal)
    body += '<div class="prod-info">'
    body += '<div class="prod-cat">%s</div>' % html.escape(", ".join(c["name"] for c in p["categories"]))
    body += '<h1 class="prod-title">%s</h1>' % html.escape(p["name"])
    body += '<div class="prod-price">'
    if sale:
        body += '<span class="old">%s ₽</span>' % money(reg)
    body += '<span class="now">%s ₽</span>' % money(price)
    if p["is_in_stock"]:
        body += '<span class="stock">В наличии</span>'
    body += "</div>"
    body += '<div class="prod-btns"><a class="btn btn-primary" href="tel:%s">Заказать</a><a class="btn btn-ghost" href="mailto:%s?subject=Заказ: %s">Написать в почту</a></div>' % (
        PHONE_TEL, EMAIL, html.escape(p["name"]))
    if specs:
        body += '<div class="prod-specs">%s</div>' % specs
    body += "</div></section>"

    if long:
        body += '<section class="wrap sec prod-desc"><h2>Описание</h2>%s</section>' % long

    related = [x for x in (p.get("_related") or []) if x["slug"] != p["slug"]][:4]
    if related:
        body += '<section class="sec"><div class="wrap"><div class="sec-h"><h2>Похожие товары</h2></div><div class="grid">' + \
                "".join(product_card(x) for x in related) + "</div></div></section>"

    write("product/%s/index.html" % p["slug"],
          head("%s — цена %s ₽ | Емкости Маркет" % (p["name"], money(price)),
               strip_tags(specs or long)[:160] or ("%s — купить по цене %s ₽. В наличии, доставка по России." % (p["name"], money(price))),
               "/product/%s/" % p["slug"]) + body + FOOT)

# ---------------------------------------------------------------- статические

STAT = {
    "delivery": ("Доставка по России | Емкости Маркет", "/delivery/"),
    "payment": ("Способы оплаты | Емкости Маркет", "/payment/"),
    "about": ("О компании | Емкости Маркет", "/about/"),
    "contacts": ("Контакты и адреса | Емкости Маркет", "/contacts/"),
}

def build_static_pages(pages):
    want = {
        "dostavka-tovarov": "delivery",
        "payment-methods": "payment",
        "o-kompanii": "about",
        "contacty-i-adresa": "contacts",
    }
    by_slug = {p["slug"]: p for p in pages}
    for wslug, key in want.items():
        pg = by_slug.get(wslug)
        title, canon = STAT[key]
        content = clean_html(pg["content"]["rendered"]) if pg else ""
        if key == "contacts":
            # формы CF7 на статике не работают — убираем, ниже добавим прямые контакты
            content = re.sub(r'<div class="wpcf7[^"]*".*?</form>', '', content, flags=re.S)
            content = re.sub(r'<div class="widget">.*?<h3[^>]*>Обратная связь</h3>.*?</div>\s*(?=<div class="wpcf7|$)', '', content, flags=re.S)
        body = breadcrumbs([(title.split(" | ")[0], canon)]).replace('<nav class="crumbs"', '<nav class="crumbs wrap"')
        body += '<section class="wrap sec page"><h1 class="h1">%s</h1><div class="prose">%s</div></section>' % (
            html.escape(title.split(" | ")[0]), content)
        if key == "contacts":
            body += contacts_block()
        if key == "delivery":
            body += delivery_block()
        if key == "payment":
            body += payment_block()
        write("%s/index.html" % key, head(title, strip_tags(content)[:160], canon) + body + FOOT)

    # документы
    docs = {
        "privacy": ("politika-konfidencialnosti", "Политика конфиденциальности"),
        "offer": ("offer", "Публичная оферта"),
        "return": ("usloviya-vozvrata", "Условия возврата"),
        "faq": ("faq", "Частые вопросы"),
        "docs": ("dokumentu", "Документы"),
    }
    for slug, (wslug, h1) in docs.items():
        pg = by_slug.get(wslug)
        if not pg:
            continue
        content = clean_html(pg["content"]["rendered"])
        crumb = ("Документы", "/docs/") if slug != "docs" else (h1, "/docs/")
        body = breadcrumbs([crumb, (h1, "/docs/%s/" % slug)]) if slug != "docs" else breadcrumbs([crumb])
        body = body.replace('<nav class="crumbs"', '<nav class="crumbs wrap"')
        if slug == "docs":
            links = "".join('<li><a href="/docs/%s/">%s</a></li>' % (k, v[1])
                            for k, v in docs.items() if k != "docs")
            body += '<section class="wrap sec page"><h1 class="h1">%s</h1><ul class="prose doclist">%s</ul></section>' % (h1, links)
        else:
            body += '<section class="wrap sec page"><h1 class="h1">%s</h1><div class="prose">%s</div></section>' % (h1, content)
        path = "docs/index.html" if slug == "docs" else "docs/%s/index.html" % slug
        canon = "/docs/" if slug == "docs" else "/docs/%s/" % slug
        write(path, head("%s | Емкости Маркет" % h1, h1, canon) + body + FOOT)

def contacts_block():
    return """
<div class="contact-grid">
  <div class="contact-card">
    <div class="cc-h">Телефон</div>
    <a class="cc-big" href="tel:%s">%s</a>
    <span class="cc-sub">Дополнительно: %s</span>
  </div>
  <div class="contact-card">
    <div class="cc-h">Почта</div>
    <a class="cc-big cc-mail" href="mailto:%s">%s</a>
    <span class="cc-sub">Ответим в рабочее время</span>
  </div>
  <div class="contact-card">
    <div class="cc-h">Адрес</div>
    <span class="cc-big">%s</span>
    <span class="cc-sub">%s</span>
  </div>
</div>
""" % (PHONE_TEL, PHONE_HUMAN, PHONE2_HUMAN, EMAIL, EMAIL, ADDRESS, WORK_HOURS)

def delivery_block():
    tks = [
        ("СДЭК", "до пункта выдачи и курьером"),
        ("Почта России", "посылки и грузы в любой населённый пункт"),
        ("ПЭК", "крупногабаритные ёмкости по РФ"),
        ("Деловые Линии", "паллетные отгрузки"),
        ("Байкал Сервис", "доставка грузов"),
        ("КИТ (ТК «Кит»)", "грузоперевозки"),
        ("Автотрейдинг", "межгород"),
        ("Своя логистика", "Санкт-Петербург и Ленинградская область"),
    ]
    cards = "".join('<li class="tk"><b>%s</b><span>%s</span></li>' % (n, d) for n, d in tks)
    return """
<div class="note">Страница готовится: условия и тарифы подключаем вместе с продвижением.
Ниже — предварительный список служб доставки, которыми мы уже пользуемся.</div>
<section class="tk-wrap">
  <h2>Службы доставки</h2>
  <ul class="tk-list">%s</ul>
</section>
<section class="tk-wrap">
  <h2>Как получить расчёт</h2>
  <ol class="steps">
    <li>Позвоните или напишите нам — назовите город и объём ёмкости.</li>
    <li>Мы посчитаем стоимость и сроки доставки выбранной службой.</li>
    <li>Согласуем заказ и отгрузим товар со склада.</li>
  </ol>
  <a class="btn btn-primary" href="tel:%s">Рассчитать доставку</a>
</section>
""" % (cards, PHONE_TEL)

def payment_block():
    items = [
        ("Безналичный расчёт", "Для юридических лиц и ИП выставим счёт с НДС и закрывающие документы."),
        ("Наличными", "Оплата при получении — в согласованный способ."),
        ("Онлайн-оплата", "Картой на сайте — подключаем вместе с продвижением."),
        ("Отсрочка", "Постоянным клиентам — по договорённости."),
    ]
    cards = "".join('<li class="pay"><b>%s</b><span>%s</span></li>' % (n, d) for n, d in items)
    return """
<div class="note">Приём онлайн-оплаты на сайте подключаем на следующем этапе — пока принимаем заказы
по телефону и почте, оплата удобна безналичным расчётом или при получении.</div>
<section class="tk-wrap">
  <h2>Доступные способы</h2>
  <ul class="tk-list">%s</ul>
</section>
""" % cards

# ---------------------------------------------------------------- seo

def build_robots():
    write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % BASE)

def build_sitemap(urls):
    items = "".join(
        "<url><loc>%s</loc></url>" % (BASE + u) for u in urls)
    write("sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s\n</urlset>\n' % items)

# ---------------------------------------------------------------- main

def main():
    global IMG_MAP, ID_TO_SRC, STEM_TO_FILE
    IMG_MAP = load_img_map()
    products = load_products()
    cats = load_categories()
    pages = load_pages()
    all_cats = cats
    for c in cats:
        c["_all"] = all_cats

    # индексы картинок: id вложения -> путь WP, имя файла -> локальный webp
    for p in products:
        for im in p.get("images", []):
            ID_TO_SRC[str(im["id"])] = im["src"]
    imgdir = os.path.join(SITE, "img")
    if os.path.isdir(imgdir):
        for f in os.listdir(imgdir):
            stem = os.path.splitext(f)[0]
            STEM_TO_FILE.setdefault(stem, f)
            if stem.startswith("pg_"):
                STEM_TO_FILE.setdefault(stem[3:], f)

    # связи «похожие»: та же первая категория
    by_cat = defaultdict(list)
    for p in products:
        for c in p["categories"]:
            by_cat[c["id"]].append(p)
    for p in products:
        rel = []
        seen = set()
        for c in p["categories"]:
            for q in by_cat[c["id"]]:
                if q["slug"] != p["slug"] and q["slug"] not in seen:
                    seen.add(q["slug"]); rel.append(q)
        p["_related"] = rel

    os.makedirs(SITE, exist_ok=True)
    build_home(products, cats)
    build_catalog(products, cats)
    for c in cats:
        build_category(c, products, all_cats)
    for p in products:
        build_product(p, all_cats)
    build_static_pages(pages)
    build_robots()

    urls = ["/", "/catalog/"]
    urls += ["/catalog/%s/" % c["slug"] for c in cats]
    urls += ["/product/%s/" % p["slug"] for p in products]
    urls += ["/delivery/", "/payment/", "/about/", "/contacts/",
             "/docs/", "/docs/privacy/", "/docs/offer/", "/docs/return/", "/docs/faq/"]
    build_sitemap(urls)

    n = sum(len(f) for _, _, f in os.walk(SITE))
    print("страниц:", len(urls), "| файлов в site/:", n)

if __name__ == "__main__":
    main()
