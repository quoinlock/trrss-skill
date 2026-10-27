# Changelog

Record every change here (what, why, risk considered) so future maintainers can reflect on decisions.

## 1.1.1 - 2026-10-26

Packaging only: no change to `SKILL.md`, `scripts/`, `references/` or `examples/`.

### Added
- Repo wrapper so friends can install with `claude plugin marketplace add` + `claude plugin install`: root `.claude-plugin/marketplace.json`, `plugins/trrss-royalty-statement/.claude-plugin/plugin.json`, `README.md`, `LICENSE`.
- The skill now lives at `plugins/trrss-royalty-statement/skills/trrss-royalty-statement/`.

### Decisions to revisit
- **License is MIT by default** (my choice, not the author's: change it if you prefer another). `YOUR NAME` and `YOUR-GITHUB-USERNAME` are placeholders to replace before publishing.
- Marketplace `name` (`trrss-skill`) equals the repo name used in the README install command; plugin entry `name` equals the manifest `name` (a mismatch breaks installs).
- BISG redistribution terms for the field list have not been checked; README points readers to BISG.

### Security considerations
- Installing from GitHub means users trust the repo owner's account for future updates: enable two-factor authentication and bump `version` in `plugin.json` on every release.
- README tells users to read `scripts/trrss.py` before installing and states it has no network access; verified by inspection that the script imports only stdlib modules and makes no network calls.
- Bundled examples contain invented data only; README warns never to commit real statements.

## 1.1.0 - 2026-10-25

Request: evaluated statements should output an easy-to-read table showing every field in red/green so gaps are obvious.

### Added
- `audit --table`: markdown table of all 44 fields, 🟢 present / 🔴 missing, with ID, label, location, required/conditional, and the value found (truncated). Emoji are used because they render in chat/terminals where ANSI or CSS colour would not.
- `audit --html OUT.html [--force]`: same table as a standalone HTML file with green/red cells.
- `rows` (one per field, per entry for list sections) added to the `audit --json` result.

### Changed (kept deliberately small)
- `audit()` records a row inside its existing presence loop via a small `add_row` helper, instead of a second pass, so the table can never disagree with the error/notes lists. Empty `product_lines` / `sublicenses` produce all-red rows so the table still covers all 44 fields.
- `SKILL.md`: workflow steps 3-4 now run `--table`/`--html` and lead the report with the table; security and Files lines updated. No change to `fields.json`, `to-xml`, `template`, or the text report.

### Design decisions
- **Two colours only, as requested.** Absent *conditional* fields are also red; the `Req` column says "conditional" and SKILL.md tells Claude to explain these may not apply. An amber state for "conditional, absent" is a possible follow-up (e.g. the passing sample shows 4 such red rows: Con16, Con21, RA9, RA24).
- Colour is never the only signal: HTML cells say PRESENT/MISSING, markdown rows carry the ID/Req text.
- Type/arithmetic warnings are not shown per row (a present-but-suspicious value stays green); they remain in the warnings list.

### Security considerations
- Statement text is untrusted. HTML: every cell passes through `html.escape`; no scripts, no external resources, CSP `default-src 'none'; style-src 'unsafe-inline'`. Markdown table: values HTML-escaped and `|` escaped; control chars and newlines stripped, length capped, so a value cannot break out of its row or inject markup.
- `--html` opens with exclusive-create unless `--force` (same guard as `to-xml -o`); no new file reads, network access, or dependencies (`html` is stdlib).
- Tested with a value containing `<script>`, `<img onerror>`, quotes, `|`, newline, NUL and ESC characters plus a `<evil/>` key: no raw markup in HTML or markdown output.
- Regression check against the 1.0.0 snapshot: `audit` text report, `to-xml`, and `template` output are byte-identical on both example files.

### Known limitations
- `rows` in `--json` is additive; consumers that validate the exact JSON shape of 1.0.0 would need updating.

## 1.0.0 - 2026-10-25

Initial version, built from `BISG_Translation-Rights-Royalty-Statement-Standard_2026-02.pdf` (standard released Jan 2026).

### Added
- `references/fields.json`: all 44 fields (15 contract, 19 statement-specific, 5 sublicense, 5 remittance). Counts were checked against the PDF's "forty-four data fields".
- `scripts/trrss.py` (single file, stdlib only): `template`, `audit`, `to-xml`.
- `SKILL.md`, `examples/sample_complete.json`, `examples/sample_incomplete.json`.

### Design decisions
- **Claude does the fuzzy mapping, the script does the deterministic checks.** Real statements use varied labels, so extraction to normalized JSON is left to Claude (guided by synonyms in fields.json); presence checks, arithmetic and XML output are scripted so results are repeatable.
- **Required vs conditional is an interpretation** (see `interpretation_note` in fields.json). The PDF only explicitly labels SC3-SC23 as conditional and RA9 "if applicable". Con16/Con21, RA14, RA19, RA24 are treated as conditional from their descriptions. Revisit if BISG publishes clearer rules.
- **XML is unofficial.** The PDF defines no schema. Root carries `representation="unofficial..."`. Elements use the BISG short key plus `bisgId`. Product forms and sublicensees repeat as `ProductLine` / `Sublicense`.
- **Arithmetic checks are warnings, not failures**, since they depend on how a licensee defines basis/rate (percent vs per-copy). Rate x basis x units is tried with the rate as a fraction and as a percent.

### Security considerations
- Input parsed with `json` only (no eval/pickle/YAML); 5 MB size cap.
- XML is only written, never parsed, so no XXE / entity-expansion exposure.
- Element names come exclusively from fields.json, so input keys cannot inject markup (tested with a `<evil/>` key); text is escaped and illegal XML 1.0 control characters are stripped (tested with `<`, `>`, `&`).
- Output opened with exclusive-create unless `--force`, to avoid silently clobbering files.
- SKILL.md tells Claude to treat statement text as data, not instructions, and to avoid sending financial/tax data elsewhere.

### Known limitations
- Single currency assumed per statement; multi-currency statements need review.
- No XSD validation of the XML (no official schema exists).
- Rate escalations (SS47 note) are not modelled beyond a single rate per product line.
