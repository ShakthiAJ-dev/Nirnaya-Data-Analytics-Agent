import React, { useState, useEffect } from 'react';
import { ChevronDown, Loader, CheckCircle, AlertCircle, Clock } from 'lucide-react';
import type { StepEvent } from '../types';

interface StepsPanelProps {
  steps: StepEvent[];
  isLoading: boolean;
  startTime: number | null;
  endTime: number | null;
}

const getStepIcon = (name: string) => {
  const icons: Record<string, string> = {
    loading_context: '📚',
    analyzing_question: '🔍',
    running_discovery: '🔎',
    deciding: '🤔',
    dispatching_artifacts: '📤',
    artifact_progress: '⚙️',
    joining_results: '🔗',
    synthesizing: '✨',
    direct_response: '💬',
    error: '❌',
  };
  return icons[name] || '•';
};

const formatDuration = (ms: number): string => {
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 1) return '<1s';
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
};

export const StepsPanel: React.FC<StepsPanelProps> = ({ steps, isLoading, startTime, endTime }) => {
  const [expanded, setExpanded] = useState(false);
  const [showAllSteps, setShowAllSteps] = useState(false);
  const [elapsedTime, setElapsedTime] = useState<string | null>(null);

  useEffect(() => {
    if (!startTime) return;

    const update = () => {
      const end = endTime || Date.now();
      const duration = end - startTime;
      setElapsedTime(formatDuration(duration));
    };

    update();
    if (isLoading) {
      const interval = setInterval(update, 100);
      return () => clearInterval(interval);
    }
  }, [startTime, endTime, isLoading]);

  console.log('[StepsPanel] render:', { stepsCount: steps.length, isLoading });
  if (steps.length === 0) {
    console.log('[StepsPanel] no steps, returning null');
    return null;
  }

  const currentStep = steps[steps.length - 1];

  return (
    <div className="steps-panel">
      <div className="steps-header">
        <h3 className="steps-title">
          {getStepIcon(currentStep.name)} {isLoading ? 'Processing' : 'Completed'}
        </h3>
        <div className="steps-controls">
          {!isLoading && elapsedTime && (
            <button
              onClick={() => setShowAllSteps(!showAllSteps)}
              className="timestamp-btn"
              title="View all steps"
            >
              <Clock size={14} />
              <span>{elapsedTime}</span>
            </button>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="steps-toggle"
          >
            <ChevronDown size={16} style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }} />
          </button>
        </div>
      </div>

      <div className="steps-current">
        <div className="step-status">
          {isLoading ? (
            <Loader size={16} className="spin" />
          ) : currentStep.status === 'error' ? (
            <AlertCircle size={16} className="error" />
          ) : (
            <CheckCircle size={16} className="success" />
          )}
        </div>
        <div className="step-info">
          <div className="step-title">{currentStep.title}</div>
          <div className="step-detail">{currentStep.detail}</div>
          {currentStep.reasoning && (
            <div className="step-reasoning">{currentStep.reasoning}</div>
          )}
        </div>
      </div>

      {(expanded || showAllSteps) && steps.length > 0 && (
        <div className="steps-history">
          {steps.map((step, idx) => (
            <StepHistoryItem key={idx} step={step} />
          ))}
        </div>
      )}

      <style>{`
        .steps-panel {
          border: 1px solid var(--border-color);
          border-radius: 8px;
          padding: 12px;
          margin-bottom: 16px;
          background: var(--bg-secondary);
        }
        .steps-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }
        .steps-title {
          margin: 0;
          font-size: 14px;
          font-weight: 600;
          flex: 1;
        }
        .steps-controls {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .timestamp-btn {
          background: none;
          border: 1px solid var(--border-color);
          cursor: pointer;
          padding: 4px 8px;
          border-radius: 4px;
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 12px;
          color: var(--text-secondary);
          transition: all 0.2s;
        }
        .timestamp-btn:hover {
          border-color: var(--text-primary);
          color: var(--text-primary);
        }
        .steps-toggle {
          background: none;
          border: none;
          cursor: pointer;
          padding: 0;
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          transition: color 0.2s;
        }
        .steps-toggle:hover {
          color: var(--text-primary);
        }
        .steps-current {
          display: flex;
          gap: 12px;
          align-items: flex-start;
        }
        .step-status {
          flex-shrink: 0;
          margin-top: 2px;
        }
        .step-status .spin {
          animation: spin 1s linear infinite;
        }
        .step-status .success {
          color: #10b981;
        }
        .step-status .error {
          color: #ef4444;
        }
        .step-info {
          flex: 1;
        }
        .step-title {
          font-size: 14px;
          font-weight: 600;
          margin-bottom: 4px;
        }
        .step-detail {
          font-size: 13px;
          color: var(--text-secondary);
          margin-bottom: 4px;
        }
        .step-reasoning {
          font-size: 12px;
          color: var(--text-secondary);
          padding: 8px;
          background: rgba(0, 0, 0, 0.1);
          border-radius: 4px;
          margin-top: 4px;
        }
        .steps-history {
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid var(--border-color);
          max-height: 400px;
          overflow-y: auto;
        }
        .step-item {
          display: flex;
          gap: 8px;
          margin-bottom: 12px;
          font-size: 12px;
          padding: 8px;
          background: rgba(0, 0, 0, 0.05);
          border-radius: 4px;
          cursor: pointer;
          transition: background 0.2s;
        }
        .step-item:hover {
          background: rgba(0, 0, 0, 0.1);
        }
        .step-marker {
          flex-shrink: 0;
          margin-top: 2px;
        }
        .step-content {
          flex: 1;
        }
        .step-name {
          font-weight: 500;
          color: var(--text-primary);
          margin-bottom: 2px;
        }
        .step-reason {
          color: var(--text-secondary);
          font-size: 11px;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

interface StepHistoryItemProps {
  step: StepEvent;
}

const StepHistoryItem: React.FC<StepHistoryItemProps> = ({ step }) => {
  const [showReasoning, setShowReasoning] = useState(false);

  const getStepLabel = (name: string) => {
    const labels: Record<string, string> = {
      loading_context: 'Loading Context',
      analyzing_question: 'Analyzing Question',
      running_discovery: 'Running Discovery',
      deciding: 'Deciding',
      dispatching_artifacts: 'Dispatching Artifacts',
      artifact_progress: 'Processing Artifact',
      joining_results: 'Joining Results',
      synthesizing: 'Synthesizing',
      direct_response: 'Direct Response',
      error: 'Error',
    };
    return labels[name] || name;
  };

  return (
    <div
      className="step-item"
      onClick={() => setShowReasoning(!showReasoning)}
    >
      <div className="step-marker">
        {step.status === 'done' && <CheckCircle size={12} className="success" />}
        {step.status === 'in_progress' && <Loader size={12} className="spin" />}
        {step.status === 'error' && <AlertCircle size={12} className="error" />}
      </div>
      <div className="step-content">
        <div className="step-name">{getStepLabel(step.name)}</div>
        {showReasoning && step.reasoning && (
          <div className="step-reason">{step.reasoning}</div>
        )}
      </div>
    </div>
  );
};
