import { useEffect, useMemo, useRef, useState } from 'react';
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
import { loadAuthUser, type UserRole, withAuthHeaders } from '@/auth';
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
  city?: string;
  district?: string;
  latitude: number | null;
  longitude: number | null;
  facility_type: string;
  growth_stage: string;
  sowing_date: string;
  notes: string;
  weather_snapshot: string;
  relative_humidity_2m: number | null;
  precipitation: number | null;
  rain_risk: number | null;
  weather_temperature_2m: number | null;
  weather_wind_speed_10m: number | null;
  last_weather_refresh_at: string;
  risk_tags: string[];
  risk_items: Array<{ code?: string; label?: string; level?: string; reason?: string }>;
  risk_updated_at: string;
}

interface FarmerProfile {
  farmer_id: string;
  name: string;
  display_name: string;
  owner_user_id: string;
  role_type?: string;
  account_role?: string;
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
const toSafeStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return value.map((item) => toSafeString(item).trim()).filter(Boolean);
};
const toSafeRiskItems = (value: unknown): Array<{ code?: string; label?: string; level?: string; reason?: string }> => {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (item && typeof item === 'object' ? item as Record<string, unknown> : null))
    .filter(Boolean)
    .map((item) => ({
      code: toSafeString((item as Record<string, unknown>).code),
      label: toSafeString((item as Record<string, unknown>).label),
      level: toSafeString((item as Record<string, unknown>).level),
      reason: toSafeString((item as Record<string, unknown>).reason),
    }))
    .filter((item) => item.code || item.label || item.reason);
};

const RISK_TAG_LABELS: Record<string, string> = {
  HIGH_HUMIDITY: '高湿风险',
  RAIN_RISK: '降雨风险',
  POOR_VENTILATION: '通风不足',
  GREENHOUSE_PRESSURE: '温室环境压力',
  NEAR_HARVEST: '临近采收',
  SEEDLING_VULNERABLE: '苗期脆弱',
  FLOWERING_FRUITING_SENSITIVE: '开花/结果期敏感',
  CONTEXT_CONFLICT: '上下文冲突',
  MISSING_CONTEXT: '关键信息缺失',
};

const getRiskTagLabel = (code: string): string => {
  const normalized = code.trim().toUpperCase();
  return RISK_TAG_LABELS[normalized] || code;
};

const getRiskItemLabel = (item: { code?: string; label?: string }): string => {
  const directLabel = toSafeString(item.label).trim();
  if (directLabel) return directLabel;
  const code = toSafeString(item.code).trim();
  if (!code) return '风险项';
  return getRiskTagLabel(code);
};

const getRiskLevelClass = (level: string | undefined): string => {
  const normalized = toSafeString(level).trim().toLowerCase();
  if (normalized === 'high') return 'border-red-400/60 bg-red-500/10 text-red-200';
  if (normalized === 'warning') return 'border-orange-300/60 bg-orange-500/10 text-orange-100';
  if (normalized === 'medium') return 'border-amber-300/60 bg-amber-500/10 text-amber-100';
  if (normalized === 'low') return 'border-emerald-300/60 bg-emerald-500/10 text-emerald-100';
  return 'border-white/20 bg-white/5 text-white/70';
};

const getRiskLevelLabel = (level: string | undefined): string => {
  const normalized = toSafeString(level).trim().toLowerCase();
  if (normalized === 'high') return '高';
  if (normalized === 'warning') return '预警';
  if (normalized === 'medium') return '中';
  if (normalized === 'low') return '低';
  return normalized || '未分级';
};

const formatRiskUpdatedAt = (value: string): string => {
  const text = toSafeString(value).trim();
  if (!text) return '风险尚未生成';
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  const pad = (num: number) => String(num).padStart(2, '0');
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
};

const isMissingContextRisk = (code: string | undefined): boolean => toSafeString(code).trim().toUpperCase() === 'MISSING_CONTEXT';

const toSafeNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const TOMATO_TOTAL_GROW_DAYS = 120;

const estimateHarvestWindowDaysFromSowingDate = (sowingDate: string): number | null => {
  const normalized = toSafeString(sowingDate).trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return null;
  const sowDate = new Date(`${normalized}T00:00:00Z`);
  if (Number.isNaN(sowDate.getTime())) return null;
  const utcNow = new Date();
  const todayUtc = Date.UTC(utcNow.getUTCFullYear(), utcNow.getUTCMonth(), utcNow.getUTCDate());
  let passedDays = Math.floor((todayUtc - sowDate.getTime()) / (24 * 60 * 60 * 1000));
  if (passedDays < 0) passedDays = 0;
  return Math.max(TOMATO_TOTAL_GROW_DAYS - passedDays, 0);
};



const getProfileRoleLabel = (profile: Pick<FarmerProfile, 'account_role' | 'role_type'>): string => {
  const normalized = toSafeString(profile.account_role || profile.role_type).trim().toUpperCase();
  if (normalized === 'ADMIN') return '管理员';
  if (normalized === 'EXPERT') return '专家';
  if (normalized === 'USER' || normalized === 'FARMER') return '农户';
  return '';
};

const normalizeBase = (baseId: string, base: unknown): FarmerBase => {
  const baseObj = base && typeof base === 'object' ? (base as Record<string, unknown>) : {};
  return {
    base_id: toSafeString(baseObj.base_id, baseId),
    name: toSafeString(baseObj.name),
    location: toSafeString(baseObj.location),
    province: toSafeString(baseObj.province),
    city: toSafeString(baseObj.city),
    district: toSafeString(baseObj.district),
    latitude: toSafeNumber(baseObj.latitude ?? baseObj.lat),
    longitude: toSafeNumber(baseObj.longitude ?? baseObj.lon),
    facility_type: toSafeString(baseObj.facility_type ?? baseObj.facility),
    growth_stage: normalizeGrowthStage(toSafeString(baseObj.growth_stage)),
    sowing_date: toSafeString(baseObj.sowing_date),
    notes: toSafeString(baseObj.notes),
    weather_snapshot: toSafeString(baseObj.weather_snapshot),
    relative_humidity_2m: toSafeNumber(baseObj.relative_humidity_2m),
    precipitation: toSafeNumber(baseObj.precipitation),
    rain_risk: toSafeNumber(baseObj.rain_risk),
    weather_temperature_2m: toSafeNumber(baseObj.weather_temperature_2m ?? baseObj.temperature_2m),
    weather_wind_speed_10m: toSafeNumber(baseObj.weather_wind_speed_10m ?? baseObj.wind_speed_10m),
    last_weather_refresh_at: toSafeString(baseObj.last_weather_refresh_at ?? baseObj.weather_refreshed_at),
    risk_tags: toSafeStringArray(baseObj.risk_tags),
    risk_items: toSafeRiskItems(baseObj.risk_items),
    risk_updated_at: toSafeString(baseObj.risk_updated_at),
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
    role_type: toSafeString(rawObj.role_type),
    account_role: toSafeString(rawObj.account_role),
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

const getMaxBaseIdNumber = (bases: FarmerBase[]): number => {
  const baseIdPattern = /^B(\d{4})$/i;
  let maxNo = 0;
  for (const base of bases) {
    const matched = toSafeString(base.base_id).toUpperCase().match(baseIdPattern);
    if (!matched) continue;
    const parsed = Number(matched[1]);
    if (Number.isFinite(parsed)) {
      maxNo = Math.max(maxNo, parsed);
    }
  }
  return maxNo;
};

const generateNextBaseId = (bases: FarmerBase[], startNo: number): string => {
  const usedIds = new Set(bases.map((base) => toSafeString(base.base_id).toUpperCase()).filter(Boolean));
  let candidate = Math.max(1, startNo);
  while (usedIds.has(`B${String(candidate).padStart(4, '0')}`)) {
    candidate += 1;
  }
  return `B${String(candidate).padStart(4, '0')}`;
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
  const [baseActionLoading, setBaseActionLoading] = useState<Record<string, boolean>>({});
  const nextBaseSequenceRef = useRef(1);

  const sortedProfiles = useMemo(() => {
    if (!canManageAllProfiles || !authUser?.userId) return profiles;
    return [...profiles].sort((a, b) => {
      const aMine = a.owner_user_id === authUser.userId ? 0 : 1;
      const bMine = b.owner_user_id === authUser.userId ? 0 : 1;
      if (aMine !== bMine) return aMine - bMine;
      return a.farmer_id.localeCompare(b.farmer_id);
    });
  }, [authUser?.userId, canManageAllProfiles, profiles]);

  const activeBase = useMemo(() => {
    if (!editedProfile) return null;
    const activeBaseId = toSafeString(editedProfile.active_base_id).trim();
    if (!activeBaseId) return null;
    return editedProfile.bases.find((base) => toSafeString(base.base_id).trim() === activeBaseId) || null;
  }, [editedProfile]);

  const estimatedHarvestWindowDays = useMemo(() => {
    if (!activeBase) return null;
    return estimateHarvestWindowDaysFromSowingDate(activeBase.sowing_date);
  }, [activeBase]);

  const resolvedHarvestWindowDays = estimatedHarvestWindowDays ?? (editedProfile?.constraints.harvest_window_days ?? 0);
  const harvestWindowSource = estimatedHarvestWindowDays != null ? 'sowing_date' : 'fallback';

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
      const resp = await fetch('/api/profiles', withAuthHeaders(undefined, authUser));
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
      const resp = await fetch(`/api/profiles/${encodeURIComponent(farmerId)}`, withAuthHeaders(undefined, authUser));
      const data = await parseJsonOrThrow(resp);
      const normalized = normalizeProfile(data);
      setSelectedProfile(normalized);
      setEditedProfile(JSON.parse(JSON.stringify(normalized)));
      setBaseActionLoading({});
      nextBaseSequenceRef.current = getMaxBaseIdNumber(normalized.bases) + 1;
      return normalized;
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '加载档案详情失败');
      return null;
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

    const normalizedBaseIds = editedProfile.bases.map((base) => toSafeString(base.base_id).trim());
    const invalidBaseIdIndex = normalizedBaseIds.findIndex((baseId) => !baseId);
    if (invalidBaseIdIndex >= 0) {
      setErrorMessage(`第 ${invalidBaseIdIndex + 1} 个基地缺少基地ID，请修改后再保存`);
      return;
    }
    const seenBaseId = new Set<string>();
    let duplicatedBaseId = '';
    for (const baseId of normalizedBaseIds) {
      const normalized = baseId.toUpperCase();
      if (seenBaseId.has(normalized)) {
        duplicatedBaseId = normalized;
        break;
      }
      seenBaseId.add(normalized);
    }
    if (duplicatedBaseId) {
      setErrorMessage(`基地ID重复：${duplicatedBaseId}，请修改后再保存`);
      return;
    }

    const basesMap = Object.fromEntries(
      editedProfile.bases.map((base, idx) => [normalizedBaseIds[idx], {
        base_id: normalizedBaseIds[idx],
        name: base.name,
        location: base.location,
        province: base.province,
        city: base.city,
        district: base.district,
        latitude: base.latitude,
        longitude: base.longitude,
        facility: base.facility_type,
        growth_stage: normalizeGrowthStage(base.growth_stage),
        sowing_date: base.sowing_date || null,
        notes: base.notes,
        weather_snapshot: base.weather_snapshot || null,
        relative_humidity_2m: base.relative_humidity_2m,
        precipitation: base.precipitation,
        rain_risk: base.rain_risk,
        weather_temperature_2m: base.weather_temperature_2m,
        weather_wind_speed_10m: base.weather_wind_speed_10m,
        last_weather_refresh_at: base.last_weather_refresh_at || null,
      }]),
    );

    try {
      const resp = await fetch(`/api/profiles/${encodeURIComponent(editedProfile.farmer_id)}`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...editedProfile,
          display_name: editedProfile.display_name || editedProfile.name || editedProfile.farmer_id,
          bases: basesMap,
        }),
      }, authUser));
      await parseJsonOrThrow(resp);
      const refreshed = await fetchProfileDetail(editedProfile.farmer_id);
      setInfoMessage(refreshed ? '档案业务资料已保存，并已同步最新风险标签。' : '档案业务资料已保存。');
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
    const nextId = generateNextBaseId(editedProfile.bases, nextBaseSequenceRef.current);
    const matched = nextId.match(/^B(\d{4})$/);
    nextBaseSequenceRef.current = matched ? Number(matched[1]) + 1 : nextBaseSequenceRef.current + 1;
    setBaseActionLoading({});
    setEditedProfile({
      ...editedProfile,
      bases: [...editedProfile.bases, {
        base_id: nextId,
        name: '',
        location: '',
        province: '',
        city: '',
        district: '',
        latitude: null,
        longitude: null,
        facility_type: '',
        growth_stage: '',
        sowing_date: '',
        notes: '',
        weather_snapshot: '',
        relative_humidity_2m: null,
        precipitation: null,
        rain_risk: null,
        weather_temperature_2m: null,
        weather_wind_speed_10m: null,
        last_weather_refresh_at: '',
        risk_tags: [],
        risk_items: [],
        risk_updated_at: '',
      }],
    });
  };

  const removeBase = (idx: number) => {
    if (!editedProfile) return;
    setBaseActionLoading({});
    setEditedProfile({ ...editedProfile, bases: editedProfile.bases.filter((_, i) => i !== idx) });
  };

  const updateBase = (idx: number, updater: (base: FarmerBase) => FarmerBase) => {
    setEditedProfile((prev) => {
      if (!prev) return prev;
      const next = [...prev.bases];
      if (!next[idx]) return prev;
      next[idx] = updater(next[idx]);
      return { ...prev, bases: next };
    });
  };

  const setBaseLoading = (operationKey: string, loading: boolean) => {
    setBaseActionLoading((prev) => ({ ...prev, [operationKey]: loading }));
  };

  const reverseGeocodeBaseAddress = async (idx: number, latitude: number, longitude: number) => {
    const resp = await fetch(`/api/location/reverse?lat=${encodeURIComponent(latitude)}&lon=${encodeURIComponent(longitude)}`, withAuthHeaders(undefined, authUser));
    const payload = await parseJsonOrThrow(resp);
    updateBase(idx, (current) => ({
      ...current,
      location: toSafeString(payload?.location, current.location),
      province: toSafeString(payload?.province, current.province),
      city: toSafeString(payload?.city, current.city),
      district: toSafeString(payload?.district, current.district),
    }));
  };

  const fetchBaseGeolocation = async (idx: number) => {
    if (!editedProfile) return;
    const base = editedProfile.bases[idx];
    if (!base) return;
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setErrorMessage('当前浏览器不支持获取地理位置');
      return;
    }
    setErrorMessage('');
    setInfoMessage('');
    const geolocationKey = `${idx}:geolocation`;
    setBaseLoading(geolocationKey, true);
    try {
      const position = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 10000,
        });
      });
      const latitude = Number(position.coords.latitude);
      const longitude = Number(position.coords.longitude);
      updateBase(idx, (current) => ({
        ...current,
        latitude,
        longitude,
      }));
      try {
        await reverseGeocodeBaseAddress(idx, latitude, longitude);
        setInfoMessage(`基地 ${base.base_id} 已获取经纬度并自动回填地址（未自动保存）`);
      } catch {
        setInfoMessage(`基地 ${base.base_id} 经纬度已更新，但地址回填失败`);
      }
    } catch (error) {
      const geolocationError = error as GeolocationPositionError;
      if (geolocationError?.code === 1) {
        setErrorMessage('已拒绝地理位置权限，请允许后重试');
      } else {
        setErrorMessage('获取地理位置失败，请稍后重试');
      }
    } finally {
      setBaseLoading(geolocationKey, false);
    }
  };

  const refreshBaseWeather = async (idx: number) => {
    if (!editedProfile) return;
    const base = editedProfile.bases[idx];
    if (!base) return;
    const latitude = toSafeNumber(base.latitude);
    const longitude = toSafeNumber(base.longitude);
    if (latitude == null || longitude == null) {
      setErrorMessage(`基地 ${base.base_id} 缺少经纬度，无法刷新天气`);
      return;
    }
    updateBase(idx, (current) => ({ ...current, latitude, longitude }));
    setErrorMessage('');
    setInfoMessage('');
    const weatherKey = `${idx}:weather`;
    setBaseLoading(weatherKey, true);
    try {
      const resp = await fetch(`/api/profiles/${encodeURIComponent(editedProfile.farmer_id)}/bases/${encodeURIComponent(base.base_id)}/weather/refresh`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          latitude,
          longitude,
        }),
      }, authUser));
      const payload = await parseJsonOrThrow(resp);
      updateBase(idx, (current) => ({
        ...current,
        weather_snapshot: toSafeString(payload?.weather_snapshot, current.weather_snapshot),
        relative_humidity_2m: toSafeNumber(payload?.relative_humidity_2m),
        precipitation: toSafeNumber(payload?.precipitation),
        rain_risk: toSafeNumber(payload?.rain_risk),
        weather_temperature_2m: toSafeNumber(payload?.weather_temperature_2m ?? payload?.temperature_2m),
        weather_wind_speed_10m: toSafeNumber(payload?.weather_wind_speed_10m ?? payload?.wind_speed_10m),
        last_weather_refresh_at: toSafeString(payload?.last_weather_refresh_at, current.last_weather_refresh_at),
      }));
      const refreshed = await fetchProfileDetail(editedProfile.farmer_id);
      if (refreshed) {
        setInfoMessage(`基地 ${base.base_id} 天气已刷新，并已同步最新风险标签。`);
      } else {
        setInfoMessage(`基地 ${base.base_id} 天气已刷新（风险标签同步失败，请手动刷新档案）`);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '刷新天气失败');
    } finally {
      setBaseLoading(weatherKey, false);
    }
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
                const roleLabel = getProfileRoleLabel(profile);
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
                      {roleLabel ? <Badge variant="outline" className="border-white/20 text-white/80 text-[10px]">{roleLabel}</Badge> : null}
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
                        <SelectContent>{editedProfile.bases.map((base, idx) => <SelectItem key={`${base.base_id}-${idx}`} value={base.base_id}>{base.name || base.base_id}</SelectItem>)}</SelectContent>
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
                    <div className="space-y-2">
                      <Label className="text-white/60">距离采收期（天）</Label>
                      <Input value={`${resolvedHarvestWindowDays}`} readOnly className="bg-white/5 border-white/10 text-white/80" />
                      <p className="text-xs text-white/50">
                        {harvestWindowSource === 'sowing_date' ? '根据播种日期自动估算' : '当前为档案保存值 / 回退值'}
                      </p>
                    </div>
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
                        <div className="space-y-4">
                          <div className="grid sm:grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">基地名称</Label>
                              <Input
                                value={base.name}
                                onChange={(e) => {
                                  updateBase(idx, (current) => ({ ...current, name: e.target.value }));
                                }}
                                className="bg-white/10 border-white/20 text-white"
                                placeholder="请输入基地名称"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">设施类型</Label>
                              <Input
                                value={base.facility_type}
                                onChange={(e) => {
                                  updateBase(idx, (current) => ({ ...current, facility_type: e.target.value }));
                                }}
                                className="bg-white/10 border-white/20 text-white"
                                placeholder="例如：露地 / 温室 / 大棚"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">生长阶段</Label>
                              <Select
                                value={base.growth_stage || '__EMPTY__'}
                                onValueChange={(value) => {
                                  updateBase(idx, (current) => ({
                                    ...current,
                                    growth_stage: value === '__EMPTY__' ? '' : value,
                                  }));
                                }}
                              >
                                <SelectTrigger className="bg-white/10 border-white/20 text-white">
                                  <SelectValue placeholder="请选择生长阶段" />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="__EMPTY__">未设置</SelectItem>
                                  {TOMATO_GROWTH_STAGE_OPTIONS.map((stage) => (
                                    <SelectItem key={stage.value} value={stage.value}>
                                      {stage.label}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">播种日期</Label>
                              <Input
                                type="date"
                                value={base.sowing_date}
                                onChange={(e) => {
                                  updateBase(idx, (current) => ({ ...current, sowing_date: e.target.value }));
                                }}
                                className="bg-white/10 border-white/20 text-white"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">详细地址</Label>
                              <Input 
                                value={base.location} 
                                onChange={(e) => { 
                                  const next = [...editedProfile.bases]; 
                                  next[idx].location = e.target.value; 
                                  setEditedProfile({ ...editedProfile, bases: next }); 
                                }} 
                                className="bg-white/10 border-white/20 text-white"
                                placeholder="请输入详细地址"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">省份</Label>
                              <Input 
                                value={base.province} 
                                onChange={(e) => { 
                                  const next = [...editedProfile.bases]; 
                                  next[idx].province = e.target.value; 
                                  setEditedProfile({ ...editedProfile, bases: next }); 
                                }} 
                                className="bg-white/10 border-white/20 text-white"
                                placeholder="请输入省份"
                              />
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-3">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => { void fetchBaseGeolocation(idx); }}
                              disabled={baseActionLoading[`${idx}:geolocation`]}
                              className="border-[#c8f7c5]/40 text-[#c8f7c5] hover:bg-[#c8f7c5]/10 transition-all"
                            >
                              {baseActionLoading[`${idx}:geolocation`] ? <RefreshCw className="w-4 h-4 mr-1 animate-spin" /> : <MapPin className="w-4 h-4 mr-1" />}
                              获取地理位置
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => { void refreshBaseWeather(idx); }}
                              disabled={baseActionLoading[`${idx}:weather`]}
                              className="border-[#c8f7c5]/40 text-[#c8f7c5] hover:bg-[#c8f7c5]/10 transition-all"
                            >
                              {baseActionLoading[`${idx}:weather`] ? <RefreshCw className="w-4 h-4 mr-1 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1" />}
                              刷新天气
                            </Button>
                          </div>
                          {(base.weather_snapshot || base.last_weather_refresh_at) && (
                            <div className="rounded-lg bg-white/10 border border-white/10 p-4 space-y-2">
                              <p className="text-sm text-[#c8f7c5] font-medium">当前天气</p>
                              <p className="text-sm text-white/80">{base.weather_snapshot || '暂无'}</p>
                              <div className="flex flex-wrap items-center gap-4 mt-2 text-xs text-white/60">
                                <span>最近刷新：{base.last_weather_refresh_at || '未刷新'}</span>
                                {base.weather_temperature_2m && <span>温度：{base.weather_temperature_2m}℃</span>}
                                {base.relative_humidity_2m && <span>湿度：{base.relative_humidity_2m}%</span>}
                                {base.rain_risk && <span>雨风险：{base.rain_risk}</span>}
                              </div>
                            </div>
                          )}
                          <div className="rounded-lg bg-white/10 border border-white/10 p-3 space-y-2">
                            <p className="text-xs text-[#c8f7c5]">风险标签概览</p>
                            <div className="flex flex-wrap gap-2">
                              {base.risk_tags.length > 0 ? base.risk_tags.map((tag) => (
                                <Badge
                                  key={`${base.base_id}-${tag}`}
                                  variant="outline"
                                  className={cn(
                                    isMissingContextRisk(tag)
                                      ? 'border-sky-300/60 text-sky-100 bg-sky-500/10'
                                      : 'border-amber-300/50 text-amber-200',
                                  )}
                                >
                                  {getRiskTagLabel(tag)}
                                </Badge>
                              )) : <p className="text-xs text-white/60">当前未识别到明显风险标签</p>}
                            </div>
                            <p className="text-xs text-white/60">风险更新时间：{formatRiskUpdatedAt(base.risk_updated_at)}</p>
                            {base.risk_tags.some((tag) => isMissingContextRisk(tag)) ? (
                              <p className="text-xs text-sky-200">提示：存在“信息不完整”标签，当前风险判断可能受限。</p>
                            ) : null}
                          </div>
                          <div className="rounded-lg bg-white/10 border border-white/10 p-3 space-y-2">
                            <p className="text-xs text-[#c8f7c5]">风险项明细</p>
                            {base.risk_items.length > 0 ? (
                              <div className="space-y-1">
                                {base.risk_items.map((item, itemIdx) => (
                                  <div
                                    key={`${base.base_id}-risk-${itemIdx}`}
                                    className={cn(
                                      'rounded-md border p-2 text-xs space-y-1',
                                      isMissingContextRisk(item.code)
                                        ? 'border-sky-300/50 bg-sky-500/10'
                                        : 'border-white/15 bg-black/10',
                                    )}
                                  >
                                    <div className="flex items-center gap-2">
                                      <span className="text-white/90">{getRiskItemLabel(item)}</span>
                                      <Badge variant="outline" className={cn('text-[10px] px-1.5 py-0', getRiskLevelClass(item.level))}>
                                        {getRiskLevelLabel(item.level)}
                                      </Badge>
                                    </div>
                                    <p className="text-white/70">{toSafeString(item.reason) || '请关注风险变化。'}</p>
                                    {isMissingContextRisk(item.code) ? <p className="text-sky-200">该项表示档案信息不完整，需补全上下文。</p> : null}
                                  </div>
                                ))}
                              </div>
                            ) : <p className="text-xs text-white/60">暂无风险项明细</p>}
                          </div>
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
