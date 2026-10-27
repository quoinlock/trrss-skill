# TRRSS royalty statement skill for Claude

A Claude skill that audits translation-rights royalty statements against the
BISG Translation Rights Royalty Statement Standard (TRRSS, Jan 2026, 44 fields).
Give Claude a statement (PDF, Excel/CSV, pasted text, image) and it returns a
table of every field, green if present and red if missing, plus arithmetic
warnings (closing balance, payment due, life-to-date units). It can also
convert the statement to XML.

## Install (Claude Code)

Paste these two commands in a terminal:

```
claude plugin marketplace add quoinlock/trrss-skill
claude plugin install trrss-royalty-statement@trrss-skill
```

Then start Claude Code and ask, for example: "Audit this royalty statement
against the BISG standard" and attach or paste the statement.

To remove it: `claude plugin uninstall trrss-royalty-statement@trrss-skill`

## Before you install

Skills can run code, so read what you are installing. The only code is
`plugins/trrss-royalty-statement/skills/trrss-royalty-statement/scripts/trrss.py`
(about 300 lines, Python standard library only). It reads the JSON file you
point it at and writes only the output files you name; it makes no network
calls and never overwrites a file without `--force`.

Royalty statements contain financial and tax details. The skill works only on
the file you provide. Never commit a real statement to this repository.

## Notes and limits

- **Unofficial.** This is not published or endorsed by BISG. The XML output is
  not an official format; BISG has published fields, not a schema.
- **Required vs conditional fields is an interpretation** of the standard,
  recorded in `references/fields.json`.
- Missing *conditional* fields also show red in the table; the "Req" column says
  which ones may simply not apply to a given deal.
- Single currency per statement is assumed.
- The field list comes from BISG's published standard. Please refer to BISG for
  the authoritative text and its terms of use.

## Changes

See `plugins/trrss-royalty-statement/skills/trrss-royalty-statement/CHANGELOG.md`.

## License

MIT, see `LICENSE`.
