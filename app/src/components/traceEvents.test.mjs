import test from 'node:test';
import assert from 'node:assert/strict';

import { mergeAndDedupeTraceEvents, normalizeTraceEvents } from './traceEvents.js';

test('normalizeTraceEvents supports legacy node/status events', () => {
  const [event] = normalizeTraceEvents([
    {
      trace_id: 't-1',
      seq: 1,
      ts: '2026-03-20T10:00:00.000Z',
      node: 'DiagnosisAgent',
      status: 'start',
      message: '开始诊断',
      payload: { detail: 'legacy' },
    },
  ]);

  assert.equal(event.traceId, 't-1');
  assert.equal(event.stage, 'DiagnosisAgent');
  assert.equal(event.status, 'start');
  assert.equal(event.title, '开始诊断');
});

test('normalizeTraceEvents supports step/agent events', () => {
  const [event] = normalizeTraceEvents([
    {
      trace_id: 't-2',
      seq: 2,
      ts: '2026-03-20T10:00:01.000Z',
      step: 'diagnosis_complete',
      agent: 'diagnosis',
      step_cn: '诊断完成',
      agent_cn: '诊断智能体',
      decision: { reason: '信息充分', route: 'final' },
      outputs: { summary: 'done' },
    },
  ]);

  assert.equal(event.stage, 'diagnosis_complete');
  assert.equal(event.stageCn, '诊断完成');
  assert.equal(event.agentLabel, '诊断智能体');
  assert.equal(event.status, 'decision');
  assert.equal(event.detail, '信息充分');
});

test('mergeAndDedupeTraceEvents dedupes by trace_id + seq and keeps richer event', () => {
  const existing = normalizeTraceEvents([
    { trace_id: 't-3', seq: 5, node: 'DiagnosisAgent', status: 'end' },
  ]);
  const incoming = normalizeTraceEvents([
    { trace_id: 't-3', seq: 5, node: 'DiagnosisAgent', status: 'end', message: '诊断完成', payload: { detail: 'ok' } },
    { trace_id: 't-3', seq: 6, step: 'finalize', agent: 'final', outputs: { message: 'finish' } },
  ]);

  const merged = mergeAndDedupeTraceEvents(existing, incoming);
  assert.equal(merged.length, 2);
  assert.equal(merged[0].seq, 5);
  assert.equal(merged[0].title, '诊断完成');
  assert.equal(merged[1].seq, 6);
});

test('mergeAndDedupeTraceEvents handles null node/status and fallback key', () => {
  const merged = mergeAndDedupeTraceEvents(
    [],
    normalizeTraceEvents([
      { trace_id: 't-4', ts: '2026-03-20T10:00:00.000Z', node: null, status: null, agent: 'diag' },
      { trace_id: 't-4', ts: '2026-03-20T10:00:00.000Z', node: null, status: null, agent: 'diag' },
    ]),
  );

  assert.equal(merged.length, 1);
  assert.equal(merged[0].stage, 'diag');
  assert.equal(merged[0].status, 'info');
});
