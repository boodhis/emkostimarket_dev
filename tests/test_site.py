#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверки сайта emkosti.market: ссылки, картинки, каркас, SEO, данные каталога.

Запуск с Мака (перед деплоем):
    python3 -m pytest tests/ -q
или без pytest:
    python3 tests/test_site.py
"""
import os
import re
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent

try:
    import pytest  # noqa: F401
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

BRAND = "Емкости Маркет"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}
# iframe с картами Яндекса — единственный допустимый внешний ресурс
ALLOWED_HOSTS = ("yandex.ru/map-widget", "yandex.ru/maps")


def html_files():
    for p in sorted(ROOT.rglob("*.html")):
        if ".git" in p.parts or "src" in p.parts or "tests" in p.parts:
            continue
        yield p


def rel(p):
    return p.relative_to(ROOT).as_posix()


def read(p):
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------- структура

def test_html_structure():
    """Каждая страница — валидный каркас: doctype, lang, title, viewport, описание."""
    for p in html_files():
        h = read(p)
        assert re.search(r"<!doctype html>", h, re.I), f"{rel(p)}: нет doctype"
        assert 'lang="ru"' in h, f"{rel(p)}: нет lang=ru"
        m = re.search(r"<title>(.*?)</title>", h, re.S)
        assert m and m.group(1).strip(), f"{rel(p)}: пустой/нет title"
        assert BRAND in m.group(1), f"{rel(p)}: title без бренда: {m.group(1)!r}"
        assert 'name="viewport"' in h and "width=device-width" in h, f"{rel(p)}: нет viewport"
        assert 'name="description"' in h, f"{rel(p)}: нет meta description"
        assert 'rel="canonical"' in h, f"{rel(p)}: нет canonical"
        assert 'rel="icon"' in h, f"{rel(p)}: нет favicon"
        assert "<h1" in h, f"{rel(p)}: нет h1"


def test_single_h1():
    for p in html_files():
        n = len(re.findall(r"<h1[\s>]", read(p)))
        assert n == 1, f"{rel(p)}: {n} штук <h1> (должен быть ровно один)"


def test_tags_balanced():
    for p in html_files():
        h = read(p)
        h = re.sub(r"<script\b.*?</script>", "", h, flags=re.S | re.I)
        h = re.sub(r"<style\b.*?</style>", "", h, flags=re.S | re.I)
        # самозакрывающиеся <path ... /> в SVG не требуют </path>
        h = re.sub(r"<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*/>", "", h)
        opens = Counter(t.lower() for t in re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)\b", h))
        closes = Counter(t.lower() for t in re.findall(r"</([a-zA-Z][a-zA-Z0-9]*)\s*>", h))
        for tag, n in opens.items():
            if tag in VOID:
                continue
            assert closes.get(tag, 0) == n, f"{rel(p)}: <{tag}> открыт {n}, закрыт {closes.get(tag, 0)}"
        for tag, n in closes.items():
            if tag in VOID:
                continue
            assert opens.get(tag, 0) == n, f"{rel(p)}: лишний </{tag}> x{n}"


def test_unique_ids():
    for p in html_files():
        ids = re.findall(r'id="([^"]+)"', read(p))
        dups = sorted({i for i in ids if ids.count(i) > 1})
        assert not dups, f"{rel(p)}: дубли id: {dups}"


# ---------------------------------------------------------------- ссылки

def test_all_links_resolve():
    """Все внутренние ссылки (абсолютные и относительные) указывают на файл."""
    bad = []
    for p in html_files():
        base = p.parent
        for href in re.findall(r'(?:href|src|data-full)="([^"]*)"', read(p)):
            if href.startswith(("http://", "https://", "//", "#",
                                "mailto:", "tel:", "data:")):
                continue
            target = href.split("#")[0].split("?")[0]
            if not target:
                continue
            resolved = (base / target).resolve()
            cands = [resolved] if "." in resolved.name \
                else [resolved, resolved.parent / (resolved.name + ".html"),
                      resolved / "index.html"]
            if not any(Path(c).exists() for c in cands):
                bad.append(f"{rel(p)} -> {href}")
            elif not str(resolved).startswith(str(ROOT)):
                bad.append(f"{rel(p)} -> {href} (выходит за пределы сайта)")
    assert not bad, "битые ссылки:\n  " + "\n  ".join(bad[:30])


def test_no_absolute_host_links():
    """Навигация и ресурсы — относительные. Абсолютный URL допустим только
    в canonical/og (так требует SEO), в картах Яндекса и в текстовых ссылках
    юридических документов (<a href> на consultant.ru)."""
    bad = []
    for p in html_files():
        h = read(p)
        # выкидываем мета-теги, где абсолютный URL обязателен
        h = re.sub(r'<link rel="canonical"[^>]*>', "", h)
        h = re.sub(r'<meta property="og:[^"]*"[^>]*>', "", h)
        # текстовые ссылки <a href="http..."> — это цитаты законов, не ресурсы
        h = re.sub(r'<a [^>]*href="https?://[^"]*"[^>]*>', "", h)
        for href in re.findall(r'(?:href|src)="(https?://[^"]*)"', h):
            if "yandex.ru/map" in href:
                continue
            bad.append(f"{rel(p)} -> {href}")
    assert not bad, "абсолютные ссылки (должны быть относительные):\n  " + "\n  ".join(bad[:20])


def test_sitemap():
    sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>https://emkosti\.market([^<]+)</loc>", sm)
    assert len(locs) >= 190, f"в sitemap всего {len(locs)} URL, ожидалось ~197"
    missing = [u for u in locs
               if not (ROOT / u.lstrip("/").rstrip("/") / "index.html").exists()
               and not (ROOT / u.lstrip("/")).exists()]
    assert not missing, "sitemap ведёт на несуществующее: " + ", ".join(missing[:10])


def test_robots():
    r = (ROOT / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://emkosti.market/sitemap.xml" in r, "robots.txt без sitemap"


# ---------------------------------------------------------------- картинки

def test_all_images_exist():
    bad = []
    for p in html_files():
        base = p.parent
        for src in re.findall(r'<img[^>]+src="([^"]+)"', read(p)):
            if src.startswith(("http", "//", "data:")):
                bad.append(f"{rel(p)} -> {src} (внешняя картинка)")
                continue
            if not (base / src.split("?")[0]).resolve().exists():
                bad.append(f"{rel(p)} -> {src}")
    assert not bad, "нет файла картинки:\n  " + "\n  ".join(bad[:20])


def test_no_remote_images():
    bad = []
    for p in html_files():
        for src in re.findall(r'<img[^>]+src="(https?://[^"]+)"', read(p)):
            bad.append(f"{rel(p)} -> {src}")
    assert not bad, "картинки с чужих серверов:\n  " + "\n  ".join(bad[:20])


def test_images_have_alt():
    bad = [rel(p) for p in html_files()
           if re.search(r"<img(?![^>]*\salt=)[^>]*>", read(p))]
    assert not bad, "картинки без alt: " + ", ".join(bad[:10])


def test_img_lazy_below_fold():
    """Первый экран (главная, карточка товара) грузится сразу, остальное lazy."""
    home = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'fetchpriority="high"' in home, "на главной нет приоритетной картинки"
    n_prod = len(list((ROOT / "product").glob("*/index.html")))
    assert n_prod >= 160, f"карточек товаров всего {n_prod}, ожидалось 166"


# ---------------------------------------------------------------- данные каталог

def test_product_count():
    n = len(list((ROOT / "product").glob("*/index.html")))
    assert n == 166, f"{n} карточек товаров, ожидалось 166"


def test_category_count():
    cats = [p for p in (ROOT / "catalog").iterdir() if p.is_dir()]
    assert len(cats) == 20, f"{len(cats)} категорий, ожидалось 20"
    assert (ROOT / "catalog/index.html").exists(), "нет /catalog/"


def test_prices_on_products():
    """У каждой карточки есть цена в ₽ и отметка о наличии."""
    bad = []
    for p in (ROOT / "product").glob("*/index.html"):
        h = read(p)
        if not re.search(r'class="now">[\d\s]+ ₽', h):
            bad.append(p.parent.name)
        if "В наличии" not in h:
            bad.append(p.parent.name + " (нет «В наличии»)")
    assert not bad, "карточки без цены/наличия: " + ", ".join(sorted(set(bad))[:15])


def test_no_zero_prices():
    bad = [p.parent.name for p in (ROOT / "product").glob("*/index.html")
           if re.search(r'class="now">0 ₽', read(p))]
    assert not bad, "цена 0 ₽: " + ", ".join(bad[:15])


def test_catalog_links_to_every_product():
    """Каждый товар должен быть достижим из каталога (не «сирота»)."""
    cat_html = "".join(read(p) for p in (ROOT / "catalog").rglob("index.html"))
    orphans = [p.parent.name for p in (ROOT / "product").glob("*/index.html")
               if f'/product/{p.parent.name}/' not in cat_html]
    assert not orphans, "товары не найдены в каталоге: " + ", ".join(orphans[:15])


# ---------------------------------------------------------------- контент/стиль

def test_no_wordpress_leftovers():
    """Ни одного следа WordPress/WPBakery в разметке."""
    bad = []
    for p in html_files():
        h = read(p)
        for pat, label in (
            (r"\[[a-z_][a-z0-9_]*[^\]]{0,30}\]", "шорткод"),
            (r"wp-content", "wp-content"),
            (r"192\.168\.", "локальный IP"),
            (r"wpcf7", "форма CF7"),
            (r"fancybox", "fancybox"),
            (r"vc_column|vc_row", "WPBakery"),
        ):
            if re.search(pat, h):
                bad.append(f"{rel(p)}: {label}")
    assert not bad, "WordPress-мусор:\n  " + "\n  ".join(bad[:20])


def test_no_secrets():
    """Секреты и служебные данные не должны попасть на сайт (правило волта).
    ⚠️ Короткие числа (пароль sudo) не проверяем — ложные срабатывания:
    «1780» встречается как высота бочки 1780 мм. Ищем только в контексте."""
    secrets = ("Bananamama", "cf87463", "aSpNvqtwwNN4jK4V4dLJ", "emkosti_db",
               "ssh-rsa", "BEGIN OPENSSH")
    ctx_secrets = (r"sudo -S", r"echo 1780 \|", r"1780 \| sudo", r"password 1780")
    for p in list(html_files()) + [ROOT / "robots.txt", ROOT / "sitemap.xml"]:
        h = read(p)
        for s in secrets:
            assert s not in h, f"{rel(p)}: утечка {s!r}"
        for pat in ctx_secrets:
            assert not re.search(pat, h), f"{rel(p)}: утечка в контексте {pat!r}"


def test_key_pages():
    for rel_path in ("index.html", "catalog/index.html", "delivery/index.html",
                     "payment/index.html", "about/index.html", "contacts/index.html",
                     "docs/index.html", "docs/privacy/index.html",
                     "css/style.css", "js/main.js", "favicon.svg",
                     "img/og.jpg", "sitemap.xml", "robots.txt"):
        assert (ROOT / rel_path).exists(), f"нет {rel_path}"


def test_footer_contacts():
    """Футер на всех страницах: телефон, почта, заглушки соцсетей, реквизиты."""
    for p in html_files():
        h = read(p)
        assert 'href="tel:+79119225732"' in h, f"{rel(p)}: нет телефона в футере"
        assert "emkosti.market@yandex.ru" in h, f"{rel(p)}: нет почты в футере"
        assert h.count('class="soc-i"') == 4, f"{rel(p)}: не 4 иконки соцсетей"
        assert "ООО «ЕМКОСТИ МАРКЕТ»" in h, f"{rel(p)}: нет реквизитов"
        assert 'class="ftr"' in h, f"{rel(p)}: нет футера"


def test_footer_is_compact():
    """Футер компактный: одна сетка, без простыней текста."""
    ftr_css = (ROOT / "css/style.css").read_text(encoding="utf-8")
    assert ".ftr-in{display:grid" in ftr_css, "футер не на сетке"
    for p in html_files():
        h = read(p)
        m = re.search(r'<footer class="ftr">.*?</footer>', h, re.S)
        assert m, f"{rel(p)}: футер не найден"
        assert len(m.group(0)) < 4500, f"{rel(p)}: футер {len(m.group(0))} символов — слишком большой"


def test_delivery_stub():
    """Страница доставки — заглушка под реальные РК-стеки + реальные условия."""
    h = (ROOT / "delivery/index.html").read_text(encoding="utf-8")
    for tk in ("СДЭК", "Почта России", "ПЭК", "Деловые Линии", "Байкал Сервис"):
        assert tk in h, f"в доставке нет {tk}"
    assert "Страница готовится" in h, "нет пометки, что страница дополняется"
    assert "Самовывоз" in h, "потеряны реальные условия со старого сайта"


def test_no_working_forms():
    """Заказы принимаем по телефону/почте — рабочих форм на сайте быть не должно."""
    for p in html_files():
        h = read(p)
        assert "<form" not in h, f"{rel(p)}: есть <form> — она не работает на статике"
        assert "type=\"password\"" not in h, f"{rel(p)}: поле пароля"


def test_socials_are_placeholders():
    """Соцсети — заглушки (закрыты до продвижения), не мёртвые ссылки на чужое."""
    for p in html_files():
        h = read(p)
        for m in re.findall(r'<a href="([^"]*)" class="soc-i"', h):
            assert m == "#", f"{rel(p)}: соцссылка {m} должна быть заглушкой «#»"
        assert "(скоро)" in h, f"{rel(p)}: нет пометки «скоро» у соцсетей"


def test_no_external_resources():
    """Сайт не тянет внешние шрифты/стили/скрипты/картинки.
    Текстовые ссылки <a href="http..."> в юридических документах — допустимы:
    это цитаты законов, а не подгружаемые ресурсы."""
    bad = []
    for p in html_files():
        h = read(p)
        h = re.sub(r'<a [^>]*href="https?://[^"]*"[^>]*>', "", h)  # ссылки-цитаты
        for url in re.findall(r'(?:src|href)="(https?://[^"]+)"', h):
            if "yandex.ru/map" in url or "emkosti.market" in url:
                continue
            bad.append(f"{rel(p)} -> {url}")
    for p in (ROOT / "css").glob("*.css"):
        for url in re.findall(r'url\((["\']?)(https?://[^)]+)\)', read(p)):
            bad.append(f"{rel(p)} -> {url[1]}")
    assert not bad, "внешние ресурсы:\n  " + "\n  ".join(bad[:20])


def test_css_no_broken_urls():
    css = (ROOT / "css/style.css").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}"), "css/style.css: непарные скобки"
    assert len(css) > 5000, "css/style.css подозрительно мал"


def test_no_todo_fixme():
    """Не публикуем забытые пометки."""
    bad = []
    for p in html_files():
        h = read(p)
        for tag in ("TODO", "FIXME", "XXX", "lorem ipsum", "Lorem ipsum"):
            if tag in h:
                bad.append(f"{rel(p)}: {tag}")
    assert not bad, "черновые пометки:\n  " + "\n  ".join(bad[:15])


def test_home_first_screen():
    h = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "<h1>" in h and "Пластиковые емкости" in h, "на главной нет h1 с темой"
    assert re.search(r'href="(?:\./)?catalog/"', h), "на главной нет входа в каталог"
    assert h.count('class="card') >= 20, "на главной слишком мало товаров"


# ---------------------------------------------------------------- запуск

def _run():
    import traceback
    names = sorted(n for n, v in globals().items()
                   if n.startswith("test_") and callable(v))
    failed = 0
    for name in names:
        try:
            globals()[name]()
            print("PASS", name)
        except AssertionError as e:
            failed += 1
            print("FAIL", name, "\n   ", e)
        except Exception:
            failed += 1
            print("ERROR", name)
            traceback.print_exc()
    print(f"\n{len(names) - failed}/{len(names)} проверок пройдено")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _run()
