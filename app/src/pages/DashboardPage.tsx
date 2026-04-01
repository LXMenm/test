import { useState, useEffect, useMemo, useCallback, useRef, type ReactNode } from 'react';
import { BarChart3, Calendar, RefreshCw, Image as ImageIcon, TrendingUp, AlertCircle, LineChart as LineChartIcon, Cpu, Settings2, ChevronDown, ChevronUp, Cloud } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ResponsiveContainer, LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, BarChart, Bar } from 'recharts';
import { cn } from '@/lib/utils';
import { getCultivationModeLabel, getEquipmentLabel, getFarmScaleLabel, getGrowthStageLabel, getPesticideAccessLevelLabel, getRiskPreferenceLabel } from '@/lib/profileLabels';
import { getModelLabel, resolveModelOptions } from '@/lib/modelOptions';
import { fetchTraceEvents } from '@/lib/traceClient';
import { loadAuthUser } from '@/auth';

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
  selectedBranchRaw: string;
  confirmRound: boolean;
  status: string;
  expertReviewStatus: string;
  needConfirm: boolean;
  personalizationApplied: boolean;
  filtered: boolean;
  filteredActions: string[];
  filteredReasons: string[];
  filteredComponents: string[];
  followUpQuestions: string[];
  missingProfileFields: string[];
  llmFailed: boolean;
  workflowDegraded: boolean;
  finalSource: string;
  farmerId: string;
  farmerName: string;
  baseId: string;
  baseName: string;
  farmScale: string;
  pesticideAccessLevel: string;
  equipment: string[];
  cultivationMode: string;
  riskPreference: string;
  preferOrganic: boolean | null;
  harvestWindowDays: number | null;
  growthStage: string;
  environment: string;
  personalizationReasons: string[];
  riskTags: string[];
  riskItems: Array<{ code: string; label: string; reason: string; level?: string; source?: string }>;
  riskSummary: string;
  riskUpdatedAt: string;
  elapsedMs: number | null;
  treatment?: unknown;
  raw: Record<string, unknown>;
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
  llmFailedRate: number;
  avgResponseMs: number;
}

interface FarmerStat {
  farmerId: string;
  farmerName: string;
  count: number;
  filteredRate: number;
  degradedRate: number;
  confirmRoundRate: number;
}

interface BaseStat {
  baseId: string;
  baseName: string;
  count: number;
  diseaseCounts: Record<string, number>;
}

interface KbDetail {
  name: string;
  description: string;
  treatment: string;
  prevention: string;
  ingredients?: string[];
}

interface ProfileListItem {
  id: string;
  name?: string;
  role_type?: 'FARMER' | 'EXPERT' | 'ADMIN';
}

interface KbDiseaseListItem {
  name?: string;
}

interface ProfileDetail {
  farmer_id: string;
  name?: string;
  active_base_id?: string;
  bases?: Record<string, {
    base_id?: string;
    name?: string;
    weather_snapshot?: string;
    last_weather_refresh_at?: string;
    relative_humidity_2m?: number;
    weather_temperature_2m?: number;
    weather_wind_speed_10m?: number;
  }>;
}

interface TraceSummaryItem {
  key: string;
  title: string;
  rows: Array<{ label: string; value: string }>;
}

type SelectedBranchKey = 'FAMILY' | 'MID' | 'ENTERPRISE';

type ModuleKey = 'kpi' | 'trend' | 'model' | 'filter' | 'risk' | 'recent' | 'detail' | 'disease' | 'farmerBase';

type ModulePrefs = Record<ModuleKey, boolean>;
type ModuleCollapse = Record<ModuleKey, boolean>;

const defaultModulePrefs: ModulePrefs = {
  kpi: true,
  trend: true,
  model: true,
  filter: true,
  risk: true,
  recent: true,
  detail: true,
  disease: true,
  farmerBase: true,
};

const defaultCollapse: ModuleCollapse = {
  kpi: false,
  trend: false,
  model: false,
  filter: false,
  risk: false,
  recent: false,
  detail: false,
  disease: false,
  farmerBase: false,
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

const IMAGE_PLACEHOLDER_DATA_URI = `data:image/svg+xml;utf8,${encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">
    <rect width="320" height="180" fill="#10231c"/>
    <rect x="20" y="20" width="280" height="140" rx="14" fill="#173128" stroke="#2e7d63" stroke-width="2"/>
    <circle cx="110" cy="78" r="18" fill="#79b996" opacity="0.85"/>
    <path d="M64 132l42-40 32 28 38-45 64 57H64z" fill="#6da8aa" opacity="0.85"/>
    <text x="160" y="154" text-anchor="middle" fill="#cde8d8" font-size="16" font-family="Arial, sans-serif">图片不可用</text>
  </svg>`,
)}`;

const FALLBACK_REASON_LABELS: Record<string, string> = {
  has_image: '存在图像输入',
  symptoms_missing: '症状信息不足',
  low_confidence: '置信度较低',
  low_margin: '置信度差距较小',
  post_diagnosis: '诊断完成后续流程',
  need_confirm_but_continue: '需确认但继续生成方案',
  retry_with_more_symptoms: '补充症状后复诊',
};

function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function normalizeEventDay(value: unknown): string {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed) return '';
  const directMatch = trimmed.match(/\d{4}-\d{2}-\d{2}/);
  if (directMatch) return directMatch[0];
  const parsed = Date.parse(trimmed);
  return Number.isFinite(parsed) ? formatDate(new Date(parsed)) : '';
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

function toLocalDay(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return '';
  const dt = new Date(parsed);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, '0');
  const d = String(dt.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}


function readableText(value: unknown, fallback = '—'): string {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

function normalizeBranch(value: unknown): SelectedBranchKey | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toUpperCase();
  if (!normalized) return null;
  if (normalized === 'FAMILY' || normalized === 'HOME') return 'FAMILY';
  if (normalized === 'MID' || normalized === 'PRO') return 'MID';
  if (normalized === 'ENTERPRISE') return 'ENTERPRISE';
  return null;
}

function getSelectedBranchLabelOrFallback(value?: string | null): string {
  const normalized = normalizeBranch(value);
  if (normalized === 'FAMILY') return '家庭级';
  if (normalized === 'MID') return '中等规模';
  if (normalized === 'ENTERPRISE') return '企业级';
  return '未分档';
}

function toRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' ? value as Record<string, unknown> : undefined;
}

function sanitizeTraceText(value: unknown): string {
  const text = readableText(value, '').trim();
  if (!text) return '';
  const blocked = ['codex-file-citation', '字段命名若在线上与当前假设差异较大', '不会再退回纯 ok/— 空壳', '审计说明'];
  if (blocked.some((item) => text.includes(item))) return '';
  return text;
}

function resolveSelectedBranch(event: Record<string, unknown>, traceRows?: unknown[]): SelectedBranchKey | null {
  const meta = toRecord(event.meta);
  const treatment = toRecord(event.treatment);
  const payload = toRecord(event.payload);
  const outputs = toRecord(event.outputs);
  const personalization = toRecord(event.personalization);
  const personalizationOutputs = toRecord(event.personalization_outputs);
  const treatmentOutputs = toRecord(outputs?.treatment) ?? toRecord(treatment?.outputs);
  const traceTreatmentBranch = (traceRows ?? [])
    .map((row) => toRecord(row) ?? {})
    .map((row) => toRecord(row.raw) ?? row)
    .filter((row) => normalizeNodeKey(row) === 'treatment')
    .map((row) => toRecord(row.outputs)?.selected_branch)
    .map((item) => normalizeBranch(item))
    .find((item) => item !== null) ?? null;

  const candidates = [
    event.selected_branch,
    treatment?.selected_branch,
    outputs?.selected_branch,
    personalization?.selected_branch,
    personalizationOutputs?.selected_branch,
    treatmentOutputs?.selected_branch,
    payload?.selected_branch,
    toRecord(payload?.treatment)?.selected_branch,
    meta?.selected_branch,
    meta?.branch,
    traceTreatmentBranch,
  ];
  const hit = candidates.map((item) => normalizeBranch(item)).find((item) => item !== null);
  return hit ?? null;
}

function getSelectedBranchLabel(branch?: string | null): string {
  return getSelectedBranchLabelOrFallback(branch);
}

function sourceLabel(value: string): string {
  const normalized = value.trim();
  if (!normalized) return '图像模型';
  if (normalized === 'llm') return 'LLM';
  if (normalized === 'image') return '图像模型';
  if (normalized === 'rule') return '规则';
  if (normalized === 'fallback') return '回退';
  return normalized;
}

function mapFallbackReason(value: unknown): string {
  const raw = readableText(value, '').trim();
  if (!raw) return '';
  return FALLBACK_REASON_LABELS[raw] ?? raw;
}

function formatFallbackReasons(values: unknown): string {
  if (!Array.isArray(values)) return '未触发';
  const items = values.map((item) => mapFallbackReason(item)).filter(Boolean);
  return items.length > 0 ? items.join('、') : '未触发';
}

function getLlmStatusLabel(event: DiagnosisEvent, traceRows?: unknown[]): string {
  const rows = Array.isArray(traceRows) ? traceRows : [];
  const treatmentNode = getLatestNode(buildTraceNodeMap(rows), 'treatment');
  const treatmentOutputs = getNodeOutputs(treatmentNode);
  const raw = event.raw;
  const meta = toRecord(raw.meta);
  const treatment = toRecord(raw.treatment);
  const llmFailed = event.llmFailed
    || treatmentOutputs.llm_failed === true
    || treatment?.llm_failed === true
    || meta?.llm_failed === true;
  const llmFailedReason = readableText(
    raw.llm_failed_reason ?? treatmentOutputs.llm_failed_reason ?? treatment?.llm_failed_reason ?? meta?.llm_failed_reason,
    '',
  );

  if (llmFailed) {
    return llmFailedReason ? `失败，已降级：${llmFailedReason}` : '失败，已降级';
  }
  if (event.workflowDegraded) return '未失败，当前为降级方案';
  if (Object.keys(treatmentOutputs).length > 0 || treatment) return '成功';
  return '未记录';
}

type TraceNodeMap = Record<string, Record<string, unknown>[]>;

interface PersonalizationTraceFallback {
  payload?: Record<string, unknown>;
  meta?: Record<string, unknown>;
  canonicalMeta?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  runtimeSnapshot?: Record<string, unknown>;
}

function toPercent(value: unknown): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return '未提取';
  const pct = num <= 1 ? num * 100 : num;
  return `${pct.toFixed(2)}%`;
}

function toYesNo(value: unknown, fallback = '否'): string {
  if (typeof value === 'boolean') return value ? '是' : '否';
  return fallback;
}

function normalizeNodeKey(event: Record<string, unknown>): string {
  const raw = String(event.agent_id ?? event.agent ?? event.node ?? '').toLowerCase();
  if (raw.includes('personalization')) return 'personalization';
  if (raw.includes('reception') || raw.includes('接待')) return 'reception';
  if (raw.includes('diagnosis') || raw.includes('诊断')) return 'diagnosis';
  if (raw.includes('kb') || raw.includes('retrieval') || raw.includes('知识')) return 'kb_retrieval';
  if (raw.includes('treatment') || raw.includes('治疗')) return 'treatment';
  if (raw.includes('verification') || raw.includes('compliance') || raw.includes('review') || raw.includes('审查')) return 'verification';
  if (raw.includes('supervisor') || raw.includes('监督')) return 'supervisor';
  return raw;
}

function buildTraceNodeMap(rows: unknown[]): TraceNodeMap {
  const map: TraceNodeMap = {};
  rows.forEach((row) => {
    const rec = toRecord(row) ?? {};
    const raw = toRecord(rec.raw) ?? rec;
    const key = normalizeNodeKey(raw);
    if (!key) return;
    map[key] = map[key] ?? [];
    map[key].push(raw);
  });
  return map;
}

function getLatestNode(map: TraceNodeMap, key: string): Record<string, unknown> | undefined {
  const list = map[key] ?? [];
  return list.length > 0 ? list[list.length - 1] : undefined;
}

function getNodeOutputs(node?: Record<string, unknown>): Record<string, unknown> {
  return toRecord(node?.outputs) ?? {};
}

function getPersonalizationTraceFallback(nodeMap?: TraceNodeMap): PersonalizationTraceFallback {
  const node = getLatestNode(nodeMap ?? {}, 'personalization');
  const payload = toRecord(node?.payload);
  return {
    payload,
    meta: toRecord(payload?.meta),
    canonicalMeta: toRecord(payload?.canonical_meta),
    outputs: toRecord(payload?.outputs) ?? getNodeOutputs(node),
    runtimeSnapshot: toRecord(payload?.runtime_snapshot),
  };
}

function textListFromValue(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => readableText(item, '')).filter(Boolean) : [];
}

function pickTextList(...values: unknown[]): string[] {
  for (const value of values) {
    const normalized = textListFromValue(value);
    if (normalized.length > 0) return normalized;
  }
  return [];
}

function pickBoolean(...values: unknown[]): boolean | null {
  for (const value of values) {
    if (typeof value === 'boolean') return value;
  }
  return null;
}

function pickNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const normalized = Number(value);
    if (Number.isFinite(normalized)) return normalized;
  }
  return null;
}

function pickText(...values: unknown[]): string {
  for (const value of values) {
    const normalized = readableText(value, '').trim();
    if (normalized) return normalized;
  }
  return '';
}

function normalizeRiskItems(value: unknown): Array<{ code: string; label: string; reason: string; level?: string; source?: string }> {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const obj = toRecord(item) ?? {};
    return {
      code: readableText(obj.code, ''),
      label: readableText(obj.label, readableText(obj.code, '风险')),
      reason: readableText(obj.reason, ''),
      level: readableText(obj.level, ''),
      source: readableText(obj.source, ''),
    };
  }).filter((item) => Boolean(item.code || item.label || item.reason || item.level || item.source));
}

function resolvePersonalizationInfo(event: DiagnosisEvent, nodeMap?: TraceNodeMap): Array<{ label: string; value: string }> {
  const raw = event.raw;
  const meta = toRecord(raw.meta);
  const traceFallback = getPersonalizationTraceFallback(nodeMap);
  const traceMeta = traceFallback.meta;
  const canonicalMeta = traceFallback.canonicalMeta;
  const traceOutputs = traceFallback.outputs;
  const runtimeSnapshot = traceFallback.runtimeSnapshot;
  const selectedBranch = pickText(
    raw.selected_branch,
    meta?.selected_branch,
    traceOutputs?.selected_branch,
    runtimeSnapshot?.selected_branch,
    canonicalMeta?.selected_branch,
    traceMeta?.selected_branch,
    event.selectedBranchRaw,
  );
  const equipment = pickTextList(
    raw.equipment,
    meta?.equipment,
    canonicalMeta?.equipment,
    traceMeta?.equipment,
  );
  const preferOrganic = pickBoolean(
    raw.prefer_organic,
    meta?.prefer_organic,
    meta?.constraints && toRecord(meta.constraints)?.prefer_organic,
    canonicalMeta?.prefer_organic,
    traceMeta?.prefer_organic,
    event.preferOrganic,
  );
  const harvestWindow = pickNumber(
    raw.harvest_window_days,
    meta?.harvest_window_days,
    meta?.constraints && toRecord(meta.constraints)?.harvest_window_days,
    canonicalMeta?.harvest_window_days,
    traceMeta?.harvest_window_days,
    event.harvestWindowDays,
  );
  const growthStage = pickText(
    raw.growth_stage,
    meta?.growth_stage,
    canonicalMeta?.growth_stage,
    traceMeta?.growth_stage,
    event.growthStage,
  );
  const environment = pickText(
    raw.environment,
    meta?.environment,
    canonicalMeta?.environment,
    traceMeta?.environment,
    event.environment,
  );
  const personalizationApplied = pickBoolean(
    raw.personalization_applied,
    meta?.personalization_applied,
    traceOutputs?.personalization_applied,
    runtimeSnapshot?.personalization_applied,
    event.personalizationApplied,
  );

  return [
    { label: '农户ID / 姓名', value: `${pickText(raw.farmer_id, meta?.farmer_id, canonicalMeta?.farmer_id, traceMeta?.farmer_id, event.farmerId)}${event.farmerName !== '未设置' ? ` / ${event.farmerName}` : ''}` },
    { label: '基地ID / 基地名称', value: `${pickText(raw.base_id, meta?.base_id, canonicalMeta?.base_id, traceMeta?.base_id, event.baseId)}${event.baseName !== '未设置' ? ` / ${event.baseName}` : ''}` },
    { label: '种植规模', value: getFarmScaleLabel(pickText(raw.farm_scale, meta?.farm_scale, canonicalMeta?.farm_scale, traceMeta?.farm_scale, event.farmScale)) },
    { label: '购药能力', value: getPesticideAccessLevelLabel(pickText(raw.pesticide_access_level, meta?.pesticide_access_level, canonicalMeta?.pesticide_access_level, traceMeta?.pesticide_access_level, event.pesticideAccessLevel)) },
    { label: '设备', value: equipment.length > 0 ? equipment.map((item) => getEquipmentLabel(item)).join('、') : '未设置' },
    { label: '栽培模式', value: getCultivationModeLabel(pickText(raw.cultivation_mode, meta?.cultivation_mode, canonicalMeta?.cultivation_mode, traceMeta?.cultivation_mode, event.cultivationMode)) },
    { label: '风险偏好', value: getRiskPreferenceLabel(pickText(raw.risk_preference, meta?.risk_preference, canonicalMeta?.risk_preference, traceMeta?.risk_preference, event.riskPreference)) },
    { label: '个性化已应用', value: personalizationApplied === null ? '未设置' : toYesNo(personalizationApplied) },
    { label: '有机偏好', value: preferOrganic === null ? '未设置' : (preferOrganic ? '是' : '否') },
    { label: '采收窗口', value: harvestWindow === null ? '未设置' : `${harvestWindow}天` },
    { label: '当前判定档位', value: getSelectedBranchLabel(selectedBranch) },
    { label: '生育期', value: getGrowthStageLabel(growthStage) },
    { label: '环境摘要', value: environment || '暂无' },
  ];
}

function toText(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function buildTraceSummary(rows: unknown[]): TraceSummaryItem[] {
  const nodeMap = buildTraceNodeMap(rows);
  const receptionOutputs = getNodeOutputs(getLatestNode(nodeMap, 'reception'));
  const diagnosisOutputs = getNodeOutputs(getLatestNode(nodeMap, 'diagnosis'));
  const imageDiagnosis = toRecord(diagnosisOutputs.image_diagnosis) ?? toRecord(diagnosisOutputs.image_result) ?? {};
  const top3 = Array.isArray(imageDiagnosis?.top3) ? imageDiagnosis.top3 : (Array.isArray(diagnosisOutputs.top3) ? diagnosisOutputs.top3 : []);
  const top1 = Array.isArray(top3) ? top3[0] : undefined;

  const kbOutputs = getNodeOutputs(getLatestNode(nodeMap, 'kb_retrieval'));
  const kbDoc = toRecord(kbOutputs.kb_disease) ?? toRecord(kbOutputs.disease) ?? {};
  const ingredients = Array.isArray(kbDoc.ingredients)
    ? kbDoc.ingredients
    : (Array.isArray(kbOutputs.ingredients) ? kbOutputs.ingredients : []);

  const treatmentOutputs = getNodeOutputs(getLatestNode(nodeMap, 'treatment'));
  const verificationOutputs = getNodeOutputs(getLatestNode(nodeMap, 'verification'));
  const personalizationNode = getLatestNode(nodeMap, 'personalization');
  const personalizationPayload = toRecord(personalizationNode?.payload);
  const personalizationMeta = toRecord(personalizationPayload?.meta) ?? {};
  const personalizationOutputs = toRecord(personalizationPayload?.outputs) ?? {};
  const supervisorHistory = (nodeMap.supervisor ?? []).map((node) => {
    const inputs = toRecord(node.inputs);
    const decision = toRecord(node.decision);
    const outputs = toRecord(node.outputs);
    const currentStep = sanitizeTraceText(inputs?.current_step ?? node.step);
    const nextAction = sanitizeTraceText(decision?.next_action ?? outputs?.next_action);
    const reasonArr = Array.isArray(decision?.reasons)
      ? decision.reasons.map((item) => sanitizeTraceText(item)).filter(Boolean)
      : [];
    if (!currentStep && !nextAction && reasonArr.length === 0) return null;
    return { step: currentStep, nextAction, reason: reasonArr.join('、') };
  }).filter((item): item is { step: string; nextAction: string; reason: string } => Boolean(item));
  const dedupSupervisor = supervisorHistory.filter((item, idx, arr) => (
    arr.findIndex((x) => `${x.step}|${x.nextAction}|${x.reason}` === `${item.step}|${item.nextAction}|${item.reason}`) === idx
  ));

  const make = (key: string, title: string, rowsData: Array<{ label: string; value: string }>) => ({ key, title, rows: rowsData.filter((item) => sanitizeTraceText(item.value)) });

  return [
    make('reception', '接入信息（reception）', [
      { label: '作物类型（reception.outputs.crop_type）', value: sanitizeTraceText(receptionOutputs.crop_type) },
      { label: '症状（reception.outputs.symptoms）', value: Array.isArray(receptionOutputs.symptoms) ? receptionOutputs.symptoms.map((item) => sanitizeTraceText(item)).filter(Boolean).join('、') : sanitizeTraceText(receptionOutputs.symptoms) },
      { label: '图片（reception.outputs.image_path）', value: toText(receptionOutputs.image_path) ? '已上传' : ((receptionOutputs.has_image === true) ? '已上传' : '') },
      { label: '缺失字段（reception.outputs.missing_profile_fields）', value: Array.isArray(receptionOutputs.missing_profile_fields) ? receptionOutputs.missing_profile_fields.map((item) => sanitizeTraceText(item)).filter(Boolean).join('、') : '' },
    ]),
    make('diagnosis', '识别结果（diagnosis）', [
      { label: '最终病害（diagnosis.outputs.final_disease）', value: sanitizeTraceText(diagnosisOutputs.final_disease ?? diagnosisOutputs.disease) },
      { label: '置信度（diagnosis.outputs.final_confidence）', value: Number.isFinite(Number(diagnosisOutputs.final_confidence ?? imageDiagnosis.confidence_pct ?? imageDiagnosis.confidence)) ? toPercent(diagnosisOutputs.final_confidence ?? imageDiagnosis.confidence_pct ?? imageDiagnosis.confidence) : '' },
      { label: '来源（diagnosis.outputs.final_source）', value: sanitizeTraceText(toText(diagnosisOutputs.final_source ?? diagnosisOutputs.source)) },
      { label: 'need_confirm（diagnosis.outputs.need_confirm）', value: typeof diagnosisOutputs.need_confirm === 'boolean' ? toYesNo(diagnosisOutputs.need_confirm) : '' },
      { label: 'top1（diagnosis.outputs.image_top1）', value: Array.isArray(top1)
        ? (toText(top1[0]) ? `${toText(top1[0])} (${toPercent(top1[1])})` : '')
        : (() => {
          const rec = toRecord(top1);
          const d = sanitizeTraceText(rec?.disease ?? diagnosisOutputs.image_top1);
          const p = rec?.prob ?? rec?.prob_pct ?? rec?.confidence ?? diagnosisOutputs.final_confidence;
          return d ? `${d} (${toPercent(p)})` : '';
        })() },
    ]),
    make('kb', '知识库命中（kb_retrieval）', [
      { label: '命中病害（kb_retrieval.outputs.disease）', value: sanitizeTraceText(kbOutputs.disease ?? kbOutputs.disease_name ?? kbDoc.name) },
      { label: 'description/treatment/prevention（kb_retrieval.outputs.*）', value: (toText(kbOutputs.description ?? kbDoc.description) || toText(kbOutputs.treatment ?? kbDoc.treatment) || toText(kbOutputs.prevention ?? kbDoc.prevention)) ? '已命中' : '' },
      { label: 'ingredients（kb_retrieval.outputs.ingredients）', value: ingredients.length > 0 ? ingredients.map((item) => sanitizeTraceText(item)).filter(Boolean).join('、') : '' },
    ]),
    make('treatment', '方案编排（treatment）', [
      { label: 'selected_branch（treatment.outputs.selected_branch）', value: getSelectedBranchLabel(normalizeBranch(treatmentOutputs.selected_branch)) === '未分档' ? '' : getSelectedBranchLabel(normalizeBranch(treatmentOutputs.selected_branch)) },
      { label: 'LLM失败（treatment.outputs.llm_failed）', value: typeof treatmentOutputs.llm_failed === 'boolean' ? toYesNo(treatmentOutputs.llm_failed) : '' },
      { label: '已应用个性化（treatment.outputs.personalization_applied）', value: typeof treatmentOutputs.personalization_applied === 'boolean' ? toYesNo(treatmentOutputs.personalization_applied) : '' },
      { label: '触发过滤（treatment.outputs.filtered）', value: typeof treatmentOutputs.filtered === 'boolean' ? toYesNo(treatmentOutputs.filtered) : '' },
      { label: '过滤原因（treatment.outputs.filtered_reasons）', value: Array.isArray(treatmentOutputs.filtered_reasons) ? treatmentOutputs.filtered_reasons.map((item) => sanitizeTraceText(item)).filter(Boolean).join('、') : '' },
      { label: '个性化理由（treatment.outputs.personalization_reasons）', value: Array.isArray(treatmentOutputs.personalization_reasons) ? treatmentOutputs.personalization_reasons.map((item) => sanitizeTraceText(item)).filter(Boolean).slice(0, 3).join('；') : '' },
    ]),
    make('verification', '农业合规审查（verification）', [
      { label: '审查通过（verification.outputs.passed）', value: typeof verificationOutputs.passed === 'boolean' ? toYesNo(verificationOutputs.passed) : '' },
      { label: '风险等级（verification.outputs.risk_level）', value: sanitizeTraceText(verificationOutputs.risk_level) },
      { label: '审查摘要（verification.outputs.compliance_summary）', value: sanitizeTraceText(verificationOutputs.compliance_summary ?? verificationOutputs.summary) },
      { label: '问题列表（verification.outputs.issues）', value: Array.isArray(verificationOutputs.issues) ? verificationOutputs.issues.map((item) => sanitizeTraceText(item)).filter(Boolean).join('、') : '' },
    ]),
    make('risk', '农业风险解释（risk）', [
      { label: '风险标签（personalization.meta.risk_tags）', value: Array.isArray(personalizationMeta.risk_tags) ? personalizationMeta.risk_tags.map((item) => sanitizeTraceText(item)).filter(Boolean).join('、') : '' },
      { label: '风险摘要（personalization.meta.risk_summary）', value: sanitizeTraceText(personalizationMeta.risk_summary) },
      { label: '方案影响（treatment.outputs.risk_summary）', value: sanitizeTraceText(treatmentOutputs.risk_summary ?? personalizationOutputs.risk_summary) },
    ]),
    make('supervisor', '流程决策（supervisor）', [
      { label: '决策历史（supervisor.inputs/decision/outputs）', value: dedupSupervisor.map((item) => [item.step, item.nextAction, item.reason].filter(Boolean).join(' -> ')).filter(Boolean).join('；') },
    ]),
  ].filter((item) => item.rows.length > 0);
}

function formatResponseMs(value: number, hasData: boolean): string {
  if (!hasData) return '—';
  if (!Number.isFinite(value) || value < 0) return '0 ms';
  if (value >= 100) return `${value.toFixed(0)} ms`;
  if (value >= 10) return `${value.toFixed(1)} ms`;
  return `${value.toFixed(2)} ms`;
}

function formatDisplayDateRange(start: string, end: string): string {
  if (!isValidDateString(start) || !isValidDateString(end)) return '—';
  return `${start} → ${end}`;
}

function navigateToKbDisease(diseaseName: string) {
  const name = diseaseName.trim();
  if (!name || name === '—') return;
  window.history.pushState(null, '', `/kb/${encodeURIComponent(name)}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function getConfidencePct(source: Record<string, unknown>): number | null {
  const finalConfidence = Number(source.final_confidence);
  if (Number.isFinite(finalConfidence)) return finalConfidence <= 1 ? finalConfidence * 100 : finalConfidence;

  const imageResult = source.image_result && typeof source.image_result === 'object'
    ? source.image_result as Record<string, unknown>
    : undefined;

  const confidencePct = Number(imageResult?.confidence_pct);
  if (Number.isFinite(confidencePct)) return confidencePct;

  const confidence = Number(imageResult?.confidence);
  if (Number.isFinite(confidence)) return confidence * 100;

  return null;
}

function normalizeEvent(eventLike: unknown, index: number): DiagnosisEvent {
  const event = eventLike && typeof eventLike === 'object' ? eventLike as Record<string, unknown> : {};
  const imageResult = toRecord(event.image_result);
  const meta = toRecord(event.meta);
  const constraints = toRecord(meta?.constraints);
  const selectedBranchRaw = resolveSelectedBranch(event, Array.isArray(event.trace_events) ? event.trace_events : []);
  const modelId = readableText(meta?.model_id ?? event.model_id, '未记录模型');

  const resolvedImageUrl = typeof event.image_url === 'string' && event.image_url
    ? event.image_url
    : (typeof event.image_id === 'string' && event.image_id
      ? `/uploads/${event.image_id}`
      : (typeof meta?.image_url === 'string' && meta.image_url
        ? meta.image_url
        : (typeof meta?.image_id === 'string' && meta.image_id ? `/uploads/${meta.image_id}` : '')));

  return {
    id: typeof event.id === 'string' ? event.id : `${String(event.ts ?? event.timestamp ?? 'event')}-${index}`,
    ts: typeof event.ts === 'string'
      ? event.ts
      : (typeof event.timestamp === 'string' ? event.timestamp : new Date().toISOString()),
    disease: readableText(event.final_disease ?? imageResult?.disease ?? event.disease ?? event.disease_name, '未识别病害'),
    traceId: typeof event.trace_id === 'string' ? event.trace_id : '',
    imageUrl: resolvedImageUrl,
    modelId,
    modelName: readableText(meta?.model_display_name ?? event.model_display_name, getModelLabel(modelId)),
    selectedBranchRaw: selectedBranchRaw ?? '',
    selectedBranch: getSelectedBranchLabel(selectedBranchRaw),
    confirmRound: event.confirm_round === true,
    status: readableText(event.status, ''),
    expertReviewStatus: readableText(event.expert_review_status, ''),
    needConfirm: event.need_confirm === true,
    personalizationApplied: event.personalization_applied === true || meta?.personalization_applied === true,
    filtered: event.filtered === true || meta?.filtered === true,
    filteredActions: Array.isArray(event.filtered_actions)
      ? event.filtered_actions.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.filtered_actions) ? meta.filtered_actions.map((item) => readableText(item, '')).filter(Boolean) : []),
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
    farmerId: readableText(meta?.farmer_id, '未设置'),
    farmerName: readableText(meta?.farmer_name ?? meta?.name, '未设置'),
    baseId: readableText(meta?.base_id, '未设置'),
    baseName: readableText(meta?.base_name, '未设置'),
    farmScale: readableText(meta?.farm_scale, ''),
    pesticideAccessLevel: readableText(meta?.pesticide_access_level, ''),
    equipment: Array.isArray(event.equipment)
      ? event.equipment.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.equipment) ? meta.equipment.map((item) => readableText(item, '')).filter(Boolean) : []),
    cultivationMode: readableText(meta?.cultivation_mode, ''),
    riskPreference: readableText(meta?.risk_preference, ''),
    preferOrganic: typeof event.prefer_organic === 'boolean'
      ? event.prefer_organic
      : (typeof meta?.prefer_organic === 'boolean'
        ? meta.prefer_organic
        : (typeof constraints?.prefer_organic === 'boolean' ? constraints.prefer_organic : null)),
    harvestWindowDays: Number.isFinite(Number(event.harvest_window_days))
      ? Number(event.harvest_window_days)
      : (Number.isFinite(Number(meta?.harvest_window_days))
        ? Number(meta?.harvest_window_days)
        : (Number.isFinite(Number(constraints?.harvest_window_days)) ? Number(constraints?.harvest_window_days) : null)),
    growthStage: readableText(event.growth_stage ?? meta?.growth_stage, ''),
    environment: readableText(event.environment ?? meta?.environment, ''),
    personalizationReasons: Array.isArray(event.personalization_reasons)
      ? event.personalization_reasons.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.personalization_reasons) ? meta.personalization_reasons.map((item) => readableText(item, '')).filter(Boolean) : []),
    riskTags: Array.isArray(event.risk_tags)
      ? event.risk_tags.map((item) => readableText(item, '')).filter(Boolean)
      : (Array.isArray(meta?.risk_tags) ? meta.risk_tags.map((item) => readableText(item, '')).filter(Boolean) : []),
    riskItems: normalizeRiskItems(event.risk_items ?? meta?.risk_items),
    riskSummary: readableText(event.risk_summary ?? meta?.risk_summary, ''),
    riskUpdatedAt: readableText(event.risk_updated_at ?? meta?.risk_updated_at, ''),
    elapsedMs: Number.isFinite(Number(event.elapsed_ms ?? meta?.elapsed_ms)) ? Number(event.elapsed_ms ?? meta?.elapsed_ms) : null,
    confidencePct: getConfidencePct(event),
    treatment: event.treatment,
    raw: event,
  };
}

function getEventTimestampMs(event: DiagnosisEvent): number {
  const ts = Date.parse(event.ts || '');
  return Number.isNaN(ts) ? 0 : ts;
}

function pickLatestEventsByTrace(events: DiagnosisEvent[]): DiagnosisEvent[] {
  const latestByTrace = new Map<string, DiagnosisEvent>();
  events.forEach((event) => {
    const traceKey = readableText(event.traceId, '');
    if (!traceKey) return;
    const existing = latestByTrace.get(traceKey);
    if (!existing || getEventTimestampMs(event) > getEventTimestampMs(existing)) {
      latestByTrace.set(traceKey, event);
    }
  });
  return Array.from(latestByTrace.values()).sort((a, b) => getEventTimestampMs(b) - getEventTimestampMs(a));
}

export function DashboardPage() {
  const authUser = useMemo(() => loadAuthUser(), []);
  const canViewAllFarmers = authUser?.role === 'ADMIN';
  const scopedFarmerId = canViewAllFarmers ? 'ALL' : (authUser?.linkedFarmerId || authUser?.userId || 'ALL');
  const [presetKey, setPresetKey] = useState<'7d' | '30d' | '90d'>('7d');
  const [allEvents, setAllEvents] = useState<DiagnosisEvent[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [selectedDisease, setSelectedDisease] = useState('ALL');
  const [selectedBranch, setSelectedBranch] = useState('ALL');
  const [selectedPersonalizationStatus, setSelectedPersonalizationStatus] = useState('ALL');
  const [selectedModel, setSelectedModel] = useState('ALL');
  const [profiles, setProfiles] = useState<ProfileListItem[]>([]);
  const [kbDiseases, setKbDiseases] = useState<string[]>([]);
  const [summary, setSummary] = useState<SummaryCards>({
    total: 0,
    today: 0,
    diseaseKinds: 0,
    firstPassRate: 0,
    treatmentSuccessRate: 0,
    filteredRate: 0,
    degradedRate: 0,
    llmFailedRate: 0,
    avgResponseMs: 0,
  });
  const [stats, setStats] = useState<DiseaseStat[]>([]);
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([]);
  const [modelStats, setModelStats] = useState<Array<{ model: string; count: number; success: number; fallback: number; degraded: number; llmFailedRate: number; avgMs: number }>>([]);
  const [filteredReasonDistribution, setFilteredReasonDistribution] = useState<Array<{ name: string; count: number }>>([]);
  const [farmerStats, setFarmerStats] = useState<FarmerStat[]>([]);
  const [baseStats, setBaseStats] = useState<BaseStat[]>([]);
  const [baseTopDiseases, setBaseTopDiseases] = useState<string[]>([]);
  const [selectedFarmerId, setSelectedFarmerId] = useState(scopedFarmerId);
  const [selectedBaseId, setSelectedBaseId] = useState('ALL');
  const [farmerBases, setFarmerBases] = useState<Array<{ id: string; name?: string }>>([]);
  const [kbDetail, setKbDetail] = useState<KbDetail | null>(null);
  const [traceSummary, setTraceSummary] = useState<TraceSummaryItem[]>([]);
  const [traceRawEvents, setTraceRawEvents] = useState<unknown[]>([]);
  const traceFetchAbortRef = useRef<AbortController | null>(null);
  const [showRawTrace, setShowRawTrace] = useState(false);
  const [loading, setLoading] = useState(false);
  const [modulePrefs, setModulePrefs] = useState<ModulePrefs>(() => {
    try {
      const raw = localStorage.getItem('dashboard:module-prefs');
      if (!raw) return defaultModulePrefs;
      return { ...defaultModulePrefs, ...(JSON.parse(raw) as Partial<ModulePrefs>) };
    } catch {
      return defaultModulePrefs;
    }
  });
  const [moduleCollapse, setModuleCollapse] = useState<ModuleCollapse>(defaultCollapse);
  const [weatherCard, setWeatherCard] = useState<{
    farmerId: string;
    baseId: string;
    baseName: string;
    weatherSummary: string;
    humidity: number | null;
    temperature: number | null;
    windSpeed: number | null;
    lastUpdatedAt: string;
  } | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);

  useEffect(() => {
    setSelectedFarmerId(scopedFarmerId);
  }, [scopedFarmerId]);


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

  const getPresetRange = useCallback((key: '7d' | '30d' | '90d'): { start: string; end: string } => {
    const days = key === '30d' ? 30 : key === '90d' ? 90 : 7;
    return getDefaultDateRange(days);
  }, []);

  const effectiveRange = useMemo(() => getPresetRange(presetKey), [getPresetRange, presetKey]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const safeStart = effectiveRange.start;
    const safeEnd = effectiveRange.end;
    const params = new URLSearchParams({
      start: safeStart,
      end: safeEnd,
      farmer_id: selectedFarmerId,
      base_id: selectedBaseId,
      disease: selectedDisease,
      model_id: selectedModel,
      selected_branch: selectedBranch,
      personalization_status: selectedPersonalizationStatus,
    });

    try {
      const eventsResp = await fetch(`/api/events/latest?start=${safeStart}&end=${safeEnd}&limit=5000`);
      const eventsData = await eventsResp.json();
      const eventsList = Array.isArray(eventsData?.events) ? eventsData.events : [];
      const safeEvents = eventsList.map((eventLike: unknown, index: number) => normalizeEvent(eventLike, index));
      setAllEvents(safeEvents);

      const [summaryResp, diseaseResp, timeseriesResp, modelResp, reasonResp, farmerResp, baseResp] = await Promise.all([
        fetch(`/api/stats/summary?${params.toString()}`),
        fetch(`/api/stats/disease?${params.toString()}`),
        fetch(`/api/stats/timeseries?${params.toString()}`),
        fetch(`/api/stats/models?${params.toString()}`),
        fetch(`/api/stats/filter-reasons?${params.toString()}`),
        fetch(`/api/stats/by-farmer?start=${safeStart}&end=${safeEnd}&base_id=${encodeURIComponent(selectedBaseId)}&disease=${encodeURIComponent(selectedDisease)}&model_id=${encodeURIComponent(selectedModel)}&selected_branch=${encodeURIComponent(selectedBranch)}&personalization_status=${encodeURIComponent(selectedPersonalizationStatus)}`),
        fetch(`/api/stats/by-base?start=${safeStart}&end=${safeEnd}&farmer_id=${encodeURIComponent(selectedFarmerId)}&model_id=${encodeURIComponent(selectedModel)}&selected_branch=${encodeURIComponent(selectedBranch)}&personalization_status=${encodeURIComponent(selectedPersonalizationStatus)}`),
      ]);

      const summaryData = await summaryResp.json();
      setSummary({
        total: Number(summaryData?.total ?? 0),
        today: Number(summaryData?.today ?? 0),
        diseaseKinds: Number(summaryData?.disease_kinds ?? 0),
        firstPassRate: Number(summaryData?.first_pass_rate ?? 0),
        treatmentSuccessRate: Number(summaryData?.treatment_success_rate ?? 0),
        filteredRate: Number(summaryData?.filtered_rate ?? 0),
        degradedRate: Number(summaryData?.degraded_rate ?? 0),
        llmFailedRate: Number(summaryData?.llm_failed_rate ?? 0),
        avgResponseMs: Number(summaryData?.avg_response_ms ?? 0),
      });

      const diseaseData = await diseaseResp.json();
      setStats(Array.isArray(diseaseData?.items)
        ? diseaseData.items.map((item: Record<string, unknown>) => ({ disease: String(item?.disease ?? '未识别病害'), count: Number(item?.count ?? 0) }))
        : []);

      const timeseriesData = await timeseriesResp.json();
      setTimeseries(Array.isArray(timeseriesData?.items)
        ? timeseriesData.items.map((item: Record<string, unknown>) => ({ date: String(item?.date ?? ''), count: Number(item?.count ?? 0) }))
        : []);

      const modelData = await modelResp.json();
      setModelStats(Array.isArray(modelData?.items)
        ? modelData.items.map((item: Record<string, unknown>) => ({
          model: String(item?.model ?? '未知模型'),
          count: Number(item?.count ?? 0),
          success: Number(item?.success ?? 0),
          fallback: Number(item?.fallback ?? 0),
          degraded: Number(item?.degraded ?? 0),
          llmFailedRate: Number(item?.llm_failed_rate ?? 0),
          avgMs: Number(item?.avg_response_ms ?? 0),
        }))
        : []);

      const reasonData = await reasonResp.json();
      setFilteredReasonDistribution(Array.isArray(reasonData?.items)
        ? reasonData.items.map((item: Record<string, unknown>) => ({ name: String(item?.name ?? ''), count: Number(item?.count ?? 0) })).filter((item: { name: string }) => Boolean(item.name))
        : []);

      const farmerData = await farmerResp.json();
      setFarmerStats(Array.isArray(farmerData?.items)
        ? farmerData.items.map((item: Record<string, unknown>) => ({
          farmerId: String(item?.farmer_id ?? '未绑定农户'),
          farmerName: String(item?.farmer_name ?? ''),
          count: Number(item?.count ?? 0),
          filteredRate: Number(item?.filtered_rate ?? 0),
          degradedRate: Number(item?.degraded_rate ?? 0),
          confirmRoundRate: Number(item?.confirm_round_rate ?? 0),
        }))
        : []);

      const baseData = await baseResp.json();
      setBaseTopDiseases(Array.isArray(baseData?.top_diseases) ? baseData.top_diseases.map((item: unknown) => String(item)) : []);
      setBaseStats(Array.isArray(baseData?.items)
        ? baseData.items.map((item: Record<string, unknown>) => ({
          baseId: String(item?.base_id ?? '未绑定基地'),
          baseName: String(item?.base_name ?? ''),
          count: Number(item?.count ?? 0),
          diseaseCounts: (item?.disease_counts && typeof item.disease_counts === 'object') ? item.disease_counts as Record<string, number> : {},
        }))
        : []);
    } catch {
      setAllEvents([]);
      setSelectedTraceId(null);
      setSummary({ total: 0, today: 0, diseaseKinds: 0, firstPassRate: 0, treatmentSuccessRate: 0, filteredRate: 0, degradedRate: 0, llmFailedRate: 0, avgResponseMs: 0 });
      setStats([]);
      setTimeseries([]);
      setModelStats([]);
      setFilteredReasonDistribution([]);
      setFarmerStats([]);
      setBaseStats([]);
      setBaseTopDiseases([]);
    } finally {
      setLoading(false);
    }
  }, [effectiveRange.end, effectiveRange.start, selectedFarmerId, selectedBaseId, selectedDisease, selectedModel, selectedBranch, selectedPersonalizationStatus]);

  useEffect(() => {
    const run = async () => {
      try {
        const resp = await fetch('/api/profiles');
        const data = await resp.json();
        const items: Record<string, unknown>[] = Array.isArray(data?.profiles) ? data.profiles : [];
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
    const run = async () => {
      try {
        const resp = await fetch('/api/kb/diseases');
        const data = await resp.json();
        const items: KbDiseaseListItem[] = Array.isArray(data?.items) ? data.items : [];
        setKbDiseases(
          items
            .map((item) => (typeof item?.name === 'string' ? item.name.trim() : ''))
            .filter(Boolean)
            .sort((a, b) => a.localeCompare(b, 'zh-CN')),
        );
      } catch {
        setKbDiseases([]);
      }
    };
    void run();
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

  const weatherRiskTip = useMemo(() => {
    if (!weatherCard) return '请先选择档案与基地，或补充基地经纬度后刷新天气。';
    const summaryText = weatherCard.weatherSummary;
    if (typeof weatherCard.humidity === 'number' && weatherCard.humidity >= 80) {
      return '当前湿度较高，叶部病害风险需关注。';
    }
    if (typeof weatherCard.temperature === 'number' && weatherCard.temperature >= 32) {
      return '当前环境偏炎热，注意高温胁迫与虫害风险。';
    }
    if (typeof weatherCard.temperature === 'number' && weatherCard.temperature <= 10) {
      return '当前温度偏低，注意低温湿害与生长受抑风险。';
    }
    if (/雨|阵雨|雷暴|雾/i.test(summaryText)) {
      return '当前天气偏潮湿，建议关注棚内通风与叶面干燥管理。';
    }
    if (/晴|多云|稳定/i.test(summaryText)) {
      return '当前天气相对稳定，短期环境风险较低。';
    }
    return '请结合田间实际情况持续关注环境波动风险。';
  }, [weatherCard]);
  const isAdminGlobalView = canViewAllFarmers && selectedFarmerId === 'ALL';
  const hasActiveProfile = !isAdminGlobalView && selectedFarmerId !== 'ALL';

  const refreshWeather = useCallback(async (farmerId: string, baseId: string) => {
    if (!farmerId || farmerId === 'ALL' || !baseId || baseId === 'ALL') return;
    setWeatherLoading(true);
    try {
      const resp = await fetch(`/api/profiles/${encodeURIComponent(farmerId)}/bases/${encodeURIComponent(baseId)}/weather/refresh`, { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '天气刷新失败'));
      setWeatherCard((prev) => ({
        farmerId,
        baseId,
        baseName: prev?.baseName || baseId,
        weatherSummary: String(data?.weather_snapshot || '暂无天气摘要'),
        humidity: Number.isFinite(Number(data?.relative_humidity_2m)) ? Number(data.relative_humidity_2m) : null,
        temperature: Number.isFinite(Number(data?.temperature_2m)) ? Number(data.temperature_2m) : null,
        windSpeed: Number.isFinite(Number(data?.wind_speed_10m)) ? Number(data.wind_speed_10m) : null,
        lastUpdatedAt: String(data?.last_weather_refresh_at || ''),
      }));
    } catch {
      // 保持静默，避免破坏主流程
    } finally {
      setWeatherLoading(false);
    }
  }, []);

  useEffect(() => {
    const run = async () => {
      if (!selectedFarmerId || selectedFarmerId === 'ALL') {
        setWeatherCard(null);
        return;
      }
      try {
        const resp = await fetch(`/api/profiles/${encodeURIComponent(selectedFarmerId)}`);
        const data = await resp.json() as ProfileDetail;
        if (!resp.ok) throw new Error();
        const bases = data?.bases && typeof data.bases === 'object' ? data.bases : {};
        const baseId = (selectedBaseId !== 'ALL' && bases[selectedBaseId])
          ? selectedBaseId
          : (data.active_base_id && bases[data.active_base_id] ? data.active_base_id : Object.keys(bases)[0]);
        if (!baseId) {
          setWeatherCard(null);
          return;
        }
        const base = bases[baseId] || {};
        const nextCard = {
          farmerId: selectedFarmerId,
          baseId,
          baseName: String(base?.name || baseId),
          weatherSummary: String(base?.weather_snapshot || '暂无天气摘要'),
          humidity: Number.isFinite(Number(base?.relative_humidity_2m)) ? Number(base?.relative_humidity_2m) : null,
          temperature: Number.isFinite(Number(base?.weather_temperature_2m)) ? Number(base?.weather_temperature_2m) : null,
          windSpeed: Number.isFinite(Number(base?.weather_wind_speed_10m)) ? Number(base?.weather_wind_speed_10m) : null,
          lastUpdatedAt: String(base?.last_weather_refresh_at || ''),
        };
        setWeatherCard(nextCard);
        const today = toLocalDay(new Date().toISOString());
        if (!nextCard.lastUpdatedAt || toLocalDay(nextCard.lastUpdatedAt) !== today) {
          await refreshWeather(selectedFarmerId, baseId);
        }
      } catch {
        setWeatherCard(null);
      }
    };
    void run();
  }, [refreshWeather, selectedBaseId, selectedFarmerId]);

  const diseaseOptions = useMemo(() => kbDiseases, [kbDiseases]);
  const modelOptions = useMemo(() => resolveModelOptions(), []);

  const filteredEvents = useMemo(() => allEvents.filter((event) => {
    if (selectedDisease !== 'ALL' && event.disease !== selectedDisease) return false;
    if (selectedBranch !== 'ALL' && event.selectedBranch !== selectedBranch) return false;
    if (selectedPersonalizationStatus === 'APPLIED' && !event.personalizationApplied) return false;
    if (selectedPersonalizationStatus === 'FILTERED' && !event.filtered) return false;
    if (selectedModel !== 'ALL' && event.modelId !== selectedModel) return false;
    if (selectedFarmerId !== 'ALL' && event.farmerId !== selectedFarmerId) return false;
    if (selectedBaseId !== 'ALL' && event.baseId !== selectedBaseId) return false;
    return true;
  }), [allEvents, selectedDisease, selectedBranch, selectedPersonalizationStatus, selectedModel, selectedFarmerId, selectedBaseId]);

  const recentEvents = useMemo(() => pickLatestEventsByTrace(filteredEvents), [filteredEvents]);
  const selectedEvent = useMemo(
    () => (selectedTraceId ? recentEvents.find((event) => event.traceId === selectedTraceId) : null) ?? recentEvents[0] ?? null,
    [recentEvents, selectedTraceId],
  );


  const modelSummary = useMemo(() => ({
    avgResponseMs: summary.avgResponseMs,
    llmFailedRate: summary.llmFailedRate,
  }), [summary.avgResponseMs, summary.llmFailedRate]);

  const diseaseTrend = useMemo(() => {
    const eventBreakdown = new Map<string, Record<string, number>>();
    const diseaseTotals = new Map<string, number>();
    filteredEvents.forEach((event) => {
      const day = normalizeEventDay(event.ts);
      const diseaseName = readableText(event.disease, '未识别病害');
      diseaseTotals.set(diseaseName, (diseaseTotals.get(diseaseName) ?? 0) + 1);
      if (!day) return;
      const current = eventBreakdown.get(day) ?? {};
      current[diseaseName] = (current[diseaseName] ?? 0) + 1;
      eventBreakdown.set(day, current);
    });
    const topDiseases = (diseaseTotals.size > 0
      ? Array.from(diseaseTotals.entries())
      : stats.map(({ disease, count }) => [disease, count] as const))
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([disease]) => disease);
    const dateRows = timeseries.length > 0
      ? timeseries
      : Array.from(eventBreakdown.keys()).sort().map((date) => ({
        date,
        count: Object.values(eventBreakdown.get(date) ?? {}).reduce((sum, value) => sum + value, 0),
      }));
    const data = dateRows.map((row) => {
      const breakdown = eventBreakdown.get(row.date) ?? {};
      const payload: Record<string, number | string> = { date: row.date, total: row.count };
      topDiseases.forEach((disease) => { payload[disease] = breakdown[disease] ?? 0; });
      return payload;
    });
    return { data, topDiseases };
  }, [filteredEvents, stats, timeseries]);

  useEffect(() => {
    localStorage.setItem('dashboard:module-prefs', JSON.stringify(modulePrefs));
  }, [modulePrefs]);

  useEffect(() => {
    if (selectedTraceId && !recentEvents.some((event) => event.traceId === selectedTraceId)) {
      setSelectedTraceId(recentEvents[0]?.traceId ?? null);
      return;
    }
    if (!selectedTraceId && recentEvents.length > 0) {
      setSelectedTraceId(recentEvents[0].traceId);
    }
  }, [recentEvents, selectedTraceId]);

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
    if (!traceId) {
      traceFetchAbortRef.current?.abort();
      traceFetchAbortRef.current = null;
      setTraceSummary([]);
      setTraceRawEvents([]);
      return;
    }
    const controller = new AbortController();
    traceFetchAbortRef.current?.abort();
    traceFetchAbortRef.current = controller;
    const run = async () => {
      try {
        const resp = await fetchTraceEvents(traceId, {
          source: 'DashboardPage.traceSummary',
          signal: controller.signal,
          debugState: { hasInFlight: true },
        });
        const data = await resp.json();
        if (traceFetchAbortRef.current === controller) {
          traceFetchAbortRef.current = null;
        }
        const rows = Array.isArray(data?.events) ? data.events : [];
        setTraceRawEvents(rows);
        setTraceSummary(buildTraceSummary(rows));
      } catch (error) {
        if (traceFetchAbortRef.current === controller) {
          traceFetchAbortRef.current = null;
        }
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setTraceSummary([]);
        setTraceRawEvents([]);
      }
    };
    run();
    return () => {
      controller.abort();
      if (traceFetchAbortRef.current === controller) {
        traceFetchAbortRef.current = null;
      }
    };
  }, [selectedEvent?.traceId]);

  const traceNodeMap = useMemo(() => buildTraceNodeMap(traceRawEvents), [traceRawEvents]);
  const personalInfoRows = useMemo(() => (
    selectedEvent ? resolvePersonalizationInfo(selectedEvent, traceNodeMap) : []
  ), [selectedEvent, traceNodeMap]);

  const personalizationTabData = useMemo(() => {
    if (!selectedEvent) {
      return {
        reasons: [] as string[],
        filtered: false,
        filteredActions: [] as string[],
        filteredReasons: [] as string[],
        filteredComponents: [] as string[],
        followUpQuestions: [] as string[],
        missingProfileFields: [] as string[],
        riskItems: [] as DiagnosisEvent['riskItems'],
      };
    }

    const raw = selectedEvent.raw;
    const meta = toRecord(raw.meta);
    const traceFallback = getPersonalizationTraceFallback(traceNodeMap);
    const traceOutputs = traceFallback.outputs;
    const runtimeSnapshot = traceFallback.runtimeSnapshot;
    const canonicalMeta = traceFallback.canonicalMeta;
    const traceMeta = traceFallback.meta;

    const reasons = pickTextList(
      raw.personalization_reasons,
      meta?.personalization_reasons,
      traceOutputs?.personalization_reasons,
      runtimeSnapshot?.personalization_reasons,
      selectedEvent.personalizationReasons,
    );
    const filteredActions = pickTextList(
      raw.filtered_actions,
      meta?.filtered_actions,
      traceOutputs?.filtered_actions,
      runtimeSnapshot?.filtered_actions,
      selectedEvent.filteredActions,
    );
    const filteredReasons = pickTextList(
      raw.filtered_reasons,
      meta?.filtered_reasons,
      traceOutputs?.filtered_reasons,
      runtimeSnapshot?.filtered_reasons,
      selectedEvent.filteredReasons,
    );
    const filteredComponents = pickTextList(
      raw.filtered_components,
      meta?.filtered_components,
      traceOutputs?.filtered_components,
      runtimeSnapshot?.filtered_components,
      selectedEvent.filteredComponents,
    );
    const followUpQuestions = pickTextList(
      raw.follow_up_questions,
      meta?.follow_up_questions,
      traceOutputs?.follow_up_questions,
      runtimeSnapshot?.follow_up_questions,
      selectedEvent.followUpQuestions,
    );
    const missingProfileFields = pickTextList(
      raw.missing_profile_fields,
      meta?.missing_profile_fields,
      traceOutputs?.missing_profile_fields,
      runtimeSnapshot?.missing_profile_fields,
      selectedEvent.missingProfileFields,
    );
    const filtered = pickBoolean(
      raw.filtered,
      meta?.filtered,
      traceOutputs?.filtered,
      runtimeSnapshot?.filtered,
      selectedEvent.filtered,
    ) === true;
    const riskItems = normalizeRiskItems(
      raw.risk_items
      ?? meta?.risk_items
      ?? canonicalMeta?.risk_items
      ?? traceMeta?.risk_items
      ?? selectedEvent.riskItems
    );

    return {
      reasons,
      filtered,
      filteredActions,
      filteredReasons,
      filteredComponents,
      followUpQuestions,
      missingProfileFields,
      riskItems,
    };
  }, [selectedEvent, traceNodeMap]);

  const caseDiagnosis = useMemo(() => {
    const disease = selectedEvent?.disease || '—';
    const confidence = selectedEvent?.confidencePct;
    return {
      disease,
      confidenceText: confidence !== null && confidence !== undefined ? `${confidence.toFixed(2)}%` : '—',
    };
  }, [selectedEvent]);

  const caseBranchLabel = useMemo(() => {
    if (!selectedEvent) return '未分档';
    const branch = resolveSelectedBranch(selectedEvent.raw, traceRawEvents)
      ?? normalizeBranch(selectedEvent.selectedBranchRaw);
    return getSelectedBranchLabel(branch);
  }, [selectedEvent, traceRawEvents]);

  const caseTreatmentSummary = useMemo(() => {
    if (!selectedEvent) return { plan: '', prevention: '' };
    const treatmentObj = toRecord(selectedEvent.treatment);
    const plan = sanitizeTraceText(treatmentObj?.plan ?? selectedEvent.raw.treatment_plan);
    const prevention = sanitizeTraceText(treatmentObj?.prevention ?? selectedEvent.raw.prevention_advice);
    return { plan, prevention };
  }, [selectedEvent]);

  const caseVerificationSummary = useMemo(() => {
    if (!selectedEvent) return { passedText: '—', riskLevel: '—', summary: '', issues: '' };
    const verification = toRecord(selectedEvent.raw.verification_result);
    const passed = verification?.passed;
    const issues = Array.isArray(verification?.issues)
      ? verification.issues.map((item) => sanitizeTraceText(item)).filter(Boolean).join('、')
      : '';
    return {
      passedText: typeof passed === 'boolean' ? toYesNo(passed) : '—',
      riskLevel: sanitizeTraceText(verification?.risk_level) || '—',
      summary: sanitizeTraceText(verification?.compliance_summary ?? verification?.summary),
      issues,
    };
  }, [selectedEvent]);

  const caseFallbackSummary = useMemo(() => {
    if (!selectedEvent) return { source: '未触发', reasons: '未触发', llmStatus: '未记录' };
    const raw = selectedEvent.raw;
    const meta = toRecord(raw.meta);
    const reasons = Array.isArray(raw.confirm_reasons) && raw.confirm_reasons.length > 0
      ? raw.confirm_reasons
      : (Array.isArray(raw.fallback_reason) && raw.fallback_reason.length > 0
        ? raw.fallback_reason
        : (Array.isArray(meta?.confirm_reasons) && meta.confirm_reasons.length > 0
          ? meta.confirm_reasons
          : (Array.isArray(meta?.fallback_reason) ? meta.fallback_reason : [])));

    return {
      source: readableText(raw.final_source, selectedEvent.finalSource),
      reasons: formatFallbackReasons(reasons),
      llmStatus: getLlmStatusLabel(selectedEvent, traceRawEvents),
    };
  }, [selectedEvent, traceRawEvents]);

  const riskDistribution = useMemo(() => {
    const counts = new Map<string, number>();
    filteredEvents.forEach((event) => {
      const tags = event.riskTags.length > 0 ? event.riskTags : event.riskItems.map((item) => item.code || item.label).filter(Boolean);
      tags.forEach((tag) => {
        counts.set(tag, (counts.get(tag) || 0) + 1);
      });
    });
    return Array.from(counts.entries())
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [filteredEvents]);

  const riskDiseaseTop = useMemo(() => {
    const byRisk = new Map<string, Map<string, number>>();
    filteredEvents.forEach((event) => {
      const disease = event.disease || '未知病害';
      const tags = event.riskTags.length > 0 ? event.riskTags : event.riskItems.map((item) => item.code || item.label).filter(Boolean);
      tags.forEach((tag) => {
        const diseaseMap = byRisk.get(tag) || new Map<string, number>();
        diseaseMap.set(disease, (diseaseMap.get(disease) || 0) + 1);
        byRisk.set(tag, diseaseMap);
      });
    });
    return Array.from(byRisk.entries()).slice(0, 5).map(([tag, diseaseMap]) => ({
      tag,
      topDiseases: Array.from(diseaseMap.entries()).sort((a, b) => b[1] - a[1]).slice(0, 3),
    }));
  }, [filteredEvents]);

  const kbSummary = useMemo(() => {
    const eventKbSnapshot = toRecord(selectedEvent?.raw?.kb_snapshot);
    const selectedTreatment = toRecord(toRecord(selectedEvent?.raw)?.treatment);
    if (eventKbSnapshot && Object.keys(eventKbSnapshot).length > 0) {
      const eventIngredients = Array.isArray(eventKbSnapshot.ingredients)
        ? eventKbSnapshot.ingredients.map((item) => toText(item)).filter(Boolean)
        : [];
      const rawTreatment = toRecord(selectedEvent?.raw?.treatment);
      return {
        name: toText(eventKbSnapshot.disease ?? eventKbSnapshot.disease_name) || selectedEvent?.disease || '',
        description: toText(eventKbSnapshot.description),
        treatment: toText(eventKbSnapshot.treatment ?? selectedTreatment?.plan ?? selectedEvent?.raw?.treatment_plan),
        prevention: toText(eventKbSnapshot.prevention ?? selectedTreatment?.prevention ?? selectedEvent?.raw?.prevention_advice),
        ingredients: eventIngredients,
      };
    }

    const kbOutputs = getNodeOutputs(getLatestNode(traceNodeMap, 'kb_retrieval'));
    const kbDoc = toRecord(kbOutputs.kb_disease) ?? {};
    const ingredients = Array.isArray(kbOutputs.ingredients)
      ? kbOutputs.ingredients.map((item) => toText(item)).filter(Boolean)
      : (Array.isArray(kbDoc.ingredients) ? kbDoc.ingredients.map((item) => toText(item)).filter(Boolean) : []);
    return {
      name: toText(kbOutputs.disease ?? kbOutputs.disease_name ?? kbDoc.name) || kbDetail?.name || selectedEvent?.disease || '',
      description: toText(kbOutputs.description ?? kbDoc.description) || kbDetail?.description || '',
      treatment: toText(kbOutputs.treatment ?? kbDoc.treatment) || kbDetail?.treatment || '',
      prevention: toText(kbOutputs.prevention ?? kbDoc.prevention) || kbDetail?.prevention || '',
      ingredients,
    };
  }, [traceNodeMap, kbDetail, selectedEvent]);

  const maxCount = Math.max(...stats.map((s) => s.count), 1);

  const setQuickRange = (key: '7d' | '30d' | '90d') => {
    setPresetKey(key);
  };

  const displayStartDate = effectiveRange.start;
  const displayEndDate = effectiveRange.end;
  const displayRangeText = formatDisplayDateRange(displayStartDate, displayEndDate);

  const selectedQuickRange = useMemo(() => {
    if (presetKey === '7d') return 7;
    if (presetKey === '30d') return 30;
    if (presetKey === '90d') return 90;
    return null;
  }, [presetKey]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return (
    <div className="space-y-6 animate-fadeIn overflow-visible">
      <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
        <div className="max-w-[620px]">
          <h1 className="text-[28px] md:text-[30px] leading-tight font-bold text-white md:whitespace-nowrap">番茄病害<span className="text-[#b9dbc7]">诊疗分析看板</span></h1>
          <p className="text-white/60 mt-1 text-sm">诊疗过程的趋势、案例与可解释分析</p>
        </div>

        {/* Date Range Controls */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="h-10 min-w-[280px] px-3 rounded-md border border-white/20 bg-white/5 text-white flex items-center justify-start text-sm">
            <Calendar className="w-4 h-4 mr-2 text-[#c8f7c5]" />
            <span className="text-white/90">{displayRangeText}</span>
          </div>

          <div className="flex items-center gap-1.5">
            {[7, 30, 90].map((days) => (
              <Button
                key={days}
                variant="outline"
                size="sm"
                onClick={() => setQuickRange(`${days}d` as '7d' | '30d' | '90d')}
                className={cn('border-white/20 text-white/70 hover:text-white hover:bg-white/10', selectedQuickRange === days && 'border-[#c8f7c5] text-[#c8f7c5] bg-[#c8f7c5]/10')}
              >
                近{days}天
              </Button>
            ))}
          </div>

          <Button
            onClick={() => { void fetchData(); }}
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
                  farmerBase: '农户/基地维度分析',
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
            <select
              value={selectedFarmerId}
              onChange={(e) => setSelectedFarmerId(e.target.value)}
              className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none disabled:opacity-60"
              disabled={!canViewAllFarmers}
            >
              {canViewAllFarmers ? <option value="ALL">农户：全部</option> : null}
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
              {['家庭级', '中等规模', '企业级', '未分档'].map((item) => <option key={item} value={item} className="bg-[#0b241b] text-[#e8fff0]">{item}</option>)}
            </select>
            <select value={selectedPersonalizationStatus} onChange={(e) => setSelectedPersonalizationStatus(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none">
              <option value="ALL" className="bg-[#0b241b] text-[#e8fff0]">个性化：全部</option>
              <option value="APPLIED" className="bg-[#0b241b] text-[#e8fff0]">已应用个性化</option>
              <option value="FILTERED" className="bg-[#0b241b] text-[#e8fff0]">触发过滤</option>
            </select>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="h-10 bg-[#114a38] border border-[#2e7d63] rounded-lg px-3 text-[#e8fff0] font-medium w-full leading-none">
              <option value="ALL" className="bg-[#0b241b] text-[#e8fff0]">模型：全部</option>
              {modelOptions.map((item: { value: string; label: string }) => <option key={item.value} value={item.value} className="bg-[#0b241b] text-[#e8fff0]">{item.label}</option>)}
            </select>
          </div>
        </CardContent>
      </Card>

      <Card className="glass-card">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-white flex items-center gap-2">
              <Cloud className="w-5 h-5 text-[#b8ddc7]" />
              天气概览
            </CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (weatherCard?.farmerId && weatherCard?.baseId) {
                  void refreshWeather(weatherCard.farmerId, weatherCard.baseId);
                }
              }}
              disabled={isAdminGlobalView || !weatherCard?.baseId || weatherLoading}
            >
              <RefreshCw className={cn('w-4 h-4 mr-1', weatherLoading && 'animate-spin')} />
              刷新天气
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid md:grid-cols-5 gap-3 text-sm">
          {!hasActiveProfile ? (
            <div className="rounded-xl border border-[#c8f7c5]/25 bg-[#1a3228] p-4 md:col-span-5 text-[#c8f7c5]">
              当前为全平台视角，请先选择档案以查看对应天气
            </div>
          ) : (
            <>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 md:col-span-2">
                <p className="text-white/60 text-xs">当前天气摘要</p>
                <p className="text-white mt-1">{weatherCard?.weatherSummary || '暂无天气数据'}</p>
                <p className="text-white/50 text-xs mt-2">基地：{weatherCard?.baseName || '未选择'}</p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                <p className="text-white/60 text-xs">温度</p>
                <p className="text-[#c8f7c5] text-lg font-semibold">{typeof weatherCard?.temperature === 'number' ? `${weatherCard.temperature.toFixed(1)}℃` : '—'}</p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                <p className="text-white/60 text-xs">湿度</p>
                <p className="text-[#c8f7c5] text-lg font-semibold">{typeof weatherCard?.humidity === 'number' ? `${weatherCard.humidity.toFixed(0)}%` : '—'}</p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                <p className="text-white/60 text-xs">风速</p>
                <p className="text-[#c8f7c5] text-lg font-semibold">{typeof weatherCard?.windSpeed === 'number' ? `${weatherCard.windSpeed.toFixed(1)} m/s` : '—'}</p>
              </div>
              <div className="rounded-xl border border-[#c8f7c5]/25 bg-[#1a3228] p-3 md:col-span-5">
                <p className="text-white/60 text-xs">最近天气更新时间：{safeDisplayTime(weatherCard?.lastUpdatedAt || '')}</p>
                <p className="text-[#c8f7c5] mt-1">天气风险提示：{weatherRiskTip}</p>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {modulePrefs.kpi && (
        <Card className="border border-[#2e7d63]/45 bg-[#12231d] shadow-[0_0_0_1px_rgba(121,185,150,0.08),0_14px_40px_rgba(5,18,12,0.4)]">
          {renderModuleHeader('kpi', '核心诊疗总览', <BarChart3 className="w-5 h-5 text-[#b8ddc7]" />)}
          {!moduleCollapse.kpi && (
            <CardContent className="grid sm:grid-cols-2 xl:grid-cols-8 gap-4 pt-1">
              {[
                ['总诊断次数', String(summary.total)],
                ['今日诊断次数', String(summary.today)],
                ['病害种类数（窗口内）', String(summary.diseaseKinds)],
                ['首轮完成率', `${summary.firstPassRate.toFixed(1)}%`],
                ['方案生成成功率', `${summary.treatmentSuccessRate.toFixed(1)}%`],
                ['过滤触发率 / 降级率', `${summary.filteredRate.toFixed(1)}% / ${summary.degradedRate.toFixed(1)}%`],
                ['LLM失败率', `${summary.llmFailedRate.toFixed(1)}%`],
                ['平均响应时间', formatResponseMs(summary.avgResponseMs, summary.total > 0)],
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
                {diseaseTrend.topDiseases.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={diseaseTrend.data} margin={{ left: 8, right: 8, top: 10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(193,227,207,0.18)" />
                      <XAxis dataKey="date" stroke="rgba(229,243,236,0.72)" tick={{ fontSize: 12 }} />
                      <YAxis stroke="rgba(229,243,236,0.72)" allowDecimals={false} tick={{ fontSize: 12 }} />
                      <Tooltip contentStyle={{ background: '#10231c', border: '1px solid rgba(146,194,168,0.5)', color: '#e8fff0' }} />
                      {diseaseTrend.topDiseases.map((disease, index) => (
                        <Bar
                          key={disease}
                          dataKey={disease}
                          stackId="disease"
                          fill={[chartPalette.greenSoft, chartPalette.greenDark, chartPalette.yellowSoft, chartPalette.cyanSoft, chartPalette.coralSoft, chartPalette.purpleSoft][index % 6]}
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-white/40 text-sm">暂无病害趋势数据</div>
                )}
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
                <span>平均响应时间：{formatResponseMs(modelSummary.avgResponseMs, summary.total > 0)}</span>
                <span>LLM 失败率：{modelSummary.llmFailedRate.toFixed(1)}%</span>
              </div>
            </CardContent>
          )}
        </Card>
      )}

      {(modulePrefs.disease || modulePrefs.filter || modulePrefs.risk) && (
        <div className="grid lg:grid-cols-3 gap-6">
          {modulePrefs.disease && (
            <Card className="glass-card flex flex-col">
              {renderModuleHeader('disease', `病害 Top ${Math.min(8, stats.length)}`, <TrendingUp className="w-5 h-5 text-[#c8f7c5]" />)}
              {!moduleCollapse.disease && (
                <CardContent className="flex-1">
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
              )}
            </Card>
          )}

          {modulePrefs.filter && (
            <Card className="glass-card flex flex-col">
              {renderModuleHeader('filter', '过滤原因统计', <TrendingUp className="w-5 h-5 text-[#b8ddc7]" />)}
              {!moduleCollapse.filter && (
                <CardContent className="flex-1">
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

          {modulePrefs.risk && (
            <Card className="glass-card flex flex-col">
              {renderModuleHeader('risk', '风险标签统计', <AlertCircle className="w-5 h-5 text-[#b8ddc7]" />)}
              {!moduleCollapse.risk && (
                <CardContent className="flex-1 space-y-4">
                  <div className="space-y-3">
                    {riskDistribution.map((item) => {
                      const max = Math.max(...riskDistribution.map((x) => x.count), 1);
                      return (
                        <div key={item.tag} className="space-y-1">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-white/70 truncate pr-2">{item.tag}</span>
                            <span className="text-[#b8ddc7]">{item.count}</span>
                          </div>
                          <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                            <div className="h-full bg-[#6fa98b]" style={{ width: `${(item.count / max) * 100}%` }} />
                          </div>
                        </div>
                      );
                    })}
                    {riskDistribution.length === 0 && <p className="text-white/40 text-sm">暂无风险标签统计</p>}
                  </div>

                  <div className="space-y-2">
                    <p className="text-white/60 text-xs">风险标签 × 病害 Top3</p>
                    {riskDiseaseTop.length > 0 ? riskDiseaseTop.map((item) => (
                      <div key={item.tag} className="bg-white/5 rounded-lg p-2 text-xs">
                        <div className="text-[#c8f7c5] mb-1">{item.tag}</div>
                        <div className="text-white/80">{item.topDiseases.map((pair) => `${pair[0]}(${pair[1]})`).join('、') || '暂无'}</div>
                      </div>
                    )) : <p className="text-white/40 text-sm">暂无关联统计</p>}
                  </div>
                </CardContent>
              )}
            </Card>
          )}
        </div>
      )}


      {modulePrefs.farmerBase && (
        <Card className="glass-card">
          {renderModuleHeader('farmerBase', '农户 / 基地维度分析', <TrendingUp className="w-5 h-5 text-[#b8ddc7]" />)}
          {!moduleCollapse.farmerBase && (
            <CardContent className="grid lg:grid-cols-2 gap-6">
              <div className="h-80">
                <p className="text-white/70 text-sm mb-2">农户诊断量排行（含过滤/确认轮/降级率）</p>
                {farmerStats.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={farmerStats} margin={{ left: 8, right: 8, top: 10, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(193,227,207,0.18)" />
                      <XAxis dataKey="farmerId" stroke="rgba(229,243,236,0.72)" tick={{ fontSize: 11 }} interval={0} angle={-15} textAnchor="end" height={56} />
                      <YAxis stroke="rgba(229,243,236,0.72)" allowDecimals={false} tick={{ fontSize: 12 }} />
                      <Tooltip contentStyle={{ background: '#10231c', border: '1px solid rgba(146,194,168,0.5)', color: '#e8fff0' }} />
                      <Bar dataKey="count" fill={chartPalette.greenSoft} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <div className="h-full flex items-center justify-center text-white/40 text-sm">暂无农户维度统计</div>}
              </div>

              <div className="h-80">
                <p className="text-white/70 text-sm mb-2">基地病害构成（Top病害堆叠）</p>
                {baseStats.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={baseStats} margin={{ left: 8, right: 8, top: 10, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(193,227,207,0.18)" />
                      <XAxis dataKey="baseId" stroke="rgba(229,243,236,0.72)" tick={{ fontSize: 11 }} interval={0} angle={-15} textAnchor="end" height={56} />
                      <YAxis stroke="rgba(229,243,236,0.72)" allowDecimals={false} tick={{ fontSize: 12 }} />
                      <Tooltip contentStyle={{ background: '#10231c', border: '1px solid rgba(146,194,168,0.5)', color: '#e8fff0' }} />
                      {baseTopDiseases.map((disease, index) => (
                        <Bar
                          key={disease}
                          dataKey={`diseaseCounts.${disease}`}
                          stackId="disease"
                          fill={[chartPalette.greenSoft, chartPalette.greenDark, chartPalette.yellowSoft, chartPalette.cyanSoft, chartPalette.coralSoft][index % 5]}
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                ) : <div className="h-full flex items-center justify-center text-white/40 text-sm">暂无基地维度统计</div>}
              </div>
            </CardContent>
          )}
        </Card>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {modulePrefs.recent && (
          <Card className="glass-card flex flex-col h-[1000px]">
            {renderModuleHeader('recent', '最近诊断', <Calendar className="w-5 h-5 text-[#b8ddc7]" />)}
            {!moduleCollapse.recent && (
              <CardContent className="flex-1 min-h-0 overflow-hidden">
                <div className="space-y-2 h-full overflow-y-auto dashboard-scrollbar">
                  {recentEvents.slice(0, 80).map((event) => (
                    <div
                      key={event.traceId}
                      onClick={() => setSelectedTraceId(event.traceId)}
                      className={cn('p-3 rounded-xl cursor-pointer transition-all duration-300 border flex gap-3', selectedEvent?.traceId === event.traceId ? 'bg-[#203b31] border-[#84b89d]' : 'bg-white/5 hover:bg-white/10 border-transparent')}
                    >
                      <div className="flex-shrink-0 rounded-lg overflow-hidden border border-white/10 bg-black/20">
                        <img
                          src={event.imageUrl || IMAGE_PLACEHOLDER_DATA_URI}
                          alt={`${event.disease} 缩略图`}
                          className="w-20 h-20 object-cover"
                          loading="lazy"
                          onError={(evt) => {
                            evt.currentTarget.src = IMAGE_PLACEHOLDER_DATA_URI;
                          }}
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-white/60 text-xs">{safeDisplayTime(event.ts)}</p>
                          <Badge variant="outline" className="text-[10px] border-[#c8f7c5]/40 text-[#c8f7c5] flex-shrink-0">
                            {event.confidencePct !== null ? `${event.confidencePct.toFixed(2)}%` : '—'}
                          </Badge>
                        </div>
                        <button
                          type="button"
                          onClick={(evt) => {
                            evt.stopPropagation();
                            navigateToKbDisease(event.disease);
                          }}
                          className="text-white font-medium mt-1 hover:text-[#c8f7c5] text-left truncate block"
                        >
                          {event.disease}
                        </button>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {(event.status === 'pending_expert_review' || event.expertReviewStatus === 'PENDING') && (
                            <Badge className="text-[10px] bg-orange-400 text-black">等待专家复核</Badge>
                          )}
                          {event.expertReviewStatus === 'COMPLETED' && (
                            <Badge className="text-[10px] bg-emerald-400 text-black">已专家复核</Badge>
                          )}
                          {event.personalizationApplied && <Badge className="text-[10px] bg-[#c8f7c5] text-black">个性化</Badge>}
                          {event.filtered && <Badge className="text-[10px] bg-yellow-400 text-black">已过滤</Badge>}
                          {event.confirmRound && <Badge className="text-[10px] bg-blue-400 text-black">确认轮</Badge>}
                        </div>
                      </div>
                    </div>
                  ))}
                  {recentEvents.length === 0 && (
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
        {modulePrefs.detail && (
          <Card className="glass-card lg:col-span-1 flex flex-col h-[1000px]">
            {renderModuleHeader('detail', '详情', <AlertCircle className="w-5 h-5 text-[#c8f7c5]" />)}
            {!moduleCollapse.detail && (
              <CardContent className="flex-1 min-h-0 overflow-hidden">
                {selectedEvent ? (
              <Tabs defaultValue="case" className="w-full flex flex-col h-full">
                <TabsList className="bg-white/5 border border-white/10 grid grid-cols-4">
                  <TabsTrigger value="case">病例</TabsTrigger>
                  <TabsTrigger value="personal">个性化</TabsTrigger>
                  <TabsTrigger value="trace">Trace</TabsTrigger>
                  <TabsTrigger value="kb">知识库</TabsTrigger>
                </TabsList>
                <div className="flex-1 overflow-y-auto dashboard-scrollbar pt-3">
                  <TabsContent value="case" className="space-y-3 mt-0">
                    {selectedEvent.imageUrl ? (
                      <div className="bg-white/5 rounded-lg p-3">
                        <div className="rounded-md overflow-hidden bg-black/30">
                          <img
                            src={selectedEvent.imageUrl || IMAGE_PLACEHOLDER_DATA_URI}
                            alt="诊断图片"
                            className="w-full max-h-56 object-contain"
                            onError={(evt) => {
                              evt.currentTarget.src = IMAGE_PLACEHOLDER_DATA_URI;
                            }}
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="bg-white/5 rounded-lg p-3">
                        <div className="rounded-md overflow-hidden bg-black/30">
                          <img src={IMAGE_PLACEHOLDER_DATA_URI} alt="诊断图片占位" className="w-full max-h-56 object-contain" />
                        </div>
                      </div>
                    )}
                    <div className="bg-white/5 rounded-lg p-3">
                      <p className="text-white/60 text-xs mb-1">最终病害 / 置信度</p>
                      <button
                        type="button"
                        className="text-lg font-bold text-[#c8f7c5] hover:underline"
                        onClick={() => navigateToKbDisease(selectedEvent.disease)}
                      >
                        {caseDiagnosis.disease}
                      </button>
                      <p className="text-white/80 text-sm">{caseDiagnosis.confidenceText}</p>
                    </div>
                    <div className="bg-white/5 rounded-lg p-3">
                      <p className="text-white/60 text-xs mb-1">模型 / 时间 / 档位</p>
                      <p className="text-white text-sm">{selectedEvent.modelName || selectedEvent.modelId}</p>
                      <p className="text-white/60 text-xs mt-1">{safeDisplayTime(selectedEvent.ts)} · {caseBranchLabel}</p>
                      <p className="text-white/60 text-xs mt-1">状态：{selectedEvent.status || '—'} · 专家复核：{selectedEvent.expertReviewStatus || 'NONE'}</p>
                    </div>
                    <div className="bg-white/5 rounded-lg p-3 text-sm text-white/80 space-y-2">
                      <p className="text-white/60 text-xs">处方建议</p>
                      <div className="whitespace-pre-wrap">{caseTreatmentSummary.plan || '暂无处方建议'}</div>
                      {caseTreatmentSummary.prevention && (
                        <div>
                          <p className="text-white/60 text-xs mt-2 mb-1">补充建议</p>
                          <div className="whitespace-pre-wrap">{caseTreatmentSummary.prevention}</div>
                        </div>
                      )}
                    </div>
                    <div className="bg-white/5 rounded-lg p-3 text-sm text-white/80 space-y-1">
                      <p className="text-white/60 text-xs">合规审查（latest event）</p>
                      <div>是否通过：{caseVerificationSummary.passedText}</div>
                      <div>风险等级：{caseVerificationSummary.riskLevel}</div>
                      <div>摘要：{caseVerificationSummary.summary || '暂无'}</div>
                      <div>问题：{caseVerificationSummary.issues || '暂无'}</div>
                    </div>
                    <div className="bg-white/5 rounded-lg p-3 text-sm text-white/80 space-y-2">
                      <p className="text-white/60 text-xs">回退 / LLM 状态</p>
                      <div>结果来源：{caseFallbackSummary.source}</div>
                      <div>回退原因：{caseFallbackSummary.reasons}</div>
                      <div>LLM 状态：{caseFallbackSummary.llmStatus}</div>
                    </div>
                  </TabsContent>
                  <TabsContent value="personal" className="space-y-2 mt-0 text-sm text-white/80">
                    <div className="bg-[#1a3329] border border-[#2e7d63]/40 rounded-lg px-3 py-2 text-[#c8f7c5] text-xs">基础画像信息</div>
                    <div className="grid grid-cols-1 gap-2">
                      {personalInfoRows.map((item) => (
                        <div key={item.label} className="bg-white/5 rounded-lg p-2">
                          <div className="text-white/60 text-xs">{item.label}</div>
                          <div className="text-white mt-1">{item.value || '未设置'}</div>
                        </div>
                      ))}
                    </div>
                    <div className="bg-white/5 rounded-lg p-3 space-y-2">
                      <div className="text-white/60 text-xs">追问 / 档案缺失</div>
                      {personalizationTabData.followUpQuestions.length === 0 && personalizationTabData.missingProfileFields.length === 0 ? (
                        <div className="rounded-lg bg-black/20 px-3 py-2 text-white/70">无后续追问 / 档案完整</div>
                      ) : (
                        <div className="grid grid-cols-1 gap-2">
                          <div className="rounded-lg bg-black/20 px-3 py-2">
                            <div className="text-white/50 text-xs">追问问题</div>
                            <div className="mt-1 text-white">
                              {personalizationTabData.followUpQuestions.length > 0 ? (
                                <ul className="list-disc pl-5 space-y-1">
                                  {personalizationTabData.followUpQuestions.map((question, idx) => <li key={`follow-up-${idx}`}>{question}</li>)}
                                </ul>
                              ) : '无'}
                            </div>
                          </div>
                          <div className="rounded-lg bg-black/20 px-3 py-2">
                            <div className="text-white/50 text-xs">缺失档案字段</div>
                            <div className="mt-1 text-white">
                              {personalizationTabData.missingProfileFields.length > 0 ? (
                                <ul className="list-disc pl-5 space-y-1">
                                  {personalizationTabData.missingProfileFields.map((field) => <li key={field}>{field}</li>)}
                                </ul>
                              ) : '无'}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </TabsContent>
                  <TabsContent value="trace" className="space-y-2 mt-0">
                    {traceSummary.map((item) => (
                      <div key={item.key} className="bg-white/5 rounded-lg p-3 text-xs">
                        <div className="text-[#c8f7c5] mb-2">{item.title}</div>
                        <div className="space-y-1">
                          {item.rows.map((row) => (
                            <div key={`${item.key}-${row.label}`} className="flex items-start justify-between gap-2">
                              <span className="text-white/60">{row.label}</span>
                              <span className="text-white text-right">{row.value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                    {traceSummary.length === 0 && <p className="text-white/40 text-sm">暂无可提炼的 Trace 摘要</p>}
                    <Button size="sm" variant="outline" className="border-white/20 text-white" onClick={() => setShowRawTrace((prev) => !prev)}>{showRawTrace ? '收起原始 Trace' : '查看原始 Trace'}</Button>
                    {showRawTrace && (
                      <pre className="bg-black/30 rounded-lg p-2 text-[11px] text-white/70 max-h-40 overflow-auto">{JSON.stringify(traceRawEvents, null, 2)}</pre>
                    )}
                  </TabsContent>
                  <TabsContent value="kb" className="space-y-2 mt-0 text-sm text-white/80">
                    {kbSummary.name ? (
                      <>
                        <button type="button" className="text-[#c8f7c5] font-semibold hover:underline" onClick={() => navigateToKbDisease(kbSummary.name)}>
                          {kbSummary.name}
                        </button>
                        <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">
                          <div className="text-xs text-white/60 mb-1">病害描述</div>
                          {kbSummary.description || '暂无描述'}
                        </div>
                        <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">
                          <div className="text-xs text-white/60 mb-1">治疗方案</div>
                          {kbSummary.treatment || '暂无'}
                        </div>
                        <div className="bg-white/5 rounded-lg p-2 whitespace-pre-wrap">
                          <div className="text-xs text-white/60 mb-1">预防建议</div>
                          {kbSummary.prevention || '暂无'}
                        </div>
                                              <div className="bg-white/5 rounded-lg p-2">
                            <div className="text-xs text-white/60 mb-2">推荐成分</div>
                            <div className="flex flex-wrap gap-1">
                              {(kbSummary.ingredients.length ?? 0) > 0 ? kbSummary.ingredients.map((ingredient) => (
                                <Badge key={ingredient} className="bg-[#c8f7c5]/20 text-[#c8f7c5]">{ingredient}</Badge>
                              )) : <span className="text-white/40">暂无 ingredients</span>}
                            </div>
                          </div>
                          <Button size="sm" variant="outline" className="border-white/20 text-white" onClick={() => navigateToKbDisease(kbSummary.name)}>
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
                </div>
              </Tabs>
            ) : (
              <div className="text-center py-12 text-white/40">
                <ImageIcon className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p className="text-sm">点击左侧记录查看详情</p>
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
