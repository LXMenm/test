import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const filePath = path.resolve('src/pages/ExpertReviewPage.tsx');
const source = fs.readFileSync(filePath, 'utf8');

test('ReviewCaseDetail includes new expert detail fields for location/weather/harvest', () => {
  assert.match(source, /location\?:\s*string/);
  assert.match(source, /province\?:\s*string/);
  assert.match(source, /city\?:\s*string/);
  assert.match(source, /district\?:\s*string/);
  assert.match(source, /latitude\?:\s*number/);
  assert.match(source, /longitude\?:\s*number/);
  assert.match(source, /weather_snapshot\?:\s*string/);
  assert.match(source, /harvest_window_days\?:\s*number\s*\|\s*null/);
});

test('A section uses location/weather/harvest fallback chain and avoids base_id as location fallback', () => {
  assert.match(source, /const locationText = \(detail\.location \|\| ''\)\.trim\(\)\s*\|\|\s*regionText\s*\|\|\s*coordinateText\s*\|\|\s*\(detail\.base_name \|\| ''\)\.trim\(\)\s*\|\|\s*'-';/);
  assert.match(source, /距离采收天数/);
  assert.match(source, /detail\.harvest_window_days/);
  assert.match(source, /天气/);
  assert.match(source, /detail\.weather_snapshot/);
  assert.match(source, /\|\|\s*\(detail\.environment\s*\|\|\s*''\)\.trim\(\)/);
});

test('removed fields stay hidden in UI including supplement symptoms input', () => {
  assert.doesNotMatch(source, />规模<|规模<\/p>/);
  assert.doesNotMatch(source, />购药能力<|购药能力<\/p>/);
  assert.doesNotMatch(source, />设备<|设备<\/p>/);
  assert.doesNotMatch(source, />补充症状<|补充症状<\/Label>/);
  assert.match(source, /expert_review_supplement_symptoms:/);
});
