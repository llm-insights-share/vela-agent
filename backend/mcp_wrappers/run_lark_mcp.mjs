#!/usr/bin/env node
/**
 * Run bundled @larksuiteoapi/lark-mcp CLI (avoids broken npx/keytar native builds).
 * Usage: node run_lark_mcp.mjs mcp -a APP_ID -s APP_SECRET ...
 */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const entry = require.resolve('@larksuiteoapi/lark-mcp/dist/cli.js');
process.argv = [process.argv[0], entry, ...process.argv.slice(2)];
await import(pathToFileURL(entry).href);
