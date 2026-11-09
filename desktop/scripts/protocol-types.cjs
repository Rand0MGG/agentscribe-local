const fs = require('node:fs');
const path = require('node:path');
const { rendererMethods } = require('../electron/protocol.cjs');
const target = path.resolve(__dirname, '../src/protocol.generated.ts');
function params(fields) {
  const entries = Object.entries(fields);
  return entries.length ? '{ ' + entries.map(([key, field]) => `${key}${field.optional ? '?' : ''}: ${field.ts || (field.type === 'object' ? 'Record<string, unknown>' : field.type)}${field.nullable ? ' | null' : ''}`).join('; ') + ' }' : 'Record<string, never>';
}
const source = '// Generated from linguaflow/desktop_contract.json. Run node scripts/protocol-types.cjs.\n' +
  "import type { Bootstrap, Settings, State, Library, Item, Page, Caption, DeletedItem, CaptionLocation, OverlayOptions, Material } from './types';\n" +
  'export type RequestParams = {\n' + Object.entries(rendererMethods).map(([name, spec]) => `  '${name}': ${params(spec.params)};`).join('\n') + '\n};\n' +
  'export type RequestResults = {\n' + Object.entries(rendererMethods).map(([name, spec]) => `  '${name}': ${spec.result};`).join('\n') + '\n};\n' +
  'export type Method = keyof RequestParams;\n' +
  'export type RequestArgs<M extends Method> = {} extends RequestParams[M] ? [params?: RequestParams[M]] : [params: RequestParams[M]];\n';
if (process.argv.includes('--check')) {
  // Git may check out text as CRLF on Windows; only line endings are equivalent.
  if (!fs.existsSync(target) || fs.readFileSync(target, 'utf8').replace(/\r\n/g, '\n') !== source) throw new Error('桌面接口类型已过期，请运行 node scripts/protocol-types.cjs。');
} else fs.writeFileSync(target, source);
