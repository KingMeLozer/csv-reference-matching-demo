# CSV reference matching demo

Self-directed portfolio work by Sina Gharavi, built with AI assistance. The three businesses and all contact details here are fictional; there was no client or paid order. This Python standard-library tool matches a source CSV to a supplied reference CSV on chosen exact keys, fills blank fields only when the reference match is unambiguous, keeps conflicting existing values, and writes a row-level change and review report. It does not search the web or invent data.

![Fictional before-and-after preview](reference_matching_preview.png)

Run the included example from this folder with Python 3.11 or newer:

```powershell
python clean_csv.py source.csv my_output.csv --reference reference.csv --key business phone --add segment
```

The command creates `my_output.csv` and `my_output_report.csv`. Compare those with `cleaned.csv` and `cleaned_report.csv`. The source and reference remain unchanged, and existing outputs are never overwritten. Choose new output names for later runs. Run `python test_clean_csv.py` for the focused checks covering matching, conflicts, malformed rows, quoted fields, Unicode, leading zeroes, phones, and the spreadsheet-formula delivery gate.

This is a small-file, human-reviewed workflow. It relies on the match keys you choose and does not verify the truth of the reference file. Ambiguous or unmatched records need your review. If a retained value could be treated as a spreadsheet formula, the tool stops without writing either output; review the reported source records before rerunning. Plain signed numbers such as `-5` remain usable. Do not put confidential customer data in a public repository.


## Excel workbook example

The same cleanup and exact-key matching are available for a **single-sheet, data-only `.xlsx` workbook**. The fictional `source.xlsx` and `reference.xlsx` in this folder produce `cleaned.xlsx` and `cleaned_xlsx_report.csv`. This is a self-directed demo, not a client order. Install the workbook dependency with `python -m pip install -r requirements.txt`, then run:

```powershell
python clean_xlsx.py source.xlsx my_excel_output.xlsx --report my_excel_report.csv --reference reference.xlsx --key business phone --add segment
python test_clean_xlsx.py
```

Choose new output names: existing files are never overwritten. The source and reference workbooks are unchanged. The Excel path accepts at most 100 data rows and 10 columns per workbook, with exactly one worksheet. It returns a new values-only workbook and a CSV change/review report; it does **not** preserve layout, styling, charts, macros, or formulas. It rejects formula/error cells, dates, formatted numbers, and other typed cells rather than silently changing their meaning. Plain text and unformatted finite numbers are accepted, and output values are stored as text to preserve leading-zero IDs. Review flagged rows before delivery. The original CSV path needs no third-party package.
