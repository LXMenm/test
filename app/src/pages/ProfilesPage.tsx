import { useState, useEffect } from 'react';
import { Users, Plus, RefreshCw, Save, Trash2, MapPin, Sprout, Ban, Cloud } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { loadAuthUser, normalizeRole, saveAuthUser, type UserRole } from '@/auth';
import {
  getCultivationModeLabel,
  getEquipmentLabel,
  getExperienceLevelLabel,
  getFarmScaleLabel,
  getPesticideAccessLevelLabel,
  getRiskPreferenceLabel,
  getSelectedBranchLabel,
  getGrowthStageLabel,
  normalizeGrowthStage,
  TOMATO_GROWTH_STAGE_OPTIONS,
  type SelectedBranch,
} from '@/lib/profileLabels';

interface RiskItem {
  code: string;
  label: string;
  level: "low" | "medium" | "high" | "warning";
  reason: string;
  source?: string;
}

interface FarmerBase {
  base_id: string;
  internal_base_uid?: string;
  name: string;
  location: string;
  province: string;
  latitude?: number | null;
  longitude?: number | null;
  city?: string;
  district?: string;
  facility_type: string;
  environment: string;
  growth_stage: string;
  sowing_date: string;
  estimated_harvest_window_days: number | null;
  weather_snapshot?: string;
  last_weather_refresh_at?: string;
  weather_temperature_2m?: number | null;
  weather_wind_speed_10m?: number | null;
  risk_tags?: string[];
  risk_reasons?: string[];
  risk_items?: RiskItem[];
  risk_updated_at?: string;
  notes: string;
}

interface FarmerProfile {
  farmer_id: string;
  name: string;
  display_name: string;
  role_type: 'FARMER' | 'EXPERT' | 'ADMIN';
  owner_user_id: string;
  set_as_default_profile?: boolean;
  active_base_id: string;
  confirm_when_low_confidence: boolean;
  schema_version: string;
  updated_at: string;
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
const PROFILE_ROLE_OPTIONS = ['FARMER', 'EXPERT', 'ADMIN'] as const;
const PROFILE_ROLE_LABELS: Record<FarmerProfile['role_type'], string> = {
  FARMER: '农户',
  EXPERT: '专家',
  ADMIN: '管理员',
};


const RISK_LABEL_MAP: Record<string, string> = {
  HIGH_HUMIDITY: '高湿风险',
  RAIN_RISK: '降雨风险',
  POOR_VENTILATION: '通风不良风险',
  NEAR_HARVEST: '临近采收风险',
  SEEDLING_VULNERABLE: '苗期脆弱风险',
  FLOWERING_FRUITING_SENSITIVE: '开花结果期敏感风险',
  GREENHOUSE_PRESSURE: '温室环境风险',
  MISSING_CONTEXT: '信息不完整',
  CONTEXT_CONFLICT: '档案信息冲突',
};

const TOMATO_TOTAL_GROW_DAYS = 120;

const estimateHarvestWindowDays = (sowingDate?: string | null): number | null => {
  if (!sowingDate) return null;
  const parsed = new Date(`${sowingDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  const now = new Date();
  const elapsedDays = Math.max(Math.floor((now.getTime() - parsed.getTime()) / (24 * 60 * 60 * 1000)), 0);
  return Math.max(TOMATO_TOTAL_GROW_DAYS - elapsedDays, 0);
};



const mergeEnvironmentWeather = (environment: string, weatherSummary: string): string => {
  const weather = weatherSummary.trim();
  if (!weather) return environment;
  return weather;
};

const composeLocationText = (payload: Record<string, unknown>, fallback = ''): string => {
  const pick = (...keys: string[]) => {
    for (const key of keys) {
      const value = payload[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
    return '';
  };

  const province = pick('province', 'admin1');
  const city = pick('city', 'name', 'admin2');
  const district = pick('district', 'admin3', 'admin4');
  const location = pick('location');
  if (location) return location;
  const joined = [province, city, district].filter(Boolean).join(' ').trim();
  return joined || fallback;
};
const validateUniqueBaseIds = (bases: FarmerBase[]): string | null => {
  const seen = new Set<string>();
  for (const base of bases) {
    const id = base.base_id.trim();
    if (!id) continue;
    if (seen.has(id)) return id;
    seen.add(id);
  }
  return null;
};


const predictBranch = (
  profile: Pick<FarmerProfile, 'farm_scale' | 'pesticide_access_level' | 'equipment'>
): SelectedBranch => {
  if (profile.pesticide_access_level === 'NONE') return 'FAMILY';
  if (profile.farm_scale === 'BALCONY' || profile.farm_scale === 'SMALL') return 'FAMILY';
  if (profile.farm_scale === 'MEDIUM') return 'MID';

  if (profile.farm_scale === 'LARGE' || profile.farm_scale === 'GREENHOUSE_LARGE') {
    const hasAdvancedEquipment = profile.equipment.includes('DRONE') || profile.equipment.includes('MIST_BLOWER');
    if (profile.equipment.length === 0 && profile.pesticide_access_level !== 'FULL') return 'MID';
    if (profile.farm_scale === 'GREENHOUSE_LARGE' && profile.pesticide_access_level === 'FULL' && hasAdvancedEquipment) return 'ENTERPRISE';
    return 'ENTERPRISE';
  }

  return 'MID';
};

const toSafeString = (value: unknown, fallback = ''): string => {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
};

const toSafeNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
};

const formatDisplayTime = (value?: string): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
};

const normalizeBase = (baseId: string, base: unknown): FarmerBase => {
  const baseObj = base && typeof base === 'object' ? base as Record<string, unknown> : {};
  const latitude = typeof baseObj.latitude === 'number' ? baseObj.latitude : null;
  const longitude = typeof baseObj.longitude === 'number' ? baseObj.longitude : null;
  return {
    base_id: toSafeString(baseObj.base_id, baseId),
    name: toSafeString(baseObj.name),
    location: toSafeString(baseObj.location),
    province: toSafeString(baseObj.province),
    latitude,
    longitude,
    city: toSafeString(baseObj.city),
    district: toSafeString(baseObj.district),
    facility_type: toSafeString(baseObj.facility_type ?? baseObj.facility),
    environment: toSafeString(baseObj.environment),
    growth_stage: normalizeGrowthStage(toSafeString(baseObj.growth_stage)),
    sowing_date: toSafeString(baseObj.sowing_date),
    estimated_harvest_window_days: estimateHarvestWindowDays(toSafeString(baseObj.sowing_date)),
    weather_snapshot: toSafeString(baseObj.weather_snapshot),
    last_weather_refresh_at: toSafeString(baseObj.last_weather_refresh_at),
    weather_temperature_2m: typeof baseObj.weather_temperature_2m === 'number' ? baseObj.weather_temperature_2m : null,
    weather_wind_speed_10m: typeof baseObj.weather_wind_speed_10m === 'number' ? baseObj.weather_wind_speed_10m : null,
    risk_tags: Array.isArray(baseObj.risk_tags) ? baseObj.risk_tags.map((item: unknown) => toSafeString(item)).filter(Boolean) : [],
    risk_reasons: Array.isArray(baseObj.risk_reasons) ? baseObj.risk_reasons.map((item: unknown) => toSafeString(item)).filter(Boolean) : [],
    risk_items: Array.isArray(baseObj.risk_items)
      ? baseObj.risk_items
        .map((item: unknown) => {
          const obj = item && typeof item === 'object' ? item as Record<string, unknown> : {};
          const code = toSafeString(obj.code);
          const label = toSafeString(obj.label, RISK_LABEL_MAP[code] || code);
          const reason = toSafeString(obj.reason);
          const level = toSafeString(obj.level, 'low');
          if (!code || !label || !reason) return null;
          return {
            code,
            label,
            reason,
            level: (level === 'high' || level === 'medium' || level === 'low') ? level : 'low',
          } as RiskItem;
        })
        .filter((item): item is RiskItem => Boolean(item))
      : [],
    risk_updated_at: toSafeString(baseObj.risk_updated_at),
    notes: toSafeString(baseObj.notes),
    internal_base_uid: toSafeString(baseObj.internal_base_uid) || undefined,
  };
};

const normalizeProfile = (raw: unknown): FarmerProfile => {
  const rawObj = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  const rawBases = rawObj.bases;
  const basesArray: FarmerBase[] = Array.isArray(rawBases)
    ? rawBases.map((base: unknown, idx) => {
      const baseObj = base && typeof base === 'object' ? base as Record<string, unknown> : {};
      return normalizeBase(toSafeString(baseObj.base_id, `B${idx + 1}`), baseObj);
    })
    : rawBases && typeof rawBases === 'object'
      ? Object.entries(rawBases).map(([baseId, base]) => normalizeBase(baseId, base))
      : [];

  const rawConstraints = rawObj.constraints && typeof rawObj.constraints === 'object'
    ? rawObj.constraints as Record<string, unknown>
    : {};
  const rawBanned = rawConstraints.banned_ingredients;

  const profile: FarmerProfile = {
    farmer_id: toSafeString(rawObj.farmer_id),
    name: toSafeString(rawObj.name),
    display_name: toSafeString(rawObj.display_name || rawObj.name || rawObj.farmer_id),
    role_type: (PROFILE_ROLE_OPTIONS.includes(toSafeString(rawObj.role_type) as never) ? toSafeString(rawObj.role_type) : 'FARMER') as FarmerProfile['role_type'],
    owner_user_id: toSafeString(rawObj.owner_user_id),
    set_as_default_profile: Boolean(rawObj.set_as_default_profile),
    active_base_id: toSafeString(rawObj.active_base_id),
    confirm_when_low_confidence: Boolean(rawObj.confirm_when_low_confidence),
    schema_version: toSafeString(rawObj.schema_version, '1.2'),
    updated_at: toSafeString(rawObj.updated_at),
    farm_scale: (FARM_SCALE_OPTIONS.includes(toSafeString(rawObj.farm_scale) as never) ? toSafeString(rawObj.farm_scale) : 'SMALL') as FarmerProfile['farm_scale'],
    pesticide_access_level: (PESTICIDE_ACCESS_OPTIONS.includes(toSafeString(rawObj.pesticide_access_level) as never) ? toSafeString(rawObj.pesticide_access_level) : 'LIMITED') as FarmerProfile['pesticide_access_level'],
    equipment: (Array.isArray(rawObj.equipment) ? rawObj.equipment : [])
      .map((v) => toSafeString(v))
      .filter((v): v is FarmerProfile['equipment'][number] => EQUIPMENT_OPTIONS.includes(v as never)),
    cultivation_mode: (CULTIVATION_MODE_OPTIONS.includes(toSafeString(rawObj.cultivation_mode) as never) ? toSafeString(rawObj.cultivation_mode) : 'SOIL') as FarmerProfile['cultivation_mode'],
    experience_level: (EXPERIENCE_OPTIONS.includes(toSafeString(rawObj.experience_level) as never) ? toSafeString(rawObj.experience_level) : 'INTERMEDIATE') as FarmerProfile['experience_level'],
    risk_preference: (RISK_OPTIONS.includes(toSafeString(rawObj.risk_preference) as never) ? toSafeString(rawObj.risk_preference) : 'BALANCED') as FarmerProfile['risk_preference'],
    constraints: {
      prefer_organic: Boolean(rawConstraints.prefer_organic),
      harvest_window_days: toSafeNumber(rawConstraints.harvest_window_days, 0),
      banned_ingredients: Array.isArray(rawBanned)
        ? rawBanned.map((item: unknown) => toSafeString(item)).filter(Boolean)
        : [],
    },
    bases: basesArray,
  };

  const activeBase = profile.active_base_id ? profile.bases.find((base) => base.base_id === profile.active_base_id) : null;
  const estimated = estimateHarvestWindowDays(activeBase?.sowing_date);
  if (estimated !== null) profile.constraints.harvest_window_days = estimated;

  return profile;
};


const normalizeProfileList = (raw: unknown): FarmerProfile[] => {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item: unknown) => {
      const itemObj = item && typeof item === 'object' ? item as Record<string, unknown> : {};
      if ('farmer_id' in itemObj) {
        const normalized = normalizeProfile(itemObj);
        return normalized.farmer_id ? normalized : null;
      }
      const farmerId = toSafeString(itemObj.id).trim();
      if (!farmerId) return null;
      const displayName = toSafeString(itemObj.name).trim();
      return {
        farmer_id: farmerId,
        name: displayName || farmerId,
        display_name: displayName || farmerId,
        role_type: 'FARMER',
        owner_user_id: '',
        set_as_default_profile: false,
        active_base_id: '',
        confirm_when_low_confidence: true,
        schema_version: '1.1',
        updated_at: '',
        farm_scale: 'SMALL',
        pesticide_access_level: 'LIMITED',
        equipment: [],
        cultivation_mode: 'SOIL',
        experience_level: 'INTERMEDIATE',
        risk_preference: 'BALANCED',
        constraints: {
          prefer_organic: false,
          harvest_window_days: 0,
          banned_ingredients: [],
        },
        bases: [],
      };
    })
    .filter((item): item is FarmerProfile => Boolean(item && item.farmer_id));
};

export function ProfilesPage() {
  const authUser = loadAuthUser();
  const currentRole: UserRole = authUser?.role || 'USER';
  const canManageAllProfiles = currentRole === 'ADMIN';
  const [profiles, setProfiles] = useState<FarmerProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<FarmerProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newProfileName, setNewProfileName] = useState('');
  const [newProfileRoleType, setNewProfileRoleType] = useState<FarmerProfile['role_type']>('FARMER');
  const [newProfileOwnerUserId, setNewProfileOwnerUserId] = useState('');
  const [newProfileSetAsDefault, setNewProfileSetAsDefault] = useState(false);
  const [editedProfile, setEditedProfile] = useState<FarmerProfile | null>(null);
  const [newIngredient, setNewIngredient] = useState('');
  const [showAddBaseDialog, setShowAddBaseDialog] = useState(false);
  const [newBaseId, setNewBaseId] = useState('');
  const [allBaseIds, setAllBaseIds] = useState<Set<string>>(new Set());
  const [adminRoleFilter, setAdminRoleFilter] = useState<'ALL' | FarmerProfile['role_type']>('ALL');
  const [adminViewMode, setAdminViewMode] = useState<'MINE' | 'ALL'>(authUser?.linkedFarmerId ? 'MINE' : 'ALL');

  // 获取所有基地ID，用于检查全局重复
  const fetchAllBaseIds = async () => {
    try {
      const resp = await fetch('/api/profiles/base-ids');
      if (resp.ok) {
        const data = await resp.json();
        const baseIds = new Set<string>();
        if (Array.isArray(data?.items)) {
          data.items.forEach((item: unknown) => {
            const itemObj = item && typeof item === 'object' ? item as Record<string, unknown> : {};
            if (typeof itemObj.base_id === 'string') {
              baseIds.add(itemObj.base_id);
            }
          });
        }
        setAllBaseIds(baseIds);
      }
    } catch (error) {
      console.error('Failed to fetch base IDs:', error);
    }
  };

  // 组件加载时获取所有基地ID
  useEffect(() => {
    fetchAllBaseIds();
  }, []);
  const [errorMessage, setErrorMessage] = useState('');
  const [infoMessage, setInfoMessage] = useState('');
  const [locatingBaseId, setLocatingBaseId] = useState<string | null>(null);

  const parseJsonOrThrow = async (resp: Response) => {
    let payload: Record<string, unknown> | null = null;
    try {
      const parsed: unknown = await resp.json();
      payload = parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null;
    } catch {
      // noop
    }
    if (!resp.ok) {
      const detail = (payload?.detail ?? payload?.message ?? `请求失败：${resp.status}`);
      throw new Error(String(detail));
    }
    return payload;
  };

  const applyAccountSyncIfNeeded = (payload: Record<string, unknown> | null) => {
    const accountSync = payload?.account_sync;
    if (!accountSync || typeof accountSync !== 'object') return;
    const syncObj = accountSync as Record<string, unknown>;
    const syncedUserId = toSafeString(syncObj.user_id).trim();
    if (!syncedUserId) return;
    if (authUser?.userId && syncedUserId === authUser.userId) {
      saveAuthUser({
        userId: authUser.userId,
        displayName: authUser.displayName,
        role: normalizeRole(syncObj.role),
        linkedFarmerId: toSafeString(syncObj.linked_farmer_id) || null,
      });
      if (canManageAllProfiles) {
        setAdminViewMode((toSafeString(syncObj.linked_farmer_id) || authUser.linkedFarmerId) ? 'MINE' : 'ALL');
      }
      setInfoMessage('已同步当前登录账号的主诊断档案与权限角色。');
      return;
    }
    setInfoMessage('绑定已保存；对方刷新页面或重新登录后可看到自己的主诊断档案。');
  };

  const fetchProfiles = async () => {
    setLoading(true);
    setErrorMessage('');
    setInfoMessage('');
    try {
      const params = new URLSearchParams();
      if (canManageAllProfiles && adminRoleFilter !== 'ALL') params.set('role_type', adminRoleFilter);
      if (canManageAllProfiles && adminViewMode === 'MINE') params.set('prefer_actor_linked', '1');
      const query = params.toString() ? `?${params.toString()}` : '';
      const resp = await fetch(`/api/profiles${query}`);
      const data = await parseJsonOrThrow(resp);
      const nextProfiles = normalizeProfileList(data?.profiles);
      setProfiles(nextProfiles);
      if (canManageAllProfiles && adminViewMode === 'MINE' && authUser?.linkedFarmerId) {
        if (nextProfiles[0]?.farmer_id) {
          void fetchProfileDetail(nextProfiles[0].farmer_id);
        } else {
          setSelectedProfile(null);
          setEditedProfile(null);
        }
      } else if (!canManageAllProfiles && nextProfiles[0]?.farmer_id) {
        void fetchProfileDetail(nextProfiles[0].farmer_id);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : '加载档案列表失败';
      setErrorMessage(msg);
      console.error('Failed to fetch profiles:', error);
      setProfiles([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchProfileDetail = async (farmerId: string) => {
    if (!farmerId) return;
    setErrorMessage('');
    setInfoMessage('');
    try {
      const resp = await fetch(`/api/profiles/${encodeURIComponent(farmerId)}`);
      const data = await parseJsonOrThrow(resp);
      const normalized = normalizeProfile(data);
      setSelectedProfile(normalized);
      setEditedProfile(JSON.parse(JSON.stringify(normalized)));
    } catch (error) {
      const msg = error instanceof Error ? error.message : '加载农户详情失败';
      setErrorMessage(msg);
      console.error('Failed to fetch profile detail:', error);
    }
  };

  const saveProfile = async () => {
    if (!editedProfile) return;

    setErrorMessage('');
    setInfoMessage('');
    const duplicateBaseId = validateUniqueBaseIds(editedProfile.bases);
    if (duplicateBaseId) {
      setErrorMessage(`基地ID重复：${duplicateBaseId}（同一农户下不允许重复）`);
      return;
    }

    const basesMap = Object.fromEntries(editedProfile.bases.map((base) => [base.base_id, {
      base_id: base.base_id,
      internal_base_uid: base.internal_base_uid,
      name: base.name,
      location: base.location,
      province: base.province,
      latitude: typeof base.latitude === 'number' ? base.latitude : null,
      longitude: typeof base.longitude === 'number' ? base.longitude : null,
      city: base.city,
      district: base.district,
      facility: base.facility_type,
      environment: base.environment,
      growth_stage: normalizeGrowthStage(base.growth_stage),
      sowing_date: base.sowing_date || null,
      weather_snapshot: base.weather_snapshot,
      last_weather_refresh_at: base.last_weather_refresh_at || null,
      weather_temperature_2m: typeof base.weather_temperature_2m === 'number' ? base.weather_temperature_2m : null,
      weather_wind_speed_10m: typeof base.weather_wind_speed_10m === 'number' ? base.weather_wind_speed_10m : null,
      risk_tags: base.risk_tags || [],
      risk_reasons: base.risk_reasons || [],
      risk_items: base.risk_items || [],
      risk_updated_at: base.risk_updated_at || null,
      notes: base.notes,
    }]));
    const activeBase = editedProfile.active_base_id
      ? editedProfile.bases.find((base) => base.base_id === editedProfile.active_base_id)
      : null;
    const estimatedHarvest = estimateHarvestWindowDays(activeBase?.sowing_date);

    try {
      const resp = await fetch(`/api/profiles/${editedProfile.farmer_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...editedProfile,
          display_name: editedProfile.display_name || editedProfile.name || editedProfile.farmer_id,
          owner_user_id: editedProfile.owner_user_id,
          role_type: editedProfile.role_type,
          set_as_default_profile: Boolean(editedProfile.set_as_default_profile),
          bases: basesMap,
          constraints: {
            ...editedProfile.constraints,
            harvest_window_days: estimatedHarvest ?? editedProfile.constraints.harvest_window_days,
          },
        })
      });
      const data = await parseJsonOrThrow(resp);
      applyAccountSyncIfNeeded(data);
      fetchProfiles();
      setSelectedProfile(editedProfile);
    } catch (error) {
      const msg = error instanceof Error ? error.message : '保存农户失败';
      setErrorMessage(msg);
      console.error('Failed to save profile:', error);
    }
  };

  const [showErrorDialog, setShowErrorDialog] = useState(false);
  const [errorDialogMessage, setErrorDialogMessage] = useState('');

  const createProfileWithPayload = async (payload: Record<string, unknown>) => {
    setErrorMessage('');
    setErrorDialogMessage('');
    setInfoMessage('');
    try {
      const resp = await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await parseJsonOrThrow(resp);
      const createdId = typeof data?.id === 'string'
        ? data.id
        : (typeof data?.farmer_id === 'string' ? data.farmer_id : null);

      if (createdId) {
        applyAccountSyncIfNeeded(data);
        fetchProfiles();
        fetchProfileDetail(createdId);
        setShowAddDialog(false);
        setNewProfileName('');
        setNewProfileRoleType('FARMER');
        setNewProfileOwnerUserId('');
        setNewProfileSetAsDefault(false);
      } else {
        setErrorDialogMessage('创建成功但未返回有效 farmer_id，无法自动打开详情');
        setShowErrorDialog(true);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : '创建档案失败';
      setErrorDialogMessage(msg);
      setShowErrorDialog(true);
      console.error('Failed to create profile:', error);
    }
  };

  const createProfile = async () => {
    if (!newProfileName.trim()) return;
    await createProfileWithPayload({
      name: newProfileName,
      display_name: newProfileName,
      role_type: newProfileRoleType,
      owner_user_id: canManageAllProfiles ? newProfileOwnerUserId.trim() : (authUser?.userId || ''),
      set_as_default_profile: canManageAllProfiles ? newProfileSetAsDefault : true,
      confirm_when_low_confidence: true,
      constraints: {
        prefer_organic: false,
        harvest_window_days: 30,
        banned_ingredients: []
      },
      farm_scale: 'SMALL',
      pesticide_access_level: 'LIMITED',
      equipment: [],
      cultivation_mode: 'SOIL',
      experience_level: 'INTERMEDIATE',
      risk_preference: 'BALANCED',
    });
  };

  const deleteProfile = async () => {
    if (!selectedProfile) return;

    setErrorMessage('');
    try {
      const resp = await fetch(`/api/profiles/${selectedProfile.farmer_id}`, {
        method: 'DELETE'
      });

      await parseJsonOrThrow(resp);
      setSelectedProfile(null);
      setEditedProfile(null);
      fetchProfiles();
    } catch (error) {
      const msg = error instanceof Error ? error.message : '删除农户失败';
      setErrorMessage(msg);
      console.error('Failed to delete profile:', error);
    }
  };

  const addIngredient = () => {
    if (!newIngredient.trim() || !editedProfile) return;

    setEditedProfile({
      ...editedProfile,
      constraints: {
        ...editedProfile.constraints,
        banned_ingredients: [
          ...(Array.isArray(editedProfile.constraints.banned_ingredients)
            ? editedProfile.constraints.banned_ingredients
            : []),
          newIngredient.trim(),
        ]
      }
    });
    setNewIngredient('');
  };

  const removeIngredient = (idx: number) => {
    if (!editedProfile) return;

    setEditedProfile({
      ...editedProfile,
      constraints: {
        ...editedProfile.constraints,
        banned_ingredients: (Array.isArray(editedProfile.constraints.banned_ingredients)
          ? editedProfile.constraints.banned_ingredients
          : []
        ).filter((_, i) => i !== idx)
      }
    });
  };

  const addBase = () => {
    if (!newBaseId.trim() || !editedProfile) return;

    const safeBaseId = newBaseId.trim();
    
    // 检查同一农户下的重复
    const existsInCurrent = editedProfile.bases.some((base) => base.base_id === safeBaseId);
    if (existsInCurrent) {
      setErrorDialogMessage(`基地ID重复：${safeBaseId}（同一农户下不允许重复）`);
      setShowErrorDialog(true);
      return;
    }
    
    // 检查全局重复
    if (allBaseIds.has(safeBaseId)) {
      setErrorDialogMessage(`基地ID已存在，请更换后再试`);
      setShowErrorDialog(true);
      return;
    }

    setEditedProfile({
      ...editedProfile,
      bases: [...(Array.isArray(editedProfile.bases) ? editedProfile.bases : []), {
        base_id: safeBaseId,
        name: '',
        location: '',
        province: '',
        latitude: null,
        longitude: null,
        city: '',
        district: '',
        facility_type: '',
        environment: '',
        growth_stage: '',
        sowing_date: '',
        estimated_harvest_window_days: null,
        weather_snapshot: '',
        last_weather_refresh_at: '',
        weather_temperature_2m: null,
        weather_wind_speed_10m: null,
        notes: ''
      }]
    });
    
    // 更新本地的基地ID集合
    setAllBaseIds(prev => new Set(prev).add(safeBaseId));
    
    setShowAddBaseDialog(false);
    setNewBaseId('');
  };

  const removeBase = (idx: number) => {
    if (!editedProfile) return;

    setEditedProfile({
      ...editedProfile,
      bases: (Array.isArray(editedProfile.bases) ? editedProfile.bases : []).filter((_, i) => i !== idx)
    });
  };

  const updateBase = (idx: number, updater: (base: FarmerBase) => FarmerBase) => {
    setEditedProfile((prev) => {
      if (!prev) return prev;
      if (!Array.isArray(prev.bases) || !prev.bases[idx]) return prev;
      const newBases = [...prev.bases];
      newBases[idx] = updater(newBases[idx]);
      return { ...prev, bases: newBases };
    });
  };

  const handleGetCurrentLocation = (idx: number) => {
    if (!editedProfile) return;
    const targetBase = editedProfile.bases[idx];
    if (!targetBase) return;

    setErrorMessage('');
    setLocatingBaseId(targetBase.base_id || `idx-${idx}`);
    if (!navigator.geolocation) {
      setErrorMessage('当前浏览器不支持地理定位');
      setLocatingBaseId(null);
      return;
    }

    navigator.geolocation.getCurrentPosition(async (position) => {
      const lat = Number(position.coords.latitude.toFixed(6));
      const lon = Number(position.coords.longitude.toFixed(6));

      updateBase(idx, (base) => ({ ...base, latitude: lat, longitude: lon }));

      try {
        const reverseResp = await fetch(`/api/location/reverse?lat=${encodeURIComponent(String(lat))}&lon=${encodeURIComponent(String(lon))}`);
        if (reverseResp.ok) {
          const data = await reverseResp.json();
          const reverseData = data && typeof data === 'object' ? data as Record<string, unknown> : {};
          updateBase(idx, (base) => {
            const nextProvince = (typeof reverseData.province === 'string' && reverseData.province.trim())
              ? reverseData.province.trim()
              : (typeof reverseData.admin1 === 'string' ? reverseData.admin1.trim() : base.province);
            const nextCity = (typeof reverseData.city === 'string' && reverseData.city.trim())
              ? reverseData.city.trim()
              : (typeof reverseData.name === 'string' ? reverseData.name.trim() : (base.city || ''));
            const nextDistrict = (typeof reverseData.district === 'string' && reverseData.district.trim())
              ? reverseData.district.trim()
              : (typeof reverseData.admin3 === 'string' ? reverseData.admin3.trim() : (base.district || ''));
            const nextLocation = composeLocationText(reverseData, base.location);
            return {
              ...base,
              province: nextProvince || base.province,
              city: nextCity || base.city,
              district: nextDistrict || base.district,
              location: nextLocation || base.location,
            };
          });
        } else {
          setErrorMessage('已获取经纬度，但地址解析失败，可手动填写地址');
        }
      } catch {
        setErrorMessage('已获取经纬度，但地址解析失败，可手动填写地址');
      } finally {
        setLocatingBaseId(null);
      }
    }, (err) => {
      const denied = err?.code === 1;
      setErrorMessage(denied ? '定位权限被拒绝，请在浏览器中允许位置访问后重试' : '定位失败，请检查浏览器权限并重试');
      setLocatingBaseId(null);
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  };

  const handleGetWeather = (idx: number) => {
    if (!editedProfile) return;
    const targetBase = editedProfile.bases[idx];
    if (!targetBase || !targetBase.latitude || !targetBase.longitude) return;

    setErrorMessage('');

    const lat = targetBase.latitude;
    const lon = targetBase.longitude;

    fetch(`/api/weather/summary?lat=${encodeURIComponent(String(lat))}&lon=${encodeURIComponent(String(lon))}`)
      .then(async (weatherResp) => {
        if (weatherResp.ok) {
          const weatherData = await weatherResp.json();
          updateBase(idx, (base) => {
            const summary = typeof weatherData.summary === 'string' ? weatherData.summary : '';
            const hasSummary = Boolean(summary.trim());
            const enrichedEnvironment = hasSummary ? mergeEnvironmentWeather(base.environment, summary) : base.environment;
            return {
              ...base,
              weather_snapshot: hasSummary ? summary : base.weather_snapshot,
              environment: enrichedEnvironment,
              last_weather_refresh_at: new Date().toISOString(),
              weather_temperature_2m: typeof weatherData.temperature_2m === 'number' ? weatherData.temperature_2m : base.weather_temperature_2m,
              weather_wind_speed_10m: typeof weatherData.wind_speed_10m === 'number' ? weatherData.wind_speed_10m : base.weather_wind_speed_10m,
            };
          });
        } else {
          setErrorMessage('天气摘要获取失败，不影响保存');
        }
      })
      .catch(() => {
        setErrorMessage('天气摘要获取失败，不影响保存');
      });
  };

  useEffect(() => {
    void fetchProfiles();
  }, [adminRoleFilter, adminViewMode, canManageAllProfiles]);

  useEffect(() => {
    if (canManageAllProfiles) return;
    if (loading) return;
    if (profiles.length > 0) return;
    if (!authUser?.userId) return;
    void createProfileWithPayload({
      farmer_id: authUser.userId,
      owner_user_id: authUser.userId,
      set_as_default_profile: true,
      role_type: currentRole === 'EXPERT' ? 'EXPERT' : 'FARMER',
      name: authUser.displayName || authUser.userId,
      display_name: authUser.displayName || authUser.userId,
      confirm_when_low_confidence: true,
      constraints: {
        prefer_organic: false,
        harvest_window_days: 30,
        banned_ingredients: [],
      },
      farm_scale: 'SMALL',
      pesticide_access_level: 'LIMITED',
      equipment: [],
      cultivation_mode: 'SOIL',
      experience_level: 'INTERMEDIATE',
      risk_preference: 'BALANCED',
    });
  }, [authUser?.displayName, authUser?.userId, canManageAllProfiles, currentRole, loading, profiles.length]);

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">
            <span className="text-[#c8f7c5]">档案管理</span>
          </h1>
          <p className="text-white/60 mt-1">管理农户/专家/管理员档案、治疗约束与基地数据</p>
          {canManageAllProfiles && (
            <div className="flex items-center gap-2 mt-3">
              <Button
                variant={adminViewMode === 'MINE' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAdminViewMode('MINE')}
                className={cn(adminViewMode === 'MINE' ? 'bg-[#c8f7c5] text-black' : 'border-white/20 text-white')}
              >
                我的档案
              </Button>
              <Button
                variant={adminViewMode === 'ALL' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAdminViewMode('ALL')}
                className={cn(adminViewMode === 'ALL' ? 'bg-[#c8f7c5] text-black' : 'border-white/20 text-white')}
              >
                全部档案
              </Button>
            </div>
          )}
        </div>
        {canManageAllProfiles && (
          <Button
            onClick={() => setShowAddDialog(true)}
            className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
          >
            <Plus className="w-4 h-4 mr-2" />
            新增档案
          </Button>
        )}
      </div>

      {errorMessage && (
        <Card className="border-red-500/30 bg-red-500/10">
          <CardContent className="pt-6 text-red-300 text-sm">
            {errorMessage}
          </CardContent>
        </Card>
      )}
      {infoMessage && (
        <Card className="border-[#c8f7c5]/30 bg-[#c8f7c5]/10">
          <CardContent className="pt-6 text-[#c8f7c5] text-sm">
            {infoMessage}
          </CardContent>
        </Card>
      )}
      {canManageAllProfiles && adminViewMode === 'MINE' && !authUser?.linkedFarmerId && (
        <Card className="border-amber-400/30 bg-amber-500/10">
          <CardContent className="pt-6 text-amber-200 text-sm">
            当前未绑定主诊断档案
          </CardContent>
        </Card>
      )}

      {/* Error Dialog */}
      <Dialog open={showErrorDialog} onOpenChange={setShowErrorDialog}>
        <DialogContent className="bg-[#1a3329] border-[#c8f7c5]/30 text-white">
          <DialogHeader>
            <DialogTitle className="text-white">错误提示</DialogTitle>
          </DialogHeader>
          <DialogDescription className="text-white/60">
            {errorDialogMessage}
          </DialogDescription>
          <div className="flex justify-end mt-4">
            <Button 
              onClick={() => setShowErrorDialog(false)}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              确定
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <div className={cn('grid gap-6', canManageAllProfiles ? 'lg:grid-cols-4' : 'lg:grid-cols-1')}>
        {/* Profile List (ADMIN only) */}
        {canManageAllProfiles && <Card className="glass-card lg:col-span-1">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-white flex items-center gap-2">
              <Users className="w-5 h-5 text-[#c8f7c5]" />
              档案列表
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchProfiles}
              disabled={loading}
              className="text-white/60 hover:text-white"
            >
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
            </Button>
          </CardHeader>
          <CardContent>
            <div className="mb-3">
              <Select value={adminRoleFilter} onValueChange={(v) => setAdminRoleFilter(v as typeof adminRoleFilter)}>
                <SelectTrigger className="bg-white/5 border-white/20 text-white">
                  <SelectValue placeholder="角色筛选" />
                </SelectTrigger>
                <SelectContent className="bg-[#111] text-white border-white/20">
                  <SelectItem value="ALL">全部</SelectItem>
                  <SelectItem value="FARMER">农户</SelectItem>
                  <SelectItem value="EXPERT">专家</SelectItem>
                  <SelectItem value="ADMIN">管理员</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              {(Array.isArray(profiles) ? profiles : []).map((profile) => (
                <div
                  key={profile.farmer_id || profile.name}
                  onClick={() => fetchProfileDetail(profile.farmer_id)}
                  className={cn(
                    'p-3 rounded-xl cursor-pointer transition-all duration-300',
                    selectedProfile?.farmer_id === profile.farmer_id
                      ? 'bg-[#c8f7c5]/20 border border-[#c8f7c5]/50'
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                  )}
                >
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 bg-[#c8f7c5]/20 rounded-full flex items-center justify-center">
                      <span className="text-[#c8f7c5] text-xs font-bold">
                        {(profile.name || profile.farmer_id || '?').charAt(0)}
                      </span>
                    </div>
                    <div>
                      <p className="text-white font-medium">{profile.display_name || profile.name || profile.farmer_id || '未命名档案'}</p>
                      <p className="text-white/40 text-xs">{profile.farmer_id} · {PROFILE_ROLE_LABELS[profile.role_type]}</p>
                    </div>
                  </div>
                </div>
              ))}
              {profiles.length === 0 && (
                <div className="text-center py-8 text-white/40">
                  <Users className="w-10 h-10 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">暂无档案</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>}

        {/* Profile Detail */}
        <Card className={cn('glass-card', canManageAllProfiles ? 'lg:col-span-3' : 'lg:col-span-1')}>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="space-y-1">
              <CardTitle className="text-white">
                {selectedProfile ? `当前档案: ${selectedProfile.farmer_id}` : (canManageAllProfiles ? '请选择档案' : '我的档案')}
              </CardTitle>
              {selectedProfile && selectedProfile.updated_at && (
                <p className="text-white/60 text-xs">
                  更新时间为：{new Date(selectedProfile.updated_at).toLocaleString()}
                </p>
              )}
            </div>
            {selectedProfile && editedProfile && (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchProfileDetail(selectedProfile.farmer_id)}
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  <RefreshCw className="w-4 h-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={saveProfile}
                  className="border-[#c8f7c5]/50 text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                >
                  <Save className="w-4 h-4 mr-1" />
                  保存
                </Button>
                {canManageAllProfiles && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={deleteProfile}
                    className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                )}
              </div>
            )}
          </CardHeader>
          <CardContent>
            {editedProfile ? (
              <div className="space-y-6 animate-fadeIn">
                {/* Basic Info */}
                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2">
                    <Users className="w-4 h-4" />
                    档案基本信息
                  </h3>
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-white/60">档案ID</Label>
                      <Input
                        value={editedProfile.farmer_id}
                        disabled
                        className="bg-white/5 border-white/20 text-white/60"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">显示名称</Label>
                      <Input
                        value={editedProfile.display_name}
                        onChange={(e) => setEditedProfile({ ...editedProfile, display_name: e.target.value, name: e.target.value })}
                        className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">档案展示类型</Label>
                      {canManageAllProfiles ? (
                        <div className="space-y-2">
                          <Select value={editedProfile.role_type} onValueChange={(v) => setEditedProfile({ ...editedProfile, role_type: v as FarmerProfile['role_type'] })}>
                            <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                            <SelectContent className="bg-[#1a1a1a] border-white/20">
                              <SelectItem value="FARMER">农户</SelectItem>
                              <SelectItem value="EXPERT">专家</SelectItem>
                              <SelectItem value="ADMIN">管理员</SelectItem>
                            </SelectContent>
                          </Select>
                          <p className="text-xs text-white/60 leading-5">
                            档案展示类型仅用于档案展示，不是权限真相。<br />
                            权限来源是绑定账号的登录角色（USER / EXPERT / ADMIN）。<br />
                            保存时可按选择把绑定账号角色同步为 USER / EXPERT / ADMIN。
                          </p>
                        </div>
                      ) : (
                        <Input value={PROFILE_ROLE_LABELS[editedProfile.role_type]} disabled className="bg-white/5 border-white/20 text-white/60" />
                      )}
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">绑定账号ID</Label>
                      <Input
                        value={editedProfile.owner_user_id || ''}
                        onChange={(e) => setEditedProfile({ ...editedProfile, owner_user_id: e.target.value })}
                        disabled={!canManageAllProfiles}
                        placeholder={canManageAllProfiles ? '可留空（仅保存档案，不同步账号）' : ''}
                        className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5] disabled:text-white/60"
                      />
                    </div>
                    {canManageAllProfiles && (
                      <div className="flex items-center gap-2">
                        <Checkbox
                          checked={Boolean(editedProfile.set_as_default_profile)}
                          onCheckedChange={(v) => setEditedProfile({ ...editedProfile, set_as_default_profile: Boolean(v) })}
                          className="border-white/30 data-[state=checked]:bg-[#c8f7c5] data-[state=checked]:text-black"
                        />
                        <Label className="text-white/80">设为该账号主诊断档案</Label>
                        <p className="text-xs text-white/50">
                          勾选后会把当前档案绑定为该账号当前使用的诊断档案；不勾选仅保存档案，不影响账号已有绑定。
                        </p>
                      </div>
                    )}
                    <div className="space-y-2">
                      <Label className="text-white/60">当前基地</Label>
                      <Select
                        value={editedProfile.active_base_id || ''}
                        onValueChange={(v) => setEditedProfile({ ...editedProfile, active_base_id: v })}
                      >
                        <SelectTrigger className="bg-white/5 border-white/20 text-white">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-[#1a1a1a] border-white/20">
                          {(Array.isArray(editedProfile.bases) ? editedProfile.bases : []).map((base) => (
                            <SelectItem key={base.base_id} value={base.base_id}>
                              {base.name || base.base_id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">档案版本</Label>
                      <Input
                        value={editedProfile.schema_version}
                        disabled
                        className="bg-white/5 border-white/20 text-white/60"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={editedProfile.confirm_when_low_confidence}
                        onCheckedChange={(v) => setEditedProfile({ ...editedProfile, confirm_when_low_confidence: v as boolean })}
                        className="border-white/30 data-[state=checked]:bg-[#c8f7c5] data-[state=checked]:text-black"
                      />
                      <Label className="text-white/80">低置信度需确认</Label>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">种植规模</Label>
                      <Select value={editedProfile.farm_scale} onValueChange={(v) => setEditedProfile({ ...editedProfile, farm_scale: v as FarmerProfile['farm_scale'] })}>
                        <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-[#1a1a1a] border-white/20">
                          {FARM_SCALE_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getFarmScaleLabel(v)}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">购药能力</Label>
                      <Select value={editedProfile.pesticide_access_level} onValueChange={(v) => setEditedProfile({ ...editedProfile, pesticide_access_level: v as FarmerProfile['pesticide_access_level'] })}>
                        <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-[#1a1a1a] border-white/20">
                          {PESTICIDE_ACCESS_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getPesticideAccessLevelLabel(v)}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">栽培模式</Label>
                      <Select value={editedProfile.cultivation_mode} onValueChange={(v) => setEditedProfile({ ...editedProfile, cultivation_mode: v as FarmerProfile['cultivation_mode'] })}>
                        <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-[#1a1a1a] border-white/20">
                          {CULTIVATION_MODE_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getCultivationModeLabel(v)}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">经验水平</Label>
                      <Select value={editedProfile.experience_level} onValueChange={(v) => setEditedProfile({ ...editedProfile, experience_level: v as FarmerProfile['experience_level'] })}>
                        <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-[#1a1a1a] border-white/20">
                          {EXPERIENCE_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getExperienceLevelLabel(v)}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">风险偏好</Label>
                      <Select value={editedProfile.risk_preference} onValueChange={(v) => setEditedProfile({ ...editedProfile, risk_preference: v as FarmerProfile['risk_preference'] })}>
                        <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-[#1a1a1a] border-white/20">
                          {RISK_OPTIONS.map((v) => <SelectItem key={v} value={v}>{getRiskPreferenceLabel(v)}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2 sm:col-span-2">
                      <Label className="text-white/60">可用设备（多选）</Label>
                      <div className="flex flex-wrap gap-2">
                        {EQUIPMENT_OPTIONS.map((eq) => {
                          const checked = editedProfile.equipment.includes(eq);
                          return (
                            <label key={eq} className="inline-flex items-center gap-2 text-sm text-white/80 bg-white/5 border border-white/10 px-2 py-1 rounded">
                              <Checkbox
                                checked={checked}
                                onCheckedChange={(v) => {
                                  const next = v
                                    ? [...editedProfile.equipment, eq]
                                    : editedProfile.equipment.filter((item) => item !== eq);
                                  setEditedProfile({ ...editedProfile, equipment: Array.from(new Set(next)) as FarmerProfile['equipment'] });
                                }}
                                className="border-white/30 data-[state=checked]:bg-[#c8f7c5] data-[state=checked]:text-black"
                              />
                              <span>{getEquipmentLabel(eq)}</span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                    <div className="space-y-2 sm:col-span-2">
                      <Label className="text-white/60">系统预估方案档位</Label>
                      <div className="flex items-center gap-2">
                        <Badge className="bg-emerald-900/50 border border-emerald-600/60 text-emerald-100">
                          {getSelectedBranchLabel(predictBranch(editedProfile))}
                        </Badge>
                        <span className="text-xs text-white/50">{predictBranch(editedProfile)}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <Separator className="bg-white/10" />

                {/* Constraints */}
                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2">
                    <Ban className="w-4 h-4" />
                    治疗约束
                  </h3>
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={editedProfile.constraints.prefer_organic}
                        onCheckedChange={(v) => setEditedProfile({
                          ...editedProfile,
                          constraints: { ...editedProfile.constraints, prefer_organic: v as boolean }
                        })}
                        className="border-white/30 data-[state=checked]:bg-[#c8f7c5] data-[state=checked]:text-black"
                      />
                      <Label className="text-white/80">有机/低残留偏好</Label>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">距离采收期（天）</Label>
                      <Input
                        value={`${editedProfile.constraints.harvest_window_days ?? 0}`}
                        readOnly
                        className="bg-white/5 border-white/10 text-white/80"
                      />
                      <p className="text-xs text-white/45">
                        优先根据活跃基地播种日期自动估算（经验规则），无播种日期时回退历史手填值。
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">禁用成分关键词</Label>
                      <div className="flex gap-2">
                        <Input
                          placeholder="输入成分"
                          value={newIngredient}
                          onChange={(e) => setNewIngredient(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && addIngredient()}
                          className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                        />
                        <Button
                          onClick={addIngredient}
                          variant="outline"
                          className="border-white/20 text-white hover:bg-white/10"
                        >
                          添加
                        </Button>
                      </div>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {(Array.isArray(editedProfile.constraints.banned_ingredients)
                          ? editedProfile.constraints.banned_ingredients
                          : []
                        ).map((ing, idx) => (
                          <Badge
                            key={idx}
                            variant="outline"
                            className="border-red-400/50 text-red-400 cursor-pointer hover:bg-red-400/10"
                            onClick={() => removeIngredient(idx)}
                          >
                            {ing} ×
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                <Separator className="bg-white/10" />

                {/* Bases */}
                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2">
                    <MapPin className="w-4 h-4" />
                    基地信息
                  </h3>
                  <div className="space-y-4">
                    <div className="flex gap-2">
                      <Button
                        onClick={() => setShowAddBaseDialog(true)}
                        variant="outline"
                        size="sm"
                        className="border-[#c8f7c5]/50 text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                      >
                        <Plus className="w-4 h-4 mr-1" />
                        新增基地
                      </Button>
                    </div>

                    {(Array.isArray(editedProfile.bases) ? editedProfile.bases : []).map((base, idx) => (
                      <div key={base.base_id} className="bg-white/5 rounded-xl p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5]">{base.base_id}</Badge>
                          <span className="text-xs text-white/50">{getGrowthStageLabel(base.growth_stage)}</span>
                          <Button
                            onClick={() => removeBase(idx)}
                            variant="ghost"
                            size="sm"
                            className="text-red-400 hover:text-red-300 hover:bg-red-400/10"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                        <div className="grid sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">基地名称</Label>
                            <Input
                              value={base.name}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].name = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">位置/地址</Label>
                            <Input
                              value={base.location}
                              onChange={(e) => updateBase(idx, (current) => ({ ...current, location: e.target.value }))}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1 sm:col-span-2">
                            <div className="flex gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                className="border-white/20 text-white hover:bg-white/10"
                                onClick={() => handleGetCurrentLocation(idx)}
                                disabled={locatingBaseId === (base.base_id || `idx-${idx}`)}
                              >
                                <MapPin className={`w-4 h-4 mr-1 ${locatingBaseId === (base.base_id || `idx-${idx}`) ? 'animate-pulse' : ''}`} />
                                {locatingBaseId === (base.base_id || `idx-${idx}`) ? '定位中…' : '获取当前位置'}
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                className="border-white/20 text-white hover:bg-white/10"
                                onClick={() => handleGetWeather(idx)}
                                disabled={!base.latitude || !base.longitude}
                              >
                                <Cloud className="w-4 h-4 mr-1" />
                                获取天气
                              </Button>
                            </div>
                            <p className="text-xs text-white/60 mt-2">最近天气更新时间：{formatDisplayTime(base.last_weather_refresh_at)}</p>
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">省份</Label>
                            <Input
                              value={base.province}
                              onChange={(e) => updateBase(idx, (current) => ({ ...current, province: e.target.value }))}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">经纬度</Label>
                            <Input
                              value={base.latitude != null && base.longitude != null ? `${base.latitude}, ${base.longitude}` : ''}
                              readOnly
                              placeholder="点击“获取当前位置”自动填充"
                              className="bg-white/5 border-white/10 text-white/70 text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">设施类型</Label>
                            <Input
                              value={base.facility_type}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].facility_type = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">生长阶段</Label>
                            <Select
                              value={normalizeGrowthStage(base.growth_stage) || '__EMPTY__'}
                              onValueChange={(value) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].growth_stage = value === '__EMPTY__' ? '' : value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                            >
                              <SelectTrigger className="bg-white/10 border-white/20 text-white text-sm">
                                <SelectValue placeholder="请选择生长阶段" />
                              </SelectTrigger>
                              <SelectContent className="bg-[#111] text-white border-white/20 max-h-56 overflow-y-auto">
                                <SelectItem value="__EMPTY__">未设置</SelectItem>
                                {TOMATO_GROWTH_STAGE_OPTIONS.map((stage: { value: string; label: string }) => (
                                  <SelectItem key={stage.value} value={stage.value}>{stage.label}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1">
                              <Label className="text-white/60 text-xs">播种日期</Label>
                              <Input
                                type="date"
                                value={base.sowing_date || ''}
                                onChange={(e) => {
                                  const newBases = [...editedProfile.bases];
                                  newBases[idx].sowing_date = e.target.value;
                                  newBases[idx].estimated_harvest_window_days = estimateHarvestWindowDays(e.target.value);
                                  if (editedProfile.active_base_id === newBases[idx].base_id) {
                                    setEditedProfile({
                                      ...editedProfile,
                                      constraints: {
                                        ...editedProfile.constraints,
                                        harvest_window_days: newBases[idx].estimated_harvest_window_days ?? editedProfile.constraints.harvest_window_days,
                                      },
                                      bases: newBases,
                                    });
                                    return;
                                  }
                                  setEditedProfile({ ...editedProfile, bases: newBases });
                                }}
                                className="bg-white/10 border-white/20 text-white text-sm"
                              />
                            </div>
                            <div className="space-y-1">
                              <Label className="text-white/60 text-xs">预计距采收天数（系统估算）</Label>
                              <Input
                                value={base.estimated_harvest_window_days === null ? '未设置' : `${base.estimated_harvest_window_days} 天`}
                                readOnly
                                className="bg-white/5 border-white/10 text-white/80 text-sm"
                              />
                            </div>
                          <div className="space-y-2 sm:col-span-2">
                            <Label className="text-[#c8f7c5] font-medium text-xs">农业风险标签</Label>
                            <div className="flex flex-wrap gap-2 mb-2">
                              {(base.risk_items && base.risk_items.length > 0
                                ? base.risk_items.map((item) => ({ code: item.code, label: item.label }))
                                : (base.risk_tags || []).map((code) => ({ code, label: RISK_LABEL_MAP[code] || code }))
                              ).map((tag) => (
                                <span key={tag.code} className="bg-[#c8f7c5] text-black px-4 py-1.5 rounded-full text-sm font-medium">
                                  {tag.label}
                                </span>
                              ))}
                              {(!(base.risk_tags && base.risk_tags.length) && !(base.risk_items && base.risk_items.length)) && (
                                <span className="text-white/50 text-xs">暂无风险标签</span>
                              )}
                            </div>
                            <div className="space-y-1 bg-white/5 p-3 rounded-lg">
                              {(base.risk_items && base.risk_items.length > 0
                                ? base.risk_items.map((item) => item.reason)
                                : (base.risk_reasons || [])
                              ).slice(0, 4).map((reason, reasonIdx) => (
                                <p key={`${base.base_id}-risk-${reasonIdx}`} className="text-xs text-white/70">• {reason}</p>
                              ))}
                            </div>
                          </div>

                          <div className="space-y-1 sm:col-span-2 mt-4">
                            <Label className="text-white/60 text-xs">环境描述</Label>
                            <Textarea
                              value={base.environment}
                              readOnly
                              className="bg-white/10 border-white/20 text-white text-sm min-h-[72px] resize-y"
                            />
                          </div>
                        </div>
                      </div>
                    ))}

                    {editedProfile.bases.length === 0 && (
                      <div className="text-center py-6 text-white/40">
                        <MapPin className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">暂无基地信息</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-16 text-white/40">
                <Sprout className="w-16 h-16 mx-auto mb-4 opacity-50" />
                <p>{canManageAllProfiles ? '从左侧列表选择档案查看详情' : '未找到可编辑档案'}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Add Profile Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white max-w-md max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新增档案</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>显示名称 <span className="text-red-400">*</span></Label>
              <Input
                placeholder="请输入档案名称"
                value={newProfileName}
                onChange={(e) => setNewProfileName(e.target.value)}
                className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
              />
            </div>
            <div className="space-y-2">
              <Label>档案展示类型</Label>
              <Select value={newProfileRoleType} onValueChange={(v) => setNewProfileRoleType(v as FarmerProfile['role_type'])}>
                <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                <SelectContent className="bg-[#111] text-white border-white/20">
                  <SelectItem value="FARMER">农户</SelectItem>
                  <SelectItem value="EXPERT">专家</SelectItem>
                  <SelectItem value="ADMIN">管理员</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {canManageAllProfiles && (
              <div className="space-y-2">
                <Label>绑定账号ID</Label>
                <Input
                  placeholder="可留空（仅保存档案，不同步账号）"
                  value={newProfileOwnerUserId}
                  onChange={(e) => setNewProfileOwnerUserId(e.target.value)}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
            )}
            {canManageAllProfiles && (
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={newProfileSetAsDefault}
                  onCheckedChange={(v) => setNewProfileSetAsDefault(Boolean(v))}
                  className="border-white/30 data-[state=checked]:bg-[#c8f7c5] data-[state=checked]:text-black"
                />
                <Label className="text-white/80">绑定该账号为主诊断档案</Label>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowAddDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={createProfile}
              disabled={!newProfileName.trim()}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              确认创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Base Dialog */}
      <Dialog open={showAddBaseDialog} onOpenChange={setShowAddBaseDialog}>
        <DialogContent className="bg-[#1a3329] border-[#c8f7c5]/30 text-white max-w-md max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新增基地</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>基地ID</Label>
              <Input
                placeholder="例如：B0002"
                value={newBaseId}
                onChange={(e) => setNewBaseId(e.target.value)}
                className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowAddBaseDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={addBase}
              disabled={!newBaseId.trim()}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              确定
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
