"""
Public LinkedIn comment lead extractor for recruitment outreach.

Purpose:
- Extract visible comments from one public LinkedIn post.
- For each visible commenter profile URL, extract only public professional information
  that is visible without bypassing login or access controls.
- Produce JSON, CSV and Markdown files for manual recruitment review.

Important:
- No login bypass.
- No credential automation.
- No guessing/inference of email addresses or phone numbers.
- No extraction of sensitive traits.
- No automated hiring decision or candidate ranking.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scrapegraphai.graphs import SmartScraperGraph

POST_URL = os.getenv(
    "LINKEDIN_POST_URL",
    "https://lnkd.in/p/eE6MmmW7",
)
COMMENT_LIMIT = int(os.getenv("LINKEDIN_COMMENT_LIMIT", "50"))
OUTPUT_DIR = Path(os.getenv("LINKEDIN_OUTPUT_DIR", "linkedin_recruitment_output"))
MODEL = os.getenv("SCRAPEGRAPH_MODEL", "openai/gpt-4o-mini")


def graph_config() -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it as a GitHub Actions secret."
        )

    return {
        "llm": {
            "api_key": api_key,
            "model": MODEL,
        },
        "verbose": False,
        "headless": True,
    }


def run_graph(prompt: str, source: str) -> Any:
    graph = SmartScraperGraph(
        prompt=prompt,
        source=source,
        config=graph_config(),
    )
    return graph.run()


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def normalize_linkedin_url(value: Any) -> str:
    url = as_text(value)
    if not url:
        return ""
    if url.startswith("/"):
        url = "https://www.linkedin.com" + url
    url = url.split("?")[0].rstrip("/")
    if "linkedin.com/in/" in url or "linkedin.com/company/" in url:
        return url
    return ""


def pick(data: Any, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None
    lower = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def safe_public_email(value: Any) -> str:
    text = as_text(value)
    if not text:
        return ""
    match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
    return match.group(0) if match else ""


def safe_public_phone(value: Any) -> str:
    text = as_text(value)
    if not text:
        return ""
    match = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
    return match.group(0).strip() if match else ""


def normalize_comments(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, dict):
        return []

    candidates = (
        pick(raw, "comments", "visible_comments", "commenters", "replies")
        or []
    )
    if not isinstance(candidates, list):
        return []

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in candidates:
        if not isinstance(item, dict):
            continue

        name = as_text(pick(item, "name", "author", "commenter_name", "full_name"))
        comment = as_text(pick(item, "comment", "text", "content"))
        profile_url = normalize_linkedin_url(
            pick(item, "profile_url", "linkedin_url", "author_url", "url")
        )

        if not name and not comment:
            continue

        key = (name.lower(), comment.lower())
        if key in seen:
            continue
        seen.add(key)

        out.append(
            {
                "name": name,
                "comment": comment,
                "profile_url": profile_url,
            }
        )

        if len(out) >= COMMENT_LIMIT:
            break

    return out


def extract_public_profile(profile_url: str) -> dict[str, str]:
    if not profile_url:
        return {
            "headline": "",
            "current_role": "",
            "company": "",
            "location": "",
            "website": "",
            "public_professional_email": "",
            "public_professional_phone": "",
        }

    prompt = """
Extract ONLY public professional information visibly available on this LinkedIn
profile page without bypassing login or access controls.

Return valid JSON with exactly these fields:
- headline
- current_role
- company
- location
- website
- public_professional_email
- public_professional_phone

Rules:
- Use only information explicitly visible on the public page.
- Do not guess or infer email addresses.
- Do not guess or infer phone numbers.
- Do not infer age, gender, ethnicity, religion, health, political views,
  marital status, family status, or any other sensitive trait.
- If a field is not publicly visible, return an empty string.
"""
    try:
        result = run_graph(prompt, profile_url)
    except Exception as exc:  # keep the whole job running if one profile fails
        return {
            "headline": "",
            "current_role": "",
            "company": "",
            "location": "",
            "website": "",
            "public_professional_email": "",
            "public_professional_phone": "",
            "profile_error": str(exc),
        }

    data = result if isinstance(result, dict) else {}

    return {
        "headline": as_text(pick(data, "headline", "title")),
        "current_role": as_text(pick(data, "current_role", "role", "job_title")),
        "company": as_text(pick(data, "company", "current_company", "employer")),
        "location": as_text(pick(data, "location", "city")),
        "website": as_text(pick(data, "website", "site")),
        "public_professional_email": safe_public_email(
            pick(data, "public_professional_email", "email")
        ),
        "public_professional_phone": safe_public_phone(
            pick(data, "public_professional_phone", "phone")
        ),
    }


def hse_evidence(row: dict[str, str]) -> str:
    """
    Return objective work-related HSE keywords found in public professional text.
    This is not a hiring score or recommendation.
    """
    haystack = " ".join(
        [
            row.get("comment", ""),
            row.get("headline", ""),
            row.get("current_role", ""),
            row.get("company", ""),
        ]
    ).lower()

    terms = [
        "hse",
        "qhse",
        "qse",
        "hygiène",
        "hygiene",
        "sécurité",
        "securite",
        "safety",
        "environnement",
        "environment",
        "chantier",
        "construction",
        "prévention",
        "prevention",
        "iso 45001",
    ]

    found = []
    for term in terms:
        if term in haystack and term not in found:
            found.append(term)
    return ", ".join(found)


def build_rows(comments: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for idx, comment in enumerate(comments, start=1):
        profile = extract_public_profile(comment.get("profile_url", ""))

        row = {
            "index": str(idx),
            "name": comment.get("name", ""),
            "comment": comment.get("comment", ""),
            "linkedin_profile": comment.get("profile_url", ""),
            "headline": profile.get("headline", ""),
            "current_role": profile.get("current_role", ""),
            "company": profile.get("company", ""),
            "location": profile.get("location", ""),
            "website": profile.get("website", ""),
            "public_professional_email": profile.get("public_professional_email", ""),
            "public_professional_phone": profile.get("public_professional_phone", ""),
        }
        row["hse_evidence"] = hse_evidence(row)
        row["source_post"] = POST_URL
        rows.append(row)

    return rows


def write_csv(rows: list[dict[str, str]]) -> None:
    path = OUTPUT_DIR / "linkedin_recruitment_leads.csv"
    fieldnames = [
        "index",
        "name",
        "comment",
        "linkedin_profile",
        "headline",
        "current_role",
        "company",
        "location",
        "website",
        "public_professional_email",
        "public_professional_phone",
        "hse_evidence",
        "source_post",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(post_data: Any, rows: list[dict[str, str]]) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_post": POST_URL,
        "comment_limit": COMMENT_LIMIT,
        "visible_comments_extracted": len(rows),
        "post_raw": post_data,
        "leads": rows,
        "method_note": (
            "Only public professional information visible without bypassing "
            "LinkedIn access controls is included. Missing contacts are left blank."
        ),
    }

    (OUTPUT_DIR / "linkedin_recruitment_leads.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_markdown(rows: list[dict[str, str]]) -> None:
    lines = [
        "# LinkedIn recruitment comment leads",
        "",
        f"- Source post: {POST_URL}",
        f"- Visible comments extracted: {len(rows)}",
        "",
        "Only public professional data is included. Blank contact fields mean the "
        "information was not publicly visible and was not guessed.",
        "",
        "| # | Name | Role | Company | Location | HSE evidence | LinkedIn |",
        "|---:|---|---|---|---|---|---|",
    ]

    for row in rows:
        lines.append(
            "| {i} | {name} | {role} | {company} | {location} | {evidence} | {url} |".format(
                i=row["index"],
                name=row["name"].replace("|", "/"),
                role=row["current_role"].replace("|", "/"),
                company=row["company"].replace("|", "/"),
                location=row["location"].replace("|", "/"),
                evidence=row["hse_evidence"].replace("|", "/"),
                url=row["linkedin_profile"],
            )
        )

    (OUTPUT_DIR / "linkedin_recruitment_leads.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    post_prompt = f"""
Extract up to {COMMENT_LIMIT} comments visibly available on this public LinkedIn
post.

Return valid JSON with:
- post_author
- post_text
- published_date
- reaction_count (if visible)
- comment_count (if visible)
- repost_count (if visible)
- comments: a list of objects, each containing:
  - name
  - comment
  - profile_url

Rules:
- Extract only visible public comments.
- Keep comment text as written.
- Return the public LinkedIn profile URL when it is visibly linked.
- Do not bypass login, authentication, paywalls, or access restrictions.
- Do not infer private contact information.
"""

    post_data = run_graph(post_prompt, POST_URL)
    comments = normalize_comments(post_data)
    rows = build_rows(comments)

    write_csv(rows)
    write_json(post_data, rows)
    write_markdown(rows)

    print(
        json.dumps(
            {
                "source_post": POST_URL,
                "visible_comments_extracted": len(rows),
                "output_dir": str(OUTPUT_DIR),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
