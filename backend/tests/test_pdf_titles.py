import io
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.papers.pdf_parser import parse_pdf


def paper_pdf(metadata_title=None, *, heading=True):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})})})
    lines = [(10, 810, 'arXiv:2604.24212v1 [cs.SE]')]
    if heading:
        lines += [(20, 750, 'Evidence-Grounded Research'), (20, 724, 'with Language Model Agents')]
    lines += [(12, 680, 'Alice Example and Bob Example'), (10, 640, 'Abstract'),
              (10, 620, 'This paper studies reliable evidence in research systems.')]
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(f'BT /F1 {size} Tf 1 0 0 1 40 {position} Tm ({text}) Tj ET'
        for size, position, text in lines).encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    if metadata_title is not None:
        writer.add_metadata({'/Title': metadata_title})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class PDFTitleTests(unittest.TestCase):
    def test_uses_embedded_title_and_normalizes_whitespace(self):
        result = parse_pdf(paper_pdf('  A Verified\n Research Title  '))
        self.assertEqual(result.title, 'A Verified Research Title')

    def test_extracts_multiline_first_page_heading_without_metadata(self):
        self.assertEqual(parse_pdf(paper_pdf()).title,
            'Evidence-Grounded Research with Language Model Agents')

    def test_ignores_generic_metadata_and_uses_first_page_heading(self):
        for metadata in ('Untitled', 'Microsoft Word - draft.docx', '2604.24212v1.pdf', 'Main Document',
                         '2604.24212v1', 'hep-th/9901001v2'):
            with self.subTest(metadata=metadata):
                self.assertEqual(parse_pdf(paper_pdf(metadata)).title,
                    'Evidence-Grounded Research with Language Model Agents')

    def test_does_not_mistake_authors_or_body_for_a_title(self):
        self.assertIsNone(parse_pdf(paper_pdf('Untitled', heading=False)).title)

    def test_title_is_bounded_and_control_characters_are_removed(self):
        title = parse_pdf(paper_pdf('研究标题\x00\x01 ' + 'evidence ' * 60)).title
        self.assertLessEqual(len(title), 255)
        self.assertTrue(title.startswith('研究标题 '))
        self.assertNotIn('\x00', title)
        self.assertNotIn('\x01', title)

    def test_title_extraction_preserves_original_evidence(self):
        source = paper_pdf('Research title')
        original = PdfReader(io.BytesIO(source)).pages[0].extract_text().strip()
        self.assertEqual(''.join(chunk.content for chunk in parse_pdf(source).chunks), original)


if __name__ == '__main__':
    unittest.main()
