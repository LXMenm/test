import { useState, useEffect, useMemo } from 'react';
import {
  BarChart3,
  Calendar,
  RefreshCw,
  Image as ImageIcon,
  TrendingUp,
  LineChart as LineChartIcon,
  Cpu,
  ChevronDown,
  ChevronUp,
  Settings2,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Calendar as DateCalendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ResponsiveContainer, LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, BarChart, Bar } from 'recharts';
import type { DateRange } from 'react-day-picker';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface DiseaseStat {
  disease: string;
  count: number;
}

interface DiagnosisEvent {
  id: string;
  ts: string;
  disease: string;
  traceId: string;
  confidencePct: number | null;
  imageUrl: string;
  modelId: string;
  modelName: string;
  selectedBranch: string;
  confirmRound: boolean;
  needConfirm: boolean;
  personalizationApplied: boolean;
  filtered: boolean;
  filteredReasons: string[];
  filteredComponents: string[];
  followUpQuestions: string[];
  missingProfileFields: string[];
  llmFailed: boolean;
  workflowDegraded: boolean;
  finalSource: string;
  farmerId: string;
  baseId: string;
  farmScale: string;
  pesticideAccessLevel: string;
  equipment: string[];
  cultivationMode: string;
  personalizationReasons: string[];
  elapsedMs: number | null;
  treatment?: unknown;
}

interface TimeseriesPoint {
  date: string;
  count: number;
}

interface SummaryCards {
  total: number;
  today: number;
  diseaseKinds: number;
  firstPassRate: number;
  treatmentSuccessRate: number;
  filteredRate: number;
  degradedRate: number;
}

interface KbDetail {
  name: string;
  description: string;
  treatment: string;
  prevention: string;
  actions?: Record<string, unknown> | null;
  ingredients?: string[];
}

interface ProfileListItem {
  id: string;
  name?: string;
}

interface ProfileDetail {
  farmer_id: string;
  name?: string;
  bases?: Record<string, { base_id?: string; name?: string }>;
}

interface TraceSummaryItem {
  key: string;
  agent: string;
  title: string;
  detail: string;
}

type ModuleKey = 'kpi' | 'trend' | 'model' | 'filter' | 'recent' | 'detail' | 'disease';

type ModulePrefs = Record<ModuleKey, boolean>;
type ModuleCollapse = Record<ModuleKey, boolean>;

const DASHBOARD_PREFS_KEY = 'dashboard-module-prefs-v1';
const DASHBOARD_COLLAPSE_KEY = 'dashboard-module-collapse-v1';

const defaultModulePrefs: ModulePrefs = {
  kpi: true,
  trend: true,
  model: true,
  filter: true,
  recent: true,
  detail: true,
  disease: true,
};

const defaultCollapse: ModuleCollapse = {
  kpi: false,
  trend: false,
  model: false,
  filter: false,
  recent: false,
  detail: false,
  disease: false,
};

const chartPalette = {
  line: '#9acfb0',
  greenSoft: '#79b996',
  greenDark: '#4c7f69',
  cyanSoft: '#6da8aa',
  yellowSoft: '#c3b277',
  coralSoft: '#b1837e',
  purpleSoft: '#8f84af',
};

function formatDate(date: Date): string {
  return date.toISOString().split('T')[0];
}

function getDefaultDateRange(days: number = 7): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (days - 1));
  return { start: formatDate(start), end: formatDate(end) };
}

function isValidDateString(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return false;
  return formatDate(parsed) === value;
}

function safeDisplayTime(value: string): string {
  if (!value) return '—';
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return '—';
  return new Date(parsed).toLocaleString();
}

function readableText(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback;
  const text = value.trim();
  if (!text) return fallback;
  if (['UNKNOWN', 'unknown', 'null', 'undefined', '-'].includes(text)) return fallback;
  return text;
}

function branchLabel(value: string): string {
  const val = readableText(value, '未分档').toUpperCase();
  const map: Record<string, string> = {
    FAMILY: '家庭档',
    MID: '专业档',
    ENTERPRISE: '规模档',
    '未分档': '未分档',
  };
  return map[val] || '未分档';
}

function sourceLabel(value: string): string {
  const val = readableText(value, '图像识别');
  const map: Record<string, string> = {
    image: '图像识别',
    symptom: '症状补充',
    confirm: '二次确认',
    fallback: '规则兜底',
  };
  return map[val] || val;
}

function getConfidencePct(source: Record<string, unknown>): number | null {
  const imageResult = source.image_result && typeof source.image_result === 'object'
    ? source.image_result as Record<string, unknown>
    : undefined;

  const confidencePct = Number(imageResult?.confidence_pct);
  if (Number.isFinite(confidencePct)) return confidencePct;

  const finalConfidence = Number(source.final_confidence);
  if (Number.isFinite(finalConfidence)) return finalConfidence <= 1 ? finalConfidence * 100 : finalConfidence;

  const confidence = Number(imageResult?.confidence);
  if (Number.isFinite(confidence)) return confidence * 100;

  return null;
}

function normalizeEvent(eventLike: unknown, index: number): DiagnosisEvent {
  const event = eventLike && typeof eventLike === 'object' ? eventLike as Record<string, unknown> : {};
  const imageResult = event.image_result && typeof event.image_result === 'object'
    ? event.image_result as Record<string, unknown>
    : undefined;
  const meta = event.meta && typeof event.meta === 'object' ? event.meta as Record<string, unknown> : undefined;

  return {
    id: typeof event.id === 'string' ? event.id : `${String(event.ts ?? event.timestamp ?? 'event')}-${index}`,
    ts: typeof event.ts === 'string'
      ? event.ts
      : (typeof event.timestamp === 'string' ? event.timestamp : new Date().toISOString()),
    disease: readableText(event.final_disease ?? imageResult?.disease, '未识别病害'),
    traceId: typeof event.trace_id === 'string' ? event.trace_id : '',
    imageUrl: typeof event.image_url === 'string' ? event.image_url : '',
    modelId: readableText(meta?.model_id ?? event.model_id, '未记录模型'),
    modelName: readableText(meta?.model_display_name ?? event.model_display_name, '未记录模型'),
    selectedBranch: branchLabel(String(event.selected_branch ?? meta?.selected_branch ?? '')),
    confirmRound: event.confirm_round === true,
    needConfirm: event.need_confirm === true,
    personalizationApplied: event.personalization_applied === true || meta?.personalization_applied === true,
    filtered: event.filtered === true || meta?.filtered === true,
    filteredReasons: Array.isArray(event.filtered_reasons)
      ? event.filtered_reasons.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.filtered_reasons) ? meta.filtered_reasons.map((item) => readableText(item, '')).filter(Boolean) : []),
    filteredComponents: Array.isArray(event.filtered_components)
      ? event.filtered_components.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.filtered_components) ? meta.filtered_components.map((item) => readableText(item, '')).filter(Boolean) : []),
    followUpQuestions: Array.isArray(event.follow_up_questions)
      ? event.follow_up_questions.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.follow_up_questions) ? meta.follow_up_questions.map((item) => readableText(item, '')).filter(Boolean) : []),
    missingProfileFields: Array.isArray(event.missing_profile_fields)
      ? event.missing_profile_fields.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.missing_profile_fields) ? meta.missing_profile_fields.map((item) => readableText(item, '')).filter(Boolean) : []),
    llmFailed: event.llm_failed === true || meta?.llm_failed === true,
    workflowDegraded: event.workflow_degraded === true || meta?.workflow_degraded === true,
    finalSource: sourceLabel(String(event.final_source ?? 'image')),
    farmerId: readableText(meta?.farmer_id, '未记录农户'),
    baseId: readableText(meta?.base_id, '未记录基地'),
    farmScale: readableText(meta?.farm_scale, '未记录'),
    pesticideAccessLevel: readableText(meta?.pesticide_access_level, '未记录'),
    equipment: Array.isArray(meta?.equipment) ? meta.equipment.map((item) => readableText(item, '')).filter(Boolean) : [],
    cultivationMode: readableText(meta?.cultivation_mode, '未记录'),
    personalizationReasons: Array.isArray(event.personalization_reasons)
      ? event.personalization_reasons.map((item) => readableText(item, '')).filter(Boolean)
      : [],
    elapsedMs: Number.isFinite(Number(event.elapsed_ms ?? meta?.elapsed_ms)) ? Number(event.elapsed_ms ?? meta?.elapsed_ms) : null,
    confidencePct: getConfidencePct(event),
    treatment: event.treatment,
  };
}

function renderTreatment(value: unknown) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return <div className="whitespace-pre-wrap">{value}</div>;
  if (typeof value === 'object') {
    const data = value as Record<string, unknown>;
    const plan = data.plan;
    const prevention = data.prevention;
    return (
      <div className="space-y-3">
        {typeof plan === 'string' && plan.trim() && (
          <div>
            <div className="text-[#b8ddc7] text-xs mb-1">处方建议</div>
            <div className="whitespace-pre-wrap">{plan}</div>
          </div>
        )}
        {typeof prevention === 'string' && prevention.trim() && (
          <div>
            <div className="text-[#b8ddc7] text-xs mb-1">预防管理</div>
            <div className="whitespace-pre-wrap">{prevention}</div>
          </div>
        )}
      </div>
    );
  }
  return <div className="whitespace-pre-wrap">{String(value)}</div>;
}

function getNestedRecord(source: unknown, key: string): Record<string, unknown> {
  if (!source || typeof source !== 'object') return {};
  const value = (source as Record<string, unknown>)[key];
  if (!value || typeof value !== 'object') return {};
  return value as Record<string, unknown>;
}

function summarizeTraceRows(rows: unknown[]): TraceSummaryItem[] {
  const safeRows = rows.filter((item) => item && typeof item === 'object') as Record<string, unknown>[];
  if (safeRows.length === 0) return [];

  const findLatest = (needle: string[]) => {
    return [...safeRows].reverse().find((row) => {
      const agent = String(row.agent ?? row.agent_id ?? row.node ?? '').toLowerCase();
      const step = String(row.step ?? row.step_cn ?? row.message ?? '').toLowerCase();
      return needle.some((key) => agent.includes(key) || step.includes(key));
    });
  };

  const reception = findLatest(['reception']);
  const diagnosis = findLatest(['diagnosis']);
  const kb = findLatest(['kb_retrieval', 'kb']);
  const treatment = findLatest(['treatment', 'prescription']);
  const personalization = findLatest(['personalization']);

  const summary: TraceSummaryItem[] = [];

  if (reception) {
    const inputs = getNestedRecord(reception, 'inputs');
    const outputs = getNestedRecord(reception, 'outputs');
    const symptoms = Array.isArray(inputs.symptoms) ? inputs.symptoms.map(String).filter(Boolean) : [];
    const missing = Array.isArray(outputs.missing_profile_fields) ? outputs.missing_profile_fields.map(String).filter(Boolean) : [];
    summary.push({
      key: 'reception',
      agent: '接待智能体',
      title: `抽取症状 ${symptoms.length > 0 ? symptoms.slice(0, 3).join('、') : '未记录'}`,
      detail: `档案缺失字段：${missing.length > 0 ? missing.join('、') : '无'}`,
    });
  }

  if (diagnosis) {
    const payload = getNestedRecord(diagnosis, 'payload');
    const disease = readableText(payload.disease, '未明确病害');
    const conf = Number(payload.confidence);
    const needConfirm = payload.need_confirm === true || String(diagnosis.message ?? '').includes('确认');
    summary.push({
      key: 'diagnosis',
      agent: '诊断智能体',
      title: `判定病害：${disease}，置信度：${Number.isFinite(conf) ? `${(conf * 100).toFixed(1)}%` : '未记录'}`,
      detail: `诊断结论${needConfirm ? '建议继续确认' : '可直接输出'}。`,
    });
  }

  if (kb) {
    const outputs = getNestedRecord(kb, 'outputs');
    const payload = getNestedRecord(kb, 'payload');
    const disease = readableText(outputs.kb_disease ?? payload.kb_disease ?? payload.disease, '未命中');
    const hasActions = outputs.actions || payload.actions;
    const ingredients = Array.isArray(outputs.ingredients)
      ? outputs.ingredients.length
      : (Array.isArray(payload.ingredients) ? payload.ingredients.length : 0);
    summary.push({
      key: 'kb',
      agent: '知识检索智能体',
      title: `知识命中：${disease}`,
      detail: `措施字段：${hasActions ? '有' : '无'}；药剂成分：${ingredients > 0 ? `${ingredients} 项` : '无'}`,
    });
  }

  if (treatment) {
    const outputs = getNestedRecord(treatment, 'outputs');
    const payload = getNestedRecord(treatment, 'payload');
    const branch = branchLabel(String(outputs.selected_branch ?? payload.selected_branch ?? ''));
    const llmFailed = outputs.llm_failed === true || payload.llm_failed === true;
    const filtered = outputs.filtered === true || payload.filtered === true;
    summary.push({
      key: 'treatment',
      agent: '治疗方案智能体',
      title: `按${branch}生成方案，LLM${llmFailed ? '失败转兜底' : '生成成功'}`,
      detail: filtered ? '方案触发个性化过滤，已做安全改写。' : '方案按个性化信息直接输出。',
    });
  }

  if (personalization) {
    const payload = getNestedRecord(personalization, 'payload');
    const outputs = getNestedRecord(payload, 'outputs');
    const reasons = Array.isArray(outputs.personalization_reasons) ? outputs.personalization_reasons.map(String).filter(Boolean) : [];
    const filteredReasons = Array.isArray(outputs.filtered_reasons) ? outputs.filtered_reasons.map(String).filter(Boolean) : [];
    summary.push({
      key: 'personalization',
      agent: '个性化节点',
      title: `个性化${outputs.personalization_applied ? '已应用' : '未应用'}，命中约束 ${reasons.length}`,
      detail: `触发过滤原因：${filteredReasons.length > 0 ? filteredReasons.join('、') : '无'}`,
    });
  }

  if (summary.length > 0) return summary;

  return safeRows
    .slice(-4)
    .map((row, index) => ({
      key: `fallback-${index}`,
      agent: readableText(row.agent_cn ?? row.agent, '流程节点'),
      title: readableText(row.step_cn ?? row.message, '流程执行'),
      detail: '该节点缺少结构化信息，暂展示原始摘要。',
    }));
}

function loadLocalRecord<T extends Record<string, boolean>>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const merged = { ...fallback } as Record<string, boolean>;
    Object.keys(merged).forEach((k) => {
      if (typeof parsed[k] === 'boolean') merged[k] = parsed[k] as boolean;
    });
    return merged as T;
  } catch {
    return fallback;
  }
}

export function DashboardPage() {
  const defaultRange = getDefaultDateRange(7);
  const [startDate, setStartDate] = useState(defaultRange.start);
  const [endDate, setEndDate] = useState(defaultRange.end);
  const [calendarRange, setCalendarRange] = useState<DateRange | undefined>(() => ({
    from: new Date(`${defaultRange.start}T00:00:00`),
    to: new Date(`${defaultRange.end}T00:00:00`),
  }));
  const [calendarMonths, setCalendarMonths] = useState(2);
  const [allEvents, setAllEvents] = useState<DiagnosisEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<DiagnosisEvent | null>(null);
  const [selectedDisease, setSelectedDisease] = useState('ALL');
  const [selectedBranch, setSelectedBranch] = useState('ALL');
  const [selectedPersonalizationStatus, setSelectedPersonalizationStatus] = useState('ALL');
  const [selectedModel, setSelectedModel] = useState('ALL');
  const [profiles, setProfiles] = useState<ProfileListItem[]>([]);
  const [selectedFarmerId, setSelectedFarmerId] = useState('ALL');
  const [selectedBaseId, setSelectedBaseId] = useState('ALL');
  const [farmerBases, setFarmerBases] = useState<Array<{ id: string; name?: string }>>([]);
  const [kbDetail, setKbDetail] = useState<KbDetail | null>(null);
  const [traceSummary, setTraceSummary] = useState<TraceSummaryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modulePrefs, setModulePrefs] = useState<ModulePrefs>(defaultModulePrefs);
  const [moduleCollapse, setModuleCollapse] = useState<ModuleCollapse>(defaultCollapse);

  const hasTreatment = selectedEvent
    ? typeof selectedEvent.treatment === 'string'
      || (selectedEvent.treatment !== null && typeof selectedEvent.treatment === 'object')
    : false;

  useEffect(() => {
    setModulePrefs(loadLocalRecord(DASHBOARD_PREFS_KEY, defaultModulePrefs));
    setModuleCollapse(loadLocalRecord(DASHBOARD_COLLAPSE_KEY, defaultCollapse));
    const updateMonths = () => setCalendarMonths(window.innerWidth < 1100 ? 1 : 2);
    updateMonths();
    window.addEventListener('resize', updateMonths);
    return () => window.removeEventListener('resize', updateMonths);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(DASHBOARD_PREFS_KEY, JSON.stringify(modulePrefs));
  }, [modulePrefs]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(DASHBOARD_COLLAPSE_KEY, JSON.stringify(moduleCollapse));
  }, [moduleCollapse]);

  const sanitizeDateRange = (): { start: string; end: string } => {
    const fallbackRange = getDefaultDateRange(7);
    const invalid = !isValidDateString(startDate) || !isValidDateString(endDate) || startDate > endDate;
    if (invalid) {
      setStartDate(fallbackRange.start);
      setEndDate(fallbackRange.end);
      return fallbackRange;
    }
    return { start: startDate, end: endDate };
  };

  const fetchData = async () => {
    setLoading(true);
    const { start: safeStart, end: safeEnd } = sanitizeDateRange();
    try {
      const eventsResp = await fetch(`/api/events?start=${safeStart}&end=${safeEnd}&limit=5000`);
      const eventsData = await eventsResp.json();
      const eventsList = Array.isArray(eventsData)
        ? eventsData
        : eventsData?.events ?? eventsData?.items ?? eventsData?.data ?? [];
      const safeEvents = Array.isArray(eventsList)
        ? eventsList.map((eventLike, index) => normalizeEvent(eventLike, index))
        : [];
      setAllEvents(safeEvents);
      setSelectedEvent(safeEvents.length > 0 ? safeEvents[0] : null);
    } catch {
      setAllEvents([]);
      setSelectedEvent(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  useEffect(() => {
    const run = async () => {
      try {
        const resp = await fetch('/api/profiles');
        const data = await resp.json();
        const rows: unknown[] = Array.isArray(data?.profiles) ? data.profiles : [];
        setProfiles(
          rows
            .map((item: unknown) => {
              const row = item && typeof item === 'object' ? item as Record<string, unknown> : {};
              return { id: String(row.id ?? ''), name: typeof row.name === 'string' ? row.name : undefined };
            })
            .filter((item: ProfileListItem) => item.id)
        );
      } catch {
        setProfiles([]);
      }
    };
    run();
  }, []);

  useEffect(() => {
    if (!selectedFarmerId || selectedFarmerId === 'ALL') {
      setFarmerBases([]);
      setSelectedBaseId('ALL');
      return;
    }
    const run = async () => {
      try {
        const resp = await fetch(`/api/profiles/${encodeURIComponent(selectedFarmerId)}`);
        const data = await resp.json() as ProfileDetail;
        const bases = data?.bases && typeof data.bases === 'object'
          ? Object.entries(data.bases).map(([id, value]) => ({ id, name: value?.name }))
          : [];
        setFarmerBases(bases);
      } catch {
        setFarmerBases([]);
      }
    };
    run();
  }, [selectedFarmerId]);

  const diseaseOptions = useMemo(() => Array.from(new Set(allEvents.map((event) => event.disease))).sort((a, b) => a.localeCompare(b, 'zh-CN')), [allEvents]);
  const modelOptions = useMemo(() => Array.from(new Set(allEvents.map((event) => event.modelName || event.modelId))).sort((a, b) => a.localeCompare(b, 'zh-CN')), [allEvents]);

  const filteredEvents = useMemo(() => allEvents.filter((event) => {
    if (selectedDisease !== 'ALL' && event.disease !== selectedDisease) return false;
    if (selectedBranch !== 'ALL' && event.selectedBranch !== selectedBranch) return false;
    if (selectedPersonalizationStatus === 'APPLIED' && !event.personalizationApplied) return false;
    if (selectedPersonalizationStatus === 'FILTERED' && !event.filtered) return false;
    if (selectedModel !== 'ALL' && (event.modelName || event.modelId) !== selectedModel) return false;
    if (selectedFarmerId !== 'ALL' && event.farmerId !== selectedFarmerId) return false;
    if (selectedBaseId !== 'ALL' && event.baseId !== selectedBaseId) return false;
    return true;
  }), [allEvents, selectedDisease, selectedBranch, selectedPersonalizationStatus, selectedModel, selectedFarmerId, selectedBaseId]);

  const stats = useMemo<DiseaseStat[]>(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => map.set(event.disease, (map.get(event.disease) ?? 0) + 1));
    return Array.from(map.entries()).map(([disease, count]) => ({ disease, count })).sort((a, b) => b.count - a.count);
  }, [filteredEvents]);

  const timeseries = useMemo<TimeseriesPoint[]>(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => {
      const ts = Date.parse(event.ts);
      if (!Number.isFinite(ts)) return;
      const day = formatDate(new Date(ts));
      map.set(day, (map.get(day) ?? 0) + 1);
    });
    return Array.from(map.entries()).map(([date, count]) => ({ date, count })).sort((a, b) => a.date.localeCompare(b.date));
  }, [filteredEvents]);

  const timeseriesBreakdown = useMemo(() => {
    const map = new Map<string, Record<string, number>>();
    filteredEvents.forEach((event) => {
      const ts = Date.parse(event.ts);
      if (!Number.isFinite(ts)) return;
      const day = formatDate(new Date(ts));
      const current = map.get(day) ?? {};
      current[event.disease] = (current[event.disease] ?? 0) + 1;
      map.set(day, current);
    });
    return map;
  }, [filteredEvents]);

  const diseaseTrendData = useMemo(() => {
    const topDiseases = stats.slice(0, 6).map((item) => item.disease);
    return timeseries.map((row) => {
      const breakdown = timeseriesBreakdown.get(row.date) ?? {};
      const payload: Record<string, number | string> = { date: row.date, total: row.count };
      topDiseases.forEach((disease) => { payload[disease] = breakdown[disease] ?? 0; });
      return payload;
    });
  }, [stats, timeseries, timeseriesBreakdown]);

  const modelStats = useMemo(() => {
    const map = new Map<string, { count: number; success: number; fallback: number; degraded: number; llmFailed: number; elapsedSum: number; elapsedCount: number }>();
    filteredEvents.forEach((event) => {
      const label = event.modelName || event.modelId;
      const current = map.get(label) ?? { count: 0, success: 0, fallback: 0, degraded: 0, llmFailed: 0, elapsedSum: 0, elapsedCount: 0 };
      current.count += 1;
      if (event.llmFailed || event.workflowDegraded) current.degraded += 1;
      else if (event.finalSource === '规则兜底') current.fallback += 1;
      else current.success += 1;
      if (event.llmFailed) current.llmFailed += 1;
      if (event.elapsedMs !== null) {
        current.elapsedSum += event.elapsedMs;
        current.elapsedCount += 1;
      }
      map.set(label, current);
    });
    return Array.from(map.entries())
      .map(([model, data]) => ({
        model,
        count: data.count,
        success: data.success,
        fallback: data.fallback,
        degraded: data.degraded,
        llmFailedRate: data.count > 0 ? (data.llmFailed / data.count) * 100 : 0,
        avgMs: data.elapsedCount > 0 ? data.elapsedSum / data.elapsedCount : 0,
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [filteredEvents]);

  const modelSummary = useMemo(() => {
    const total = modelStats.reduce((sum, item) => sum + item.count, 0);
    const llmFailed = modelStats.reduce((sum, item) => sum + (item.llmFailedRate / 100) * item.count, 0);
    const avgResponseMs = filteredEvents.filter((event) => event.elapsedMs !== null).reduce((sum, event) => sum + Number(event.elapsedMs), 0) / Math.max(filteredEvents.filter((event) => event.elapsedMs !== null).length, 1);
    return { avgResponseMs: Number.isFinite(avgResponseMs) ? avgResponseMs : 0, llmFailedRate: total > 0 ? (llmFailed / total) * 100 : 0 };
  }, [modelStats, filteredEvents]);

  const summary = useMemo<SummaryCards>(() => {
    const total = filteredEvents.length;
    const todayStr = formatDate(new Date());
    const today = filteredEvents.filter((event) => {
      const ts = Date.parse(event.ts);
      return Number.isFinite(ts) && formatDate(new Date(ts)) === todayStr;
    }).length;
    const treatmentSuccess = filteredEvents.filter((event) => {
      if (!event.treatment || typeof event.treatment !== 'object') return false;
      const plan = (event.treatment as Record<string, unknown>).plan;
      return typeof plan === 'string' && plan.trim().length > 0;
    }).length;
    const firstPassDone = filteredEvents.filter((event) => !event.confirmRound && !event.needConfirm).length;
    const filteredCount = filteredEvents.filter((event) => event.filtered).length;
    const degradedCount = filteredEvents.filter((event) => event.workflowDegraded || event.llmFailed).length;
    return {
      total,
      today,
      diseaseKinds: new Set(filteredEvents.map((event) => event.disease)).size,
      firstPassRate: total > 0 ? (firstPassDone / total) * 100 : 0,
      treatmentSuccessRate: total > 0 ? (treatmentSuccess / total) * 100 : 0,
      filteredRate: total > 0 ? (filteredCount / total) * 100 : 0,
      degradedRate: total > 0 ? (degradedCount / total) * 100 : 0,
    };
  }, [filteredEvents]);

  const filteredReasonDistribution = useMemo(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => event.filteredReasons.forEach((reason) => map.set(reason, (map.get(reason) ?? 0) + 1)));
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count).slice(0, 8);
  }, [filteredEvents]);

  useEffect(() => {
    if (!selectedEvent && filteredEvents.length > 0) setSelectedEvent(filteredEvents[0]);
    if (selectedEvent && !filteredEvents.some((event) => event.id === selectedEvent.id)) setSelectedEvent(filteredEvents[0] ?? null);
  }, [filteredEvents, selectedEvent]);

  useEffect(() => {
    const targetDisease = selectedEvent?.disease;
    if (!targetDisease || targetDisease === '未识别病害') { setKbDetail(null); return; }
    const run = async () => {
      try {
        const resp = await fetch(`/api/kb/diseases/${encodeURIComponent(targetDisease)}`);
        const data = await resp.json();
        if (!resp.ok) throw new Error(String(data?.detail || 'kb detail failed'));
        setKbDetail(data as KbDetail);
      } catch {
        setKbDetail(null);
      }
    };
    run();
  }, [selectedEvent?.disease]);

  useEffect(() => {
    const traceId = selectedEvent?.traceId;
    if (!traceId) { setTraceSummary([]); return; }
    const run = async () => {
      try {
        const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
        const data = await resp.json();
        const rows = Array.isArray(data?.events) ? data.events : [];
        setTraceSummary(summarizeTraceRows(rows));
      } catch {
        setTraceSummary([]);
      }
    };
    run();
  }, [selectedEvent?.traceId]);

  const maxCount = Math.max(...stats.map((s) => s.count), 1);

  const setQuickRange = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setEndDate(formatDate(end));
    setStartDate(formatDate(start));
    setCalendarRange({ from: start, to: end });
  };

  const onCalendarRangeSelect = (range: DateRange | undefined) => {
    setCalendarRange(range);
    if (range?.from) setStartDate(formatDate(range.from));
    if (range?.to) setEndDate(formatDate(range.to));
  };

  const renderModuleHeader = (key: ModuleKey, title: string, icon?: ReactNode) => (
    <CardHeader className="pb-3">
      <div className="flex items-center justify-between gap-3">
        <CardTitle className="text-white flex items-center gap-2 text-base">{icon}{title}</CardTitle>
        <Button
          size="sm"
          variant="outline"
          className="border-[#2b5f4d] text-white/80 hover:bg-[#183229]"
          onClick={() => setModuleCollapse((prev) => ({ ...prev, [key]: !prev[key] }))}
        >
          {moduleCollapse[key] ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
        </Button>
      </div>
    </CardHeader>
  );

  return (
    <div className="space-y-6 animate-fadeIn overflow-visible">
      <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
        <div className="max-w-[620px]">
          <h1 className="text-[28px] md:text-[30px] leading-tight font-bold text-white md:whitespace-nowrap">番茄病害<span className="text-[#b9dbc7]">诊疗联动分析看板</span></h1>
          <p className="text-white/60 mt-1 text-sm">面向基地诊疗过程的趋势、案例与可解释分析</p>
        </div>

        <div className="flex flex-wrap xl:flex-nowrap items-center justify-end gap-2 xl:gap-2.5">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="h-10 bg-[#1f7558] text-white border-[#3b8a6c] hover:bg-[#287f61] min-w-[280px] justify-start">
                <Calendar className="w-4 h-4 mr-2" />
                {startDate} - {endDate}
              </Button>
            </PopoverTrigger>
            <PopoverContent
              side="bottom"
              align="end"
              sideOffset={10}
              className="z-[1200] w-auto max-w-[calc(100vw-1.5rem)] overflow-auto p-0 bg-[#b7d8c0] text-[#111f18] border border-[#7bab92] shadow-[0_12px_42px_rgba(20,92,69,0.28)] rounded-xl"
            >
              <DateCalendar
                mode="range"
                numberOfMonths={calendarMonths}
                selected={calendarRange}
                onSelect={onCalendarRangeSelect}
                defaultMonth={calendarRange?.from}
                className="bg-[#b7d8c0] text-[#12211a] rounded-xl p-3 [&_button]:text-[#12211a] [&_button:hover]:bg-[#9ec7ae] [&_button[data-selected-single=true]]:bg-[#5f997c] [&_button[data-selected-single=true]]:text-[#0f1d16] [&_button[data-range-middle=true]]:bg-[#9fc9b0] [&_button[data-range-middle=true]]:text-[#0f1d16] [&_button[data-range-start=true]]:bg-[#5f997c] [&_button[data-range-start=true]]:text-[#0f1d16] [&_button[data-range-end=true]]:bg-[#5f997c] [&_button[data-range-end=true]]:text-[#0f1d16]"
                classNames={{
                  root: 'text-[#12211a]',
                  month_caption: 'text-[#0f1d16] font-semibold',
                  weekday: 'text-[#1f4536] font-medium',
                  day: 'text-[#12211a]',
                  outside: 'text-[#3d6a57] opacity-80',
                  today: 'bg-[#95c2a8] text-[#0f1d16]',
                  range_middle: 'bg-[#9fc9b0] text-[#0f1d16]',
                  range_start: 'bg-[#5f997c] text-[#0f1d16]',
                  range_end: 'bg-[#5f997c] text-[#0f1d16]',
                }}
              />
            </PopoverContent>
          </Popover>

          <div className="flex items-center gap-1.5">
            {[7, 30, 90].map((days) => (
              <Button key={days} variant="outline" size="sm" onClick={() => setQuickRange(days)} className="h-10 bg-[#1f7558]/95 text-white border-[#3b8a6c] hover:bg-[#287f61]">近{days}天</Button>
            ))}
          </div>

          <Button onClick={fetchData} disabled={loading} className="h-10 bg-[#1f7a59] text-white hover:bg-[#228664]">
            <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
          </Button>

          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="h-10 border-[#3b8a6c] bg-[#1f7558] text-white hover:bg-[#287f61]">
                <Settings2 className="w-4 h-4 mr-1" /> 页面设置
              </Button>
            </PopoverTrigger>
            <PopoverContent className="z-[1100] w-[320px] max-h-[420px] overflow-y-auto dashboard-scrollbar bg-[#b7d8c0] border border-[#7bab92] text-[#12211a] shadow-[0_10px_34px_rgba(15,40,28,0.22)]">
              <div className="space-y-2">
                {Object.entries({
                  kpi: 'KPI 总览区',
                  trend: '趋势图区域',
                  model: '模型调用统计',
                  filter: '过滤原因统计',
                  recent: '最近诊断',
                  detail: '详情区',
                  disease: '病害 Top / 补充图表',
                }).map(([key, label]) => {
                  const visible = modulePrefs[key as ModuleKey];
                  return (
                    <div key={key} className="rounded-lg border border-[#90bda5] bg-[#c3e0cd]/70 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-[#12211a] truncate">{label}</p>
                          <p className="text-xs text-[#2b4b3d]">{visible ? '已显示 · 点击 - 从页面移除' : '已隐藏 · 点击 + 添加到页面'}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setModulePrefs((prev) => ({ ...prev, [key]: !visible }))}
                          className={cn(
                            'h-8 w-8 rounded-md border font-bold text-lg leading-none transition-colors',
                            visible
                              ? 'bg-[#d6eadc] border-[#7ea78f] text-[#1e3a2e] hover:bg-[#c7e0d0]'
                              : 'bg-[#6c9c7f] border-[#5f8c72] text-[#0f1a14] hover:bg-[#78a98a]'
                          )}
                          aria-label={visible ? `从页面移除${label}` : `添加${label}到页面`}
                        >
                          {visible ? '−' : '+'}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>

      <Card className="glass-card mt-1">
        <CardContent className="pt-5">
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
            <select value={selectedFarmerId} onChange={(e) => setSelectedFarmerId(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none">
              <option value="ALL">农户：全部（先选农户）</option>
              {profiles.map((item) => <option key={item.id} value={item.id}>{item.name ? `${item.id} · ${item.name}` : item.id}</option>)}
            </select>
            <select value={selectedBaseId} onChange={(e) => setSelectedBaseId(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium disabled:opacity-50 w-full leading-none" disabled={selectedFarmerId === 'ALL'}>
              <option value="ALL">基地：全部</option>
              {farmerBases.map((item) => <option key={item.id} value={item.id}>{item.name ? `${item.id} · ${item.name}` : item.id}</option>)}
            </select>
            <select value={selectedDisease} onChange={(e) => setSelectedDisease(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none">
              <option value="ALL" className="bg-[#0b241b] text-[#e8fff0]">病害：全部</option>
              {diseaseOptions.map((item) => <option key={item} value={item} className="bg-[#0b241b] text-[#e8fff0]">{item}</option>)}
            </select>
            <select value={selectedBranch} onChange={(e) => setSelectedBranch(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none">
              <option value="ALL" className="bg-[#0b241b] text-[#e8fff0]">档位：全部</option>
              {['家庭档', '专业档', '规模档', '未分档'].map((item) => <option key={item} value={item} className="bg-[#0b241b] text-[#e8fff0]">{item}</option>)}
            </select>
            <select value={selectedPersonalizationStatus} onChange={(e) => setSelectedPersonalizationStatus(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none">
              <option value="ALL" className="bg-[#0b241b] text-[#e8fff0]">个性化：全部</option>
              <option value="APPLIED" className="bg-[#0b241b] text-[#e8fff0]">已应用个性化</option>
              <option value="FILTERED" className="bg-[#0b241b] text-[#e8fff0]">触发过滤</option>
            </select>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none">
              <option value="ALL" className="bg-[#0b241b] text-[#e8fff0]">模型：全部</option>
              {modelOptions.map((item) => <option key={item} value={item} className="bg-[#0b241b] text-[#e8fff0]">{item}</option>)}
            </select>
          </div>
        </CardContent>
      </Card>

      {modulePrefs.kpi && (
        <Card className="border border-[#2e7d63]/45 bg-[#12231d] shadow-[0_0_0_1px_rgba(121,185,150,0.08),0_14px_40px_rgba(5,18,12,0.4)]">
          {renderModuleHeader('kpi', '核心诊疗总览', <BarChart3 className="w-5 h-5 text-[#b8ddc7]" />)}
          {!moduleCollapse.kpi && (
            <CardContent className="grid sm:grid-cols-2 xl:grid-cols-6 gap-4 pt-1">
              {[
                ['总诊断次数', String(summary.total)],
                ['今日诊断次数', String(summary.today)],
                ['病害种类数（窗口内）', String(summary.diseaseKinds)],
                ['首轮完成率', `${summary.firstPassRate.toFixed(1)}%`],
                ['方案生成成功率', `${summary.treatmentSuccessRate.toFixed(1)}%`],
                ['过滤触发率 / 降级率', `${summary.filteredRate.toFixed(1)}% / ${summary.degradedRate.toFixed(1)}%`],
              ].map(([title, value]) => (
                <div key={title} className="rounded-xl border border-[#2e7d63]/35 bg-[#173128] px-4 py-4">
                  <p className="text-white/70 text-xs">{title}</p>
                  <p className="text-2xl font-bold text-[#cde8d8] mt-2">{value}</p>
                </div>
              ))}
            </CardContent>
          )}
        </Card>
      )}

      {modulePrefs.trend && (
        <Card className="glass-card">
          {renderModuleHeader('trend', '趋势图区域', <LineChartIcon className="w-5 h-5 text-[#b8ddc7]" />)}
          {!moduleCollapse.trend && (
            <CardContent className="grid lg:grid-cols-2 gap-6">
              <div className="h-72">
                <p className="text-white/70 text-sm mb-2">诊断趋势（按日）</p>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={timeseries} margin={{ left: 8, right: 8, top: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(193,227,207,0.18)" />
                    <XAxis dataKey="date" stroke="rgba(229,243,236,0.72)" tick={{ fontSize: 12 }} />
                    <YAxis stroke="rgba(229,243,236,0.72)" allowDecimals={false} tick={{ fontSize: 12 }} />
                    <Tooltip contentStyle={{ background: '#10231c', border: '1px solid rgba(146,194,168,0.5)', color: '#e8fff0' }} />
                    <Line type="monotone" dataKey="count" stroke={chartPalette.line} strokeWidth={2.6} dot={{ r: 2.5, fill: chartPalette.line }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="h-72">
                <p className="text-white/70 text-sm mb-2">病害趋势（按日堆叠）</p>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={diseaseTrendData} margin={{ left: 8, right: 8, top: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(193,227,207,0.18)" />
                    <XAxis dataKey="date" stroke="rgba(229,243,236,0.72)" tick={{ fontSize: 12 }} />
                    <YAxis stroke="rgba(229,243,236,0.72)" allowDecimals={false} tick={{ fontSize: 12 }} />
                    <Tooltip contentStyle={{ background: '#10231c', border: '1px solid rgba(146,194,168,0.5)', color: '#e8fff0' }} />
                    {stats.slice(0, 6).map((item, index) => (
                      <Bar
                        key={item.disease}
                        dataKey={item.disease}
                        stackId="disease"
                        fill={[chartPalette.greenSoft, chartPalette.greenDark, chartPalette.yellowSoft, chartPalette.cyanSoft, chartPalette.coralSoft, chartPalette.purpleSoft][index % 6]}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          )}
        </Card>
      )}

      {modulePrefs.model && (
        <Card className="glass-card">
          {renderModuleHeader('model', '模型调用统计', <Cpu className="w-5 h-5 text-[#b8ddc7]" />)}
          {!moduleCollapse.model && (
            <CardContent className="h-80">
              {modelStats.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={modelStats} margin={{ left: 8, right: 8, top: 10, bottom: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(193,227,207,0.18)" />
                    <XAxis dataKey="model" stroke="rgba(229,243,236,0.72)" tick={{ fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={60} />
                    <YAxis stroke="rgba(229,243,236,0.72)" allowDecimals={false} tick={{ fontSize: 12 }} />
                    <Tooltip contentStyle={{ background: '#10231c', border: '1px solid rgba(146,194,168,0.5)', color: '#e8fff0' }} />
                    <Bar dataKey="success" stackId="a" fill={chartPalette.greenSoft} />
                    <Bar dataKey="fallback" stackId="a" fill={chartPalette.yellowSoft} />
                    <Bar dataKey="degraded" stackId="a" fill={chartPalette.coralSoft} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-white/40 text-sm">暂无模型调用数据</div>
              )}
              <div className="mt-2 text-xs text-white/70 flex items-center justify-between">
                <span>平均响应时间：{modelSummary.avgResponseMs > 0 ? `${modelSummary.avgResponseMs.toFixed(0)} ms` : '—'}</span>
                <span>LLM 失败率：{modelSummary.llmFailedRate.toFixed(1)}%</span>
              </div>
            </CardContent>
          )}
        </Card>
      )}

      {modulePrefs.filter && (
        <Card className="glass-card">
          {renderModuleHeader('filter', '过滤原因统计', <TrendingUp className="w-5 h-5 text-[#b8ddc7]" />)}
          {!moduleCollapse.filter && (
            <CardContent>
              <div className="space-y-3">
                {filteredReasonDistribution.map((item) => {
                  const max = Math.max(...filteredReasonDistribution.map((x) => x.count), 1);
                  return (
                    <div key={item.name} className="space-y-1">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-white/70 truncate pr-2">{item.name}</span>
                        <span className="text-[#b8ddc7]">{item.count}</span>
                      </div>
                      <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                        <div className="h-full bg-[#6fa98b]" style={{ width: `${(item.count / max) * 100}%` }} />
                      </div>
                    </div>
                  );
                })}
                {filteredReasonDistribution.length === 0 && <p className="text-white/40 text-sm">暂无过滤原因统计</p>}
              </div>
            </CardContent>
          )}
        </Card>
      )}

      {modulePrefs.disease && (
        <Card className="glass-card">
          {renderModuleHeader('disease', `病害 Top ${Math.min(8, stats.length)}`, <TrendingUp className="w-5 h-5 text-[#b8ddc7]" />)}
          {!moduleCollapse.disease && (
            <CardContent>
              <div className="space-y-3">
                {stats.slice(0, 8).map((stat, index) => (
                  <div key={stat.disease} className="space-y-1">
                    <button className="flex items-center justify-between text-sm w-full text-left" onClick={() => setSelectedDisease(stat.disease)}>
                      <span className="text-white/80 truncate flex-1">#{index + 1} {stat.disease}</span>
                      <span className="text-[#b8ddc7] font-mono ml-2">({stat.count})</span>
                    </button>
                    <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-[#94c7aa] to-[#5f967b] rounded-full" style={{ width: `${(stat.count / maxCount) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          )}
        </Card>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {modulePrefs.recent && (
          <Card className="glass-card">
            {renderModuleHeader('recent', '最近诊断', <Calendar className="w-5 h-5 text-[#b8ddc7]" />)}
            {!moduleCollapse.recent && (
              <CardContent>
                <div className="space-y-2 max-h-[420px] overflow-y-auto dashboard-scrollbar">
                  {filteredEvents.slice(0, 80).map((event) => (
                    <div
                      key={event.id}
                      onClick={() => setSelectedEvent(event)}
                      className={cn('p-3 rounded-xl cursor-pointer transition-all duration-300 border', selectedEvent?.id === event.id ? 'bg-[#203b31] border-[#84b89d]' : 'bg-white/5 hover:bg-white/10 border-transparent')}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-white/45 text-xs font-mono">{safeDisplayTime(event.ts)}</span>
                        <Badge variant="outline" className={cn('text-xs', (event.confidencePct ?? -1) >= 80 ? 'border-[#79b996] text-[#bde4cf]' : (event.confidencePct ?? -1) >= 50 ? 'border-[#c3b277] text-[#e4dbb5]' : 'border-[#b1837e] text-[#d7b4af]')}>
                          {event.confidencePct !== null ? `${event.confidencePct.toFixed(2)}%` : '未记录'}
                        </Badge>
                      </div>
                      <p className="text-white font-medium mt-1">{event.disease}</p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        <Badge variant="outline" className="text-[10px] border-white/25 text-white/70">{event.selectedBranch}</Badge>
                        {event.personalizationApplied && <Badge className="text-[10px] bg-[#7aa88e] text-[#0d1712]">个性化</Badge>}
                        {event.filtered && <Badge className="text-[10px] bg-[#8e9561] text-[#0d1712]">已过滤</Badge>}
                        {event.confirmRound && <Badge className="text-[10px] bg-[#698997] text-[#0d1712]">确认轮</Badge>}
                      </div>
                    </div>
                  ))}
                  {filteredEvents.length === 0 && <p className="text-center py-8 text-white/40 text-sm">暂无数据（可调整日期或筛选条件）</p>}
                </div>
              </CardContent>
            )}
          </Card>
        )}

        {modulePrefs.detail && (
          <Card className="glass-card">
            {renderModuleHeader('detail', '详情', <ImageIcon className="w-5 h-5 text-[#b8ddc7]" />)}
            {!moduleCollapse.detail && (
              <CardContent>
                {selectedEvent ? (
                  <Tabs defaultValue="case" className="w-full">
                    <TabsList className="bg-white/5 border border-white/10 grid grid-cols-4">
                      <TabsTrigger value="case">病例</TabsTrigger>
                      <TabsTrigger value="personal">个性化</TabsTrigger>
                      <TabsTrigger value="trace">Trace</TabsTrigger>
                      <TabsTrigger value="kb">知识库</TabsTrigger>
                    </TabsList>
                    <TabsContent value="case" className="space-y-3 mt-3">
                      {selectedEvent.imageUrl ? <div className="rounded-xl overflow-hidden bg-black/30"><img src={selectedEvent.imageUrl} alt="Diagnosis" className="w-full max-h-44 object-contain" /></div> : null}
                      <div className="bg-white/5 rounded-lg p-3">
                        <p className="text-white/60 text-xs mb-1">最终病害 / 置信度</p>
                        <p className="text-lg font-bold text-[#b8ddc7]">{selectedEvent.disease}</p>
                        <p className="text-white/80 text-sm">{selectedEvent.confidencePct !== null ? `${selectedEvent.confidencePct.toFixed(2)}%` : '未记录'}</p>
                      </div>
                      <div className="bg-white/5 rounded-lg p-3">
                        <p className="text-white/60 text-xs mb-1">模型 / 时间 / 档位</p>
                        <p className="text-white text-sm">{selectedEvent.modelName || selectedEvent.modelId}</p>
                        <p className="text-white/65 text-xs mt-1">{safeDisplayTime(selectedEvent.ts)} · {selectedEvent.selectedBranch} · {selectedEvent.confirmRound ? '确认轮' : '首轮'} · 来源：{selectedEvent.finalSource}</p>
                      </div>
                      {hasTreatment && <div className="bg-white/5 rounded-lg p-3 text-white/80 text-sm max-h-36 overflow-y-auto dashboard-scrollbar">{renderTreatment(selectedEvent?.treatment)}</div>}
                    </TabsContent>
                    <TabsContent value="personal" className="space-y-2 mt-3 text-sm text-white/80">
                      <p className="text-white/60">该部分用于案例分析：解释该病例为何输出当前方案。</p>
                      <div>已应用个性化：{selectedEvent.personalizationApplied ? '是' : '否'}</div>
                      <div>触发过滤：{selectedEvent.filtered ? '是' : '否'}</div>
                      <div>个性化原因：{selectedEvent.personalizationReasons.join('；') || '无'}</div>
                      <div>农户/基地：{selectedEvent.farmerId} / {selectedEvent.baseId}</div>
                      <div>农场规模/购药能力：{selectedEvent.farmScale} / {selectedEvent.pesticideAccessLevel}</div>
                      <div>设备/栽培模式：{selectedEvent.equipment.join('、') || '未记录'} / {selectedEvent.cultivationMode}</div>
                      <div>过滤原因：{selectedEvent.filtered ? (selectedEvent.filteredReasons.join('；') || '策略改写') : '未触发过滤'}</div>
                      <div>追问问题：{selectedEvent.followUpQuestions.join('；') || '无'}</div>
                    </TabsContent>
                    <TabsContent value="trace" className="space-y-2 mt-3">
                      {traceSummary.map((item) => (
                        <div key={item.key} className="bg-white/5 rounded-lg p-3 text-xs">
                          <div className="text-[#b8ddc7] text-sm font-medium">{item.agent}</div>
                          <div className="text-white mt-1">{item.title}</div>
                          <div className="text-white/70 mt-1">{item.detail}</div>
                        </div>
                      ))}
                      {traceSummary.length === 0 && <p className="text-white/40 text-sm">暂无可分析的关键节点</p>}
                    </TabsContent>
                    <TabsContent value="kb" className="space-y-2 mt-3 text-sm text-white/80">
                      {kbDetail ? (
                        <>
                          <div className="text-[#b8ddc7] font-semibold">{kbDetail.name}</div>
                          <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">{kbDetail.description || '暂无描述'}</div>
                          <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">治疗：{kbDetail.treatment || '暂无'}</div>
                          <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">预防：{kbDetail.prevention || '暂无'}</div>
                          <div className="flex flex-wrap gap-1">
                            <Badge className={cn('text-xs', kbDetail.actions ? 'bg-[#7aa88e] text-[#0d1712]' : 'bg-white/10 text-white')}>actions</Badge>
                            <Badge className={cn('text-xs', (kbDetail.ingredients?.length ?? 0) > 0 ? 'bg-[#7aa88e] text-[#0d1712]' : 'bg-white/10 text-white')}>ingredients</Badge>
                          </div>
                        </>
                      ) : <p className="text-white/40">暂无知识库摘要</p>}
                    </TabsContent>
                  </Tabs>
                ) : (
                  <div className="text-center py-12 text-white/40">
                    <ImageIcon className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p className="text-sm">请选择左侧病例，查看案例分析详情</p>
                  </div>
                )}
              </CardContent>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
