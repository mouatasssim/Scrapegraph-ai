"""
Public Instagram audit for Moody International Certification.

Uses ScrapeGraphAI against the public Instagram profile and visible public posts.
No login bypass, private data access, or credential automation is attempted.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scrapegraphai.graphs import SmartScraperGraph

PROFILE_URL = os.getenv(
    "INSTAGRAM_PROFILE_URL",
    "https://www.instagram.com/moodyinternationalcertif/",
)
POST_LIMIT = int(os.getenv("INSTAGRAM_POST_LIMIT", "12"))
OUTPUT_DIR = Path(os.getenv("AUDIT_OUTPUT_DIR", "audit_output"))
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


def extract_urls(value: Any) -> list[str]:
    raw = json.dumps(value, ensure_ascii=False)
    urls = re.findall(
        r"https://www\.instagram\.com/[^\"'\\\s]+/(?:p|reel)/[^\"'\\\s]+/?",
        raw,
    )

    # Fallback for the canonical Instagram URL order: /username/p/SHORTCODE/
    if not urls:
        urls = re.findall(
            r"https://www\.instagram\.com/[^\"'\\\s]+/(?:p|reel)/[^\"'\\\s]+/?",
            raw,
        )

    deduped: list[str] = []
    for url in urls:
        clean = url.rstrip(".,);]")
        if clean not in deduped:
            deduped.append(clean)
    return deduped[:POST_LIMIT]


def pick(data: Any, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None
    lower = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip().lower().replace(",", "").replace(" ", "")
    match = re.search(r"(\d+(?:\.\d+)?)([km]?)", text)
    if not match:
        return None

    number = float(match.group(1))
    suffix = match.group(2)
    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000
    return int(number)


def normalize_post(url: str, result: Any) -> dict[str, Any]:
    item = result if isinstance(result, dict) else {"raw": result}
    return {
        "url": url,
        "type": pick(item, "type", "post_type", "format"),
        "date": pick(item, "date", "published_date", "publication_date"),
        "likes": as_int(pick(item, "likes", "like_count")),
        "comments": as_int(pick(item, "comments", "comment_count")),
        "caption": pick(item, "caption", "text", "description"),
        "raw": item,
    }


def build_report(profile: Any, posts: list[dict[str, Any]]) -> dict[str, Any]:
    profile_dict = profile if isinstance(profile, dict) else {"raw": profile}

    followers = as_int(
        pick(profile_dict, "followers", "followers_count", "follower_count")
    )
    following = as_int(
        pick(profile_dict, "following", "following_count")
    )
    posts_count = as_int(
        pick(profile_dict, "posts", "posts_count", "media_count")
    )

    scored_posts = []
    for post in posts:
        likes = post.get("likes")
        comments = post.get("comments")
        interactions = None
        engagement_rate = None

        if likes is not None or comments is not None:
            interactions = (likes or 0) + (comments or 0)
            if followers:
                engagement_rate = round((interactions / followers) * 100, 2)

        scored = dict(post)
        scored["interactions"] = interactions
        scored["engagement_rate_by_followers_pct"] = engagement_rate
        scored_posts.append(scored)

    known_rates = [
        p["engagement_rate_by_followers_pct"]
        for p in scored_posts
        if p["engagement_rate_by_followers_pct"] is not None
    ]

    known_comments = [
        p["comments"] for p in scored_posts if p["comments"] is not None
    ]

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "profile_url": PROFILE_URL,
        "profile": {
            "username": pick(profile_dict, "username", "handle"),
            "name": pick(profile_dict, "name", "display_name"),
            "bio": pick(profile_dict, "bio", "biography"),
            "website": pick(profile_dict, "website", "link"),
            "followers": followers,
            "following": following,
            "posts_count": posts_count,
            "raw": profile_dict,
        },
        "posts": scored_posts,
        "summary": {
            "visible_posts_audited": len(scored_posts),
            "average_public_engagement_rate_by_followers_pct": (
                round(sum(known_rates) / len(known_rates), 2) if known_rates else None
            ),
            "posts_with_zero_comments": (
                sum(1 for c in known_comments if c == 0) if known_comments else None
            ),
            "note": (
                "Public engagement rate uses visible likes + comments divided by "
                "followers. It does not include reach, saves, shares, watch time, "
                "profile visits or DMs. Use Instagram Insights/Meta Graph API for those."
            ),
        },
    }


def to_markdown(report: dict[str, Any]) -> str:
    profile = report["profile"]
    summary = report["summary"]

    lines = [
        "# Moody International Certification - Instagram public audit",
        "",
        f"- Profile: {report['profile_url']}",
        f"- Followers: {profile.get('followers')}",
        f"- Following: {profile.get('following')}",
        f"- Public posts count: {profile.get('posts_count')}",
        f"- Visible posts audited: {summary.get('visible_posts_audited')}",
        (
            "- Average public engagement rate by followers: "
            f"{summary.get('average_public_engagement_rate_by_followers_pct')}%"
        ),
        "",
        "## Visible posts",
        "",
        "| Date | Type | Likes | Comments | ER/followers | URL |",
        "|---|---:|---:|---:|---:|---|",
    ]

    for post in report["posts"]:
        lines.append(
            "| {date} | {type_} | {likes} | {comments} | {er}% | {url} |".format(
                date=post.get("date") or "",
                type_=post.get("type") or "",
                likes=post.get("likes") if post.get("likes") is not None else "",
                comments=(
                    post.get("comments") if post.get("comments") is not None else ""
                ),
                er=(
                    post.get("engagement_rate_by_followers_pct")
                    if post.get("engagement_rate_by_followers_pct") is not None
                    else ""
                ),
                url=post.get("url") or "",
            )
        )

    lines += [
        "",
        "## Interpretation limits",
        "",
        summary["note"],
        "",
        "For a full engagement diagnosis, add Instagram Insights metrics: reach, "
        "impressions, saves, shares, reel watch time, follows from content and profile visits.",
    ]
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    profile_prompt = """
Extract ONLY public information visible on this Instagram profile.
Return valid JSON with:
- username
- name
- bio
- website
- followers (integer if visible)
- following (integer if visible)
- posts_count (integer if visible)
- recent_post_urls: up to 12 full public URLs for recent posts/reels visible on the page

Do not invent values. Use null when unavailable.
"""

    profile_result = run_graph(profile_prompt, PROFILE_URL)
    post_urls = extract_urls(profile_result)

    posts: list[dict[str, Any]] = []
    post_prompt = """
Extract ONLY public metadata from this Instagram post/reel.
Return valid JSON with:
- type: post, reel, or carousel if determinable
- date: publication date if visible
- likes: integer if visible
- comments: integer if visible
- caption: full visible caption text

Do not infer private metrics. Do not invent values. Use null when unavailable.
"""

    for url in post_urls:
        try:
            result = run_graph(post_prompt, url)
            posts.append(normalize_post(url, result))
        except Exception as exc:  # keep the audit running if one post is blocked
            posts.append(
                {
                    "url": url,
                    "type": None,
                    "date": None,
                    "likes": None,
                    "comments": None,
                    "caption": None,
                    "raw": {"error": str(exc)},
                }
            )

    report = build_report(profile_result, posts)

    json_path = OUTPUT_DIR / "moody_instagram_audit.json"
    md_path = OUTPUT_DIR / "moody_instagram_audit.md"

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(to_markdown(report), encoding="utf-8")

    print(to_markdown(report))
    print(f"\nSaved: {json_path}")
    print(f"Saved: {md_path}")


if __name__ == "__main__":
    main()
