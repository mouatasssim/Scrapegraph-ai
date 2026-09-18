# Moody Instagram public audit

This example audits the public Instagram profile:

https://www.instagram.com/moodyinternationalcertif/

It uses this repository's ScrapeGraphAI package and Playwright through a manually triggered GitHub Actions workflow.

## What it extracts

- public profile information
- follower/following/post counts when visible
- visible recent post/reel URLs
- visible publication date
- visible likes and comments
- visible caption
- a simple public engagement rate: (likes + comments) / followers

## Important limitation

Public scraping cannot provide the full Instagram performance picture. Metrics such as reach, impressions, saves, shares, reel watch time, follows generated, profile visits and DMs require Instagram Insights / the Meta Graph API for the account owner.

The script does not bypass login, access private data, or automate credentials.

## Setup

In the repository settings, add this GitHub Actions secret:

- `OPENAI_API_KEY`

Then run the workflow:

**Actions -> Moody Instagram Audit -> Run workflow**

Inputs:

- profile URL
- maximum visible posts to audit

## Output

The workflow uploads an artifact named `moody-instagram-audit` containing:

- `moody_instagram_audit.json`
- `moody_instagram_audit.md`

## Local execution

```bash
uv sync --frozen
uv run playwright install chromium
export OPENAI_API_KEY="..."
uv run python examples/instagram_audit/moody_instagram_audit.py
```
