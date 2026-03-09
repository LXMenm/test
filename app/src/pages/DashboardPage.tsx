import { useState, useEffect, useMemo } from 'react';
import { BarChart3, Calendar, RefreshCw, Image as ImageIcon, TrendingUp, AlertCircle, LineChart as LineChartIcon, Cpu } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Calendar as DateCalendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ResponsiveContainer, LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, BarChart, Bar } from 'recharts';
import type { DateRange } from 'react-day-picker';

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
  treatment?: unknown;
  top3?: Array<{ disease: string; confidence: number }>;
}

interface TimeseriesPoint {
  date: string;
  count: number;
}

interface SummaryCards {
  total: number;
  today: number;
  rangeCount: number;
  diseaseKinds: number;
  firstPassRate: number;
  treatmentSuccessRate: number;
  personalizationApplyRate: number;
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
  const top3Raw = Array.isArray(event.top3)
    ? event.top3
    : (Array.isArray(imageResult?.top3) ? imageResult.top3 : []);

  const top3 = top3Raw
    .map((item) => {
      if (Array.isArray(item) && typeof item[0] === 'string') {
        const confidence = Number(item[1]);
        if (!Number.isFinite(confidence)) return null;
        return { disease: item[0], confidence: confidence <= 1 ? confidence * 100 : confidence };
      }
      if (item && typeof item === 'object') {
        const obj = item as Record<string, unknown>;
        const disease = typeof obj.disease === 'string' ? obj.disease : '';
        const rawConfidence = Number(obj.confidence ?? obj.confidence_pct);
        if (!disease || !Number.isFinite(rawConfidence)) return null;
        return { disease, confidence: rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence };
      }
      return null;
    })
    .filter((item): item is { disease: string; confidence: number } => item !== null);

  return {
    id: typeof event.id === 'string' ? event.id : `${String(event.ts ?? event.timestamp ?? 'event')}-${index}`,
    ts: typeof event.ts === 'string'
      ? event.ts
      : (typeof event.timestamp === 'string' ? event.timestamp : new Date().toISOString()),
    disease: typeof event.final_disease === 'string'
      ? event.final_disease
      : (typeof imageResult?.disease === 'string' ? imageResult.disease : '—'),
    traceId: typeof event.trace_id === 'string' ? event.trace_id : '',
    imageUrl: typeof event.image_url === 'string' ? event.image_url : '',
    modelId: typeof meta?.model_id === 'string'
      ? meta.model_id
      : (typeof event.model_id === 'string' ? event.model_id : '—'),
    modelName: typeof meta?.model_display_name === 'string'
      ? meta.model_display_name
      : (typeof event.model_display_name === 'string' ? event.model_display_name : '—'),
    selectedBranch: typeof event.selected_branch === 'string'
      ? event.selected_branch
      : (typeof meta?.selected_branch === 'string' ? meta.selected_branch : 'UNKNOWN'),
    confirmRound: event.confirm_round === true,
    needConfirm: event.need_confirm === true,
    personalizationApplied: event.personalization_applied === true || meta?.personalization_applied === true,
    filtered: event.filtered === true || meta?.filtered === true,
    filteredReasons: Array.isArray(event.filtered_reasons)
      ? event.filtered_reasons.map((item) => String(item))
      : (Array.isArray(meta?.filtered_reasons) ? meta.filtered_reasons.map((item) => String(item)) : []),
    filteredComponents: Array.isArray(event.filtered_components)
      ? event.filtered_components.map((item) => String(item))
      : (Array.isArray(meta?.filtered_components) ? meta.filtered_components.map((item) => String(item)) : []),
    followUpQuestions: Array.isArray(event.follow_up_questions)
      ? event.follow_up_questions.map((item) => String(item))
      : (Array.isArray(meta?.follow_up_questions) ? meta.follow_up_questions.map((item) => String(item)) : []),
    missingProfileFields: Array.isArray(event.missing_profile_fields)
      ? event.missing_profile_fields.map((item) => String(item))
      : (Array.isArray(meta?.missing_profile_fields) ? meta.missing_profile_fields.map((item) => String(item)) : []),
    llmFailed: event.llm_failed === true || meta?.llm_failed === true,
    workflowDegraded: event.workflow_degraded === true || meta?.workflow_degraded === true,
    confidencePct: getConfidencePct(event),
    treatment: event.treatment,
    top3,
  };
}

function renderTreatment(value: unknown) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') {
    return <div className="whitespace-pre-wrap">{value}</div>;
  }
  if (typeof value === 'object') {
    const data = value as Record<string, unknown>;
    const plan = data.plan;
    const prevention = data.prevention;
    if (typeof plan === 'string' || typeof prevention === 'string') {
      return (
        <div className="space-y-3">
          {typeof plan === 'string' && plan.trim() && (
            <div>
              <div className="text-[#c8f7c5] text-xs mb-1">处方/方案</div>
              <div className="whitespace-pre-wrap">{plan}</div>
            </div>
          )}
          {typeof prevention === 'string' && prevention.trim() && (
            <div>
              <div className="text-[#c8f7c5] text-xs mb-1">预防/管理</div>
              <div className="whitespace-pre-wrap">{prevention}</div>
            </div>
          )}
        </div>
      );
    }
    return <pre className="whitespace-pre-wrap break-words">{JSON.stringify(value, null, 2)}</pre>;
  }
  return <div className="whitespace-pre-wrap">{String(value)}</div>;
}

export function DashboardPage() {
  const defaultRange = getDefaultDateRange(7);
  const [startDate, setStartDate] = useState(defaultRange.start);
  const [endDate, setEndDate] = useState(defaultRange.end);
  const [calendarRange, setCalendarRange] = useState<DateRange | undefined>(() => ({
    from: new Date(`${defaultRange.start}T00:00:00`),
    to: new Date(`${defaultRange.end}T00:00:00`),
  }));
  const [allEvents, setAllEvents] = useState<DiagnosisEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<DiagnosisEvent | null>(null);
  const [selectedDisease, setSelectedDisease] = useState('ALL');
  const [selectedBranch, setSelectedBranch] = useState('ALL');
  const [selectedRound, setSelectedRound] = useState('ALL');
  const [selectedPersonalizationStatus, setSelectedPersonalizationStatus] = useState('ALL');
  const [selectedModel, setSelectedModel] = useState('ALL');
  const [kbDetail, setKbDetail] = useState<KbDetail | null>(null);
  const [traceSummary, setTraceSummary] = useState<Array<{ agent: string; message: string; status: string }>>([]);
  const [loading, setLoading] = useState(false);
  const hasTreatment = selectedEvent
    ? typeof selectedEvent.treatment === 'string'
      || (selectedEvent.treatment !== null && typeof selectedEvent.treatment === 'object')
    : false;

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
      console.log('[Dashboard] /api/events response:', eventsData);

      const eventsList = Array.isArray(eventsData)
        ? eventsData
        : eventsData?.events ?? eventsData?.items ?? eventsData?.data ?? [];
      const safeEvents = Array.isArray(eventsList)
        ? eventsList.map((eventLike, index) => normalizeEvent(eventLike, index))
        : [];

      setAllEvents(safeEvents);
      setSelectedEvent(safeEvents.length > 0 ? safeEvents[0] : null);
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
      setAllEvents([]);
      setSelectedEvent(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const diseaseOptions = useMemo(() => {
    return Array.from(new Set(allEvents.map((event) => event.disease).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [allEvents]);

  const modelOptions = useMemo(() => {
    return Array.from(new Set(allEvents.map((event) => event.modelName || event.modelId).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [allEvents]);

  const filteredEvents = useMemo(() => {
    return allEvents.filter((event) => {
      if (selectedDisease !== 'ALL' && event.disease !== selectedDisease) return false;
      if (selectedBranch !== 'ALL' && event.selectedBranch !== selectedBranch) return false;
      if (selectedRound === 'INITIAL' && event.confirmRound) return false;
      if (selectedRound === 'CONFIRM' && !event.confirmRound) return false;
      if (selectedPersonalizationStatus === 'APPLIED' && !event.personalizationApplied) return false;
      if (selectedPersonalizationStatus === 'FILTERED' && !event.filtered) return false;
      if (selectedModel !== 'ALL' && (event.modelName || event.modelId) !== selectedModel) return false;
      return true;
    });
  }, [allEvents, selectedDisease, selectedBranch, selectedRound, selectedPersonalizationStatus, selectedModel]);

  const stats = useMemo<DiseaseStat[]>(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => {
      map.set(event.disease, (map.get(event.disease) ?? 0) + 1);
    });
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

  const modelStats = useMemo(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => {
      const label = event.modelName || event.modelId || '未知模型';
      map.set(label, (map.get(label) ?? 0) + 1);
    });
    return Array.from(map.entries()).map(([model, count]) => ({ model, count })).sort((a, b) => b.count - a.count).slice(0, 10);
  }, [filteredEvents]);

  const summary = useMemo<SummaryCards>(() => {
    const total = filteredEvents.length;
    const todayKey = formatDate(new Date());
    const today = filteredEvents.filter((event) => {
      const ts = Date.parse(event.ts);
      return Number.isFinite(ts) && formatDate(new Date(ts)) === todayKey;
    }).length;
    const treatmentSuccess = filteredEvents.filter((event) => {
      if (!event.treatment || typeof event.treatment !== 'object') return false;
      const plan = (event.treatment as Record<string, unknown>).plan;
      return typeof plan === 'string' && plan.trim().length > 0;
    }).length;
    const firstPassDone = filteredEvents.filter((event) => !event.confirmRound && !event.needConfirm).length;
    const personalizationAppliedCount = filteredEvents.filter((event) => event.personalizationApplied).length;
    const filteredCount = filteredEvents.filter((event) => event.filtered).length;
    const degradedCount = filteredEvents.filter((event) => event.workflowDegraded || event.llmFailed).length;
    return {
      total,
      today,
      rangeCount: total,
      diseaseKinds: new Set(filteredEvents.map((event) => event.disease)).size,
      firstPassRate: total > 0 ? (firstPassDone / total) * 100 : 0,
      treatmentSuccessRate: total > 0 ? (treatmentSuccess / total) * 100 : 0,
      personalizationApplyRate: total > 0 ? (personalizationAppliedCount / total) * 100 : 0,
      filteredRate: total > 0 ? (filteredCount / total) * 100 : 0,
      degradedRate: total > 0 ? (degradedCount / total) * 100 : 0,
    };
  }, [filteredEvents]);

  const branchDistribution = useMemo(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => {
      const key = event.selectedBranch || 'UNKNOWN';
      map.set(key, (map.get(key) ?? 0) + 1);
    });
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  }, [filteredEvents]);

  const filteredReasonDistribution = useMemo(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => {
      event.filteredReasons.forEach((reason) => {
        map.set(reason, (map.get(reason) ?? 0) + 1);
      });
    });
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count).slice(0, 8);
  }, [filteredEvents]);

  const missingFieldDistribution = useMemo(() => {
    const map = new Map<string, number>();
    filteredEvents.forEach((event) => {
      event.missingProfileFields.forEach((field) => {
        map.set(field, (map.get(field) ?? 0) + 1);
      });
    });
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count).slice(0, 8);
  }, [filteredEvents]);

  useEffect(() => {
    if (!selectedEvent && filteredEvents.length > 0) {
      setSelectedEvent(filteredEvents[0]);
      return;
    }
    if (selectedEvent && !filteredEvents.some((event) => event.id === selectedEvent.id)) {
      setSelectedEvent(filteredEvents[0] ?? null);
    }
  }, [filteredEvents, selectedEvent]);

  useEffect(() => {
    const targetDisease = selectedEvent?.disease;
    if (!targetDisease || targetDisease === '—') {
      setKbDetail(null);
      return;
    }
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
    if (!traceId) {
      setTraceSummary([]);
      return;
    }
    const run = async () => {
      try {
        const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
        const data = await resp.json();
        const rows = Array.isArray(data?.events) ? data.events : [];
        const summaryRows = rows
          .filter((item: unknown) => item && typeof item === 'object')
          .map((item: unknown) => {
            const event = item as Record<string, unknown>;
            return {
              agent: String(event.agent_cn ?? event.agent ?? '-'),
              message: String(event.message ?? event.step_cn ?? event.step ?? '-'),
              status: String(event.status ?? 'info'),
            };
          })
          .slice(-8);
        setTraceSummary(summaryRows);
      } catch {
        setTraceSummary([]);
      }
    };
    run();
  }, [selectedEvent?.traceId]);

  const maxCount = Math.max(...stats.map(s => s.count), 1);

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
    if (range?.from) {
      setStartDate(formatDate(range.from));
    }
    if (range?.to) {
      setEndDate(formatDate(range.to));
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">
            番茄病害<span className="text-[#c8f7c5]">诊疗联动分析看板</span>
          </h1>
          <p className="text-white/60 mt-1">诊断运营、个性化效果、知识库支撑与案例钻取</p>
        </div>

        {/* Date Range Controls */}
        <div className="flex items-center gap-2 flex-wrap">
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className="border-white/20 text-white/80 hover:bg-white/10"
              >
                <Calendar className="w-4 h-4 mr-2" />
                {startDate} - {endDate}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0 bg-[#121212] border border-white/20">
              <DateCalendar
                mode="range"
                numberOfMonths={2}
                selected={calendarRange}
                onSelect={onCalendarRangeSelect}
                defaultMonth={calendarRange?.from}
              />
            </PopoverContent>
          </Popover>
          <div className="flex gap-1">
            {[7, 30, 90].map((days) => (
              <Button
                key={days}
                variant="outline"
                size="sm"
                onClick={() => setQuickRange(days)}
                className="border-white/20 text-white/70 hover:text-white hover:bg-white/10"
              >
                近{days}天
              </Button>
            ))}
          </div>
          <Button
            onClick={fetchData}
            disabled={loading}
            className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      <Card className="glass-card">
        <CardContent className="pt-6">
          <div className="grid md:grid-cols-2 xl:grid-cols-5 gap-3">
            <select value={selectedDisease} onChange={(e) => setSelectedDisease(e.target.value)} className="bg-white/5 border border-white/20 rounded-lg px-3 py-2 text-white">
              <option value="ALL" className="bg-black">病害：全部</option>
              {diseaseOptions.map((item) => <option key={item} value={item} className="bg-black">{item}</option>)}
            </select>
            <select value={selectedBranch} onChange={(e) => setSelectedBranch(e.target.value)} className="bg-white/5 border border-white/20 rounded-lg px-3 py-2 text-white">
              <option value="ALL" className="bg-black">档位：全部</option>
              {['FAMILY', 'MID', 'ENTERPRISE', 'UNKNOWN'].map((item) => <option key={item} value={item} className="bg-black">{item}</option>)}
            </select>
            <select value={selectedRound} onChange={(e) => setSelectedRound(e.target.value)} className="bg-white/5 border border-white/20 rounded-lg px-3 py-2 text-white">
              <option value="ALL" className="bg-black">轮次：全部</option>
              <option value="INITIAL" className="bg-black">首轮</option>
              <option value="CONFIRM" className="bg-black">确认轮</option>
            </select>
            <select value={selectedPersonalizationStatus} onChange={(e) => setSelectedPersonalizationStatus(e.target.value)} className="bg-white/5 border border-white/20 rounded-lg px-3 py-2 text-white">
              <option value="ALL" className="bg-black">个性化：全部</option>
              <option value="APPLIED" className="bg-black">已应用个性化</option>
              <option value="FILTERED" className="bg-black">触发过滤</option>
            </select>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="bg-white/5 border border-white/20 rounded-lg px-3 py-2 text-white">
              <option value="ALL" className="bg-black">模型：全部</option>
              {modelOptions.map((item) => <option key={item} value={item} className="bg-black">{item}</option>)}
            </select>
          </div>
        </CardContent>
      </Card>

      <div className="grid sm:grid-cols-2 xl:grid-cols-6 gap-6">
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">总诊断次数</CardTitle></CardHeader>
          <CardContent><p className="text-3xl font-bold text-[#c8f7c5]">{summary.total}</p></CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">今日诊断次数</CardTitle></CardHeader>
          <CardContent><p className="text-3xl font-bold text-[#c8f7c5]">{summary.today}</p></CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">当前窗口诊断数</CardTitle></CardHeader>
          <CardContent><p className="text-3xl font-bold text-[#c8f7c5]">{summary.rangeCount}</p></CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">病害种类数（窗口内）</CardTitle></CardHeader>
          <CardContent><p className="text-3xl font-bold text-[#c8f7c5]">{summary.diseaseKinds}</p></CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">首轮完成率</CardTitle></CardHeader>
          <CardContent><p className="text-3xl font-bold text-[#c8f7c5]">{summary.firstPassRate.toFixed(1)}%</p></CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">方案生成成功率</CardTitle></CardHeader>
          <CardContent><p className="text-3xl font-bold text-[#c8f7c5]">{summary.treatmentSuccessRate.toFixed(1)}%</p></CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">个性化应用率</CardTitle></CardHeader>
          <CardContent><p className="text-3xl font-bold text-[#c8f7c5]">{summary.personalizationApplyRate.toFixed(1)}%</p></CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white/80 text-sm">过滤触发率 / 降级率</CardTitle></CardHeader>
          <CardContent><p className="text-xl font-bold text-[#c8f7c5]">{summary.filteredRate.toFixed(1)}% / {summary.degradedRate.toFixed(1)}%</p></CardContent>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Card className="glass-card">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <LineChartIcon className="w-5 h-5 text-[#c8f7c5]" />
              诊断趋势（按日）
            </CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={timeseries} margin={{ left: 8, right: 8, top: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.15)" />
                <XAxis dataKey="date" stroke="rgba(255,255,255,0.65)" tick={{ fontSize: 12 }} />
                <YAxis stroke="rgba(255,255,255,0.65)" allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={{ background: '#111', border: '1px solid rgba(255,255,255,0.2)' }} />
                <Line type="monotone" dataKey="count" stroke="#c8f7c5" strokeWidth={3} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="glass-card">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <Cpu className="w-5 h-5 text-[#c8f7c5]" />
              模型调用统计
            </CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            {modelStats.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={modelStats} margin={{ left: 8, right: 8, top: 10, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.15)" />
                  <XAxis dataKey="model" stroke="rgba(255,255,255,0.65)" tick={{ fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={60} />
                  <YAxis stroke="rgba(255,255,255,0.65)" allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip contentStyle={{ background: '#111', border: '1px solid rgba(255,255,255,0.2)' }} />
                  <Bar dataKey="count" fill="#4ade80" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-white/40 text-sm">暂无模型调用数据</div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white">档位分布</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {branchDistribution.map((item) => (
                <div key={item.name} className="flex items-center justify-between text-sm">
                  <span className="text-white/70">{item.name}</span>
                  <span className="text-[#c8f7c5]">{item.count}</span>
                </div>
              ))}
              {branchDistribution.length === 0 && <p className="text-white/40 text-sm">暂无档位统计</p>}
            </div>
          </CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white">过滤原因分布</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {filteredReasonDistribution.map((item) => (
                <div key={item.name} className="flex items-center justify-between text-sm">
                  <span className="text-white/70 truncate pr-2">{item.name}</span>
                  <span className="text-[#c8f7c5]">{item.count}</span>
                </div>
              ))}
              {filteredReasonDistribution.length === 0 && <p className="text-white/40 text-sm">暂无过滤原因统计</p>}
            </div>
          </CardContent>
        </Card>
        <Card className="glass-card">
          <CardHeader><CardTitle className="text-white">缺失字段分布</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {missingFieldDistribution.map((item) => (
                <div key={item.name} className="flex items-center justify-between text-sm">
                  <span className="text-white/70">{item.name}</span>
                  <span className="text-[#c8f7c5]">{item.count}</span>
                </div>
              ))}
              {missingFieldDistribution.length === 0 && <p className="text-white/40 text-sm">暂无缺失字段统计</p>}
            </div>
          </CardContent>
        </Card>
      </div>

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
                  <button className="flex items-center justify-between text-sm w-full text-left" onClick={() => setSelectedDisease(stat.disease)}>
                    <span className="text-white/80 truncate flex-1">#{index + 1} {stat.disease}</span>
                    <span className="text-[#c8f7c5] font-mono ml-2">({stat.count})</span>
                  </button>
                  <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-[#c8f7c5] to-[#4ade80] rounded-full transition-all duration-500"
                      style={{ width: `${(stat.count / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
              {stats.length === 0 && (
                <div className="text-center py-8 text-white/40">
                  <BarChart3 className="w-10 h-10 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">暂无数据（请先完成一次诊断或调整日期范围）</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Recent Diagnoses Table */}
        <Card className="glass-card lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <Calendar className="w-5 h-5 text-[#c8f7c5]" />
              最近诊断
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 max-h-[400px] overflow-y-auto">
              {filteredEvents.slice(0, 80).map((event) => (
                <div
                  key={event.id}
                  onClick={() => setSelectedEvent(event)}
                  className={cn(
                    "p-3 rounded-xl cursor-pointer transition-all duration-300",
                    selectedEvent?.id === event.id
                      ? "bg-[#c8f7c5]/20 border border-[#c8f7c5]/50"
                      : "bg-white/5 hover:bg-white/10 border border-transparent"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-white/40 text-xs font-mono">
                      {safeDisplayTime(event.ts)}
                    </span>
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-xs",
                        (event.confidencePct ?? -1) >= 80
                          ? "border-green-400 text-green-400"
                          : (event.confidencePct ?? -1) >= 50
                          ? "border-yellow-400 text-yellow-400"
                          : "border-red-400 text-red-400"
                      )}
                    >
                      {event.confidencePct !== null ? `${event.confidencePct.toFixed(2)}%` : '—'}
                    </Badge>
                  </div>
                  <p className="text-white font-medium mt-1">{event.disease}</p>
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
        </Card>

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
                    <p className="text-lg font-bold text-[#c8f7c5]">{selectedEvent.disease}</p>
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
                      <div className="text-[#c8f7c5] font-semibold">{kbDetail.name}</div>
                      <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">{kbDetail.description || '暂无描述'}</div>
                      <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">治疗：{kbDetail.treatment || '暂无'}</div>
                      <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">预防：{kbDetail.prevention || '暂无'}</div>
                      <div className="flex flex-wrap gap-1">
                        <Badge className={cn('text-xs', kbDetail.description ? 'bg-[#c8f7c5] text-black' : 'bg-white/10 text-white')}>description</Badge>
                        <Badge className={cn('text-xs', kbDetail.treatment ? 'bg-[#c8f7c5] text-black' : 'bg-white/10 text-white')}>treatment</Badge>
                        <Badge className={cn('text-xs', kbDetail.prevention ? 'bg-[#c8f7c5] text-black' : 'bg-white/10 text-white')}>prevention</Badge>
                        <Badge className={cn('text-xs', kbDetail.actions ? 'bg-[#c8f7c5] text-black' : 'bg-white/10 text-white')}>actions</Badge>
                        <Badge className={cn('text-xs', (kbDetail.ingredients?.length ?? 0) > 0 ? 'bg-[#c8f7c5] text-black' : 'bg-white/10 text-white')}>ingredients</Badge>
                      </div>
                      <Button size="sm" variant="outline" className="border-white/20 text-white" onClick={() => {
                        window.history.pushState(null, '', `/kb/${encodeURIComponent(selectedEvent.disease)}`);
                        window.dispatchEvent(new PopStateEvent('popstate'));
                      }}>跳转知识库详情</Button>
                    </>
                  ) : <p className="text-white/40">暂无知识库摘要</p>}
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
