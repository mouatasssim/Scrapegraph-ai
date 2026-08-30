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
MAX_PAGES = int(os.getenv("MOODY_MAX_PAGES", "120"))
TIMEOUT = int(os.getenv("MOODY_TIMEOUT", "20"))
OUT = Path(os.getenv("MOODY_OUT", "scrape_results"))
OUT.mkdir(parents=True, exist_ok=True)

HOST = urlparse(TARGET).netloc.lower()
SKIP_EXT = re.compile(r"\.(?:jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|docx?|xlsx?|pptx?|mp4|mp3|woff2?|ttf|css|js)(?:$|\?)", re.I)
PLACEHOLDER_PATTERNS = [
    "lorem ipsum",
    "texte à venir",
    "contenu à venir",
    "à compléter",
    "sera enrichi",
    "sera complété",
    "sera mis à jour",
]
OLD_PROCESS = "/certifications/processus-certification/"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; MoodyPrototypeAudit/1.0; +https://github.com/mouatasssim/Scrapegraph-ai)"
})


def normalize_url(href: str, base: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    url = urljoin(base, href)
    url, _ = urldefrag(url)
    p = urlparse(url)
    if p.scheme not in {"http", "https"}:
        return None
    if p.netloc.lower() != HOST:
        return None
    if SKIP_EXT.search(url):
        return None
    if any(x in p.path for x in ["/wp-admin/", "/wp-login.php", "/wp-json/", "/feed/"]):
        return None
    clean = p._replace(query="").geturl()
    if not clean.endswith("/") and "." not in p.path.rsplit("/", 1)[-1]:
        clean += "/"
    return clean


def absolute_link(href: str, base: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:")):
        return href
    return urljoin(base, href)


def visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return " ".join(soup.stripped_strings)


def form_summary(form):
    fields = []
    for el in form.find_all(["input", "select", "textarea", "button"]):
        typ = el.get("type") or el.name
        fields.append({
            "tag": el.name,
            "type": typ,
            "name": el.get("name", ""),
            "required": el.has_attr("required"),
            "placeholder": el.get("placeholder", ""),
            "label_or_text": " ".join(el.stripped_strings)[:200],
        })
    return {
        "action": form.get("action", ""),
        "method": (form.get("method") or "get").lower(),
        "fields": fields,
    }


def analyze_page(url: str):
    started = time.time()
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        status = r.status_code
        ctype = r.headers.get("content-type", "")
        if "text/html" not in ctype.lower():
            return {
                "url": url,
                "status": status,
                "final_url": r.url,
                "content_type": ctype,
                "elapsed_ms": int((time.time() - started) * 1000),
                "skip": "non-html",
            }, []

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        h1 = [x.get_text(" ", strip=True) for x in soup.find_all("h1")]
        headings = {
            f"h{i}": [x.get_text(" ", strip=True) for x in soup.find_all(f"h{i}")]
            for i in range(1, 7)
        }
        text = visible_text(BeautifulSoup(r.text, "html.parser"))
        text_lower = text.lower()

        links = []
        internal_for_crawl = []
        broken_candidates = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            abs_url = absolute_link(href, r.url)
            label = a.get_text(" ", strip=True)
            links.append({"href": href, "absolute": abs_url, "text": label[:240]})
            normalized = normalize_url(href, r.url)
            if normalized:
                internal_for_crawl.append(normalized)
            if href in {"#", "", "/#"}:
                broken_candidates.append({"href": href, "text": label})

        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            images.append({
                "src": urljoin(r.url, src) if src else "",
                "alt": img.get("alt"),
                "loading": img.get("loading", ""),
            })

        buttons = []
        for el in soup.find_all(["button", "a"]):
            classes = " ".join(el.get("class", []))
            role = el.get("role", "")
            if el.name == "button" or "btn" in classes.lower() or "button" in classes.lower() or role == "button":
                buttons.append({
                    "tag": el.name,
                    "text": el.get_text(" ", strip=True)[:240],
                    "href": el.get("href", ""),
                    "classes": classes[:300],
                })

        forms = [form_summary(f) for f in soup.find_all("form")]
        placeholder_hits = [p for p in PLACEHOLDER_PATTERNS if p in text_lower]

        meta_description = ""
        meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        if meta:
            meta_description = meta.get("content", "")

        canonical = ""
        canon = soup.find("link", rel=lambda v: v and "canonical" in v)
        if canon:
            canonical = canon.get("href", "")

        page = {
            "url": url,
            "final_url": r.url,
            "status": status,
            "elapsed_ms": int((time.time() - started) * 1000),
            "title": title,
            "meta_description": meta_description,
            "canonical": canonical,
            "h1": h1,
            "headings": headings,
            "forms": forms,
            "buttons": buttons,
            "images_count": len(images),
            "images_without_alt": sum(1 for x in images if x["alt"] is None or x["alt"] == ""),
            "images": images,
            "internal_links_count": sum(1 for x in links if x["absolute"] and urlparse(x["absolute"]).netloc.lower() == HOST),
            "links": links,
            "empty_hash_links": broken_candidates,
            "old_process_url_present": OLD_PROCESS in r.text,
            "placeholder_hits": placeholder_hits,
            "text_length": len(text),
            "html_length": len(r.text),
        }
        return page, sorted(set(internal_for_crawl))
    except Exception as exc:
        return {
            "url": url,
            "status": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": int((time.time() - started) * 1000),
        }, []


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


def deterministic_summary(pages):
    ok = [p for p in pages if 200 <= p.get("status", 0) < 400]
    bad = [p for p in pages if p.get("status", 0) == 0 or p.get("status", 0) >= 400]
    one_h1 = [p for p in ok if len(p.get("h1", [])) == 1]
    h1_issues = [p for p in ok if len(p.get("h1", [])) != 1]
    old_links = [p for p in ok if p.get("old_process_url_present")]
    placeholders = [p for p in ok if p.get("placeholder_hits")]
    forms = [p for p in ok if p.get("forms")]
    alt_issues = [p for p in ok if p.get("images_without_alt", 0) > 0]

    title_map = {}
    for p in ok:
        t = p.get("title", "").strip()
        if t:
            title_map.setdefault(t, []).append(p["url"])
    duplicate_titles = {k: v for k, v in title_map.items() if len(v) > 1}

    summary = {
        "target": TARGET,
        "pages_crawled": len(pages),
        "pages_ok": len(ok),
        "pages_error": len(bad),
        "pages_with_exactly_one_h1": len(one_h1),
        "h1_issues": [{"url": p["url"], "h1": p.get("h1", [])} for p in h1_issues],
        "pages_with_old_process_url": [p["url"] for p in old_links],
        "pages_with_placeholder_markers": [{"url": p["url"], "hits": p.get("placeholder_hits", [])} for p in placeholders],
        "pages_with_forms": [{"url": p["url"], "forms_count": len(p.get("forms", []))} for p in forms],
        "pages_with_images_without_alt": [{"url": p["url"], "count": p.get("images_without_alt", 0)} for p in alt_issues],
        "duplicate_titles": duplicate_titles,
        "errors": bad,
    }
    return summary


def write_markdown(summary, pages, scrapegraph_result=None, scrapegraph_error=None):
    md = []
    md.append("# Moody prototype — structural scrape report\n")
    md.append(f"Target: `{TARGET}`  \n")
    md.append(f"Pages crawled: **{summary['pages_crawled']}**  \n")
    md.append(f"HTTP OK/redirect: **{summary['pages_ok']}**  \n")
    md.append(f"Errors: **{summary['pages_error']}**  \n")
    md.append(f"Pages with one H1: **{summary['pages_with_exactly_one_h1']}**\n")

    md.append("\n## Structural issues\n")
    md.append(f"- H1 issues: **{len(summary['h1_issues'])}**")
    md.append(f"- Old `/certifications/processus-certification/` occurrences: **{len(summary['pages_with_old_process_url'])}**")
    md.append(f"- Placeholder-content markers: **{len(summary['pages_with_placeholder_markers'])}**")
    md.append(f"- Pages with missing image ALT: **{len(summary['pages_with_images_without_alt'])}**")
    md.append(f"- Duplicate title groups: **{len(summary['duplicate_titles'])}**")

    md.append("\n## Forms detected\n")
    for item in summary["pages_with_forms"]:
        md.append(f"- {item['url']} — {item['forms_count']} form(s)")

    md.append("\n## Page inventory\n")
    for p in pages:
        title = p.get("title", "") or "(no title)"
        h1 = " | ".join(p.get("h1", [])) or "(no H1)"
        md.append(f"- `{p.get('status', 0)}` {p['url']} — **{title}** — H1: {h1}")

    md.append("\n## ScrapeGraphAI semantic audit\n")
    if scrapegraph_result is not None:
        md.append("```json")
        md.append(json.dumps(scrapegraph_result, ensure_ascii=False, indent=2, default=str))
        md.append("```")
    elif scrapegraph_error:
        md.append(f"ScrapeGraphAI semantic pass failed: `{scrapegraph_error}`")
    else:
        md.append("ScrapeGraphAI semantic pass was not run.")

    (OUT / "moody_prototype_report.md").write_text("\n".join(md), encoding="utf-8")


def run_scrapegraphai():
    from scrapegraphai.graphs import DepthSearchGraph

    graph_config = {
        "llm": {
            "model": os.getenv("MOODY_OLLAMA_MODEL", "ollama/llama3.2:1b"),
            "temperature": 0,
            "format": "json",
        },
        "verbose": True,
        "headless": True,
        "depth": int(os.getenv("MOODY_GRAPH_DEPTH", "2")),
        "only_inside_links": True,
    }

    prompt = """
Audit this Moody International Certification staging PROTOTYPE as a website structure and functionality prototype, not as final approved copy.
Return a structured JSON audit with:
1) site architecture and major page families,
2) navigation and CTA consistency,
3) forms found and their purpose,
4) visible structural/design inconsistencies that can be inferred from the scraped pages,
5) broken or obsolete internal links, especially any old /certifications/processus-certification/ URL,
6) pages that look duplicated, empty, draft-like or placeholder-heavy,
7) recurring components (references carousel, headers, footers, WhatsApp, forms),
8) a prototype-readiness verdict focused on structure/functionality before official content is supplied.
Do not judge whether marketing copy is factually final; content is intentionally provisional.
""".strip()

    graph = DepthSearchGraph(prompt=prompt, source=TARGET, config=graph_config)
    return graph.run()


if __name__ == "__main__":
    pages = crawl()
    summary = deterministic_summary(pages)

    (OUT / "moody_pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "moody_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    sg_result = None
    sg_error = None
    try:
        sg_result = run_scrapegraphai()
        (OUT / "moody_scrapegraphai.json").write_text(json.dumps(sg_result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        sg_error = f"{type(exc).__name__}: {exc}"
        (OUT / "moody_scrapegraphai_error.txt").write_text(sg_error, encoding="utf-8")
        print("ScrapeGraphAI semantic pass failed:", sg_error, flush=True)

    write_markdown(summary, pages, sg_result, sg_error)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
