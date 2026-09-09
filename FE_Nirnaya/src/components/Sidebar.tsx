import React, { useState } from 'react';
import {
  Plus,
  MessageSquare,
  Key,
  Trash2,
  Database,
  Upload,
  Layers,
  Lock,
  Eye,
} from 'lucide-react';
import { NirnayaLogo } from './Logo';
import { DatabaseTablesModal } from './DatabaseTablesModal';
import type { Project, Database as DatabaseType, LLMCredentials } from '../types';

interface SidebarProps {
  currentProjectId: string | null;
  projects: Project[];
  databases: DatabaseType[];
  credentials: LLMCredentials;
  pendingDatabaseId?: string;
  onSelectProject: (projectId: string) => void;
  onSelectDatabase?: (dbId: string) => void;
  onNewChat: () => void;
  onDeleteProject: (projectId: string, e: React.MouseEvent) => void;
  onNewDatabase: () => void;
  onDeleteDatabase: (databaseId: string, e: React.MouseEvent) => void;
  onUploadToDatabase: (databaseId: string) => void;
  onOpenCredentials: () => void;
}

interface ModalState {
  databaseId: string;
  databaseName: string;
  isDemo: boolean;
  metadata: any;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentProjectId,
  projects,
  databases,
  credentials,
  pendingDatabaseId,
  onSelectProject,
  onSelectDatabase,
  onNewChat,
  onDeleteProject,
  onNewDatabase,
  onDeleteDatabase,
  onUploadToDatabase,
  onOpenCredentials,
}) => {
  const [dbHovered, setDbHovered] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState | null>(null);

  const hasCredentials = Boolean(
    credentials.anthropicApiKey || credentials.openaiApiKey || credentials.geminiApiKey
  );

  // Demo project (for building the demo database card)
  const demoProject = projects.find((p) => p.is_demo || p.isDemo || p.id === 'demo-project');
  const demoRawMeta = demoProject?.raw_metadata ?? null;
  const demoTableCount = demoRawMeta?.tables
    ? Object.keys(demoRawMeta.tables).length
    : (demoProject?.datasets?.length ?? 0);

  // User projects only (non-demo, real chat history)
  const today = new Date().toISOString().split('T')[0];
  const userProjects = projects.filter((p) => !p.is_demo && !p.isDemo && p.id !== 'demo-project');
  const todayProjects = userProjects.filter((p) => p.created_at?.startsWith(today));
  const earlierProjects = userProjects.filter((p) => !p.created_at?.startsWith(today));
  const hasUserProjects = userProjects.length > 0;

  const getDatabaseForProject = (project: Project) => {
    if (!project.database_id) return null;
    return databases.find((d) => d.id === project.database_id);
  };

  const tableCountForDb = (db: DatabaseType) =>
    db.metadata?.tables ? Object.keys(db.metadata.tables).length : 0;

  const openModal = (e: React.MouseEvent, opts: ModalState) => {
    e.stopPropagation();
    setModal(opts);
  };

  return (
    <aside className="nirnaya-sidebar">
      {/* Brand Header */}
      <div className="sidebar-header">
        <NirnayaLogo size={36} />
      </div>

      {/* ── Databases Section ─────────────────────────────────────── */}
      <div className="sidebar-section-label">
        <span>Databases</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', padding: '0 8px' }}>
        {/* Demo database card */}
        {demoProject && (
          <DbCard
            name="Music E-commerce (Demo)"
            tableCount={demoTableCount}
            isDemo={true}
            isActive={pendingDatabaseId === 'demo-database'}
            hovered={dbHovered === 'demo-database'}
            onMouseEnter={() => setDbHovered('demo-database')}
            onMouseLeave={() => setDbHovered(null)}
            onSelect={() => onSelectDatabase?.('demo-database')}
            onViewTables={(e) => openModal(e, {
              databaseId: 'demo-database',
              databaseName: 'Music E-commerce (Demo)',
              isDemo: true,
              metadata: demoRawMeta,
            })}
          />
        )}

        {/* User databases */}
        {databases.filter((d) => !d.is_demo).map((db) => (
          <DbCard
            key={db.id}
            name={db.name}
            tableCount={tableCountForDb(db)}
            isDemo={false}
            isActive={pendingDatabaseId === db.id}
            hovered={dbHovered === db.id}
            onMouseEnter={() => setDbHovered(db.id)}
            onMouseLeave={() => setDbHovered(null)}
            onSelect={() => onSelectDatabase?.(db.id)}
            onViewTables={(e) => openModal(e, {
              databaseId: db.id,
              databaseName: db.name,
              isDemo: false,
              metadata: db.metadata,
            })}
            onUpload={() => onUploadToDatabase(db.id)}
            onDelete={(e) => onDeleteDatabase(db.id, e)}
          />
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

      {/* ── Projects Section ───────────────────────────────────────── */}
      <div className="sidebar-section-label" style={{ marginTop: '8px' }}>
        <span>Projects</span>
      </div>

      {/* New Chat — only visible once user has created at least one project */}
      {hasUserProjects && (
        <div className="sidebar-action-wrap">
          <button type="button" className="btn-new-chat" onClick={onNewChat} id="btn-new-chat">
            <Plus size={16} strokeWidth={2.5} />
            <span>New Chat</span>
            <span className="kbd-shortcut">Ctrl+N</span>
          </button>
        </div>
      )}

      {/* Project History */}
      <div className="sidebar-history-section">
        {todayProjects.length > 0 && (
          <div>
            <div className="history-group-title">Today</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {todayProjects.map((project) => {
                const db = getDatabaseForProject(project);
                return (
                  <ProjectRow
                    key={project.id}
                    project={project}
                    db={db}
                    isActive={project.id === currentProjectId}
                    onSelect={() => onSelectProject(project.id)}
                    onDelete={(e) => onDeleteProject(project.id, e)}
                  />
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
                  <ProjectRow
                    key={project.id}
                    project={project}
                    db={db}
                    isActive={project.id === currentProjectId}
                    onSelect={() => onSelectProject(project.id)}
                    onDelete={(e) => onDeleteProject(project.id, e)}
                  />
                );
              })}
            </div>
          </div>
        )}

        {!hasUserProjects && (
          <div style={{
            padding: '16px 12px', textAlign: 'center', color: 'var(--text-muted)',
            fontSize: '12.5px', display: 'flex', flexDirection: 'column',
            alignItems: 'center', gap: '8px',
          }}>
            <Layers size={22} style={{ opacity: 0.3 }} />
            <span>No conversations yet.</span>
            <span style={{ fontSize: '11px' }}>Type a question below to start analyzing.</span>
          </div>
        )}
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

      {/* Database Tables Modal */}
      {modal && (
        <DatabaseTablesModal
          isOpen={!!modal}
          onClose={() => setModal(null)}
          databaseId={modal.databaseId}
          databaseName={modal.databaseName}
          isDemo={modal.isDemo}
          metadata={modal.metadata}
        />
      )}
    </aside>
  );
};

// ── Sub-components ─────────────────────────────────────────────────────────────

interface DbCardProps {
  name: string;
  tableCount: number;
  isDemo: boolean;
  isActive?: boolean;
  hovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onViewTables: (e: React.MouseEvent) => void;
  onSelect?: () => void;
  onUpload?: () => void;
  onDelete?: (e: React.MouseEvent) => void;
}

const DbCard: React.FC<DbCardProps> = ({
  name, tableCount, isDemo, isActive, hovered,
  onMouseEnter, onMouseLeave, onViewTables, onSelect, onUpload, onDelete,
}) => (
  <div
    className="db-list-item"
    onMouseEnter={onMouseEnter}
    onMouseLeave={onMouseLeave}
    style={isActive ? { background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(99,102,241,0.3)' } : undefined}
  >
    {/* Left: icon + name + table count (clickable area if onSelect provided) */}
    <div
      style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0, cursor: onSelect ? 'pointer' : 'default' }}
      onClick={onSelect}
    >
      {isDemo
        ? <Lock size={13} style={{ color: '#818cf8', flexShrink: 0 }} />
        : <Database size={13} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
      }
      <span style={{
        fontSize: '12.5px', color: isActive ? '#c7d2fe' : 'var(--text-secondary)',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
      }}>
        {name}
      </span>
      <span style={{
        fontSize: '10px', padding: '1px 6px', borderRadius: '8px', flexShrink: 0,
        background: isDemo ? 'rgba(99,102,241,0.15)' : 'rgba(6,182,212,0.12)',
        color: isDemo ? '#a5b4fc' : 'var(--accent-cyan)',
        fontWeight: 600, whiteSpace: 'nowrap',
      }}>
        {tableCount} {tableCount === 1 ? 'table' : 'tables'}
      </span>
    </div>

    {/* Right: action buttons (shown on hover) */}
    <div style={{ display: 'flex', gap: '3px', flexShrink: 0, visibility: hovered ? 'visible' : 'hidden' }}>
      {/* View tables button — always */}
      <button
        type="button"
        title="View tables"
        onClick={onViewTables}
        style={{
          padding: '3px 5px', borderRadius: '5px', cursor: 'pointer',
          background: isDemo ? 'rgba(99,102,241,0.12)' : 'rgba(6,182,212,0.1)',
          border: 'none',
          color: isDemo ? '#a5b4fc' : 'var(--accent-cyan)',
          display: 'flex', alignItems: 'center',
        }}
      >
        <Eye size={11} />
      </button>

      {/* Upload + Delete — user databases only */}
      {!isDemo && onUpload && (
        <button
          type="button"
          title="Upload file to this database"
          onClick={onUpload}
          style={{
            padding: '3px 5px', borderRadius: '5px', cursor: 'pointer',
            background: 'rgba(6,182,212,0.1)', border: 'none',
            color: 'var(--accent-cyan)', display: 'flex', alignItems: 'center',
          }}
        >
          <Upload size={11} />
        </button>
      )}
      {!isDemo && onDelete && (
        <button
          type="button"
          title="Delete database"
          onClick={onDelete}
          style={{
            padding: '3px 5px', borderRadius: '5px', cursor: 'pointer',
            background: 'rgba(239,68,68,0.1)', border: 'none',
            color: '#f87171', display: 'flex', alignItems: 'center',
          }}
        >
          <Trash2 size={11} />
        </button>
      )}
    </div>
  </div>
);

interface ProjectRowProps {
  project: Project;
  db: DatabaseType | null | undefined;
  isActive: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
}

const ProjectRow: React.FC<ProjectRowProps> = ({ project, db, isActive, onSelect, onDelete }) => (
  <button
    type="button"
    className={`history-item-btn ${isActive ? 'active' : ''}`}
    onClick={onSelect}
  >
    <MessageSquare size={14} style={{ flexShrink: 0, opacity: 0.7 }} />
    <span className="history-item-title">{project.title || 'Untitled'}</span>
    {db && (
      <span style={{
        fontSize: '10px', padding: '1px 5px', borderRadius: '4px',
        background: 'rgba(6,182,212,0.12)', color: 'var(--accent-cyan)',
        flexShrink: 0, maxWidth: '60px', overflow: 'hidden',
        textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {db.name}
      </span>
    )}
    <span
      className="history-delete-btn"
      title="Delete Chat"
      onClick={onDelete}
    >
      <Trash2 size={13} />
    </span>
  </button>
);
