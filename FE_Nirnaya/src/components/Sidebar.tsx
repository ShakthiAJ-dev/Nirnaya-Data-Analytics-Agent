import React, { useState } from 'react';
import {
  Plus,
  MessageSquare,
  Key,
  Trash2,
  Database,
  Lock,
  Upload,
  Layers,
  ChevronDown,
  ChevronRight,
  Table as TableIcon,
  Columns,
} from 'lucide-react';
import { NirnayaLogo } from './Logo';
import type { Project, Database as DatabaseType, LLMCredentials, DatasetMetadata } from '../types';
import { DEFAULT_DEMO_DATASETS } from '../constants/demoData';

interface SidebarProps {
  currentProjectId: string | null;
  projects: Project[];
  databases: DatabaseType[];
  credentials: LLMCredentials;
  onSelectProject: (projectId: string) => void;
  onNewChat: () => void;
  onDeleteProject: (projectId: string, e: React.MouseEvent) => void;
  onNewDatabase: () => void;
  onDeleteDatabase: (databaseId: string, e: React.MouseEvent) => void;
  onUploadToDatabase: (databaseId: string) => void;
  onOpenCredentials: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentProjectId,
  projects,
  databases,
  credentials,
  onSelectProject,
  onNewChat,
  onDeleteProject,
  onNewDatabase,
  onDeleteDatabase,
  onUploadToDatabase,
  onOpenCredentials,
}) => {
  const [dbHovered, setDbHovered] = useState<string | null>(null);
  const [isDemoTablesOpen, setIsDemoTablesOpen] = useState(true);
  const [expandedTable, setExpandedTable] = useState<string | null>(null);

  const hasCredentials = Boolean(
    credentials.anthropicApiKey || credentials.openaiApiKey || credentials.geminiApiKey
  );

  const today = new Date().toISOString().split('T')[0];
  const todayProjects = projects.filter((p) => !p.is_demo && !p.isDemo && p.created_at?.startsWith(today));
  const earlierProjects = projects.filter((p) => !p.is_demo && !p.isDemo && !p.created_at?.startsWith(today));

  const getDatabaseForProject = (project: Project) => {
    if (!project.database_id) return null;
    return databases.find((d) => d.id === project.database_id);
  };

  return (
    <aside className="nirnaya-sidebar">
      {/* Brand Header */}
      <div className="sidebar-header">
        <NirnayaLogo size={36} />
      </div>

      {/* ── Projects Section ───────────────────────────────────── */}
      <div className="sidebar-section-label">
        <span>Projects</span>
      </div>

      {/* New Chat Button */}
      <div className="sidebar-action-wrap">
        <button type="button" className="btn-new-chat" onClick={onNewChat} id="btn-new-chat">
          <Plus size={16} strokeWidth={2.5} />
          <span>New Chat</span>
          <span className="kbd-shortcut">Ctrl+N</span>
        </button>
      </div>

      {/* Project History */}
      <div className="sidebar-history-section">
        {/* ── Demo Project Card with Expandable 9 Tables ──────────────── */}
        {(() => {
          const demoProject = projects.find((p) => p.is_demo || p.isDemo || p.id === 'demo-project');
          if (!demoProject) return null;
          const isActive = demoProject.id === currentProjectId;
          const tablesList: DatasetMetadata[] =
            (demoProject.datasets && demoProject.datasets.length > 0)
              ? demoProject.datasets
              : DEFAULT_DEMO_DATASETS;

          return (
            <div style={{ padding: '0 8px', marginBottom: '12px' }}>
              <div
                style={{
                  borderRadius: '10px',
                  background: isActive ? 'rgba(99,102,241,0.18)' : 'rgba(255,255,255,0.03)',
                  border: isActive ? '1px solid rgba(99,102,241,0.4)' : '1px solid rgba(255,255,255,0.06)',
                  overflow: 'hidden',
                  transition: 'all 0.15s ease',
                }}
              >
                {/* Demo Card Header */}
                <div
                  onClick={() => onSelectProject(demoProject.id)}
                  style={{
                    padding: '10px 12px',
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '14px' }}>✨</span>
                    <span style={{ fontWeight: 600, fontSize: '12.5px', color: isActive ? '#c7d2fe' : 'var(--text-primary)' }}>
                      Music E-commerce (Demo)
                    </span>
                    <span style={{
                      marginLeft: 'auto',
                      fontSize: '9px',
                      background: isActive ? 'var(--accent-purple)' : 'rgba(99,102,241,0.3)',
                      color: 'white',
                      padding: '2px 6px',
                      borderRadius: '10px',
                      fontWeight: 600,
                      textTransform: 'uppercase',
                    }}>
                      {isActive ? 'Active' : 'Free'}
                    </span>
                  </div>
                  <p style={{ fontSize: '10.5px', color: 'var(--text-muted)', margin: '2px 0 0', lineHeight: 1.3 }}>
                    9 Datasets/Tables · No API Key required
                  </p>
                </div>

                {/* Demo Metadata Accordion Toggle */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsDemoTablesOpen((prev) => !prev);
                  }}
                  style={{
                    width: '100%',
                    padding: '6px 12px',
                    background: 'rgba(99,102,241,0.08)',
                    borderTop: '1px solid rgba(99,102,241,0.15)',
                    borderBottom: isDemoTablesOpen ? '1px solid rgba(99,102,241,0.15)' : 'none',
                    borderLeft: 'none',
                    borderRight: 'none',
                    color: '#a5b4fc',
                    fontSize: '11px',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <TableIcon size={12} />
                    <span>Demo Tables ({tablesList.length})</span>
                  </span>
                  {isDemoTablesOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>

                {/* Expandable 9 Tables List */}
                {isDemoTablesOpen && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', padding: '6px 8px' }}>
                    {tablesList.map((t) => {
                      const isExpanded = expandedTable === t.tableName;
                      return (
                        <div
                          key={t.tableName}
                          style={{
                            background: isExpanded ? 'rgba(99,102,241,0.12)' : 'rgba(255,255,255,0.02)',
                            borderRadius: '6px',
                            padding: '6px 8px',
                            border: '1px solid rgba(255,255,255,0.04)',
                            transition: 'background 0.15s ease',
                          }}
                        >
                          <div
                            onClick={() => setExpandedTable(isExpanded ? null : t.tableName)}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              cursor: 'pointer',
                            }}
                          >
                            <span style={{
                              fontSize: '11.5px',
                              fontWeight: 600,
                              color: 'var(--text-primary)',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '5px',
                            }}>
                              <TableIcon size={11} style={{ color: 'var(--accent-cyan)' }} />
                              {t.tableName}
                            </span>
                            <span style={{
                              fontSize: '9.5px',
                              padding: '1px 5px',
                              borderRadius: '4px',
                              background: 'rgba(6,182,212,0.12)',
                              color: 'var(--accent-cyan)',
                              fontWeight: 500,
                            }}>
                              {t.rows.toLocaleString()} rows
                            </span>
                          </div>

                          <p style={{
                            fontSize: '10px',
                            color: 'var(--text-muted)',
                            margin: '3px 0 0',
                            lineHeight: 1.35,
                          }}>
                            {t.description}
                          </p>

                          {/* Expanded Table Column Metadata */}
                          {isExpanded && t.columns && t.columns.length > 0 && (
                            <div style={{
                              marginTop: '6px',
                              paddingTop: '6px',
                              borderTop: '1px dashed rgba(255,255,255,0.08)',
                            }}>
                              <div style={{
                                fontSize: '9.5px',
                                color: '#a5b4fc',
                                fontWeight: 600,
                                marginBottom: '4px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                              }}>
                                <Columns size={10} />
                                <span>Columns ({t.columns.length}):</span>
                              </div>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px' }}>
                                {t.columns.map((col) => (
                                  <span
                                    key={col}
                                    style={{
                                      fontSize: '9px',
                                      padding: '1px 4px',
                                      borderRadius: '3px',
                                      background: 'rgba(255,255,255,0.05)',
                                      color: 'var(--text-secondary)',
                                      fontFamily: 'monospace',
                                    }}
                                  >
                                    {col}
                                  </span>
                                ))}
                              </div>
                              {t.useCase && (
                                <p style={{ fontSize: '9.5px', color: '#34d399', margin: '5px 0 0', fontStyle: 'italic' }}>
                                  💡 {t.useCase}
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        {todayProjects.length > 0 && (
          <div>
            <div className="history-group-title">Today</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {todayProjects.map((project) => {
                const db = getDatabaseForProject(project);
                return (
                  <button
                    key={project.id}
                    type="button"
                    className={`history-item-btn ${project.id === currentProjectId ? 'active' : ''}`}
                    onClick={() => onSelectProject(project.id)}
                  >
                    <MessageSquare size={14} style={{ flexShrink: 0, opacity: 0.7 }} />
                    <span className="history-item-title">{project.title || 'Untitled'}</span>
                    {db && (
                      <span style={{
                        fontSize: '10px', padding: '1px 5px', borderRadius: '4px',
                        background: 'rgba(6,182,212,0.12)', color: 'var(--accent-cyan)',
                        flexShrink: 0, maxWidth: '60px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {db.name}
                      </span>
                    )}
                    <span
                      className="history-delete-btn"
                      title="Delete Chat"
                      onClick={(e) => onDeleteProject(project.id, e)}
                    >
                      <Trash2 size={13} />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {earlierProjects.length > 0 && (
          <div>
            <div className="history-group-title">Previous 7 Days</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {earlierProjects.map((project) => {
                const db = getDatabaseForProject(project);
                return (
                  <button
                    key={project.id}
                    type="button"
                    className={`history-item-btn ${project.id === currentProjectId ? 'active' : ''}`}
                    onClick={() => onSelectProject(project.id)}
                  >
                    <MessageSquare size={14} style={{ flexShrink: 0, opacity: 0.7 }} />
                    <span className="history-item-title">{project.title || 'Untitled'}</span>
                    {db && (
                      <span style={{
                        fontSize: '10px', padding: '1px 5px', borderRadius: '4px',
                        background: 'rgba(6,182,212,0.12)', color: 'var(--accent-cyan)',
                        flexShrink: 0, maxWidth: '60px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {db.name}
                      </span>
                    )}
                    <span
                      className="history-delete-btn"
                      title="Delete Chat"
                      onClick={(e) => onDeleteProject(project.id, e)}
                    >
                      <Trash2 size={13} />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {projects.length === 0 && (
          <div style={{
            padding: '16px 12px', textAlign: 'center', color: 'var(--text-muted)',
            fontSize: '12.5px', display: 'flex', flexDirection: 'column',
            alignItems: 'center', gap: '8px',
          }}>
            <Layers size={22} style={{ opacity: 0.3 }} />
            <span>No conversations yet.</span>
            <span style={{ fontSize: '11px' }}>Click "New Chat" to start analyzing.</span>
          </div>
        )}
      </div>

      {/* ── Databases Section ──────────────────────────────────── */}
      <div className="sidebar-section-label" style={{ marginTop: '4px' }}>
        <span>Databases</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', padding: '0 8px' }}>
        {databases.map((db) => (
          <div
            key={db.id}
            className="db-list-item"
            onMouseEnter={() => setDbHovered(db.id)}
            onMouseLeave={() => setDbHovered(null)}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0 }}>
              {db.is_demo
                ? <Lock size={13} style={{ color: '#818cf8', flexShrink: 0 }} />
                : <Database size={13} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
              }
              <span style={{
                fontSize: '12.5px', color: 'var(--text-secondary)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {db.name}
              </span>
              {db.is_demo && (
                <span style={{
                  fontSize: '9.5px', padding: '1px 5px', borderRadius: '4px',
                  background: 'rgba(99,102,241,0.15)', color: '#a5b4fc', flexShrink: 0,
                }}>
                  Demo
                </span>
              )}
            </div>

            {/* Actions — shown on hover */}
            {dbHovered === db.id && (
              <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                {!db.is_demo && (
                  <>
                    <button
                      type="button"
                      title="Upload file to this database"
                      onClick={() => onUploadToDatabase(db.id)}
                      style={{
                        padding: '3px 5px', borderRadius: '5px', cursor: 'pointer',
                        background: 'rgba(6,182,212,0.1)', border: 'none',
                        color: 'var(--accent-cyan)',
                      }}
                    >
                      <Upload size={11} />
                    </button>
                    <button
                      type="button"
                      title="Delete database"
                      onClick={(e) => onDeleteDatabase(db.id, e)}
                      style={{
                        padding: '3px 5px', borderRadius: '5px', cursor: 'pointer',
                        background: 'rgba(239,68,68,0.1)', border: 'none', color: '#f87171',
                      }}
                    >
                      <Trash2 size={11} />
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        ))}

        {/* + New Database */}
        <button
          type="button"
          className="btn-new-database"
          onClick={onNewDatabase}
          id="btn-new-database"
        >
          <Plus size={13} strokeWidth={2.5} />
          <span>New Database</span>
        </button>
      </div>

      {/* Footer — LLM Credentials */}
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
