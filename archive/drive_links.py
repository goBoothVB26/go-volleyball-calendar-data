"""Convert Google Drive "share" links into direct-download URLs for use
with Google Calendar's "From URL" subscription.

Input CSV has a header row, then two columns: filename,share_link
  e.g. wpvc_schedule.ics,https://drive.google.com/file/d/1AbCdEf.../view?usp=sharing

Output CSV (printed to stdout, or written with -o) has a header row, then
three columns: filename,share_link,direct_url
  e.g. wpvc_schedule.ics,https://drive.google.com/file/d/1AbCdEf.../view?usp=sharing,https://drive.google.com/uc?export=download&id=1AbCdEf...

Usage:
  python drive_links.py links.csv [-o output.csv]

  # Or generate the input template by scanning a folder of *_schedule.ics
  # files, so you only have to paste in share_link values:
  python drive_links.py --init "G:\\My Drive\\Calendar" -o links.csv
"""

import argparse
import csv
import re
import sys
from pathlib import Path

FILE_ID_RE = re.compile(r"/d/([\w-]+)")


def extract_file_id(share_link: str) -> str:
    match = FILE_ID_RE.search(share_link)
    if not match:
        raise ValueError(f"Couldn't find a file ID in: {share_link}")
    return match.group(1)


def convert(rows: list[list[str]]) -> list[tuple[str, str, str]]:
    results = [("filename", "share_link", "direct_url")]
    for row in rows[1:]:  # skip header row
        if not row or not row[0].strip():
            continue
        filename = row[0].strip()
        share_link = row[1].strip() if len(row) > 1 else ""
        if not share_link:
            # New .ics file picked up by --init but no share link pasted in
            # yet -- keep the row so it's not lost, but skip conversion.
            print(f"WARNING: no share_link for {filename} -- paste one into links.csv", file=sys.stderr)
            results.append((filename, "", ""))
            continue
        file_id = extract_file_id(share_link)
        direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        results.append((filename, share_link, direct_url))
    return results


def write_csv_rows(rows: list[tuple], output: str | None) -> None:
    out = open(output, "w", newline="", encoding="utf-8") if output else sys.stdout
    try:
        writer = csv.writer(out)
        for row in rows:
            writer.writerow(row)
    finally:
        if output:
            out.close()


def init_template(folder: str, existing: str | None = None) -> list[tuple[str, str]]:
    """Scan `folder` for *_schedule.ics files and return (filename, share_link)
    rows. If `existing` points at a CSV already containing share_link values
    (e.g. from a previous run), those are preserved instead of being blanked
    out, so re-running --init is safe."""
    known_links: dict[str, str] = {}
    if existing and Path(existing).exists():
        with open(existing, newline="", encoding="utf-8") as f:
            for row in list(csv.reader(f))[1:]:  # skip header row
                if row and row[0].strip():
                    known_links[row[0].strip()] = row[1].strip() if len(row) > 1 else ""

    files = sorted(Path(folder).glob("*_schedule.ics"))
    return [("filename", "share_link")] + [
        (f.name, known_links.get(f.name, "")) for f in files
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", nargs="?", help="CSV of filename,share_link (with header row)")
    parser.add_argument("--init", metavar="FOLDER", help="Scan FOLDER for *_schedule.ics files and write a filename,share_link template (with header row) instead of converting")
    parser.add_argument("-o", "--output", help="Write result CSV here instead of stdout")
    args = parser.parse_args()

    if args.init:
        write_csv_rows(init_template(args.init, existing=args.output), args.output)
        return

    if not args.input_csv:
        parser.error("input_csv is required unless --init is used")

    with open(args.input_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    write_csv_rows(convert(rows), args.output)


if __name__ == "__main__":
    main()
