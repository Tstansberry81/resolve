"use client";

import { useSyncExternalStore } from "react";
import { engine } from "./engine";
import type { EngineState } from "./types";

const SERVER_SNAPSHOT: EngineState = engine.getSnapshot();

export function useEngine(): EngineState {
  return useSyncExternalStore(
    engine.subscribe,
    engine.getSnapshot,
    () => SERVER_SNAPSHOT,
  );
}

export { engine };
