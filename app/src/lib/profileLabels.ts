export type SelectedBranch = 'FAMILY' | 'MID' | 'ENTERPRISE';

const FARM_SCALE_LABELS: Record<string, string> = {
  BALCONY: '阳台/庭院',
  SMALL: '小规模',
  MEDIUM: '中等规模',
  LARGE: '大规模',
  GREENHOUSE_LARGE: '大型温室',
};

const PESTICIDE_ACCESS_LABELS: Record<string, string> = {
  NONE: '无法购药',
  LIMITED: '有限购药',
  FULL: '购药充足',
};

const EQUIPMENT_LABELS: Record<string, string> = {
  HAND_SPRAYER: '手动喷雾器',
  BACKPACK_SPRAYER: '背负式喷雾器',
  MIST_BLOWER: '弥雾机',
  DRONE: '无人机',
};

const CULTIVATION_MODE_LABELS: Record<string, string> = {
  SOIL: '土培',
  HYDROPONIC: '水培',
  SUBSTRATE: '基质栽培',
};

const EXPERIENCE_LEVEL_LABELS: Record<string, string> = {
  NOVICE: '新手',
  INTERMEDIATE: '有经验',
  EXPERT: '专家',
};

const RISK_PREFERENCE_LABELS: Record<string, string> = {
  CONSERVATIVE: '保守',
  BALANCED: '平衡',
  AGGRESSIVE: '积极',
};

const SELECTED_BRANCH_LABELS: Record<SelectedBranch, string> = {
  FAMILY: '家庭级',
  MID: '中等规模',
  ENTERPRISE: '企业级',
};

const GROWTH_STAGE_ALIASES: Record<string, string> = {
  SEEDLING: 'SEEDLING',
  苗期: 'SEEDLING',
  VEGETATIVE: 'VEGETATIVE',
  营养生长期: 'VEGETATIVE',
  营养期: 'VEGETATIVE',
  FLOWERING: 'FLOWERING',
  开花期: 'FLOWERING',
  FLOWER: 'FLOWERING',
  FRUIT_SET: 'FRUIT_SET',
  坐果期: 'FRUIT_SET',
  结果期: 'FRUIT_SET',
  FRUIT_EXPANSION: 'FRUIT_EXPANSION',
  膨果期: 'FRUIT_EXPANSION',
  果实膨大期: 'FRUIT_EXPANSION',
  RIPENING: 'RIPENING',
  转色成熟期: 'RIPENING',
  成熟期: 'RIPENING',
  HARVEST: 'HARVEST',
  采收期: 'HARVEST',
};

export const TOMATO_GROWTH_STAGE_OPTIONS = [
  { value: 'SEEDLING', label: '苗期' },
  { value: 'VEGETATIVE', label: '营养生长期' },
  { value: 'FLOWERING', label: '开花期' },
  { value: 'FRUIT_SET', label: '坐果期' },
  { value: 'FRUIT_EXPANSION', label: '膨果期' },
  { value: 'RIPENING', label: '转色成熟期' },
  { value: 'HARVEST', label: '采收期' },
] as const;

const GROWTH_STAGE_LABELS: Record<string, string> = Object.fromEntries(
  TOMATO_GROWTH_STAGE_OPTIONS.map((stage) => [stage.value, stage.label]),
);

const labelOrFallback = (mapping: Record<string, string>, value: string | null | undefined, fallback = '未设置'): string => {
  const key = String(value ?? '').trim();
  if (!key) return fallback;
  return mapping[key] ?? key;
};

export const normalizeGrowthStage = (value: string | null | undefined): string => {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  return GROWTH_STAGE_ALIASES[raw] ?? GROWTH_STAGE_ALIASES[raw.toUpperCase()] ?? raw.toUpperCase();
};

export const getGrowthStageLabel = (value: string | null | undefined): string => {
  const normalized = normalizeGrowthStage(value);
  return normalized ? (GROWTH_STAGE_LABELS[normalized] ?? normalized) : '未设置';
};

export const getFarmScaleLabel = (value: string | null | undefined): string => labelOrFallback(FARM_SCALE_LABELS, value, '未设置');
export const getPesticideAccessLevelLabel = (value: string | null | undefined): string => labelOrFallback(PESTICIDE_ACCESS_LABELS, value, '未设置');
export const getEquipmentLabel = (value: string | null | undefined): string => labelOrFallback(EQUIPMENT_LABELS, value, '未知设备');
export const getCultivationModeLabel = (value: string | null | undefined): string => labelOrFallback(CULTIVATION_MODE_LABELS, value, '未设置');
export const getExperienceLevelLabel = (value: string | null | undefined): string => labelOrFallback(EXPERIENCE_LEVEL_LABELS, value, '未设置');
export const getRiskPreferenceLabel = (value: string | null | undefined): string => labelOrFallback(RISK_PREFERENCE_LABELS, value, '未设置');

export const getSelectedBranchLabel = (value: string | null | undefined): string => {
  const key = String(value ?? '').trim().toUpperCase();
  if (!key) return '未分档';
  if (key === 'HOME') return SELECTED_BRANCH_LABELS.FAMILY;
  if (key === 'PRO') return SELECTED_BRANCH_LABELS.MID;
  return SELECTED_BRANCH_LABELS[key as SelectedBranch] ?? value ?? '未分档';
};
