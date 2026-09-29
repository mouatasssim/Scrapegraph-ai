# LinkedIn recruitment comment leads

This isolated example was added on the branch:

`linkedin-recruitment-comments`

It does **not** modify the main ScrapeGraphAI package or the existing Instagram audit.

## Goal

Given one public LinkedIn post URL, extract visible public comments and build a manual recruitment prospecting file from public professional information.

Default post:

`https://lnkd.in/p/eE6MmmW7`

## Output

The script creates:

- `linkedin_recruitment_leads.csv`
- `linkedin_recruitment_leads.json`
- `linkedin_recruitment_leads.md`

Fields include:

- commenter name
- visible comment
- public LinkedIn profile URL
- headline
- current role
- company
- location
- public professional website
- public professional email, only when explicitly visible
- public professional phone, only when explicitly visible
- objective HSE/QHSE-related keywords found in the public professional text
- source post URL

## Guardrails

The extractor does not:

- bypass LinkedIn login or access controls
- automate credentials
- guess email addresses or phone numbers
- infer sensitive personal traits
- rank candidates or make hiring decisions

Missing information is left blank.

## Required secret

The script uses the repository's ScrapeGraphAI package and requires:

- `OPENAI_API_KEY`

## Local run from this branch

```bash
git checkout linkedin-recruitment-comments
uv sync --frozen
uv run playwright install chromium

export OPENAI_API_KEY="..."
export LINKEDIN_POST_URL="https://lnkd.in/p/eE6MmmW7"
export LINKEDIN_COMMENT_LIMIT="50"

uv run python examples/linkedin_recruitment_comments/linkedin_comment_leads.py
```

## GitHub Actions note

The branch contains:

`.github/workflows/linkedin-recruitment-comments.yml`

GitHub only exposes a new `workflow_dispatch` workflow in the Actions UI after the workflow exists on the repository's default branch. Keeping this work isolated on a feature branch therefore means the script can be reviewed and tested locally without changing `main`.
