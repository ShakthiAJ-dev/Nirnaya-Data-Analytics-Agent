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
  HelpCircle,
  ArrowRight,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { FileAttachment, AskUserEvent } from '../types';
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

// ---------------------------------------------------------------------------
// AskUser Overlay — mounts above chat-input-container, below messages
// ---------------------------------------------------------------------------
const AskUserOverlay: React.FC<{
  askUser: AskUserEvent;
  modelId: string;
  onResponse: (turnId: string, answer: string, modelId: string) => void;
}> = ({ askUser, modelId, onResponse }) => {
  const [freeText, setFreeText] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!submitted) inputRef.current?.focus();
  }, [submitted]);

  const submit = (answer: string) => {
    if (!answer.trim() || submitted) return;
    setSubmitted(true);
    onResponse(askUser.turn_id, answer, modelId);
  };

  const isMcq = askUser.mode === 'mcq' && askUser.options && askUser.options.length > 0;

  return (
    <div style={{
      background: 'rgba(6,182,212,0.045)',
      border: '1px solid rgba(6,182,212,0.22)',
      borderBottom: 'none',
      borderRadius: '12px 12px 0 0',
      padding: '14px 16px 12px',
      animation: 'fadeSlideUp 0.2s ease',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '10px' }}>
        <HelpCircle size={13} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
        <span style={{ fontSize: '10.5px', fontWeight: 700, color: 'var(--accent-cyan)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Clarification Needed
        </span>
        <div style={{ flex: 1, height: '1px', background: 'rgba(6,182,212,0.15)', marginLeft: '4px' }} />
      </div>

      {/* Question — Markdown rendered */}
      <div className="ask-overlay-question" style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: '12px' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <p style={{ margin: 0 }}>{children}</p>,
            strong: ({ children }) => <strong style={{ color: 'var(--text-primary)' }}>{children}</strong>,
          }}
        >
          {askUser.question}
        </ReactMarkdown>
      </div>

      {/* MCQ options — vertical list */}
      {isMcq && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', marginBottom: '10px' }}>
          {askUser.options!.map((opt, i) => (
            <button
              key={i}
              type="button"
              disabled={submitted}
              onClick={() => submit(opt)}
              style={{
                padding: '8px 12px',
                borderRadius: '8px',
                border: '1px solid rgba(6,182,212,0.25)',
                background: 'rgba(6,182,212,0.06)',
                color: 'var(--text-primary)',
                fontSize: '12.5px',
                fontWeight: 400,
                cursor: submitted ? 'not-allowed' : 'pointer',
                transition: 'all 0.15s ease',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '9px',
                opacity: submitted ? 0.45 : 1,
                textAlign: 'left',
                width: '100%',
              }}
              onMouseEnter={(e) => { if (!submitted) { e.currentTarget.style.background = 'rgba(6,182,212,0.13)'; e.currentTarget.style.borderColor = 'rgba(6,182,212,0.45)'; }}}
              onMouseLeave={(e) => { if (!submitted) { e.currentTarget.style.background = 'rgba(6,182,212,0.06)'; e.currentTarget.style.borderColor = 'rgba(6,182,212,0.25)'; }}}
            >
              <span style={{
                width: '19px', height: '19px', borderRadius: '5px',
                background: 'rgba(6,182,212,0.12)',
                border: '1px solid rgba(6,182,212,0.3)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '10px', fontWeight: 700, flexShrink: 0, color: 'var(--accent-cyan)',
                marginTop: '1px',
              }}>
                {String.fromCharCode(65 + i)}
              </span>
              <span style={{ flex: 1, lineHeight: 1.5 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ p: ({ children }) => <span>{children}</span> }}>
                  {opt}
                </ReactMarkdown>
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Free-text textarea */}
      {!isMcq && (
        <textarea
          ref={inputRef}
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(freeText); }
          }}
          disabled={submitted}
          placeholder="Type your answer… (Enter or Send button to submit)"
          rows={2}
          style={{
            width: '100%', background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px',
            color: 'var(--text-primary)', fontSize: '13px', padding: '8px 12px',
            resize: 'none', outline: 'none', fontFamily: 'inherit', lineHeight: 1.5,
            marginBottom: '8px', boxSizing: 'border-box',
          }}
        />
      )}

      {/* Footer */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <button
          type="button"
          disabled={submitted}
          onClick={() => submit('Use defaults — proceed with best analytical judgment and state assumptions made.')}
          style={{
            background: 'none', border: 'none', cursor: submitted ? 'not-allowed' : 'pointer',
            color: 'var(--text-muted)', fontSize: '11.5px',
            display: 'flex', alignItems: 'center', gap: '4px',
            padding: '2px 0', opacity: submitted ? 0.4 : 0.65,
            transition: 'opacity 0.15s ease',
          }}
          onMouseEnter={(e) => { if (!submitted) e.currentTarget.style.opacity = '1'; }}
          onMouseLeave={(e) => { if (!submitted) e.currentTarget.style.opacity = '0.65'; }}
        >
          <ArrowRight size={11} />
          <span>Use defaults &amp; continue</span>
        </button>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', opacity: 0.55 }}>
          {isMcq ? 'Select an option above' : 'Enter or Send ↓'}
        </span>
      </div>

      <style>{`
        @keyframes fadeSlideUp {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
};


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
  /** Active unanswered ask_user event — overlay mounts above input. */
  activeAskUser?: AskUserEvent | null;
  /** Called when user submits an ask_user answer. */
  onAskUserResponse?: (turnId: string, answer: string, modelId: string) => void;
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
  activeAskUser,
  onAskUserResponse,
}) => {
  const [content, setContent] = useState('');
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [showNoDatabaseError, setShowNoDatabaseError] = useState(false);
  // Track whether current ask_user was submitted (for immediate overlay dismiss)
  const [submittedAskTurnId, setSubmittedAskTurnId] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const noDatabaseDismissRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasModels = availableModels.length > 0;

  // The currently selected model object (or null if no models loaded yet)
  const selectedModel =
    availableModels.find((m) => m.id === selectedModelId) ||
    (hasModels ? availableModels[0] : null);

  // Reset submittedAskTurnId when a new ask arrives
  useEffect(() => {
    if (activeAskUser?.turn_id && activeAskUser.turn_id !== submittedAskTurnId) {
      setSubmittedAskTurnId(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAskUser?.turn_id]);

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

  // Auto-select smart default
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

  // Overlay is active when there's an unanswered ask_user that hasn't been locally submitted yet
  const showAskOverlay =
    activeAskUser != null &&
    !activeAskUser.answeredAnswer &&
    activeAskUser.turn_id !== submittedAskTurnId;

  const handleAskUserResponse = (turnId: string, answer: string, mid: string) => {
    setSubmittedAskTurnId(turnId);
    onAskUserResponse?.(turnId, answer, mid);
  };

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
    // Block normal send while ask overlay is active
    if (showAskOverlay) return;

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

      {/* AskUser overlay — constrained to same width as chat-input-container */}
      {showAskOverlay && activeAskUser && onAskUserResponse && (
        <div style={{ maxWidth: '820px', margin: '0 auto' }}>
          <AskUserOverlay
            askUser={activeAskUser}
            modelId={selectedModel?.id || selectedModelId}
            onResponse={handleAskUserResponse}
          />
        </div>
      )}

      <div className="chat-input-container" style={showAskOverlay ? { borderTopLeftRadius: 0, borderTopRightRadius: 0 } : undefined}>
        {/* Input Textarea Row */}
        <div className="input-main-row">
          {/* Chat Textarea — dimmed while ask overlay is active */}
          <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              placeholder={
                showAskOverlay
                  ? 'Answer the clarification above to continue…'
                  : isLoading
                  ? 'Generating response… Press Esc to stop'
                  : !isDataLoaded || hasModels
                  ? 'Ask about your data, run queries, or explore insights…'
                  : 'Add an API key in settings to start asking analytics questions…'
              }
              value={showAskOverlay ? '' : content}
              onChange={(e) => { if (!showAskOverlay) setContent(e.target.value); }}
              onKeyDown={handleKeyDown}
              rows={1}
              id="chat-textarea-input"
              disabled={showAskOverlay}
              style={showAskOverlay ? { opacity: 0.3, cursor: 'not-allowed', pointerEvents: 'none' } : undefined}
            />
          </div>

          {/* Stop button — always shown when agent is active (including during ask_user) */}
          {isLoading ? (
            <button
              type="button"
              className="btn-stop-generating"
              onClick={onStopGeneration}
              title="Stop generation (Esc)"
              id="btn-send-chat"
            >
              <Square size={11} strokeWidth={2.5} fill="currentColor" />
              <span className="btn-stop-label">Stop</span>
            </button>
          ) : (
            <button
              type="button"
              className="btn-send-message"
              onClick={handleSend}
              disabled={showAskOverlay || !content.trim()}
              title={
                showAskOverlay
                  ? 'Answer the clarification above'
                  : !hasModels
                  ? 'Add an API key to send queries'
                  : 'Send query (Enter)'
              }
              id="btn-send-chat"
            >
              <Send size={16} strokeWidth={2.2} />
            </button>
          )}
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

          <div className="chat-input-bottom-hint" style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Sparkles size={12} style={{ color: 'var(--accent-primary)' }} />
            <span>Multi-turn analytics  •  Shift+Enter for new line</span>
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
