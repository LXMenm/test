import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const filePath = path.resolve('src/pages/DashboardPage.tsx');
const source = fs.readFileSync(filePath, 'utf8');

test('recent diagnosis loads latest-by-trace endpoint and dedupes by traceId', () => {
  assert.match(source, /fetch\(`\/api\/events\/latest\?start=\$\{safeStart\}&end=\$\{safeEnd\}&limit=5000`\)/);
  assert.match(source, /function pickLatestEventsByTrace\(events: DiagnosisEvent\[\]\): DiagnosisEvent\[\]/);
  assert.match(source, /const recentEvents = useMemo\(\(\) => pickLatestEventsByTrace\(filteredEvents\), \[filteredEvents\]\)/);
});

test('detail panel is bound to selected trace latest snapshot rather than stale event id', () => {
  assert.match(source, /const \[selectedTraceId, setSelectedTraceId\] = useState<string \| null>\(null\);/);
  assert.match(source, /\(\) => \(selectedTraceId \? recentEvents\.find\(\(event\) => event\.traceId === selectedTraceId\) : null\) \?\? recentEvents\[0\] \?\? null/);
  assert.match(source, /onClick=\{\(\) => setSelectedTraceId\(event\.traceId\)\}/);
  assert.match(source, /selectedEvent\?\.traceId === event\.traceId/);
});

test('recent list renders one card per traceId', () => {
  assert.match(source, /key=\{event\.traceId\}/);
  assert.doesNotMatch(source, /key=\{event\.id\}/);
});

test('confidence priority uses final_confidence before image_result confidence', () => {
  const finalIdx = source.indexOf('const finalConfidence = Number(source.final_confidence);');
  const imagePctIdx = source.indexOf('const confidencePct = Number(imageResult?.confidence_pct);');
  assert.ok(finalIdx >= 0 && imagePctIdx >= 0 && finalIdx < imagePctIdx);
});

test('case tab reads latest event snapshot fields for diagnosis/treatment/verification', () => {
  assert.match(source, /const disease = selectedEvent\?\.disease \|\| '—';/);
  assert.match(source, /const treatmentObj = toRecord\(selectedEvent\.treatment\);/);
  assert.match(source, /const verification = toRecord\(selectedEvent\.raw\.verification_result\);/);
  assert.doesNotMatch(source, /const diagnosisOutputs = getNodeOutputs\(getLatestNode\(traceNodeMap, 'diagnosis'\)\)/);
});

test('kb tab prefers latest event kb_snapshot and only then falls back to trace kb node', () => {
  assert.match(source, /const eventKbSnapshot = toRecord\(selectedEvent\?\.raw\?\.kb_snapshot\);/);
  assert.match(source, /const kbOutputs = getNodeOutputs\(getLatestNode\(traceNodeMap, 'kb_retrieval'\)\);/);
});
