import { useEffect, useMemo, useState } from 'react';
import { Users, RefreshCw, Save, MapPin, Ban, Sprout, Trash2, Plus } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { loadAuthUser, type UserRole } from '@/auth';
import {
  getCultivationModeLabel,
  getEquipmentLabel,
  getExperienceLevelLabel,
  getFarmScaleLabel,
  getPesticideAccessLevelLabel,
  getRiskPreferenceLabel,
  getSelectedBranchLabel,
  normalizeGrowthStage,
  TOMATO_GROWTH_STAGE_OPTIONS,
  type SelectedBranch,
} from '@/lib/profileLabels';

interface FarmerBase {
  base_id: string;
  name: string;
  location: string;
  province: string;
  facility_type: string;
  growth_stage: string;
  sowing_date: string;
  notes: string;
}

interface FarmerProfile {
  farmer_id: string;
  name: string;
  display_name: string;
  owner_user_id: string;
  active_base_id: string;
  confirm_when_low_confidence: boolean;
  farm_scale: 'BALCONY' | 'SMALL' | 'MEDIUM' | 'LARGE' | 'GREENHOUSE_LARGE';
  pesticide_access_level: 'NONE' | 'LIMITED' | 'FULL';
  equipment: Array<'HAND_SPRAYER' | 'BACKPACK_SPRAYER' | 'MIST_BLOWER' | 'DRONE'>;
  cultivation_mode: 'SOIL' | 'HYDROPONIC' | 'SUBSTRATE';
  experience_level: 'NOVICE' | 'INTERMEDIATE' | 'EXPERT';
  risk_preference: 'CONSERVATIVE' | 'BALANCED' | 'AGGRESSIVE';
  constraints: {
    prefer_organic: boolean;
    harvest_window_days: number;
    banned_ingredients: string[];
  };
  bases: FarmerBase[];
}

const FARM_SCALE_OPTIONS = ['BALCONY', 'SMALL', 'MEDIUM', 'LARGE', 'GREENHOUSE_LARGE'] as const;
const PESTICIDE_ACCESS_OPTIONS = ['NONE', 'LIMITED', 'FULL'] as const;
const EQUIPMENT_OPTIONS = ['HAND_SPRAYER', 'BACKPACK_SPRAYER', 'MIST_BLOWER', 'DRONE'] as const;
const CULTIVATION_MODE_OPTIONS = ['SOIL', 'HYDROPONIC', 'SUBSTRATE'] as const;
const EXPERIENCE_OPTIONS = ['NOVICE', 'INTERMEDIATE', 'EXPERT'] as const;
const RISK_OPTIONS = ['CONSERVATIVE', 'BALANCED', 'AGGRESSIVE'] as const;

const toSafeString = (value: unknown, fallback = ''): string => (typeof value === 'string' ? value : fallback);

const normalizeBase = (baseId: string, base: unknown): FarmerBase => {
  const baseObj = base && typeof base === 'object' ? (base as Record<string, unknown>) : {};
  return {
    base_id: toSafeString(baseObj.base_id, baseId),
    name: toSafeString(baseObj.name),
    location: toSafeString(baseObj.location),
    province: toSafeString(baseObj.province),
    facility_type: toSafeString(baseObj.facility_type ?? baseObj.facility),
    growth_stage: normalizeGrowthStage(toSafeString(baseObj.growth_stage)),
    sowing_date: toSafeString(baseObj.sowing_date),
    notes: toSafeString(baseObj.notes),
  };
};

const normalizeProfile = (raw: unknown): FarmerProfile => {
  const rawObj = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const rawBases = rawObj.bases;
  const basesArray: FarmerBase[] = Array.isArray(rawBases)
    ? rawBases.map((base: unknown, idx) => {
      const baseObj = base && typeof base === 'object' ? (base as Record<string, unknown>) : {};
      return normalizeBase(toSafeString(baseObj.base_id, `B${idx + 1}`), baseObj);
    })
    : rawBases && typeof rawBases === 'object'
      ? Object.entries(rawBases).map(([baseId, base]) => normalizeBase(baseId, base))
      : [];

  return {
    farmer_id: toSafeString(rawObj.farmer_id || rawObj.id),
    name: toSafeString(rawObj.name),
    display_name: toSafeString(rawObj.display_name || rawObj.name || rawObj.farmer_id),
    owner_user_id: toSafeString(rawObj.owner_user_id),
    active_base_id: toSafeString(rawObj.active_base_id),
    confirm_when_low_confidence: Boolean(rawObj.confirm_when_low_confidence),
    farm_scale: (FARM_SCALE_OPTIONS.includes(toSafeString(rawObj.farm_scale) as never) ? toSafeString(rawObj.farm_scale) : 'SMALL') as FarmerProfile['farm_scale'],
    pesticide_access_level: (PESTICIDE_ACCESS_OPTIONS.includes(toSafeString(rawObj.pesticide_access_level) as never) ? toSafeString(rawObj.pesticide_access_level) : 'LIMITED') as FarmerProfile['pesticide_access_level'],
    equipment: (Array.isArray(rawObj.equipment) ? rawObj.equipment : [])
      .map((v) => toSafeString(v))
      .filter((v): v is FarmerProfile['equipment'][number] => EQUIPMENT_OPTIONS.includes(v as never)),
    cultivation_mode: (CULTIVATION_MODE_OPTIONS.includes(toSafeString(rawObj.cultivation_mode) as never) ? toSafeString(rawObj.cultivation_mode) : 'SOIL') as FarmerProfile['cultivation_mode'],
    experience_level: (EXPERIENCE_OPTIONS.includes(toSafeString(rawObj.experience_level) as never) ? toSafeString(rawObj.experience_level) : 'INTERMEDIATE') as FarmerProfile['experience_level'],
    risk_preference: (RISK_OPTIONS.includes(toSafeString(rawObj.risk_preference) as never) ? toSafeString(rawObj.risk_preference) : 'BALANCED') as FarmerProfile['risk_preference'],
    constraints: {
      prefer_organic: Boolean((rawObj.constraints as Record<string, unknown> | undefined)?.prefer_organic),
      harvest_window_days: Number((rawObj.constraints as Record<string, unknown> | undefined)?.harvest_window_days || 0),
      banned_ingredients: Array.isArray((rawObj.constraints as Record<string, unknown> | undefined)?.banned_ingredients)
        ? (((rawObj.constraints as Record<string, unknown>).banned_ingredients as unknown[]).map((item) => toSafeString(item)).filter(Boolean))
        : [],
    },
    bases: basesArray,
  };
};

const normalizeProfileList = (raw: unknown): FarmerProfile[] => {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => normalizeProfile(item)).filter((item) => Boolean(item.farmer_id));
};

const predictBranch = (profile: Pick<FarmerProfile, 'farm_scale' | 'pesticide_access_level' | 'equipment'>): SelectedBranch => {
  if (profile.pesticide_access_level === 'NONE') return 'FAMILY';
  if (profile.farm_scale === 'BALCONY' || profile.farm_scale === 'SMALL') return 'FAMILY';
  if (profile.farm_scale === 'MEDIUM') return 'MID';
  return 'ENTERPRISE';
};

export function ProfilesPage() {
  const authUser = loadAuthUser();
  const currentRole: UserRole = authUser?.role || 'USER';
  const canManageAllProfiles = currentRole === 'ADMIN';

  const [profiles, setProfiles] = useState<FarmerProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<FarmerProfile | null>(null);
  const [editedProfile, setEditedProfile] = useState<FarmerProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [infoMessage, setInfoMessage] = useState('');
  const [newIngredient, setNewIngredient] = useState('');

  const sortedProfiles = useMemo(() => {
    if (!canManageAllProfiles || !authUser?.userId) return profiles;
    return [...profiles].sort((a, b) => {
      const aMine = a.owner_user_id === authUser.userId ? 0 : 1;
      const bMine = b.owner_user_id === authUser.userId ? 0 : 1;
      if (aMine !== bMine) return aMine - bMine;
      return a.farmer_id.localeCompare(b.farmer_id);
    });
  }, [authUser?.userId, canManageAllProfiles, profiles]);

  const parseJsonOrThrow = async (resp: Response) => {
    let payload: Record<string, unknown> | null = null;
    try {
      const parsed: unknown = await resp.json();
      payload = parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
    } catch {
      // noop
    }
    if (!resp.ok) {
      const detail = payload?.detail ?? payload?.message ?? `请求失败：${resp.status}`;
      throw new Error(String(detail));
    }
    return payload;
  };

  const fetchProfiles = async () => {
    setLoading(true);
    setErrorMessage('');
    setInfoMessage('');
    try {
      const resp = await fetch('/api/profiles');
      const data = await parseJsonOrThrow(resp);
      const nextProfiles = normalizeProfileList(data?.profiles);
      setProfiles(nextProfiles);
      const fallback = nextProfiles[0]?.farmer_id;
      if (fallback && !selectedProfile) {
        void fetchProfileDetail(fallback);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '加载档案列表失败');
      setProfiles([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchProfileDetail = async (farmerId: string) => {
    setErrorMessage('');
    try {
      const resp = await fetch(`/api/profiles/${encodeURIComponent(farmerId)}`);
      const data = await parseJsonOrThrow(resp);
      const normalized = normalizeProfile(data);
      setSelectedProfile(normalized);
      setEditedProfile(JSON.parse(JSON.stringify(normalized)));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '加载档案详情失败');
    }
  };

  useEffect(() => {
    void fetchProfiles();

    const handleProfilesInvalidated = () => {
      void fetchProfiles();
    };
    window.addEventListener('profiles:invalidate', handleProfilesInvalidated);
    return () => window.removeEventListener('profiles:invalidate', handleProfilesInvalidated);
  }, []);

  const saveProfile = async () => {
    if (!editedProfile) return;
    setErrorMessage('');
    setInfoMessage('');

    const basesMap = Object.fromEntries(
      editedProfile.bases.map((base) => [base.base_id, {
        base_id: base.base_id,
        name: base.name,
        location: base.location,
        province: base.province,
        facility: base.facility_type,
        growth_stage: normalizeGrowthStage(base.growth_stage),
        sowing_date: base.sowing_date || null,
        notes: base.notes,
      }]),
    );

    try {
      const resp = await fetch(`/api/profiles/${encodeURIComponent(editedProfile.farmer_id)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...editedProfile,
          display_name: editedProfile.display_name || editedProfile.name || editedProfile.farmer_id,
          bases: basesMap,
        }),
      });
      await parseJsonOrThrow(resp);
      setInfoMessage('档案业务资料已保存。');
      setSelectedProfile(editedProfile);
      await fetchProfiles();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '保存档案失败');
    }
  };

  const addIngredient = () => {
    if (!newIngredient.trim() || !editedProfile) return;
    setEditedProfile({
      ...editedProfile,
      constraints: {
        ...editedProfile.constraints,
        banned_ingredients: [...editedProfile.constraints.banned_ingredients, newIngredient.trim()],
      },
    });
    setNewIngredient('');
  };

  const removeIngredient = (idx: number) => {
    if (!editedProfile) return;
    setEditedProfile({
      ...editedProfile,
      constraints: {
        ...editedProfile.constraints,
        banned_ingredients: editedProfile.constraints.banned_ingredients.filter((_, i) => i !== idx),
      },
    });
  };

  const addBase = () => {
    if (!editedProfile) return;
    const nextId = `B${String((editedProfile.bases.length || 0) + 1).padStart(4, '0')}`;
    setEditedProfile({
      ...editedProfile,
      bases: [...editedProfile.bases, { base_id: nextId, name: '', location: '', province: '', facility_type: '', growth_stage: '', sowing_date: '', notes: '' }],
    });
  };

  const removeBase = (idx: number) => {
    if (!editedProfile) return;
    setEditedProfile({ ...editedProfile, bases: editedProfile.bases.filter((_, i) => i !== idx) });
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      <div>
        <h1 className="text-3xl font-bold text-white"><span className="text-[#c8f7c5]">档案管理</span></h1>
        <p className="text-white/60 mt-1">仅用于编辑业务资料（基地、约束、种植参数）。账号新增/删除/改角色请在“账号管理”完成。</p>
      </div>

      {errorMessage ? <Card className="border-red-500/30 bg-red-500/10"><CardContent className="pt-6 text-red-300 text-sm">{errorMessage}</CardContent></Card> : null}
      {infoMessage ? <Card className="border-[#c8f7c5]/30 bg-[#c8f7c5]/10"><CardContent className="pt-6 text-[#c8f7c5] text-sm">{infoMessage}</CardContent></Card> : null}

      <div className={cn('grid gap-6', canManageAllProfiles ? 'lg:grid-cols-4' : 'lg:grid-cols-1')}>
        {canManageAllProfiles ? (
          <Card className="glass-card lg:col-span-1">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white flex items-center gap-2"><Users className="w-5 h-5 text-[#c8f7c5]" />全部档案</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => { void fetchProfiles(); }} disabled={loading} className="text-white/60 hover:text-white">
                <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
              </Button>
            </CardHeader>
            <CardContent className="space-y-2">
              {sortedProfiles.map((profile) => {
                const isMine = authUser?.userId && profile.owner_user_id === authUser.userId;
                return (
                  <button
                    type="button"
                    key={profile.farmer_id}
                    onClick={() => { void fetchProfileDetail(profile.farmer_id); }}
                    className={cn(
                      'w-full p-3 rounded-xl text-left transition-all border',
                      selectedProfile?.farmer_id === profile.farmer_id
                        ? 'bg-[#c8f7c5]/20 border-[#c8f7c5]/50'
                        : 'bg-white/5 border-transparent hover:bg-white/10',
                    )}
                  >
                    <p className="text-white font-medium">{profile.display_name || profile.farmer_id}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-white/40 text-xs">{profile.farmer_id}</p>
                      {isMine ? <Badge className="bg-[#c8f7c5] text-black text-[10px]">我的档案</Badge> : null}
                    </div>
                  </button>
                );
              })}
            </CardContent>
          </Card>
        ) : null}

        <Card className={cn('glass-card', canManageAllProfiles ? 'lg:col-span-3' : 'lg:col-span-1')}>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-white">{selectedProfile ? `当前档案: ${selectedProfile.farmer_id}` : '请选择档案'}</CardTitle>
            {editedProfile ? (
              <Button variant="outline" size="sm" onClick={() => { void saveProfile(); }} className="border-[#c8f7c5]/50 text-[#c8f7c5] hover:bg-[#c8f7c5]/10">
                <Save className="w-4 h-4 mr-1" />保存
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            {!editedProfile ? (
              <div className="text-center py-16 text-white/40"><Sprout className="w-16 h-16 mx-auto mb-4 opacity-50" /><p>请选择档案查看详情</p></div>
            ) : (
              <div className="space-y-6">
                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2"><Users className="w-4 h-4" />档案基本信息</h3>
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div className="space-y-2"><Label className="text-white/60">档案ID</Label><Input value={editedProfile.farmer_id} disabled className="bg-white/5 border-white/20 text-white/60" /></div>
                    <div className="space-y-2"><Label className="text-white/60">绑定账号ID</Label><Input value={editedProfile.owner_user_id} disabled className="bg-white/5 border-white/20 text-white/60" /></div>
                    <div className="space-y-2"><Label className="text-white/60">显示名</Label><Input value={editedProfile.display_name} onChange={(e) => setEditedProfile({ ...editedProfile, display_name: e.target.value, name: e.target.value })} className="bg-white/5 border-white/20 text-white" /></div>
                    <div className="space-y-2"><Label className="text-white/60">当前基地</Label>
                      <Select value={editedProfile.active_base_id || ''} onValueChange={(v) => setEditedProfile({ ...editedProfile, active_base_id: v })}>
                        <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                        <SelectContent>{editedProfile.bases.map((base) => <SelectItem key={base.base_id} value={base.base_id}>{base.name || base.base_id}</SelectItem>)}</SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-center gap-2"><Checkbox checked={editedProfile.confirm_when_low_confidence} onCheckedChange={(v) => setEditedProfile({ ...editedProfile, confirm_when_low_confidence: Boolean(v) })} /><Label className="text-white/80">低置信度需确认</Label></div>
                    <div className="space-y-2"><Label className="text-white/60">种植规模</Label><Select value={editedProfile.farm_scale} onValueChange={(v) => setEditedProfile({ ...editedProfile, farm_scale: v as FarmerProfile['farm_scale'] })}><SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger><SelectContent>{FARM_SCALE_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getFarmScaleLabel(v)}</SelectItem>)}</SelectContent></Select></div>
                    <div className="space-y-2"><Label className="text-white/60">购药能力</Label><Select value={editedProfile.pesticide_access_level} onValueChange={(v) => setEditedProfile({ ...editedProfile, pesticide_access_level: v as FarmerProfile['pesticide_access_level'] })}><SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger><SelectContent>{PESTICIDE_ACCESS_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getPesticideAccessLevelLabel(v)}</SelectItem>)}</SelectContent></Select></div>
                    <div className="space-y-2"><Label className="text-white/60">栽培模式</Label><Select value={editedProfile.cultivation_mode} onValueChange={(v) => setEditedProfile({ ...editedProfile, cultivation_mode: v as FarmerProfile['cultivation_mode'] })}><SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger><SelectContent>{CULTIVATION_MODE_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getCultivationModeLabel(v)}</SelectItem>)}</SelectContent></Select></div>
                    <div className="space-y-2"><Label className="text-white/60">经验水平</Label><Select value={editedProfile.experience_level} onValueChange={(v) => setEditedProfile({ ...editedProfile, experience_level: v as FarmerProfile['experience_level'] })}><SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger><SelectContent>{EXPERIENCE_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getExperienceLevelLabel(v)}</SelectItem>)}</SelectContent></Select></div>
                    <div className="space-y-2"><Label className="text-white/60">风险偏好</Label><Select value={editedProfile.risk_preference} onValueChange={(v) => setEditedProfile({ ...editedProfile, risk_preference: v as FarmerProfile['risk_preference'] })}><SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger><SelectContent>{RISK_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getRiskPreferenceLabel(v)}</SelectItem>)}</SelectContent></Select></div>
                    <div className="space-y-2 sm:col-span-2"><Label className="text-white/60">可用设备（多选）</Label><div className="flex flex-wrap gap-2">{EQUIPMENT_OPTIONS.map((eq) => { const checked = editedProfile.equipment.includes(eq); return <label key={eq} className="inline-flex items-center gap-2 text-sm text-white/80 bg-white/5 border border-white/10 px-2 py-1 rounded"><Checkbox checked={checked} onCheckedChange={(v) => setEditedProfile({ ...editedProfile, equipment: v ? Array.from(new Set([...editedProfile.equipment, eq])) as FarmerProfile['equipment'] : editedProfile.equipment.filter((item) => item !== eq) })} /><span>{getEquipmentLabel(eq)}</span></label>; })}</div></div>
                    <div className="space-y-2 sm:col-span-2"><Label className="text-white/60">系统预估方案档位</Label><Badge className="bg-emerald-900/50 border border-emerald-600/60 text-emerald-100">{getSelectedBranchLabel(predictBranch(editedProfile))}</Badge></div>
                  </div>
                </div>

                <Separator className="bg-white/10" />

                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2"><Ban className="w-4 h-4" />治疗约束</h3>
                  <div className="space-y-4">
                    <div className="flex items-center gap-2"><Checkbox checked={editedProfile.constraints.prefer_organic} onCheckedChange={(v) => setEditedProfile({ ...editedProfile, constraints: { ...editedProfile.constraints, prefer_organic: Boolean(v) } })} /><Label className="text-white/80">有机/低残留偏好</Label></div>
                    <div className="space-y-2"><Label className="text-white/60">距离采收期（天）</Label><Input value={`${editedProfile.constraints.harvest_window_days ?? 0}`} readOnly className="bg-white/5 border-white/10 text-white/80" /></div>
                    <div className="space-y-2"><Label className="text-white/60">禁用成分关键词</Label><div className="flex gap-2"><Input value={newIngredient} onChange={(e) => setNewIngredient(e.target.value)} className="bg-white/5 border-white/20 text-white" /><Button onClick={addIngredient} variant="outline" className="border-white/20 text-white">添加</Button></div><div className="flex flex-wrap gap-2">{editedProfile.constraints.banned_ingredients.map((ing, idx) => <Badge key={`${ing}-${idx}`} variant="outline" className="border-red-400/50 text-red-400 cursor-pointer" onClick={() => removeIngredient(idx)}>{ing} ×</Badge>)}</div></div>
                  </div>
                </div>

                <Separator className="bg-white/10" />

                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2"><MapPin className="w-4 h-4" />基地信息</h3>
                  <div className="mb-3"><Button onClick={addBase} variant="outline" size="sm" className="border-[#c8f7c5]/50 text-[#c8f7c5]"><Plus className="w-4 h-4 mr-1" />新增基地</Button></div>
                  <div className="space-y-4">
                    {editedProfile.bases.map((base, idx) => (
                      <div key={`${base.base_id}-${idx}`} className="bg-white/5 rounded-xl p-4 space-y-3">
                        <div className="flex items-center justify-between"><Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5]">{base.base_id}</Badge><Button onClick={() => removeBase(idx)} variant="ghost" size="sm" className="text-red-400"><Trash2 className="w-4 h-4" /></Button></div>
                        <div className="grid sm:grid-cols-2 gap-3">
                          <div className="space-y-1"><Label className="text-white/60 text-xs">基地名称</Label><Input value={base.name} onChange={(e) => { const next = [...editedProfile.bases]; next[idx].name = e.target.value; setEditedProfile({ ...editedProfile, bases: next }); }} className="bg-white/10 border-white/20 text-white text-sm" /></div>
                          <div className="space-y-1"><Label className="text-white/60 text-xs">位置/地址</Label><Input value={base.location} onChange={(e) => { const next = [...editedProfile.bases]; next[idx].location = e.target.value; setEditedProfile({ ...editedProfile, bases: next }); }} className="bg-white/10 border-white/20 text-white text-sm" /></div>
                          <div className="space-y-1"><Label className="text-white/60 text-xs">省份</Label><Input value={base.province} onChange={(e) => { const next = [...editedProfile.bases]; next[idx].province = e.target.value; setEditedProfile({ ...editedProfile, bases: next }); }} className="bg-white/10 border-white/20 text-white text-sm" /></div>
                          <div className="space-y-1"><Label className="text-white/60 text-xs">设施类型</Label><Input value={base.facility_type} onChange={(e) => { const next = [...editedProfile.bases]; next[idx].facility_type = e.target.value; setEditedProfile({ ...editedProfile, bases: next }); }} className="bg-white/10 border-white/20 text-white text-sm" /></div>
                          <div className="space-y-1"><Label className="text-white/60 text-xs">生长阶段</Label><Select value={normalizeGrowthStage(base.growth_stage) || '__EMPTY__'} onValueChange={(value) => { const next = [...editedProfile.bases]; next[idx].growth_stage = value === '__EMPTY__' ? '' : value; setEditedProfile({ ...editedProfile, bases: next }); }}><SelectTrigger className="bg-white/10 border-white/20 text-white text-sm"><SelectValue placeholder="请选择生长阶段" /></SelectTrigger><SelectContent><SelectItem value="__EMPTY__">未设置</SelectItem>{TOMATO_GROWTH_STAGE_OPTIONS.map((stage) => <SelectItem key={stage.value} value={stage.value}>{stage.label}</SelectItem>)}</SelectContent></Select></div>
                          <div className="space-y-1"><Label className="text-white/60 text-xs">播种日期</Label><Input type="date" value={base.sowing_date} onChange={(e) => { const next = [...editedProfile.bases]; next[idx].sowing_date = e.target.value; setEditedProfile({ ...editedProfile, bases: next }); }} className="bg-white/10 border-white/20 text-white text-sm" /></div>
                          <div className="space-y-1 sm:col-span-2"><Label className="text-white/60 text-xs">备注</Label><Textarea value={base.notes} onChange={(e) => { const next = [...editedProfile.bases]; next[idx].notes = e.target.value; setEditedProfile({ ...editedProfile, bases: next }); }} className="bg-white/10 border-white/20 text-white text-sm" /></div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
