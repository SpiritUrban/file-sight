/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly DEV: boolean;
  readonly PROD: boolean;
  /** Set to "1" to drive the UI from the in-memory mock worker. */
  readonly VITE_MOCK_WORKER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
