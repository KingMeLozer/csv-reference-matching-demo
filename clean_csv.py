"""Clean a small CSV and produce a record-by-record change report."""

import argparse
import csv
import io
import re
from pathlib import Path


def clean_csv(source, destination, report=None, key_columns=None, reference=None, add_columns=None):
    source, destination = Path(source), Path(destination)
    report = Path(report) if report else destination.with_name(destination.stem + "_report.csv")
    reference = Path(reference) if reference else None
    paths = [source, destination, report] + ([reference] if reference else [])
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError("Source, reference, output, and report must be different files")
    if destination.exists() or report.exists():
        raise FileExistsError("Output or report exists; choose new filenames")

    # ponytail: memory-backed for small exports; stream if larger files become routine.
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, strict=True))
    if not rows:
        raise ValueError("Empty CSV")
    headers = [h.strip() for h in rows[0]]
    if any(not h for h in headers) or len({h.casefold() for h in headers}) != len(headers):
        raise ValueError("Headers must be nonempty and unique")
    columns = {h.casefold(): i for i, h in enumerate(headers)}
    if key_columns:
        missing = [h for h in key_columns if h.casefold() not in columns]
        if missing:
            raise ValueError("Unknown match columns: " + ", ".join(missing))
        match_columns = [columns[h.casefold()] for h in key_columns]
    else:
        match_columns = [columns["business"], columns["phone"]] if "business" in columns and "phone" in columns else []

    def key_value(value, name):
        if name == "phone":
            digits = re.sub(r"\D", "", value)
            return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
        return value.casefold() if name == "business" else value

    add_columns = add_columns or []
    if add_columns and not reference:
        raise ValueError("--add requires --reference")
    reference_rows = {}
    reference_columns = {}
    extra_headers = []
    if reference:
        if not match_columns:
            raise ValueError("Reference enrichment needs --key, or business and phone columns")
        with reference.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.reader(handle, strict=True))
        if not source_rows:
            raise ValueError("Empty reference CSV")
        reference_headers = [h.strip() for h in source_rows[0]]
        if any(not h for h in reference_headers) or len({h.casefold() for h in reference_headers}) != len(reference_headers):
            raise ValueError("Reference headers must be nonempty and unique")
        reference_columns = {h.casefold(): i for i, h in enumerate(reference_headers)}
        key_names = [headers[i].casefold() for i in match_columns]
        if any(name not in reference_columns for name in key_names):
            raise ValueError("Reference CSV lacks a match column")
        for name in add_columns:
            if name.casefold() not in reference_columns:
                raise ValueError(f"Reference CSV lacks requested column: {name}")
            if name.casefold() not in columns and name.casefold() not in {h.casefold() for h in extra_headers}:
                extra_headers.append(reference_headers[reference_columns[name.casefold()]])
        for number, row in enumerate(source_rows[1:], 1):
            if not row or not any(value.strip() for value in row):
                continue
            if len(row) != len(reference_headers):
                raise ValueError(f"Reference record {number}: wrong field count")
            row = [value.strip() for value in row]
            key = tuple(key_value(row[reference_columns[name]], name) for name in key_names)
            if all(key):
                reference_rows.setdefault(key, []).append((number, row))

    output_headers = headers + extra_headers

    def make_match_key(row, names):
        return tuple(key_value(row[columns[name]], name) for name in names)

    output = [output_headers]
    audit = [["source_record", "status", "cleaned_record", "changes", "review_note"]]
    seen, matched = {}, {}
    duplicates = blanks = changed = reviews = 0
    for source_record, row in enumerate(rows[1:], 1):
        if not row or not any(value.strip() for value in row):
            blanks += 1
            audit.append([source_record, "blank_skipped", "", "", ""])
            continue
        if len(row) != len(headers):
            raise ValueError(f"Record {source_record}: expected {len(headers)} fields, got {len(row)}")
        clean = [value.strip() for value in row] + [""] * len(extra_headers)
        notes = []
        if reference:
            key_names = [headers[i].casefold() for i in match_columns]
            key = make_match_key(clean, key_names)
            candidates = reference_rows.get(key, []) if all(key) else []
            unique = {tuple(record) for _, record in candidates}
            if len(unique) > 1:
                notes.append("Multiple conflicting reference records; no enrichment applied")
            elif not candidates:
                notes.append("No exact reference match; no enrichment applied")
            else:
                reference_number, reference_row = candidates[0]
                for name, index in columns.items():
                    if name in key_names or name not in reference_columns:
                        continue
                    supplied = reference_row[reference_columns[name]]
                    if not clean[index] and supplied:
                        clean[index] = supplied
                        notes.append(f"{headers[index]} filled from reference record {reference_number}")
                    elif clean[index] and supplied and clean[index].casefold() != supplied.casefold():
                        notes.append(f"{headers[index]} conflicts with reference record {reference_number}; input retained")
                for offset, name in enumerate(extra_headers, len(headers)):
                    clean[offset] = reference_row[reference_columns[name.casefold()]]
                    if clean[offset]:
                        notes.append(f"{name} added from reference record {reference_number}")
        for name, index in columns.items():
            value = clean[index]
            if name == "phone" and value:
                digits = re.sub(r"\D", "", value)
                if len(digits) == 11 and digits.startswith("1"):
                    digits = digits[1:]
                if len(digits) == 10:
                    clean[index] = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
                else:
                    notes.append("Phone needs review; original retained")
            elif name == "city" and value and (value.islower() or value.isupper()):
                clean[index] = value.title()
            elif name == "state" and len(value) == 2 and value.isalpha():
                clean[index] = value.upper()
            elif name == "email":
                if not value:
                    notes.append("Email missing; verify")
                elif "@" in value:
                    local, domain = value.rsplit("@", 1)
                    clean[index] = local + "@" + domain.lower()
        for index, value in enumerate(clean):
            if value[:1] in "=+@" or (value[:1] == "-" and value[1:2] and not value[1:2].isdigit()):
                notes.append(f"{output_headers[index]} starts with a spreadsheet formula character; review before opening in Excel")
        before_values = row + [""] * len(extra_headers)
        changes = "; ".join(f"{output_headers[i]}: {before!r} -> {after!r}" for i, (before, after) in enumerate(zip(before_values, clean)) if before != after)
        # Business names compare case-insensitively; email local parts stay case-sensitive
        # (domains were already lowercased above). Every other value must match exactly.
        exact_key = tuple(v.casefold() if output_headers[i].casefold() == "business" else v for i, v in enumerate(clean))
        if exact_key in seen:
            duplicates += 1
            audit.append([source_record, "duplicate_removed", seen[exact_key], changes, "Same cleaned values as retained record"])
            continue
        seen[exact_key] = len(output)
        if match_columns:
            match_key = tuple(key_value(clean[i], headers[i].casefold()) for i in match_columns)
            if all(match_key):
                if match_key in matched:
                    first = matched[match_key][0]
                    notes.append(f"Match key also in cleaned record {first}; conflicting values retained")
                    matched[match_key].append(len(audit))
                else:
                    matched[match_key] = [len(output), len(audit)]
        output.append(clean)
        changed += bool(changes)
        reviews += bool(notes)
        audit.append([source_record, "needs_review" if notes else "kept", len(output) - 1, changes, "; ".join(notes)])

    # Flag the first record of each conflicting group too, so a reviewer sees both sides.
    for group in matched.values():
        if len(group) > 2:
            entry = audit[group[1]]
            note = f"Match key shared with later record(s); conflicting values retained"
            if entry[1] == "kept":
                entry[1] = "needs_review"
                reviews += 1
            entry[4] = "; ".join(filter(None, [entry[4], note]))

    def encode(table):
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerows(table)
        return buffer.getvalue()

    created = []
    try:
        for path, table in ((destination, output), (report, audit)):
            with path.open("x", encoding="utf-8-sig", newline="") as handle:
                created.append(path)
                handle.write(encode(table))
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {"input_records": len(rows) - 1, "output_records": len(output) - 1,
            "duplicates_removed": duplicates, "blank_records_skipped": blanks,
            "kept_records_changed": changed, "kept_records_needing_review": reviews,
            "report": str(report)}


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder) / "in.csv", Path(folder) / "out.csv"
        original = ('business,phone,city,state,email\r\n'
                    'Demo Ridge,(704) 555-0182,charlotte,nc,RIDGE@EXAMPLE.COM\r\n'
                    'demo ridge,7045550182,Charlotte,NC,RIDGE@Example.com\r\n'
                    'Demo Ridge,7045550182,Charlotte,NC,other@example.com\r\n'
                    'Demo Maple,704-555-0177,pineville,NC,\r\n')
        source.write_bytes(original.encode("utf-8-sig"))
        stats = clean_csv(source, target)
        with target.open(encoding="utf-8-sig", newline="") as handle:
            cleaned = list(csv.reader(handle))
        with Path(stats["report"]).open(encoding="utf-8-sig", newline="") as handle:
            audit = list(csv.DictReader(handle))
        assert stats["output_records"] == 3 and stats["duplicates_removed"] == 1
        assert stats["kept_records_needing_review"] == 3
        assert cleaned[1] == ["Demo Ridge", "704-555-0182", "Charlotte", "NC", "RIDGE@example.com"]
        assert [r["status"] for r in audit] == ["needs_review", "duplicate_removed", "needs_review", "needs_review"]
        assert source.read_bytes() == original.encode("utf-8-sig")
        try:
            clean_csv(source, target)
        except FileExistsError:
            pass
        else:
            raise AssertionError("Existing output overwritten")
        source.write_text("A,B\n1,2,3\n", encoding="utf-8")
        try:
            clean_csv(source, Path(folder) / "bad.csv")
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed row accepted")
        assert not (Path(folder) / "bad.csv").exists()
    print("PASS: cleanup, conflict review, report, source preservation, overwrite protection")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?")
    parser.add_argument("destination", nargs="?")
    parser.add_argument("--report", help="New report filename; default OUTPUT_report.csv")
    parser.add_argument("--key", nargs="+", metavar="COLUMN", help="Match columns used to flag conflicting records")
    parser.add_argument("--reference", help="Client-provided CSV used only for exact-key enrichment")
    parser.add_argument("--add", nargs="+", metavar="COLUMN", help="New columns to add from the reference CSV")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif not args.source or not args.destination:
        parser.error("Provide source.csv and a NEW output.csv path")
    else:
        try:
            for label, value in clean_csv(args.source, args.destination, args.report, args.key, args.reference, args.add).items():
                print(f"{label}: {value}")
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            parser.exit(1, f"Cannot clean CSV: {error}\n")
