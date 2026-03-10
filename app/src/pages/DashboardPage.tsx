import { useState, useEffect, useMemo, useCallback, type ReactNode } from 'react';
import { BarChart3, Calendar, RefreshCw, Image as ImageIcon, TrendingUp, AlertCircle, LineChart as LineChartIcon, Cpu, ArrowRight, Settings2, ChevronDown, ChevronUp } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Calendar as DateCalendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ResponsiveContainer, LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, BarChart, Bar } from 'recharts';
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
  status: string;
  message: string;
}

type ModuleKey = 'kpi' | 'trend' | 'model' | 'filter' | 'recent' | 'detail' | 'disease';

type ModulePrefs = Record<ModuleKey, boolean>;
type ModuleCollapse = Record<ModuleKey, boolean>;

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


function readableText(value: unknown, fallback = '—'): string {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

function branchLabel(value: string): string {
  const normalized = value.trim();
  if (!normalized) return '未分档';
  if (normalized === 'home') return '家庭档';
  if (normalized === 'pro') return '专业档';
  if (normalized === 'enterprise') return '规模档';
  return normalized;
}

function sourceLabel(value: string): string {
  const normalized = value.trim();
  if (!normalized) return 'image';
  if (normalized === 'llm') return 'LLM';
  if (normalized === 'image') return '图像模型';
  if (normalized === 'fallback') return '回退';
  return normalized;
}

function summarizeTraceRows(rows: unknown[]): TraceSummaryItem[] {
  return rows.slice(0, 12).map((row, index) => {
    const rec = row && typeof row === 'object' ? row as Record<string, unknown> : {};
    return {
      key: readableText(rec.id ?? rec.ts ?? index, String(index)),
      agent: readableText(rec.agent ?? rec.node ?? 'agent', 'agent'),
      status: readableText(rec.status ?? rec.level ?? 'ok', 'ok'),
      message: readableText(rec.message ?? rec.detail ?? rec.content, '—'),
    };
  });
}

function formatDisplayDate(value: string): string {
  if (!isValidDateString(value)) return '—';
  const parsed = new Date(`${value}T00:00:00`);
  return parsed.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function navigateToKbDisease(diseaseName: string) {
  const name = diseaseName.trim();
  if (!name || name === '—') return;
  window.history.pushState(null, '', `/kb/${encodeURIComponent(name)}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
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

export function DashboardPage() {
  const defaultRange = getDefaultDateRange(7);
  const [startDate, setStartDate] = useState(defaultRange.start);
  const [endDate, setEndDate] = useState(defaultRange.end);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [draftStartDate, setDraftStartDate] = useState<Date | undefined>(() => new Date(`${defaultRange.start}T00:00:00`));
  const [draftEndDate, setDraftEndDate] = useState<Date | undefined>(() => new Date(`${defaultRange.end}T00:00:00`));
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


  const renderModuleHeader = (key: ModuleKey, title: string, icon: ReactNode) => (
    <CardHeader className="pb-2">
      <div className="flex items-center justify-between">
        <CardTitle className="text-white flex items-center gap-2">
          {icon}
          {title}
        </CardTitle>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-white/70 hover:text-white hover:bg-white/10"
          onClick={() => setModuleCollapse((prev) => ({ ...prev, [key]: !prev[key] }))}
        >
          {moduleCollapse[key] ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </Button>
      </div>
    </CardHeader>
  );

  const hasTreatment = selectedEvent
    ? typeof selectedEvent.treatment === 'string'
      || (selectedEvent.treatment !== null && typeof selectedEvent.treatment === 'object')
    : false;

  const fetchData = useCallback(async () => {
    setLoading(true);

    const fallbackRange = getDefaultDateRange(7);
    const invalidRange = !isValidDateString(startDate) || !isValidDateString(endDate) || startDate > endDate;
    const safeStart = invalidRange ? fallbackRange.start : startDate;
    const safeEnd = invalidRange ? fallbackRange.end : endDate;
    if (invalidRange) {
      setStartDate(fallbackRange.start);
      setEndDate(fallbackRange.end);
      setDraftStartDate(new Date(`${fallbackRange.start}T00:00:00`));
      setDraftEndDate(new Date(`${fallbackRange.end}T00:00:00`));
    }

    try {
      const eventsResp = await fetch(`/api/events?start=${safeStart}&end=${safeEnd}&limit=5000`);
      const eventsData = await eventsResp.json();
      console.log('[Dashboard] /api/events response:', eventsData);

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
  }, [startDate, endDate]);


  useEffect(() => {
    const run = async () => {
      try {
        const resp = await fetch('/api/profiles');
        const data = await resp.json();
        const items: Record<string, unknown>[] = Array.isArray(data)
          ? data
          : (Array.isArray(data?.items) ? data.items : []);
        setProfiles(items
          .map((item) => ({ id: String(item.id ?? item.farmer_id ?? ''), name: typeof item.name === 'string' ? item.name : undefined }))
          .filter((item) => item.id));
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

  const applyDateRange = (fromDate: Date, toDate: Date) => {
    const from = formatDate(fromDate);
    const to = formatDate(toDate);
    setStartDate(from);
    setEndDate(to);
    setDatePickerOpen(false);
  };

  const setQuickRange = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setDraftStartDate(start);
    setDraftEndDate(end);
    applyDateRange(start, end);
  };

  const onStartDateSelect = (nextStart: Date | undefined) => {
    if (!nextStart) return;
    setDraftStartDate(nextStart);
    if (!draftEndDate || nextStart > draftEndDate) {
      setDraftEndDate(undefined);
      return;
    }
    applyDateRange(nextStart, draftEndDate);
  };

  const onEndDateSelect = (nextEnd: Date | undefined) => {
    if (!nextEnd || !draftStartDate) return;
    if (nextEnd < draftStartDate) {
      setDraftStartDate(nextEnd);
      setDraftEndDate(undefined);
      return;
    }
    setDraftEndDate(nextEnd);
    applyDateRange(draftStartDate, nextEnd);
  };

  const selectedQuickRange = useMemo(() => {
    const today = new Date();
    const end = formatDate(today);
    const daysDiff = (from: string, to: string) => {
      const fromMs = Date.parse(`${from}T00:00:00`);
      const toMs = Date.parse(`${to}T00:00:00`);
      if (!Number.isFinite(fromMs) || !Number.isFinite(toMs)) return null;
      return Math.floor((toMs - fromMs) / (24 * 60 * 60 * 1000)) + 1;
    };
    if (endDate !== end) return null;
    const diff = daysDiff(startDate, endDate);
    return diff === 7 || diff === 30 || diff === 90 ? diff : null;
  }, [startDate, endDate]);

  useEffect(() => {
    setDraftStartDate(new Date(`${startDate}T00:00:00`));
    setDraftEndDate(new Date(`${endDate}T00:00:00`));
  }, [startDate, endDate]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className="space-y-6 animate-fadeIn overflow-visible">
      <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
        <div className="max-w-[620px]">
          <h1 className="text-[28px] md:text-[30px] leading-tight font-bold text-white md:whitespace-nowrap">番茄病害<span className="text-[#b9dbc7]">诊疗联动分析看板</span></h1>
          <p className="text-white/60 mt-1 text-sm">面向基地诊疗过程的趋势、案例与可解释分析</p>
        </div>

        {/* Date Range Controls */}
        <div className="flex items-center gap-2 flex-wrap">
          <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className="border-white/20 bg-white/5 text-white hover:bg-white/10 min-w-[280px] justify-start"
              >
                <Calendar className="w-4 h-4 mr-2 text-[#c8f7c5]" />
                <span className="text-white/70 mr-2">开始</span>
                <span>{formatDisplayDate(startDate)}</span>
                <ArrowRight className="w-3 h-3 mx-2 text-white/40" />
                <span className="text-white/70 mr-2">结束</span>
                <span>{formatDisplayDate(endDate)}</span>
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="z-50 w-auto max-w-[95vw] p-4 bg-[#d7edd4] text-black border border-[#a7c7a1] shadow-2xl rounded-2xl">
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="rounded-lg border border-black/10 bg-white/50 px-3 py-2">
                    <p className="text-black/60">开始日期</p>
                    <p className="font-semibold">{draftStartDate ? formatDisplayDate(formatDate(draftStartDate)) : '请选择开始日期'}</p>
                  </div>
                  <div className="rounded-lg border border-black/10 bg-white/50 px-3 py-2">
                    <p className="text-black/60">结束日期</p>
                    <p className="font-semibold">{draftEndDate ? formatDisplayDate(formatDate(draftEndDate)) : '请选择结束日期'}</p>
                  </div>
                </div>
                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-black/60 mb-2">开始日期</p>
                    <DateCalendar
                      mode="single"
                      selected={draftStartDate}
                      onSelect={onStartDateSelect}
                      month={draftStartDate}
                      className="rounded-xl border border-black/10 bg-white/60"
                      classNames={{
                        day: 'text-black',
                        day_button: 'hover:bg-[#c8f7c5]/60 data-[selected=true]:bg-[#7fbf7b] data-[selected=true]:text-black',
                        range_middle: 'bg-[#b2d8ac]',
                      }}
                    />
                  </div>
                  <div>
                    <p className="text-xs text-black/60 mb-2">结束日期</p>
                    <DateCalendar
                      mode="single"
                      selected={draftEndDate}
                      onSelect={onEndDateSelect}
                      month={draftEndDate ?? draftStartDate}
                      disabled={(day) => (draftStartDate ? day < draftStartDate : false)}
                      modifiers={{ range_middle: draftStartDate && draftEndDate ? { from: draftStartDate, to: draftEndDate } : undefined }}
                      className="rounded-xl border border-black/10 bg-white/60"
                      classNames={{
                        day: 'text-black',
                        day_button: 'hover:bg-[#c8f7c5]/60 data-[selected=true]:bg-[#7fbf7b] data-[selected=true]:text-black',
                        range_middle: 'bg-[#b2d8ac]',
                      }}
                    />
                  </div>
                </div>
              </div>
            </PopoverContent>
          </Popover>

          <div className="flex items-center gap-1.5">
            {[7, 30, 90].map((days) => (
              <Button
                key={days}
                variant="outline"
                size="sm"
                onClick={() => setQuickRange(days)}
                className={cn('border-white/20 text-white/70 hover:text-white hover:bg-white/10', selectedQuickRange === days && 'border-[#c8f7c5] text-[#c8f7c5] bg-[#c8f7c5]/10')}
              >
                近{days}天
              </Button>
            ))}
          </div>
          <Button
            onClick={fetchData}
            disabled={loading}
            className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            title="手动刷新"
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
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

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Disease Stats Chart */}
        <Card className="glass-card lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-[#c8f7c5]" />
              病害 Top {Math.min(8, stats.length)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats.slice(0, 8).map((stat, index) => (
                <div key={stat.disease} className="space-y-1">
                  <div className="flex items-center justify-between text-sm gap-2">
                    <button className="text-white/80 truncate flex-1 text-left hover:text-[#c8f7c5]" onClick={() => navigateToKbDisease(stat.disease)}>
                      #{index + 1} {stat.disease}
                    </button>
                    <button className="text-[#c8f7c5] font-mono ml-2" onClick={() => setSelectedDisease(stat.disease)}>
                      ({stat.count})
                    </button>
                  </div>
                  <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-[#c8f7c5] to-[#4ade80] rounded-full transition-all duration-500"
                      style={{ width: `${(stat.count / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
            </CardContent>
          </Card>
      </div>

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
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-white/60 text-xs">{safeDisplayTime(event.ts)}</p>
                        <Badge variant="outline" className="text-[10px] border-[#c8f7c5]/40 text-[#c8f7c5]">
                          {event.confidencePct !== null ? `${event.confidencePct.toFixed(2)}%` : '—'}
                        </Badge>
                      </div>
                      <button
                        type="button"
                        onClick={(evt) => {
                          evt.stopPropagation();
                          navigateToKbDisease(event.disease);
                        }}
                        className="text-white font-medium mt-1 hover:text-[#c8f7c5] text-left"
                      >
                        {event.disease}
                      </button>
                      <div className="mt-2 flex flex-wrap gap-1">
                        <Badge variant="outline" className="text-[10px] border-white/30 text-white/70">{event.selectedBranch || 'UNKNOWN'}</Badge>
                        {event.personalizationApplied && <Badge className="text-[10px] bg-[#c8f7c5] text-black">个性化</Badge>}
                        {event.filtered && <Badge className="text-[10px] bg-yellow-400 text-black">已过滤</Badge>}
                        {event.confirmRound && <Badge className="text-[10px] bg-blue-400 text-black">确认轮</Badge>}
                      </div>
                    </div>
                  ))}
                  {filteredEvents.length === 0 && (
                    <div className="text-center py-8 text-white/40">
                      <Calendar className="w-10 h-10 mx-auto mb-2 opacity-50" />
                      <p className="text-sm">暂无数据（请先完成一次诊断或调整日期范围）</p>
                    </div>
                  )}
                  </div>
              </CardContent>
            )}
          </Card>
        )}

        {/* Detail Panel */}
        <Card className="glass-card lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-[#c8f7c5]" />
              详情
            </CardTitle>
          </CardHeader>
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
                  {selectedEvent.imageUrl ? (
                    <div className="rounded-xl overflow-hidden bg-black/30">
                      <img src={selectedEvent.imageUrl} alt="Diagnosis" className="w-full max-h-40 object-contain" />
                    </div>
                  ) : null}
                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-white/60 text-xs mb-1">最终病害 / 置信度</p>
                    <button
                      type="button"
                      className="text-lg font-bold text-[#c8f7c5] hover:underline"
                      onClick={() => navigateToKbDisease(selectedEvent.disease)}
                    >
                      {selectedEvent.disease}
                    </button>
                    <p className="text-white/80 text-sm">{selectedEvent.confidencePct !== null ? `${selectedEvent.confidencePct.toFixed(2)}%` : '—'}</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-white/60 text-xs mb-1">模型 / 时间 / 档位</p>
                    <p className="text-white text-sm">{selectedEvent.modelName || selectedEvent.modelId}</p>
                    <p className="text-white/60 text-xs mt-1">{safeDisplayTime(selectedEvent.ts)} · {selectedEvent.selectedBranch}</p>
                  </div>
                  {hasTreatment && <div className="bg-white/5 rounded-lg p-3 text-white/80 text-sm max-h-36 overflow-y-auto">{renderTreatment(selectedEvent?.treatment)}</div>}
                </TabsContent>
                <TabsContent value="personal" className="space-y-2 mt-3 text-sm text-white/80">
                  <div>已应用个性化：{selectedEvent.personalizationApplied ? '是' : '否'}</div>
                  <div>触发过滤：{selectedEvent.filtered ? '是' : '否'}</div>
                  <div>轮次：{selectedEvent.confirmRound ? '确认轮' : '首轮'}</div>
                  <div>过滤原因：{selectedEvent.filteredReasons.join('；') || '无'}</div>
                  <div>过滤成分：{selectedEvent.filteredComponents.join('；') || '无'}</div>
                  <div>缺失字段：{selectedEvent.missingProfileFields.join('；') || '无'}</div>
                  <div>追问问题：{selectedEvent.followUpQuestions.join('；') || '无'}</div>
                </TabsContent>
                <TabsContent value="trace" className="space-y-2 mt-3">
                  {traceSummary.map((item, index) => (
                    <div key={`${item.agent}-${index}`} className="bg-white/5 rounded-lg p-2 text-xs">
                      <div className="text-[#c8f7c5]">{item.agent} · {item.status}</div>
                      <div className="text-white/80 mt-1">{item.message}</div>
                    </div>
                  ))}
                  {traceSummary.length === 0 && <p className="text-white/40 text-sm">暂无 Trace 摘要</p>}
                </TabsContent>
                <TabsContent value="kb" className="space-y-2 mt-3 text-sm text-white/80">
                  {kbDetail ? (
                    <>
                      <button type="button" className="text-[#c8f7c5] font-semibold hover:underline" onClick={() => navigateToKbDisease(kbDetail.name)}>
                        {kbDetail.name}
                      </button>
                      <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">
                        <div className="text-xs text-white/60 mb-1">病害描述</div>
                        {kbDetail.description || '暂无描述'}
                      </div>
                      <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">
                        <div className="text-xs text-white/60 mb-1">治疗方案</div>
                        {kbDetail.treatment || '暂无'}
                      </div>
                      <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">
                        <div className="text-xs text-white/60 mb-1">预防建议</div>
                        {kbDetail.prevention || '暂无'}
                      </div>
                      <div className="bg-white/5 rounded-lg p-2">
                        <div className="text-xs text-white/60 mb-2">处置动作</div>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(kbDetail.actions ?? {}).length > 0 ? Object.entries(kbDetail.actions ?? {}).map(([key, value]) => (
                            <Badge key={key} variant="outline" className="border-[#c8f7c5]/60 text-[#c8f7c5]">{key}：{Array.isArray(value) ? `${value.length}项` : '已配置'}</Badge>
                          )) : <span className="text-white/40">暂无 actions</span>}
                        </div>
                      </div>
                      <div className="bg-white/5 rounded-lg p-2">
                        <div className="text-xs text-white/60 mb-2">推荐成分</div>
                        <div className="flex flex-wrap gap-1">
                          {(kbDetail.ingredients?.length ?? 0) > 0 ? kbDetail.ingredients?.map((ingredient) => (
                            <Badge key={ingredient} className="bg-[#c8f7c5]/20 text-[#c8f7c5]">{ingredient}</Badge>
                          )) : <span className="text-white/40">暂无 ingredients</span>}
                        </div>
                      </div>
                      <Button size="sm" variant="outline" className="border-white/20 text-white" onClick={() => navigateToKbDisease(kbDetail.name)}>
                        查看知识库详情
                      </Button>
                    </>
                  ) : (
                    <div className="bg-white/5 rounded-lg p-3 space-y-2">
                      <p className="text-white/50">暂无知识库详情</p>
                      <Button size="sm" variant="outline" disabled className="border-white/20 text-white/50">查看知识库详情</Button>
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            ) : (
              <div className="text-center py-12 text-white/40">
                <ImageIcon className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p className="text-sm">点击左侧记录查看详情</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
