import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bot,
  SearchCheck,
  ShieldCheck,
  BookOpen,
  SlidersHorizontal,
  FilePenLine,
  Database,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Signal,
  Timer,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type AgentPhaseStatus = 'pending' | 'running' | 'completed' | 'error';

interface AgentCatalogItem {
  id: string;
  name: string;
  description: string;
}

interface AgentPhase extends AgentCatalogItem {
  status: AgentPhaseStatus;
  progress: number;
  detail?: string;
  startTime?: number;
  endTime?: number;
}

interface AgentWorkflowPanelProps {
  traceId?: string;
  lastConfidencePct?: number;
  traceEvents?: any[];
  onPhaseChange?: (phaseId: string) => void;
  onTraceEvent?: (payload: any) => void;
}

const ICONS: Record<string, any> = {
  parse_input: SearchCheck,
  reception: Bot,
  diagnosis: SearchCheck,
  confidence_gate: ShieldCheck,
  kb_retrieval: BookOpen,
  personalization: SlidersHorizontal,
  treatment: FilePenLine,
  prescription: FilePenLine,
  validator: ShieldCheck,
  persist: Database,
  supervisor: Bot,
  confirm_input: SearchCheck,
  final: CheckCircle2,
};

const normalizeStatus = (status: unknown): 'start' | 'progress' | 'completed' | 'error' | 'info' => {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始'].includes(text)) return 'start';
  if (['progress', 'processing', '进行中'].includes(text)) return 'progress';
  if (['end', 'done', 'completed', 'finish', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
};

const formatDuration = (start?: number, end?: number, now?: number) => {
  if (!start) return '0.00';
  return (((end ?? now ?? Date.now()) - start) / 1000).toFixed(2);
};

export function AgentWorkflowPanel({ traceId, lastConfidencePct, traceEvents, onPhaseChange, onTraceEvent }: AgentWorkflowPanelProps) {
  const [catalog, setCatalog] = useState<AgentCatalogItem[]>([]);
  const [nodeToAgent, setNodeToAgent] = useState<Record<string, string>>({});
  const [phases, setPhases] = useState<AgentPhase[]>([]);
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [now, setNow] = useState(Date.now());

  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const intervalRefs = useRef<Record<string, ReturnType<typeof setInterval> | undefined>>({});

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await fetch('/api/agents');
        const data = await resp.json();
        const agents = Array.isArray(data?.agents) ? data.agents : [];
        const mapping = data?.node_to_agent && typeof data.node_to_agent === 'object' ? data.node_to_agent : {};
        if (!alive) return;
        setCatalog(agents);
        setNodeToAgent(mapping);
        setPhases(agents.map((a: AgentCatalogItem) => ({ ...a, status: 'pending', progress: 0, detail: a.description })));
      } catch {
        if (!alive) return;
        setCatalog([]);
        setNodeToAgent({});
        setPhases([]);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!traceEvents?.length) return;
    const nodes = Array.from(new Set(traceEvents.map((e) => e?.node || e?.agent).filter(Boolean))).slice(0, 20);
    if (nodes.length > 0) console.log('[AgentWorkflowPanel] sampled trace nodes (max20):', nodes);
  }, [traceEvents]);

  const clearSim = (id: string) => {
    const h = intervalRefs.current[id];
    if (h) {
      clearInterval(h);
      intervalRefs.current[id] = undefined;
    }
  };

  const startSim = (id: string) => {
    clearSim(id);
    intervalRefs.current[id] = setInterval(() => {
      setPhases((prev: AgentPhase[]) => prev.map((p: AgentPhase) => {
        if (p.id !== id || p.status !== 'running') return p;
        return { ...p, progress: Math.min(90, p.progress + 2) };
      }));
    }, 200);
  };

  const resolveAgentId = (payload: any): string | undefined => {
    const direct = payload?.agent_id || payload?.payload?.agent_id;
    if (typeof direct === 'string' && direct) return direct;
    const node = payload?.node;
    if (typeof node === 'string' && nodeToAgent[node]) return nodeToAgent[node];
    return undefined;
  };

  const handleTraceEvent = (payload: any) => {
    onTraceEvent?.(payload);
    const agentId = resolveAgentId(payload);
    if (!agentId) return;
    const status = normalizeStatus(payload?.status);
    const message = payload?.message || payload?.payload?.message || '';
    const rawProgress = Number(payload?.payload?.progress ?? payload?.progress);

    setPhases((prev: AgentPhase[]) => {
      const idx = prev.findIndex((p) => p.id === agentId);
      if (idx < 0) return prev;
      const next = prev.map((p: AgentPhase) => ({ ...p }));
      const current = next[idx];

      if (status === 'start') {
        for (let i = 0; i < idx; i += 1) {
          if (next[i].status === 'running') {
            next[i].status = 'completed';
            next[i].progress = 100;
            next[i].endTime = Date.now();
          }
        }
        current.status = 'running';
        current.startTime = current.startTime ?? Date.now();
        current.progress = Math.max(5, current.progress);
        current.detail = message || current.description;
        onPhaseChange?.(agentId);
        startSim(agentId);
      } else if (status === 'progress') {
        current.status = current.status === 'pending' ? 'running' : current.status;
        current.startTime = current.startTime ?? Date.now();
        const p = Number.isFinite(rawProgress) ? Math.min(95, Math.max(0, rawProgress)) : Math.min(95, current.progress + 5);
        current.progress = Math.max(current.progress, p);
        if (message) current.detail = message;
        if (!intervalRefs.current[agentId]) startSim(agentId);
      } else if (status === 'completed') {
        current.status = 'completed';
        current.progress = 100;
        current.endTime = Date.now();
        current.detail = message || '处理完成';
        clearSim(agentId);
      } else if (status === 'error') {
        current.status = 'error';
        current.endTime = Date.now();
        current.detail = message || '发生错误';
        clearSim(agentId);
      }

      return next;
    });
  };

  useEffect(() => {
    if (!traceId || phases.length === 0) {
      setConnectionState('idle');
      setConnectionHint('');
      return;
    }

    setPhases((prev: AgentPhase[]) => prev.map((p: AgentPhase) => ({ ...p, status: 'pending', progress: 0, detail: p.description, startTime: undefined, endTime: undefined })));
    seenRef.current.clear();
    setConnectionState('connecting');
    setConnectionHint('正在连接追踪流...');

    if (esRef.current) esRef.current.close();
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }

    const es = new EventSource(`/api/traces/${encodeURIComponent(traceId)}/stream`);
    esRef.current = es;

    es.addEventListener('trace', (evt) => {
      const payload = JSON.parse(evt.data || '{}');
      const key = `${payload.trace_id || traceId}-${payload.seq || ''}-${payload.ts || ''}-${payload.node || ''}-${payload.status || ''}`;
      if (seenRef.current.has(key)) return;
      seenRef.current.add(key);
      handleTraceEvent(payload);
      setConnectionState('connected');
      setConnectionHint('SSE 实时连接中');
    });

    es.onerror = () => {
      setConnectionState('disconnected');
      setConnectionHint('连接已断开，尝试使用轮询补齐...');
      es.close();
      pollRef.current = setInterval(async () => {
        try {
          const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
          if (!resp.ok) return;
          const data = await resp.json();
          const list = Array.isArray(data?.events) ? data.events : [];
          list.forEach((evt: any) => {
            const payload = {
              node: evt?.node || evt?.agent,
              agent_id: evt?.agent_id || evt?.payload?.agent_id,
              status: evt?.status || evt?.step,
              message: evt?.message || evt?.step,
              payload: evt?.payload || {},
              ts: evt?.ts || evt?.timestamp,
              seq: evt?.seq,
              trace_id: traceId,
            };
            const key = `${traceId}-${payload.seq || ''}-${payload.ts || ''}-${payload.node || ''}-${payload.status || ''}`;
            if (seenRef.current.has(key)) return;
            seenRef.current.add(key);
            handleTraceEvent(payload);
          });
        } catch {
          // ignore
        }
      }, 2000);
    };

    return () => {
      es.close();
      if (pollRef.current) clearInterval(pollRef.current);
      Object.keys(intervalRefs.current).forEach(clearSim);
    };
  }, [traceId, phases.length, JSON.stringify(nodeToAgent)]);

  const totalProgress = useMemo(() => {
    if (phases.length === 0) return 0;
    const sum = phases.reduce((acc: number, p: AgentPhase) => acc + p.progress, 0);
    return Math.round(sum / phases.length);
  }, [phases]);

  const totalStart = useMemo(() => {
    const starts = phases.map((p: AgentPhase) => p.startTime).filter(Boolean) as number[];
    return starts.length ? Math.min(...starts) : undefined;
  }, [phases]);

  const totalEnd = useMemo(() => {
    const ends = phases.map((p: AgentPhase) => p.endTime).filter(Boolean) as number[];
    if (!ends.length) return undefined;
    if (phases.some((p: AgentPhase) => p.status === 'running')) return undefined;
    return Math.max(...ends);
  }, [phases]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5]">
          <Signal className="w-3 h-3 mr-1" />
          {connectionState === 'connected' ? 'SSE 已连接' : connectionState === 'connecting' ? 'SSE 连接中' : connectionState === 'disconnected' ? 'SSE 已断开' : '等待 trace'}
        </Badge>
        {connectionHint && <span className="text-xs text-white/50">{connectionHint}</span>}
        {typeof lastConfidencePct === 'number' && (
          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/30">置信度 {lastConfidencePct.toFixed(2)}%</Badge>
        )}
      </div>

      <div className="space-y-0">
        {phases.map((phase: AgentPhase, idx: number) => {
          const Icon = ICONS[phase.id] || Bot;
          const duration = formatDuration(phase.startTime, phase.endTime, now);
          return (
            <div key={phase.id} className="animate-phase-enter">
              <div className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div className={cn(
                    'w-9 h-9 rounded-full border flex items-center justify-center',
                    phase.status === 'completed' && 'bg-green-500/20 border-green-400 text-green-300',
                    phase.status === 'running' && 'bg-[#c8f7c5]/20 border-[#c8f7c5] text-[#c8f7c5] animate-phase-pulse',
                    phase.status === 'error' && 'bg-red-500/20 border-red-400 text-red-300',
                    phase.status === 'pending' && 'bg-white/5 border-white/20 text-white/50',
                  )}>
                    {phase.status === 'completed' ? <CheckCircle2 className="w-5 h-5" /> : phase.status === 'error' ? <AlertTriangle className="w-5 h-5" /> : phase.status === 'running' ? <Loader2 className="w-5 h-5 animate-spin" /> : <Icon className="w-5 h-5" />}
                  </div>
                  {idx < phases.length - 1 && (
                    <div className="w-[2px] h-10 mt-1 rounded-full bg-white/10 overflow-hidden">
                      <div className={cn('w-full transition-all duration-500', phase.status === 'completed' ? 'h-full bg-green-400 progress-shine' : 'h-0')} />
                    </div>
                  )}
                </div>
                <div className="flex-1 pb-4">
                  <div className="bg-white/5 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <h4 className="text-white font-medium">{phase.name}</h4>
                        <Badge variant="outline" className={cn('text-xs', phase.status === 'completed' && 'border-green-400/50 text-green-300', phase.status === 'running' && 'border-[#c8f7c5]/50 text-[#c8f7c5]', phase.status === 'error' && 'border-red-400/50 text-red-300', phase.status === 'pending' && 'border-white/20 text-white/60')}>{phase.status}</Badge>
                      </div>
                      <div className="text-xs text-white/50 flex items-center gap-1">
                        <Timer className="w-3 h-3" />
                        {phase.status === 'completed' ? `✓ 完成 (${duration}s)` : phase.status === 'running' ? `进行中 (${duration}s)` : '等待执行'}
                      </div>
                    </div>
                    <p className={cn('text-sm mt-2 text-white/70', phase.status === 'running' && 'animate-pulse')}>{phase.detail || phase.description}</p>
                    <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                      <div className="h-full rounded-full bg-[#c8f7c5] transition-all duration-500 progress-shine" style={{ width: `${Math.max(0, Math.min(100, phase.progress))}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <div className="flex items-center justify-between text-sm mb-2">
          <span className="text-white/70">总体进度</span>
          <span className="text-[#c8f7c5] font-mono">{totalProgress}%</span>
        </div>
        <div className="h-2 rounded-full bg-white/10 overflow-hidden">
          <div className="h-full bg-[#4ade80] transition-all duration-500 progress-shine" style={{ width: `${totalProgress}%` }} />
        </div>
        <p className="text-xs text-white/50 mt-2">总耗时：{formatDuration(totalStart, totalEnd, now)}s</p>
      </div>
    </div>
  );
}
