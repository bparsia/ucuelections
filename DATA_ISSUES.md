# Data Issues

## ballots.csv — known problems

### Missing years
- **2007, 2008**: no scrutineer PDFs with machine-readable ballot stats (2007 is fixed-width text without these fields; 2008 count sheets are .doc/.xls)
- **2018, 2019, 2021-22**: scrutineer PDFs downloaded but `Number of eligible voters` / `Total number of votes cast` not found in parseable text — likely scanned image pages or non-standard layout. Needs manual investigation.

### Misclassified / suspect rows
- **2010 FE**: no row produced — FE scrutineer report exists (`elect10_reportFE.pdf`) with eligible=40,438 but was not classified as FE by `_infer_ballot_type` (filename `reportFE` pattern not matched). Bug in regex.
- **2011 FE**: no row — `elections2011_feuk_fereg.pdf` produced no text (image PDF or extraction failure).
- **2011 HE (eligible=120,080)**: this figure looks like the *national* ballot, not HE-only — the report `elections2011_hevp_hontreas_eq.pdf` covers VP + Hon Treasurer + equality seats (national contest), mislabelled as HE. Should be `national`.
- **2012 FE — two rows**: main FE ballot (eligible=39,793) plus a casual vacancy ballot (eligible=38,114). The CV row should not be on the annual trend chart.
- **2013 HE — two rows**: eligible=7,259 (regional FE South casualvacancy?) and eligible=10,173 (NEC casual vacancy HE NE). Neither is the full HE ballot. The full 2013 HE ballot stats are not captured.
- **2016 HE (eligible=1,601)**: this is a single regional count sheet (e.g. London & East HE), not the full HE ballot. Full HE ballot stats not captured for 2016.
- **2019-20 HE (eligible=1,766)**: same problem — a single regional count sheet.
- **2021 FE (eligible=29,390)**: this is a casual vacancy ballot (from `2021_cv` directory), not an annual FE ballot. Included because its electorate is large enough to pass the suspect threshold.

### Structural note: HE/FE ballot size change post-2012
Pre-2012, all HE members voted in a single HE ballot (~67k eligible). Post-2012, regional HE NEC seats each have their own ballot covering only that region's HE members (typically 1–20k). These are not comparable to the pre-2012 figures. The `HE` line on a turnout chart is only meaningful within each era, not as a continuous series across 2009–2025.

Similarly for FE: pre-2012 the full FE ballot had ~40k eligible; post-2012 regional FE seats have ~3–6k.

### Rows to exclude from trend charts
Rows flagged `suspect=True` in ballots.csv:
- `election_type != "UK national"` (GS, Scotland, casual vacancy entries)
- `ballot_type == "HE"` and `eligible_voters < 5,000`
- `ballot_type == "FE"` and `eligible_voters < 3,000`
- 2011 HE row (actually national, mislabelled)
- 2021 FE row (casual vacancy, not annual ballot)
