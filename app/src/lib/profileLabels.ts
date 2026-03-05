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


export const BRANCH_LABEL_MAP = {
  FAMILY: '家庭规模（小）',
  MID: '中等规模',
  ENTERPRISE: '企业级（大）',
} as const;

export const formatSelectedBranch = (value?: string | null): string => {
  if (!value) return '—';
  return BRANCH_LABEL_MAP[value as keyof typeof BRANCH_LABEL_MAP] || '—';
};
