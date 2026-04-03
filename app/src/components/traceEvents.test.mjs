import test from 'node:test';
import assert from 'node:assert/strict';

import {
  detectTraceProtocol,
  mergeAndDedupeTraceEvents,
  normalizeTraceEvents,
  splitTraceEventsByProtocol,
} from './traceEvents.js';

test('detectTraceProtocol identifies workflow snapshot events', () => {
  assert.equal(detectTraceProtocol({ step: 'diagnosis_complete', agent: 'diagnosis' }), 'workflow_snapshot');
  assert.equal(detectTraceProtocol({ outputs: { final_disease: '灰霉病' } }), 'workflow_snapshot');
});

test('detectTraceProtocol identifies compact replay events', () => {
  assert.equal(detectTraceProtocol({ node: 'DiagnosisAgent', status: 'end' }), 'compact_replay');
  assert.equal(detectTraceProtocol({ payload: { detail: 'legacy replay' } }), 'compact_replay');
});

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
      __source: 'replay',
    },
  ]);

  assert.equal(event.traceId, 't-1');
  assert.equal(event.stage, 'DiagnosisAgent');
  assert.equal(event.status, 'start');
  assert.equal(event.title, '开始诊断');
  assert.equal(event.protocol, 'compact_replay');
  assert.equal(event.sourceHint, 'replay');
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
      __source: 'continue',
    },
  ]);

  assert.equal(event.stage, 'diagnosis_complete');
  assert.equal(event.stageCn, '诊断完成');
  assert.equal(event.agentLabel, '诊断智能体');
  assert.equal(event.status, 'decision');
  assert.equal(event.detail, '信息充分');
  assert.equal(event.protocol, 'workflow_snapshot');
  assert.equal(event.sourceHint, 'continue');
});

test('mergeAndDedupeTraceEvents only dedupes within same protocol bucket', () => {
  const merged = mergeAndDedupeTraceEvents(
    normalizeTraceEvents([
      { trace_id: 't-5', seq: 8, node: 'DiagnosisAgent', status: 'end', payload: { agent_id: 'diagnosis' }, __source: 'replay' },
    ]),
    normalizeTraceEvents([
      { trace_id: 't-5', seq: 8, step: 'diagnosis_complete', agent: 'diagnosis', outputs: { final_disease: '灰霉病' }, __source: 'continue' },
    ]),
  );

  assert.equal(merged.length, 2);
  const split = splitTraceEventsByProtocol(merged);
  assert.equal(split.workflowSnapshotEvents.length, 1);
  assert.equal(split.compactReplayEvents.length, 1);
});

test('mergeAndDedupeTraceEvents still picks richer event inside the same protocol', () => {
  const merged = mergeAndDedupeTraceEvents(
    normalizeTraceEvents([
      { trace_id: 't-6', seq: 9, step: 'treatment_complete', agent: 'treatment', __source: 'continue' },
    ]),
    normalizeTraceEvents([
      { trace_id: 't-6', seq: 9, step: 'treatment_complete', agent: 'treatment', outputs: { selected_branch: 'FAMILY' }, __source: 'continue' },
    ]),
  );

  assert.equal(merged.length, 1);
  assert.equal(merged[0].protocol, 'workflow_snapshot');
  assert.equal(merged[0].raw.outputs.selected_branch, 'FAMILY');
});
