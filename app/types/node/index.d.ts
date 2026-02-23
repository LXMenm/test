declare const __dirname: string;

declare module 'path' {
  export function resolve(...paths: string[]): string;
  const _default: {
    resolve: typeof resolve;
  };
  export default _default;
}

declare module 'node:path' {
  export * from 'path';
  import path from 'path';
  export default path;
}
