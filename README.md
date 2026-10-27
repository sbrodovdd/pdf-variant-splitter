# PDF Variant Splitter

**English** | [Русский](README.ru.md)

A command-line tool that splits large PDF collections of exam variants (for example, a Russian Unified State Exam book with 30 variants) into separate PDF files: one per variant plus one for the answers section.

It uses OCR to find the header of each variant, so it works on scanned books where the text cannot be extracted directly. Several collections can be processed in one run.

## How it works

1. Every page is rendered to an image with `pypdfium2`.
2. The top part of the page is recognised with Tesseract OCR.
3. Regular expressions (tolerant to typical OCR mistakes such as Cyrillic/Latin look-alike letters) look for the headers "Вариант N ... Часть 1" and "Ответы ...".
4. Variants are expected in order (1, 2, 3, ...); the number is checked when it is recognised and the order is trusted when it is not.
5. The PDF is cut at the found pages with `pypdf`.

## Requirements

- Python 3.9+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) with the **Russian** language pack (select "Russian" under "Additional language data" in the Windows installer)

## Installation

```bash
git clone https://github.com/sbrodovdd/pdf-variant-splitter.git
cd pdf-variant-splitter
python -m venv .venv
.venv\Scripts\activate        # Windows (Linux/macOS: source .venv/bin/activate)
python -m pip install -r requirements.txt
```

## Usage

Each job is written as `file.pdf:NUMBER_OF_VARIANTS`.

Suppose you have a collection of variants named `ege_phys_2027.pdf` with 30 variants:

```bash
python split_variants.py ege_phys_2027.pdf:30
```

Several files in one run:

```bash
python split_variants.py 2026_ege_math.pdf:36 2027_ege_math.pdf:36
```

Example output (illustrative):

```
=== ege_phys_2027.pdf (30 variants) ===
Pages in file: 160
Variant 1 -> page 11
Variant 2 -> page 15
...
Variant 30 -> page 143
Answers -> page 147
Saved: ege_phys_2027/ege_phys_2027_var1.pdf (4 pages)
...
Saved: ege_phys_2027/ege_phys_2027_answers.pdf (14 pages)
done
```

Every PDF gets its own folder named after it, next to the source file. If one file fails, the others are still processed and the failed ones are listed at the end.

### Options

| Option | Description | Default |
|---|---|---|
| `PDF:VARIANTS` | One or more jobs: path to the PDF and the number of variants in it | required |
| `-o`, `--output-dir` | Parent output folder (each PDF still gets its own subfolder) | next to each PDF |
| `--tesseract-cmd` | Path to the Tesseract executable | `$TESSERACT_CMD`, then `PATH`, then the default Windows path |
| `--lang` | Tesseract language | `rus` |
| `--dpi` | Render resolution | `150` |
| `--top-fraction` | Top part of the page sent to OCR (0-1) | `0.33` |
| `--psm` | Tesseract page segmentation mode | `11` |
| `--start-page` | First page to scan (1-based) | `1` |
| `--debug` | Save OCR images and text to `debug_ocr/` and scan the whole file (use with a single file) | off |

## Troubleshooting

- `No module named ...`: the dependencies are installed into a different Python than the one running the script. Run `python -m pip install -r requirements.txt` with the same interpreter (in VS Code: **Python: Select Interpreter**).
- Some variants are not found: the script skips that file without saving anything and prints the missing numbers. Run it with `--debug`, check `debug_ocr/ocr_text.txt`, and try a higher `--dpi` or a larger `--top-fraction`.

## Development

The code is fully type-annotated. To run the strict type check:

```bash
python -m pip install mypy types-pytesseract
mypy --strict split_variants.py
```

## Note on copyright

Exam collections are copyrighted material, so PDF files are not included in this repository (`*.pdf` is in `.gitignore`). Use your own copy.

## License

[MIT](LICENSE)
