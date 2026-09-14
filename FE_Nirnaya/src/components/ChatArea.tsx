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
  KeyRound,
  ChevronDown,
  CheckCircle,
  AlertCircle,
  Sparkles,
  HelpCircle,
  ArrowUpRight,
  Trash2,
  MoreVertical,
} from 'lucide-react';
import { LogoEmblem } from './Logo';
import type { Message, Project, Database as DatabaseType, Artifact, AskUserEvent } from '../types';
import type { BackendModel } from '../services/sessionService';

// ---------------------------------------------------------------------------
// Inline Markdown Renderer
// ---------------------------------------------------------------------------

function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*(.+?)\*\*)|(`([^`]+)`)|(\*(.+?)\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<span key={key++}>{text.slice(lastIndex, match.index)}</span>);
    }
    if (match[1]) {
      parts.push(<strong key={key++}>{match[2]}</strong>);
    } else if (match[3]) {
      parts.push(<code key={key++} className="md-inline-code">{match[4]}</code>);
    } else if (match[5]) {
      parts.push(<em key={key++}>{match[6]}</em>);
    }
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(<span key={key++}>{text.slice(lastIndex)}</span>);
  }
  return parts.length === 0 ? text : parts.length === 1 ? parts[0] : parts;
}

const MarkdownContent: React.FC<{ text: string }> = ({ text }) => {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trimStart().startsWith('```')) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      elements.push(
        <pre key={`cb-${i}`} className="md-pre"><code>{codeLines.join('\n')}</code></pre>
      );
      i++;
      continue;
    }
    if (line.startsWith('### ')) { elements.push(<h3 key={i} className="md-h3">{renderInline(line.slice(4))}</h3>); i++; continue; }
    if (line.startsWith('## ')) { elements.push(<h2 key={i} className="md-h2">{renderInline(line.slice(3))}</h2>); i++; continue; }
    if (line.startsWith('# ')) { elements.push(<h1 key={i} className="md-h1">{renderInline(line.slice(2))}</h1>); i++; continue; }
    if (line === '---' || line === '***' || line === '___') { elements.push(<hr key={i} className="md-hr" />); i++; continue; }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const items: string[] = [];
      while (i < lines.length && (lines[i].startsWith('- ') || lines[i].startsWith('* '))) {
        items.push(lines[i].slice(2));
        i++;
      }
      elements.push(<ul key={`ul-${i}`} className="md-ul">{items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}</ul>);
      continue;
    }
    if (/^\d+\. /.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\. /, ''));
        i++;
      }
      elements.push(<ol key={`ol-${i}`} className="md-ol">{items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}</ol>);
      continue;
    }
    if (line.startsWith('> ')) { elements.push(<blockquote key={i} className="md-blockquote">{renderInline(line.slice(2))}</blockquote>); i++; continue; }
    if (line.trim() === '') { i++; continue; }
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].startsWith('#') &&
      !lines[i].startsWith('- ') &&
      !lines[i].startsWith('* ') &&
      !lines[i].startsWith('> ') &&
      !lines[i].trimStart().startsWith('```') &&
      !/^\d+\. /.test(lines[i]) &&
      lines[i] !== '---' && lines[i] !== '***'
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      elements.push(
        <p key={`p-${i}`} className="md-p">
          {paraLines.map((pl, j) => (
            <React.Fragment key={j}>{j > 0 && <br />}{renderInline(pl)}</React.Fragment>
          ))}
        </p>
      );
    }
  }
  return <div className="markdown-content">{elements}</div>;
};

// ---------------------------------------------------------------------------
// TypingDots
// ---------------------------------------------------------------------------
// TurnMetaRow — rendered BETWEEN user bubble and assistant bubble
// ---------------------------------------------------------------------------

function formatThinkDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 1) return '<1s';
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

const TurnMetaRow: React.FC<{
  msg: Message;
  isLast: boolean;
  isLoading: boolean;
}> = ({ msg, isLast, isLoading }) => {
  const [expanded, setExpanded] = useState(false);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  const [elapsed, setElapsed] = useState<string>('');

  const isLive = isLoading && isLast;
  const hasSteps = Boolean(msg.steps && msg.steps.length > 0);
  const hasMeta = hasSteps || Boolean(msg.executionTimeMs);

  // Live elapsed timer
  useEffect(() => {
    if (!isLive || !msg.turnStartTime) return;
    const update = () => setElapsed(formatThinkDuration(Date.now() - msg.turnStartTime!));
    update();
    const id = setInterval(update, 250);
    return () => clearInterval(id);
  }, [isLive, msg.turnStartTime]);

  if (!isLive && !hasMeta) return null;

  const toggleStep = (seq: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

  const sortedSteps = [...(msg.steps || [])].sort((a, b) => a.seq - b.seq);
  const currentStep = sortedSteps[sortedSteps.length - 1];

  if (isLive) {
    // Show all accumulated steps while processing — each is expandable for reasoning
    return (
      <div className="turn-meta-row">
        <div className="turn-meta-live" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '6px', padding: '8px 10px' }}>
          {/* Spinner + current label */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%' }}>
            <span className="turn-meta-spinner" />
            <span className="turn-meta-step-label">
              {currentStep ? currentStep.title : 'Thinking…'}
            </span>
            {elapsed && <span className="turn-meta-elapsed" style={{ marginLeft: 'auto' }}>{elapsed}</span>}
          </div>
          {/* All prior completed steps — accumulated, each expandable */}
          {sortedSteps.length > 0 && (
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '2px', paddingLeft: '20px' }}>
              {sortedSteps.map((step) => (
                <React.Fragment key={step.seq}>
                  <div
                    style={{
                      display: 'flex', alignItems: 'center', gap: '6px',
                      fontSize: '11.5px', color: step.status === 'in_progress' ? 'var(--text-secondary)' : 'var(--text-muted)',
                      cursor: step.reasoning ? 'pointer' : 'default',
                      padding: '2px 0',
                    }}
                    onClick={() => step.reasoning && toggleStep(step.seq)}
                  >
                    {step.status === 'in_progress' ? (
                      <span className="thinking-spin-icon" style={{ width: '10px', height: '10px', flexShrink: 0 }} />
                    ) : step.status === 'error' ? (
                      <AlertCircle size={10} style={{ color: '#ef4444', flexShrink: 0 }} />
                    ) : (
                      <CheckCircle size={10} style={{ color: '#10b981', flexShrink: 0 }} />
                    )}
                    <span>{step.title}</span>
                    {step.detail && <span style={{ opacity: 0.55 }}>— {step.detail}</span>}
                    {step.reasoning && (
                      <ChevronDown
                        size={9}
                        style={{
                          marginLeft: 'auto', flexShrink: 0, color: 'var(--text-muted)',
                          transform: expandedSteps.has(step.seq) ? 'rotate(180deg)' : 'none',
                          transition: 'transform 0.2s ease',
                        }}
                      />
                    )}
                  </div>
                  {expandedSteps.has(step.seq) && step.reasoning && (
                    <div className="turn-meta-step-reasoning" style={{ marginLeft: '16px', marginBottom: '2px' }}>
                      {step.reasoning}
                    </div>
                  )}
                </React.Fragment>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Done state
  const execSec = msg.executionTimeMs ? formatThinkDuration(msg.executionTimeMs) : null;
  const thinkSec = msg.thinkingSeconds ? `${msg.thinkingSeconds}s` : null;
  const displayTime = execSec || thinkSec || '';

  return (
    <div className="turn-meta-row">
      <button
        type="button"
        className="turn-meta-done-btn"
        onClick={() => setExpanded((v) => !v)}
      >
        <Sparkles size={11} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
        <span>
          {displayTime ? `Analysed in ${displayTime}` : 'Analysis complete'}
        </span>
        {sortedSteps.length > 0 && (
          <span className="turn-meta-step-count">{sortedSteps.length} steps</span>
        )}
        <ChevronDown
          size={11}
          style={{
            marginLeft: 'auto',
            flexShrink: 0,
            color: 'var(--text-muted)',
            transform: expanded ? 'rotate(180deg)' : 'none',
            transition: 'transform 0.2s ease',
          }}
        />
      </button>
      {expanded && sortedSteps.length > 0 && (
        <div className="turn-meta-steps-list">
          {sortedSteps.map((step) => (
            <React.Fragment key={step.seq}>
              <div
                className="turn-meta-step-item"
                onClick={() => step.reasoning && toggleStep(step.seq)}
                style={{ cursor: step.reasoning ? 'pointer' : 'default' }}
              >
                {step.status === 'error' ? (
                  <AlertCircle size={11} style={{ color: '#ef4444', flexShrink: 0 }} />
                ) : (
                  <CheckCircle size={11} style={{ color: '#10b981', flexShrink: 0 }} />
                )}
                <span>{step.title}</span>
                {step.reasoning && (
                  <ChevronDown
                    size={9}
                    style={{
                      marginLeft: 'auto',
                      flexShrink: 0,
                      color: 'var(--text-muted)',
                      transform: expandedSteps.has(step.seq) ? 'rotate(180deg)' : 'none',
                      transition: 'transform 0.2s ease',
                    }}
                  />
                )}
              </div>
              {expandedSteps.has(step.seq) && step.reasoning && (
                <div className="turn-meta-step-reasoning">{step.reasoning}</div>
              )}
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// AskUserBlock (Claude-Style Checkpoint Clarification)
// ---------------------------------------------------------------------------

const AskUserBlock: React.FC<{
  askUser: AskUserEvent & { answeredAnswer?: string };
  onResponse: (turnId: string, answer: string, modelId: string) => void;
  modelId: string;
}> = ({ askUser, onResponse, modelId }) => {
  const [freeText, setFreeText] = useState('');
  const [submittedAnswer, setSubmittedAnswer] = useState<string | null>(
    askUser.answeredAnswer || null
  );

  useEffect(() => {
    if (askUser.answeredAnswer) {
      setSubmittedAnswer(askUser.answeredAnswer);
    }
  }, [askUser.answeredAnswer]);

  const submit = (answer: string) => {
    if (!answer.trim() || submittedAnswer) return;
    setSubmittedAnswer(answer);
    onResponse(askUser.turn_id, answer, modelId);
  };

  const isAnswered = Boolean(submittedAnswer);

  return (
    <div className={`claude-ask-container ${isAnswered ? 'is-answered' : ''}`}>
      <div className="claude-ask-header">
        <div className="claude-ask-badge">
          <HelpCircle size={13} className="claude-ask-icon" />
          <span>Clarification Required</span>
        </div>
        {askUser.timeout_seconds && !isAnswered ? (
          <span className="claude-ask-timer">
            Auto-skips in {askUser.timeout_seconds}s
          </span>
        ) : null}
      </div>

      <div className="claude-ask-question">
        {askUser.question}
      </div>

      {askUser.mode === 'mcq' && askUser.options ? (
        <div className="claude-choices-stack">
          {askUser.options.map((opt, i) => {
            const letter = String.fromCharCode(65 + i);
            const isChosen = submittedAnswer === opt;
            const isOther = isAnswered && !isChosen;

            return (
              <button
                key={i}
                type="button"
                className={`claude-choice-card ${isChosen ? 'selected' : ''} ${isOther ? 'dimmed' : ''}`}
                onClick={() => submit(opt)}
                disabled={isAnswered}
              >
                <span className="claude-choice-badge">{letter}</span>
                <span className="claude-choice-label">{opt}</span>
                <div className="claude-choice-indicator">
                  {isChosen ? (
                    <Check size={13} className="claude-check-icon" />
                  ) : (
                    <span className="claude-radio-dot" />
                  )}
                </div>
              </button>
            );
          })}

          <div className="claude-ask-footer">
            <button
              type="button"
              className={`claude-skip-btn ${submittedAnswer === 'skip' ? 'selected' : ''}`}
              onClick={() => submit('skip')}
              disabled={isAnswered}
            >
              {submittedAnswer === 'skip' ? (
                <>
                  <Check size={12} />
                  <span>Skipped — proceeding with default strategy</span>
                </>
              ) : (
                <>
                  <span>Skip and continue with defaults</span>
                  <ArrowRight size={12} />
                </>
              )}
            </button>
          </div>
        </div>
      ) : (
        <div className="claude-free-input-wrap">
          <div className="claude-input-row">
            <input
              className="claude-ask-input"
              placeholder="Type your clarification…"
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  submit(freeText);
                }
              }}
              disabled={isAnswered}
              autoFocus={!isAnswered}
            />
            <button
              type="button"
              className="claude-submit-btn"
              onClick={() => submit(freeText)}
              disabled={isAnswered || !freeText.trim()}
            >
              <span>Submit</span>
              <ArrowRight size={13} />
            </button>
          </div>
          <div className="claude-ask-footer">
            <button
              type="button"
              className={`claude-skip-btn ${submittedAnswer === 'skip' ? 'selected' : ''}`}
              onClick={() => submit('skip')}
              disabled={isAnswered}
            >
              {submittedAnswer === 'skip' ? (
                <>
                  <Check size={12} />
                  <span>Skipped — proceeding with default strategy</span>
                </>
              ) : (
                <>
                  <span>Skip and continue with defaults</span>
                  <ArrowRight size={12} />
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// ArtifactThumb
// ---------------------------------------------------------------------------

const ARTIFACT_ICONS: Record<string, string> = {
  chart: '📊',
  table: '📋',
  kpi: '💡',
};

const ArtifactThumb: React.FC<{
  artifact: Artifact;
  onClick: (a: Artifact) => void;
}> = ({ artifact, onClick }) => {
  const icon = ARTIFACT_ICONS[artifact.type] || '📄';
  const kpiKeys = Object.keys(artifact.key_numbers || {});
  const firstKpi = kpiKeys[0] ? artifact.key_numbers[kpiKeys[0]] : null;

  return (
    <button type="button" className="artifact-thumb" onClick={() => onClick(artifact)}>
      <div className="artifact-thumb-icon">{icon}</div>
      <div className="artifact-thumb-body">
        <div className="artifact-thumb-title">{artifact.title}</div>
        {artifact.note && <div className="artifact-thumb-note">{artifact.note}</div>}
        {artifact.type === 'kpi' && firstKpi !== null && (
          <div className="artifact-thumb-kpi-val">{String(firstKpi)}</div>
        )}
      </div>
    </button>
  );
};

// ---------------------------------------------------------------------------
// ChatArea
// ---------------------------------------------------------------------------

interface ChatAreaProps {
  currentProject: Project | null;
  /** The raw project ID from App state — null means no project selected */
  currentProjectId: string | null;
  messages: Message[];
  selectedModelId: string;
  isLoading: boolean;
  isDataLoaded?: boolean;
  pendingDatabaseName?: string;
  availableDatabasesForPicker?: Pick<DatabaseType, 'id' | 'name'>[];
  onSelectDatabase?: (dbId: string) => void;
  onSendSuggestedPrompt: (prompt: string) => void;
  availableModels?: BackendModel[];
  onOpenCredentials?: () => void;
  onAskUserResponse?: (turnId: string, answer: string, modelId: string) => void;
  /** Delete a turn (pass the assistant message id / turn_id) */
  onDeleteMessage?: (messageId: string) => void;
  onSelectArtifact?: (artifact: Artifact | null) => void;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  currentProject,
  currentProjectId,
  messages,
  selectedModelId,
  isLoading,
  isDataLoaded = false,
  pendingDatabaseName,
  availableDatabasesForPicker = [],
  onSelectDatabase,
  onSendSuggestedPrompt,
  availableModels = [],
  onOpenCredentials,
  onAskUserResponse,
  onDeleteMessage,
  onSelectArtifact,
}) => {
  const scrollEndRef = useRef<HTMLDivElement>(null);
  const [copiedCodeId, setCopiedCodeId] = useState<string | null>(null);
  const [dbPickerOpen, setDbPickerOpen] = useState(false);
  const [deletingMsgId, setDeletingMsgId] = useState<string | null>(null);
  /** Which user-message row's 3-dot menu is open (stores the paired assistant id) */
  const [openMenuMsgId, setOpenMenuMsgId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the 3-dot menu when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuMsgId(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // true when the user has selected a project (regardless of message count)
  const isInsideProject = currentProjectId !== null;
  const headerDbName =
    currentProject?.title && currentProject.title !== 'Untitled'
      ? currentProject.title
      : pendingDatabaseName ?? 'Select a Database';

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleCopyCode = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCodeId(id);
    setTimeout(() => setCopiedCodeId(null), 2000);
  };

  const handleDeleteMsg = async (msgId: string) => {
    if (!onDeleteMessage || deletingMsgId) return;
    // UUID validation — guard against local placeholder ids like "msg-assistant-XXXX"
    const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    // Also accept historical prefixed ids like "hist-asst-{uuid}"
    const cleanId = msgId.startsWith('hist-asst-') ? msgId.replace('hist-asst-', '') : msgId;
    if (!UUID_RE.test(cleanId)) {
      console.warn('[ChatArea] Cannot delete — message id is not a UUID yet:', msgId,
        '\nThe ACK frame may not have arrived yet. Please wait for the response to complete before deleting.');
      return;
    }
    setOpenMenuMsgId(null);
    setDeletingMsgId(cleanId);
    try {
      await onDeleteMessage(cleanId);
    } finally {
      setDeletingMsgId(null);
    }
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
      {/* Header */}
      <header className="chat-header">
        <div className="chat-header-title-box" style={{ position: 'relative' }}>
          {!isInsideProject && onSelectDatabase ? (
            <button
              type="button"
              className="chat-header-project"
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              onClick={() => setDbPickerOpen((v) => !v)}
              title="Change active database"
            >
              <Database size={16} style={{ color: 'var(--accent-cyan)' }} />
              <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{headerDbName}</span>
              <ChevronDown size={13} style={{ color: 'var(--text-muted)', marginLeft: '2px' }} />
            </button>
          ) : (
            <div className="chat-header-project">
              <Database size={16} style={{ color: 'var(--accent-cyan)' }} />
              <span>{currentProject?.title || headerDbName}</span>
            </div>
          )}
          <span className="header-slash">/</span>
          <span className="chat-header-session">Data Analytics Chat</span>

          {dbPickerOpen && availableDatabasesForPicker.length > 0 && (
            <div
              style={{
                position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 200,
                background: '#111827', border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: '8px', padding: '6px', minWidth: '220px',
                boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
              }}
            >
              {availableDatabasesForPicker.map((db) => (
                <button
                  key={db.id}
                  type="button"
                  onClick={() => { onSelectDatabase?.(db.id); setDbPickerOpen(false); }}
                  style={{
                    width: '100%', padding: '8px 10px', borderRadius: '6px', textAlign: 'left',
                    background: db.name === headerDbName ? 'rgba(99,102,241,0.15)' : 'transparent',
                    color: 'var(--text-secondary)', fontSize: '13px',
                    display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer',
                    border: 'none',
                  }}
                >
                  <Database size={13} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
                  <span>{db.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      {/* Messages */}
      <div className="chat-messages-container">
        {messages.length === 0 ? (
          <div className="empty-state-wrap">
            <div className="empty-logo-glow">
              <LogoEmblem size={44} />
            </div>
            <h1 className="empty-heading">What decision are we analyzing today?</h1>
            <p className="empty-subtext">
              Welcome to <span className="kannada-accent-pill">Nirnaya</span>. Ask complex
              business questions, inspect uploaded data files, or simulate strategic decisions
              across <strong style={{ color: '#ffffff' }}>{currentProject?.title || 'your datasets'}</strong>.
            </p>
            {isDataLoaded && availableModels.length === 0 && (
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: '12px',
                  background: 'rgba(245, 158, 11, 0.08)',
                  border: '1px solid rgba(245, 158, 11, 0.25)',
                  borderRadius: '10px', padding: '10px 16px',
                  margin: '0 auto 20px', maxWidth: '560px',
                  fontSize: '12.5px', color: '#fbbf24',
                }}
              >
                <KeyRound size={18} style={{ flexShrink: 0, color: '#f59e0b' }} />
                <span style={{ flex: 1, textAlign: 'left', lineHeight: 1.4, color: '#e2e8f0' }}>
                  No AI models configured yet. Add your Anthropic or OpenAI API key to start querying your data.
                </span>
                {onOpenCredentials && (
                  <button
                    type="button"
                    onClick={onOpenCredentials}
                    style={{
                      padding: '6px 12px', background: '#4f46e5', color: '#ffffff',
                      borderRadius: '6px', fontSize: '11.5px', fontWeight: 600,
                      cursor: 'pointer', whiteSpace: 'nowrap', border: 'none',
                    }}
                  >
                    Add API Key
                  </button>
                )}
              </div>
            )}
            <div className="starter-prompts-grid">
              {starterPrompts.map((item, idx) => (
                <button
                  key={idx}
                  type="button"
                  className="prompt-card-btn"
                  onClick={() => onSendSuggestedPrompt(item.prompt)}
                >
                  <div className="prompt-card-header"><span>{item.title}</span></div>
                  <div className="prompt-card-desc">{item.desc}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isLast = idx === messages.length - 1;
            const isUser = msg.role === 'user';

            if (isUser) {
              // Find the paired assistant message (next message after this user one)
              const nextMsg = messages[idx + 1];
              const pairedAssistantId = nextMsg?.role === 'assistant' ? nextMsg.id : null;
              const isMenuOpen = openMenuMsgId === pairedAssistantId;
              const isThisDeleting = pairedAssistantId ? deletingMsgId === pairedAssistantId : false;

              return (
                <div key={msg.id} className="message-row message-row-user" style={{ alignItems: 'flex-start', gap: '8px' }}>
                  {/* 3-dot menu — sits to the LEFT of the bubble (before it in RTL layout), outside */}
                  {onDeleteMessage && pairedAssistantId && (
                    <div
                      ref={isMenuOpen ? menuRef : undefined}
                      style={{ position: 'relative', flexShrink: 0, alignSelf: 'flex-start', marginTop: '8px' }}
                    >
                      <button
                        type="button"
                        title="Message options"
                        onClick={() => setOpenMenuMsgId(isMenuOpen ? null : pairedAssistantId)}
                        style={{
                          background: 'none', border: 'none', cursor: 'pointer',
                          color: 'var(--text-muted)', padding: '4px', borderRadius: '5px',
                          display: 'flex', alignItems: 'center',
                          opacity: isMenuOpen ? 1 : 0.5,
                          transition: 'opacity 0.15s ease',
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                        onMouseLeave={(e) => (e.currentTarget.style.opacity = isMenuOpen ? '1' : '0.5')}
                      >
                        <MoreVertical size={15} />
                      </button>
                      {/* Dropdown */}
                      {isMenuOpen && (
                        <div
                          style={{
                            position: 'absolute', right: 0, top: '28px',
                            background: 'var(--bg-secondary, #1e2a3a)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: '8px', boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                            minWidth: '160px', zIndex: 100, overflow: 'hidden',
                            padding: '4px',
                          }}
                        >
                          <button
                            type="button"
                            onClick={() => handleDeleteMsg(pairedAssistantId)}
                            disabled={isThisDeleting}
                            style={{
                              display: 'flex', alignItems: 'center', gap: '8px',
                              width: '100%', padding: '8px 10px',
                              background: 'none', border: 'none',
                              borderRadius: '6px',
                              color: '#f87171', cursor: isThisDeleting ? 'not-allowed' : 'pointer',
                              fontSize: '12.5px', fontWeight: 500,
                              transition: 'background 0.15s ease',
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(239,68,68,0.12)')}
                            onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}
                          >
                            <Trash2 size={13} />
                            <span>{isThisDeleting ? 'Deleting…' : 'Delete this turn'}</span>
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="message-bubble-user-wrap" style={{ flex: 1 }}>
                    <div className="user-bubble">
                      <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{msg.content}</p>
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

            // Assistant message — wrap in Fragment so TurnMetaRow is a sibling
            const hasContent = Boolean(msg.content);
            const hasSteps = Boolean(msg.steps && msg.steps.length > 0);
            const isThisLoading = isLoading && isLast;
            const freshArtifacts = (msg.artifacts || []).filter((a) => a.status === 'fresh');
            const followUps = msg.followUpQuestions || [];

            // During streaming: TurnMetaRow handles the live step display.
            // Show assistant bubble when we have content, an ask_user checkpoint, or completed steps.
            const showAssistantBubble =
              hasContent ||
              Boolean(msg.askUser) ||
              (!isThisLoading && (hasSteps || freshArtifacts.length > 0));

            return (
              <React.Fragment key={msg.id}>
                {/* TurnMetaRow sits BETWEEN user bubble and assistant bubble */}
                <TurnMetaRow msg={msg} isLast={isLast} isLoading={isLoading} />

                {/* Assistant bubble — rendered for askUser checkpoint or actual content */}
                {showAssistantBubble && (
                  <div className="message-row message-row-assistant">
                    <div className="message-bubble-assistant-wrap">
                      <div className="assistant-avatar" title="Nirnaya Analytics Agent">
                        <LogoEmblem size={22} />
                      </div>
                      <div className="assistant-content-box">
                        <div className="assistant-bubble">
                          {/* Claude-style Checkpoint Clarification block */}
                          {msg.askUser && onAskUserResponse && (
                            <AskUserBlock
                              askUser={msg.askUser}
                              onResponse={onAskUserResponse}
                              modelId={selectedModelId}
                            />
                          )}

                          {/* Final answer */}
                          {hasContent && <MarkdownContent text={msg.content} />}

                          {/* Legacy: SQL query block */}
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
                                    <><Check size={12} style={{ color: 'var(--accent-emerald)' }} />Copied</>
                                  ) : (
                                    <><Copy size={12} />Copy SQL</>
                                  )}
                                </button>
                              </div>
                              <pre className="code-block-content"><code>{msg.sqlQuery}</code></pre>
                            </div>
                          )}

                          {/* Legacy: Data table */}
                          {msg.tableData && (
                            <div className="data-table-wrapper">
                              {msg.tableData.title && (
                                <div className="data-table-title">
                                  <TableIcon size={14} /><span>{msg.tableData.title}</span>
                                </div>
                              )}
                              <div className="data-table-scroll">
                                <table className="analytics-table">
                                  <thead><tr>{msg.tableData.headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
                                  <tbody>
                                    {msg.tableData.rows.map((row, rIdx) => (
                                      <tr key={rIdx}>{row.map((cell, cIdx) => <td key={cIdx}>{cell}</td>)}</tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          )}

                          {/* Legacy: Insights */}
                          {msg.insights && msg.insights.length > 0 && (
                            <div>
                              <div className="analytics-section-title">
                                <TrendingUp size={14} /><span>Decision Insights</span>
                              </div>
                              <ul className="analytics-insights-list">
                                {msg.insights.map((insight, insIdx) => (
                                  <li key={insIdx} className="analytics-insight-item">
                                    <span className="insight-bullet" />
                                    <span>{insight}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {/* Legacy: Suggestions */}
                          {msg.suggestions && msg.suggestions.length > 0 && (
                            <div style={{ marginTop: '14px' }}>
                              <div style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px' }}>
                                Suggested Follow-Ups:
                              </div>
                              <div className="assistant-suggestions">
                                {msg.suggestions.map((sug, sIdx) => (
                                  <button key={sIdx} type="button" className="suggestion-pill-btn" onClick={() => onSendSuggestedPrompt(sug)}>
                                    <span>{sug}</span><ArrowRight size={11} />
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Artifact thumbnails */}
                        {freshArtifacts.length > 0 && (
                          <div className="artifact-thumbs-row">
                            {freshArtifacts.map((a) => (
                              <ArtifactThumb key={a.artifact_id} artifact={a} onClick={() => onSelectArtifact?.(a)} />
                            ))}
                          </div>
                        )}

                        {/* Follow-up questions */}
                        {followUps.length > 0 && isLast && (
                          <div className="followup-container">
                            <div className="followup-header">
                              <div className="followup-header-left">
                                <Sparkles size={13} className="followup-sparkle-icon" />
                                <span className="followup-title">Suggested Next Questions</span>
                              </div>
                              <span className="followup-hint">Click to ask</span>
                            </div>
                            <div className="followup-grid">
                              {followUps.slice(0, 3).map((q, qi) => (
                                <button
                                  key={qi}
                                  type="button"
                                  className="followup-card"
                                  onClick={() => onSendSuggestedPrompt(q)}
                                >
                                  <span className="followup-chip">0{qi + 1}</span>
                                  <span className="followup-text">{q}</span>
                                  <ArrowUpRight size={13} className="followup-arrow" />
                                </button>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="assistant-meta-left">
                          <Clock size={11} />
                          <span>{msg.timestamp}</span>
                          <span>• Nirnaya Agent</span>
                          {msg.model && <span className="assistant-model-tag">{msg.model}</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </React.Fragment>
            );
          })
        )}
        <div ref={scrollEndRef} />
      </div>

    </div>
  );
};
