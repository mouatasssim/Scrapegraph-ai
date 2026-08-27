---
name: africa-business-email-sourcing
description: Evidence-first B2B sourcing for AFRICA BUSINESS Maroc. Discover official company websites, crawl public pages and PDFs, extract only email addresses that are actually present in source content, validate syntax/domain/MX, rank communication/press/marketing/institutional contacts, and prepare CRM-ready evidence without guessing or generating email patterns.
version: 1.0
---

# AFRICA BUSINESS — Public Email Sourcing

## Mission

Build an operational email-first prospecting dataset for AFRICA BUSINESS / Afrique Europe Business Magazine in Morocco.

Primary objective:

`TARGET ACCOUNT -> OFFICIAL DOMAIN -> PUBLIC FIRST-PARTY SOURCES -> OBSERVED EMAIL -> VALIDATION -> EVIDENCE -> CRM/EMAILING`

This skill is designed for B2B commercial and institutional prospecting. It is not a generic people-data harvester.

## Non-negotiable truth rule

**Never create, infer, predict, permute, or guess an email address.**

Forbidden examples:

- deriving `firstname.lastname@company.com` from a person's name;
- testing common aliases that were never observed;
- using an LLM to invent an address;
- reconstructing a corporate email pattern from other employees;
- treating a masked address such as `m***@company.com` as a full address;
- copying an email from an untrusted aggregator without preserving the source.

An email may enter the final dataset only if the exact address is observed in retrieved public source material or returned verbatim by an explicitly authorized data provider.

## Allowed evidence

Preferred evidence order:

1. Official company website `mailto:` link.
2. Official company website visible text.
3. Official company PDF / press release / annual report / media kit.
4. Official public subsidiary or group website clearly linked to the target company.
5. Official public institutional directory or event page when it clearly identifies the organization.
6. Authorized enrichment provider output, only when the user has approved use of that provider and any credit/person-data access.

Third-party directories, scraped mirrors and people-search sites are never treated as stronger evidence than first-party sources.

## Privacy and access rules

- Use public professional contact information relevant to the user's B2B purpose.
- Do not collect unrelated personal data.
- Do not bypass authentication, paywalls, CAPTCHAs, access controls or anti-bot protections.
- Respect robots directives where applicable.
- Use conservative request rates.
- Prefer role mailboxes and business contact channels when equally useful.
- A direct professional email may be used when the organization has published it publicly.
- Do not scrape private LinkedIn data or attempt to bypass LinkedIn restrictions.
- Do not perform SMTP mailbox probing by default.

# Operating workflow

## Phase 1 — Target input

Accept one of:

- a company name + verified official website;
- a CSV with `company,url,priority`;
- an existing AFRICA BUSINESS CRM list;
- a bounded list supplied by the user.

If only a company name is available, resolve the official domain first using reliable public evidence. Do not guess the domain if identity is ambiguous.

## Phase 2 — First-party crawl

For each official website:

1. start from the supplied homepage;
2. read `robots.txt` when available;
3. crawl same-site HTML pages;
4. prioritize URLs containing:
   - contact / contacts;
   - communication;
   - presse / press / media / newsroom;
   - actualités / news;
   - relations institutionnelles / public affairs;
   - marketing / brand;
   - partenariat / partnership;
   - gouvernance / direction / management;
   - investisseurs / investor relations;
   - mentions légales;
   - reports / rapports;
5. follow public PDF links;
6. optionally render JavaScript pages with Playwright when static HTML is insufficient.

Default crawl discipline:

- maximum 60 pages per target;
- maximum depth 3;
- minimum delay 0.8 s/request/domain;
- up to 4 target domains in parallel;
- remain on the same registrable domain unless a clearly official related domain is explicitly accepted.

## Phase 3 — Deterministic extraction

Extract candidates from:

- `mailto:` anchors;
- decoded HTML text;
- JSON-LD / embedded metadata;
- public PDF text.

Use deterministic parsing first.

The LLM must **not** be the source of truth for an email string.

If ScrapeGraphAI semantic extraction is used, the prompt must require:

> Return only email addresses that are verbatim present in the supplied page content. For each address return the exact supporting text. If no address is present, return an empty list.

Then cross-check every LLM result against raw retrieved source text. Reject anything that cannot be matched verbatim.

## Phase 4 — Evidence gate

Every retained email must contain:

- organization;
- official website;
- exact email;
- source URL;
- source type;
- source title when available;
- local context snippet;
- discovery timestamp;
- evidence hash.

Hard gate:

`EMAIL IN SOURCE == TRUE`

If the exact address cannot be found in the retrieved source, discard it.

## Phase 5 — Technical validation

Validate without changing the address:

1. RFC/syntax validation;
2. domain extraction;
3. same-domain check against target website;
4. DNS/MX lookup;
5. deduplication.

Statuses:

- `VALID_MX` — domain publishes MX records;
- `NO_MX` — no MX observed;
- `NXDOMAIN` — domain does not resolve;
- `UNKNOWN` — DNS could not be conclusively checked;
- `NOT_CHECKED` — MX validation intentionally disabled.

Do not interpret `VALID_MX` as proof that a specific mailbox is currently active. It confirms mail infrastructure only.

SMTP RCPT probing is disabled by default because it is unreliable, often blocked, can create compliance/deliverability issues and is unnecessary for the core rule: observed first-party professional emails.

## Phase 6 — Commercial relevance ranking

Classify only from the observed address and source context.

Preferred AFRICA BUSINESS roles:

1. `communication`
2. `press_media`
3. `institutional`
4. `marketing`
5. `partnerships`
6. `direct_named`
7. `general`
8. `other`

Priority logic:

- communication / institutional: highest;
- press/media: very high for editorial + media approach;
- marketing / partnerships: very high for advertiser conversations;
- direct named professional mailbox: high only if publicly observed;
- generic contact/info: usable fallback;
- unrelated operational addresses: deprioritize.

Do not infer a person's job title solely from an email local part.

## Phase 7 — Confidence

Use:

### HIGH
- exact address observed;
- syntax valid;
- domain has MX;
- first-party source;
- same corporate domain or clearly official related domain.

### MEDIUM
- exact address observed;
- syntax valid;
- source is credible;
- MX is valid or inconclusive.

### LOW
- exact address observed but domain/source relationship is weak or mail infrastructure is questionable.

### REJECT
- syntax invalid;
- not observed verbatim;
- inferred/generated;
- masked/incomplete;
- source cannot be established.

Default export threshold: `MEDIUM`.

## Phase 8 — Zero-result recovery

If no useful email is found on the initial crawl, do not guess.

Perform these recovery lanes in order:

1. increase crawl coverage on the official domain;
2. render likely contact pages with Playwright;
3. search official PDFs and press releases;
4. use ScrapeGraphAI `SearchGraph` or public web search with queries such as:
   - `site:official-domain.tld contact email`
   - `site:official-domain.tld presse email`
   - `site:official-domain.tld communication`
   - `site:official-domain.tld filetype:pdf contact`
5. inspect official subsidiary/group sites if the relationship is explicit;
6. use an authorized enrichment provider only with user approval.

Still no observed email = output `NO_PUBLIC_EMAIL_FOUND`.

Never fill the gap with a predicted address.

# AFRICA BUSINESS output contract

## Minimal emailing dataset

For execution, the minimum useful fields are:

`PRIORITY | ORGANISATION | WEBSITE | EMAIL | ROLE_LABEL | SOURCE_URL | MX_STATUS | CONFIDENCE | OBSERVED_AT`

## Evidence-rich dataset

The CLI additionally keeps:

- source type;
- source title;
- context snippet;
- same-domain flag;
- syntax status;
- ranking score;
- evidence SHA-256.

## CRM mapping

When preparing Google Sheets CRM updates:

- `Priorité` <- target priority;
- `Organisation` <- target company;
- `Site web` <- official website;
- `Email pro` <- observed email;
- `Source du contact` <- source URL;
- `Notes compliance` <- `Public professional email observed on source; confidence=...; MX=...`;
- `Statut` <- `À contacter` only when user has approved the CRM write.

If multiple useful emails exist for one account, do not overwrite silently. Preserve each evidence row first, then select the primary outreach mailbox according to role relevance.

# CLI supplied with this skill

Script:

`skills/africa-business-email-sourcing/scripts/email_sourcing.py`

Install additional dependencies:

```bash
pip install -r skills/africa-business-email-sourcing/requirements.txt
playwright install chromium
```

Single target:

```bash
python skills/africa-business-email-sourcing/scripts/email_sourcing.py \
  --company "Example Company" \
  --url "https://www.example.com" \
  --priority A \
  --out outputs/example_emails.csv
```

Batch:

```bash
python skills/africa-business-email-sourcing/scripts/email_sourcing.py \
  --targets skills/africa-business-email-sourcing/targets.example.csv \
  --out outputs/africa_business_emails.csv \
  --json-out outputs/africa_business_emails.json \
  --workers 4
```

For JavaScript-heavy sites:

```bash
python skills/africa-business-email-sourcing/scripts/email_sourcing.py \
  --targets targets.csv \
  --render-js \
  --out outputs/emails.csv
```

## Required final report after a sourcing run

Always report:

- targets attempted;
- targets with >=1 observed email;
- number of HIGH / MEDIUM results;
- targets with no public email;
- emails rejected and why;
- any access/robots limitation;
- exact output path;
- recommended first emailing wave.

# ScrapeGraphAI role in the stack

ScrapeGraphAI is the semantic and browser-aware layer, not the truth generator.

Use the repo's capabilities for:

- JavaScript rendering through Playwright;
- multi-page processing;
- SearchGraph-based public discovery;
- semantic page classification;
- context extraction.

For email strings themselves, deterministic extraction + evidence matching always wins.

# External repo policy

Additional open-source components may be evaluated when they materially improve:

- crawl breadth;
- PDF extraction;
- DNS validation;
- reproducibility;
- containerization.

Do not add another crawler merely because it exists. Prefer the smallest dependable stack for production.

Current V1 deliberately does not require Crawl4AI because this ScrapeGraphAI fork already includes BeautifulSoup, Playwright and multi-page/search pipelines. Crawl4AI can be introduced later for high-volume crawl orchestration if real throughput proves it necessary.

# Commercial handoff

This skill owns sourcing and evidence preparation, not sending.

After the email list is ready:

1. rank accounts by AFRICA BUSINESS Tier A/B/C;
2. select one primary email route per account;
3. create personalized messages from verified account facts;
4. prepare Gmail drafts or campaign import;
5. send only after the user's explicit authorization.

Never turn missing data into invented data merely to increase list size.

# Success criteria

A sourcing batch is successful when:

- every retained email is source-backed;
- no guessed email is present;
- duplicate addresses are removed;
- technical status is visible;
- high-value communication/marketing/institutional addresses are ranked first;
- the output can be audited later by opening the stored source URL;
- the dataset is immediately usable for a controlled B2B emailing wave.
