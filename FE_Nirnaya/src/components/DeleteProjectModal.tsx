import React from 'react';
import ReactDOM from 'react-dom';
import { AlertTriangle, Trash2, Loader2 } from 'lucide-react';

interface DeleteProjectModalProps {
  isOpen: boolean;
  projectTitle: string | undefined;
  isDeleting?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const DeleteProjectModal: React.FC<DeleteProjectModalProps> = ({
  isOpen,
  projectTitle,
  isDeleting = false,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  const content = (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.72)',
        zIndex: 10100, display: 'flex', alignItems: 'center',
        justifyContent: 'center', padding: '24px',
      }}
      onClick={() => !isDeleting && onCancel()}
    >
      <div
        style={{
          background: '#0f1117', border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: '14px', padding: '28px 24px', maxWidth: '420px',
          width: '100%', boxShadow: '0 32px 80px rgba(0,0,0,0.6)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Icon + Title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <div style={{
            width: '40px', height: '40px', borderRadius: '10px',
            background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.25)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <AlertTriangle size={20} style={{ color: '#f87171' }} />
          </div>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Delete Project
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
              This action cannot be undone
            </div>
          </div>
        </div>

        {/* Body */}
        <p style={{
          fontSize: '13.5px', color: 'var(--text-secondary)', lineHeight: 1.6,
          marginBottom: '16px',
        }}>
          You are about to permanently delete{' '}
          <strong style={{ color: 'var(--text-primary)' }}>
            &ldquo;{projectTitle || 'Untitled'}&rdquo;
          </strong>
          . All conversation history and any generated charts or tables will be{' '}
          <strong style={{ color: '#f87171' }}>permanently removed</strong>{' '}
          and cannot be recovered.
        </p>

        {/* Warning banner */}
        <div style={{
          padding: '10px 14px', borderRadius: '8px', marginBottom: '20px',
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
          fontSize: '12px', color: '#fca5a5', display: 'flex', alignItems: 'center', gap: '8px',
        }}>
          <AlertTriangle size={13} style={{ flexShrink: 0, color: '#f87171' }} />
          <span>All chat messages and artifacts will be deleted forever.</span>
        </div>

        {/* Buttons */}
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={onCancel}
            disabled={isDeleting}
            style={{
              padding: '9px 18px', borderRadius: '8px',
              border: '1px solid rgba(255,255,255,0.1)',
              background: 'rgba(255,255,255,0.05)',
              color: 'var(--text-secondary)', cursor: isDeleting ? 'not-allowed' : 'pointer',
              fontSize: '13px', fontWeight: 600, opacity: isDeleting ? 0.5 : 1,
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            style={{
              padding: '9px 18px', borderRadius: '8px',
              border: '1px solid #b91c1c', background: '#dc2626',
              color: '#fff', cursor: isDeleting ? 'not-allowed' : 'pointer',
              fontSize: '13px', fontWeight: 700,
              display: 'flex', alignItems: 'center', gap: '7px',
              opacity: isDeleting ? 0.8 : 1,
            }}
          >
            {isDeleting ? (
              <>
                <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                <span>Deleting...</span>
              </>
            ) : (
              <>
                <Trash2 size={13} />
                <span>Delete Permanently</span>
              </>
            )}
          </button>
        </div>
      </div>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );

  return ReactDOM.createPortal(content, document.body);
};
