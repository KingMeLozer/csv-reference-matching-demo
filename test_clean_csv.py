"""Edge-case checks for clean_csv.py. Run: python test_clean_csv.py"""
import csv
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from clean_csv import clean_csv

BASE = Path(os.environ.get("CLEAN_CSV_TEST_DIR") or tempfile.gettempdir()) / f"clean_csv_tests_{uuid.uuid4().hex[:8]}"


def new_folder():
    folder = BASE / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    return folder


def run(text, **kwargs):
    folder = new_folder()
    source = folder / "in.csv"
    source.write_bytes(text.encode("utf-8"))
    before = source.read_bytes()
    stats = clean_csv(source, folder / "out.csv", **kwargs)
    assert source.read_bytes() == before, "source changed"
    read = lambda p: list(csv.reader(Path(p).open(encoding="utf-8-sig", newline="")))
    return stats, read(folder / "out.csv"), list(csv.DictReader(Path(stats["report"]).open(encoding="utf-8-sig", newline="")))


def expect_error(text, error, **kwargs):
    folder = new_folder()
    (folder / "in.csv").write_bytes(text.encode("utf-8"))
    try:
        clean_csv(folder / "in.csv", folder / "out.csv", **kwargs)
    except error:
        assert not (folder / "out.csv").exists(), "partial output left behind"
        assert not (folder / "out_report.csv").exists(), "partial report left behind"
        return
    raise AssertionError(f"expected {error.__name__}")


# Quoted fields: commas, embedded quotes, and line breaks survive intact.
stats, out, _ = run('business,notes\r\n"Acme, LLC","He said ""hi""\nline two"\r\n')
assert out[1] == ["Acme, LLC", 'He said "hi"\nline two'], out

# Unicode: accents and non-Latin text kept; surrounding whitespace trimmed.
stats, out, _ = run("business,city\n  Café Zoë  ,SÃO PAULO\n東京 Shop,tokyo\n")
assert out[1][0] == "Café Zoë" and out[2][0] == "東京 Shop", out
assert out[1][1] == "São Paulo" and out[2][1] == "Tokyo", out

# Leading zeroes in non-phone columns are never converted to numbers.
stats, out, _ = run("sku,zip,phone\n00123,02134,7045550100\n")
assert out[1] == ["00123", "02134", "704-555-0100"], out

# Invalid phone kept as-is and flagged.
stats, out, audit = run("business,phone\nA,555-01\nB,call 7045550182\n")
assert [row[1] for row in out[1:]] == ["555-01", "call 7045550182"], out
assert all(row["status"] == "needs_review" for row in audit), audit

# Email: domain lowercased; local parts that differ only by case are NOT merged.
stats, out, audit = run("business,email\nA,Jo@EX.com\nA,jo@ex.com\n")
assert stats["duplicates_removed"] == 0 and out[1][1] == "Jo@ex.com" and out[2][1] == "jo@ex.com", out

# Malformed nonempty emails remain untouched and require human review.
stats, out, audit = run("business,email\nA,not-an-email\nC,a@\nD,a b@example.com\n")
assert [row[1] for row in out[1:]] == ["not-an-email", "a@", "a b@example.com"], out
assert all(row["status"] == "needs_review" and "Email format" in row["review_note"] for row in audit), audit

# Chosen key columns: conflicting records flagged on both sides, both retained.
stats, out, audit = run("id,name,price\n7,Widget,10\n7,Widget,12\n8,Gadget,5\n", key_columns=["ID"])
assert stats["output_records"] == 3
assert [r["status"] for r in audit] == ["needs_review", "needs_review", "kept"], audit
expect_error("id,name\n1,a\n", ValueError, key_columns=["missing"])
stats, out, audit = run("id,name\nAb1,Widget\nab1,Gadget\n", key_columns=["id"])
assert [r["status"] for r in audit] == ["kept", "kept"], audit

# Reference enrichment uses only supplied records and exact keys; conflicts stay visible.
folder = new_folder()
source, reference, target = folder / "in.csv", folder / "reference.csv", folder / "out.csv"
source.write_text("id,name,email\n001,Acme,\n002,Blue,old@example.com\n003,Gray,\n", encoding="utf-8")
reference.write_text("id,name,email,city\n001,Acme,new@example.com,Charlotte\n002,Blue,newer@example.com,Pineville\n003,Gray,a@example.com,Matthews\n003,Gray,b@example.com,Matthews\n", encoding="utf-8")
stats = clean_csv(source, target, key_columns=["id"], reference=reference, add_columns=["city"])
with target.open(encoding="utf-8-sig", newline="") as handle:
    enriched = list(csv.reader(handle))
with Path(stats["report"]).open(encoding="utf-8-sig", newline="") as handle:
    provenance = list(csv.DictReader(handle))
assert enriched == [["id", "name", "email", "city"], ["001", "Acme", "new@example.com", "Charlotte"], ["002", "Blue", "old@example.com", "Pineville"], ["003", "Gray", "", ""]], enriched
assert "reference record 1" in provenance[0]["review_note"]
assert "conflicts with reference record 2" in provenance[1]["review_note"]
assert "Multiple conflicting reference records" in provenance[2]["review_note"]
assert source.read_text(encoding="utf-8") == "id,name,email\n001,Acme,\n002,Blue,old@example.com\n003,Gray,\n"

# Case-sensitive IDs cannot borrow values from differently cased reference IDs.
folder = new_folder()
(folder / "in.csv").write_text("id,email\nAb1,\n", encoding="utf-8")
(folder / "ref.csv").write_text("id,email\nab1,wrong@example.com\n", encoding="utf-8")
stats = clean_csv(folder / "in.csv", folder / "out.csv", key_columns=["id"], reference=folder / "ref.csv")
with (folder / "out.csv").open(encoding="utf-8-sig", newline="") as handle:
    assert list(csv.reader(handle))[1][1] == ""

# US +1 notation and 10-digit notation refer to the same supplied phone key.
folder = new_folder()
(folder / "in.csv").write_text("business,phone,email\nA,7045550100,\n", encoding="utf-8")
(folder / "ref.csv").write_text("business,phone,email\nA,+1 (704) 555-0100,a@example.com\n", encoding="utf-8")
stats = clean_csv(folder / "in.csv", folder / "out.csv", reference=folder / "ref.csv")
with (folder / "out.csv").open(encoding="utf-8-sig", newline="") as handle:
    assert list(csv.reader(handle))[1][2] == "a@example.com"

# A phone field containing words cannot borrow data from a valid phone key.
folder = new_folder()
(folder / "in.csv").write_text("business,phone,email\nA,call 7045550100,\n", encoding="utf-8")
(folder / "ref.csv").write_text("business,phone,email\nA,7045550100,a@example.com\n", encoding="utf-8")
clean_csv(folder / "in.csv", folder / "out.csv", reference=folder / "ref.csv")
with (folder / "out.csv").open(encoding="utf-8-sig", newline="") as handle:
    assert list(csv.reader(handle))[1][2] == ""

# Blank and all-empty rows skipped and reported.
stats, out, audit = run("a,b\n1,2\n\n,\n")
assert stats["blank_records_skipped"] == 2 and stats["output_records"] == 1

# Spreadsheet formula risks stop delivery without changing the source or writing outputs.
for value in ('=1+1', '+1+1', '-5+1', '@example.com', '＝1+1', "'=1+1"):
    expect_error(f"business,notes\nA,{value}\n", ValueError)
stats, out, audit = run("business,balance\nA,-5\nB,+12.5\n")
assert [row[1] for row in out[1:]] == ["-5", "+12.5"], out

# Malformed input rejected without leaving output behind.
expect_error("a,b\n1,2,3\n", ValueError)
expect_error('a,b\n"unterminated,2\n', Exception)
expect_error("a,a\n1,2\n", ValueError)
expect_error("=1+1,b\nx,y\n", ValueError)
expect_error("", ValueError)

folder = new_folder()
(folder / "in.csv").write_text("id,email\n1,\n", encoding="utf-8")
(folder / "ref.csv").write_text("id,=1+1\n1,x\n", encoding="utf-8")
try:
    clean_csv(folder / "in.csv", folder / "out.csv", key_columns=["id"], reference=folder / "ref.csv")
    raise AssertionError("Formula-like reference header accepted")
except ValueError:
    assert not (folder / "out.csv").exists()

# Non-UTF-8 input rejected rather than silently garbled.
folder = new_folder()
(folder / "in.csv").write_bytes("business\nCaf\xe9\n".encode("latin-1"))
try:
    clean_csv(folder / "in.csv", folder / "out.csv")
    raise AssertionError("latin-1 accepted")
except UnicodeDecodeError:
    pass

shutil.rmtree(BASE)
print("PASS: cleanup, reference enrichment, conflicts, quoted fields, Unicode, leading zeroes, phones, formula gate, malformed input")
