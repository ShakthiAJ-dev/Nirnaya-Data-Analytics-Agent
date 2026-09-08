import React, { useState } from 'react';
import { Key, Eye, EyeOff, ShieldCheck, X, Sparkles } from 'lucide-react';
import type { LLMCredentials } from '../types';

interface CredentialsModalProps {
  isOpen: boolean;
  onClose: () => void;
  credentials: LLMCredentials;
  onSave: (creds: LLMCredentials) => void;
}

export const CredentialsModal: React.FC<CredentialsModalProps> = ({
  isOpen,
  onClose,
  credentials,
  onSave,
}) => {
  const [formData, setFormData] = useState<LLMCredentials>({ ...credentials });
  const [showAnthropic, setShowAnthropic] = useState(false);
  const [showOpenAI, setShowOpenAI] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(formData);
    setSavedSuccess(true);
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 600);
  };

  const handleClear = () => {
    const emptyCreds: LLMCredentials = {
      anthropicApiKey: '',
      openaiApiKey: '',
      geminiApiKey: '',
      customEndpoint: '',
      preferredProvider: 'anthropic',
    };
    setFormData(emptyCreds);
    onSave(emptyCreds);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-row">
            <div className="cred-icon-wrap">
              <Key size={18} />
            </div>
            <div>
              <h2 className="modal-title">LLM Credentials & API Keys</h2>
              <p style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                Configure your Anthropic or OpenAI API keys
              </p>
            </div>
          </div>
          <button className="history-delete-btn" style={{ opacity: 1 }} onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {/* Privacy notice banner */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '10px 14px',
                background: 'rgba(99, 102, 241, 0.08)',
                border: '1px solid rgba(99, 102, 241, 0.2)',
                borderRadius: '8px',
                fontSize: '12px',
                color: '#c7d2fe',
              }}
            >
              <ShieldCheck size={18} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
              <span>
                Your credentials are encrypted in local browser storage. They are never sent to third-party tracking servers.
              </span>
            </div>

            {/* Anthropic Claude Key (Primary for Haiku) */}
            <div className="form-group">
              <label className="form-label">
                <span>Anthropic API Key (Claude Haiku / Sonnet)</span>
                <span className="badge-configured" style={{ fontSize: '9.5px' }}>
                  Recommended
                </span>
              </label>
              <div className="form-input-wrapper">
                <input
                  type={showAnthropic ? 'text' : 'password'}
                  className="form-input"
                  placeholder="sk-ant-api03-..."
                  value={formData.anthropicApiKey}
                  onChange={(e) => setFormData({ ...formData, anthropicApiKey: e.target.value })}
                />
                <button
                  type="button"
                  className="btn-toggle-mask"
                  onClick={() => setShowAnthropic(!showAnthropic)}
                  tabIndex={-1}
                >
                  {showAnthropic ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <span className="form-help-text">
                Required for the default <strong>Claude 3.5 Haiku</strong> model and Sonnet analytics.
              </span>
            </div>

            {/* OpenAI API Key */}
            <div className="form-group">
              <label className="form-label">
                <span>OpenAI API Key (GPT-4o / GPT-4o-mini)</span>
              </label>
              <div className="form-input-wrapper">
                <input
                  type={showOpenAI ? 'text' : 'password'}
                  className="form-input"
                  placeholder="sk-..."
                  value={formData.openaiApiKey}
                  onChange={(e) => setFormData({ ...formData, openaiApiKey: e.target.value })}
                />
                <button
                  type="button"
                  className="btn-toggle-mask"
                  onClick={() => setShowOpenAI(!showOpenAI)}
                  tabIndex={-1}
                >
                  {showOpenAI ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <span className="form-help-text">
                Required when selecting OpenAI models for data extraction.
              </span>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn-secondary" onClick={handleClear}>
              Clear Keys
            </button>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {savedSuccess ? (
                <>
                  <Sparkles size={15} /> Saved!
                </>
              ) : (
                'Save Credentials'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
