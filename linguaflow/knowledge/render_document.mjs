// AgentScribe owns the parent pipe; LibreOffice Kit owns its native helper and profile.
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const controller = new AbortController();
const stop = () => controller.abort(new Error('Document rendering cancelled.'));
process.stdin.resume();
process.stdin.once('end', stop);
process.once('SIGTERM', stop);
process.once('SIGINT', stop);
let converter;
try {
  const request = JSON.parse(await readFile(process.argv[3], 'utf8'));
  const { createConverter } = await import(pathToFileURL(process.argv[2]).href);
  converter = await createConverter(request.options);
  await converter.renderImages(request.render, controller.signal);
} catch (error) {
  // Provider diagnostics may contain document content; emit a bounded code only.
  process.stderr.write(String(error.code ?? 'failed').slice(0, 80));
  process.exitCode = 1;
} finally {
  if (converter) await converter.dispose();
  process.stdin.destroy();
}
