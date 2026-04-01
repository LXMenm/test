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
