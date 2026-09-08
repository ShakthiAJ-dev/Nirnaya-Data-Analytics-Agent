/**
 * src/hooks/useModels.ts
 * -----------------------
 * Hook that fetches live available models from GET /session/models.
 *
 * Models are only returned for providers whose API keys have been submitted
 * and validated on the BE. Until then, models is [].
 *
 * Usage:
 *   const { models, isLoading, refresh } = useModels(sessionStatus);
 *
 *   // After user saves credentials:
 *   await handleSaveCredentials(creds);
 *   await refresh();   ← re-fetches and updates the dropdown instantly
 */

import { useState, useCallback, useEffect } from 'react';
import { fetchAvailableModels } from '../services/sessionService';
import type { BackendModel } from '../services/sessionService';

export type { BackendModel };

export interface UseModelsResult {
  /** Live models from the BE. Empty until at least one key is stored. */
  models: BackendModel[];
  isLoading: boolean;
  /** Call after credentials are saved to refresh the model list immediately. */
  refresh: () => Promise<void>;
}

/**
 * @param sessionReady - pass true when the session is initialised.
 *   The hook will only call the BE once this becomes true.
 */
export function useModels(sessionReady: boolean): UseModelsResult {
  const [models, setModels] = useState<BackendModel[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const fetchModels = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await fetchAvailableModels();
      setModels(result);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Auto-fetch once session is ready
  useEffect(() => {
    if (sessionReady) {
      fetchModels();
    }
  }, [sessionReady, fetchModels]);

  return { models, isLoading, refresh: fetchModels };
}
