import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  X,
  ChevronDown,
  Sparkles,
  Zap,
  KeyRound,
  Database,
  AlertTriangle,
  Square,
} from 'lucide-react';
import type { FileAttachment } from '../types';
import type { BackendModel } from '../hooks/useModels';

// Preferred defaults when BE models first load
const PREFERRED_DEFAULTS = ['claude-4.5-haiku', 'gpt-5.4-mini'];

function pickDefaultModel(models: BackendModel[]): string {
  for (const preferred of PREFERRED_DEFAULTS) {
    const found = models.find((m) => m.id === preferred);
    if (found) return found.id;
  }
  return models[0]?.id ?? '';
}

interface ChatInputProps {
  onSendMessage: (content: string, files: FileAttachment[], selectedModel: string) => void;
  selectedModelId: string;
  onSelectModel: (modelId: string) => void;
  isLoading?: boolean;
  isDataLoaded?: boolean;
  /** Live models from BE — only populated when provider keys are stored. */
  availableModels?: BackendModel[];
  /** Callback to open the LLM Credentials modal when user needs to add keys. */
  onOpenCredentials?: () => void;
  /** True when no database has been selected yet — blocks send and shows an inline error. */
  noDatabaseSelected?: boolean;
  /** Open the demo database init modal — shown as a quick-action in the no-DB error banner. */
  onAddDemo?: () => void;
  /** Callback to cancel/pause generation. */
  onStopGeneration?: () => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  selectedModelId,
  onSelectModel,
  isLoading = false,
  isDataLoaded = false,
  availableModels = [],
  onOpenCredentials,
  noDatabaseSelected = false,
  onAddDemo,
  onStopGeneration,
}) => {
  const [content, setContent] = useState('');
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [showNoDatabaseError, setShowNoDatabaseError] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const noDatabaseDismissRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasModels = availableModels.length > 0;

  // The currently selected model object (or null if no models loaded yet)
  const selectedModel =
    availableModels.find((m) => m.id === selectedModelId) ||
    (hasModels ? availableModels[0] : null);

  // Auto resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [content]);

  // Close model picker on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modelPickerRef.current && !modelPickerRef.current.contains(e.target as Node)) {
        setShowModelPicker(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Auto-select smart default (claude-4.5-haiku for Anthropic, gpt-5.4-mini for OpenAI)
  const modelsKey = availableModels.map((m) => m.id).join(',');
  useEffect(() => {
    if (availableModels.length > 0) {
      const currentIsValid = availableModels.some((m) => m.id === selectedModelId);
      if (!currentIsValid) {
        onSelectModel(pickDefaultModel(availableModels));
      }
    } else if (selectedModelId) {
      onSelectModel('');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsKey]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape' && isLoading) {
      e.preventDefault();
      onStopGeneration?.();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSend = () => {
    if (!content.trim() || isLoading) return;

    // Guard: no database selected
    if (noDatabaseSelected) {
      // Show the error banner and auto-dismiss after 4s
      setShowNoDatabaseError(true);
      if (noDatabaseDismissRef.current) clearTimeout(noDatabaseDismissRef.current);
      noDatabaseDismissRef.current = setTimeout(() => setShowNoDatabaseError(false), 4000);
      return;
    }

    if (!hasModels) {
      if (onOpenCredentials) {
        onOpenCredentials();
      } else {
        setShowModelPicker(true);
      }
      return;
    }

    const modelToUse = selectedModel?.id || selectedModelId;
    if (!modelToUse) {
      if (onOpenCredentials) onOpenCredentials();
      return;
    }

    onSendMessage(content.trim(), [], modelToUse);
    setContent('');

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  return (
    <div className="chat-input-wrapper">
      {/* No-database error banner */}
      {showNoDatabaseError && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            padding: '10px 16px', marginBottom: '8px',
            background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)',
            borderRadius: '10px', animation: 'shake 0.4s ease',
          }}
        >
          <AlertTriangle size={15} style={{ color: '#f59e0b', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <span style={{ fontSize: '13px', fontWeight: 600, color: '#fbbf24' }}>
              No database selected
            </span>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', marginLeft: '6px' }}>
              Select a database from the sidebar or load the demo to start chatting.
            </span>
          </div>
          {onAddDemo && (
            <button
              type="button"
              onClick={() => { setShowNoDatabaseError(false); onAddDemo(); }}
              style={{
                padding: '5px 12px', borderRadius: '6px', border: 'none',
                background: 'rgba(245,158,11,0.2)', color: '#fbbf24',
                cursor: 'pointer', fontSize: '12px', fontWeight: 600,
                display: 'flex', alignItems: 'center', gap: '5px', flexShrink: 0,
              }}
            >
              <Database size={12} />
              <span>Load Demo</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowNoDatabaseError(false)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: '2px', flexShrink: 0 }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="chat-input-container">
        {/* Input Textarea Row */}
        <div className="input-main-row">
          {/* Chat Textarea */}
          <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              placeholder={
                isLoading
                  ? 'Generating response... Click Pause to stop (Esc)'
                  : !isDataLoaded || hasModels
                  ? 'Ask questions based on your data or project... (Shift+Enter for newline)'
                  : 'Add an API key in settings to start asking analytics questions...'
              }
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              id="chat-textarea-input"
            />
            {isLoading && (
              <button
                type="button"
                className="chat-pause-indicator"
                onClick={onStopGeneration}
                title="Click to pause response"
              >
                <span className="pulse-dot" />
                <span>Pause</span>
              </button>
            )}
          </div>

          {/* Send or Stop Button */}
          <button
            type="button"
            className={`btn-send-message ${isLoading ? 'btn-stop-generating' : ''}`}
            onClick={isLoading ? onStopGeneration : handleSend}
            disabled={!isLoading && !content.trim()}
            title={
              isLoading
                ? 'Pause / Stop generation (Esc)'
                : !hasModels
                ? 'Add an API key to send queries'
                : 'Send query (Enter)'
            }
            id="btn-send-chat"
          >
            {isLoading ? (
              <Square size={13} strokeWidth={2.2} fill="currentColor" />
            ) : (
              <Send size={16} strokeWidth={2.2} />
            )}
          </button>
        </div>

        {/* Bottom Bar: Model Selector Dropdown & Capabilities hint */}
        <div className="input-bottom-bar">
          {/* Model Selector */}
          <div className="model-picker-wrapper" ref={modelPickerRef}>
            {hasModels && selectedModel ? (
              <button
                type="button"
                className={`model-picker-btn ${
                  selectedModel.id === 'claude-4.5-haiku' || selectedModel.id === 'gpt-5.4-mini'
                    ? 'haiku-active'
                    : ''
                }`}
                onClick={() => setShowModelPicker(!showModelPicker)}
                title="Select AI Model"
                id="btn-model-selector"
              >
                <Zap size={13} style={{ color: 'var(--accent-cyan)' }} />
                <span>{selectedModel.name}</span>
                {(selectedModel.id === 'claude-4.5-haiku' ||
                  selectedModel.id === 'gpt-5.4-mini') && (
                  <span
                    style={{
                      fontSize: '9.5px',
                      background: 'rgba(6, 182, 212, 0.15)',
                      color: 'var(--accent-cyan)',
                      padding: '1px 5px',
                      borderRadius: '4px',
                      fontWeight: 600,
                    }}
                  >
                    Default
                  </span>
                )}
                <ChevronDown size={12} style={{ color: 'var(--text-muted)' }} />
              </button>
            ) : isDataLoaded ? (
              <button
                type="button"
                className="model-picker-btn model-picker-no-key"
                onClick={() => {
                  if (onOpenCredentials) {
                    onOpenCredentials();
                  } else {
                    setShowModelPicker(!showModelPicker);
                  }
                }}
                title="No AI models active — click to add your API key"
                id="btn-model-selector"
              >
                <KeyRound size={13} style={{ color: 'var(--accent-amber, #f59e0b)' }} />
                <span style={{ color: 'var(--accent-amber, #f59e0b)', fontWeight: 500 }}>
                  Add API Key to unlock models
                </span>
              </button>
            ) : (
              <div
                className="model-picker-btn"
                style={{ color: 'var(--text-muted)', pointerEvents: 'none' }}
              >
                <Zap size={13} style={{ opacity: 0.4 }} />
                <span style={{ opacity: 0.5 }}>Loading…</span>
              </div>
            )}

            {/* Model Dropdown Menu */}
            {showModelPicker && (
              <div className="model-dropdown-menu" id="model-dropdown-menu">
                {hasModels ? (
                  <>
                    <div className="model-dropdown-header">Available Models</div>
                    {availableModels.map((model) => {
                      const isSelected = model.id === selectedModel?.id;
                      const isDefault =
                        model.id === 'claude-4.5-haiku' || model.id === 'gpt-5.4-mini';
                      return (
                        <button
                          key={model.id}
                          type="button"
                          className={`model-option-item ${isSelected ? 'selected' : ''}`}
                          onClick={() => {
                            onSelectModel(model.id);
                            setShowModelPicker(false);
                          }}
                        >
                          <div className="model-option-top">
                            <span className="model-option-name">{model.name}</span>
                            {isDefault ? (
                              <span className="model-option-badge">Default</span>
                            ) : model.provider ? (
                              <span
                                className="model-option-badge"
                                style={{ textTransform: 'capitalize' }}
                              >
                                {model.provider}
                              </span>
                            ) : null}
                          </div>
                          {model.description && (
                            <span className="model-option-desc">{model.description}</span>
                          )}
                        </button>
                      );
                    })}
                  </>
                ) : isDataLoaded ? (
                  <div className="model-dropdown-empty-state">
                    <KeyRound
                      size={20}
                      style={{ color: 'var(--accent-amber, #f59e0b)', margin: '0 auto 8px' }}
                    />
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: '13px',
                        color: 'var(--text-primary)',
                        marginBottom: '4px',
                      }}
                    >
                      No AI Models Configured
                    </div>
                    <div
                      style={{
                        fontSize: '11.5px',
                        color: 'var(--text-muted)',
                        lineHeight: 1.4,
                        marginBottom: '12px',
                      }}
                    >
                      Add your Anthropic (Claude) or OpenAI (GPT) API key to unlock data analytics
                      models for this session.
                    </div>
                    {onOpenCredentials && (
                      <button
                        type="button"
                        className="btn-add-keys-prompt"
                        onClick={() => {
                          setShowModelPicker(false);
                          onOpenCredentials();
                        }}
                      >
                        <KeyRound size={12} />
                        <span>Configure API Keys</span>
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="model-dropdown-empty-state" style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                    Loading…
                  </div>
                )}
              </div>
            )}
          </div>

          <div style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Sparkles size={12} style={{ color: 'var(--accent-primary)' }} />
            <span>Nirnaya Data Agent • Multi-turn analytics</span>
          </div>
        </div>
      </div>

      <div className="input-footer-hint">
        Nirnaya synthesizes insights across datasets. Verify critical business calculations before finalizing decisions.
      </div>
      <style>{`
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          15% { transform: translateX(-6px); }
          30% { transform: translateX(6px); }
          45% { transform: translateX(-4px); }
          60% { transform: translateX(4px); }
          75% { transform: translateX(-2px); }
          90% { transform: translateX(2px); }
        }
      `}</style>
    </div>
  );
};
