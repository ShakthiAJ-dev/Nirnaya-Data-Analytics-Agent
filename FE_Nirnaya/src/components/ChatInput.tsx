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
} from 'lucide-react';
import type { FileAttachment } from '../types';
import { AVAILABLE_MODELS } from '../constants/models';

interface ChatInputProps {
  onSendMessage: (content: string, files: FileAttachment[], selectedModel: string) => void;
  selectedModelId: string;
  onSelectModel: (modelId: string) => void;
  isLoading?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  selectedModelId,
  onSelectModel,
  isLoading = false,
}) => {
  const [content, setContent] = useState('');
  const [stagedFiles, setStagedFiles] = useState<FileAttachment[]>([]);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);

  const selectedModel =
    AVAILABLE_MODELS.find((m) => m.id === selectedModelId) || AVAILABLE_MODELS[0];

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

    onSendMessage(content.trim(), stagedFiles, selectedModel.id);
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
            placeholder="Ask questions based on your data or project... (Shift+Enter for newline)"
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
            title="Send query (Enter)"
            id="btn-send-chat"
          >
            <Send size={16} strokeWidth={2.2} />
          </button>
        </div>

        {/* Bottom Bar: Model Selector Dropdown & Capabilities hint */}
        <div className="input-bottom-bar">
          {/* Model Selector (Defaults to Claude 3.5 Haiku) */}
          <div className="model-picker-wrapper" ref={modelPickerRef}>
            <button
              type="button"
              className={`model-picker-btn ${selectedModel.id === 'claude-3-5-haiku' ? 'haiku-active' : ''}`}
              onClick={() => setShowModelPicker(!showModelPicker)}
              title="Select AI Model (Default: Claude 3.5 Haiku)"
              id="btn-model-selector"
            >
              <Zap size={13} style={{ color: 'var(--accent-cyan)' }} />
              <span>{selectedModel.name}</span>
              {selectedModel.id === 'claude-3-5-haiku' && (
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

            {/* Model Dropdown Menu */}
            {showModelPicker && (
              <div className="model-dropdown-menu" id="model-dropdown-menu">
                <div className="model-dropdown-header">Select Analytics Model</div>
                {AVAILABLE_MODELS.map((model) => (
                  <button
                    key={model.id}
                    type="button"
                    className={`model-option-item ${model.id === selectedModel.id ? 'selected' : ''}`}
                    onClick={() => {
                      onSelectModel(model.id);
                      setShowModelPicker(false);
                    }}
                  >
                    <div className="model-option-top">
                      <span className="model-option-name">{model.name}</span>
                      {model.badge && (
                        <span className="model-option-badge">{model.badge}</span>
                      )}
                    </div>
                    <span className="model-option-desc">{model.description}</span>
                  </button>
                ))}
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
