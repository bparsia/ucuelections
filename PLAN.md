# UCU Elections — Scraping & Data Extraction Plan

## Overview

Build a pipeline that fetches UCU UK election result pages, extracts structured candidate/result data from both inline HTML and PDF scrutineer reports, and stores it as clean JSON/CSV for downstream use in a Streamlit explorer.

---

## Data Sources

### Known election pages

| Year    | URL |
|---------|-----|
| 2025-26 | https://www.ucu.org.uk/article/14191/UCU-UK-elections-2025-26 |
| 2024-25 | https://www.ucu.org.uk/article/13734/UCU-UK-elections-2024-25 |

More years can be added manually or discovered by scraping the "Previous elections" index page at `https://www.ucu.org.uk/previouselections` (or similar — to be confirmed).

### Per-page assets

Each article page contains:
1. **Inline HTML results** — candidate names, institutions, contested/uncontested status
2. **PDF scrutineer reports** — typically three per year (National, HE seats, FE seats), containing vote counts and full candidate lists
>>> BJP These are summaries and do not contain all the info we want. For example, they do not include the other candidates! In addition to inline stuff like uncontested or no candidate.
3. **Supporting documents** — nomination forms, rules, guidance (not needed for results)

---

## Data Model

Each extracted record represents a single candidate in a single election contest:

```python
{
    "year":           "2024-25",          # election cycle
    "election_type":  "NEC Geographic",   # Officer | NEC Geographic | NEC Constituency | Trustee | Scotland
    "position":       "North West HE",    # human-readable seat label
    "sector":         "HE",               # HE | FE | Both | null
    "region":         "North West",       # geographic region or null
    "constituency":   null,               # e.g. "Disabled Members", "LGBT+" or null
    "seats_available": 2,                 # number of seats being filled
    "candidate_name": "Rhiannon Lockley", # cleaned full name
    "pronouns":       "she/her",          # if listed, else null
    "institution":    "Birmingham City University",
    "outcome":        "Elected",          # Elected | Not Elected | Uncontested
    "votes":          142,                # from scrutineer PDF, else null
    "contested":      True,               # False if seat was uncontested
    "source":         "html",             # html | pdf
    "source_url":     "https://..."       # originating page or PDF URL
}
```
>>> BJP many seats do not have a region. All equality seats (e.g., disabled members' rep)
---

## Pipeline Stages

### Stage 1 — Page discovery (`discover.py` or top of `scraper.py`)

- Start from a hardcoded list of known article URLs
- Optionally crawl the "Previous elections" index to find additional years
- Output: list of `{year, url}` dicts

### Stage 2 — HTML scraping (`scraper.py`)

For each election page:

1. Fetch with `requests` + `User-Agent` header
2. Parse with `BeautifulSoup` (lxml parser)
3. Locate the main article body (`<article>` or `.article-content` — to be confirmed on live page)
4. Walk headings (`<h2>`, `<h3>`) and the content beneath them to identify:
   - Election type / position group (from heading text)
   - Candidate entries (likely `<li>` or `<p>` elements)
5. For each candidate entry, extract:
   - Name (strip title, pronouns if present)
   - Institution (after ` - ` or inside parens)
   - Uncontested marker (text like "unopposed", "uncontested", italics)
6. Collect all `<a href="...pdf">` links with their anchor text to identify scrutineer reports vs supporting docs
>>> BJP need results, not scrutineer docs.

**Known parsing challenges:**
- Year-over-year HTML structure differs (2025-26 appears summary-only; 2024-25 is comprehensive)
- Pronouns embedded in names: `Rhiannon Lockley (she/her) - Birmingham City University`
- Nested institutions: `Luminate Education Group (Leeds City College)`
- Some positions have seat counts and demographic requirements in the heading text

### Stage 3 — PDF extraction (`pdf_extractor.py`)

For each scrutineer report PDF:
>>> BJP need to rework for results.
1. Download to a local cache directory (`data/pdfs/`)
2. Extract text page-by-page with `pdfplumber`
3. Parse vote tables — scrutineer reports typically list:
   - Contest name / seat
   - Candidate name
   - First preference votes (or single-round totals)
   - Elected / not elected status
4. Attempt to match PDF records back to HTML records by candidate name + position

**Known challenges:**
- PDFs are image-based or have variable table layouts (need to verify)
>>> BJP they are text based but have a lot of variable complex table and list structures.

- Vote counts may use STV (Single Transferable Vote) — multiple rounds, not just totals
- Candidate names in PDFs may differ slightly from inline HTML (titles, middle initials)
>>> I really only care about what's in the reports, wrt names. The inline HTML is only needed for uncontested and no-nomination seats.

### Stage 4 — Merging & normalisation (`normalise.py`)

1. Merge HTML and PDF records on `(year, position, candidate_name)`
2. Normalise position names across years (e.g., "North West HE" = "NEC Geographic - North West HE")
3. Clean candidate names: strip extra whitespace, standardise title handling
4. Classify `election_type` from position text using a lookup/regex map
5. Flag records where PDF data could not be matched to an HTML entry
>>> BJP I think this as a cross check is good, but a lot of data is pretty much only in the results PDFs unless we go back to the nomination stuff.
### Stage 5 — Output (`data/`)

```
data/
  raw/
    2024-25_html.json       # raw scraped records before merging
    2024-25_pdfs/           # downloaded scrutineer PDFs
    2025-26_html.json
    2025-26_pdfs/
  processed/
    elections.json          # all years, merged, normalised
    elections.csv           # same, flat file for quick inspection
```

---

## Key Decisions / Open Questions

1. **STV vote data** — Scrutineer reports may show multi-round STV counts. Should we store only final totals, or all rounds? Suggest: store final totals only initially, with a flag `vote_method: "STV"`.
>>> BJP I do want all rounds and wouldn't summing that be a cross check on the final results? I mean, I'm ok starting with final totals, but the goal really is all the data.
2. **PDF format** — Are the PDFs machine-readable text or scanned images? If scanned, `pdfplumber` won't work and we'd need OCR (`pytesseract`). Need to verify by downloading a sample.

3. **Historical pages** — How many years back do we want to go? The URL pattern (`/article/NNNNN/...`) is not predictable — do we manually curate the URL list, or crawl the elections index?

4. **Uncontested seats** — Some seats are declared without a vote. These have no vote count. They should still appear in the data with `contested: false, outcome: "Elected"`.
>>> BJP Maybe with "0" votes? One of the things I'm going to want to analyse is seat vs vote share.
5. **Normalising positions across years** — Position names change subtly year-over-year. A manual mapping table may be needed to track the "same" seat across years. Worth doing now or defer to the Streamlit phase?

>>> BJP We should have a normalisation csv so we can track this over time.
---

## Proposed File Structure

```
ucuelections/
  scraper.py          # Stages 1-2: page fetch + HTML parse
  pdf_extractor.py    # Stage 3: PDF download + text extraction
  normalise.py        # Stage 4: merge + clean
  run_pipeline.py     # Orchestrates all stages, saves output
  data/
    raw/
    processed/
  PLAN.md             # this file
  requirements.txt
```

---

## Suggested Libraries

| Purpose | Library |
|---------|---------|
| HTTP fetching | `requests` |
| HTML parsing | `beautifulsoup4` + `lxml` |
| PDF text extraction | `pdfplumber` |
| Data wrangling | `pandas` |
| CLI orchestration | stdlib `argparse` |
>>> BJP seems fine.
---

## Next Steps (pending your review)

1. Confirm plan and resolve open questions above
2. Manually download one scrutineer PDF to inspect its format (text vs image, table layout)
3. Implement Stage 2 (HTML scraper) with output to `raw/`
4. Implement Stage 3 (PDF extractor) — approach depends on PDF format check
5. Implement Stage 4 (normalise/merge)
>>> BJP Gonna wanna data review here.
6. Build Streamlit app against `processed/elections.json`
