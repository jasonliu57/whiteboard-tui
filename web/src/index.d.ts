export interface WhiteboardState {
  revision: string;
  generation: number;
  dirty: boolean;
  readOnly: boolean;
  cards: number;
  edges: number;
  x: string;
  y: string;
  columns: number;
  rows: number;
  name: string;
}
export type Appearance = 'light' | 'dark' | 'system';
export interface WhiteboardAppearance {
  appearance: Appearance;
  resolvedAppearance: 'light' | 'dark';
}
export interface WhiteboardOptions {
  assetBaseUrl?: string | URL;
  readOnly?: boolean;
  /** Original document retained for reset; an existing draft is restored by default. */
  document?: Uint8Array;
  name?: string;
  drafts?: boolean;
  draftKey?: string;
  restoreDraft?: boolean;
  fontFamily?: string;
  theme?: Record<string, string>;
  appearance?: Appearance;
  backLink?: { href: string; label?: string };
  onAppearanceChange?: (appearance: WhiteboardAppearance) => void;
  confirmDiscard?: () => boolean | Promise<boolean>;
  onChange?: (state: WhiteboardState) => void;
  onError?: (error: Error) => void;
}
export interface WhiteboardSnapshot {
  bytes: Uint8Array;
  name: string;
  generation: number;
  revision: string;
}
export interface Whiteboard {
  open(bytes: Uint8Array, name?: string): Promise<boolean>;
  export(): Promise<WhiteboardSnapshot>;
  newDocument(): Promise<boolean>;
  saveDraft(): Promise<void>;
  /** Restore the original and clear only this draft, without confirmation. */
  resetToOriginal(): Promise<void>;
  setReadOnly(value: boolean): Promise<void>;
  setAppearance(value: Appearance): void;
  getAppearance(): WhiteboardAppearance;
  getState(): WhiteboardState | undefined;
  dispose(): void;
}
export function mountWhiteboard(container: HTMLElement, options?: WhiteboardOptions): Promise<Whiteboard>;
