import React, { useRef, useEffect, useState } from 'react';
import {
  Copy,
  Check,
  Code2,
  Table as TableIcon,
  TrendingUp,
  FileSpreadsheet,
  FileText,
  Clock,
  ArrowRight,
  Database,
} from 'lucide-react';
import { LogoEmblem } from './Logo';
import type { Message, Project } from '../types';
import { AVAILABLE_MODELS } from '../constants/models';

interface ChatAreaProps {
  currentProject: Project;
  messages: Message[];
  selectedModelId: string;
  isLoading: boolean;
  onSendSuggestedPrompt: (prompt: string) => void;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  currentProject,
  messages,
  selectedModelId,
  isLoading,
  onSendSuggestedPrompt,
}) => {
  const scrollEndRef = useRef<HTMLDivElement>(null);
  const [copiedCodeId, setCopiedCodeId] = useState<string | null>(null);

  const selectedModel =
    AVAILABLE_MODELS.find((m) => m.id === selectedModelId) || AVAILABLE_MODELS[0];

  // Auto scroll to bottom
  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleCopyCode = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCodeId(id);
    setTimeout(() => setCopiedCodeId(null), 2000);
  };

  const starterPrompts = [
    {
      title: '📈 Quarterly Revenue Variance',
      desc: 'Breakdown revenue vs target across product categories and detect margin slippage.',
      prompt: 'Analyze our Q3 gross revenue, category contributions, and margin trends.',
    },
    {
      title: '🔍 Customer Churn Cliff Analysis',
      desc: 'Pinpoint which cohort month experiences steepest retention drop-off.',
      prompt: 'Identify the customer churn cliff and primary triggers across cohorts.',
    },
    {
      title: '⚡ SQL Query Generation',
      desc: 'Formulate optimized analytics SQL for high-LTV segment activity.',
      prompt: 'Generate an analytical SQL query to extract our top active customer cohorts.',
    },
    {
      title: '📑 Auto-Profile Project Datasets',
      desc: 'Inspect dataset schemas, missing values, and data health scores.',
      prompt: 'Please profile our active project datasets and highlight data quality anomalies.',
    },
  ];

  return (
    <div className="nirnaya-chat-main">
      {/* Chat Area Top Header */}
      <header className="chat-header">
        <div className="chat-header-title-box">
          <div className="chat-header-project">
            <Database size={16} style={{ color: 'var(--accent-cyan)' }} />
            <span>{currentProject.name}</span>
          </div>
          <span className="header-slash">/</span>
          <span className="chat-header-session">Data Analytics Chat</span>
        </div>

        <div className="chat-header-actions">
          <div className="model-pill-badge" title={`Active model: ${selectedModel.name}`}>
            <span className="model-pill-dot"></span>
            <span>{selectedModel.name}</span>
          </div>
        </div>
      </header>

      {/* Messages Stream Container */}
      <div className="chat-messages-container">
        {messages.length === 0 ? (
          /* Empty / Welcome State with Nirnaya Logo */
          <div className="empty-state-wrap">
            <div className="empty-logo-glow">
              <LogoEmblem size={44} />
            </div>

            <h1 className="empty-heading">What decision are we analyzing today?</h1>
            <p className="empty-subtext">
              Welcome to <span className="kannada-accent-pill">Nirnaya</span>. Ask complex
              business questions, inspect uploaded data files, or simulate strategic decisions
              across <strong style={{ color: '#ffffff' }}>{currentProject.name}</strong>.
            </p>

            {/* Quick Starter Prompts */}
            <div className="starter-prompts-grid">
              {starterPrompts.map((item, idx) => (
                <button
                  key={idx}
                  type="button"
                  className="prompt-card-btn"
                  onClick={() => onSendSuggestedPrompt(item.prompt)}
                >
                  <div className="prompt-card-header">
                    <span>{item.title}</span>
                  </div>
                  <div className="prompt-card-desc">{item.desc}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Message Thread */
          messages.map((msg) => {
            const isUser = msg.role === 'user';

            if (isUser) {
              /* ==========================================================
                 USER MESSAGE: ALWAYS RIGHT HAND SIDE
                 ========================================================== */
              return (
                <div key={msg.id} className="message-row message-row-user">
                  <div className="message-bubble-user-wrap">
                    <div className="user-bubble">
                      <p style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</p>

                      {/* User Attached Files */}
                      {msg.files && msg.files.length > 0 && (
                        <div className="user-attachments-container">
                          {msg.files.map((file) => (
                            <span key={file.id} className="attachment-tag">
                              {file.extension === 'csv' || file.extension === 'xlsx' ? (
                                <FileSpreadsheet size={12} />
                              ) : (
                                <FileText size={12} />
                              )}
                              <span>{file.name}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="message-meta-right">
                      <Clock size={11} />
                      <span>{msg.timestamp}</span>
                      <span>• You</span>
                    </div>
                  </div>
                </div>
              );
            }

            /* ==========================================================
               ASSISTANT MESSAGE: ALWAYS LEFT HAND SIDE
               ========================================================== */
            return (
              <div key={msg.id} className="message-row message-row-assistant">
                <div className="message-bubble-assistant-wrap">
                  {/* Nirnaya Avatar */}
                  <div className="assistant-avatar" title="Nirnaya Analytics Agent">
                    <LogoEmblem size={22} />
                  </div>

                  <div className="assistant-content-box">
                    <div className="assistant-bubble">
                      {/* Main explanation content */}
                      <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>

                      {/* SQL Code Query Block */}
                      {msg.sqlQuery && (
                        <div className="code-block-wrapper">
                          <div className="code-block-header">
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <Code2 size={13} style={{ color: 'var(--accent-cyan)' }} />
                              Analytical SQL Query
                            </span>
                            <button
                              type="button"
                              className="btn-copy-code"
                              onClick={() => handleCopyCode(msg.sqlQuery!, msg.id)}
                            >
                              {copiedCodeId === msg.id ? (
                                <>
                                  <Check size={12} style={{ color: 'var(--accent-emerald)' }} />
                                  Copied
                                </>
                              ) : (
                                <>
                                  <Copy size={12} />
                                  Copy SQL
                                </>
                              )}
                            </button>
                          </div>
                          <pre className="code-block-content">
                            <code>{msg.sqlQuery}</code>
                          </pre>
                        </div>
                      )}

                      {/* Data Analytics Table */}
                      {msg.tableData && (
                        <div className="data-table-wrapper">
                          {msg.tableData.title && (
                            <div className="data-table-title">
                              <TableIcon size={14} />
                              <span>{msg.tableData.title}</span>
                            </div>
                          )}
                          <div className="data-table-scroll">
                            <table className="analytics-table">
                              <thead>
                                <tr>
                                  {msg.tableData.headers.map((h, i) => (
                                    <th key={i}>{h}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {msg.tableData.rows.map((row, rIdx) => (
                                  <tr key={rIdx}>
                                    {row.map((cell, cIdx) => (
                                      <td key={cIdx}>{cell}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      {/* Key Insights & Strategic Decision Takeaways */}
                      {msg.insights && msg.insights.length > 0 && (
                        <div>
                          <div className="analytics-section-title">
                            <TrendingUp size={14} />
                            <span>Decision Insights</span>
                          </div>
                          <ul className="analytics-insights-list">
                            {msg.insights.map((insight, idx) => (
                              <li key={idx} className="analytics-insight-item">
                                <span className="insight-bullet"></span>
                                <span>{insight}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Follow-up / Suggestions */}
                      {msg.suggestions && msg.suggestions.length > 0 && (
                        <div style={{ marginTop: '14px' }}>
                          <div
                            style={{
                              fontSize: '11px',
                              fontWeight: 600,
                              textTransform: 'uppercase',
                              color: 'var(--text-muted)',
                              marginBottom: '8px',
                            }}
                          >
                            Suggested Follow-Ups:
                          </div>
                          <div className="assistant-suggestions">
                            {msg.suggestions.map((sug, sIdx) => (
                              <button
                                key={sIdx}
                                type="button"
                                className="suggestion-pill-btn"
                                onClick={() => onSendSuggestedPrompt(sug)}
                              >
                                <span>{sug}</span>
                                <ArrowRight size={11} />
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="assistant-meta-left">
                      <Clock size={11} />
                      <span>{msg.timestamp}</span>
                      <span>• Nirnaya Agent</span>
                      {msg.model && (
                        <span className="assistant-model-tag">{msg.model}</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}

        {/* Loading / Typing Indicator */}
        {isLoading && (
          <div className="message-row message-row-assistant">
            <div className="message-bubble-assistant-wrap">
              <div className="assistant-avatar">
                <LogoEmblem size={22} />
              </div>
              <div className="assistant-bubble typing-indicator-box">
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: '8px' }}>
                  Nirnaya is synthesizing decision data...
                </span>
              </div>
            </div>
          </div>
        )}

        <div ref={scrollEndRef} />
      </div>
    </div>
  );
};
