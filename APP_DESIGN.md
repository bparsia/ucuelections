# UCU Elections Explorer — App Design

>>> BJP OY! THIS IS ALL NONSENSE
>>> BJP Seriously, why would you do all this "work" without consulting me? Just to cost me tokens? Make me upset? Generally bullshit?
>>> BJP It's extra annoying becuase I made it clear that I had particular goals.

## Goals

1. The overarching goal is to help provide insight into UCU elections as a whole. This means doing key bits of analysis that the existing election pages (with PDFs etc.) make tedious or impossible. That's why we extracted the data.
2. For example, overall turnout (percentagewise and absolute) over time is really difficult to track. Having a turnout percentage with key events (e.g., whether GS or VP HE or VP FE year) is key.
3. Some things are tedious and difficult even for a single election. It'd be nice to have sections for each election so one can drill in without having to open multiple documents. It'd be nice to see at a scan which elections had specific turnout issues (e.g., wasted ballots)
4. Eventually I want to add faction/affiliation information so we can see a notion of "vote share" for each grouping. I'm also very interested is seeing the "vote/seat" ratio to understand the effects of regional gerry mandering.
5. I am also interested in views of individuals e.g., vote share, length of service ,etc.

So, to get started, how about a simple landing page with a table with gross stats in total (e.g., races, seats, winners, candidates) and a line chart of turnout.

>>> BJP
>>> BJP ---- 
>>> BJP I am ignoring AI SLOP below even if some bits are relevant or helpful. 
>>> BJP ----
## Primary goals

The app should help answer:

1. **What happened in a given election year?** — a complete picture of all contests, turnout, results.
2. **How has a role or region changed over time?** — longitudinal view of the same seat across multiple elections.
3. **Where did votes go in an STV contest?** — round-by-round flow for a single contest.

Single-contest drill-down (the only thing in the current draft) is at best tertiary.

---

## Navigation structure

A top-level navigation (Streamlit `st.tabs` or sidebar radio):

```
[ Overview ]  [ Election Year ]  [ Longitudinal ]  [ Contest Detail ]
```

---

## View 1 — Overview (landing page)

A dashboard summarising the whole dataset.

**Content:**
- **Stat cards:** total years covered, total contests, total candidates, total ballots cast (sum of valid_votes)
- **Bar chart — contests per year:** stacked by election_type (UK national / Scotland / GS / casual vacancy)
- **Bar chart — candidates per year:** stacked elected vs not elected
- **Bar chart — total valid votes cast per year** (turnout proxy; note: each voter may cast ballots in multiple contests)
- **Table — data coverage gaps:** which years have no STV round data and why (2008 = .doc/.xls; 2015/2017 = text-only scrutineer report; image PDFs)

**Questions it answers:** How large is this dataset? Which years are well-covered?

---

## View 2 — Election Year

Drill into a single election year. Selector: year dropdown (most recent first).

### Section A — Summary

- Cards: total contests, total valid votes, number with full STV data
- Table of all contests for the year with columns:
  `Contest | Type | Seats | Candidates | Valid votes | Winner(s) | STV data?`
  - Clicking a row navigates to Contest Detail (View 4)

### Section B — Turnout map / bar chart

Horizontal bar chart: contests sorted by valid_votes, coloured by election_type.
Shows at a glance which roles attracted the most votes.

### Section C — Results grid

For all contested roles in this year: winner name(s), first-preference vote share, number of rounds needed.
Useful for a quick "who won everything" overview.

### Section D — Uncontested / no-nomination list

Table of positions that were uncontested or had no nominations, from html_records.

---

## View 3 — Longitudinal

Track a role (or region) across all years it appears.

**Selector:** free-text search + dropdown of `position` values (from contests.csv). Because contest names vary year-to-year, this will need `position_map.csv` to work well — but can fall back to exact `contest_name` matching in the meantime.

### Section A — Turnout over time

Line chart: valid_votes by year for the selected position.

### Section B — Competition over time

Line chart or bar: number of candidates, number of seats, quota value — all by year.

### Section C — Results table over time

One row per year: winner(s), first-preference votes, rounds, turnout.

### Section D — First-preference vote share over time

For positions contested in multiple years: stacked bar showing first-preference distribution per candidate per year. Useful for tracking whether the same people keep running and how their support shifts.

---

## View 4 — Contest Detail

Drill into one specific contest (reached by clicking from the Year view, or via direct selector).

### Section A — Metadata

Seats, valid votes, invalid votes, quota, election rules, date, source PDF.

### Section B — Results table

Candidate table: name | demographic flags | outcome | first preferences | rounds to elected/eliminated.

### Section C — Vote progression chart

Line chart: votes per candidate per round (x = round, y = votes). One line per candidate, coloured by outcome (green = elected, red = not elected, orange = withdrawn). Dashed horizontal line at quota.

This is the STV "flow" view within a single contest. True Sankey (showing transfers between specific candidates) is not possible with current data — we have net totals per candidate per round, not per-transfer breakdowns.

### Section D — Transfer heatmap

Heatmap of net transfers per candidate per stage. Green = gained votes, red = lost.

---

## Data notes / constraints

- **Turnout:** `valid_votes` counts ballots for that one contest, not unique voters. No way to compute whole-election turnout from these figures.
- **STV round data gaps:** 99 of 288 contests have no round data (ROV-only, uncontested, image PDFs, pre-2009). These show results only.
- **Demographic flags:** sparse and inconsistently formatted across years — not reliable enough for filtering without a cleaning pass.
- **Position normalisation:** `position_map.csv` (not yet created) is needed to reliably match the same role across years. Without it, Longitudinal view uses exact `contest_name` string matching (limited).
- **Scotland / GS / casual vacancy pages** are included but sparse — most have no STV data.

---

## Open questions for the user

1. **Longitudinal view:** should it be limited to roles with 3+ appearances, or show all? Should it be a first-class view or a section within the Year view?
2. **Position map:** do you want to create `position_map.csv` now so the longitudinal view works properly? Or build the view first and add normalisation later?
3. **Demographic flags:** worth a cleaning pass to enable filtering by woman/post-92/etc.?
4. **Turnout:** is valid_votes per contest useful, or would you prefer to focus on relative measures (vote share, turnout vs previous year)?
5. **GS / Scotland / casual vacancy:** include in main views, or filter to UK national only by default?
