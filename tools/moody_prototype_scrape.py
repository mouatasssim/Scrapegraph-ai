import json
import os
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

TARGET = os.getenv("MOODY_TARGET", "https://moody.devconsoleconsulting.com/").rstrip("/") + "/"
MAX_PAGES = int(os.getenv("MOODY_MAX_PAGES", "100"))
TIMEOUT = int(os.getenv("MOODY_TIMEOUT", "12"))
OUT = Path(os.getenv("MOODY_OUT", "scrape_results"))
OUT.mkdir(parents=True, exist_ok=True)
HOST = urlparse(TARGET).netloc.lower()
OLD_PROCESS = "/certifications/processus-certification/"
SKIP_EXT = re.compile(r"\.(?:jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|docx?|xlsx?|pptx?|mp4|mp3|woff2?|ttf|css|js)(?:$|\?)", re.I)
PLACEHOLDER_PATTERNS = ["lorem ipsum", "texte à venir", "contenu à venir", "à compléter", "sera enrichi", "sera complété", "sera mis à jour"]

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; MoodyPrototypeAudit/2.0; +https://github.com/mouatasssim/Scrapegraph-ai)"})


def normalize_url(href: str, base: str):
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    url, _ = urldefrag(urljoin(base, href))
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or p.netloc.lower() != HOST:
        return None
    if SKIP_EXT.search(url) or any(x in p.path for x in ["/wp-admin/", "/wp-login.php", "/wp-json/", "/feed/"]):
        return None
    clean = p._replace(query="").geturl()
    if not clean.endswith("/") and "." not in p.path.rsplit("/", 1)[-1]:
        clean += "/"
    return clean


def form_summary(form):
    fields = []
    for el in form.find_all(["input", "select", "textarea", "button"]):
        fields.append({
            "tag": el.name,
            "type": el.get("type") or el.name,
            "name": el.get("name", ""),
            "required": el.has_attr("required"),
            "placeholder": el.get("placeholder", ""),
            "text": " ".join(el.stripped_strings)[:160],
        })
    return {"action": form.get("action", ""), "method": (form.get("method") or "get").lower(), "fields": fields}


def analyze_page(url: str):
    started = time.time()
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        ctype = r.headers.get("content-type", "")
        if "text/html" not in ctype.lower():
            return {"url": url, "status": r.status_code, "final_url": r.url, "content_type": ctype, "elapsed_ms": int((time.time()-started)*1000)}, []

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        h1 = [x.get_text(" ", strip=True) for x in soup.find_all("h1")]
        headings = {f"h{i}": [x.get_text(" ", strip=True) for x in soup.find_all(f"h{i}")] for i in range(1, 7)}

        text_soup = BeautifulSoup(r.text, "html.parser")
        for tag in text_soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        text = " ".join(text_soup.stripped_strings)
        text_lower = text.lower()

        links = []
        crawl_links = []
        empty_links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            absolute = urljoin(r.url, href)
            label = a.get_text(" ", strip=True)[:220]
            links.append({"href": href, "absolute": absolute, "text": label})
            n = normalize_url(href, r.url)
            if n:
                crawl_links.append(n)
            if href.strip() in {"", "#", "/#"}:
                empty_links.append({"href": href, "text": label})

        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            images.append({"src": urljoin(r.url, src) if src else "", "alt": img.get("alt"), "loading": img.get("loading", "")})

        buttons = []
        for el in soup.find_all(["button", "a"]):
            classes = " ".join(el.get("class", []))
            if el.name == "button" or "btn" in classes.lower() or "button" in classes.lower() or el.get("role") == "button":
                buttons.append({"tag": el.name, "text": el.get_text(" ", strip=True)[:220], "href": el.get("href", "")})

        meta_desc = ""
        meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        if meta:
            meta_desc = meta.get("content", "")

        canonical = ""
        canon = soup.find("link", rel=lambda v: v and "canonical" in v)
        if canon:
            canonical = canon.get("href", "")

        page = {
            "url": url,
            "final_url": r.url,
            "status": r.status_code,
            "elapsed_ms": int((time.time()-started)*1000),
            "title": title,
            "meta_description": meta_desc,
            "canonical": canonical,
            "h1": h1,
            "headings": headings,
            "forms": [form_summary(f) for f in soup.find_all("form")],
            "buttons": buttons,
            "images_count": len(images),
            "images_without_alt": sum(1 for x in images if x["alt"] is None or x["alt"] == ""),
            "images": images,
            "links": links,
            "empty_hash_links": empty_links,
            "old_process_url_present": OLD_PROCESS in r.text,
            "placeholder_hits": [p for p in PLACEHOLDER_PATTERNS if p in text_lower],
            "text_length": len(text),
        }
        return page, sorted(set(crawl_links))
    except Exception as exc:
        return {"url": url, "status": 0, "error": f"{type(exc).__name__}: {exc}", "elapsed_ms": int((time.time()-started)*1000)}, []


def crawl():
    queue = deque([TARGET])
    queued = {TARGET}
    seen = set()
    pages = []
    while queue and len(seen) < MAX_PAGES:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        print(f"[{len(seen):03d}] {url}", flush=True)
        page, discovered = analyze_page(url)
        pages.append(page)
        for link in discovered:
            if link not in seen and link not in queued:
                queued.add(link)
                queue.append(link)
    return pages


def make_summary(pages):
    ok = [p for p in pages if 200 <= p.get("status", 0) < 400]
    bad = [p for p in pages if p.get("status", 0) == 0 or p.get("status", 0) >= 400]
    title_map = {}
    for p in ok:
        if p.get("title"):
            title_map.setdefault(p["title"], []).append(p["url"])
    return {
        "target": TARGET,
        "pages_crawled": len(pages),
        "pages_ok": len(ok),
        "pages_error": len(bad),
        "pages_with_exactly_one_h1": sum(1 for p in ok if len(p.get("h1", [])) == 1),
        "h1_issues": [{"url": p["url"], "h1": p.get("h1", [])} for p in ok if len(p.get("h1", [])) != 1],
        "pages_with_old_process_url": [p["url"] for p in ok if p.get("old_process_url_present")],
        "pages_with_placeholder_markers": [{"url": p["url"], "hits": p.get("placeholder_hits", [])} for p in ok if p.get("placeholder_hits")],
        "pages_with_forms": [{"url": p["url"], "forms_count": len(p.get("forms", []))} for p in ok if p.get("forms")],
        "pages_with_images_without_alt": [{"url": p["url"], "count": p.get("images_without_alt", 0)} for p in ok if p.get("images_without_alt", 0) > 0],
        "duplicate_titles": {k: v for k, v in title_map.items() if len(v) > 1},
        "errors": bad,
    }


def run_scrapegraphai_homepage():
    from scrapegraphai.graphs import SmartScraperGraph

    graph_config = {
        "llm": {
            "model": os.getenv("MOODY_OLLAMA_MODEL", "ollama/llama3.2:1b"),
            "temperature": 0,
            "format": "json",
        },
        "verbose": True,
        "headless": True,
    }

    prompt = """
Analyze this Moody International Certification STAGING PROTOTYPE homepage as a structural prototype, not final approved copy. Extract: main navigation, page families, major CTA destinations, visible recurring components, contact mechanisms, and any obvious prototype/structural inconsistencies. State explicitly that wording/content accuracy is out of scope because final content will be supplied later. Return JSON.
""".strip()

    graph = SmartScraperGraph(prompt=prompt, source=TARGET, config=graph_config)
    return graph.run()


def write_markdown(summary, pages, sg_result=None, sg_error=None):
    md = ["# Moody prototype — structural scrape report", "", f"Target: `{TARGET}`", ""]
    md += [
        f"- Pages crawled: **{summary['pages_crawled']}**",
        f"- HTTP OK/redirect: **{summary['pages_ok']}**",
        f"- Errors: **{summary['pages_error']}**",
        f"- Pages with exactly one H1: **{summary['pages_with_exactly_one_h1']}**",
        f"- H1 issues: **{len(summary['h1_issues'])}**",
        f"- Old process URL occurrences: **{len(summary['pages_with_old_process_url'])}**",
        f"- Placeholder marker pages: **{len(summary['pages_with_placeholder_markers'])}**",
        f"- Pages with image ALT issues: **{len(summary['pages_with_images_without_alt'])}**",
        f"- Duplicate title groups: **{len(summary['duplicate_titles'])}**",
    ]
    md += ["", "## Forms detected"]
    for item in summary["pages_with_forms"]:
        md.append(f"- {item['url']} — {item['forms_count']} form(s)")
    md += ["", "## Page inventory"]
    for p in pages:
        h1 = " | ".join(p.get("h1", [])) or "(no H1)"
        md.append(f"- `{p.get('status', 0)}` {p['url']} — **{p.get('title') or '(no title)'}** — H1: {h1}")
    md += ["", "## ScrapeGraphAI homepage semantic pass"]
    if sg_result is not None:
        md += ["```json", json.dumps(sg_result, ensure_ascii=False, indent=2, default=str), "```"]
    elif sg_error:
        md.append(f"ScrapeGraphAI pass failed: `{sg_error}`")
    (OUT / "moody_prototype_report.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    pages = crawl()
    summary = make_summary(pages)
    (OUT / "moody_pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "moody_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    sg_result = None
    sg_error = None
    try:
        sg_result = run_scrapegraphai_homepage()
        (OUT / "moody_scrapegraphai.json").write_text(json.dumps(sg_result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        sg_error = f"{type(exc).__name__}: {exc}"
        (OUT / "moody_scrapegraphai_error.txt").write_text(sg_error, encoding="utf-8")
        print("ScrapeGraphAI semantic pass failed:", sg_error, flush=True)

    write_markdown(summary, pages, sg_result, sg_error)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
