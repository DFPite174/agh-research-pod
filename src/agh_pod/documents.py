"""Bounded extraction with source hashes; scanned pages require explicit review."""

import hashlib
from io import BytesIO

from pypdf import PdfReader


def prepare_evidence(content, *, max_characters=25000, max_pages=100):
    if not isinstance(content, bytes) or len(content) > 25_000_000:
        raise ValueError("evidence must be bytes within25MB")
    if type(max_characters) is not int or max_characters < 1 or type(max_pages) is not int or max_pages < 1:
        raise ValueError("invalid extraction budget")
    result = {"sha256": hashlib.sha256(content).hexdigest(), "pages": [], "empty_pages": []}
    if content.startswith(b'%PDF-'):
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                raise ValueError("encrypted PDF requires separately authorized extraction")
            if len(reader.pages) > max_pages:
                raise ValueError("PDF page budget exceeded")
            for i, page in enumerate(reader.pages):
                text = (page.extract_text() or '').strip()
                result["pages"].append({"page": i+1, "text": text})
                if not text:
                    result["empty_pages"].append(i+1)
        except ValueError:
            raise
        except Exception:
            raise ValueError("unreadable PDF evidence") from None
        result["text"] = '\n\n'.join(f'[PDF page {p["page"]}]\n{p["text"]}' for p in result["pages"] if p["text"])
        result["status"] = 'NEEDS_OCR_OR_MANUAL_REVIEW' if result['empty_pages'] else 'READY'
    else:
        try:
            result["text"] = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError("evidence is not valid UTF-8 text or a readable PDF") from None
        result["status"] = 'READY'
    if len(result["text"]) > max_characters:
        raise ValueError("extracted text exceeds character budget; select a reviewed excerpt explicitly")
    return result
