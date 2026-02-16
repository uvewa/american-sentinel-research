#!/usr/bin/env python3
"""Batch OCR all American Sentinel PDFs for a given year using Mistral OCR."""

import sys
import os
import json
import glob
import time
import concurrent.futures
from mistralai import Mistral

API_KEY = "JyOIMLTIaikkhKeGcjqBudlNMkTpeVCJ"
PDF_DIR = "/Users/apl/Documents/PUBLICAR/APL/English/American Sentinel (Religious Freedom)/0. American Sentinel/1. Originals/New Scan/{year}/"
OUTPUT_DIR = "/tmp/mistral_ocr/{year}/"

def ocr_one_pdf(pdf_path, output_path):
    """OCR a single PDF and save combined markdown."""
    basename = os.path.basename(pdf_path)

    # Skip if already done
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
        print(f"  SKIP (exists): {basename}")
        return basename, "skipped"

    try:
        client = Mistral(api_key=API_KEY)

        # Upload file
        with open(pdf_path, "rb") as f:
            uploaded = client.files.upload(
                file={"file_name": basename, "content": f},
                purpose="ocr"
            )

        # Get signed URL
        signed = client.files.get_signed_url(file_id=uploaded.id)

        # Run OCR
        result = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": signed.url,
            },
        )

        # Save combined markdown
        with open(output_path, "w") as f:
            for page in result.pages:
                f.write(f"\n\n{'='*60}\n")
                f.write(f"PAGE {page.index + 1}\n")
                f.write(f"{'='*60}\n\n")
                f.write(page.markdown)

        pages = len(result.pages)
        print(f"  DONE: {basename} ({pages} pages)")
        return basename, f"done ({pages} pages)"

    except Exception as e:
        print(f"  ERROR: {basename}: {e}")
        return basename, f"error: {e}"


def main():
    year = sys.argv[1] if len(sys.argv) > 1 else "1894"
    max_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    pdf_dir = PDF_DIR.format(year=year)
    output_dir = OUTPUT_DIR.format(year=year)
    os.makedirs(output_dir, exist_ok=True)

    # Find all PDFs
    pdfs = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")))
    print(f"Found {len(pdfs)} PDFs in {pdf_dir}")
    print(f"Output: {output_dir}")
    print(f"Workers: {max_workers}")
    print()

    # Build tasks: (pdf_path, output_path)
    tasks = []
    for pdf in pdfs:
        # Extract issue number from filename for output naming
        # "American Sentinel (1894-01-04) Volume 09, Number 01.pdf"
        basename = os.path.basename(pdf)
        # Parse date and volume/number
        parts = basename.replace(".pdf", "")
        # Extract the date part
        date_start = parts.index("(") + 1
        date_end = parts.index(")")
        date_str = parts[date_start:date_end]
        # Extract volume and number
        vol_part = parts.split("Volume ")[1]
        vol_num = vol_part.split(", Number ")
        vol = int(vol_num[0])
        num_str = vol_num[1]  # may contain suffix like "10a"
        # Extract numeric part and optional suffix
        num_digits = ''.join(c for c in num_str if c.isdigit())
        num_suffix = ''.join(c for c in num_str if not c.isdigit())
        num = int(num_digits)

        out_name = f"v{vol:02d}n{num:02d}{num_suffix}_{date_str}.md"
        out_path = os.path.join(output_dir, out_name)
        tasks.append((pdf, out_path))

    # Process with thread pool
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(ocr_one_pdf, pdf, out): (pdf, out)
            for pdf, out in tasks
        }
        for future in concurrent.futures.as_completed(futures):
            name, status = future.result()
            results[name] = status

    # Summary
    print(f"\n{'='*60}")
    print(f"COMPLETE: {len(results)} PDFs processed")
    done = sum(1 for s in results.values() if s.startswith("done"))
    skipped = sum(1 for s in results.values() if s == "skipped")
    errors = sum(1 for s in results.values() if s.startswith("error"))
    print(f"  Done: {done}, Skipped: {skipped}, Errors: {errors}")

    if errors:
        print("\nErrors:")
        for name, status in sorted(results.items()):
            if status.startswith("error"):
                print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
