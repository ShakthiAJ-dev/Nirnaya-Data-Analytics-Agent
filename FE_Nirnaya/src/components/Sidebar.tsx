import React, { useState } from 'react';
import {
  Plus,
  MessageSquare,
  Key,
  FolderGit2,
  Trash2,
  ChevronDown,
  Layers,
} from 'lucide-react';
import { NirnayaLogo } from './Logo';
import type { ChatSession, Project, LLMCredentials } from '../types';

interface SidebarProps {
  currentSessionId: string | null;
  sessions: ChatSession[];
  currentProject: Project;
  projects: Project[];
  credentials: LLMCredentials;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string, e: React.MouseEvent) => void;
  onSelectProject: (projectId: string) => void;
  onOpenCredentials: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentSessionId,
  sessions,
  currentProject,
  projects,
  credentials,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onSelectProject,
  onOpenCredentials,
}) => {
  const [showProjectDropdown, setShowProjectDropdown] = useState(false);

  // Group sessions by Today / Earlier
  const today = new Date().toISOString().split('T')[0];
  const todaySessions = sessions.filter((s) => s.createdAt.startsWith(today));
  const earlierSessions = sessions.filter((s) => !s.createdAt.startsWith(today));

  const hasCredentials = Boolean(
    credentials.anthropicApiKey || credentials.openaiApiKey || credentials.geminiApiKey
  );

  return (
    <aside className="nirnaya-sidebar">
      {/* Brand Header */}
      <div className="sidebar-header">
        <NirnayaLogo size={36} />
      </div>

      {/* Project Context Box (Project based Q&A) */}
      <div className="project-context-box">
        <div className="project-box-label">
          <span>Active Project</span>
          <span style={{ fontSize: '10.5px', color: 'var(--accent-cyan)' }}>
            {currentProject.datasetsCount} Datasets
          </span>
        </div>

        <div style={{ position: 'relative' }}>
          <button
            type="button"
            className="project-select-btn"
            onClick={() => setShowProjectDropdown(!showProjectDropdown)}
            title="Switch analytics project"
          >
            <div className="project-item-content">
              <span className="project-badge-dot"></span>
              <span className="project-title-text">{currentProject.name}</span>
            </div>
            <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} />
          </button>

          {showProjectDropdown && (
            <div
              style={{
                position: 'absolute',
                top: 'calc(100% + 4px)',
                left: 0,
                right: 0,
                background: '#111827',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                borderRadius: '8px',
                padding: '6px',
                boxShadow: 'var(--shadow-lg)',
                zIndex: 40,
                display: 'flex',
                flexDirection: 'column',
                gap: '4px',
              }}
            >
              <div
                style={{
                  fontSize: '10.5px',
                  color: 'var(--text-muted)',
                  padding: '4px 8px',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                }}
              >
                Switch Project
              </div>
              {projects.map((proj) => (
                <button
                  key={proj.id}
                  type="button"
                  style={{
                    padding: '8px 10px',
                    borderRadius: '6px',
                    textAlign: 'left',
                    background: proj.id === currentProject.id ? 'rgba(99, 102, 241, 0.18)' : 'transparent',
                    color: proj.id === currentProject.id ? '#c7d2fe' : 'var(--text-secondary)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    fontSize: '12.5px',
                  }}
                  onClick={() => {
                    onSelectProject(proj.id);
                    setShowProjectDropdown(false);
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <FolderGit2 size={14} style={{ color: 'var(--accent-cyan)' }} />
                    <span style={{ fontWeight: proj.id === currentProject.id ? 600 : 400 }}>{proj.name}</span>
                  </div>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                    {proj.datasetsCount} files
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* New Chat Button */}
      <div className="sidebar-action-wrap">
        <button type="button" className="btn-new-chat" onClick={onNewChat} id="btn-new-chat">
          <Plus size={16} strokeWidth={2.5} />
          <span>New Chat</span>
          <span className="kbd-shortcut">Ctrl+N</span>
        </button>
      </div>

      {/* Chat History List */}
      <div className="sidebar-history-section">
        {todaySessions.length > 0 && (
          <div>
            <div className="history-group-title">Today</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {todaySessions.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  className={`history-item-btn ${session.id === currentSessionId ? 'active' : ''}`}
                  onClick={() => onSelectSession(session.id)}
                >
                  <MessageSquare size={14} style={{ flexShrink: 0, opacity: 0.7 }} />
                  <span className="history-item-title">{session.title}</span>
                  <span
                    className="history-delete-btn"
                    title="Delete Chat"
                    onClick={(e) => onDeleteSession(session.id, e)}
                  >
                    <Trash2 size={13} />
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {earlierSessions.length > 0 && (
          <div>
            <div className="history-group-title">Previous 7 Days</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {earlierSessions.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  className={`history-item-btn ${session.id === currentSessionId ? 'active' : ''}`}
                  onClick={() => onSelectSession(session.id)}
                >
                  <MessageSquare size={14} style={{ flexShrink: 0, opacity: 0.7 }} />
                  <span className="history-item-title">{session.title}</span>
                  <span
                    className="history-delete-btn"
                    title="Delete Chat"
                    onClick={(e) => onDeleteSession(session.id, e)}
                  >
                    <Trash2 size={13} />
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {sessions.length === 0 && (
          <div
            style={{
              padding: '24px 12px',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '12.5px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <Layers size={22} style={{ opacity: 0.3 }} />
            <span>No conversations yet.</span>
            <span style={{ fontSize: '11px' }}>Click "New Chat" to start analyzing.</span>
          </div>
        )}
      </div>

      {/* Left-hand side LLM Credentials Section */}
      <div className="sidebar-footer">
        <button
          type="button"
          className="credentials-card-btn"
          onClick={onOpenCredentials}
          id="btn-llm-credentials"
          title="Configure LLM API credentials"
        >
          <div className="cred-left">
            <div className="cred-icon-wrap">
              <Key size={15} />
            </div>
            <div className="cred-text">
              <span className="cred-name">LLM Credentials</span>
              <span className="cred-status-tag">
                {hasCredentials ? 'API Keys Active' : 'Setup Required'}
              </span>
            </div>
          </div>

          <div>
            {hasCredentials ? (
              <span className="badge-configured">Configured</span>
            ) : (
              <span className="badge-missing">Add Key</span>
            )}
          </div>
        </button>
      </div>
    </aside>
  );
};
