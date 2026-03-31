import { useEffect, useState, useRef } from 'react';
import type { ChangeEvent, JSX } from 'react';
import { Upload, Send, RefreshCw, AlertCircle, CheckCircle, Loader2, Image as ImageIcon, ChevronDown, ChevronUp, Bell } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { deriveDiagnoseReviewViewFlags } from './diagnoseStatusView';
import { AgentWorkflowPanel } from '@/components/AgentWorkflowPanel';
import {
  getCultivationModeLabel,
  getEquipmentLabel,
  getFarmScaleLabel,
  getPesticideAccessLevelLabel,
  getSelectedBranchLabel,
  normalizeGrowthStage,
  TOMATO_GROWTH_STAGE_OPTIONS,
} from '@/lib/profileLabels';
import { resolveModelOptions } from '@/lib/modelOptions';
import { fetchTraceEvents } from '@/lib/traceClient';
import { calcTracePhaseTiming, formatDurationMs } from '@/components/agentWorkflowTiming';
import { authFetch, loadAuthUser } from '@/auth';

interface DiagnosisResult {
  image_url: string;
  final_disease: string;
  displayConfidencePct: number | null;
  model_display_name: string;
  top3: unknown;
  text_top3?: unknown;
  fusion_top3?: unknown;
  image_result?: unknown;
  treatment: unknown;
  prevention: unknown;
  trace_id: string;
  personalization_applied?: boolean;
  filtered?: boolean;
  filtered_reasons?: string[];
  personalization_reasons?: string[];
  follow_up_questions?: string[];
  missing_profile_fields?: string[];
  profile_farm_scale?: string;
  profile_pesticide_access_level?: string;
  profile_equipment?: string[];
  profile_cultivation_mode?: string;
  selected_branch?: "FAMILY" | "MID" | "ENTERPRISE" | string;
  risk_tags?: string[];
  risk_items?: Array<{ code?: string; label?: string; reason?: string; level?: string; source?: string }>;
  risk_summary?: string;
  risk_updated_at?: string;
  verification_result?: {
    passed?: boolean;
    risk_level?: string;
    issues?: string[];
    must_fix?: string[];
    suggested_rewrite_points?: string[];
    compliance_summary?: string;
  };
  verification_passed?: boolean;
  verification_risk_level?: string;
  verification_issues?: string[];
  verification_summary?: string;
  status?: string;
  confirm_message?: string;
  expert_review_recommended?: boolean;
  expert_review_selected?: boolean;
  expert_review_status?: string;
  expert_review_result?: string;
  expert_review_notes?: string;
  expert_reviewed_at?: string;
  expert_review_actions?: string[];
  treatment_available?: boolean;
  confirm_reasons?: string[];
  fusion_mode?: string;
  image_reliable?: boolean;
  text_reliable?: boolean;
  reliability_issue_types?: string[];
  supplement_mode?: "none" | "text_only" | "image_only" | "image_and_text" | string;
  confirm_reason_code?: string;
  confirm_reason_text?: string;
  recommended_action?: string;
  confirm_ui_mode?: "image" | "text" | "image_and_text" | string;
  confirm_fields?: string[];
}

interface ProfileListItem {
  id: string;
  name?: string;
}

interface ProfileDetail {
  farmer_id: string;
  name?: string;
  active_base_id?: string;
  farm_scale?: string;
  pesticide_access_level?: string;
  equipment?: string[];
  cultivation_mode?: string;
  constraints?: {
    prefer_organic?: boolean;
    harvest_window_days?: number;
    banned_ingredients?: string[];
  };
  bases?: Record<string, {
    base_id?: string;
    name?: string;
    growth_stage?: string;
    sowing_date?: string;
  }>;
}

type BaseOption = { id: string; name?: string };

interface TraceEvent {
  timestamp: string;
  agent: string;
  status: string;
  message?: string;
  raw: Record<string, unknown>;
}

type Top3Candidate = { disease: string; probPct: number };
type PendingExpertItem = {
  trace_id: string;
  farmer_name?: string;
  farmer_id?: string;
};

export function DiagnosePage() {
  const modelOptions = resolveModelOptions();
  const [file, setFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string>('');
  const [symptoms, setSymptoms] = useState('');
  const [cropType, setCropType] = useState('番茄');
  const [growthStage, setGrowthStage] = useState('');
  const [modelId, setModelId] = useState('tf_default');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DiagnosisResult | null>(null);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [latestPayload, setLatestPayload] = useState<Record<string, unknown> | null>(null);
  const [traceId, setTraceId] = useState('');
  const [imageId, setImageId] = useState('');
  const [confirmMode, setConfirmMode] = useState<boolean>(false);
  const [confirmChoice, setConfirmChoice] = useState('other');
  const [confirmSymptoms, setConfirmSymptoms] = useState('');
  const [resubmitFile, setResubmitFile] = useState<File | null>(null);
  const [resubmitPreview, setResubmitPreview] = useState('');
  const [resubmitSubmitting, setResubmitSubmitting] = useState(false);
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);
  const [showRawTrace, setShowRawTrace] = useState(false);
  const [workflowCollapsed, setWorkflowCollapsed] = useState(false);
  const [phase1StartTime, setPhase1StartTime] = useState<number | null>(null);
  const [phase2StartTime, setPhase2StartTime] = useState<number | null>(null);
  const [phase1FrozenMs, setPhase1FrozenMs] = useState<number | null>(null);
  const [workflowRefreshToken, setWorkflowRefreshToken] = useState(0);
  const [timingNowMs, setTimingNowMs] = useState(() => Date.now());
  const [profiles, setProfiles] = useState<ProfileListItem[]>([]);
  const [selectedFarmerId, setSelectedFarmerId] = useState('');
  const [selectedBaseId, setSelectedBaseId] = useState('');
  const [selectedProfile, setSelectedProfile] = useState<ProfileDetail | null>(null);
  const [expertPendingCount, setExpertPendingCount] = useState(0);
  const [expertPendingItems, setExpertPendingItems] = useState<PendingExpertItem[]>([]);
  const [showExpertInbox, setShowExpertInbox] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const traceFetchAbortRef = useRef<AbortController | null>(null);
  const authUser = loadAuthUser();
  const canViewExpertInbox = authUser?.role === 'EXPERT' || authUser?.role === 'ADMIN';

  const navigateToKbDisease = (disease: string) => {
    const name = disease.trim();
    if (!name || name === '未知' || name === '—') return;
    window.history.pushState(null, '', `/kb/${encodeURIComponent(name)}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      const reader = new FileReader();
      reader.onloadend = () => {
        setImagePreview(reader.result as string);
      };
      reader.readAsDataURL(selectedFile);
    }
  };

  const handleResubmitFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] ?? null;
    setResubmitFile(selectedFile);
    if (!selectedFile) {
      setResubmitPreview('');
      return;
    }
    const reader = new FileReader();
    reader.onloadend = () => {
      setResubmitPreview(reader.result as string);
    };
    reader.readAsDataURL(selectedFile);
  };

  const toNumber = (value: unknown): number | null => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  };

  const resolveDisplayConfidencePct = (payload: Record<string, unknown>): number | null => {
    const finalConfidence = toNumber(payload?.final_confidence);
    if (finalConfidence !== null) {
      return finalConfidence <= 1 ? finalConfidence * 100 : finalConfidence;
    }

    const diagnosisEvidence = payload.diagnosis_evidence && typeof payload.diagnosis_evidence === 'object'
      ? payload.diagnosis_evidence as Record<string, unknown>
      : {};
    const evidenceFinalConfidence = toNumber(diagnosisEvidence.final_confidence);
    if (evidenceFinalConfidence !== null) {
      return evidenceFinalConfidence <= 1 ? evidenceFinalConfidence * 100 : evidenceFinalConfidence;
    }

    const imageResult = payload.image_result && typeof payload.image_result === 'object'
      ? payload.image_result as Record<string, unknown>
      : {};

    const imageConfidencePct = toNumber(imageResult.confidence_pct);
    if (imageConfidencePct !== null) {
      return imageConfidencePct;
    }

    const imageConfidence = toNumber(imageResult.confidence);
    if (imageConfidence !== null) {
      return imageConfidence * 100;
    }

    return null;
  };

  const hasLowConfidenceReason = (value: unknown): boolean => {
    if (!Array.isArray(value)) return false;
    return value.some((item) => {
      const reason = String(item || '');
      return reason === 'low_confidence' || reason === 'low_margin';
    });
  };

  const getConfirmReasons = (payloadLike: unknown): string[] => {
    const payload = payloadLike && typeof payloadLike === 'object' ? payloadLike as Record<string, unknown> : {};
    const preferred = Array.isArray(payload.confirm_reasons) ? payload.confirm_reasons : payload.fallback_reason;
    return Array.isArray(preferred) ? preferred.map((item) => String(item)) : [];
  };

  const hasBackendExplain = (payloadLike: unknown): boolean => {
    const payload = payloadLike && typeof payloadLike === 'object' ? payloadLike as Record<string, unknown> : {};
    const reasonCode = typeof payload.confirm_reason_code === 'string' ? payload.confirm_reason_code.trim() : '';
    const uiMode = typeof payload.confirm_ui_mode === 'string' ? payload.confirm_ui_mode.trim() : '';
    return Boolean(reasonCode) && Boolean(uiMode);
  };

  const parseTop3Candidates = (payloadLike: unknown, resultLike?: DiagnosisResult | null, sourceType: 'image' | 'text' | 'fusion' = 'image'): Top3Candidate[] => {
    const payload = payloadLike && typeof payloadLike === 'object' ? payloadLike as Record<string, unknown> : {};
    const imageResult = payload.image_result && typeof payload.image_result === 'object'
      ? payload.image_result as Record<string, unknown>
      : undefined;
    const imageDiagnosis = payload.image_diagnosis && typeof payload.image_diagnosis === 'object'
      ? payload.image_diagnosis as Record<string, unknown>
      : undefined;

    const eventCandidates = Array.isArray(payload.events)
      ? payload.events
        .map((eventLike) => {
          if (!eventLike || typeof eventLike !== 'object') return undefined;
          const event = eventLike as Record<string, unknown>;
          if (String(event.agent ?? '').toLowerCase() !== 'diagnosis') return undefined;
          const outputs = event.outputs && typeof event.outputs === 'object' ? event.outputs as Record<string, unknown> : undefined;
          const fromDiagnosis = outputs?.image_diagnosis && typeof outputs.image_diagnosis === 'object'
            ? outputs.image_diagnosis as Record<string, unknown>
            : undefined;
          return fromDiagnosis?.top3;
        })
        .find((top3) => Array.isArray(top3))
      : undefined;

    let source: unknown[] = [];
    if (sourceType === 'text') {
      // 优先使用text_top3字段
      if (Array.isArray(payload.text_top3)) {
        source = payload.text_top3;
      } else if (Array.isArray(resultLike?.text_top3)) {
        source = resultLike.text_top3;
      } else {
        // 回退到默认top3
        source = Array.isArray(imageResult?.top3)
          ? imageResult.top3
          : Array.isArray(imageDiagnosis?.top3)
            ? imageDiagnosis.top3
            : Array.isArray(eventCandidates)
              ? eventCandidates
              : Array.isArray(resultLike?.top3)
                ? resultLike.top3
                : [];
      }
    } else if (sourceType === 'fusion') {
      // 优先使用fusion_top3字段
      if (Array.isArray(payload.fusion_top3)) {
        source = payload.fusion_top3;
      } else if (Array.isArray(resultLike?.fusion_top3)) {
        source = resultLike.fusion_top3;
      } else {
        // 回退到默认top3
        source = Array.isArray(imageResult?.top3)
          ? imageResult.top3
          : Array.isArray(imageDiagnosis?.top3)
            ? imageDiagnosis.top3
            : Array.isArray(eventCandidates)
              ? eventCandidates
              : Array.isArray(resultLike?.top3)
                ? resultLike.top3
                : [];
      }
    } else {
      // 图像top3
      source = Array.isArray(imageResult?.top3)
        ? imageResult.top3
        : Array.isArray(imageDiagnosis?.top3)
          ? imageDiagnosis.top3
          : Array.isArray(eventCandidates)
            ? eventCandidates
            : Array.isArray(resultLike?.top3)
              ? resultLike.top3
              : Array.isArray((resultLike?.image_result && typeof resultLike.image_result === 'object')
                ? (resultLike.image_result as Record<string, unknown>).top3
                : undefined)
                ? ((resultLike?.image_result as Record<string, unknown>).top3 as unknown[])
                : [];
    }

    const mapped = source.map((item): Top3Candidate | null => {
      if (!item || typeof item !== 'object') {
        if (Array.isArray(item) && typeof item[0] === 'string') {
          const probRaw = Number(item[1]);
          if (!Number.isFinite(probRaw)) return null;
          return { disease: item[0], probPct: probRaw <= 1 ? probRaw * 100 : probRaw };
        }
        return null;
      }

      if (Array.isArray(item) && typeof item[0] === 'string') {
        const probRaw = Number(item[1]);
        if (!Number.isFinite(probRaw)) return null;
        return { disease: item[0], probPct: probRaw <= 1 ? probRaw * 100 : probRaw };
      }

      const record = item as Record<string, unknown>;
      const disease = typeof record.disease === 'string' ? record.disease.trim() : '';
      if (!disease) return null;
      const rawProbPct = toNumber(record.prob_pct) ?? toNumber(record.probPct);
      const rawProb = toNumber(record.prob);
      const probPct = rawProbPct ?? (rawProb !== null ? rawProb * 100 : null);
      if (probPct === null || !Number.isFinite(probPct)) return null;
      return { disease, probPct };
    }).filter((item): item is Top3Candidate => item !== null && Boolean(item.disease));

    return mapped.sort((a, b) => b.probPct - a.probPct).slice(0, 3);
  };

  const deriveNeedConfirm = (
    payloadLike: unknown,
    candidates: Top3Candidate[],
    displayConfidencePct: number | null,
  ): boolean => {
    const payload = payloadLike && typeof payloadLike === 'object' ? payloadLike as Record<string, unknown> : {};
    if (hasBackendExplain(payload)) {
      return payload.need_confirm === true;
    }
    if (payload.need_confirm === true) return true;
    if (hasLowConfidenceReason(getConfirmReasons(payload))) return true;

    const imageResult = payload.image_result && typeof payload.image_result === 'object'
      ? payload.image_result as Record<string, unknown>
      : undefined;
    const diseaseText = typeof imageResult?.disease === 'string' ? imageResult.disease : '';
    if (diseaseText.includes('置信度不足')) return true;
    if (displayConfidencePct !== null && displayConfidencePct < 60) return true;

    if (Array.isArray(payload.events)) {
      const hasDiagnosisNeedConfirm = payload.events.some((eventLike) => {
        if (!eventLike || typeof eventLike !== 'object') return false;
        const event = eventLike as Record<string, unknown>;
        if (String(event.agent ?? '').toLowerCase() !== 'diagnosis') return false;
        const outputs = event.outputs && typeof event.outputs === 'object' ? event.outputs as Record<string, unknown> : undefined;
        return outputs?.need_confirm === true || hasLowConfidenceReason(getConfirmReasons(outputs));
      });
      if (hasDiagnosisNeedConfirm) return true;
    }

    return candidates.length > 0 && displayConfidencePct !== null && displayConfidencePct < 60;
  };

  const normalizeRiskItems = (value: unknown) => {
    if (!Array.isArray(value)) return [];
    return value.map((item) => {
      const obj = item && typeof item === 'object' ? item as Record<string, unknown> : {};
      return {
        code: typeof obj.code === 'string' ? obj.code : undefined,
        label: typeof obj.label === 'string' ? obj.label : undefined,
        level: typeof obj.level === 'string' ? obj.level : undefined,
        reason: typeof obj.reason === 'string' ? obj.reason : undefined,
        source: typeof obj.source === 'string' ? obj.source : undefined,
      };
    });
  };

  const buildResultFromPayload = (payload: Record<string, unknown>): DiagnosisResult => {
    const meta = payload.meta && typeof payload.meta === 'object'
      ? payload.meta as Record<string, unknown>
      : {};
    const treatmentObj = payload.treatment && typeof payload.treatment === 'object'
      ? payload.treatment as Record<string, unknown>
      : undefined;
    const selectedBranch = typeof treatmentObj?.selected_branch === 'string'
      ? treatmentObj.selected_branch
      : (typeof payload.selected_branch === 'string' ? payload.selected_branch : undefined);
    const rawVerification = payload.verification_result && typeof payload.verification_result === 'object'
      ? payload.verification_result as Record<string, unknown>
      : undefined;
    const verificationResult = rawVerification
      ? {
        passed: typeof rawVerification.passed === 'boolean'
          ? rawVerification.passed
          : (typeof payload.verification_passed === 'boolean' ? payload.verification_passed : undefined),
        risk_level: typeof rawVerification.risk_level === 'string'
          ? rawVerification.risk_level
          : (typeof payload.verification_risk_level === 'string' ? payload.verification_risk_level : undefined),
        issues: Array.isArray(rawVerification.issues)
          ? rawVerification.issues.map((item) => String(item))
          : (Array.isArray(payload.verification_issues) ? payload.verification_issues.map((item) => String(item)) : []),
        must_fix: Array.isArray(rawVerification.must_fix)
          ? rawVerification.must_fix.map((item) => String(item))
          : [],
        suggested_rewrite_points: Array.isArray(rawVerification.suggested_rewrite_points)
          ? rawVerification.suggested_rewrite_points.map((item) => String(item))
          : [],
        compliance_summary: typeof rawVerification.compliance_summary === 'string'
          ? rawVerification.compliance_summary
          : (typeof payload.verification_summary === 'string' ? payload.verification_summary : undefined),
      }
      : undefined;

    return {
      image_url: typeof payload.image_url === 'string'
        ? payload.image_url
        : (typeof payload.image_id === 'string' && payload.image_id ? `/uploads/${payload.image_id}` : ''),
      final_disease: typeof payload.final_disease === 'string'
        ? payload.final_disease
        : (payload.image_result && typeof payload.image_result === 'object' && typeof (payload.image_result as Record<string, unknown>).disease === 'string'
          ? String((payload.image_result as Record<string, unknown>).disease)
          : '未知'),
      displayConfidencePct: resolveDisplayConfidencePct(payload),
      model_display_name: typeof payload.model_display_name === 'string'
        ? payload.model_display_name
        : (typeof payload.model_id === 'string' ? payload.model_id : '-'),
      top3: payload.top3 ?? ((payload.image_result && typeof payload.image_result === 'object')
        ? (payload.image_result as Record<string, unknown>).top3
        : undefined),
      image_result: payload.image_result,
      treatment: payload?.treatment,
      prevention: payload?.prevention ?? ((payload.treatment && typeof payload.treatment === 'object') ? (payload.treatment as Record<string, unknown>).prevention : undefined),
      trace_id: typeof payload.trace_id === 'string' ? payload.trace_id : '',
      personalization_applied: payload.personalization_applied === true,
      filtered: payload.filtered === true,
      filtered_reasons: Array.isArray(payload.filtered_reasons) ? payload.filtered_reasons.map((item) => String(item)) : [],
      personalization_reasons: Array.isArray(payload.personalization_reasons) ? payload.personalization_reasons.map((item) => String(item)) : [],
      follow_up_questions: Array.isArray(payload.follow_up_questions) ? payload.follow_up_questions.map((item) => String(item)) : [],
      missing_profile_fields: Array.isArray(payload.missing_profile_fields) ? payload.missing_profile_fields.map((item) => String(item)) : [],
      profile_farm_scale: typeof payload.profile_farm_scale === 'string' ? payload.profile_farm_scale : undefined,
      profile_pesticide_access_level: typeof payload.profile_pesticide_access_level === 'string' ? payload.profile_pesticide_access_level : undefined,
      profile_equipment: Array.isArray(payload.profile_equipment) ? payload.profile_equipment.map((item) => String(item)) : [],
      profile_cultivation_mode: typeof payload.profile_cultivation_mode === 'string' ? payload.profile_cultivation_mode : undefined,
      selected_branch: selectedBranch,
      risk_tags: Array.isArray(payload.risk_tags)
        ? payload.risk_tags.map((item) => String(item))
        : (Array.isArray(meta.risk_tags) ? meta.risk_tags.map((item) => String(item)) : []),
      risk_items: normalizeRiskItems(payload.risk_items ?? meta.risk_items),
      risk_summary: typeof payload.risk_summary === 'string'
        ? payload.risk_summary
        : (typeof meta.risk_summary === 'string' ? meta.risk_summary : undefined),
      risk_updated_at: typeof payload.risk_updated_at === 'string'
        ? payload.risk_updated_at
        : (typeof meta.risk_updated_at === 'string' ? meta.risk_updated_at : undefined),
      verification_result: verificationResult,
      verification_passed: verificationResult?.passed ?? (typeof payload.verification_passed === 'boolean' ? payload.verification_passed : undefined),
      verification_risk_level: verificationResult?.risk_level ?? (typeof payload.verification_risk_level === 'string' ? payload.verification_risk_level : undefined),
      verification_issues: verificationResult?.issues ?? (Array.isArray(payload.verification_issues) ? payload.verification_issues.map((item) => String(item)) : []),
      verification_summary: verificationResult?.compliance_summary ?? (typeof payload.verification_summary === 'string' ? payload.verification_summary : undefined),
      status: typeof payload.status === 'string' ? payload.status : undefined,
      confirm_message: typeof payload.confirm_message === 'string' ? payload.confirm_message : undefined,
      expert_review_recommended: payload.expert_review_recommended === true,
      expert_review_selected: payload.expert_review_selected === true,
      expert_review_status: typeof payload.expert_review_status === 'string' ? payload.expert_review_status : undefined,
      expert_review_result: typeof payload.expert_review_result === 'string' ? payload.expert_review_result : undefined,
      expert_review_notes: typeof payload.expert_review_notes === 'string' ? payload.expert_review_notes : undefined,
      expert_reviewed_at: typeof payload.expert_reviewed_at === 'string' ? payload.expert_reviewed_at : undefined,
      expert_review_actions: Array.isArray(payload.expert_review_actions) ? payload.expert_review_actions.map((item) => String(item)) : [],
      treatment_available: payload.treatment_available === true,
      confirm_reasons: getConfirmReasons(payload),
      fusion_mode: typeof payload.fusion_mode === 'string' ? payload.fusion_mode : undefined,
      image_reliable: typeof payload.image_reliable === 'boolean' ? payload.image_reliable : undefined,
      text_reliable: typeof payload.text_reliable === 'boolean' ? payload.text_reliable : undefined,
      reliability_issue_types: Array.isArray(payload.reliability_issue_types) ? payload.reliability_issue_types.map((item) => String(item)) : [],
      supplement_mode: typeof payload.supplement_mode === 'string' ? payload.supplement_mode : undefined,
      confirm_reason_code: typeof payload.confirm_reason_code === 'string' ? payload.confirm_reason_code : undefined,
      confirm_reason_text: typeof payload.confirm_reason_text === 'string' ? payload.confirm_reason_text : undefined,
      recommended_action: typeof payload.recommended_action === 'string' ? payload.recommended_action : undefined,
      confirm_ui_mode: typeof payload.confirm_ui_mode === 'string' ? payload.confirm_ui_mode : undefined,
      confirm_fields: Array.isArray(payload.confirm_fields) ? payload.confirm_fields.map((item) => String(item)) : [],
    };
  };

  const normalizeTraceEvents = (eventsLike: unknown): TraceEvent[] => {
    if (!Array.isArray(eventsLike)) return [];
    return eventsLike
      .map((evt: unknown) => {
        const event = evt && typeof evt === 'object' ? evt as Record<string, unknown> : {};
        const decision = event.decision && typeof event.decision === 'object'
          ? event.decision as Record<string, unknown>
          : undefined;
        const seq = typeof event.seq === 'number' && Number.isFinite(event.seq) ? event.seq : Number.MAX_SAFE_INTEGER;
        return {
          seq,
          value: {
            timestamp: typeof event.ts === 'string'
              ? event.ts
              : (typeof event.timestamp === 'string' ? event.timestamp : new Date().toISOString()),
            agent: typeof event.agent_cn === 'string'
              ? event.agent_cn
              : (typeof event.agent_id === 'string'
                ? event.agent_id
                : (typeof event.agent === 'string'
                  ? event.agent
                  : String(event.node ?? ''))),
            status: typeof event.step_cn === 'string'
              ? event.step_cn
              : (typeof event.step === 'string'
                ? event.step
                : (typeof event.status === 'string' ? event.status : '')),
            message: typeof event.message === 'string'
              ? event.message
              : (typeof decision?.reason_str === 'string'
                ? decision.reason_str
                : (typeof decision?.reason === 'string' ? decision.reason : '')),
            raw: event,
          } as TraceEvent,
        };
      })
      .sort((a, b) => a.seq - b.seq)
      .map((item) => item.value);
  };

  const parseProfiles = (raw: unknown): ProfileListItem[] => {
    if (!Array.isArray(raw)) return [];
    const items: ProfileListItem[] = [];
    raw.forEach((item) => {
      const record = item && typeof item === 'object' ? item as Record<string, unknown> : {};
      const id = typeof record.id === 'string' ? record.id : '';
      if (!id) return;
      items.push({ id, name: typeof record.name === 'string' ? record.name : undefined });
    });
    return items;
  };

  const fetchProfiles = async () => {
    try {
      const resp = await fetch('/api/profiles');
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载农户档案失败'));
      setProfiles(parseProfiles(data?.profiles));
    } catch (error) {
      console.error('Failed to fetch profiles:', error);
      setProfiles([]);
    }
  };

  const fetchExpertPending = async () => {
    if (!canViewExpertInbox) return;
    try {
      const resp = await authFetch('/api/expert-reviews/pending?limit=5', undefined, authUser);
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载专家复核提醒失败'));
      setExpertPendingCount(typeof data?.count === 'number' ? data.count : 0);
      setExpertPendingItems(Array.isArray(data?.items) ? data.items as PendingExpertItem[] : []);
    } catch (error) {
      console.error('Failed to fetch expert pending reviews:', error);
      setExpertPendingCount(0);
      setExpertPendingItems([]);
    }
  };

  const fetchProfileDetail = async (farmerId: string) => {
    if (!farmerId) {
      setSelectedProfile(null);
      setSelectedBaseId('');
      return;
    }
    try {
      const resp = await fetch(`/api/profiles/${encodeURIComponent(farmerId)}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载档案详情失败'));
      const profile = (data || {}) as ProfileDetail;
      setSelectedProfile(profile);
      if (profile.active_base_id) {
        setSelectedBaseId(profile.active_base_id);
      } else if (profile.bases && typeof profile.bases === 'object') {
        const firstBaseId = Object.keys(profile.bases)[0];
        setSelectedBaseId(firstBaseId || '');
      }
    } catch (error) {
      console.error('Failed to fetch profile detail:', error);
      setSelectedProfile(null);
      setSelectedBaseId('');
    }
  };

  useEffect(() => {
    fetchProfiles();
  }, []);

  useEffect(() => {
    if (!canViewExpertInbox) return;
    void fetchExpertPending();
  }, [canViewExpertInbox]);

  useEffect(() => {
    fetchProfileDetail(selectedFarmerId);
  }, [selectedFarmerId]);

  useEffect(() => {
    if (result?.status !== 'waiting_for_supplement') return;
    if (phase1FrozenMs !== null || phase2StartTime !== null) return;
    if (phase1StartTime === null) return;
    setPhase1FrozenMs(Math.max(0, Date.now() - phase1StartTime));
  }, [result?.status, phase1StartTime, phase1FrozenMs, phase2StartTime]);

  useEffect(() => {
    const shouldTick =
      loading
      || confirmSubmitting
      || (phase1StartTime !== null && !['completed', 'pending_expert_review', 'waiting_for_supplement', 'waiting_for_expert_decision'].includes(result?.status ?? ''));
    if (!shouldTick) {
      setTimingNowMs(Date.now());
      return undefined;
    }
    const timer = window.setInterval(() => setTimingNowMs(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, [loading, confirmSubmitting, phase1StartTime, result?.status]);

  const handleSubmit = async () => {
    if (!file || !selectedFarmerId) return;

    setLoading(true);
    setResult(null);
    setTraceEvents([]);
    setConfirmMode(false);
    setConfirmChoice('other');
    setConfirmSymptoms('');
    setResubmitFile(null);
    setResubmitPreview('');
    const now = Date.now();
    setPhase1StartTime(now);
    setPhase2StartTime(null);
    setPhase1FrozenMs(null);
    setWorkflowRefreshToken((prev) => prev + 1);

    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('crop_type', cropType || '番茄');
      const symptomsForDiagnose = symptoms.trim() || confirmSymptoms.trim();
      if (symptomsForDiagnose) fd.append('symptoms', symptomsForDiagnose);
      if (growthStage.trim()) fd.append('growth_stage', growthStage.trim());
      if (modelId) fd.append('model_id', modelId);
      fd.append('farmer_id', selectedFarmerId);
      if (selectedBaseId) fd.append('base_id', selectedBaseId);
      console.log('diagnose-image model_id=', modelId);

      const resp = await fetch('/api/diagnose-image', {
        method: 'POST',
        body: fd
      });
      const raw = await resp.text();
      let data: unknown = null;
      try {
        data = raw ? JSON.parse(raw) : null;
      } catch {
        data = null;
      }
      if (!resp.ok) {
        const detail = data && typeof data === 'object' && 'detail' in data
          ? String((data as { detail?: unknown }).detail ?? '')
          : '';
        throw new Error(detail || raw || `诊断失败: ${resp.status}`);
      }

      if (!data || typeof data !== 'object') {
        throw new Error('诊断接口返回格式非法');
      }

      const payload = data as Record<string, unknown>;

      if (payload.trace_id) {
        setTraceId(String(payload.trace_id));
      }
      if (payload.image_id) {
        setImageId(String(payload.image_id));
      }
      if (Array.isArray(payload.events)) {
        setTraceEvents(normalizeTraceEvents(payload.events));
      }
      setWorkflowRefreshToken((prev) => prev + 1);

      const normalizedResult = buildResultFromPayload(payload);
      setResult(normalizedResult);
      const payloadRecord = payload;
      setLatestPayload(payloadRecord);

      const candidates = parseTop3Candidates(payloadRecord, normalizedResult);
      const needsConfirm = payload.status === 'waiting_for_supplement' && payload.expert_review_recommended !== true && (
        hasBackendExplain(payloadRecord)
          ? payload.need_confirm === true
          : deriveNeedConfirm(payloadRecord, candidates, normalizedResult.displayConfidencePct)
      );
      console.log('[confirm] candidates=', candidates);
      console.log('[confirm] derivedNeedConfirm=', needsConfirm);
      setConfirmMode(needsConfirm);
      if (needsConfirm && candidates[0]?.disease && !confirmChoice) {
        setConfirmChoice(candidates[0].disease);
      }
    } catch (error) {
      console.error('Diagnosis failed:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleResubmitWithNewImage = async () => {
    if (!selectedFarmerId || !traceId || !imageId) return;
    if (usesImageSupplement && !resubmitFile) return;
    setResubmitSubmitting(true);
    setConfirmMode(false);
    setConfirmChoice('other');
    setConfirmSymptoms('');
    setTraceEvents([]);
    const now = Date.now();
    setPhase1StartTime(now);
    setPhase2StartTime(null);
    setPhase1FrozenMs(null);
    setWorkflowRefreshToken((prev) => prev + 1);
    try {
      const fd = new FormData();
      fd.append('trace_id', traceId);
      fd.append('previous_trace_id', traceId);
      fd.append('image_id', imageId);
      fd.append('crop_type', cropType || '番茄');
      if (usesImageSupplement && resubmitFile) fd.append('file', resubmitFile);
      if (usesTextSupplement && confirmSymptoms.trim()) fd.append('symptoms', confirmSymptoms.trim());
      if (growthStage.trim()) fd.append('growth_stage', growthStage.trim());
      if (modelId) fd.append('model_id', modelId);
      fd.append('choice', (confirmChoice && confirmChoice !== 'other') ? confirmChoice : 'other');
      fd.append('farmer_id', selectedFarmerId);
      if (selectedBaseId) fd.append('base_id', selectedBaseId);

      const resp = await fetch('/api/diagnose-retry', {
        method: 'POST',
        body: fd,
      });
      const raw = await resp.text();
      let data: unknown = null;
      try {
        data = raw ? JSON.parse(raw) : null;
      } catch {
        data = null;
      }
      if (!resp.ok) {
        const detail = data && typeof data === 'object' && 'detail' in data
          ? String((data as { detail?: unknown }).detail ?? '')
          : '';
        throw new Error(detail || raw || `重新诊断失败: ${resp.status}`);
      }
      if (!data || typeof data !== 'object') {
        throw new Error('重新诊断接口返回格式非法');
      }

      const payload = data as Record<string, unknown>;
      if (payload.trace_id) {
        setTraceId(String(payload.trace_id));
      } else {
        setTraceId('');
      }
      if (payload.image_id) {
        setImageId(String(payload.image_id));
      } else {
        setImageId('');
      }
      if (Array.isArray(payload.events)) {
        setTraceEvents(normalizeTraceEvents(payload.events));
      } else {
        setTraceEvents([]);
      }
      setWorkflowRefreshToken((prev) => prev + 1);

      const normalizedResult = buildResultFromPayload(payload);
      setResult(normalizedResult);
      setLatestPayload(payload);

      const candidates = parseTop3Candidates(payload, normalizedResult);
      const needsConfirm = payload.status === 'waiting_for_supplement' && payload.expert_review_recommended !== true && (
        hasBackendExplain(payload)
          ? payload.need_confirm === true
          : deriveNeedConfirm(payload, candidates, normalizedResult.displayConfidencePct)
      );
      setConfirmMode(needsConfirm);
      setConfirmChoice(needsConfirm && candidates[0]?.disease ? candidates[0].disease : 'other');
      setConfirmSymptoms('');
      setResubmitFile(null);
      setResubmitPreview('');
    } catch (error) {
      console.error('Resubmit diagnose failed:', error);
    } finally {
      setResubmitSubmitting(false);
    }
  };

  const handleConfirmSubmit = async (finalDecision?: 'use_current_result' | 'request_expert_review') => {
    if (!traceId || !imageId) return;
    if (!finalDecision) {
      await handleResubmitWithNewImage();
      return;
    }
    setPhase2StartTime(Date.now());
    setConfirmSubmitting(true);
    try {
      const additionalSymptoms = confirmSymptoms
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
      const symptomsForConfirm = additionalSymptoms;
      const isExpertDecisionStage = result?.status === 'waiting_for_expert_decision';
      const choiceForConfirm = isExpertDecisionStage
        ? null
        : ((confirmChoice && confirmChoice !== 'other') ? confirmChoice : 'other');
      const finalDecisionForConfirm = isExpertDecisionStage
        ? finalDecision
        : null;

      const resp = await fetch('/api/diagnose-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trace_id: traceId,
          image_id: imageId,
          crop_type: cropType || '番茄',
          symptoms: symptomsForConfirm,
          growth_stage: growthStage || null,
          model_id: modelId || null,
          choice: choiceForConfirm,
          notes: confirmSymptoms || null,
          farmer_id: selectedFarmerId || null,
          base_id: selectedBaseId || null,
          final_decision: finalDecisionForConfirm,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || `确认失败: ${resp.status}`);
      }

      if (data.trace_id) {
        setTraceId(data.trace_id);
      }
      if (data.image_id) {
        setImageId(data.image_id);
      }
      if (Array.isArray(data?.events)) {
        setTraceEvents(normalizeTraceEvents(data.events));
      }
      setWorkflowRefreshToken((prev) => prev + 1);

      const mergedPayload = {
        ...data,
        image_url: (typeof data?.image_url === 'string' && data.image_url)
          ? data.image_url
          : (typeof data?.image_id === 'string' && data.image_id)
            ? `/uploads/${data.image_id}`
            : (result?.image_url || ''),
      };
      const nextResult = buildResultFromPayload(mergedPayload as Record<string, unknown>);
      setResult(nextResult);
      const payloadRecord = mergedPayload && typeof mergedPayload === 'object' ? mergedPayload as Record<string, unknown> : {};
      setLatestPayload(payloadRecord);
      const candidates = parseTop3Candidates(payloadRecord, nextResult);
      const needsConfirm = data?.status === 'waiting_for_supplement' && data?.expert_review_recommended !== true && (
        hasBackendExplain(payloadRecord)
          ? data?.need_confirm === true
          : deriveNeedConfirm(payloadRecord, candidates, nextResult.displayConfidencePct)
      );
      console.log('[confirm] candidates=', candidates);
      console.log('[confirm] derivedNeedConfirm=', needsConfirm);
      setConfirmMode(needsConfirm);
      if (needsConfirm && candidates[0]?.disease && !confirmChoice) {
        setConfirmChoice(candidates[0].disease);
      }
    } catch (error) {
      console.error('Confirm diagnose failed:', error);
    } finally {
      setConfirmSubmitting(false);
    }
  };

  const renderRichValue = (value: unknown): JSX.Element | null => {
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
  };

  const renderTreatment = (t: unknown): JSX.Element | null => renderRichValue(t);
  const candidates = parseTop3Candidates(latestPayload ?? result ?? {}, result);
  const confirmUiMode = (() => {
    if (typeof result?.confirm_ui_mode === 'string' && result.confirm_ui_mode.trim()) {
      return result.confirm_ui_mode;
    }
    if (typeof result?.supplement_mode === 'string') {
      if (result.supplement_mode === 'image_only') return 'image';
      if (result.supplement_mode === 'image_and_text') return 'image_and_text';
      if (result.supplement_mode === 'text_only') return 'text';
    }
    return confirmMode ? 'text' : 'none';
  })();
  const usesTextSupplement = confirmUiMode === 'text' || confirmUiMode === 'image_and_text';
  const usesImageSupplement = confirmUiMode === 'image' || confirmUiMode === 'image_and_text';
  const shouldShowSupplementSection = result?.status === 'waiting_for_supplement' && confirmUiMode !== 'none';
  const {
    expertReviewPending,
    expertReviewCompleted,
    shouldShowExpertReviewDecision,
    shouldHideTreatment,
  } = deriveDiagnoseReviewViewFlags(result, shouldShowSupplementSection);
  const primaryRiskLabels = (() => {
    if (!result) return [] as string[];
    if (Array.isArray(result.risk_items) && result.risk_items.length > 0) {
      const sorted = [...result.risk_items].sort((a, b) => {
        const weight = (level?: string) => (level === 'high' ? 3 : level === 'medium' ? 2 : 1);
        return weight(b.level) - weight(a.level);
      });
      const labels = sorted
        .map((item) => (item.label || item.code || '').trim())
        .filter(Boolean);
      return Array.from(new Set(labels)).slice(0, 3);
    }
    if (Array.isArray(result.risk_tags) && result.risk_tags.length > 0) {
      return Array.from(new Set(result.risk_tags.map((tag) => String(tag).trim()).filter(Boolean))).slice(0, 3);
    }
    return [] as string[];
  })();
  const confirmCopy = (() => {
    const code = result?.confirm_reason_code;
    const mapping: Record<string, { title: string; body: string; cta: string }> = {
      IMAGE_QUALITY_LOW: { title: '图片不够清晰', body: '当前图片证据不足，无法稳定识别病斑特征', cta: '重新上传图片并复诊' },
      SYMPTOM_TEXT_INSUFFICIENT: { title: '症状描述不够完整', body: '请补充病斑颜色、边缘、霉层、水渍状等信息', cta: '补充症状并复诊' },
      IMAGE_TEXT_CONFLICT: { title: '图片与描述不一致', body: '请确认上传的是当前病株图片，并补充更准确症状', cta: '重新上传并补充信息' },
      BOTH_IMAGE_AND_TEXT_WEAK: { title: '图片和描述都不足', body: '请重新上传清晰图片，并补充病斑颜色、边缘、霉层等症状', cta: '补充信息并复诊' },
      LOW_DISCRIMINATION_NEED_KEY_FEATURES: { title: '候选病害过于接近', body: '请补充最能区分候选病害的特征', cta: '补充关键特征并复诊' },
    };
    return mapping[code || ''] || { title: '请补充诊断信息', body: result?.confirm_reason_text || '当前信息不足，请补充后继续复诊', cta: '提交补充信息' };
  })();
  const baseOptions: BaseOption[] = selectedProfile?.bases && typeof selectedProfile.bases === 'object'
    ? Object.entries(selectedProfile.bases).map(([baseId, base]) => ({
      id: baseId,
      name: base?.name,
    }))
    : [];

  useEffect(() => {
    if (!selectedProfile?.bases || !selectedBaseId) return;
    const base = selectedProfile.bases[selectedBaseId];
    const mappedStage = normalizeGrowthStage(base?.growth_stage || '');
    if (mappedStage) setGrowthStage(mappedStage);
  }, [selectedProfile, selectedBaseId]);

  useEffect(() => {
    if (!confirmMode) return;
    // 仅在尚未选择时自动回填首个候选；不要覆盖用户手动选择"仍不确定/其他"。
    const shouldAutofillChoice = !confirmChoice;
    if (candidates[0]?.disease && shouldAutofillChoice) {
      setConfirmChoice(candidates[0].disease);
    }
  }, [confirmMode, candidates, confirmChoice]);

  const refreshTrace = async (source: string = 'DiagnosePage.traceEffect') => {
    if (!traceId) return;

    traceFetchAbortRef.current?.abort();
    const controller = new AbortController();
    traceFetchAbortRef.current = controller;

    try {
      const resp = await fetchTraceEvents(traceId, {
        source,
        signal: controller.signal,
        debugState: {
          updatesStopped: false,
          waitingStable: false,
          workflowDone: false,
          hasInFlight: true,
        },
      });
      const data = await resp.json();
      if (traceFetchAbortRef.current === controller) {
        traceFetchAbortRef.current = null;
      }
      if (Array.isArray(data?.events)) {
        setTraceEvents(normalizeTraceEvents(data.events));
      }
    } catch (error) {
      if (traceFetchAbortRef.current === controller) {
        traceFetchAbortRef.current = null;
      }
      if (error instanceof DOMException && error.name === 'AbortError') return;
      console.error('Failed to fetch trace events:', error);
    }
  };

  useEffect(() => {
    if (!traceId) {
      traceFetchAbortRef.current?.abort();
      traceFetchAbortRef.current = null;
      setTraceEvents([]);
      return;
    }
    refreshTrace();
    return () => {
      traceFetchAbortRef.current?.abort();
      traceFetchAbortRef.current = null;
    };
  }, [traceId]);

  const rawTraceTimingEvents = traceEvents.map((event) => event.raw);
  const traceTiming = calcTracePhaseTiming(rawTraceTimingEvents, timingNowMs);
  const fallbackTiming = phase1StartTime === null
    ? null
    : {
      phase1Ms: phase1FrozenMs ?? Math.max(0, ((phase2StartTime ?? timingNowMs) - phase1StartTime)),
      phase2Ms: phase2StartTime === null ? 0 : Math.max(0, timingNowMs - phase2StartTime),
      totalMs: 0,
    };
  if (fallbackTiming) {
    fallbackTiming.totalMs = fallbackTiming.phase1Ms + fallbackTiming.phase2Ms;
  }
  const displayedTiming = traceTiming.hasTraceTiming ? traceTiming : fallbackTiming;
  const timingSourceLabel = traceTiming.hasTraceTiming ? 'trace events' : (displayedTiming ? '本地提交兜底' : null);
  return (
    <div className="space-y-6 animate-fadeIn">
      {canViewExpertInbox && (
        <div className="flex justify-end">
          <div className="relative">
            <Button
              type="button"
              variant="outline"
              className="border-[#c8f7c5]/60 text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
              onClick={() => setShowExpertInbox((prev) => !prev)}
            >
              <Bell className="w-4 h-4 mr-1" />
              待复核 {expertPendingCount}
            </Button>
            {showExpertInbox && (
              <div className="absolute right-0 z-20 mt-2 w-80 rounded-xl border border-white/20 bg-[#101010] p-3 shadow-xl">
                <div className="mb-2 flex items-center justify-between text-xs text-white/70">
                  <span>最近待复核病例</span>
                  <button type="button" className="text-[#c8f7c5]" onClick={() => { void fetchExpertPending(); }}>刷新</button>
                </div>
                <div className="space-y-1 text-sm">
                  {expertPendingItems.length === 0 ? (
                    <p className="text-white/60">暂无待复核</p>
                  ) : expertPendingItems.map((item) => (
                    <div key={item.trace_id} className="rounded-lg border border-white/10 px-2 py-1 text-white/85">
                      <p className="font-mono text-xs">{item.trace_id.slice(0, 14)}...</p>
                      <p className="text-xs">{item.farmer_name || item.farmer_id || '未知用户'}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold text-white mb-3">
          智能<span className="text-[#c8f7c5]">病害诊断</span>
        </h1>
        <p className="text-white/60 max-w-2xl mx-auto">
          上传作物图像，AI智能识别病害，提供精准治疗方案
        </p>
      </div>

      <div className="grid lg:grid-cols-5 gap-6">
        {/* Left Column - Upload Form */}
        <Card className="lg:col-span-2 glass-card">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <Upload className="w-5 h-5 text-[#c8f7c5]" />
              上传信息
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* File Upload */}
            <div className="space-y-2">
              <Label className="text-white/80">图片文件</Label>
              <div
                onClick={() => fileInputRef.current?.click()}
                className={cn(
                  "border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all duration-300",
                  imagePreview 
                    ? "border-[#c8f7c5]/50 bg-[#c8f7c5]/5" 
                    : "border-white/20 hover:border-[#c8f7c5]/50 hover:bg-white/5"
                )}
              >
                {imagePreview ? (
                  <img 
                    src={imagePreview} 
                    alt="Preview" 
                    className="max-h-40 mx-auto rounded-lg object-contain"
                  />
                ) : (
                  <div className="space-y-2">
                    <ImageIcon className="w-10 h-10 text-white/40 mx-auto" />
                    <p className="text-white/60 text-sm">点击选择或拖拽图片</p>
                  </div>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </div>
            </div>

            {/* Symptoms */}
            <div className="space-y-2">
              <Label className="text-white/80">症状（逗号分隔）</Label>
              <Input
                placeholder="例如：斑点, 发黄"
                value={symptoms}
                onChange={(e) => setSymptoms(e.target.value)}
                className="bg-white/5 border-white/20 text-white placeholder:text-white/40 focus:border-[#c8f7c5]"
              />
            </div>

            {/* Crop Type */}
            <div className="space-y-2">
              <Label className="text-white/80">作物类型</Label>
              <Input
                placeholder="番茄"
                value={cropType}
                onChange={(e) => setCropType(e.target.value)}
                className="bg-white/5 border-white/20 text-white placeholder:text-white/40 focus:border-[#c8f7c5]"
              />
            </div>

            {/* Growth Stage */}
            <div className="space-y-2">
              <Label className="text-white/80">生长阶段（可选）</Label>
              <Select value={normalizeGrowthStage(growthStage) || '__EMPTY__'} onValueChange={(value) => setGrowthStage(value === '__EMPTY__' ? '' : value)}>
                <SelectTrigger className="bg-white/5 border-white/20 text-white">
                  <SelectValue placeholder="请选择番茄生长阶段" className="text-white placeholder:text-white/60" />
                </SelectTrigger>
                <SelectContent side="bottom" align="start" sideOffset={6} className="bg-[#111] text-white border-white/20">
                  <SelectItem value="__EMPTY__">未设置</SelectItem>
                  {TOMATO_GROWTH_STAGE_OPTIONS.map((stage: { value: string; label: string }) => (
                    <SelectItem key={stage.value} value={stage.value} className="text-white data-[highlighted]:bg-[#c8f7c5] data-[highlighted]:text-black">
                      {stage.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Model Selection */}
            <div className="space-y-2">
              <Label className="text-white/80">识别模型</Label>
              <Select value={modelId} onValueChange={setModelId}>
                <SelectTrigger className="bg-white/5 border-white/20 text-white">
                  <SelectValue className="text-white placeholder:text-white/60" />
                </SelectTrigger>
                <SelectContent
                  side="bottom"
                  align="start"
                  sideOffset={6}
                  className="bg-[#111] text-white border-white/20"
                >
                  {modelOptions.map((option: { value: string; label: string }) => (
                    <SelectItem key={option.value} value={option.value} className="text-white data-[highlighted]:bg-[#c8f7c5] data-[highlighted]:text-black">
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-white/60">将发送 model_id：{modelId}</p>
            </div>

            {/* Farmer Profile */}
            <div className="space-y-2">
              <Label className="text-white/80">农户档案（个性化设置）</Label>
              <Select value={selectedFarmerId} onValueChange={setSelectedFarmerId}>
                <SelectTrigger className="bg-white/5 border-white/20 text-white">
                  <SelectValue placeholder="请选择农户档案" className="text-white placeholder:text-white/60" />
                </SelectTrigger>
                <SelectContent side="bottom" align="start" sideOffset={6} className="bg-[#111] text-white border-white/20">
                  {profiles.map((profile) => (
                    <SelectItem key={profile.id} value={profile.id} className="text-white data-[highlighted]:bg-[#c8f7c5] data-[highlighted]:text-black">
                      {profile.id}{profile.name ? ` · ${profile.name}` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {baseOptions.length > 0 && (
                <Select value={selectedBaseId} onValueChange={setSelectedBaseId}>
                  <SelectTrigger className="bg-white/5 border-white/20 text-white">
                    <SelectValue placeholder="请选择基地" className="text-white placeholder:text-white/60" />
                  </SelectTrigger>
                  <SelectContent side="bottom" align="start" sideOffset={6} className="bg-[#111] text-white border-white/20">
                    {baseOptions.map((base) => (
                      <SelectItem key={base.id} value={base.id} className="text-white data-[highlighted]:bg-[#c8f7c5] data-[highlighted]:text-black">
                        {base.id}{base.name ? ` · ${base.name}` : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {selectedProfile && (
                <div className="bg-white/5 rounded-xl p-3 text-xs text-white/75 space-y-1 border border-white/10">
                  <p>农户：{selectedProfile.farmer_id}{selectedProfile.name ? ` · ${selectedProfile.name}` : ''}</p>
                  <p>规模：{getFarmScaleLabel(selectedProfile.farm_scale || 'SMALL')}</p>
                  <p>购药能力：{getPesticideAccessLevelLabel(selectedProfile.pesticide_access_level || 'LIMITED')}</p>
                  <p>设备：{(selectedProfile.equipment || []).map((item) => getEquipmentLabel(item)).join('、') || '无'}</p>
                  <p>栽培模式：{getCultivationModeLabel(selectedProfile.cultivation_mode || 'SOIL')}</p>
                  <p>偏好有机：{selectedProfile.constraints?.prefer_organic ? '是' : '否'}</p>
                  <p>禁用成分：{(selectedProfile.constraints?.banned_ingredients || []).join('、') || '无'}</p>
                  <p>采收窗口：{selectedProfile.constraints?.harvest_window_days ?? '未设置'} 天</p>
                  <p>基地：{selectedBaseId || selectedProfile.active_base_id || '未设置'}</p>
                </div>
              )}
              {!selectedFarmerId && (
                <p className="text-xs text-yellow-200">请先选择农户档案（个性化方案依赖档案约束）</p>
              )}
            </div>

            {/* Submit Button */}
            <Button
              onClick={handleSubmit}
              disabled={!file || loading || !selectedFarmerId}
              className="w-full bg-[#c8f7c5] text-black hover:bg-[#b8e7b5] font-semibold h-12 rounded-xl transition-all duration-300 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                  诊断中...
                </>
              ) : (
                <>
                  <Send className="w-5 h-5 mr-2" />
                  开始诊断
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        {/* Right Column - Results */}
        <div className="lg:col-span-3 space-y-6">
          {/* Diagnosis Result Card */}
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-white flex items-center gap-2">
                <CheckCircle className="w-5 h-5 text-[#c8f7c5]" />
                诊断结果
              </CardTitle>
            </CardHeader>
            <CardContent>
              {result ? (
                <div className="space-y-5 animate-fadeIn">
                  {/* Result Image */}
                  {result.image_url && (
                    <div className="rounded-xl overflow-hidden bg-black/30">
                      <img 
                        src={result.image_url} 
                        alt="Diagnosed" 
                        className="w-full max-h-64 object-contain"
                      />
                    </div>
                  )}

                  {/* Main Result */}
                  <div className="grid sm:grid-cols-3 gap-4">
                    <div className="bg-white/5 rounded-xl p-4">
                      <p className="text-white/60 text-sm mb-1">最终病害</p>
                      <button
                        type="button"
                        onClick={() => navigateToKbDisease(result.final_disease)}
                        className="text-left text-xl font-bold text-[#c8f7c5] hover:underline underline-offset-4"
                      >
                        {result.final_disease}
                      </button>
                    </div>
                    <div className="bg-white/5 rounded-xl p-4">
                      <p className="text-white/60 text-sm mb-1">置信度</p>
                      <p className="text-xl font-bold text-[#c8f7c5]">{result.displayConfidencePct !== null ? `${result.displayConfidencePct.toFixed(2)}%` : "—"}</p>
                    </div>
                    <div className="bg-white/5 rounded-xl p-4">
                      <p className="text-white/60 text-sm mb-1">使用模型</p>
                      <p className="text-sm font-medium text-white">{result.model_display_name}</p>
                    </div>
                  </div>

                  {candidates.length > 0 ? (
                    <div className="bg-white/5 rounded-xl p-4">
                      <div className="flex items-center justify-between mb-4">
                        <h4 className="text-white/80 font-medium">病害诊治top3</h4>
                        <div className="text-sm text-white/60">
                          {result?.confirm_reason_code && (
                            <span>原因码: {result.confirm_reason_code}</span>
                          )}
                          {result?.reliability_issue_types && result.reliability_issue_types.length > 0 && (
                            <span className="ml-2">weights: {result.reliability_issue_types.join(', ')}</span>
                          )}
                        </div>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="flex flex-col">
                          <h5 className="text-white/60 text-sm mb-2">图像top3</h5>
                          <div className="space-y-2 flex-1">
                            {parseTop3Candidates(latestPayload ?? result ?? {}, result, 'image').map((item, idx) => (
                              <div key={idx} className="flex items-center gap-3">
                                <Badge
                                  variant={idx === 0 ? 'default' : 'outline'}
                                  className={cn(
                                    'min-w-[3rem] text-center',
                                    idx === 0 ? 'bg-[#c8f7c5] text-black' : 'border-white/30 text-white',
                                  )}
                                >
                                  #{idx + 1}
                                </Badge>
                                <button
                                  type="button"
                                  onClick={() => navigateToKbDisease(item.disease)}
                                  className="text-white flex-1 text-left hover:text-[#c8f7c5] hover:underline underline-offset-4"
                                >
                                  {item.disease}
                                </button>
                                <span className="text-[#c8f7c5] font-mono">{item.probPct.toFixed(2)}%</span>
                              </div>
                            ))}
                            {parseTop3Candidates(latestPayload ?? result ?? {}, result, 'image').length === 0 && (
                              <div className="text-white/40 text-sm">无数据</div>
                            )}
                          </div>
                        </div>
                        <div className="flex flex-col">
                          <h5 className="text-white/60 text-sm mb-2">文本top3</h5>
                          <div className="space-y-2 flex-1">
                            {parseTop3Candidates(latestPayload ?? result ?? {}, result, 'text').map((item, idx) => (
                              <div key={idx} className="flex items-center gap-3">
                                <Badge
                                  variant={idx === 0 ? 'default' : 'outline'}
                                  className={cn(
                                    'min-w-[3rem] text-center',
                                    idx === 0 ? 'bg-[#c8f7c5] text-black' : 'border-white/30 text-white',
                                  )}
                                >
                                  #{idx + 1}
                                </Badge>
                                <button
                                  type="button"
                                  onClick={() => navigateToKbDisease(item.disease)}
                                  className="text-white flex-1 text-left hover:text-[#c8f7c5] hover:underline underline-offset-4"
                                >
                                  {item.disease}
                                </button>
                                <span className="text-[#c8f7c5] font-mono">{item.probPct.toFixed(2)}%</span>
                              </div>
                            ))}
                            {parseTop3Candidates(latestPayload ?? result ?? {}, result, 'text').length === 0 && (
                              <div className="text-white/40 text-sm">无数据</div>
                            )}
                          </div>
                        </div>
                        <div className="flex flex-col">
                          <h5 className="text-white/60 text-sm mb-2">融合top3</h5>
                          <div className="space-y-2 flex-1">
                            {parseTop3Candidates(latestPayload ?? result ?? {}, result, 'fusion').map((item, idx) => (
                              <div key={idx} className="flex items-center gap-3">
                                <Badge
                                  variant={idx === 0 ? 'default' : 'outline'}
                                  className={cn(
                                    'min-w-[3rem] text-center',
                                    idx === 0 ? 'bg-[#c8f7c5] text-black' : 'border-white/30 text-white',
                                  )}
                                >
                                  #{idx + 1}
                                </Badge>
                                <button
                                  type="button"
                                  onClick={() => navigateToKbDisease(item.disease)}
                                  className="text-white flex-1 text-left hover:text-[#c8f7c5] hover:underline underline-offset-4"
                                >
                                  {item.disease}
                                </button>
                                <span className="text-[#c8f7c5] font-mono">{item.probPct.toFixed(2)}%</span>
                              </div>
                            ))}
                            {parseTop3Candidates(latestPayload ?? result ?? {}, result, 'fusion').length === 0 && (
                              <div className="text-white/40 text-sm">无数据</div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  <div>
                    <h4 className="text-white/80 font-medium mb-2">个性化影响（生成阶段）</h4>
                    <div className="bg-white/5 rounded-xl p-4 text-sm text-white/80 space-y-2">
                      <div className="flex items-center gap-2">
                        <span>已应用个性化：</span>
                        <Badge className={cn(result.personalization_applied ? 'bg-[#c8f7c5] text-black' : 'bg-white/10 text-white')}>
                          {result.personalization_applied ? '是' : '否'}
                        </Badge>
                        {result.filtered && (
                          <Badge className="bg-yellow-400 text-black">后处理已过滤</Badge>
                        )}
                      </div>
                      {Array.isArray(result.personalization_reasons) && result.personalization_reasons.length > 0 ? (
                        <ul className="list-disc pl-5 space-y-1">
                          {result.personalization_reasons.map((reason: string, idx: number) => (
                            <li key={`${reason}-${idx}`}>{reason}</li>
                          ))}
                        </ul>
                      ) : Array.isArray(result.filtered_reasons) && result.filtered_reasons.length > 0 ? (
                        <ul className="list-disc pl-5 space-y-1">
                          {result.filtered_reasons.map((reason, idx) => (
                            <li key={`${reason}-${idx}`}>{reason}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-white/50">暂无个性化影响说明</p>
                      )}
                    </div>
                  </div>

                  <div>
                    <h4 className="text-white/80 font-medium mb-2">农业风险标签（辅助解释层）</h4>
                    <div className="bg-white/5 rounded-xl p-4 border border-[#c8f7c5]/20 text-sm text-white/80">
                      {primaryRiskLabels.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                          {primaryRiskLabels.map((tag, idx) => (
                            <span
                              key={`${tag}-${idx}`}
                              className="inline-flex items-center rounded-full border border-[#73d59f]/70 bg-[#73d59f]/20 px-3 py-1 text-xs font-medium text-[#baf7d3]"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <div className="text-center py-4 text-white/50">
                          <p>暂无风险标签</p>
                          <p className="text-xs mt-1">风险标签仅用于解释层，原始字段仍是诊断与方案生成的主依据。</p>
                        </div>
                      )}
                    </div>
                  </div>



                  <div>
                    <h4 className="text-white/80 font-medium mb-2">待补充信息（用于提升个性化精度）</h4>
                    <div className="bg-white/5 rounded-xl p-4 border border-[#c8f7c5]/20 text-sm text-white/80 space-y-3">
                      <div className="flex items-center gap-2">
                        <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/40">建议补齐</Badge>
                      </div>
                      {Array.isArray(result.follow_up_questions) && result.follow_up_questions.length > 0 ? (
                        <ul className="list-disc pl-5 space-y-1">
                          {result.follow_up_questions.map((question, idx) => (
                            <li key={`${question}-${idx}`}>{question}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-white/50">暂无待补充信息</p>
                      )}
                      {Array.isArray(result.missing_profile_fields) && result.missing_profile_fields.length > 0 ? (
                        <div className="flex flex-wrap gap-2 pt-1">
                          {result.missing_profile_fields.map((field) => (
                            <Badge key={field} variant="outline" className="border-[#c8f7c5]/40 text-[#c8f7c5]">{field}</Badge>
                          ))}
                        </div>
                      ) : null}
                      <p className="text-xs text-white/60">可前往【农户档案管理】补齐设备/生育期等信息，以获得更精准的可执行方案。</p>
                    </div>
                  </div>

                  {shouldShowSupplementSection ? (
                    <div className="bg-[#c8f7c5]/10 border border-[#c8f7c5]/30 rounded-xl p-4 space-y-4">
                      <h4 className="text-[#c8f7c5] font-medium">{confirmCopy.title}</h4>
                      <p className="text-sm text-white/80">{result?.confirm_reason_text || confirmCopy.body}</p>
                      <p className="text-xs text-white/70">{result?.confirm_message || confirmCopy.body}</p>

                      {usesTextSupplement && (
                        <>
                          <div className="space-y-2">
                            <Label className="text-white/80">补充症状（逗号分隔）</Label>
                            <Input
                              value={confirmSymptoms}
                              onChange={(e) => setConfirmSymptoms(e.target.value)}
                              placeholder="例如：病斑边缘褐色, 叶背有霉层, 水渍状扩展"
                              className="bg-white/5 border-white/20 text-white placeholder:text-white/40"
                            />
                          </div>
                          {Array.isArray(result?.follow_up_questions) && result.follow_up_questions.length > 0 ? (
                            <ul className="list-disc pl-5 text-xs text-white/70 space-y-1">
                              {result.follow_up_questions.map((q, idx) => <li key={`${q}-${idx}`}>{q}</li>)}
                            </ul>
                          ) : null}
                        </>
                      )}

                      {usesImageSupplement && (
                        <div className="space-y-3 rounded-lg border border-white/20 bg-white/5 p-3">
                          <p className="text-sm text-white/90">当前图片信息不足，建议重新上传更清晰图片</p>
                          <p className="text-xs text-white/70">可补拍叶片正面、背面及病斑近照</p>
                          <Input type="file" accept="image/*" onChange={handleResubmitFileChange} className="bg-white/5 border-white/20 text-white file:text-white" />
                          {resubmitPreview ? (
                            <img src={resubmitPreview} alt="重新上传预览" className="max-h-40 rounded-lg object-contain bg-black/30" />
                          ) : (
                            <p className="text-xs text-white/60">{resubmitFile ? `已选择文件：${resubmitFile.name}` : '尚未选择重新上传图片'}</p>
                          )}
                        </div>
                      )}

                      <div className="flex flex-col sm:flex-row gap-3">
                        <Button
                          onClick={() => handleConfirmSubmit()}
                          disabled={confirmSubmitting || resubmitSubmitting || !traceId || !imageId || (usesImageSupplement && !resubmitFile)}
                          className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                        >
                          {(confirmSubmitting || resubmitSubmitting) ? '提交中...' : confirmCopy.cta}
                        </Button>
                      </div>
                    </div>
                  ) : shouldShowExpertReviewDecision ? (
                    <div className="bg-amber-500/10 border border-amber-400/30 rounded-xl p-4 space-y-4">
                      <h4 className="text-amber-200 font-medium">补充诊断后仍建议专家复核</h4>
                      <p className="text-sm text-white/80">
                        {result.confirm_message || '多次补充后仍存在不确定性。你可以使用当前结果结束，或转入待专家复核状态。'}
                      </p>
                      <div className="flex flex-col sm:flex-row gap-3">
                        <Button
                          onClick={() => handleConfirmSubmit('use_current_result')}
                          disabled={confirmSubmitting || !traceId || !imageId}
                          className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                        >
                          {confirmSubmitting ? '提交中...' : '使用当前结果结束'}
                        </Button>
                        <Button
                          onClick={() => handleConfirmSubmit('request_expert_review')}
                          disabled={confirmSubmitting || !traceId || !imageId}
                          variant="outline"
                          className="border-amber-300/50 text-amber-100 hover:bg-amber-500/10"
                        >
                          {confirmSubmitting ? '提交中...' : '转入专家复核'}
                        </Button>
                      </div>
                    </div>
                  ) : null}

                  {expertReviewPending ? (
                    <div className="bg-blue-500/10 border border-blue-400/30 rounded-xl p-4 text-blue-100 text-sm space-y-2">
                      <h4 className="font-medium">已转入专家复核</h4>
                      <p>{result?.confirm_message || '当前病例已进入待专家复核状态，后续将由专家确认病害并补充最终方案。'}</p>
                      <p className="text-xs text-blue-200/90">expert_review_status：{result?.expert_review_status || 'PENDING'}</p>
                      <p className="text-xs text-blue-200/90">当前不下发治疗方案，等待专家确认。</p>
                    </div>
                  ) : null}

                  <div className="bg-white/5 border border-white/10 rounded-xl p-4 text-sm text-white/85 space-y-2">
                    <h4 className="font-medium text-[#c8f7c5]">病例复核详情</h4>
                    <p>expert_review_status：{result.expert_review_status || 'NONE'}</p>
                    <p>expert_review_selected：{result.expert_review_selected ? 'true' : 'false'}</p>
                    <p>expert_review_result：{result.expert_review_result || '-'}</p>
                    <p>expert_review_notes：{result.expert_review_notes || '-'}</p>
                    {expertReviewCompleted && (
                      <p className="text-emerald-300">专家已确认（{result.expert_reviewed_at || '-' }）</p>
                    )}
                  </div>

                  <Separator className="bg-white/10" />

                  {/* Treatment */}
                  {shouldHideTreatment && (
                    <div className="bg-yellow-500/10 border border-yellow-400/30 rounded-xl p-4 text-yellow-200 text-sm">
                      {expertReviewPending
                        ? '当前病例已进入待专家复核状态，治疗/预防方案将在后续专家确认后下发。'
                        : shouldShowExpertReviewDecision
                          ? '当前结果已支持结束或转入专家复核，请先完成选择。'
                          : '置信度不足，建议先完成补充诊断、确认候选病害或补充症状。'}
                    </div>
                  )}

                  {Boolean(result.treatment) && !shouldHideTreatment && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-2 flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-[#c8f7c5]" />
                        治疗方案
                        {result.selected_branch ? (
                          <span className="inline-flex items-center rounded-full border border-emerald-600/70 bg-emerald-900/50 px-2 py-0.5 text-xs text-emerald-100">
                            {getSelectedBranchLabel(result.selected_branch)}
                          </span>
                        ) : null}
                      </h4>
                      <div className="bg-white/5 rounded-xl p-4 text-white/80 text-sm leading-relaxed whitespace-pre-line">
                        {renderTreatment(result.treatment)}
                      </div>
                    </div>
                  )}

                </div>
              ) : (
                <div className="text-center py-12 text-white/40">
                  <ImageIcon className="w-16 h-16 mx-auto mb-4 opacity-50" />
                  <p>上传图片并点击诊断按钮获取结果</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Trace Events Card */}
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white flex items-center gap-2">
                <RefreshCw className="w-5 h-5 text-[#c8f7c5]" />
                多智能体协作流程
              </CardTitle>
              <div className="flex items-center gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setWorkflowCollapsed((prev) => !prev)}
                  className="text-white/70 hover:bg-white/10"
                >
                  {workflowCollapsed ? <ChevronDown className="w-4 h-4 mr-1" /> : <ChevronUp className="w-4 h-4 mr-1" />}
                  {workflowCollapsed ? '展开流程' : '折叠流程'}
                </Button>
                {traceId && (
                  <>
                    <span className="text-white/40 text-sm">追踪ID: {traceId.slice(0, 16)}...</span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => { void refreshTrace('DiagnosePage.manualRefresh'); }}
                      className="border-white/20 text-white hover:bg-white/10"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </Button>
                  </>
                )}
              </div>
            </CardHeader>
            {!workflowCollapsed && (
            <CardContent className="space-y-4">
              <p className="text-xs text-white/60">
                当前流程包含：接待解析 → 病害诊断 → 知识检索 → 方案生成 → 农业合规审查。
              </p>
              {displayedTiming && timingSourceLabel && (
                <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                  <p className="text-xs text-white/65">
                    耗时真值来源：{timingSourceLabel}。总耗时 {formatDurationMs(displayedTiming.totalMs)}（一诊 {formatDurationMs(displayedTiming.phase1Ms)} / 二诊 {formatDurationMs(displayedTiming.phase2Ms)}）
                  </p>
                </div>
              )}
              <AgentWorkflowPanel
                traceId={traceId || undefined}
                confidencePct={result?.displayConfidencePct ?? undefined}
                refreshToken={workflowRefreshToken}
              />

              <div className="flex items-center justify-between">
                <p className="text-xs text-white/50">调试事件流（开发排查）</p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowRawTrace((prev) => !prev)}
                  className="text-white/70 hover:bg-white/10"
                >
                  {showRawTrace ? <ChevronUp className="w-4 h-4 mr-1" /> : <ChevronDown className="w-4 h-4 mr-1" />}
                  {showRawTrace ? '收起事件' : '展开事件'}
                </Button>
              </div>

              {showRawTrace && (traceEvents.length > 0 ? (
                <div className="space-y-3 max-h-80 overflow-y-auto">
                  {traceEvents.map((event, idx) => (
                    <div 
                      key={`${event.timestamp}-${idx}`}
                      className="flex items-start gap-3 p-3 rounded-lg bg-white/5 animate-slideIn"
                      style={{ animationDelay: `${idx * 30}ms` }}
                    >
                      <div className={cn(
                        "w-2 h-2 rounded-full mt-2 flex-shrink-0",
                        event.status === '完成' || event.status === 'done' || event.status === 'completed'
                          ? "bg-green-400" 
                          : event.status === '错误' || event.status === 'error'
                          ? "bg-red-400"
                          : "bg-[#c8f7c5] animate-pulse"
                      )} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-white/40 text-xs font-mono">
                            {new Date(event.timestamp).toLocaleTimeString()}
                          </span>
                          <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5] text-xs">
                            {event.agent}
                          </Badge>
                          <span className="text-white text-sm">{event.status}</span>
                        </div>
                        {event.message && (
                          <p className="text-white/50 text-xs mt-1">{event.message}</p>
                        )}

                        <details className="mt-2">
                          <summary className="text-xs text-white/40 cursor-pointer hover:text-white/70">查看原始 JSON</summary>
                          <pre className="mt-1 text-[11px] text-white/60 bg-black/30 border border-white/10 rounded-md p-2 whitespace-pre-wrap break-all">
                            {JSON.stringify(event.raw, null, 2)}
                          </pre>
                        </details>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-white/40">
                  <RefreshCw className="w-10 h-10 mx-auto mb-3 opacity-50" />
                  <p className="text-sm">暂未收到追踪事件，面板将使用模拟进度降级展示</p>
                </div>
              ))}
            </CardContent>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
