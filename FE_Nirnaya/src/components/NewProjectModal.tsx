import React, { useState } from 'react';
import { X, FolderPlus, Database, ChevronDown } from 'lucide-react';
import type { Database as DatabaseType } from '../types';

interface NewProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  databases: DatabaseType[];
  onCreateProject: (databaseId?: string) => Promise<void>;
  isLoading?: boolean;
}

export const NewProjectModal: React.FC<NewProjectModalProps> = ({
  isOpen,
  onClose,
  databases,
  onCreateProject,
  isLoading = false,
}) => {
  const [selectedDbId, setSelectedDbId] = useState<string>('');
  const [showDbPicker, setShowDbPicker] = useState(false);

  if (!isOpen) return null;

  const selectedDb = databases.find((d) => d.id === selectedDbId) || databases[0];

  const handleCreate = async () => {
    await onCreateProject(selectedDb?.id);
    setSelectedDbId('');
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content"
        style={{ maxWidth: '440px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '32px', height: '32px', borderRadius: '8px',
              background: 'rgba(99,102,241,0.2)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <FolderPlus size={16} style={{ color: '#818cf8' }} />
            </div>
            <div>
              <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                New Chat
              </h2>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
                Select a database to analyse
              </p>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px' }}>
          <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '8px' }}>
            Database
          </label>

          {databases.length === 0 ? (
            <div style={{
              padding: '16px', borderRadius: '10px',
              background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)',
              fontSize: '13px', color: 'var(--accent-amber, #f59e0b)', textAlign: 'center',
            }}>
              No databases yet — create one first in the sidebar.
            </div>
          ) : (
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                onClick={() => setShowDbPicker(!showDbPicker)}
                style={{
                  width: '100%', padding: '10px 14px',
                  borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  cursor: 'pointer', fontSize: '13.5px',
                }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Database size={14} style={{ color: 'var(--accent-cyan)' }} />
                  {selectedDb ? selectedDb.name : 'Select a database'}
                </span>
                <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} />
              </button>

              {showDbPicker && (
                <div style={{
                  position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0,
                  background: '#111827', border: '1px solid rgba(255,255,255,0.12)',
                  borderRadius: '8px', padding: '6px', zIndex: 50,
                  boxShadow: 'var(--shadow-lg)',
                }}>
                  {databases.map((db) => (
                    <button
                      key={db.id}
                      type="button"
                      onClick={() => { setSelectedDbId(db.id); setShowDbPicker(false); }}
                      style={{
                        width: '100%', padding: '8px 10px', borderRadius: '6px', textAlign: 'left',
                        background: db.id === selectedDb?.id ? 'rgba(99,102,241,0.15)' : 'transparent',
                        color: 'var(--text-secondary)', fontSize: '13px',
                        display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer',
                      }}
                    >
                      <Database size={13} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
                      <span>{db.name}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '16px 24px', borderTop: '1px solid rgba(255,255,255,0.07)',
          display: 'flex', justifyContent: 'flex-end', gap: '10px',
        }}>
          <button type="button" className="btn-modal-cancel" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-modal-primary"
            onClick={handleCreate}
            disabled={isLoading || databases.length === 0}
          >
            {isLoading ? 'Creating…' : 'Start Chat'}
          </button>
        </div>
      </div>
    </div>
  );
};
