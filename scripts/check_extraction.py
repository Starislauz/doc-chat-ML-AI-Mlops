"""Check extracted document text for corruption (mid-word splits).

Regression test for the "Unof ficial / Studen t name / c ourses" class of bug:
some PDFs position every glyph individually, so naive extractors insert spaces
inside words. That corruption poisons everything downstream:

  * keyword (BM25) search can no longer match phrases or codes like "A1";
  * the LLM reads broken context and answers worse;
  * chunking splits already-mangled text.

Usage (from the project root):

    python scripts\\check_extraction.py path\\to\\file.pdf
    python scripts\\check_extraction.py eval\\test_docs        # whole folder
    python scripts\\check_extraction.py path\\to\\file.pdf --save extracted.txt

Exit code 1 if any file looks corrupted, so it can gate a release.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.document_processor import DocumentProcessor  # noqa: E402

# Below this quality score the extracted text is considered corrupted.
QUALITY_FLOOR = 0.95
# More than this many suspected fragments also counts as corrupted.
FRAGMENT_LIMIT = 5

SUPPORTED = {".pdf", ".txt", ".md", ".docx"}


def extract_text(processor: DocumentProcessor, path: Path) -> str:
    """Extract raw text using the same code path the uploader uses."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return processor._extract_pdf_text(str(path))
    if suffix in (".txt", ".md"):
        return processor._extract_text_file(str(path))
    if suffix == ".docx":
        return processor._extract_docx_text(str(path))
    raise ValueError(f"unsupported file type: {suffix}")


def check_file(processor: DocumentProcessor, path: Path, save: Path = None) -> bool:
    """Return True when the extracted text looks clean."""
    print("=" * 78)
    print(f"FILE: {path}")

    try:
        raw = extract_text(processor, path)
    except Exception as exc:
        print(f"  EXTRACTION FAILED: {exc}")
        return False

    text = processor._normalize_text(raw)
    quality = processor._text_quality(text)
    fragments = processor.find_fragments(text, limit=10)

    print(f"  characters : {len(text)}")
    print(f"  quality    : {quality:.3f}   (1.000 = no suspected splits)")
    print(f"  fragments  : {len(fragments)} found")

    if fragments:
        print("  examples   :")
        for snippet in fragments[:6]:
            print(f"    - ...{snippet}...")

    if save:
        save.write_text(text, encoding="utf-8")
        print(f"  saved full text to: {save}")

    clean = quality >= QUALITY_FLOOR and len(fragments) < FRAGMENT_LIMIT
    print(f"  verdict    : {'CLEAN' if clean else 'SUSPECTED CORRUPTION'}")
    return clean


def main():
    parser = argparse.ArgumentParser(description="Check extraction quality")
    parser.add_argument("paths", nargs="+", help="Files or folders to check")
    parser.add_argument("--save", default=None,
                        help="Save the extracted text of the first file here")
    args = parser.parse_args()

    targets = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if path.is_dir():
            targets.extend(sorted(
                p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED
            ))
        elif path.is_file():
            targets.append(path)
        else:
            print(f"Not found: {path}")

    if not targets:
        sys.exit("Nothing to check.")

    processor = DocumentProcessor()
    results = []
    for index, target in enumerate(targets):
        save = Path(args.save) if (args.save and index == 0) else None
        results.append((target, check_file(processor, target, save)))

    print("=" * 78)
    print("SUMMARY")
    for target, clean in results:
        print(f"  {'OK   ' if clean else 'BAD  '} {target.name}")

    bad = [t for t, clean in results if not clean]
    if bad:
        print(f"\n{len(bad)} file(s) look corrupted - fix extraction before "
              f"trusting retrieval on them.")
        sys.exit(1)
    print("\nAll extracted text looks clean.")


if __name__ == "__main__":
    main()
