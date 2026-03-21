export interface TraceFetchDebugState {
  updatesStopped?: boolean;
  waitingStable?: boolean;
  workflowDone?: boolean;
  hasInFlight?: boolean;
}

interface FetchTraceEventsOptions {
  signal?: AbortSignal;
  source: string;
  debugState?: TraceFetchDebugState;
}

export function buildTraceEventsUrl(traceId: string): string {
  return `/api/trace-events?trace_id=${encodeURIComponent(traceId)}`;
}

export async function fetchTraceEvents(traceId: string, options: FetchTraceEventsOptions): Promise<Response> {
  const { signal, source, debugState } = options;
  console.debug('[trace-events.fetch]', {
    traceId,
    source,
    updatesStoppedRef: debugState?.updatesStopped ?? false,
    waitingStableRef: debugState?.waitingStable ?? false,
    workflowDoneRef: debugState?.workflowDone ?? false,
    hasInFlightRequest: debugState?.hasInFlight ?? false,
  });

  if (import.meta.env.DEV) {
    console.trace('[trace-events.fetch.trace]', { traceId, source });
  }

  return fetch(buildTraceEventsUrl(traceId), { signal });
}
