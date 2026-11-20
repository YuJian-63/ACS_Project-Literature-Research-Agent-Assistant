import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const server = await createServer({ root, server: { middlewareMode: true, watch: null }, appType: 'custom' });
const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
try {
  const { createUuid } = await server.ssrLoadModule('/src/shared/lib/uuid.ts');
  const secureCrypto = globalThis.crypto;
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {
    getRandomValues: secureCrypto.getRandomValues.bind(secureCrypto),
  } });
  const ids = Array.from({ length: 200 }, () => createUuid());
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  const native = secureCrypto.randomUUID();
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { randomUUID: () => native } });
  assert.equal(createUuid(), native);
  console.log('PASS: native and public-HTTP UUID paths retain cryptographic randomness and UUID v4 formatting');
} finally {
  if (original) Object.defineProperty(globalThis, 'crypto', original);
  await server.close();
}
