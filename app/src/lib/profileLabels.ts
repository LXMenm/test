export const FARM_SCALE_LABELS = {
  BALCONY: '家庭阳台',
  SMALL: '小规模',
  MEDIUM: '中等规模',
  LARGE: '大规模',
  GREENHOUSE_LARGE: '大型温室/大棚',
} as const;

export const PESTICIDE_ACCESS_LEVEL_LABELS = {
  NONE: '无法购买/不使用专业农药',
  LIMITED: '有限（少量常规药剂）',
  FULL: '充足（可购买常规/专业药剂）',
} as const;

export const CULTIVATION_MODE_LABELS = {
  SOIL: '土培',
  HYDROPONIC: '水培',
  SUBSTRATE: '基质栽培',
} as const;

export const EXPERIENCE_LEVEL_LABELS = {
  NOVICE: '新手',
  INTERMEDIATE: '有经验',
  EXPERT: '专业/专家',
} as const;

export const RISK_PREFERENCE_LABELS = {
  CONSERVATIVE: '注重安全',
  BALANCED: '均衡',
  AGGRESSIVE: '注重效率',
} as const;

export const EQUIPMENT_LABELS = {
  HAND_SPRAYER: '手持喷壶/喷雾器',
  BACKPACK_SPRAYER: '背负式喷雾器',
  MIST_BLOWER: '弥雾机/风送式喷雾',
  DRONE: '无人机喷洒',
} as const;

export const getFarmScaleLabel = (value?: string | null): string => {
  if (!value) return '未设置';
  return FARM_SCALE_LABELS[value as keyof typeof FARM_SCALE_LABELS] || value;
};

export const getPesticideAccessLevelLabel = (value?: string | null): string => {
  if (!value) return '未设置';
  return PESTICIDE_ACCESS_LEVEL_LABELS[value as keyof typeof PESTICIDE_ACCESS_LEVEL_LABELS] || value;
};

export const getCultivationModeLabel = (value?: string | null): string => {
  if (!value) return '未设置';
  return CULTIVATION_MODE_LABELS[value as keyof typeof CULTIVATION_MODE_LABELS] || value;
};

export const getExperienceLevelLabel = (value?: string | null): string => {
  if (!value) return '未设置';
  return EXPERIENCE_LEVEL_LABELS[value as keyof typeof EXPERIENCE_LEVEL_LABELS] || value;
};

export const getRiskPreferenceLabel = (value?: string | null): string => {
  if (!value) return '未设置';
  return RISK_PREFERENCE_LABELS[value as keyof typeof RISK_PREFERENCE_LABELS] || value;
};

export const getEquipmentLabel = (value?: string | null): string => {
  if (!value) return '未设置';
  return EQUIPMENT_LABELS[value as keyof typeof EQUIPMENT_LABELS] || value;
};


export type SelectedBranch = 'FAMILY' | 'MID' | 'ENTERPRISE';

export const SELECTED_BRANCH_LABELS: Record<SelectedBranch, string> = {
  FAMILY: '家庭规模（小）',
  MID: '中等规模',
  ENTERPRISE: '企业级（大）',
};

export const isSelectedBranch = (v: unknown): v is SelectedBranch =>
  v === 'FAMILY' || v === 'MID' || v === 'ENTERPRISE';

export function getSelectedBranchLabel(value?: string | null): string {
  if (!value || !isSelectedBranch(value)) return '—';
  return SELECTED_BRANCH_LABELS[value];
}

// 兼容已有调用
export const formatSelectedBranch = getSelectedBranchLabel;

export const TOMATO_GROWTH_STAGE_LABELS = {
  SEEDLING: '育苗期',
  VEGETATIVE: '营养生长期',
  FLOWERING: '开花期',
  FRUIT_SET: '坐果期',
  FRUIT_EXPANSION: '膨果期',
  RIPENING: '转色成熟期',
  HARVEST: '采收期',
} as const;

const TOMATO_GROWTH_STAGE_ALIASES: Record<string, keyof typeof TOMATO_GROWTH_STAGE_LABELS> = {
  育苗: 'SEEDLING',
  育苗期: 'SEEDLING',
  苗期: 'SEEDLING',
  seedling: 'SEEDLING',
  营养生长期: 'VEGETATIVE',
  营养期: 'VEGETATIVE',
  生长期: 'VEGETATIVE',
  vegetative: 'VEGETATIVE',
  开花: 'FLOWERING',
  开花期: 'FLOWERING',
  flowering: 'FLOWERING',
  坐果: 'FRUIT_SET',
  坐果期: 'FRUIT_SET',
  fruit_set: 'FRUIT_SET',
  膨果: 'FRUIT_EXPANSION',
  膨果期: 'FRUIT_EXPANSION',
  fruit_expansion: 'FRUIT_EXPANSION',
  转色: 'RIPENING',
  成熟: 'RIPENING',
  转色成熟期: 'RIPENING',
  ripening: 'RIPENING',
  采收: 'HARVEST',
  采收期: 'HARVEST',
  harvest: 'HARVEST',
};

export const TOMATO_GROWTH_STAGE_OPTIONS = Object.entries(TOMATO_GROWTH_STAGE_LABELS).map(([value, label]) => ({ value, label }));

export const normalizeGrowthStage = (value?: string | null): keyof typeof TOMATO_GROWTH_STAGE_LABELS | '' => {
  if (!value) return '';
  const raw = value.trim();
  if (!raw) return '';
  const upper = raw.toUpperCase() as keyof typeof TOMATO_GROWTH_STAGE_LABELS;
  if (upper in TOMATO_GROWTH_STAGE_LABELS) return upper;
  return TOMATO_GROWTH_STAGE_ALIASES[raw] || TOMATO_GROWTH_STAGE_ALIASES[raw.toLowerCase()] || '';
};

export const getGrowthStageLabel = (value?: string | null): string => {
  const normalized = normalizeGrowthStage(value);
  if (!normalized) return '未设置';
  return TOMATO_GROWTH_STAGE_LABELS[normalized];
};

