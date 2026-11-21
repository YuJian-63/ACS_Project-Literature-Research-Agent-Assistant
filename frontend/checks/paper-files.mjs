import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const server = await createServer({ root, server: { middlewareMode: true, watch: null }, appType: 'custom' });
try {
  const { validatePdf } = await server.ssrLoadModule('/src/features/papers/lib/validation.ts');
  const { fileSize } = await server.ssrLoadModule('/src/shared/lib/format.ts');
  const { hasPendingPaper } = await server.ssrLoadModule('/src/features/papers/lib/selection.ts');
  assert.equal(hasPendingPaper({ status: 'uploaded' }), true);
  assert.equal(hasPendingPaper({ status: 'processing' }), true);
  assert.equal(hasPendingPaper({ status: 'ready' }), false);
  assert.equal(hasPendingPaper(null), false);
  const file = new File(['%PDF-', new Uint8Array(52_428_800 - 5)], 'Large.PDF', { type: 'application/pdf' });
  assert.equal(await validatePdf(file), null);
  const oversized = new File([file, ' '], 'oversized.pdf', { type: 'application/pdf' });
  const error = await validatePdf(oversized);
  assert.ok(error && error.includes('50') && error.includes('MB'));
  assert.ok(await validatePdf(new File(['not a PDF'], 'invalid.pdf')));
  for (const [bytes, expected] of [[0, '0 B'], [512, '512 B'], [1024, '1 KB'],
    [1048576, '1.0 MB'], [52428800, '50.0 MB'], [1073741824, '1.0 GB'], [1099511627776, '1.0 TB']]) {
    assert.equal(fileSize(bytes), expected);
  }
  console.log('PASS: PDF validation accepts 50 MB, rejects larger files, and sizes use B/KB/MB/GB/TB');
} finally {
  await server.close();
}
