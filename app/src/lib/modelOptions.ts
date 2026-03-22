export interface ModelOption {
  value: string;
  label: string;
}

const MODEL_OPTIONS: ModelOption[] = [
  { value: 'tf_default', label: '默认轻量上线模型（tf）' },
  { value: 'tf_paper_opt', label: '高精度备选模型（tf）' },
  { value: 'torch_debug', label: 'Torch对比模型（torch）' },
];

const MODEL_LABELS = new Map(MODEL_OPTIONS.map((item) => [item.value, item.label]));

export function resolveModelOptions(): ModelOption[] {
  return MODEL_OPTIONS.filter((item) => item.value !== 'torch_debug');
}

export function getModelLabel(value: string | null | undefined): string {
  const key = String(value ?? '').trim();
  if (!key) return '未记录模型';
  return MODEL_LABELS.get(key) ?? key;
}
