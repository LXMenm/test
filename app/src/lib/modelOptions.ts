export interface ModelOption {
  value: string;
  label: string;
  display_name: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'tf_default',
    label: '默认高精度模型 (tf)',
    display_name: '默认高精度模型 (tf)',
  },
  {
    value: 'tf_light_v1',
    label: '轻量模型V1 (tf)',
    display_name: '轻量模型V1 (tf)',
  },
];

export function resolveModelOptions(): ModelOption[] {
  return MODEL_OPTIONS;
}
