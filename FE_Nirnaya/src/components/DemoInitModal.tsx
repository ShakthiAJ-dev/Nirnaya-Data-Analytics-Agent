import React, { useState } from 'react';
import { Database, Loader2, X } from 'lucide-react';
import { databaseService } from '../services/databaseService';

interface DemoInitModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDemoCreated: () => Promise<void>;
}

export const DemoInitModal: React.FC<DemoInitModalProps> = ({ isOpen, onClose, onDemoCreated }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleLoadDemo = async () => {
    setLoading(true);
    setError(null);
    try {
      await databaseService.createDemoDatabase();
      await onDemoCreated();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to load demo. Please try again.');
      setLoading(false);
    }
  };

  const handleSkip = () => {
    onClose();
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '24px',
      }}
      onClick={!loading ? handleSkip : undefined}
    >
      <div
        style={{
          background: '#0f1117', border: '1px solid rgba(99,102,241,0.25)',
          borderRadius: '16px', padding: '28px', maxWidth: '420px', width: '100%',
          boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '40px', height: '40px', borderRadius: '10px',
              background: 'rgba(99,102,241,0.2)', display: 'flex',
              alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <Database size={20} style={{ color: '#818cf8' }} />
            </div>
            <div>
              <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary, #e2e8f0)' }}>
                Try a Live Dataset
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted, #64748b)', marginTop: '2px' }}>
                Music E-commerce · 11 tables
              </div>
            </div>
          </div>
          {!loading && (
            <button
              type="button"
              onClick={handleSkip}
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: 'var(--text-muted, #64748b)' }}
            >
              <X size={16} />
            </button>
          )}
        </div>

        {/* Description */}
        <p style={{ fontSize: '13px', color: 'var(--text-secondary, #94a3b8)', lineHeight: '1.6', marginBottom: '18px' }}>
          A pre-loaded Music E-commerce database covering sales, customers, tracks, albums, artists, and more.
          Ask any analytics question in plain English — no SQL knowledge required.
        </p>

        {/* Error */}
        {error && (
          <div style={{
            padding: '10px 12px', borderRadius: '8px', marginBottom: '14px',
            background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)',
            fontSize: '12.5px', color: '#f87171',
          }}>
            {error}
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            padding: '12px', borderRadius: '8px', marginBottom: '14px',
            background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)',
            fontSize: '13px', color: '#a5b4fc',
          }}>
            <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
            <span>Loading 11 tables into your session…</span>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            type="button"
            onClick={handleLoadDemo}
            disabled={loading}
            style={{
              flex: 1, padding: '10px 16px', borderRadius: '8px', cursor: loading ? 'not-allowed' : 'pointer',
              background: loading ? 'rgba(99,102,241,0.4)' : 'rgba(99,102,241,0.85)',
              border: '1px solid rgba(99,102,241,0.5)', color: '#e0e7ff',
              fontSize: '13.5px', fontWeight: 600, display: 'flex', alignItems: 'center',
              justifyContent: 'center', gap: '6px',
              opacity: loading ? 0.8 : 1,
            }}
          >
            {loading ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Database size={14} />}
            {loading ? 'Loading…' : 'Load Demo Database'}
          </button>
          <button
            type="button"
            onClick={handleSkip}
            disabled={loading}
            style={{
              padding: '10px 16px', borderRadius: '8px', cursor: loading ? 'not-allowed' : 'pointer',
              background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
              color: 'var(--text-secondary, #94a3b8)', fontSize: '13px',
              opacity: loading ? 0.5 : 1,
            }}
          >
            Skip
          </button>
        </div>

        <p style={{ fontSize: '11px', color: 'var(--text-muted, #64748b)', textAlign: 'center', marginTop: '12px' }}>
          You can load the demo database later from the sidebar.
        </p>
      </div>

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};
