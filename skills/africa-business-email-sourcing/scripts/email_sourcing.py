from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import logging
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urldefrag, urljoin, urlparse, unquote
from urllib.robotparser import RobotFileParser

import dns.exception
import dns.resolver
import requests
import tldextract
from bs4 import BeautifulSoup
from email_validator import EmailNotValidError, validate_email

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional at runtime
    PdfReader = None

LOGGER = logging.getLogger("africa_business_email_sourcing")

USER_AGENT = (
    "AfricaBusinessEmailSourcing/1.0 "
    "(public B2B contact research; evidence-first; no address generation)"
)
DEFAULT_TIMEOUT = 20
DEFAULT_MAX_PAGES = 60
DEFAULT_MAX_DEPTH = 3
DEFAULT_DELAY = 0.8

EMAIL_RE = re.compile(
    r"(?i)(?<![A-Z0-9._%+\-])"
    r"([A-Z0-9.!#$%&'*+/=?^_`{|}~\-]+@"
    r"[A-Z0-9](?:[A-Z0-9\-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9\-]{0,61}[A-Z0-9])?)+)"
    r"(?![A-Z0-9._%+\-])"
)

PRIORITY_PATH_TERMS = (
    "contact",
    "contacts",
    "communication",
    "communications",
    "communique",
    "communiques",
    "press",
    "presse",
    "media",
    "newsroom",
    "actualite",
    "actualites",
    "marketing",
    "partnership",
    "partnerships",
    "partenariat",
    "partenariats",
    "institutional",
    "institutionnel",
    "relations",
    "investor",
    "investisseurs",
    "governance",
    "gouvernance",
    "management",
    "direction",
    "team",
    "equipe",
    "about",
    "apropos",
    "legal",
    "mentions",
    "rapport",
    "report",
)

ROLE_PATTERNS = {
    "communication": (
        "communication",
        "communications",
        "comms",
        "corporatecommunication",
        "corporate.communications",
    ),
    "press_media": (
        "press",
        "presse",
        "media",
        "newsroom",
        "journalist",
        "journaliste",
    ),
    "institutional": (
        "institutional",
        "institutionnel",
        "relationsinstitutionnelles",
        "publicaffairs",
        "public.affairs",
        "affairespubliques",
    ),
    "marketing": (
        "marketing",
        "brand",
        "branding",
    ),
    "partnerships": (
        "partnership",
        "partnerships",
        "partenariat",
        "partenariats",
        "businessdevelopment",
        "business.development",
        "bizdev",
    ),
    "general": (
        "contact",
        "info",
        "hello",
        "office",
        "accueil",
        "secretariat",
        "mail",
    ),
}

ROLE_BASE_SCORE = {
    "communication": 100,
    "press_media": 95,
    "institutional": 95,
    "marketing": 90,
    "partnerships": 90,
    "direct_named": 85,
    "general": 70,
    "other": 50,
}


@dataclass(frozen=True)
class Target:
    company: str
    url: str
    priority: str = ""


@dataclass
class EmailEvidence:
    company: str
    priority: str
    website: str
    email: str
    role_label: str
    source_url: str
    source_type: str
    source_title: str
    context: str
    same_domain: bool
    syntax_valid: bool
    mx_status: str
    confidence: str
    score: int
    observed_at: str
    evidence_sha256: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_seed_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("Empty URL")
    if not urlparse(url).scheme:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unsupported target URL: {url}")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"


def registrable_domain(value: str) -> str:
    host = urlparse(value).hostname if "://" in value else value
    host = (host or "").strip(".").lower()
    ext = tldextract.extract(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return host


def same_site(url: str, seed_url: str) -> bool:
    return registrable_domain(url) == registrable_domain(seed_url)


def clean_url(base: str, href: str) -> Optional[str]:
    if not href:
        return None
    href = html.unescape(href.strip())
    if href.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    absolute = urljoin(base, href)
    absolute, _ = urldefrag(absolute)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    return parsed._replace(fragment="").geturl()


def role_label_for(email_address: str, source_url: str, context: str) -> str:
    local = email_address.split("@", 1)[0].lower()
    condensed = re.sub(r"[^a-z0-9.]+", "", local)
    context_low = f"{source_url} {context}".lower()

    for label, needles in ROLE_PATTERNS.items():
        if any(n in condensed or n in context_low for n in needles):
            return label

    if (
        "." in local
        and not any(
            local.startswith(prefix)
            for vals in ROLE_PATTERNS.values()
            for prefix in vals
        )
    ):
        return "direct_named"
    return "other"


def syntax_is_valid(email_address: str) -> bool:
    try:
        validate_email(email_address, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def mx_status_for(domain: str) -> str:
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=6.0)
        if list(answers):
            return "VALID_MX"
        return "NO_MX"
    except dns.resolver.NXDOMAIN:
        return "NXDOMAIN"
    except dns.resolver.NoAnswer:
        return "NO_MX"
    except (dns.exception.Timeout, dns.resolver.NoNameservers):
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def confidence_for(*, syntax_valid: bool, mx_status: str, same_domain_flag: bool) -> str:
    if not syntax_valid:
        return "REJECT"
    if same_domain_flag and mx_status == "VALID_MX":
        return "HIGH"
    if mx_status in {"VALID_MX", "UNKNOWN", "NOT_CHECKED"}:
        return "MEDIUM"
    return "LOW"


def score_for(
    role_label: str,
    *,
    same_domain_flag: bool,
    mx_status: str,
    source_type: str,
) -> int:
    score = ROLE_BASE_SCORE.get(role_label, 50)
    if same_domain_flag:
        score += 10
    if mx_status == "VALID_MX":
        score += 10
    if source_type == "mailto":
        score += 5
    if source_type == "pdf":
        score += 2
    return min(score, 125)


def context_snippet(text: str, email_address: str, radius: int = 120) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    idx = compact.lower().find(email_address.lower())
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(compact), idx + len(email_address) + radius)
    return compact[start:end]


def evidence_hash(email_address: str, source_url: str, context: str) -> str:
    raw = f"{email_address.lower()}|{source_url}|{context}".encode(
        "utf-8", errors="ignore"
    )
    return hashlib.sha256(raw).hexdigest()


class PublicEmailCrawler:
    def __init__(
        self,
        target: Target,
        *,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_depth: int = DEFAULT_MAX_DEPTH,
        delay: float = DEFAULT_DELAY,
        timeout: int = DEFAULT_TIMEOUT,
        respect_robots: bool = True,
        render_js: bool = False,
        crawl_pdfs: bool = True,
        verify_mx: bool = True,
    ) -> None:
        self.target = Target(
            company=target.company.strip(),
            url=normalize_seed_url(target.url),
            priority=target.priority.strip(),
        )
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = max(delay, 0.0)
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.render_js = render_js
        self.crawl_pdfs = crawl_pdfs
        self.verify_mx = verify_mx
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.9"}
        )
        self._robots: Optional[RobotFileParser] = None
        self._mx_cache: dict[str, str] = {}
        self._seen_evidence: set[tuple[str, str]] = set()

    def _load_robots(self) -> None:
        if not self.respect_robots:
            return
        parsed = urlparse(self.target.url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
            if response.ok:
                rp.parse(response.text.splitlines())
                self._robots = rp
        except requests.RequestException:
            self._robots = None

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots or self._robots is None:
            return True
        try:
            return self._robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def _get_static(self, url: str) -> Optional[requests.Response]:
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            LOGGER.debug("Fetch failed %s: %s", url, exc)
            return None

    def _render_html(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            LOGGER.warning("Playwright unavailable; JS rendering skipped for %s", url)
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self.timeout * 1000,
                )
                rendered = page.content()
                browser.close()
                return rendered
        except Exception as exc:
            LOGGER.debug("JS render failed %s: %s", url, exc)
            return None

    def _mx(self, email_address: str) -> str:
        domain = email_address.rsplit("@", 1)[1].lower()
        if not self.verify_mx:
            return "NOT_CHECKED"
        if domain not in self._mx_cache:
            self._mx_cache[domain] = mx_status_for(domain)
        return self._mx_cache[domain]

    def _build_evidence(
        self,
        email_address: str,
        *,
        source_url: str,
        source_type: str,
        source_title: str,
        text_for_context: str,
    ) -> Optional[EmailEvidence]:
        email_address = email_address.strip().strip(".,;:()[]{}<>\"'").lower()
        if not email_address or not syntax_is_valid(email_address):
            return None

        decoded_source = unquote(html.unescape(text_for_context or ""))
        if email_address not in decoded_source.lower():
            return None

        key = (email_address, source_url)
        if key in self._seen_evidence:
            return None
        self._seen_evidence.add(key)

        context = context_snippet(decoded_source, email_address)
        same_domain_flag = registrable_domain(
            email_address.split("@", 1)[1]
        ) == registrable_domain(self.target.url)
        mx_status = self._mx(email_address)
        role_label = role_label_for(email_address, source_url, context)
        confidence = confidence_for(
            syntax_valid=True,
            mx_status=mx_status,
            same_domain_flag=same_domain_flag,
        )
        score = score_for(
            role_label,
            same_domain_flag=same_domain_flag,
            mx_status=mx_status,
            source_type=source_type,
        )
        return EmailEvidence(
            company=self.target.company,
            priority=self.target.priority,
            website=self.target.url,
            email=email_address,
            role_label=role_label,
            source_url=source_url,
            source_type=source_type,
            source_title=source_title,
            context=context,
            same_domain=same_domain_flag,
            syntax_valid=True,
            mx_status=mx_status,
            confidence=confidence,
            score=score,
            observed_at=utc_now(),
            evidence_sha256=evidence_hash(email_address, source_url, context),
        )

    def _extract_from_html(
        self,
        source_url: str,
        raw_html: str,
    ) -> tuple[list[EmailEvidence], list[str]]:
        soup = BeautifulSoup(raw_html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        page_text = soup.get_text(" ", strip=True)

        found: list[EmailEvidence] = []

        for anchor in soup.select('a[href^="mailto:"]'):
            href = unquote(html.unescape(anchor.get("href", "")))
            payload = href.split(":", 1)[1].split("?", 1)[0]
            for candidate in EMAIL_RE.findall(payload):
                evidence = self._build_evidence(
                    candidate,
                    source_url=source_url,
                    source_type="mailto",
                    source_title=title,
                    text_for_context=f"{raw_html} {href} {page_text}",
                )
                if evidence:
                    found.append(evidence)

        decoded = unquote(html.unescape(raw_html))
        for candidate in EMAIL_RE.findall(decoded):
            evidence = self._build_evidence(
                candidate,
                source_url=source_url,
                source_type="html_text",
                source_title=title,
                text_for_context=decoded,
            )
            if evidence:
                found.append(evidence)

        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            absolute = clean_url(source_url, anchor.get("href", ""))
            if absolute and same_site(absolute, self.target.url):
                links.append(absolute)
        return found, links

    def _extract_from_pdf(
        self,
        source_url: str,
        content: bytes,
    ) -> list[EmailEvidence]:
        if PdfReader is None:
            return []
        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:50])
        except Exception as exc:
            LOGGER.debug("PDF parse failed %s: %s", source_url, exc)
            return []

        found: list[EmailEvidence] = []
        for candidate in EMAIL_RE.findall(text):
            evidence = self._build_evidence(
                candidate,
                source_url=source_url,
                source_type="pdf",
                source_title=Path(urlparse(source_url).path).name,
                text_for_context=text,
            )
            if evidence:
                found.append(evidence)
        return found

    def crawl(self) -> list[EmailEvidence]:
        self._load_robots()
        queue: deque[tuple[str, int]] = deque([(self.target.url, 0)])
        queued = {self.target.url}
        visited: set[str] = set()
        evidence: list[EmailEvidence] = []

        while queue and len(visited) < self.max_pages:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            if not self._allowed(url):
                LOGGER.info("robots.txt disallows %s", url)
                continue

            if self.delay:
                time.sleep(self.delay)

            response = self._get_static(url)
            if response is None:
                continue

            final_url = response.url
            ctype = (response.headers.get("content-type") or "").lower()

            if "application/pdf" in ctype or final_url.lower().endswith(".pdf"):
                if self.crawl_pdfs:
                    evidence.extend(self._extract_from_pdf(final_url, response.content))
                continue

            if "text/html" not in ctype and "<html" not in response.text[:500].lower():
                continue

            raw_html = response.text
            if self.render_js:
                rendered = self._render_html(final_url)
                if rendered:
                    raw_html = rendered

            page_evidence, links = self._extract_from_html(final_url, raw_html)
            evidence.extend(page_evidence)

            if depth >= self.max_depth:
                continue

            def priority_key(link: str) -> tuple[int, int]:
                low = link.lower()
                priority_hit = any(term in low for term in PRIORITY_PATH_TERMS)
                pdf_hit = low.endswith(".pdf")
                return (0 if priority_hit else 1, 0 if pdf_hit else 1)

            for link in sorted(set(links), key=priority_key):
                if link not in queued and link not in visited:
                    queued.add(link)
                    queue.append((link, depth + 1))

        best: dict[str, EmailEvidence] = {}
        for item in evidence:
            current = best.get(item.email)
            if current is None or item.score > current.score:
                best[item.email] = item

        return sorted(best.values(), key=lambda x: (-x.score, x.email))


def load_targets(path: Path) -> list[Target]:
    targets: list[Target] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"company", "url"}
        if not reader.fieldnames or not required.issubset(
            {h.strip() for h in reader.fieldnames}
        ):
            raise ValueError(
                "Targets CSV must contain columns: company,url (optional: priority)"
            )
        for row in reader:
            company = (row.get("company") or "").strip()
            url = (row.get("url") or "").strip()
            priority = (row.get("priority") or "").strip()
            if company and url:
                targets.append(Target(company=company, url=url, priority=priority))
    return targets


def write_csv(items: Iterable[EmailEvidence], path: Path) -> None:
    rows = [asdict(x) for x in items]
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(EmailEvidence.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(items: Iterable[EmailEvidence], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(x) for x in items], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evidence-first public B2B email sourcing. "
            "Never generates email patterns; every accepted address must be observed "
            "in a retrieved source."
        )
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--targets", type=Path, help="CSV with company,url,priority")
    target.add_argument("--url", help="Single company website URL")
    parser.add_argument("--company", default="", help="Company name for --url mode")
    parser.add_argument("--priority", default="", help="A/B/C for --url mode")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("email_sourcing_results.csv"),
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--render-js", action="store_true")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--no-mx", action="store_true")
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument(
        "--min-confidence",
        choices=["LOW", "MEDIUM", "HIGH"],
        default="MEDIUM",
        help="Filter final output. Default MEDIUM.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


CONFIDENCE_ORDER = {"REJECT": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.targets:
        targets = load_targets(args.targets)
    else:
        company = args.company.strip() or registrable_domain(args.url)
        targets = [Target(company=company, url=args.url, priority=args.priority)]

    if not targets:
        raise SystemExit("No valid targets")

    all_items: list[EmailEvidence] = []

    def run_target(target: Target) -> list[EmailEvidence]:
        LOGGER.info("Crawling %s (%s)", target.company, target.url)
        crawler = PublicEmailCrawler(
            target,
            max_pages=max(1, args.max_pages),
            max_depth=max(0, args.max_depth),
            delay=max(0.0, args.delay),
            timeout=max(5, args.timeout),
            respect_robots=not args.ignore_robots,
            render_js=args.render_js,
            crawl_pdfs=not args.no_pdf,
            verify_mx=not args.no_mx,
        )
        return crawler.crawl()

    max_workers = max(1, min(args.workers, len(targets)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_target = {executor.submit(run_target, t): t for t in targets}
        for future in as_completed(future_to_target):
            target = future_to_target[future]
            try:
                items = future.result()
                all_items.extend(items)
                LOGGER.info("%s: %d observed email(s)", target.company, len(items))
            except Exception as exc:
                LOGGER.error("%s failed: %s", target.company, exc)

    threshold = CONFIDENCE_ORDER[args.min_confidence]
    filtered = [
        item
        for item in all_items
        if CONFIDENCE_ORDER.get(item.confidence, 0) >= threshold
    ]
    filtered.sort(
        key=lambda x: (x.priority or "Z", -x.score, x.company.lower(), x.email)
    )

    write_csv(filtered, args.out)
    if args.json_out:
        write_json(filtered, args.json_out)

    LOGGER.info("Wrote %d verified/evidenced rows to %s", len(filtered), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
