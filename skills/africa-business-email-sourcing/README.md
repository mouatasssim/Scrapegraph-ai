# AFRICA BUSINESS Email Sourcing

Evidence-first public B2B email sourcing layer built on the ScrapeGraphAI fork.

## Core rule

The pipeline **never generates email addresses**. An address is accepted only when the exact string is observed in a retrieved public source. Every retained row keeps its source URL and evidence metadata.

## What it does

- crawls official company websites;
- prioritizes contact / communication / press / institutional / marketing / partnership pages;
- extracts emails from `mailto:`, HTML and public PDFs;
- optionally renders JavaScript pages with Playwright;
- validates syntax and DNS/MX;
- ranks commercially useful mailboxes for AFRICA BUSINESS;
- exports CSV and JSON.

## Install

From the repository root:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -e .
pip install -r skills/africa-business-email-sourcing/requirements.txt
playwright install chromium
```

## Batch input

Create a CSV:

```csv
company,url,priority
Company A,https://www.companya.example,A
Company B,https://www.companyb.example,B
```

Run:

```bash
python skills/africa-business-email-sourcing/scripts/email_sourcing.py ^
  --targets skills/africa-business-email-sourcing/targets.example.csv ^
  --out outputs/africa_business_emails.csv ^
  --json-out outputs/africa_business_emails.json ^
  --workers 4
```

On macOS/Linux replace `^` with `\`.

## Useful options

- `--render-js`: render pages with Playwright.
- `--max-pages 100`: expand crawl coverage.
- `--max-depth 4`: expand link depth.
- `--min-confidence HIGH`: keep only strongest results.
- `--no-pdf`: disable PDF parsing.
- `--no-mx`: skip DNS/MX checks.
- `--ignore-robots`: available only for an explicitly authorized situation; default behavior respects robots when retrievable.

## Output

The CSV contains:

- company;
- priority;
- website;
- email;
- role label;
- source URL;
- source type/title/context;
- same-domain flag;
- syntax validation;
- MX status;
- confidence;
- ranking score;
- observation timestamp;
- evidence hash.

## Confidence does not mean mailbox guarantee

`HIGH` means the address was observed, is syntactically valid, and its domain has mail infrastructure. It does not prove that an individual mailbox is currently accepting mail. The stack intentionally avoids SMTP probing by default.

## Recommended operating sequence

1. Put the Tier A/B target domains in the targets CSV.
2. Run without JS rendering first.
3. Re-run zero-result targets with `--render-js --max-pages 100`.
4. Review HIGH/MEDIUM results.
5. Write only verified results into the AFRICA BUSINESS CRM.
6. Prepare personalized outreach.
7. Send only after explicit authorization.

See `SKILL.md` for the full operating policy.
