import { useState, useCallback, useRef } from 'react';
import type { StepEvent, FinalEvent, Artifact, WSAckFrame } from '../types';

interface StepTrackingState {
  turnId: string | null;
  steps: StepEvent[];
  artifacts: Artifact[];
  finalMarkdown: string | null;
  followUpQuestions: string[];
  isProcessing: boolean;
  error: string | null;
  startTime: number | null;
  endTime: number | null;
}

export const useStepTracking = () => {
  const [state, setState] = useState<StepTrackingState>({
    turnId: null,
    steps: [],
    artifacts: [],
    finalMarkdown: null,
    followUpQuestions: [],
    isProcessing: true,
    error: null,
    startTime: null,
    endTime: null,
  });

  const stateRef = useRef(state);
  stateRef.current = state;

  const handleAckFrame = useCallback((frame: WSAckFrame) => {
    setState((prev) => ({
      ...prev,
      turnId: frame.turn_id,
      steps: [],
      artifacts: [],
      finalMarkdown: null,
      followUpQuestions: [],
      isProcessing: true,
      error: null,
      startTime: Date.now(),
      endTime: null,
    }));
  }, []);

  const handleStepEvent = useCallback((event: StepEvent) => {
    console.log('[useStepTracking] handleStepEvent:', { prevTurnId: stateRef.current.turnId, eventTurnId: event.turn_id, steps: stateRef.current.steps.length });
    setState((prev) => {
      if (prev.turnId !== event.turn_id) {
        console.log('[useStepTracking] turnId mismatch, ignoring');
        return prev;
      }
      const existingIdx = prev.steps.findIndex((s) => s.seq === event.seq);
      const newSteps =
        existingIdx >= 0
          ? prev.steps.map((s, i) => (i === existingIdx ? event : s))
          : [...prev.steps, event];
      console.log('[useStepTracking] steps updated:', newSteps.length);
      return { ...prev, steps: newSteps };
    });
  }, []);

  const handleFinalEvent = useCallback((event: FinalEvent) => {
    setState((prev) => {
      if (prev.turnId !== event.turn_id) {
        return prev;
      }
      return {
        ...prev,
        artifacts: event.artifacts,
        finalMarkdown: event.markdown,
        followUpQuestions: event.follow_up_questions,
        isProcessing: false,
        error: null,
        endTime: Date.now(),
      };
    });
  }, []);

  const handleErrorEvent = useCallback((turnId: string, message: string) => {
    setState((prev) => {
      if (prev.turnId !== turnId) {
        return prev;
      }
      return {
        ...prev,
        isProcessing: false,
        error: message,
      };
    });
  }, []);

  const reset = useCallback(() => {
    setState({
      turnId: null,
      steps: [],
      artifacts: [],
      finalMarkdown: null,
      followUpQuestions: [],
      isProcessing: false,
      error: null,
      startTime: null,
      endTime: null,
    });
  }, []);

  return {
    ...state,
    handleAckFrame,
    handleStepEvent,
    handleFinalEvent,
    handleErrorEvent,
    reset,
  };
};
