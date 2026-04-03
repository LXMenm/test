import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const filePath = path.resolve('src/pages/DiagnosePage.tsx');
const source = fs.readFileSync(filePath, 'utf8');

test('resolveDisplayConfidencePct guards missing confirmed-candidate context from rendering 0%', () => {
  assert.match(source, /const missingConfirmedCandidateContext = !hasAnyCandidates\(payload\.fusion_top3\)/);
  assert.match(source, /&& !hasAnyCandidates\(payload\.text_top3\)/);
  assert.match(source, /&& !hasAnyCandidates\(imageResult\.top3\);/);
  assert.match(source, /if \(missingConfirmedCandidateContext && imageConfidencePct === 0\) {\s*return null;\s*}/);
  assert.match(source, /if \(missingConfirmedCandidateContext && imageConfidence === 0\) {\s*return null;\s*}/);
});

