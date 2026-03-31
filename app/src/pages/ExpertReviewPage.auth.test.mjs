import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const filePath = path.resolve('src/pages/ExpertReviewPage.tsx');
const source = fs.readFileSync(filePath, 'utf8');

const authHeaderHint = '当前请求未携带专家身份，或当前账号无专家权限';

test('pending/detail/submit requests use authFetch instead of bare fetch', () => {
  assert.match(source, /authFetch\('\/api\/expert-reviews\/pending\?limit=30',\s*undefined,\s*authUser\)/);
  assert.match(source, /authFetch\(`\/api\/expert-reviews\/\$\{encodeURIComponent\(traceId\)\}`,[\s\S]*?authUser\)/);
  assert.match(source, /authFetch\(`\/api\/expert-reviews\/\$\{encodeURIComponent\(selectedTraceId\)\}\/submit`,[\s\S]*?authUser\)/);
  assert.doesNotMatch(source, /\bfetch\(\s*['"`]/);
});

test('submitReview keeps JSON content-type while using auth fetch', () => {
  assert.match(source, /headers:\s*\{\s*'Content-Type':\s*'application\/json'\s*\}/);
});

test('403 branch shows explicit auth/role error and is not silently treated as empty list', () => {
  assert.match(source, /if \(resp\.status === 403\)[\s\S]*?throw new Error\('当前请求未携带专家身份，或当前账号无专家权限'\)/);
  assert.match(source, /listError/);
  assert.match(source, /items\.length === 0/);
  assert.match(source, new RegExp(authHeaderHint));
});

test('page includes lightweight identity observability block', () => {
  assert.match(source, /当前身份：/);
  assert.match(source, /authUser\?\.userId/);
  assert.match(source, /authUser\?\.role/);
});
