# UCU Elections — Scraping & Data Extraction Plan

## Overview

Build a pipeline that fetches UCU UK election result pages, extracts structured candidate/result data from both inline HTML and PDF scrutineer reports, and stores it as clean, normalised tables for downstream use in a Streamlit explorer.

**Primary data source:** PDF scrutineer reports (full candidate lists, all STV rounds)
**Supplementary source:** Inline HTML (uncontested seats and no-nomination seats only)

---

## Data Sources

### Election page discovery

URL patterns are not predictable, so discovery is a two-phase process:

**Phase A — automated crawl:**
- Scrape the UCU "Previous elections" index (URL to be confirmed by inspecting the site navigation)
- Collect all article links that look like election result pages

**Phase B — manual review:**
- Review the list of discovered URLs, add any missed years, remove non-result pages
- Maintain a curated `sources/election_pages.csv` with columns: `year`, `url`, `notes`

This file becomes the permanent registry of known election pages.

### Per-page assets

Each article page contains:
1. **Inline HTML** — summary of winners; also the only source for uncontested seats and seats with no nominations
2. **PDF scrutineer reports** — 3 per year (National, HE seats, FE seats); primary source for all contested results, full candidate lists, and STV vote data
3. **Supporting documents** — nomination forms, rules, guidance (not needed)

---

## Data Model

Three normalised tables, stored as CSV files:

### Table 1: `candidates.csv`
One row per candidate per contest per year. The base record.

| Field | Type | Notes |
|-------|------|-------|
| `year` | str | e.g. `"2024-25"` |
| `contest_id` | str | Slug linking to `contests.csv`, e.g. `"2024-25_nw-he"` |
| `candidate_name` | str | From PDF (authoritative) |
| `institution` | str | From PDF where available |
| `outcome` | str | `Elected` / `Not Elected` / `Uncontested` / `No Nomination` |
| `votes_final` | int | Total votes in final round; `0` for uncontested/no-nomination |
| `first_preferences` | int | Round 1 votes; `null` if not STV or not available |
| `source` | str | `pdf` / `html` |
| `source_url` | str | URL of PDF or article page |

### Table 2: `stv_rounds.csv`
One row per candidate per round per contest. Enables flow/Sankey analysis.

| Field | Type | Notes |
|-------|------|-------|
| `year` | str | |
| `contest_id` | str | |
| `candidate_name` | str | |
| `round` | int | 1, 2, 3… |
| `votes` | float | May include fractional transfers in STV |
| `status` | str | `Active` / `Eliminated` / `Elected` / `Excluded` |
| `votes_transferred_from` | str | Name of eliminated candidate whose votes transferred (if known from report) |

### Table 3: `contests.csv`
One row per contest per year. Metadata for grouping and filtering.

| Field | Type | Notes |
|-------|------|-------|
| `contest_id` | str | Unique slug |
| `year` | str | |
| `election_type` | str | `Officer` / `NEC Geographic` / `NEC Constituency` / `Trustee` / `Scotland` |
| `position_raw` | str | Exact label from source |
| `position_norm` | str | Normalised label from `position_map.csv` |
| `sector` | str | `HE` / `FE` / `Both` / `null` |
| `region` | str | Geographic region or `null` (equality seats have no region) |
| `constituency` | str | e.g. `"Disabled Members"`, `"LGBT+"` or `null` |
| `seats_available` | int | Number of seats being filled |
| `contested` | bool | `False` if uncontested or no nominations |
| `vote_method` | str | `STV` / `FPTP` / `Uncontested` / `null` |
| `scrutineer_pdf_url` | str | URL of source PDF |

### Reference file: `position_map.csv`
Manual mapping to track the same seat across years as names drift.

| Field | Notes |
|-------|-------|
| `position_raw` | Exact label from source |
| `year` | |
| `position_norm` | Normalised canonical label |
| `election_type` | |
| `sector` | |
| `region` | |
| `constituency` | |

This file is committed to the repo and updated manually as new years are added.

---

## Pipeline Stages

### Stage 0 — Page discovery (`discover.py`)

1. Fetch the UCU elections index page(s) and extract all election result article links
2. Write to `sources/election_pages.csv` for manual review
3. After review, this CSV drives all subsequent stages

### Stage 1 — Asset collection (`fetch.py`)

For each row in `election_pages.csv`:
1. Fetch the article page with `requests`
2. Parse with `BeautifulSoup` (lxml)
3. Identify and download all scrutineer report PDFs to `data/raw/{year}/pdfs/`
4. Save raw HTML to `data/raw/{year}/page.html`
5. Extract uncontested/no-nomination entries from inline HTML only

### Stage 2 — PDF extraction (`pdf_extractor.py`)

For each scrutineer PDF:
1. Extract text page-by-page with `pdfplumber`
2. Identify contest blocks (headings / section breaks)
3. For each contest, extract:
   - Contest name / seat label
   - Number of seats
   - All candidates (name, institution if present)
   - STV round-by-round vote tables
   - Elected/eliminated status per round
4. Write raw extracted data to `data/raw/{year}/pdf_records.json`

**Known challenges:**
- Complex, variable table and list structures across PDFs and years — parsing logic will likely need year-specific handling or heuristics
- STV fractional vote transfers
- Candidate name formatting varies (titles, middle names)

### Stage 3 — Normalise & merge (`normalise.py`)

1. Load PDF records as the base dataset
2. Supplement with HTML-extracted uncontested/no-nomination entries
3. Apply `position_map.csv` to populate `position_norm`
4. Derive `contest_id` slugs
5. Populate `stv_rounds.csv` from round-by-round data
6. Cross-check: flag any HTML-listed winners not found in PDF data
7. Write `data/processed/candidates.csv`, `contests.csv`, `stv_rounds.csv`

**Data review checkpoint** — output should be inspected before the Streamlit app is built.

### Stage 4 — Streamlit app (`app.py`)

Built against the processed CSVs. Planned separately.

---

## Output Structure

```
ucuelections/
  sources/
    election_pages.csv      # curated registry of all known election pages
    position_map.csv        # manual position normalisation across years
  data/
    raw/
      2024-25/
        page.html
        pdfs/
          national_scrutineer.pdf
          he_scrutineer.pdf
          fe_scrutineer.pdf
        pdf_records.json    # raw extracted from PDFs
        html_records.json   # uncontested/no-nomination from HTML
      2025-26/
        ...
    processed/
      candidates.csv
      contests.csv
      stv_rounds.csv
  discover.py
  fetch.py
  pdf_extractor.py
  normalise.py
  run_pipeline.py           # orchestrates all stages
  app.py                    # Streamlit (later)
  requirements.txt
  PLAN.md
```

---

## Libraries

| Purpose | Library |
|---------|---------|
| HTTP fetching | `requests` |
| HTML parsing | `beautifulsoup4` + `lxml` |
| PDF text extraction | `pdfplumber` |
| Data wrangling | `pandas` |
| CLI orchestration | stdlib `argparse` |

---

## Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | PDF format | Text-based (confirmed). Complex variable structure — no OCR needed |
| 2 | Primary data source | PDFs are authoritative; HTML only for uncontested/no-nomination |
| 3 | STV rounds | Store all rounds in `stv_rounds.csv` (long format). Goal: Sankey/flow graphs of vote transfers |
| 4 | Uncontested votes | Store `votes: 0` (not null) so seat/vote share analysis is consistent |
| 5 | Position normalisation | `position_map.csv` maintained manually in repo |
| 6 | Historical depth | Go as far back as possible; Stage 0 = discovery + manual review before scraping |

---

## Next Steps

1. **Run `discover.py`** — crawl elections index, produce draft `election_pages.csv`
2. **Manual review** — confirm/add/remove URLs, especially older years
3. **Download one PDF** — inspect structure of a scrutineer report to inform `pdf_extractor.py` design
4. **Implement `fetch.py`** — download all assets per year
5. **Implement `pdf_extractor.py`** — extract raw contest/candidate/STV data
6. **Implement `normalise.py`** — produce processed CSVs
7. **Data review checkpoint** — inspect processed output before building app
8. **Build `app.py`**
