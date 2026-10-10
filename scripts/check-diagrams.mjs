// Renders every ```mermaid block in a Markdown file with mermaid-cli; exits 1 if any fails.
// Usage: node scripts/check-diagrams.mjs docs/architecture.md
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const file = process.argv[2] ?? 'docs/architecture.md';
const blocks = [...readFileSync(file, 'utf8').matchAll(/```mermaid\r?\n([\s\S]*?)```/g)].map((m) => m[1]);
const dir = mkdtempSync(join(tmpdir(), 'mmd-'));
let failed = 0;
blocks.forEach((src, i) => {
  // A semicolon ends a Mermaid statement, so one inside a label renders as stray nodes without any error.
  const semi = src.split(/\r?\n/).filter((l) => l.includes(';') && !/^\s*%%/.test(l));
  if (semi.length) { failed++; console.log(`diagram ${i + 1}: FAILED, semicolon in: ${semi[0].trim()}`); return; }
  const input = join(dir, `d${i + 1}.mmd`);
  writeFileSync(input, src);
  try {
    execFileSync('npx', ['-y', '@mermaid-js/mermaid-cli@11.17.0', '-q', '-i', input, '-o', join(dir, `d${i + 1}.svg`)], { stdio: 'pipe', shell: process.platform === 'win32' });
    console.log(`diagram ${i + 1}: ok (${src.split(/\r?\n/)[src.startsWith('---') ? 4 : 0].trim()})`);
  } catch (e) {
    failed++;
    console.log(`diagram ${i + 1}: FAILED\n${String(e.stderr || e.message).slice(0, 800)}`);
  }
});
console.log(`${blocks.length} diagrams, ${failed} failed`);
process.exit(failed ? 1 : 0);
