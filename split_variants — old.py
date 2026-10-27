#!/usr/bin/env python3
"""Split a PDF collection of exam variants into separate PDF files.

The script OCRs the top part of every page, finds the page where each
variant starts (and the page where the answers section starts), and then
saves every variant as its own PDF.

Usage:
    python split_variants.py 2027_ege_phys.pdf:30
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytesseract
from pypdf import PdfReader, PdfWriter

# --------------------------------------------------------------------------
# Defaults (all of them can be overridden from the command line)
# --------------------------------------------------------------------------
DEFAULT_DPI = 150                   # render resolution; higher = slower but more accurate OCR
DEFAULT_TOP_FRACTION = 1 / 3        # share of the page height sent to OCR (1 = whole page)
DEFAULT_PSM = 11                    # Tesseract page segmentation mode (11 = sparse text)
DEFAULT_LANG = "rus"                # Tesseract language pack
DEBUG_DIR = Path("debug_ocr")
WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# --------------------------------------------------------------------------
# Regular expressions
# Letters are written as [Cyrillic + Latin look-alike] because OCR often
# confuses them (for example Cyrillic "а" and Latin "a").
# --------------------------------------------------------------------------

# Header of a variant: "Вариант" + optional number + (within 200 chars)
# either "Часть 1" or "Ответом к".
VARIANT_RE = re.compile(
    r"""
    [ВB][аa][рp][иuн][аa][нh][тt]            # the word "Вариант"
    (?:
        \s*[№N#]?\s*                          # optional spaces and a "№" / "N" / "#" sign
        ([0-9ЗзOОоlI|бbSs]{1,2})(?!\w)        # group 1: 1-2 chars of the number (digits or OCR look-alikes), not followed by a letter/digit
    )?                                        # the whole number part is optional
    [\s\S]{0,200}?                            # any chars (including line breaks), at most 200, as few as possible
    (?:
        Ч[аa]ст[ьb]\s*[1lI|]                  # "Часть 1"
      | О[тt]в[еe][тt]ом\s*к                  # or "Ответом к"
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Header of the answers section: "Ответы" followed by one of several phrases.
ANSWERS_RE = re.compile(
    r"""
    О[тt]в[еe][тt][ыy]                        # the word "Ответы"
    [\s\S]{0,10}?                             # up to 10 arbitrary chars (spaces, line breaks, OCR noise)
    (?:
        и\s+крит[еe]ри\w*\s+оц[еe]нив         # "и критерии оценивания"
      | [кk]ажд\w+\s+из\s+з[аa]д[аa]ни        # "каждое из заданий"
      | [ВB][аa][рp][иuн][аa][нh][тt]\s*[1lI|]  # "Вариант 1"
      | п[рp][аa]ви[лl]ьн\w+\s+р[еe]ш[еe]ни   # "правильное решение"
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Typical OCR confusions between letters and digits in the variant number.
DIGIT_FIX = {
    "З": "3", "з": "3",
    "O": "0", "О": "0", "о": "0",
    "l": "1", "I": "1", "|": "1",
    "б": "6", "b": "6",
    "S": "5", "s": "5",
}


# --------------------------------------------------------------------------
# 1. Command line and environment
# --------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split a PDF collection of exam variants into separate files."
    )
    parser.add_argument("jobs", nargs="+", metavar="PDF:VARIANTS",
                    help="one or more jobs, e.g. ege_phys_2027.pdf:30 ege_math_2027.pdf:36")
    # parser.add_argument("pdf", type=Path, help="path to the PDF collection")
    # parser.add_argument("variants", type=int, help="number of variants in the collection")
    parser.add_argument("-o", "--output-dir", type=Path,
                        help="output folder (default: a folder named after the PDF, next to it)")
    parser.add_argument("--tesseract-cmd",
                        help="path to tesseract executable (default: $TESSERACT_CMD, then PATH)")
    parser.add_argument("--lang", default=DEFAULT_LANG, help="Tesseract language (default: rus)")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="render DPI (default: 150)")
    parser.add_argument("--top-fraction", type=float, default=DEFAULT_TOP_FRACTION,
                        help="top part of the page to OCR, 0-1 (default: 0.33)")
    parser.add_argument("--psm", type=int, default=DEFAULT_PSM,
                        help="Tesseract page segmentation mode (default: 11)")
    parser.add_argument("--start-page", type=int, default=1,
                        help="first page to scan, 1-based (default: 1)")
    parser.add_argument("--debug", action="store_true",
                        help="save OCR images and text to ./debug_ocr and scan the whole file")
    return parser.parse_args()

def parse_job(job: str) -> tuple[Path, int]:
    """Parse 'file.pdf:30' into (Path('file.pdf'), 30). Works with Windows paths like C:\\dir\\file.pdf:30."""
    path, sep, count = job.rpartition(":")  # split on the LAST colon only
    if not sep or not count.isdigit():
        sys.exit(f"Invalid job '{job}'. Expected format: file.pdf:30")
    return Path(path), int(count)

def configure_tesseract(cmd: str | None) -> None:
    """Locate Tesseract: CLI argument > env variable > PATH > default Windows path."""
    candidate = cmd or os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not candidate and sys.platform == "win32" and Path(WINDOWS_TESSERACT).exists():
        candidate = WINDOWS_TESSERACT
    if not candidate:
        sys.exit(
            "Tesseract was not found. Install it, add it to PATH, "
            "or pass --tesseract-cmd / set TESSERACT_CMD."
        )
    pytesseract.pytesseract.tesseract_cmd = candidate


# --------------------------------------------------------------------------
# 2. Text recognition helpers
# --------------------------------------------------------------------------
def parse_number(raw: str | None) -> int | None:
    """Convert an OCR'd number (possibly with look-alike letters) to int."""
    if not raw:
        return None
    fixed = "".join(DIGIT_FIX.get(ch, ch) for ch in raw)
    return int(fixed) if fixed.isdigit() else None


def is_variant_start(text: str, expected: int) -> bool:
    """True if the text contains the header of the expected variant."""
    for match in VARIANT_RE.finditer(text):
        number = parse_number(match.group(1))
        # number not recognised -> trust the order; recognised -> must match
        if number is None or number == expected:
            return True
    return False


def ocr_page_top(page, lang: str, dpi: int, top_fraction: float, psm: int):
    """Render a PDF page and OCR its top part. Returns (cropped image, text)."""
    image = page.render(scale=dpi / 72).to_pil().convert("RGB")
    width, height = image.size
    top = image.crop((0, 0, width, int(height * top_fraction)))
    text = pytesseract.image_to_string(top, lang=lang, config=f"--psm {psm}")
    return top, text


# --------------------------------------------------------------------------
# 3. Finding where each variant starts
# --------------------------------------------------------------------------
def find_variant_starts(pdf_path: Path, total_variants: int, args: argparse.Namespace) -> dict[int, int]:
    """Return {variant_number: first_page}. Key total_variants + 1 is the answers section."""
    starts: dict[int, int] = {}
    answers_key = total_variants + 1
    expected = 1

    pdf = pdfium.PdfDocument(str(pdf_path))
    n_pages = len(pdf)
    print(f"Pages in the file: {n_pages}")

    debug_file = None
    if args.debug:
        DEBUG_DIR.mkdir(exist_ok=True)
        debug_file = open(DEBUG_DIR / "ocr_text.txt", "w", encoding="utf-8")

    try:
        for page_no in range(args.start_page, n_pages + 1):
            top, text = ocr_page_top(pdf[page_no - 1], args.lang, args.dpi,
                                     args.top_fraction, args.psm)

            if debug_file:
                top.save(DEBUG_DIR / f"page_{page_no:04d}.png")
                debug_file.write(f"===== Page {page_no} =====\n{text.strip()}\n\n")
                debug_file.flush()

            if expected <= total_variants:
                # still looking for the next variant
                if is_variant_start(text, expected):
                    starts[expected] = page_no
                    print(f"Variant {expected} -> page {page_no}")
                    expected += 1
            elif answers_key not in starts:
                # all variants found, now looking for the answers section
                if ANSWERS_RE.search(text):
                    starts[answers_key] = page_no
                    print(f"Answers -> page {page_no}")

            # outside debug mode stop as soon as everything is found
            if answers_key in starts and not args.debug:
                break
    finally:
        if debug_file:
            debug_file.close()
        pdf.close()

    return starts


# --------------------------------------------------------------------------
# 4. Writing the result
# --------------------------------------------------------------------------
def split_pdf(pdf_path: Path, starts: dict[int, int], total_variants: int, output_dir: Path) -> None:
    """Save each variant (and the answers) as a separate PDF."""
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    output_dir.mkdir(parents=True, exist_ok=True)

    keys = sorted(starts)
    boundaries = [starts[k] for k in keys] + [total_pages + 1]  # implicit end marker

    for key, first, next_start in zip(keys, boundaries, boundaries[1:]):
        last = next_start - 1
        writer = PdfWriter()
        for index in range(first - 1, last):
            writer.add_page(reader.pages[index])

        suffix = "answers" if key == total_variants + 1 else f"var{key}"
        out_path = output_dir / f"{pdf_path.stem}_{suffix}.pdf"
        with open(out_path, "wb") as out_file:
            writer.write(out_file)
        print(f"Saved: {out_path} ({last - first + 1} pages)")


# --------------------------------------------------------------------------
# 5. Entry point
# --------------------------------------------------------------------------
def process(pdf_path: Path, variants: int, args: argparse.Namespace) -> bool:
    """Split one PDF. Returns True on success."""
    if not pdf_path.is_file():
        print(f"File not found: {pdf_path}")
        return False

    starts = find_variant_starts(pdf_path, variants, args)

    missing = [v for v in range(1, variants + 1) if v not in starts]
    if missing:
        print(f"Could not find variants: {missing}. Nothing was saved for this file. "
              "Try --debug, a higher --dpi, or a larger --top-fraction.")
        return False
    if variants + 1 not in starts:
        print("Warning: answers section not found; the last variant will run to the end of the file.")

    # with several files, -o is a parent folder and each PDF gets its own subfolder
    base = args.output_dir or pdf_path.parent
    split_pdf(pdf_path, starts, variants, base / pdf_path.stem)
    return True


def main() -> None:
    args = parse_args()
    configure_tesseract(args.tesseract_cmd)

    failed = []
    for pdf_path, variants in (parse_job(job) for job in args.jobs):
        print(f"\n=== {pdf_path} ({variants} variants) ===")
        if not process(pdf_path, variants, args):
            failed.append(pdf_path.name)

    if failed:
        sys.exit(f"Failed: {', '.join(failed)}")
    print("done")

if __name__ == "__main__":
    main()
