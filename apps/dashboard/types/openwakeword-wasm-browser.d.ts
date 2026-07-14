// Ambient types for openwakeword-wasm-browser (ships as plain JS, no .d.ts).
// Mirrors the WakeWordEngine surface we use.
declare module "openwakeword-wasm-browser" {
  export interface WakeWordEngineOptions {
    keywords?: string[];
    baseAssetUrl?: string;
    ortWasmPath?: string;
    sampleRate?: number;
    detectionThreshold?: number;
    cooldownMs?: number;
    debug?: boolean;
  }
  export interface DetectPayload {
    keyword: string;
    score: number;
    at: number;
  }
  export class WakeWordEngine {
    constructor(opts?: WakeWordEngineOptions);
    on(event: string, handler: (payload: unknown) => void): void;
    off(event: string, handler: (payload: unknown) => void): void;
    load(): Promise<void>;
    start(opts?: { deviceId?: string; gain?: number }): Promise<void>;
    stop(): Promise<void>;
    setGain(value: number): void;
    setActiveKeywords(keywords: string[]): void;
    runWav(buffer: ArrayBuffer): Promise<void>;
  }
  export const MODEL_FILE_MAP: Record<string, string>;
  export default WakeWordEngine;
}
