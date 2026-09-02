#!/usr/bin/env node
/**
 * Run bundled mcp-mail-server after applying NetEase IMAP ID patch.
 * Force-load `imap` via CJS so the prototype patch is on the cached module
 * instance that ESM `import "imap"` will reuse.
 */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

const { patchImapExport } = require('./patch_imap_id.cjs');

const mailPkg = path.dirname(require.resolve('mcp-mail-server/package.json'));
const imapPath = require.resolve('imap', { paths: [mailPkg] });
const Imap = patchImapExport(require(imapPath));
if (!Imap?.prototype?.__velaIdPatched) {
  console.error('[vela] IMAP ID patch failed to attach at', imapPath);
  process.exit(1);
}

const entry = require.resolve('mcp-mail-server/dist/index.js');
await import(pathToFileURL(entry).href);
