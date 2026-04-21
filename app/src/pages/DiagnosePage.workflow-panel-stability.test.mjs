import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const filePath = path.resolve('src/pages/DiagnosePage.tsx');
const source = fs.readFileSync(filePath, 'utf8');

test('workflow panel initialEvents is memoized to avoid post-completion rebuild on render-only changes', () => {
  assert.match(source, /const workflowInitialEvents = useMemo\(/);
  assert.match(source, /initialEvents=\{workflowInitialEvents\}/);
});

test('workflow refresh token increments only at workflow-start handlers', () => {
  const matches = source.match(/setWorkflowRefreshToken\(\(prev\) => prev \+ 1\);/g) || [];
  assert.equal(matches.length, 3);
});

test('confirm success handlers do not bump workflow refresh token after terminal payload arrives', () => {
  const confirmCandidateBlock = source.match(/const handleConfirmCandidate = async \(\) => \{[\s\S]*?\n  \};/);
  assert.ok(confirmCandidateBlock);
  assert.doesNotMatch(confirmCandidateBlock[0], /setWorkflowRefreshToken\(\(prev\) => prev \+ 1\);/);

  const confirmSubmitBlock = source.match(/const handleConfirmSubmit = async \(finalDecision\?: 'use_current_result' \| 'request_expert_review'\) => \{[\s\S]*?\n  \};/);
  assert.ok(confirmSubmitBlock);
  assert.doesNotMatch(confirmSubmitBlock[0], /setWorkflowRefreshToken\(\(prev\) => prev \+ 1\);/);
});

