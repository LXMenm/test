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
type SubstepLevel = 'info' | 'warn' | 'error';

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

interface NormalizedTraceEvent {
  seq: number;
  ts: string;
  tsMs?: number;
  kind: EventKind;
  agentId: string;
  agentCn: string | null;
  stepKey: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  decision: Record<string, unknown>;
  message: string;
  isSystemNode: boolean;
  raw: RawTraceEvent;
}

interface Substep {
  id: string;
  text: string;
  level?: SubstepLevel;
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

const STATUS_WEIGHT: Record<AgentStatus, number> = { pending: 0, running: 1, completed: 2, error: 3 };

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
const toStringArray = (value: unknown): string[] => toArray(value).map((x) => String(x ?? '').trim()).filter(Boolean);
const asBool = (value: unknown): boolean => value === true || String(value).toLowerCase() === 'true';

const normalizeStatus = (status: unknown): AgentStatus | 'info' => {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始', 'processing', 'progress', '进行中'].includes(text)) return 'running';
  if (['end', 'done', 'completed', 'finish', '结束', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
};

const mapToCardId = (event: NormalizedTraceEvent): FixedAgentId => {
  const aid = event.agentId.toLowerCase();
  const step = event.stepKey.toLowerCase();

  if (aid.includes('supervisor')) return 'supervisor';
  if (aid.includes('reception') || step.includes('parse_input')) return 'reception';
  if (aid.includes('diagnosis') || step.includes('diagnosis') || step.includes('confidence')) return 'diagnosis';
  if (aid.includes('kb') || aid.includes('retrieval') || step.includes('kb')) return 'kb_retrieval';
  if (aid.includes('personalizationagent') || aid === 'personalization') return 'personalization';
  if (aid.includes('treatment') || aid.includes('prescription')) return 'treatment';

  return 'supervisor';
};

const isSystemNode = (agentId: string, stepKey: string, message: string): boolean => {
  const aid = agentId.toLowerCase();
  const step = stepKey.toLowerCase();
  const msg = message.toLowerCase();
  return aid.includes('validator')
    || aid.includes('persist')
    || aid.includes('confirmflow')
    || step.includes('validator')
    || step.includes('persist')
    || step.includes('confirmflow')
    || msg.includes('校验')
    || msg.includes('落盘');
};

const normalizeTraceEvent = (evt: RawTraceEvent): NormalizedTraceEvent => {
  const payload = isRecord(evt.payload) ? evt.payload : {};
  const inputs = isRecord(evt.inputs)
    ? evt.inputs
    : (isRecord(payload.inputs) ? payload.inputs as Record<string, unknown> : {});
  const outputs = isRecord(evt.outputs)
    ? evt.outputs
    : (isRecord(payload.outputs) ? payload.outputs as Record<string, unknown> : payload);
  const decision = isRecord(evt.decision)
    ? evt.decision
    : (isRecord(payload.decision) ? payload.decision as Record<string, unknown> : {});

  const kind: EventKind = (evt.agent || evt.inputs || evt.outputs) ? 'agent' : 'system';
  const seq = typeof evt.seq === 'number' && Number.isFinite(evt.seq) ? evt.seq : Number.POSITIVE_INFINITY;
  const ts = String(evt.ts || '');
  const stepKey = String(evt.step || evt.status || evt.node || 'event');
  const agentId = String(evt.agent_id || evt.agent || evt.node || 'unknown');
  const message = shortText(evt.step_cn || evt.message || String(payload.message || stepKey), 180);

  return {
    seq,
    ts,
    tsMs: parseTsMs(ts),
    kind,
    agentId,
    agentCn: evt.agent_cn ? String(evt.agent_cn) : null,
    stepKey,
    inputs,
    outputs,
    decision,
    message,
    isSystemNode: isSystemNode(agentId, stepKey, message),
    raw: evt,
  };
};

const stableEventKey = (e: NormalizedTraceEvent): string => {
  const outSig = JSON.stringify(e.outputs || {}).slice(0, 160);
  return `${e.agentId}|${e.stepKey}|${e.ts}|${outSig}|${e.message}`;
};

const dedupeEvents = (events: NormalizedTraceEvent[]): NormalizedTraceEvent[] => {
  const seqMap = new Map<number, NormalizedTraceEvent>();
  const keyMap = new Map<string, NormalizedTraceEvent>();

  events.forEach((event) => {
    if (Number.isFinite(event.seq)) {
      // seq 优先去重：同 seq 只保留最新
      seqMap.set(event.seq, event);
      return;
    }
    keyMap.set(stableEventKey(event), event);
  });

  return [...seqMap.values(), ...keyMap.values()].sort((a, b) => {
    if (a.seq !== b.seq) return a.seq - b.seq;
    return (a.tsMs ?? Number.MAX_SAFE_INTEGER) - (b.tsMs ?? Number.MAX_SAFE_INTEGER);
  });
};

const uniqSubsteps = (substeps: Substep[], min = 3, max = 5): Substep[] => {
  const dedup = new Map<string, Substep>();
  substeps.forEach((item) => {
    dedup.set(item.id, item); // 同 id 保留最新
  });
  const ordered = [...dedup.values()].sort((a, b) => a.seq - b.seq);
  if (ordered.length <= max) return ordered;
  return ordered.slice(-Math.max(min, max));
};

const formatDuration = (ms: number): string => {
  if (!Number.isFinite(ms) || ms <= 0) return '0.00s';
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(2)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m${(seconds - minutes * 60).toFixed(1)}s`;
};

const eventStatus = (event: NormalizedTraceEvent): AgentStatus | 'info' => {
  const fromRaw = normalizeStatus(event.raw.status);
  if (fromRaw !== 'info') return fromRaw;
  const step = event.stepKey.toLowerCase();
  if (step.endsWith('_complete') || step.includes('complete') || step.includes('finish')) return 'completed';
  if (step.includes('error') || step.includes('fail')) return 'error';
  return event.kind === 'agent' ? 'running' : 'info';
};

const detectDegradedReason = (text: string): string | null => {
  if (!text) return null;
  const pairs: Array<{ k: RegExp; reason: string }> = [
    { k: /api调用失败/i, reason: 'API调用失败' },
    { k: /connection/i, reason: '连接异常' },
    { k: /access denied/i, reason: '访问被拒绝' },
    { k: /timeout|timed out|超时/i, reason: '请求超时' },
  ];
  const hit = pairs.find((item) => item.k.test(text));
  return hit ? hit.reason : null;
};

const collectSystemEvents = (events: NormalizedTraceEvent[]): Substep[] => {
  return events
    .filter((event) => event.isSystemNode)
    .map((event) => ({
      id: `system:${event.seq}:${event.agentId}:${event.stepKey}`,
      text: `${event.agentId} · ${event.message || event.stepKey}`,
      seq: event.seq,
      level: 'info',
    }));
};

const buildCardsFromEvents = (normalizedEvents: NormalizedTraceEvent[], showSystemNodes: boolean, nowMs: number): { cards: AgentCardView[]; systemSubsteps: Substep[] } => {
  const mainEvents = normalizedEvents.filter((event) => !event.isSystemNode || event.agentId.toLowerCase().includes('personalizationagent'));

  const eventsByCard = FIXED_AGENTS.reduce((acc, card) => {
    acc[card.id] = mainEvents.filter((event) => mapToCardId(event) === card.id);
    return acc;
  }, {} as Record<FixedAgentId, NormalizedTraceEvent[]>);

  const systemSubsteps = showSystemNodes ? uniqSubsteps(collectSystemEvents(normalizedEvents), 3, 8) : [];

  const cards = FIXED_AGENTS.map((card): AgentCardView => {
    const cardEvents = eventsByCard[card.id] || [];
    const latest = cardEvents[cardEvents.length - 1];
    const outputs = latest?.outputs || {};
    const inputs = latest?.inputs || {};

    let status: AgentStatus = 'pending';
    cardEvents.forEach((event) => {
      const s = eventStatus(event);
      if (s !== 'info' && STATUS_WEIGHT[s] >= STATUS_WEIGHT[status]) status = s;
    });

    const startTs = cardEvents.find((event) => typeof event.tsMs === 'number')?.tsMs;
    const endTs = [...cardEvents].reverse().find((event) => typeof event.tsMs === 'number')?.tsMs;
    const duration = formatDuration(startTs ? Math.max(0, (endTs ?? nowMs) - startTs) : 0);

    let keySteps: string[] = ['暂无事件/未执行'];
    let substeps: Substep[] = [];

    if (card.id === 'supervisor' && cardEvents.length) {
      const decision = latest?.decision || {};
      const nextAction = String(decision.next_action || outputs.next_action || '').trim();
      const reasons = toStringArray(decision.reasons_cn ?? decision.reasons);
      keySteps = [
        nextAction === 'end'
          ? `流程结束（${String(decision.reason_str || reasons.join(',') || 'all_required_outputs_ready')}）`
          : `决策：下一步 = ${nextAction || 'unknown'}（原因：${reasons.join(',') || '无'}）`,
      ];

      substeps = uniqSubsteps(cardEvents.filter((event) => Object.keys(event.decision).length > 0).map((event) => {
        const d = event.decision;
        const current = String(event.inputs.current_step || 'unknown');
        const next = String(d.next_action || 'unknown');
        const rs = toStringArray(d.reasons_cn ?? d.reasons);
        return {
          id: `${current}|${next}|${rs.join(',')}`,
          text: `${current} → ${next}（${rs.join(',') || '无'}）`,
          seq: event.seq,
        };
      }), 3, 5);
    }

    if (card.id === 'reception' && cardEvents.length) {
      const cropType = String(outputs.crop_type ?? inputs.crop_type ?? '未知');
      const imagePath = String(outputs.image_path ?? outputs.image_url ?? inputs.file ?? '').trim();
      const symptoms = toStringArray(outputs.symptoms ?? inputs.symptoms);
      const missingFields = toStringArray(outputs.missing_profile_fields);
      keySteps = [`结构化抽取：作物=${cropType} / 图像=${imagePath ? '已识别' : '缺失'} / 症状=${symptoms.length}项 / 缺失字段=${missingFields.join(',') || '无'}（${missingFields.length}项）`];

      const lookaheadSupervisor = mainEvents.find((event) => event.seq > (latest?.seq ?? 0) && mapToCardId(event) === 'supervisor');
      const followUps = toStringArray(outputs.follow_up_questions ?? lookaheadSupervisor?.inputs.follow_up_questions);

      substeps = uniqSubsteps([
        ...(Object.keys(inputs).length ? [{ id: `parse_input:${latest.seq}`, text: '解析输入（crop_type/symptoms/file）', seq: latest.seq }] : []),
        ...(cropType ? [{ id: `normalize:${cropType}`, text: `规范化字段（crop_type=${cropType}）`, seq: latest.seq }] : []),
        { id: `extract_image:${imagePath ? 'ok' : 'missing'}`, text: `提取 image_path：${imagePath ? '已生成' : '缺失'}`, seq: latest.seq, level: (imagePath ? 'info' : 'warn') as SubstepLevel },
        ...(missingFields.length ? [{ id: `missing_fields:${missingFields.join(',')}`, text: `检测缺失字段 → ${missingFields.join(',')}`, seq: latest.seq, level: 'warn' as SubstepLevel }] : []),
        ...(followUps.length ? [{ id: `map_followup:${followUps.length}`, text: `缺失字段映射追问（${followUps.length}条）`, seq: latest.seq }] : []),
      ], 3, 5);
    }

    if (card.id === 'diagnosis' && cardEvents.length) {
      const disease = String(outputs.final_disease ?? outputs.disease_type ?? outputs.disease ?? '未知');
      const confRaw = Number(outputs.final_confidence ?? outputs.disease_confidence ?? outputs.confidence);
      const conf = Number.isFinite(confRaw) ? (confRaw <= 1 ? `${(confRaw * 100).toFixed(2)}%` : `${confRaw.toFixed(2)}%`) : '-';
      const source = String(outputs.final_source ?? 'unknown');
      const needConfirm = asBool(outputs.need_confirm);
      keySteps = [`诊断：病害=${disease} / 置信度=${conf} / 来源=${source} / need_confirm=${needConfirm ? '是' : '否'}`];

      const fallbackReasons = toStringArray(outputs.fallback_reason);
      const degradedReason = detectDegradedReason(String(outputs.disease_description ?? outputs.detail ?? ''));
      substeps = uniqSubsteps([
        { id: 'infer', text: '模型推理完成（top1/top3）', seq: latest.seq },
        { id: `gate:${needConfirm ? 'low' : 'pass'}`, text: `置信度门控：${needConfirm ? '低置信度' : '通过'}${fallbackReasons.length ? `（原因：${fallbackReasons.join('；')}）` : ''}`, seq: latest.seq, level: (needConfirm ? 'warn' : 'info') as SubstepLevel },
        { id: `confirm:${needConfirm}`, text: needConfirm ? 'need_confirm=是，建议二次确认' : 'need_confirm=否', seq: latest.seq, level: (needConfirm ? 'warn' : 'info') as SubstepLevel },
        { id: `personalized_hint:${degradedReason || 'ok'}`, text: degradedReason ? `个性化诊断提示：已降级（${degradedReason}）` : '个性化诊断提示：成功', seq: latest.seq, level: (degradedReason ? 'warn' : 'info') as SubstepLevel },
      ], 3, 5);
    }

    if (card.id === 'kb_retrieval' && cardEvents.length) {
      const disease = String(outputs.disease ?? outputs.final_disease ?? '未知');
      const actions = isRecord(outputs.actions) ? outputs.actions : null;
      const ingredients = toStringArray(outputs.ingredients);
      keySteps = [`检索：命中 KB=${disease}（actions=${actions ? '是' : '否'} / ingredients=${ingredients.length}）`];

      substeps = uniqSubsteps([
        { id: `load_desc:${latest.seq}`, text: '读取 diseases.json → 获取描述', seq: latest.seq },
        { id: `load_plan:${latest.seq}`, text: '读取 treatments.json → 获取 treatment/prevention', seq: latest.seq },
        ...(actions ? [{ id: `load_actions:${latest.seq}`, text: '读取 actions（immediate + treatment_plan 三档 + follow_up）', seq: latest.seq }] : []),
        { id: `load_ingredients:${ingredients.length}`, text: `读取 ingredients（${ingredients.length}项）`, seq: latest.seq },
        { id: `pack_snapshot:${latest.seq}`, text: '打包 kb_snapshot → 供治疗智能体使用', seq: latest.seq },
      ], 3, 5);
    }

    if (card.id === 'treatment' && cardEvents.length) {
      const pEvent = [...mainEvents].reverse().find((event) => event.agentId.toLowerCase().includes('personalizationagent'));
      const pOut = pEvent?.outputs || {};

      const selectedBranch = String(outputs.selected_branch || pOut.selected_branch || 'unknown');
      const llmFailed = asBool(outputs.llm_failed);
      const outputSource = llmFailed ? 'KB后备' : 'LLM';
      const personalizationApplied = asBool(outputs.personalization_applied ?? pOut.personalization_applied);
      const filtered = asBool(pOut.filtered ?? outputs.filtered);
      const filteredReasons = toStringArray(pOut.filtered_reasons ?? outputs.filtered_reasons);
      const filteredComponents = toStringArray(pOut.filtered_components ?? outputs.filtered_components);
      const reasons = [...new Set(toStringArray(pOut.personalization_reasons ?? outputs.personalization_reasons))];
      const reasonsPreview = `${reasons.slice(0, 3).join('；')}${reasons.length > 3 ? '…' : ''}`;

      keySteps = [
        `档位=${selectedBranch}；LLM=${llmFailed ? '失败' : '成功'}；输出来源=${outputSource}`,
        `已应用个性化：${personalizationApplied ? '是' : '否'}`,
        filtered
          ? `触发过滤：${filteredReasons.join('；') || '已触发'}${filteredComponents.length ? `（过滤成分：${filteredComponents.join('、')}）` : ''}`
          : '未触发过滤',
        `原因概览：${reasonsPreview || '无'}`,
        ...(!filtered && filteredReasons.length ? ['（提示：filtered_reasons 存在但 filtered=false，可能为后端一致性问题）'] : []),
      ];

      const summary = isRecord(pOut.personalization_flags_summary)
        ? pOut.personalization_flags_summary as Record<string, unknown>
        : (isRecord(outputs.personalization_flags_summary) ? outputs.personalization_flags_summary as Record<string, unknown> : {});
      const farmScale = String(summary.farm_scale || '');
      const pesticideAccess = String(summary.pesticide_access_level || '');
      const equipment = toStringArray(summary.equipment);

      const kbSnapshot = isRecord(outputs.kb_snapshot) ? outputs.kb_snapshot as Record<string, unknown> : {};
      const kbActions = isRecord(kbSnapshot.actions) ? kbSnapshot.actions as Record<string, unknown> : {};
      const immediate = toStringArray(kbActions.immediate).length;
      const tp = isRecord(kbActions.treatment_plan) ? kbActions.treatment_plan as Record<string, unknown> : {};
      const diff = toStringArray(tp.FAMILY).length + toStringArray(tp.MID).length + toStringArray(tp.ENTERPRISE).length;
      const resist = toStringArray(kbActions.resistance_management).length;
      const llmReason = shortText(outputs.llm_failed_reason || outputs.llm_failed || '', 60);

      substeps = uniqSubsteps([
        {
          id: 'branch_select',
          text: farmScale || pesticideAccess || equipment.length
            ? `档位判定：${farmScale || '-'} + ${pesticideAccess || '-'} + ${equipment.join('、') || '-'} → ${selectedBranch}`
            : '档位判定：依据档案规模/购药/设备',
          seq: latest.seq,
        },
        ...(immediate || diff || resist
          ? [{ id: 'kb_fuse', text: `融合 KB actions：立即行动${immediate}条 / 差异化处置${diff}条 / 抗性管理${resist}条`, seq: latest.seq }]
          : []),
        { id: 'llm_call', text: `LLM 调用：${llmFailed ? `失败${llmReason ? `（${llmReason}）` : ''}` : '成功'}`, seq: latest.seq, level: (llmFailed ? 'warn' : 'info') as SubstepLevel },
        ...(llmFailed ? [{ id: 'fallback', text: '回退策略：使用 KB 后备组装', seq: latest.seq, level: 'warn' as SubstepLevel }] : []),
        { id: 'apply_constraints', text: `强约束后处理：有机/禁用成分/采收窗口 → filtered=${filtered}${filteredReasons.length ? `（${filteredReasons.join('；')}）` : ''}`, seq: latest.seq },
      ], 3, 5);
    }

    if (card.id === 'personalization' && cardEvents.length) {
      const pEvent = [...mainEvents].reverse().find((event) => event.agentId.toLowerCase().includes('personalizationagent'));
      const pOut = pEvent?.outputs || outputs;
      const filtered = asBool(pOut.filtered);
      const filteredReasons = toStringArray(pOut.filtered_reasons);
      const filteredComponents = toStringArray(pOut.filtered_components);
      const reasons = toStringArray(pOut.personalization_reasons);
      const context = isRecord(pOut.personalization_context) ? pOut.personalization_context as Record<string, unknown> : {};
      const preferOrganic = asBool(context.prefer_organic);

      keySteps = [`检测到约束：有机偏好=${preferOrganic ? '是' : '否'} → ${filtered ? `触发过滤：${filteredReasons.join('；') || '已触发'}${filteredComponents.length ? `（过滤成分：${filteredComponents.join('、')}）` : ''}` : '未触发过滤'}`];
      substeps = uniqSubsteps([
        { id: 'hit_organic', text: `命中 prefer_organic → ${preferOrganic ? '开启低残留策略' : '未开启低残留策略'}`, seq: latest.seq },
        ...(filteredComponents.length ? [{ id: 'scan_ingredients', text: `扫描命中 ingredients：${filteredComponents.join('、')} → 执行替换/删除`, seq: latest.seq }] : []),
        { id: 'build_reasons', text: `生成 filtered_reasons（${filteredReasons.length}条）`, seq: latest.seq },
        { id: 'explain', text: `personalization_reasons：${reasons.slice(0, 3).join('；')}${reasons.length > 3 ? '…' : ''}`, seq: latest.seq },
      ], 3, 5);
    }

    return {
      ...card,
      status,
      duration,
      keySteps,
      substeps,
    };
  });

  return { cards, systemSubsteps };
};

export function AgentWorkflowPanel({ traceId, confidencePct, phaseStartMs, refreshToken }: AgentWorkflowPanelProps) {
  const [showSystemNodes, setShowSystemNodes] = useState(false);
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [replayedCount, setReplayedCount] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [events, setEvents] = useState<NormalizedTraceEvent[]>([]);
  const [debugOpen, setDebugOpen] = useState<Record<FixedAgentId, boolean>>({
    supervisor: false,
    reception: false,
    diagnosis: false,
    kb_retrieval: false,
    treatment: false,
    personalization: false,
  });

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

  const mergeRawEvents = useCallback((rawEvents: RawTraceEvent[]) => {
    setEvents((prev) => {
      const normalized = rawEvents
        .map(normalizeTraceEvent)
        .filter((event) => {
          if (!phaseStartMs || !Number.isFinite(phaseStartMs)) return true;
          if (typeof event.tsMs !== 'number') return true;
          return event.tsMs >= (phaseStartMs - 120_000);
        });
      return dedupeEvents([...prev, ...normalized]);
    });
  }, [phaseStartMs]);

  useEffect(() => {
    if (!traceId) {
      queueMicrotask(() => {
        setEvents([]);
        setReplayedCount(0);
        setConnectionHint('');
        setConnectionState('idle');
      });
      closeStream();
      clearTicker();
      return;
    }

    let cancelled = false;
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
  }, [traceId, refreshToken, closeStream, clearTicker, mergeRawEvents]);

  const workflowDone = useMemo(() => events.some((event) => event.agentId.toLowerCase() === 'final' && eventStatus(event) === 'completed'), [events]);

  useEffect(() => {
    clearTicker();
    if (!workflowDone) tickerRef.current = window.setInterval(() => setNowMs(Date.now()), 200);
    return clearTicker;
  }, [workflowDone, clearTicker]);

  const diagnosisConfidencePct = useMemo(() => {
    const diagnosisEvents = events.filter((event) => mapToCardId(event) === 'diagnosis');
    const latest = diagnosisEvents[diagnosisEvents.length - 1];
    const raw = Number(latest?.outputs.final_confidence ?? latest?.outputs.disease_confidence ?? latest?.outputs.confidence);
    if (!Number.isFinite(raw)) return undefined;
    return raw <= 1 ? raw * 100 : raw;
  }, [events]);

  const { cards: cardViews, systemSubsteps } = useMemo(() => buildCardsFromEvents(events, showSystemNodes, nowMs), [events, showSystemNodes, nowMs]);

  const completedCount = useMemo(() => cardViews.filter((row) => row.status === 'completed').length, [cardViews]);
  const totalProgress = Math.round((completedCount / FIXED_AGENTS.length) * 100);
  const displayConfidencePct = Number.isFinite(confidencePct) ? confidencePct : diagnosisConfidencePct;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5]">
          <Signal className="w-3 h-3 mr-1" />
          {connectionState === 'connected' ? 'SSE 已连接' : connectionState === 'connecting' ? 'SSE 连接中' : connectionState === 'disconnected' ? 'SSE 已断开' : '等待 trace'}
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
            showSystemNodes ? 'border-[#c8f7c5]/60 text-[#c8f7c5] bg-[#c8f7c5]/10' : 'border-white/20 text-white/60 hover:text-white/80',
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
                    {row.status === 'completed' ? <CheckCircle2 className="w-5 h-5" /> : row.status === 'error' ? <AlertTriangle className="w-5 h-5" /> : running ? <Loader2 className="w-5 h-5 animate-spin" /> : <Icon className="w-5 h-5" />}
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
                        {row.keySteps.map((line, index) => (
                          <li key={`${row.id}-k-${index}`} className="text-xs text-white/70 flex items-start gap-1">
                            <span className="text-[#c8f7c5] mt-[2px]">•</span>
                            <span>{line}</span>
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
                          <div key={step.id} className={cn('text-xs', step.level === 'error' ? 'text-red-300' : step.level === 'warn' ? 'text-yellow-200' : 'text-white/50')}>
                            {step.text}
                          </div>
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

      {showSystemNodes && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-3">
          <p className="text-xs text-[#c8f7c5] mb-2">系统节点（校验/落盘等）</p>
          {systemSubsteps.length ? (
            <div className="space-y-1">
              {systemSubsteps.map((step) => (
                <div key={step.id} className="text-xs text-white/50">{step.text}</div>
              ))}
            </div>
          ) : <p className="text-xs text-white/40">暂无系统节点事件</p>}
        </div>
      )}

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
