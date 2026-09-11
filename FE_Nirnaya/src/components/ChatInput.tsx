import React, { useState, useRef, useEffect } from 'react';
import {
  Plus,
  Send,
  FileText,
  FileSpreadsheet,
  FileCode,
  X,
  ChevronDown,
  Sparkles,
  Zap,
  KeyRound,
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
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  selectedModelId,
  onSelectModel,
  isLoading = false,
  isDataLoaded = false,
  availableModels = [],
  onOpenCredentials,
}) => {
  const [content, setContent] = useState('');
  const [stagedFiles, setStagedFiles] = useState<FileAttachment[]>([]);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);

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

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const newAttachments: FileAttachment[] = [];
    Array.from(files).forEach((file) => {
      const ext = file.name.split('.').pop()?.toLowerCase() || '';
      newAttachments.push({
        id: `file-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
        name: file.name,
        size: file.size,
        type: file.type || 'application/octet-stream',
        extension: ext,
        uploadedAt: new Date().toISOString(),
      });
    });

    setStagedFiles((prev) => [...prev, ...newAttachments]);
    // Reset file input value so user can upload same file again if desired
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleRemoveStagedFile = (fileId: string) => {
    setStagedFiles((prev) => prev.filter((f) => f.id !== fileId));
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getFileIcon = (ext: string) => {
    if (['csv', 'xlsx', 'xls', 'parquet'].includes(ext)) {
      return <FileSpreadsheet size={13} style={{ color: 'var(--accent-emerald)' }} />;
    }
    if (['sql', 'json', 'py', 'ts'].includes(ext)) {
      return <FileCode size={13} style={{ color: 'var(--accent-cyan)' }} />;
    }
    return <FileText size={13} style={{ color: '#94a3b8' }} />;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSend = () => {
    if ((!content.trim() && stagedFiles.length === 0) || isLoading) return;

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

    onSendMessage(content.trim(), stagedFiles, modelToUse);
    setContent('');
    setStagedFiles([]);

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  return (
    <div className="chat-input-wrapper">
      <div className="chat-input-container">
        {/* Staged Attached Files Bar */}
        {stagedFiles.length > 0 && (
          <div className="staged-files-bar">
            {stagedFiles.map((file) => (
              <div key={file.id} className="staged-file-chip">
                {getFileIcon(file.extension)}
                <span className="staged-file-name" title={file.name}>
                  {file.name}
                </span>
                <span className="staged-file-size">({formatFileSize(file.size)})</span>
                <button
                  type="button"
                  className="btn-remove-staged-file"
                  onClick={() => handleRemoveStagedFile(file.id)}
                  title="Remove file"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Input Textarea Row */}
        <div className="input-main-row">
          {/* Plus icon to add files */}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            multiple
            accept=".csv,.xlsx,.xls,.json,.parquet,.txt,.pdf,.sql"
            style={{ display: 'none' }}
            id="file-upload-input"
          />
          <button
            type="button"
            className="btn-plus-attach"
            onClick={() => fileInputRef.current?.click()}
            title="Attach data files (CSV, Excel, JSON, Parquet, SQL, PDF)"
            id="btn-attach-files"
          >
            <Plus size={18} strokeWidth={2.5} />
          </button>

          {/* Chat Textarea */}
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            placeholder={
              !isDataLoaded || hasModels
                ? 'Ask questions based on your data or project... (Shift+Enter for newline)'
                : 'Add an API key in settings to start asking analytics questions...'
            }
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={isLoading}
            id="chat-textarea-input"
          />

          {/* Send Button */}
          <button
            type="button"
            className="btn-send-message"
            onClick={handleSend}
            disabled={(!content.trim() && stagedFiles.length === 0) || isLoading}
            title={
              !hasModels
                ? 'Add an API key to send queries'
                : 'Send query (Enter)'
            }
            id="btn-send-chat"
          >
            <Send size={16} strokeWidth={2.2} />
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
    </div>
  );
};
