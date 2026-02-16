#!/usr/bin/env python3
"""Test Mistral OCR on a single American Sentinel PDF."""

import sys
import os
import base64
import json
from mistralai import Mistral

API_KEY = "JyOIMLTIaikkhKeGcjqBudlNMkTpeVCJ"

def ocr_pdf(pdf_path, output_path):
    """Send a PDF to Mistral OCR and save the markdown output."""
    client = Mistral(api_key=API_KEY)

    # Upload the file first
    print(f"Uploading {os.path.basename(pdf_path)}...")
    with open(pdf_path, "rb") as f:
        uploaded = client.files.upload(
            file={"file_name": os.path.basename(pdf_path), "content": f},
            purpose="ocr"
        )
    print(f"  File ID: {uploaded.id}")

    # Get signed URL
    signed = client.files.get_signed_url(file_id=uploaded.id)

    # Run OCR
    print("Running OCR...")
    result = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": signed.url,
        },
    )

    # Save results
    print(f"  Pages processed: {len(result.pages)}")

    with open(output_path, "w") as f:
        for page in result.pages:
            f.write(f"\n\n{'='*60}\n")
            f.write(f"PAGE {page.index + 1}\n")
            f.write(f"{'='*60}\n\n")
            f.write(page.markdown)

    print(f"  Output saved to: {output_path}")

    # Also save raw JSON for inspection
    json_path = output_path.replace('.md', '.json')
    with open(json_path, "w") as f:
        json.dump(result.model_dump(), f, indent=2, default=str)
    print(f"  JSON saved to: {json_path}")

if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not pdf_path:
        # Default test: 1894 v09n01
        pdf_path = "/Users/apl/Documents/PUBLICAR/APL/English/American Sentinel (Religious Freedom)/0. American Sentinel/1. Originals/New Scan/1894/American Sentinel (1894-01-04) Volume 09, Number 01.pdf"

    output_path = "/tmp/mistral_ocr_test.md"
    ocr_pdf(pdf_path, output_path)
