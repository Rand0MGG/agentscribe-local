import fs from 'node:fs';
import { marked } from 'marked';
const bytes = fs.readFileSync(process.argv[2]);
const encoding = bytes.subarray(0, 2).equals(Buffer.from([255, 254])) ? 'utf-16le'
  : bytes.subarray(0, 2).equals(Buffer.from([254, 255])) ? 'utf-16be' : 'utf-8';
const source = new TextDecoder(encoding, { fatal: true }).decode(bytes);
if (Buffer.byteLength(source) > 4 * 1024**2) throw Error('Markdown 超过 4 MiB 预算。');
process.stdout.write(JSON.stringify(marked.parse(source, { gfm: true })));
