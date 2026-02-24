import { useState, useEffect } from 'react';
import { BarChart3, Calendar, RefreshCw, Image as ImageIcon, TrendingUp, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

import { cn } from '@/lib/utils';

interface DiseaseStat {
  disease: string;
  count: number;
}

interface DiagnosisEvent {
  id: string;
  ts: string;
  disease: string;
  confidencePct: number | null;
  imageUrl: string;
  modelName: string;
  treatment?: unknown;
  top3?: Array<{ disease: string; confidence: number }>;
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
    imageUrl: typeof event.image_url === 'string' ? event.image_url : '',
    modelName: typeof meta?.model_display_name === 'string'
      ? meta.model_display_name
      : (typeof event.model_display_name === 'string' ? event.model_display_name : '—'),
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
  const [stats, setStats] = useState<DiseaseStat[]>([]);
  const [events, setEvents] = useState<DiagnosisEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<DiagnosisEvent | null>(null);
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
      const [statsResp, eventsResp] = await Promise.all([
        fetch(`/api/stats/disease?start=${safeStart}&end=${safeEnd}`),
        fetch(`/api/events?start=${safeStart}&end=${safeEnd}&limit=50`)
      ]);

      const statsData = await statsResp.json();
      const eventsData = await eventsResp.json();

      console.log('[Dashboard] /api/stats/disease response:', statsData);
      console.log('[Dashboard] /api/events response:', eventsData);

      const statsList = Array.isArray(statsData)
        ? statsData
        : (statsData && typeof statsData === 'object')
          ? (statsData.items ?? statsData.stats ?? statsData.data ?? Object.entries(statsData).map(([name, count]) => ({ name, count })))
          : [];
      const eventsList = Array.isArray(eventsData)
        ? eventsData
        : eventsData?.events ?? eventsData?.items ?? eventsData?.data ?? [];

      const safeStats = Array.isArray(statsList)
        ? statsList.map((item: unknown) => {
            const stat = item && typeof item === 'object' ? item as Record<string, unknown> : {};
            return {
              disease: typeof stat.disease === 'string'
                ? stat.disease
                : (typeof stat.name === 'string' ? stat.name : '-'),
              count: Number(stat.count ?? 0),
            };
          })
        : [];
      const safeEvents = Array.isArray(eventsList)
        ? eventsList.map((eventLike, index) => normalizeEvent(eventLike, index))
        : [];

      setStats(safeStats);
      setEvents(safeEvents);
      setSelectedEvent(safeEvents.length > 0 ? safeEvents[0] : null);
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
      setStats([]);
      setEvents([]);
      setSelectedEvent(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const maxCount = Math.max(...stats.map(s => s.count), 1);

  const setQuickRange = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setEndDate(formatDate(end));
    setStartDate(formatDate(start));
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">
            诊断<span className="text-[#c8f7c5]">数据看板</span>
          </h1>
          <p className="text-white/60 mt-1">查看病害诊断统计与历史记录</p>
        </div>

        {/* Date Range Controls */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-2 bg-white/5 rounded-lg p-1">
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-transparent text-white text-sm px-2 py-1 outline-none"
            />
            <span className="text-white/40">-</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-transparent text-white text-sm px-2 py-1 outline-none"
            />
          </div>
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
              {stats.slice(0, 8).map((stat) => (
                <div key={stat.disease} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-white/80 truncate flex-1">{stat.disease}</span>
                    <span className="text-[#c8f7c5] font-mono ml-2">({stat.count})</span>
                  </div>
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
              {events.map((event) => (
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
                </div>
              ))}
              {events.length === 0 && (
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
              <div className="space-y-4 animate-fadeIn">
                {selectedEvent.imageUrl ? (
                  <div className="rounded-xl overflow-hidden bg-black/30">
                    <img
                      src={selectedEvent.imageUrl}
                      alt="Diagnosis"
                      className="w-full max-h-48 object-contain"
                    />
                  </div>
                ) : (
                  <div className="rounded-xl bg-white/5 border border-white/10 p-6 text-center text-white/40 text-sm">
                    暂无图片
                  </div>
                )}

                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-white/60 text-xs mb-1">最终病害</p>
                    <p className="text-lg font-bold text-[#c8f7c5]">{selectedEvent.disease}</p>
                  </div>

                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-white/60 text-xs mb-1">置信度</p>
                    <p className="text-lg font-bold text-white">{selectedEvent.confidencePct !== null ? `${selectedEvent.confidencePct.toFixed(2)}%` : '—'}</p>
                  </div>

                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-white/60 text-xs mb-1">模型</p>
                    <p className="text-white">{selectedEvent.modelName || '—'}</p>
                  </div>

                  {selectedEvent.top3 && selectedEvent.top3.length > 0 && (
                    <div>
                      <p className="text-white/60 text-xs mb-2">Top 3</p>
                      <div className="space-y-1">
                        {selectedEvent.top3.map((item, idx) => (
                          <div key={idx} className="flex items-center justify-between text-sm">
                            <span className="text-white/80">{item.disease}</span>
                            <span className="text-[#c8f7c5] font-mono">{item.confidence?.toFixed(2)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {hasTreatment && (
                    <div>
                      <p className="text-white/60 text-xs mb-2">治疗方案</p>
                      <div className="bg-white/5 rounded-lg p-3 text-white/80 text-sm max-h-32 overflow-y-auto">
                        {renderTreatment(selectedEvent?.treatment)}
                      </div>
                    </div>
                  )}
                </div>
              </div>
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
