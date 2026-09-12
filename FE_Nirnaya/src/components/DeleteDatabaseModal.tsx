import React, { useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';

interface DeleteDatabaseModalProps {
  isOpen: boolean;
  databaseName?: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

export const DeleteDatabaseModal: React.FC<DeleteDatabaseModalProps> = ({
  isOpen,
  databaseName = 'Database',
  onConfirm,
  onCancel,
}) => {
  const [isLoading, setIsLoading] = useState(false);

  if (!isOpen) return null;

  const handleConfirm = async () => {
    setIsLoading(true);
    try {
      await onConfirm();
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        zIndex: 10000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
      onClick={!isLoading ? onCancel : undefined}
    >
      <div
        style={{
          background: '#0f1117',
          border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: '16px',
          padding: '28px',
          maxWidth: '420px',
          width: '100%',
          boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '16px' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '10px',
              background: 'rgba(239,68,68,0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <AlertTriangle size={20} style={{ color: '#f87171' }} />
          </div>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary, #e2e8f0)' }}>
              Delete Database
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted, #64748b)', marginTop: '2px' }}>
              This action cannot be undone
            </div>
          </div>
        </div>

        {/* Message */}
        <p
          style={{
            fontSize: '13px',
            color: 'var(--text-secondary, #94a3b8)',
            lineHeight: '1.6',
            marginBottom: '20px',
          }}
        >
          Are you sure you want to delete <strong>"{databaseName}"</strong>? All tables, data, and associated projects will be permanently removed from your session.
        </p>

        {/* Loading state */}
        {isLoading && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              padding: '12px',
              borderRadius: '8px',
              marginBottom: '14px',
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.2)',
              fontSize: '13px',
              color: '#f87171',
            }}
          >
            <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
            <span>Deleting database…</span>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              cursor: isLoading ? 'not-allowed' : 'pointer',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: 'var(--text-secondary, #94a3b8)',
              fontSize: '13px',
              fontWeight: 600,
              opacity: isLoading ? 0.5 : 1,
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isLoading}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              cursor: isLoading ? 'not-allowed' : 'pointer',
              background: '#dc2626',
              border: '1px solid #b91c1c',
              color: '#fff',
              fontSize: '13px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              opacity: isLoading ? 0.8 : 1,
            }}
          >
            {isLoading ? (
              <>
                <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                <span>Deleting…</span>
              </>
            ) : (
              'Delete Database'
            )}
          </button>
        </div>

        <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      </div>
    </div>
  );
};
