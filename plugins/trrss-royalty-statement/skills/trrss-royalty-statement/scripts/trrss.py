#!/usr/bin/env python3
"""BISG Translation Rights Royalty Statement Standard (TRRSS) helper.

Subcommands:
  template            print an empty normalized-JSON skeleton
  audit  FILE.json    check required/conditional fields + arithmetic; exit 1 if required fields are missing
                      (--table: 🟢/🔴 field table; --html OUT.html [--force]: red/green HTML table)
  to-xml FILE.json    convert normalized JSON to an XML representation (-o OUT.xml, --strict, --force)

Security notes: input is parsed with json only (never eval/pickle); size-capped; XML is
only ever *written* (no XML parsing, so no XXE); element names come exclusively from
references/fields.json, never from input keys; text is escaped by ElementTree and stripped
of characters illegal in XML 1.0.
"""
import argparse, html, json, os, re, sys
import xml.etree.ElementTree as ET
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS_PATH = os.path.join(HERE, "..", "references", "fields.json")
MAX_BYTES = 5 * 1024 * 1024
TOL = 0.011  # money tolerance (rounding to cents)
SECTIONS = ["contract", "statement", "product_lines", "sublicenses", "remittance"]
LISTS = {"product_lines", "sublicenses"}
BAD_XML = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")


def load_fields():
    with open(FIELDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_statement(path):
    if os.path.getsize(path) > MAX_BYTES:
        sys.exit(f"error: {path} exceeds {MAX_BYTES} bytes")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        sys.exit("error: top level of input must be a JSON object")
    return data


def blank(v):
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, list):
        return not v or all(blank(x) for x in v)
    return False


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(re.sub(r"[,$€£¥%\s]", "", v))
        except ValueError:
            return None
    return None


def isbn_ok(s):
    d = re.sub(r"[-\s]", "", str(s)).upper()
    if re.fullmatch(r"\d{13}", d):
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0
    if re.fullmatch(r"\d{9}[\dX]", d):
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d)) % 11 == 0
    return False


def type_problem(f, v):
    """Return a message if a present value looks wrong for its declared type."""
    t = f.get("type")
    vals = v if isinstance(v, list) else [v]
    for x in vals:
        if t == "number" and num(x) is None:
            return f"{f['id']} {f['label']}: '{x}' is not numeric"
        if t == "date":
            try:
                date.fromisoformat(str(x))
            except ValueError:
                return f"{f['id']} {f['label']}: '{x}' is not an ISO date (YYYY-MM-DD)"
        if t == "currency" and not re.fullmatch(r"[A-Z]{3}|[$€£¥]", str(x).strip()):
            return f"{f['id']} {f['label']}: '{x}' is not a 3-letter currency code or symbol"
        if t == "isbn" and not isbn_ok(x):
            return f"{f['id']} {f['label']}: '{x}' is not a valid ISBN (acceptable only for non-book products)"
    return None


def audit(data):
    spec = load_fields()
    by_loc = {s: [f for f in spec["fields"] if f["loc"] == s] for s in SECTIONS}
    errors, warnings, notes = [], [], []
    rows = []  # one row per field (per entry for list sections) for the red/green table

    def add_row(f, where, v):
        shown = "; ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v))
        rows.append({"id": f["id"], "label": f["label"], "where": where, "req": f["req"],
                     "present": not blank(v), "value": shown})

    # normalise containers
    objs = {}
    for s in SECTIONS:
        v = data.get(s)
        if s in LISTS:
            objs[s] = [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
        else:
            objs[s] = [v] if isinstance(v, dict) else [{}]
        if v is not None and ((s in LISTS) != isinstance(v, list)):
            errors.append(f"section '{s}' has the wrong JSON shape ({'array' if s in LISTS else 'object'} expected)")

    # unknown keys (ignored by to-xml)
    for s in SECTIONS:
        known = {f["key"] for f in by_loc[s]}
        for i, o in enumerate(objs[s]):
            for k in o:
                if k not in known:
                    warnings.append(f"{s}[{i}]: unknown key '{k}' (ignored in XML output)")
    for k in data:
        if k not in SECTIONS and k != "meta":
            warnings.append(f"unknown top-level key '{k}' (ignored)")

    # presence checks
    for s in SECTIONS:
        entries = objs[s]
        if s == "product_lines" and not entries:
            errors.append("no product_lines: every product form sold needs its own line (SS22-SS62, SS72)")
            for f in by_loc[s]:
                add_row(f, s, None)
            continue
        if s == "sublicenses" and not entries:
            notes.append("No sublicenses reported (SC3-SC23): confirm none occurred this period")
            for f in by_loc[s]:
                add_row(f, s, None)
            continue
        for i, o in enumerate(entries):
            where = f"{s}[{i}]" if s in LISTS else s
            for f in by_loc[s]:
                v = o.get(f["key"])
                add_row(f, where, v)
                if blank(v):
                    trigger = f["id"] == "Con21" and not blank(objs["contract"][0].get("PayName"))
                    if f["req"] == "required" or s == "sublicenses" or trigger:
                        errors.append(f"MISSING {f['id']} {f['label']} ({where})")
                    else:
                        notes.append(f"Not present {f['id']} {f['label']}: {f['cond']}")
                else:
                    p = type_problem(f, v)
                    if p:
                        warnings.append(f"{where}: {p}")
    notes = list(dict.fromkeys(notes))

    # arithmetic / consistency checks (warnings: they indicate a statement worth querying)
    st = objs["statement"][0]
    lines = objs["product_lines"]
    n = num
    for i, ln in enumerate(lines):
        u, b, ltd = n(ln.get("UnitsSldinPer")), n(ln.get("NetUnitstoBegPer")), n(ln.get("LTDUnitsSold"))
        if None not in (u, b, ltd) and abs(u + b - ltd) > 1e-6:
            warnings.append(f"product_lines[{i}]: SS72 LTDUnitsSold {ltd:g} != SS57 {u:g} + SS22 {b:g}")
        r, bs, e = n(ln.get("RoyRate")), n(ln.get("RoyBasis")), n(ln.get("RoyEarnings"))
        if None not in (r, bs, u, e) and min(abs(r * bs * u - e), abs(r / 100 * bs * u - e)) > TOL:
            warnings.append(f"product_lines[{i}]: SS62 RoyEarnings {e:g} != rate x basis x units (rate tried as fraction and as percent)")
    earned = [n(l.get("RoyEarnings")) for l in lines]
    tot = n(st.get("TotRoyEarnings"))
    if tot is not None and None not in earned and abs(sum(earned) - tot) > TOL:
        warnings.append(f"SS67 TotRoyEarnings {tot:g} != sum of line SS62 ({sum(earned):g})")
    rw, rr = n(st.get("ResWithheld")), n(st.get("ResReleased"))
    if rw is not None and rw > 0:
        warnings.append("SS77 ResWithheld must be 0 or negative")
    if rr is not None and rr < 0:
        warnings.append("SS82 ResReleased must be 0 or positive")
    subamt = [n(x.get("LicensorAmtInc")) or 0.0 for x in objs["sublicenses"]]
    cb, ob, pd = n(st.get("ClosingBal")), n(st.get("OpenBal")), n(st.get("PayDue"))
    if None not in (tot, cb) and abs(tot + (rw or 0) + (rr or 0) + sum(subamt) - cb) > TOL:
        warnings.append("SS87 ClosingBal != SS67 + SS77 + SS82 + sum(SC23)")
    if None not in (ob, cb, pd) and abs(ob + cb - pd) > TOL:
        warnings.append("SS92 PayDue != SS17 OpenBal + SS87 ClosingBal")
    try:
        s0, s1, s2 = (date.fromisoformat(str(st.get(k))) for k in ("RoyRptStartDt", "RoyRptEndDt", "RoyStmntDate"))
        if s0 > s1:
            warnings.append("SS7 period start is after SS12 period end")
        if s2 < s1:
            warnings.append("SS2 statement date is before the period end date")
    except (ValueError, TypeError):
        pass

    total = len(spec["fields"])
    return {"standard": spec["standard"], "version": spec["version"], "fields_in_standard": total,
            "errors": errors, "warnings": warnings, "notes": notes, "pass": not errors, "rows": rows}


def print_report(r):
    print(f"{r['standard']} ({r['version']}) audit: {'PASS' if r['pass'] else 'FAIL'}")
    for title, key in (("Missing / invalid required", "errors"), ("Warnings", "warnings"), ("Notes (conditional fields)", "notes")):
        if r[key]:
            print(f"\n{title} ({len(r[key])}):")
            for m in r[key]:
                print(f"  - {m}")


def clean(v):
    return BAD_XML.sub("", str(v))


def _cell(v, n=40):
    """One-line, control-char-free, length-capped text for a table cell."""
    v = re.sub(r"\s+", " ", clean(v)).strip()
    return v if len(v) <= n else v[: n - 1] + "…"


def _present_count(r):
    """(fields fully present, distinct field IDs); a list-section field counts only if present in every entry."""
    ids = {}
    for x in r["rows"]:
        ids[x["id"]] = ids.get(x["id"], True) and x["present"]
    return sum(ids.values()), len(ids)


def print_table(r):
    """Markdown table with 🟢/🔴 per field (renders in chat and terminals)."""
    ok, total = _present_count(r)
    print(f"{ok} of {total} fields present, {total - ok} missing\n")
    print("| | ID | Field | Where | Req | Value found |\n|---|---|---|---|---|---|")
    for x in r["rows"]:
        v = html.escape(_cell(x["value"]), quote=False).replace("|", "\\|")  # statement text is data: neutralise markup/pipes
        print(f"| {'🟢' if x['present'] else '🔴'} | {x['id']} | {x['label']} | {x['where']} | {x['req']} | {v} |")


def write_html(r, path, force=False):
    """Standalone red/green HTML table. Static: all text HTML-escaped, no scripts, CSP blocks everything but inline CSS."""
    ok, total = _present_count(r)
    body = []
    for x in r["rows"]:
        cells = ("PRESENT" if x["present"] else "MISSING", x["id"], x["label"], x["where"], x["req"], _cell(x["value"], 80))
        body.append(f'<tr class="{"ok" if x["present"] else "bad"}">' + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
    title = html.escape(f"{r['standard']} ({r['version']}) audit: {'PASS' if r['pass'] else 'FAIL'}")
    doc = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        f"<title>{title}</title><style>"
        "body{font:14px system-ui,sans-serif;margin:1.5em}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #bbb;padding:4px 8px;text-align:left}th{background:#eee}"
        ".ok td{background:#d4edda;color:#155724}.bad td{background:#f8d7da;color:#721c24;font-weight:600}"
        f"</style><h1>{title}</h1><p>{ok} of {total} fields present, {total - ok} missing</p>"
        "<table><tr><th>Status<th>ID<th>Field<th>Where<th>Req<th>Value found</tr>" + "".join(body) + "</table></html>"
    )
    try:
        with open(path, "w" if force else "x", encoding="utf-8") as f:  # 'x' refuses to overwrite
            f.write(doc)
    except FileExistsError:
        sys.exit(f"error: {path} exists (use --force to overwrite)")
    print(f"wrote {path}")


def to_xml(data):
    spec = load_fields()
    root = ET.Element("TranslationRightsRoyaltyStatement", {
        "standard": spec["standard"], "standardVersion": spec["version"],
        "representation": "unofficial (BISG has not published an XML schema)"})

    def fill(parent, fields, obj):
        for f in fields:  # tag names come only from fields.json
            v = obj.get(f["key"])
            if blank(v):
                continue
            for x in (v if isinstance(v, list) else [v]):
                if not blank(x):
                    ET.SubElement(parent, f["key"], {"bisgId": f["id"]}).text = clean(x)

    F = {s: [f for f in spec["fields"] if f["loc"] == s] for s in SECTIONS}
    dict_or_empty = lambda k: data.get(k) if isinstance(data.get(k), dict) else {}
    list_or_empty = lambda k: [x for x in data.get(k, []) if isinstance(x, dict)] if isinstance(data.get(k), list) else []
    fill(ET.SubElement(root, "Contract"), F["contract"], dict_or_empty("contract"))
    stm = ET.SubElement(root, "Statement")
    fill(stm, F["statement"], dict_or_empty("statement"))
    pl = ET.SubElement(stm, "ProductLines")
    for o in list_or_empty("product_lines"):
        fill(ET.SubElement(pl, "ProductLine"), F["product_lines"], o)
    subs = list_or_empty("sublicenses")
    if subs:
        sl = ET.SubElement(stm, "Sublicenses")
        for o in subs:
            fill(ET.SubElement(sl, "Sublicense"), F["sublicenses"], o)
    fill(ET.SubElement(root, "RemittanceAdvice"), F["remittance"], dict_or_empty("remittance"))
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def template():
    spec = load_fields()
    out = {}
    for s in SECTIONS:
        row = {f["key"]: ([] if f.get("multi") else "") for f in spec["fields"] if f["loc"] == s}
        out[s] = [row] if s in LISTS else row
    return json.dumps(out, indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("template")
    a = sub.add_parser("audit"); a.add_argument("file"); a.add_argument("--json", action="store_true")
    a.add_argument("--table", action="store_true", help="print a 🟢/🔴 table of all fields before the report")
    a.add_argument("--html", metavar="OUT.html", help="also write a red/green HTML table of all fields")
    a.add_argument("--force", action="store_true", help="overwrite the --html output file if it exists")
    x = sub.add_parser("to-xml"); x.add_argument("file"); x.add_argument("-o", "--out")
    x.add_argument("--strict", action="store_true", help="refuse to convert if required fields are missing")
    x.add_argument("--force", action="store_true", help="overwrite the output file if it exists")
    args = ap.parse_args()

    if args.cmd == "template":
        print(template()); return 0
    data = load_statement(args.file)
    r = audit(data)
    if args.cmd == "audit":
        if args.html:
            write_html(r, args.html, args.force)
        if args.table and not args.json:
            print_table(r); print()
        print(json.dumps(r, indent=2, ensure_ascii=False)) if args.json else print_report(r)
        return 0 if r["pass"] else 1
    if args.strict and not r["pass"]:
        print_report(r); print("\nnot converted (--strict)", file=sys.stderr); return 1
    for w in r["warnings"]:
        if "unknown key" in w:
            print("warning:", w, file=sys.stderr)
    xml = to_xml(data)
    if args.out:
        try:
            with open(args.out, "wb" if args.force else "xb") as f:  # 'x' refuses to overwrite
                f.write(xml)
        except FileExistsError:
            sys.exit(f"error: {args.out} exists (use --force to overwrite)")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(xml.decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
