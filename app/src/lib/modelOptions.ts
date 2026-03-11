export interface ModelOption {
  value: string;
  label: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { value: 'tf_default', label: '默认高精度模型 (tf)' },
  { value: 'tf_light_v1', label: '轻量模型V1 (tf)' },
];

export const MODEL_LABEL_MAP: Record<string, string> = Object.fromEntries(
  MODEL_OPTIONS.map((item) => [item.value, item.label]),
);

export const resolveModelOptions = (): ModelOption[] => MODEL_OPTIONS;

export const getModelLabel = (modelId?: string | null): string => {
  if (!modelId) return '未记录模型';
  return MODEL_LABEL_MAP[modelId] ?? modelId;
};
