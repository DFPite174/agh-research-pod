import hashlib
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import pytest

from agh_pod.documents import prepare_evidence


def pdf(text=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    if text:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 20 100 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_extracts_real_text_and_binds_page_to_original_hash():
    raw = pdf('Known research evidence')
    result = prepare_evidence(raw)
    assert result['status'] == 'READY'
    assert result['pages'][0]['page'] == 1
    assert 'Known research evidence' in result['text']
    assert result['sha256'] == hashlib.sha256(raw).hexdigest()


def test_image_only_pdf_does_not_become_binary_model_input():
    result = prepare_evidence(pdf())
    assert result['status'] == 'NEEDS_OCR_OR_MANUAL_REVIEW'
    assert result['text'] == ''
    assert result['empty_pages'] == [1]


def test_text_and_budget_do_not_silently_truncate():
    assert prepare_evidence(b'plain evidence')['text'] == 'plain evidence'
    with pytest.raises(ValueError, match='budget'):
        prepare_evidence(b'long text', max_characters=3)


def test_invalid_pdf_fails_without_echoing_file_body():
    with pytest.raises(ValueError, match='PDF'):
        prepare_evidence(b'%PDF-private-secret-not-a-document')
