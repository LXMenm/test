export function cn(...inputs: Array<unknown>): string {
  return inputs
    .flatMap((input) => {
      if (typeof input === 'string') return [input];
      if (Array.isArray(input)) return input.map((item) => String(item));
      if (input && typeof input === 'object') {
        return Object.entries(input as Record<string, unknown>)
          .filter(([, value]) => Boolean(value))
          .map(([key]) => key);
      }
      return [];
    })
    .filter(Boolean)
    .join(' ');
}
