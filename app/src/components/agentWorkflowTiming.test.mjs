import test from 'node:test';
import assert from 'node:assert/strict';

import {
  calcPhaseDurationsByAgent,
  isWaitingForUserInputEvent,
  parseTsMs,
  sliceCurrentPhaseEvents,
} from './agentWorkflowTiming.js';

test('sliceCurrentPhaseEvents keeps only confirm round when trace_id is reused', () => {
  const events = [
    { seq: 1, agent: 'supervisor', ts: '2026-03-20T10:00:00.000Z' },
    { seq: 2, agent: 'diagnosis', ts: '2026-03-20T10:00:01.000Z' },
    { seq: 3, node: 'AwaitUserConfirmation', status: 'end', ts: '2026-03-20T10:00:02.000Z' },
    { seq: 4, agent: 'confirm_input', ts: '2026-03-20T10:05:00.100Z' },
    { seq: 5, agent: 'supervisor', ts: '2026-03-20T10:05:00.250Z' },
    { seq: 6, agent: 'diagnosis', ts: '2026-03-20T10:05:00.400Z' },
    { seq: 7, agent: 'final', ts: '2026-03-20T10:05:00.700Z' },
  ];

  const sliced = sliceCurrentPhaseEvents(events, parseTsMs('2026-03-20T10:05:00.000Z'));

  assert.deepEqual(sliced.map((event) => event.seq), [4, 5, 6, 7]);
});

test('calcPhaseDurationsByAgent does not accumulate supervisor time across rounds', () => {
  const currentRoundEvents = [
    {
      seq: 4,
      ts: '2026-03-20T10:05:00.100Z',
      tsMs: parseTsMs('2026-03-20T10:05:00.100Z'),
      agentId: 'supervisor',
      nodeName: 'confirm_input',
      status: 'running',
      data: { agent: 'confirm_input' },
    },
    {
      seq: 5,
      ts: '2026-03-20T10:05:00.250Z',
      tsMs: parseTsMs('2026-03-20T10:05:00.250Z'),
      agentId: 'supervisor',
      nodeName: 'supervisor_route',
      status: 'running',
      data: { agent: 'supervisor' },
    },
    {
      seq: 6,
      ts: '2026-03-20T10:05:00.400Z',
      tsMs: parseTsMs('2026-03-20T10:05:00.400Z'),
      agentId: 'diagnosis',
      nodeName: 'diagnosis',
      status: 'running',
      data: { agent: 'diagnosis' },
    },
    {
      seq: 7,
      ts: '2026-03-20T10:05:00.700Z',
      tsMs: parseTsMs('2026-03-20T10:05:00.700Z'),
      agentId: 'final',
      nodeName: 'Final',
      status: 'completed',
      data: { agent: 'final' },
    },
  ];

  const durations = calcPhaseDurationsByAgent(currentRoundEvents, parseTsMs('2026-03-20T10:05:00.700Z'), true);

  assert.equal(durations.supervisor.phase1Ms, 0);
  assert.equal(durations.supervisor.phase2Ms, 300);
  assert.equal(durations.diagnosis.phase2Ms, 300);
  assert.equal(durations.final.phase2Ms, 0);
});

test('calcPhaseDurationsByAgent pauses when workflow is waiting for user supplement', () => {
  const waitingEvent = {
    seq: 3,
    ts: '2026-03-20T10:00:20.000Z',
    tsMs: parseTsMs('2026-03-20T10:00:20.000Z'),
    agentId: 'supervisor',
    nodeName: 'AwaitUserConfirmation',
    status: 'info',
    data: { status: 'waiting_for_supplement' },
  };

  const events = [
    {
      seq: 1,
      ts: '2026-03-20T10:00:00.000Z',
      tsMs: parseTsMs('2026-03-20T10:00:00.000Z'),
      agentId: 'supervisor',
      nodeName: 'supervisor_route',
      status: 'running',
      data: { agent: 'supervisor' },
    },
    {
      seq: 2,
      ts: '2026-03-20T10:00:20.000Z',
      tsMs: parseTsMs('2026-03-20T10:00:20.000Z'),
      agentId: 'diagnosis',
      nodeName: 'diagnosis',
      status: 'completed',
      data: { agent: 'diagnosis' },
    },
    waitingEvent,
  ];

  const durations = calcPhaseDurationsByAgent(events, parseTsMs('2026-03-20T10:02:20.000Z'), false);

  assert.equal(isWaitingForUserInputEvent(waitingEvent), true);
  assert.equal(durations.supervisor.phase1Ms, 20000);
  assert.equal(durations.diagnosis.phase1Ms, 0);
});
