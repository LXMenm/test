import { useEffect, useState, useRef } from 'react';
import type { ChangeEvent, JSX } from 'react';
import { Upload, Send, RefreshCw, AlertCircle, CheckCircle, Loader2, Image as ImageIcon, ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { AgentWorkflowPanel } from '@/components/AgentWorkflowPanel';

interface DiagnosisResult {
  image_url: string;
  final_disease: string;
  displayConfidencePct: number | null;
  model_display_name: string;
  top3: unknown;
  image_result?: unknown;
  treatment: unknown;
  prevention: unknown;
  trace_id: string;
  personalization_applied?: boolean;
  filtered?: boolean;
  filtered_reasons?: string[];
}

interface ProfileListItem {
  id: string;
  name?: string;
}

interface ProfileDetail {
  farmer_id: string;
  name?: string;
  active_base_id?: string;
  constraints?: {
    prefer_organic?: boolean;
    harvest_window_days?: number;
    banned_ingredients?: string[];
  };
  bases?: Record<string, {
    base_id?: string;
    name?: string;
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

export function DiagnosePage() {
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
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);
  const [showRawTrace, setShowRawTrace] = useState(false);
  const [diagnosisStartTime, setDiagnosisStartTime] = useState<number | null>(null);
  const [profiles, setProfiles] = useState<ProfileListItem[]>([]);
  const [selectedFarmerId, setSelectedFarmerId] = useState('');
  const [selectedBaseId, setSelectedBaseId] = useState('');
  const [selectedProfile, setSelectedProfile] = useState<ProfileDetail | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const parseTop3Candidates = (payloadLike: unknown, resultLike?: DiagnosisResult | null): Top3Candidate[] => {
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

    const source = Array.isArray(imageResult?.top3)
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
    if (payload.need_confirm === true) return true;
    if (hasLowConfidenceReason(payload.fallback_reason)) return true;

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
        return outputs?.need_confirm === true || hasLowConfidenceReason(outputs?.fallback_reason);
      });
      if (hasDiagnosisNeedConfirm) return true;
    }

    return candidates.length > 0 && displayConfidencePct !== null && displayConfidencePct < 60;
  };

  const buildResultFromPayload = (payload: Record<string, unknown>): DiagnosisResult => ({
    image_url: typeof payload.image_url === 'string' ? payload.image_url : '',
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
  });

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
    fetchProfileDetail(selectedFarmerId);
  }, [selectedFarmerId]);

  const handleSubmit = async () => {
    if (!file || !selectedFarmerId) return;

    setLoading(true);
    setResult(null);
    setTraceEvents([]);
    setConfirmMode(false);
    setConfirmChoice('other');
    setConfirmSymptoms('');
    setDiagnosisStartTime(Date.now());

    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('crop_type', cropType || '番茄');
      if (symptoms.trim()) fd.append('symptoms', symptoms.trim());
      if (growthStage.trim()) fd.append('growth_stage', growthStage.trim());
      if (modelId) fd.append('model_id', modelId);
      fd.append('farmer_id', selectedFarmerId);
      if (selectedBaseId) fd.append('base_id', selectedBaseId);
      console.log('diagnose-image model_id=', modelId);

      const resp = await fetch('/api/diagnose-image', {
        method: 'POST',
        body: fd
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || `诊断失败: ${resp.status}`);
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

      const normalizedResult = buildResultFromPayload(data);
      setResult(normalizedResult);
      const payloadRecord = data && typeof data === 'object' ? data as Record<string, unknown> : {};
      setLatestPayload(payloadRecord);

      const candidates = parseTop3Candidates(payloadRecord, normalizedResult);
      const needsConfirm = typeof data?.need_confirm === 'boolean'
        ? data.need_confirm
        : deriveNeedConfirm(payloadRecord, candidates, normalizedResult.displayConfidencePct);
      console.log('[confirm] candidates=', candidates);
      console.log('[confirm] derivedNeedConfirm=', needsConfirm);
      setConfirmMode(needsConfirm);
      if (needsConfirm && candidates[0]?.disease && (!confirmChoice || confirmChoice === 'other')) {
        setConfirmChoice(candidates[0].disease);
      }
    } catch (error) {
      console.error('Diagnosis failed:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmSubmit = async () => {
    if (!traceId || !imageId) return;
    setConfirmSubmitting(true);
    try {
      const additionalSymptoms = confirmSymptoms
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
      const symptomsForConfirm = additionalSymptoms;
      const choiceForConfirm = (confirmChoice && confirmChoice !== 'other') ? confirmChoice : 'other';

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

      const mergedPayload = {
        ...data,
        image_url: result?.image_url || '',
      };
      const nextResult = buildResultFromPayload(mergedPayload as Record<string, unknown>);
      setResult(nextResult);
      const payloadRecord = mergedPayload && typeof mergedPayload === 'object' ? mergedPayload as Record<string, unknown> : {};
      setLatestPayload(payloadRecord);
      const candidates = parseTop3Candidates(payloadRecord, nextResult);
      const needsConfirm = typeof data?.need_confirm === 'boolean'
        ? data.need_confirm
        : deriveNeedConfirm(payloadRecord, candidates, nextResult.displayConfidencePct);
      console.log('[confirm] candidates=', candidates);
      console.log('[confirm] derivedNeedConfirm=', needsConfirm);
      setConfirmMode(needsConfirm);
      if (needsConfirm && candidates[0]?.disease && (!confirmChoice || confirmChoice === 'other')) {
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
  const shouldHideTreatment = confirmMode;
  const baseOptions: BaseOption[] = selectedProfile?.bases && typeof selectedProfile.bases === 'object'
    ? Object.entries(selectedProfile.bases).map(([baseId, base]) => ({
      id: baseId,
      name: base?.name,
    }))
    : [];

  useEffect(() => {
    if (!confirmMode) return;
    if (candidates[0]?.disease && (!confirmChoice || confirmChoice === 'other')) {
      setConfirmChoice(candidates[0].disease);
    }
  }, [confirmMode, candidates, confirmChoice]);

  const refreshTrace = async () => {
    if (!traceId) return;
    
    try {
      const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
      const data = await resp.json();
      if (Array.isArray(data?.events)) {
        setTraceEvents(normalizeTraceEvents(data.events));
      }
    } catch (error) {
      console.error('Failed to fetch trace events:', error);
    }
  };

  useEffect(() => {
    if (!traceId) {
      setTraceEvents([]);
      return;
    }
    refreshTrace();
  }, [traceId]);

  return (
    <div className="space-y-6 animate-fadeIn">
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
              <Input
                placeholder="例如：开花期"
                value={growthStage}
                onChange={(e) => setGrowthStage(e.target.value)}
                className="bg-white/5 border-white/20 text-white placeholder:text-white/40 focus:border-[#c8f7c5]"
              />
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
                  <SelectItem value="tf_default" className="text-white data-[highlighted]:bg-[#c8f7c5] data-[highlighted]:text-black">默认高精度模型 (tf)</SelectItem>
                  <SelectItem value="tf_light_v1" className="text-white data-[highlighted]:bg-[#c8f7c5] data-[highlighted]:text-black">轻量模型V1 (tf)</SelectItem>
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
                      <p className="text-xl font-bold text-[#c8f7c5]">{result.final_disease}</p>
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
                    <div>
                      <h4 className="text-white/80 font-medium mb-3">Top 3 识别结果</h4>
                      <div className="space-y-2">
                        {candidates.map((item, idx) => (
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
                            <span className="text-white flex-1">{item.disease}</span>
                            <span className="text-[#c8f7c5] font-mono">{item.probPct.toFixed(2)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div>
                    <h4 className="text-white/80 font-medium mb-2">个性化影响</h4>
                    <div className="bg-white/5 rounded-xl p-4 text-sm text-white/80 space-y-2">
                      <div className="flex items-center gap-2">
                        <span>已应用个性化：</span>
                        <Badge className={cn(result.personalization_applied ? 'bg-[#c8f7c5] text-black' : 'bg-white/10 text-white')}>
                          {result.personalization_applied ? '是' : '否'}
                        </Badge>
                        {result.filtered && (
                          <Badge className="bg-yellow-400 text-black">已过滤</Badge>
                        )}
                      </div>
                      {Array.isArray(result.filtered_reasons) && result.filtered_reasons.length > 0 ? (
                        <ul className="list-disc pl-5 space-y-1">
                          {result.filtered_reasons.map((reason, idx) => (
                            <li key={`${reason}-${idx}`}>{reason}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-white/50">暂无过滤说明</p>
                      )}
                    </div>
                  </div>

                  {confirmMode ? (
                    <div className="bg-[#c8f7c5]/10 border border-[#c8f7c5]/30 rounded-xl p-4 space-y-4">
                      <h4 className="text-[#c8f7c5] font-medium">二次诊断 / 确认入口</h4>
                      <p className="text-xs text-white/70">当前候选数量：{candidates.length}</p>
                      <div className="space-y-2">
                        <Label className="text-white/80">候选病害选择</Label>
                        {candidates.map((item) => (
                          <label key={item.disease} className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
                            <input
                              type="radio"
                              name="confirmDisease"
                              value={item.disease}
                              checked={confirmChoice === item.disease}
                              onChange={(e) => setConfirmChoice(e.target.value)}
                            />
                            <span>{item.disease} ({item.probPct.toFixed(2)}%)</span>
                          </label>
                        ))}
                        <label className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
                          <input
                            type="radio"
                            name="confirmDisease"
                            value="other"
                            checked={confirmChoice === 'other'}
                            onChange={(e) => setConfirmChoice(e.target.value)}
                          />
                          <span>仍不确定 / 其他</span>
                        </label>
                      </div>

                      <div className="space-y-2">
                        <Label className="text-white/80">补充症状（可选，逗号分隔）</Label>
                        <Input
                          value={confirmSymptoms}
                          onChange={(e) => setConfirmSymptoms(e.target.value)}
                          placeholder="例如：叶片卷曲, 发黄"
                          className="bg-white/5 border-white/20 text-white placeholder:text-white/40"
                        />
                      </div>

                      <Button
                        onClick={handleConfirmSubmit}
                        disabled={confirmSubmitting || !traceId || !imageId}
                        className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                      >
                        {confirmSubmitting ? '提交中...' : '提交确认'}
                      </Button>
                    </div>
                  ) : null}

                  <Separator className="bg-white/10" />

                  {/* Treatment */}
                  {shouldHideTreatment && (
                    <div className="bg-yellow-500/10 border border-yellow-400/30 rounded-xl p-4 text-yellow-200 text-sm">
                      置信度不足，建议先二次诊断确认病害或补充症状。
                    </div>
                  )}

                  {Boolean(result.treatment) && !shouldHideTreatment && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-2 flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-[#c8f7c5]" />
                        治疗方案
                      </h4>
                      <div className="bg-white/5 rounded-xl p-4 text-white/80 text-sm leading-relaxed whitespace-pre-line">
                        {renderTreatment(result.treatment)}
                      </div>
                    </div>
                  )}

                  {/* Prevention */}
                  {Boolean(result.prevention) && !shouldHideTreatment && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-2">预防建议</h4>
                      <div className="bg-white/5 rounded-xl p-4 text-white/80 text-sm leading-relaxed whitespace-pre-line">
                        {renderRichValue(result.prevention)}
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
              {traceId && (
                <div className="flex items-center gap-3">
                  <span className="text-white/40 text-sm">追踪ID: {traceId.slice(0, 16)}...</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={refreshTrace}
                    className="border-white/20 text-white hover:bg-white/10"
                  >
                    <RefreshCw className="w-4 h-4" />
                  </Button>
                </div>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <AgentWorkflowPanel
                key={traceId || 'idle'}
                traceId={traceId || undefined}
                confidencePct={result?.displayConfidencePct ?? undefined}
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

              {diagnosisStartTime && (
                <p className="text-xs text-white/40">诊断启动时间：{new Date(diagnosisStartTime).toLocaleTimeString()}</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
