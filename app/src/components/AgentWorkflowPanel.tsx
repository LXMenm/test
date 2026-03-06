import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  BadgeCheck,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Headset,
  Loader2,
  Pill,
  Signal,
  Sparkles,
  Stethoscope,
  Timer,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

type AgentStatus = 'pending' | 'running' | 'completed' | 'error';
type FixedAgentId = 'supervisor' | 'reception' | 'diagnosis' | 'kb_retrieval' | 'treatment' | 'personalization';
type EventKind = 'agent' | 'system';

interface AgentWorkflowPanelProps {
  traceId?: string;
  confidencePct?: number;
  phaseStartMs?: number;
  refreshToken?: number;
}

interface RawTraceEvent {
  seq?: number;
  ts?: string;
  agent?: string;
  agent_id?: string;
  agent_cn?: string;
  step?: string;
  step_cn?: string;
  node?: string;
  status?: string;
  message?: string;
  payload?: Record<string, unknown>;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  decision?: Record<string, unknown>;
}

interface NormalizedEvent {
  seq: number;
  ts: string;
  tsMs?: number;
  kind: EventKind;
  agentId: string;
  agentCn: string | null;
  stepId: string | null;
  stepCn: string | null;
  inputs: Record<string, unknown> | null;
  outputs: Record<string, unknown> | null;
  decision: Record<string, unknown> | null;
  message: string | null;
  raw: RawTraceEvent;
}

interface Substep {
  substepId: string;
  text: string;
  seq: number;
}

interface AgentCardDef {
  id: FixedAgentId;
  name: string;
  description: string;
  icon: LucideIcon;
}

interface AgentCardView {
  id: FixedAgentId;
  name: string;
  description: string;
  icon: LucideIcon;
  status: AgentStatus;
  duration: string;
  keySteps: string[];
  substeps: Substep[];
}

const FIXED_AGENTS: AgentCardDef[] = [
  { id: 'supervisor', name: 'Supervisor', description: '监督与路由决策', icon: Bot },
  { id: 'reception', name: 'Reception', description: '输入接待与要素提取', icon: Headset },
  { id: 'diagnosis', name: 'Diagnosis', description: '病害诊断与置信度评估', icon: Stethoscope },
  { id: 'kb_retrieval', name: 'KB Retrieval', description: '知识库检索与信息补全', icon: BookOpen },
  { id: 'treatment', name: 'Treatment', description: '治疗方案生成与过滤解释', icon: Pill },
  { id: 'personalization', name: 'Personalization', description: '个性化约束触发与变更', icon: Sparkles },
];

const STATUS_WEIGHT: Record<AgentStatus, number> = {
  pending: 0,
  running: 1,
  completed: 2,
  error: 3,
};

const DIRECT_SET = new Set<string>([
  'supervisor',
  'reception',
  'diagnosis',
  'kb_retrieval',
  'treatment',
  'personalization',
]);

const shortText = (value: unknown, max = 120): string => {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  return raw.length <= max ? raw : `${raw.slice(0, max)}...`;
};

const parseTsMs = (ts?: string): number | undefined => {
  if (!ts) return undefined;
  const ms = Date.parse(ts);
  return Number.isFinite(ms) ? ms : undefined;
};

const toArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

const toStringArray = (value: unknown): string[] => toArray(value)
  .map((item) => String(item ?? '').trim())
  .filter(Boolean);

const normalizeStatus = (status: unknown): AgentStatus | 'info' => {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始', 'processing', 'progress', '进行中'].includes(text)) return 'running';
  if (['end', 'done', 'completed', 'finish', '结束', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
};

const mapToCardId = (agentId: string, stepId: string | null): FixedAgentId => {
  const aid = String(agentId || '').toLowerCase();
  if (DIRECT_SET.has(aid)) return aid as FixedAgentId;

  if (aid.includes('supervisor')) return 'supervisor';
  if (aid.includes('reception') || aid.includes('parse_input')) return 'reception';
  if (aid.includes('diagnosis') || aid.includes('confidence')) return 'diagnosis';
  if (aid.includes('kb') || aid.includes('retrieval') || aid.includes('retrieve')) return 'kb_retrieval';
  if (aid.includes('personalization')) return 'personalization';
  if (aid.includes('validator') || aid.includes('persist') || aid.includes('treatment') || aid.includes('prescription')) return 'treatment';

  const sid = String(stepId || '').toLowerCase();
  if (sid.includes('parse')) return 'reception';
  if (sid.includes('diagnosis') || sid.includes('confidence')) return 'diagnosis';
  if (sid.includes('kb') || sid.includes('retrieve')) return 'kb_retrieval';
  if (sid.includes('personalization')) return 'personalization';
  if (sid.includes('persist') || sid.includes('validator') || sid.includes('treatment')) return 'treatment';
  return 'supervisor';
};

const normalizeTraceEvent = (raw: RawTraceEvent): NormalizedEvent => {
  const payload = isRecord(raw.payload) ? raw.payload : null;
  const inferredInputs = isRecord(raw.inputs) ? raw.inputs : (payload && isRecord(payload['inputs']) ? payload['inputs'] as Record<string, unknown> : null);
  const inferredOutputs = isRecord(raw.outputs) ? raw.outputs : (payload && isRecord(payload['outputs']) ? payload['outputs'] as Record<string, unknown> : null);
  const inferredDecision = isRecord(raw.decision)
    ? raw.decision
    : (payload && isRecord(payload['decision']) ? payload['decision'] as Record<string, unknown> : null);

  const kind: EventKind = (raw.agent || raw.inputs || raw.outputs) ? 'agent' : 'system';
  const stepId = (raw.step || raw.status) ? String(raw.step || raw.status) : null;
  const ts = raw.ts || '';
  return {
    seq: (typeof raw.seq === 'number' && Number.isFinite(raw.seq)) ? raw.seq : Number.POSITIVE_INFINITY,
    ts,
    tsMs: parseTsMs(ts),
    kind,
    agentId: String(raw.agent_id || raw.agent || raw.node || 'unknown'),
    agentCn: raw.agent_cn ? String(raw.agent_cn) : null,
    stepId,
    stepCn: raw.step_cn ? String(raw.step_cn) : (raw.message ? String(raw.message) : null),
    inputs: inferredInputs,
    outputs: inferredOutputs,
    decision: inferredDecision,
    message: raw.message ? String(raw.message) : null,
    raw,
  };
};

const isNoiseSystemNode = (event: NormalizedEvent): boolean => {
  const aid = event.agentId.toLowerCase();
  const msg = String(event.message || '').toLowerCase();
  return aid.includes('persist')
    || aid.includes('validator')
    || msg.includes('落盘')
    || msg.includes('校验');
};

const formatDuration = (ms: number): string => {
  if (!Number.isFinite(ms) || ms <= 0) return '0.00s';
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(2)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m${(seconds - minutes * 60).toFixed(1)}s`;
};

const uniqSubsteps = (steps: Substep[], max = 5): Substep[] => {
  const dedup = new Map<string, Substep>();
  for (const step of steps) {
    if (!dedup.has(step.substepId)) dedup.set(step.substepId, step);
  }
  return [...dedup.values()]
    .sort((a, b) => a.seq - b.seq)
    .slice(-max);
};

const eventStatus = (event: NormalizedEvent): AgentStatus | 'info' => {
  if (event.kind === 'system') {
    return normalizeStatus(event.raw.status);
  }
  if (event.stepId && event.stepId.toLowerCase().endsWith('_complete')) return 'completed';
  if (event.stepId && event.stepId.toLowerCase().includes('error')) return 'error';
  return 'running';
};

const pickLatestOutputs = (events: NormalizedEvent[]): Record<string, unknown> => {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i].outputs && isRecord(events[i].outputs)) return events[i].outputs as Record<string, unknown>;
  }
  return {};
};

const asBool = (value: unknown): boolean => value === true || String(value).toLowerCase() === 'true';

const lastPart = (value: string): string => value.split(/[\\/]/).filter(Boolean).pop() || value;

export function AgentWorkflowPanel({ traceId, confidencePct, phaseStartMs, refreshToken }: AgentWorkflowPanelProps) {
  const [showSystemNodes, setShowSystemNodes] = useState(false);
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [replayedCount, setReplayedCount] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [events, setEvents] = useState<NormalizedEvent[]>([]);
  const [debugOpen, setDebugOpen] = useState<Record<FixedAgentId, boolean>>({
    supervisor: false,
    reception: false,
    diagnosis: false,
    kb_retrieval: false,
    treatment: false,
    personalization: false,
  });

  const seqEventMapRef = useRef<Map<number, NormalizedEvent>>(new Map());
  const noSeqEventsRef = useRef<NormalizedEvent[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const tickerRef = useRef<number | null>(null);

  const closeStream = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const clearTicker = useCallback(() => {
    if (tickerRef.current) {
      window.clearInterval(tickerRef.current);
      tickerRef.current = null;
    }
  }, []);

  const rebuildEvents = useCallback(() => {
    const merged = [...seqEventMapRef.current.values(), ...noSeqEventsRef.current]
      .sort((a, b) => {
        if (a.seq !== b.seq) return a.seq - b.seq;
        return (a.tsMs ?? Number.MAX_SAFE_INTEGER) - (b.tsMs ?? Number.MAX_SAFE_INTEGER);
      });
    setEvents(merged);
  }, []);

  const mergeRawEvents = useCallback((rawEvents: RawTraceEvent[]) => {
    rawEvents.forEach((raw) => {
      const normalized = normalizeTraceEvent(raw);
      if (typeof phaseStartMs === 'number' && Number.isFinite(phaseStartMs)) {
        const tsMs = normalized.tsMs;
        if (typeof tsMs === 'number' && tsMs < (phaseStartMs - 120_000)) {
          return;
        }
      }

      if (Number.isFinite(normalized.seq)) {
        // 强约束：同 seq 只保留一条，刷新/回放时覆盖旧值。
        seqEventMapRef.current.set(normalized.seq, normalized);
      } else {
        const signature = `${normalized.ts}|${normalized.agentId}|${normalized.stepId || ''}|${normalized.message || ''}`;
        const exists = noSeqEventsRef.current.some((item) => `${item.ts}|${item.agentId}|${item.stepId || ''}|${item.message || ''}` === signature);
        if (!exists) noSeqEventsRef.current.push(normalized);
      }
    });
    rebuildEvents();
  }, [phaseStartMs, rebuildEvents]);

  useEffect(() => {
    if (!traceId) {
      queueMicrotask(() => {
        setEvents([]);
        setReplayedCount(0);
        setConnectionHint('');
        setConnectionState('idle');
      });
      seqEventMapRef.current = new Map();
      noSeqEventsRef.current = [];
      closeStream();
      clearTicker();
      return;
    }

    let cancelled = false;
    seqEventMapRef.current = new Map();
    noSeqEventsRef.current = [];
    queueMicrotask(() => {
      setEvents([]);
      setReplayedCount(0);
      setConnectionState('connecting');
      setConnectionHint('正在回放历史事件...');
    });

    const openStream = () => {
      if (cancelled) return;
      closeStream();
      const es = new EventSource(`/api/traces/${encodeURIComponent(traceId)}/stream`);
      esRef.current = es;

      es.addEventListener('trace', (messageEvent) => {
        if (cancelled) return;
        const raw = JSON.parse(messageEvent.data || '{}') as RawTraceEvent;
        mergeRawEvents([raw]);
        setConnectionState('connected');
        setConnectionHint(`已回放 ${replayedCount} 条事件 + 实时连接中`);
      });

      es.onerror = () => {
        if (cancelled) return;
        setConnectionState('disconnected');
        setConnectionHint('实时连接断开');
        closeStream();
      };
    };

    const replayThenConnect = async () => {
      try {
        const response = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
        if (!response.ok) {
          setConnectionHint('历史回放失败，尝试实时连接');
          openStream();
          return;
        }
        const payload = await response.json();
        const rawEvents = Array.isArray(payload?.events) ? payload.events as RawTraceEvent[] : [];
        mergeRawEvents(rawEvents);
        setReplayedCount(rawEvents.length);
        setConnectionHint(`已回放 ${rawEvents.length} 条事件，正在连接实时流...`);
        openStream();
      } catch {
        setConnectionState('disconnected');
        setConnectionHint('历史回放异常，实时连接未建立');
      }
    };

    replayThenConnect();
    return () => {
      cancelled = true;
      closeStream();
    };
  }, [traceId, refreshToken, closeStream, clearTicker, mergeRawEvents, replayedCount]);

  const workflowDone = useMemo(() => events.some((event) => {
    const aid = event.agentId.toLowerCase();
    return aid === 'final' && eventStatus(event) === 'completed';
  }), [events]);

  useEffect(() => {
    clearTicker();
    if (!workflowDone) {
      tickerRef.current = window.setInterval(() => setNowMs(Date.now()), 200);
    }
    return clearTicker;
  }, [workflowDone, clearTicker]);

  const displayEvents = useMemo(() => {
    if (showSystemNodes) return events;
    return events.filter((event) => !isNoiseSystemNode(event));
  }, [events, showSystemNodes]);

  const diagnosisConfidencePct = useMemo(() => {
    const diagnosisEvents = displayEvents.filter((event) => mapToCardId(event.agentId, event.stepId) === 'diagnosis');
    const outputs = pickLatestOutputs(diagnosisEvents);
    const raw = Number(outputs['final_confidence'] ?? outputs['disease_confidence'] ?? outputs['confidence_pct'] ?? outputs['confidence']);
    if (!Number.isFinite(raw)) return undefined;
    return raw <= 1 ? raw * 100 : raw;
  }, [displayEvents]);

  const cardViews = useMemo<AgentCardView[]>(() => {
    const eventsByCard = FIXED_AGENTS.reduce((acc, card) => {
      acc[card.id] = displayEvents.filter((event) => mapToCardId(event.agentId, event.stepId) === card.id);
      return acc;
    }, {} as Record<FixedAgentId, NormalizedEvent[]>);

    const latestPersonalizationSystem = [...displayEvents]
      .filter((event) => event.agentId.toLowerCase() === 'personalizationagent' && event.outputs)
      .slice(-1)[0]?.outputs;

    return FIXED_AGENTS.map((card) => {
      const cardEvents = eventsByCard[card.id] || [];
      const latest = cardEvents[cardEvents.length - 1];
      const outputs = pickLatestOutputs(cardEvents);

      let status: AgentStatus = 'pending';
      cardEvents.forEach((event) => {
        const s = eventStatus(event);
        if (s === 'info') return;
        if (STATUS_WEIGHT[s] >= STATUS_WEIGHT[status]) status = s;
      });

      const startMs = cardEvents.find((event) => typeof event.tsMs === 'number')?.tsMs;
      const endMs = [...cardEvents].reverse().find((event) => typeof event.tsMs === 'number')?.tsMs;
      const duration = formatDuration(startMs ? Math.max(0, (endMs ?? nowMs) - startMs) : 0);

      let keySteps: string[] = [];
      let substeps: Substep[] = [];

      if (card.id === 'supervisor') {
        const supervisorEvents = cardEvents.filter((event) => event.decision);
        const latestSup = supervisorEvents[supervisorEvents.length - 1];
        const decision = latestSup?.decision || null;
        const reasons = toStringArray(decision?.['reasons_cn'] ?? decision?.['reasons']);
        const nextAction = String(decision?.['next_action'] ?? '').trim();
        if (nextAction === 'end') {
          keySteps = [`流程结束（${String(decision?.['reason_str'] || reasons.join(',') || 'all_required_outputs_ready')}）`];
        } else if (nextAction) {
          keySteps = [`决策：下一步 = ${nextAction}（原因：${reasons.join(',') || '无'}）`];
        }
        substeps = uniqSubsteps(supervisorEvents.map((event) => {
          const d = event.decision || {};
          const current = String((event.inputs || {})['current_step'] || 'unknown');
          const next = String(d['next_action'] || 'unknown');
          const rs = toStringArray(d['reasons_cn'] ?? d['reasons']);
          const reasonText = rs.join(',') || '无';
          return {
            substepId: `sup:${current}:${next}:${reasonText}`,
            text: `${current} → ${next}（${reasonText}）`,
            seq: event.seq,
          };
        }));
      }

      if (card.id === 'reception') {
        const latestOutputs = outputs;
        const cropType = String(latestOutputs['crop_type'] || '-');
        const imagePath = String(latestOutputs['image_path'] || latestOutputs['image_url'] || '').trim();
        const symptoms = toStringArray(latestOutputs['symptoms']);
        const missingFields = toStringArray(latestOutputs['missing_profile_fields']);
        keySteps = [
          `结构化抽取：作物=${cropType} / 图像=${imagePath ? '已识别' : '缺失'} / 症状=${symptoms.length}项 / 缺失字段=${missingFields.join(',') || '无'}（${missingFields.length}项）`,
        ];
        const followUps = toStringArray(latestOutputs['follow_up_questions']);
        substeps = uniqSubsteps([
          { substepId: 'reception:parse_input', text: '解析输入（file/symptoms/crop_type）', seq: latest?.seq ?? 0 },
          { substepId: `reception:normalize_crop:${cropType}`, text: `规范化字段（crop_type=${cropType || '-'})`, seq: latest?.seq ?? 0 },
          ...(imagePath ? [{ substepId: `reception:extract_image:${lastPart(imagePath)}`, text: `提取 image_path（${lastPart(imagePath)}）`, seq: latest?.seq ?? 0 }] : []),
          ...(missingFields.length ? [{ substepId: `reception:missing:${missingFields.join(',')}`, text: `检测缺失字段 → ${missingFields.join(',')}`, seq: latest?.seq ?? 0 }] : []),
          ...(followUps.length ? [{ substepId: `reception:followups:${followUps.length}`, text: `缺失字段映射追问（follow_up_questions=${followUps.length}条）`, seq: latest?.seq ?? 0 }] : []),
        ]);
      }

      if (card.id === 'diagnosis') {
        const disease = String(outputs['final_disease'] ?? outputs['disease_type'] ?? outputs['disease'] ?? '-');
        const conf = Number(outputs['final_confidence'] ?? outputs['disease_confidence'] ?? outputs['confidence']);
        const confidenceText = Number.isFinite(conf) ? (conf <= 1 ? (conf * 100).toFixed(2) : conf.toFixed(2)) : '-';
        const source = String(outputs['final_source'] ?? '-');
        const needConfirm = asBool(outputs['need_confirm']);
        keySteps = [`诊断：${disease} / 置信度=${confidenceText} / 来源=${source} / need_confirm=${needConfirm}`];

        const fallbackReasons = toStringArray(outputs['fallback_reason']);
        const desc = String(outputs['disease_description'] || '');
        const degraded = /(api调用失败|连接错误|timeout|连接超时|connection)/i.test(desc);
        substeps = uniqSubsteps([
          { substepId: 'diagnosis:infer_top', text: '模型推理完成（top1/top3）', seq: latest?.seq ?? 0 },
          { substepId: `diagnosis:confidence:${needConfirm ? 'low' : 'pass'}`, text: `置信度门控：${needConfirm ? '低置信度' : '通过'}${fallbackReasons.length ? `（原因：${fallbackReasons.join('；')}）` : ''}`, seq: latest?.seq ?? 0 },
          { substepId: `diagnosis:confirm:${needConfirm}`, text: `need_confirm：${needConfirm ? '是→生成二次确认候选' : '否'}`, seq: latest?.seq ?? 0 },
          { substepId: `diagnosis:personalized_hint:${degraded ? 'degraded' : 'ok'}`, text: `个性化诊断提示：${degraded ? '已降级' : '成功'}`, seq: latest?.seq ?? 0 },
        ]);
      }

      if (card.id === 'kb_retrieval') {
        const disease = String(outputs['disease'] ?? outputs['final_disease'] ?? '-');
        const actions = isRecord(outputs['actions']) ? outputs['actions'] : null;
        const ingredients = toStringArray(outputs['ingredients']);
        keySteps = [`检索：匹配到 KB 病害=${disease}（actions=${actions ? '是' : '否'} / ingredients=${ingredients.length}）`];

        const treatmentPlan = actions && isRecord(actions['treatment_plan']) ? actions['treatment_plan'] as Record<string, unknown> : {};
        const family = toStringArray(treatmentPlan['FAMILY']).length;
        const mid = toStringArray(treatmentPlan['MID']).length;
        const enterprise = toStringArray(treatmentPlan['ENTERPRISE']).length;
        substeps = uniqSubsteps([
          { substepId: 'kb:load_desc', text: '读取 diseases.json → 获取描述', seq: latest?.seq ?? 0 },
          { substepId: 'kb:load_plan', text: '读取 treatments.json → 获取 treatment/prevention', seq: latest?.seq ?? 0 },
          { substepId: `kb:load_actions:${family}:${mid}:${enterprise}`, text: `读取 actions（immediate/treatment_plan/follow_up）`, seq: latest?.seq ?? 0 },
          { substepId: `kb:load_ingredients:${ingredients.length}`, text: `读取 ingredients（${ingredients.length}项）`, seq: latest?.seq ?? 0 },
          { substepId: 'kb:pack_snapshot', text: '打包 kb_snapshot 供治疗智能体使用', seq: latest?.seq ?? 0 },
        ]);
      }

      if (card.id === 'treatment') {
        const pOutputs = (latestPersonalizationSystem && isRecord(latestPersonalizationSystem)) ? latestPersonalizationSystem : outputs;
        const selectedBranch = String(outputs['selected_branch'] ?? pOutputs['selected_branch'] ?? '-');
        const llmFailed = asBool(outputs['llm_failed'] ?? pOutputs['llm_failed']);
        const outputSource = llmFailed ? 'KB后备' : 'LLM';
        const personalizationApplied = asBool(pOutputs['personalization_applied'] ?? outputs['personalization_applied']);
        const filtered = asBool(pOutputs['filtered'] ?? outputs['filtered']);
        const filteredReasons = toStringArray(pOutputs['filtered_reasons'] ?? outputs['filtered_reasons']);
        const filteredComponents = toStringArray(pOutputs['filtered_components'] ?? outputs['filtered_components']);
        const reasons = toStringArray(pOutputs['personalization_reasons'] ?? outputs['personalization_reasons']);
        const reasonPreview = reasons.slice(0, 3).join('；') + (reasons.length > 3 ? '…' : '');

        keySteps = [
          `档位=${selectedBranch}；LLM=${llmFailed ? '失败' : '成功'}；输出来源=${outputSource}`,
          personalizationApplied ? '已应用个性化' : '未应用个性化',
          filtered
            ? `触发过滤：${filteredReasons.join('；') || '已触发'}${filteredComponents.length ? `（过滤成分：${filteredComponents.join('、')}）` : ''}`
            : '未触发过滤',
          `原因概览：${reasonPreview || '无'}`,
        ];

        const summary = isRecord(outputs['personalization_flags_summary']) ? outputs['personalization_flags_summary'] as Record<string, unknown> : {};
        const farmScale = String(summary['farm_scale'] ?? outputs['profile_farm_scale'] ?? '');
        const pesticide = String(summary['pesticide_access_level'] ?? outputs['profile_pesticide_access_level'] ?? '');
        const equipment = toStringArray(summary['equipment'] ?? outputs['profile_equipment']);
        const kbSnapshot = isRecord(outputs['kb_snapshot']) ? outputs['kb_snapshot'] as Record<string, unknown> : {};
        const kbActions = isRecord(kbSnapshot['actions']) ? kbSnapshot['actions'] as Record<string, unknown> : {};
        const immediateCount = toStringArray(kbActions['immediate']).length;
        const tp = isRecord(kbActions['treatment_plan']) ? kbActions['treatment_plan'] as Record<string, unknown> : {};
        const branchCount = toStringArray(tp['FAMILY']).length + toStringArray(tp['MID']).length + toStringArray(tp['ENTERPRISE']).length;
        const resistanceCount = toStringArray(kbActions['resistance_management']).length;
        substeps = uniqSubsteps([
          {
            substepId: `treatment:branch_select:${selectedBranch}:${farmScale}:${pesticide}:${equipment.join(',')}`,
            text: farmScale || pesticide || equipment.length
              ? `档位判定：farm_scale=${farmScale || '-'} + pesticide_access=${pesticide || '-'} + equipment=${equipment.join(',') || '-'} → ${selectedBranch}`
              : `档位判定：字段缺失，使用默认判定 → ${selectedBranch}`,
            seq: latest?.seq ?? 0,
          },
          {
            substepId: `treatment:kb_fuse:${immediateCount}:${branchCount}:${resistanceCount}`,
            text: `融合 KB actions：立即行动${immediateCount}条 / 差异化处置${branchCount}条 / 抗性管理${resistanceCount}条`,
            seq: latest?.seq ?? 0,
          },
          {
            substepId: `treatment:llm:${llmFailed ? 'failed' : 'ok'}`,
            text: `LLM 调用：${llmFailed ? `失败（${shortText(outputs['llm_failed_reason'] || 'JSON解析为空', 60)}）` : '成功'}`,
            seq: latest?.seq ?? 0,
          },
          ...(llmFailed ? [{ substepId: 'treatment:fallback', text: '使用 KB 后备方案组装', seq: latest?.seq ?? 0 }] : []),
          {
            substepId: `treatment:constraints:${filtered}`,
            text: `应用强约束：有机/禁用成分/采收窗口 → filtered=${filtered}`,
            seq: latest?.seq ?? 0,
          },
        ]);
      }

      if (card.id === 'personalization') {
        const pEvents = [...displayEvents].filter((event) => event.agentId.toLowerCase() === 'personalizationagent');
        const pOutputs = (pEvents[pEvents.length - 1]?.outputs && isRecord(pEvents[pEvents.length - 1].outputs))
          ? pEvents[pEvents.length - 1].outputs as Record<string, unknown>
          : outputs;
        const filteredReasons = toStringArray(pOutputs['filtered_reasons']);
        const filteredComponents = toStringArray(pOutputs['filtered_components']);
        const reasons = toStringArray(pOutputs['personalization_reasons']);
        const organic = asBool((isRecord(pOutputs['personalization_context']) ? (pOutputs['personalization_context'] as Record<string, unknown>)['prefer_organic'] : false));

        keySteps = [`检测到约束：有机偏好=${organic ? '是' : '否'} → 触发过滤：${filteredReasons.join('；') || '无'}${filteredComponents.length ? `（过滤成分：${filteredComponents.join('、')}）` : ''}`];
        substeps = uniqSubsteps([
          { substepId: `personalization:organic:${organic}`, text: `命中 prefer_organic → ${organic ? '开启低残留策略' : '未触发低残留策略'}`, seq: latest?.seq ?? 0 },
          ...(filteredComponents.length ? [{ substepId: `personalization:scan:${filteredComponents.join(',')}`, text: `扫描文本命中 ingredients：${filteredComponents.join('、')} → 执行替换/删除`, seq: latest?.seq ?? 0 }] : []),
          { substepId: `personalization:build:${filteredReasons.join('|')}`, text: `生成 filtered_reasons（${filteredReasons.length}条）`, seq: latest?.seq ?? 0 },
          { substepId: `personalization:reasons:${reasons.slice(0, 3).join('|')}`, text: `输出 personalization_reasons：${reasons.slice(0, 3).join('；')}${reasons.length > 3 ? '…' : ''}`, seq: latest?.seq ?? 0 },
        ]);
      }

      if (!cardEvents.length) {
        keySteps = ['暂无事件/未执行'];
        substeps = [];
      }

      return {
        ...card,
        status,
        duration,
        keySteps: keySteps.length ? keySteps : ['暂无事件/未执行'],
        substeps,
      };
    });
  }, [displayEvents, nowMs]);

  const completedCount = useMemo(() => cardViews.filter((row) => row.status === 'completed').length, [cardViews]);
  const totalProgress = Math.round((completedCount / FIXED_AGENTS.length) * 100);

  const displayConfidencePct = (typeof confidencePct === 'number' && Number.isFinite(confidencePct)) ? confidencePct : diagnosisConfidencePct;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5]">
          <Signal className="w-3 h-3 mr-1" />
          {connectionState === 'connected'
            ? 'SSE 已连接'
            : connectionState === 'connecting'
              ? 'SSE 连接中'
              : connectionState === 'disconnected'
                ? 'SSE 已断开'
                : '等待 trace'}
        </Badge>
        {connectionHint && <span className="text-xs text-white/50">{connectionHint}</span>}
        {replayedCount > 0 && <span className="text-xs text-[#c8f7c5]/70">已回放 {replayedCount} 条</span>}
        {typeof displayConfidencePct === 'number' && (
          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/30">诊断置信度 {displayConfidencePct.toFixed(2)}%</Badge>
        )}
        {workflowDone && (
          <Badge className="bg-green-500/20 text-green-300 border border-green-400/40">
            <BadgeCheck className="w-3 h-3 mr-1" />流程已结束
          </Badge>
        )}
        <button
          type="button"
          onClick={() => setShowSystemNodes((v) => !v)}
          className={cn(
            'text-xs px-2 py-1 rounded border',
            showSystemNodes
              ? 'border-[#c8f7c5]/60 text-[#c8f7c5] bg-[#c8f7c5]/10'
              : 'border-white/20 text-white/60 hover:text-white/80',
          )}
        >
          显示系统节点（校验/落盘）
        </button>
      </div>

      <div className="space-y-0">
        {cardViews.map((row, idx) => {
          const Icon = row.icon;
          const running = row.status === 'running' && !workflowDone;
          return (
            <div key={row.id} className="animate-phase-enter">
              <div className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      'w-9 h-9 rounded-full border flex items-center justify-center',
                      row.status === 'completed' && 'bg-green-500/20 border-green-400 text-green-300',
                      running && 'bg-[#c8f7c5]/20 border-[#c8f7c5] text-[#c8f7c5] animate-phase-pulse',
                      row.status === 'error' && 'bg-red-500/20 border-red-400 text-red-300',
                      row.status === 'pending' && 'bg-white/5 border-white/20 text-white/50',
                    )}
                  >
                    {row.status === 'completed'
                      ? <CheckCircle2 className="w-5 h-5" />
                      : row.status === 'error'
                        ? <AlertTriangle className="w-5 h-5" />
                        : running
                          ? <Loader2 className="w-5 h-5 animate-spin" />
                          : <Icon className="w-5 h-5" />}
                  </div>
                  {idx < cardViews.length - 1 && (
                    <div className="w-[2px] h-10 mt-1 rounded-full bg-white/10 overflow-hidden">
                      <div className={cn('w-full transition-all duration-500', row.status === 'completed' ? 'h-full bg-green-400 progress-shine' : 'h-0')} />
                    </div>
                  )}
                </div>

                <div className="flex-1 pb-4">
                  <div className="bg-white/5 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <h4 className="text-white font-medium">{row.name}</h4>
                        <Badge
                          variant="outline"
                          className={cn(
                            'text-xs',
                            row.status === 'completed' && 'border-green-400/50 text-green-300',
                            running && 'border-[#c8f7c5]/50 text-[#c8f7c5]',
                            row.status === 'error' && 'border-red-400/50 text-red-300',
                            row.status === 'pending' && 'border-white/20 text-white/60',
                          )}
                        >
                          {row.status}
                        </Badge>
                      </div>
                      <div className="text-xs text-white/50 flex items-center gap-1">
                        <Timer className="w-3 h-3" />
                        {row.status === 'completed' ? `✓ 完成 (${row.duration})` : row.status === 'running' ? `进行中 (${row.duration})` : row.status === 'error' ? `中断 (${row.duration})` : '等待执行'}
                      </div>
                    </div>

                    <p className={cn('text-sm mt-2 text-white/70', running && 'animate-pulse')}>{row.description}</p>

                    <div className="mt-3 rounded-md bg-black/25 border border-white/10 p-2">
                      <p className="text-xs text-[#c8f7c5] mb-1">关键步骤</p>
                      <ul className="space-y-1">
                        {row.keySteps.map((highlight, index) => (
                          <li key={`${row.id}-h-${index}`} className="text-xs text-white/70 flex items-start gap-1">
                            <span className="text-[#c8f7c5] mt-[2px]">•</span>
                            <span>{highlight}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <button
                      type="button"
                      className="mt-2 text-xs text-white/50 hover:text-white/80 inline-flex items-center gap-1"
                      onClick={() => setDebugOpen((prev) => ({ ...prev, [row.id]: !prev[row.id] }))}
                    >
                      {debugOpen[row.id] ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      最近子步骤（最近3~5条）
                    </button>

                    {debugOpen[row.id] && (
                      <div className="mt-1 space-y-1">
                        {row.substeps.length ? row.substeps.map((step) => (
                          <div key={step.substepId} className="text-xs text-white/50">{step.text}</div>
                        )) : <div className="text-xs text-white/40">暂无子步骤</div>}
                      </div>
                    )}

                    <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500 progress-shine"
                        style={{
                          width: `${Math.max(0, Math.min(100, row.status === 'completed' ? 100 : row.status === 'running' ? 60 : row.status === 'error' ? 100 : 0))}%`,
                          backgroundColor: row.status === 'error' ? '#f87171' : '#c8f7c5',
                        }}
                      />
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
          <span className="text-[#c8f7c5] font-mono">{completedCount}/6</span>
        </div>
        <div className="h-2 rounded-full bg-white/10 overflow-hidden">
          <div className="h-full bg-[#4ade80] transition-all duration-500 progress-shine" style={{ width: `${totalProgress}%` }} />
        </div>
      </div>
    </div>
  );
}
