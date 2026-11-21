import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

from app.agent_bridge.contracts import SourceFile
from app.papers.pdf_parser import ParseFailure, parse_pdf
from app.sources.arxiv import ArxivError, DownloadReceipt
from app.sources.arxiv_transport import perform_request


def text_pdf(size):
    stream = b'BT /F1 12 Tf 40 700 Td (PDF size boundary evidence) Tj ET'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    body = b'%PDF-1.4\n'
    offsets = [0]
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += str(number).encode() + b' 0 obj\n' + content + b'\nendobj\n'
    entries = b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    padding = size - len(body) - len(entries) - 120
    for _ in range(3):
        position = len(body) + padding + 2
        ending = b'xref\n0 6\n0000000000 65535 f \n' + entries + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{position}\n%%EOF\n'.encode()
        padding += size - (len(body) + padding + 2 + len(ending))
    return body + b'%' + b' ' * padding + b'\n' + ending


class PDFLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf = text_pdf(52_428_800)
        if len(cls.pdf) != 52_428_800:
            raise AssertionError('Invalid boundary fixture size')

    def test_parser_accepts_pdf_at_50_mb(self):
        result = parse_pdf(self.pdf)
        self.assertEqual(result.page_count, 1)
        self.assertNotIn('chunks', result.model_dump())

    def test_parser_rejects_pdf_above_50_mb(self):
        with self.assertRaises(ParseFailure) as caught:
            parse_pdf(self.pdf + b' ')
        self.assertEqual(caught.exception.code, 'PDF_INVALID')

    def test_parser_subprocess_accepts_50_mb_with_worker_environment(self):
        from app.papers import pdf_parser

        parser = Path(pdf_parser.__file__).resolve()
        environment = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if key in os.environ}
        environment['PYTHONIOENCODING'] = 'utf-8'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'paper.pdf'
            target = Path(directory) / 'result.json'
            source.write_bytes(self.pdf)
            result = subprocess.run([sys.executable, str(parser), str(source), str(target),
                hashlib.sha256(self.pdf).hexdigest(), str(len(self.pdf))],
                env=environment, cwd=parser.parents[2], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            parsed = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(parsed['page_count'], 1)
            self.assertNotIn('chunks', parsed)

    def test_download_receipt_accepts_50_mb_but_rejects_one_more_byte(self):
        self.assertEqual(DownloadReceipt(size_bytes=52_428_800, sha256='a' * 64).size_bytes, 52_428_800)
        with self.assertRaises(ValueError):
            DownloadReceipt(size_bytes=52_428_801, sha256='a' * 64)

    def test_backend_dispatch_accepts_50_mb_source(self):
        paper_id = uuid4()
        source = SourceFile(source_id=f'local:{paper_id}@' + 'a' * 64, paper_id=paper_id,
            title='Large paper', path=f'papers/{paper_id}.pdf', sha256='a' * 64,
            size_bytes=52_428_800, page_count=1)
        self.assertEqual(source.size_bytes, 52_428_800)
        with self.assertRaises(ValueError):
            SourceFile.model_validate(source.model_dump() | {'size_bytes': 52_428_801})

    def download(self, destination, content, headers):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers=headers, stream=httpx.ByteStream(content)))
        client = httpx.Client(transport=transport)
        with patch('app.sources.arxiv_transport.httpx.Client', return_value=client):
            return perform_request('https://arxiv.org/pdf/1706.03762v1', params=None,
                destination=destination, user_agent='PDFBoundaryTests/1.0', timeout_seconds=10)

    def test_arxiv_download_accepts_50_mb_with_and_without_content_length(self):
        for headers in ({'Content-Length': '52428800'}, {}):
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / 'paper.pdf'
                response = self.download(destination, self.pdf, headers)
                self.assertEqual(response.receipt.size_bytes, 52_428_800)
                self.assertEqual(destination.stat().st_size, 52_428_800)
                self.assertEqual(response.receipt.sha256, hashlib.sha256(self.pdf).hexdigest())

    def test_arxiv_download_rejects_oversized_header_and_stream(self):
        for headers in ({'Content-Length': '52428801'}, {}):
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ArxivError) as caught:
                    self.download(Path(directory) / 'paper.pdf', self.pdf + b' ', headers)
                self.assertEqual(caught.exception.code, 'FILE_TOO_LARGE')


if __name__ == '__main__':
    unittest.main()
