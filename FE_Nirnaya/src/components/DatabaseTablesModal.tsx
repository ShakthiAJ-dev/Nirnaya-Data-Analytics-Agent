import React, { useState, useCallback, useRef, useEffect } from 'react';
import ReactDOM from 'react-dom';
import {
  X, ArrowLeft, Table as TableIcon, Database, Eye,
  Tag, Key, Globe, Clock, User, AlertCircle, Hash, Rows,
  Loader2, Trash2,
} from 'lucide-react';
import { databaseService } from '../services/databaseService';
import type { PreviewResponse } from '../services/databaseService';

interface TableMeta {
  overview?: string;
  use_case?: string;
  grain?: string;
  domain_tags?: string[];
  key_columns?: string[];
  currency?: string | null;
  timezone?: string | null;
  tenant_column?: string | null;
  key_notes?: string | null;
  pii_columns?: string[];
  row_count?: number;
  column_count?: number;
}

interface DatabaseTablesModalProps {
  isOpen: boolean;
  onClose: () => void;
  databaseId: string;
  databaseName: string;
  metadata: any; // full metadata JSON: { tables: { [name]: TableMeta } }
  onTableDeleted?: () => void; // callback to refresh parent when table is deleted
}

type View = 'list' | 'detail' | 'preview';

const FIELD_DEFS: { key: keyof TableMeta; label: string; icon: React.ReactNode; isArray?: boolean }[] = [
  { key: 'overview', label: 'Overview', icon: <Database size={13} /> },
  { key: 'use_case', label: 'Use Case', icon: <Globe size={13} /> },
  { key: 'grain', label: 'Grain', icon: <Rows size={13} /> },
  { key: 'domain_tags', label: 'Domain Tags', icon: <Tag size={13} />, isArray: true },
  { key: 'key_columns', label: 'Key Columns', icon: <Key size={13} />, isArray: true },
  { key: 'currency', label: 'Currency', icon: <Hash size={13} /> },
  { key: 'timezone', label: 'Timezone', icon: <Clock size={13} /> },
  { key: 'tenant_column', label: 'Tenant Column', icon: <User size={13} /> },
  { key: 'key_notes', label: 'Key Notes', icon: <AlertCircle size={13} /> },
  { key: 'pii_columns', label: 'PII Columns', icon: <AlertCircle size={13} />, isArray: true },
];

export const DatabaseTablesModal: React.FC<DatabaseTablesModalProps> = ({
  isOpen,
  onClose,
  databaseId,
  databaseName,
  metadata,
  onTableDeleted,
}) => {
  const [view, setView] = useState<View>('list');
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<PreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [deleteTableId, setDeleteTableId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);

  const tables: [string, TableMeta][] = metadata?.tables
    ? Object.entries<TableMeta>(metadata.tables)
    : [];

  const selectedMeta: TableMeta | null = selectedTable && metadata?.tables
    ? (metadata.tables[selectedTable] ?? null)
    : null;

  const resetToList = () => {
    setView('list');
    setSelectedTable(null);
    setPreviewData(null);
    setPreviewError(null);
  };

  const handleClose = () => {
    resetToList();
    onClose();
  };

  const handleSelectTable = (name: string) => {
    setSelectedTable(name);
    setView('detail');
  };

  const loadPreview = useCallback(async (tableName: string, offset = 0) => {
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const data = await databaseService.previewTable(databaseId, tableName, 20, offset);
      if (offset === 0) {
        setPreviewData(data);
      } else {
        setPreviewData((prev) => prev
          ? { ...data, rows: [...prev.rows, ...data.rows] }
          : data
        );
      }
    } catch (err: any) {
      setPreviewError(err?.message || 'Failed to load preview.');
    } finally {
      setPreviewLoading(false);
    }
  }, [databaseId]);

  const handleOpenPreview = () => {
    if (!selectedTable) return;
    setView('preview');
    setPreviewData(null);
    loadPreview(selectedTable, 0);
  };

  const handlePreviewScroll = () => {
    const el = previewScrollRef.current;
    if (!el || previewLoading || !previewData?.has_more) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
      loadPreview(selectedTable!, previewData.rows.length);
    }
  };

  const handleDeleteTable = async (tableName: string) => {
    setIsDeleting(true);
    try {
      await databaseService.deleteTable(databaseId, tableName);
      setDeleteTableId(null);
      // Go back to list view
      setView('list');
      setSelectedTable(null);
      // Call parent callback to refresh
      onTableDeleted?.();
    } catch (err: any) {
      console.error('[DatabaseTablesModal] Delete table failed:', err);
      alert(err?.message || 'Failed to delete table. Please try again.');
    } finally {
      setIsDeleting(false);
    }
  };

  // Reset view when modal closes
  useEffect(() => {
    if (!isOpen) resetToList();
  }, [isOpen]);

  if (!isOpen) return null;

  const s = {
    backdrop: {
      position: 'fixed' as const, inset: 0, background: 'rgba(0,0,0,0.65)',
      zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '24px',
    },
    card: {
      background: '#0f1117', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '14px', width: '100%', maxWidth: '700px',
      maxHeight: '80vh', display: 'flex', flexDirection: 'column' as const,
      boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
      overflow: 'hidden',
    },
    header: {
      padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0,
    },
    closeBtn: {
      marginLeft: 'auto', padding: '6px', borderRadius: '6px', border: 'none',
      background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer',
      display: 'flex', alignItems: 'center',
    },
    body: { overflowY: 'auto' as const, flex: 1, padding: '16px 20px' },
    backBtn: {
      display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 10px',
      borderRadius: '6px', border: 'none', background: 'rgba(255,255,255,0.05)',
      color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '12px',
      marginBottom: '14px',
    },
    tableRow: {
      display: 'flex', alignItems: 'center', gap: '10px',
      padding: '10px 12px', borderRadius: '8px', cursor: 'pointer',
      border: '1px solid rgba(255,255,255,0.06)', marginBottom: '6px',
      background: 'rgba(255,255,255,0.02)', transition: 'background 0.12s ease',
    },
    badge: (color: string) => ({
      fontSize: '10px', padding: '2px 7px', borderRadius: '10px',
      background: `${color}20`, color: color, fontWeight: 600 as const,
      whiteSpace: 'nowrap' as const,
    }),
    fieldLabel: {
      fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 as const,
      display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '4px',
    },
    fieldValue: {
      fontSize: '12.5px', color: 'var(--text-primary)', lineHeight: 1.5,
      padding: '8px 10px', background: 'rgba(255,255,255,0.04)',
      borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)',
    },
    chip: {
      fontSize: '11px', padding: '2px 8px', borderRadius: '5px',
      background: 'rgba(99,102,241,0.15)', color: '#a5b4fc',
      border: '1px solid rgba(99,102,241,0.2)', fontFamily: 'monospace',
    },
    previewBtn: {
      display: 'flex', alignItems: 'center', gap: '6px',
      padding: '7px 14px', borderRadius: '7px', border: 'none',
      background: 'rgba(6,182,212,0.12)', color: 'var(--accent-cyan)',
      cursor: 'pointer', fontSize: '12px', fontWeight: 600 as const,
    },
  };

  // ── Table list view ──────────────────────────────────────────────────────────
  const ListView = () => (
    <>
      <div style={{ marginBottom: '12px', fontSize: '12px', color: 'var(--text-muted)' }}>
        {tables.length} table{tables.length !== 1 ? 's' : ''} in this database
      </div>
      {tables.length === 0 && (
        <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)', fontSize: '13px' }}>
          No tables found. Upload a file to create tables.
        </div>
      )}
      {tables.map(([name, meta]) => (
        <div
          key={name}
          style={s.tableRow}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)'; setHoveredRow(name); }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.02)'; setHoveredRow(null); }}
        >
          {/* Clickable area — navigate to detail */}
          <div
            style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, cursor: 'pointer', minWidth: 0 }}
            onClick={() => handleSelectTable(name)}
          >
            <TableIcon size={14} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {name}
            </span>
            <span style={s.badge('#06b6d4')}>
              {(meta.row_count ?? 0).toLocaleString()} rows
            </span>
            <span style={s.badge('#818cf8')}>
              {meta.column_count ?? 0} cols
            </span>
          </div>
          {/* Hover actions */}
          <div style={{ display: 'flex', gap: '4px', alignItems: 'center', flexShrink: 0, marginLeft: '6px', visibility: hoveredRow === name ? 'visible' : 'hidden' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>View →</span>
            <button
              type="button"
              title="Delete this table"
              onClick={(e) => { e.stopPropagation(); setDeleteTableId(name); }}
              style={{
                padding: '3px 6px', borderRadius: '5px', border: 'none',
                background: 'rgba(239,68,68,0.12)', color: '#f87171',
                cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '3px',
                fontSize: '11px', fontWeight: 600,
              }}
            >
              <Trash2 size={11} />
            </button>
          </div>
        </div>
      ))}
    </>
  );

  // ── Detail view ──────────────────────────────────────────────────────────────
  const DetailView = () => (
    <>
      <button style={s.backBtn} onClick={() => setView('list')}>
        <ArrowLeft size={13} /> Tables
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
        <TableIcon size={16} style={{ color: 'var(--accent-cyan)' }} />
        <span style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
          {selectedTable}
        </span>
        <span style={s.badge('#06b6d4')}>{(selectedMeta?.row_count ?? 0).toLocaleString()} rows</span>
        <span style={s.badge('#818cf8')}>{selectedMeta?.column_count ?? 0} cols</span>
        <button style={{ ...s.previewBtn, marginLeft: 'auto' }} onClick={handleOpenPreview}>
          <Eye size={13} /> Preview
        </button>
        <button
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            padding: '7px 14px', borderRadius: '7px', border: 'none',
            background: 'rgba(239,68,68,0.12)', color: '#f87171',
            cursor: 'pointer', fontSize: '12px', fontWeight: 600,
          }}
          onClick={() => setDeleteTableId(selectedTable)}
          title="Delete this table"
        >
          <Trash2 size={13} /> Delete
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {FIELD_DEFS.map(({ key, label, icon, isArray }) => {
          const val = selectedMeta?.[key];
          if (val === null || val === undefined || val === '') return null;
          if (isArray && Array.isArray(val) && val.length === 0) return null;

          return (
            <div key={key}>
              <div style={s.fieldLabel}>{icon} {label}</div>
              {isArray && Array.isArray(val) ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                  {(val as string[]).map((v) => (
                    <span key={v} style={s.chip}>{v}</span>
                  ))}
                </div>
              ) : (
                <div style={s.fieldValue}>{String(val)}</div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );

  // ── Preview view ──────────────────────────────────────────────────────────────
  const PreviewView = () => (
    <>
      <button style={s.backBtn} onClick={() => setView('detail')}>
        <ArrowLeft size={13} /> Metadata
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
        <Eye size={14} style={{ color: 'var(--accent-cyan)' }} />
        <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
          Preview — {selectedTable}
        </span>
        {previewData && (
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: 'auto' }}>
            {previewData.rows.length} / {previewData.total_count.toLocaleString()} rows
          </span>
        )}
      </div>

      {previewError && (
        <div style={{ padding: '12px', borderRadius: '8px', background: 'rgba(239,68,68,0.1)', color: '#f87171', fontSize: '12px', marginBottom: '12px' }}>
          {previewError}
        </div>
      )}

      {!previewData && previewLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '32px' }}>
          <Loader2 size={20} style={{ color: 'var(--accent-cyan)', animation: 'spin 1s linear infinite' }} />
        </div>
      )}

      {previewData && (
        <div
          ref={previewScrollRef}
          onScroll={handlePreviewScroll}
          style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: '360px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.08)' }}
        >
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', tableLayout: 'auto' }}>
            <thead style={{ position: 'sticky', top: 0, background: '#0d1018', zIndex: 1 }}>
              <tr>
                {previewData.columns.map((col) => (
                  <th key={col} style={{ padding: '8px 12px', textAlign: 'left', color: '#a5b4fc', fontWeight: 600, borderBottom: '1px solid rgba(255,255,255,0.1)', whiteSpace: 'nowrap' }}>
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {previewData.rows.map((row, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                  {previewData.columns.map((col) => (
                    <td key={col} style={{ padding: '7px 12px', color: 'var(--text-secondary)', borderBottom: '1px solid rgba(255,255,255,0.04)', whiteSpace: 'nowrap', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {row[col] === null || row[col] === undefined ? (
                        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>null</span>
                      ) : String(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>

          {previewLoading && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '12px' }}>
              <Loader2 size={16} style={{ color: 'var(--accent-cyan)', animation: 'spin 1s linear infinite' }} />
            </div>
          )}
          {!previewLoading && previewData.has_more && (
            <div style={{ textAlign: 'center', padding: '10px' }}>
              <button
                onClick={() => loadPreview(selectedTable!, previewData.rows.length)}
                style={{ padding: '6px 16px', borderRadius: '6px', border: '1px solid rgba(6,182,212,0.3)', background: 'rgba(6,182,212,0.08)', color: 'var(--accent-cyan)', cursor: 'pointer', fontSize: '12px' }}
              >
                Load more
              </button>
            </div>
          )}
          {!previewLoading && !previewData.has_more && previewData.rows.length > 0 && (
            <div style={{ textAlign: 'center', padding: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>
              All {previewData.total_count.toLocaleString()} rows loaded
            </div>
          )}
        </div>
      )}
    </>
  );

  const titleMap: Record<View, string> = {
    list: databaseName,
    detail: selectedTable || '',
    preview: `Preview — ${selectedTable || ''}`,
  };

  // ── Delete Table Confirmation Modal ──────────────────────────────────────────
  const DeleteTableConfirmation = () => {
    if (!deleteTableId) return null;

    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.7)',
          zIndex: 10001,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px',
        }}
        onClick={() => !isDeleting && setDeleteTableId(null)}
      >
        <div
          style={{
            background: '#0f1117',
            border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: '12px',
            padding: '20px',
            maxWidth: '380px',
            width: '100%',
            boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
            <AlertCircle size={18} style={{ color: '#f87171', flexShrink: 0 }} />
            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Delete Table
            </span>
          </div>

          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.5 }}>
            Are you sure you want to delete <strong>"{deleteTableId}"</strong>? This table and all its data will be permanently removed from the database.
          </p>

          {isDeleting && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px',
                borderRadius: '6px',
                marginBottom: '12px',
                background: 'rgba(239,68,68,0.08)',
                border: '1px solid rgba(239,68,68,0.2)',
                fontSize: '12px',
                color: '#f87171',
              }}
            >
              <Loader2 size={14} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
              <span>Deleting table…</span>
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button
              onClick={() => setDeleteTableId(null)}
              disabled={isDeleting}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)',
                color: 'var(--text-secondary)',
                cursor: isDeleting ? 'not-allowed' : 'pointer',
                fontSize: '12px',
                fontWeight: 600,
                opacity: isDeleting ? 0.5 : 1,
              }}
            >
              Cancel
            </button>
            <button
              onClick={() => handleDeleteTable(deleteTableId)}
              disabled={isDeleting}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid #b91c1c',
                background: '#dc2626',
                color: '#fff',
                cursor: isDeleting ? 'not-allowed' : 'pointer',
                fontSize: '12px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                opacity: isDeleting ? 0.8 : 1,
              }}
            >
              {isDeleting ? (
                <>
                  <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
                  <span>Deleting…</span>
                </>
              ) : (
                <>
                  <Trash2 size={12} />
                  <span>Delete</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  };

  const content = (
    <>
      <div style={s.backdrop} onClick={(e) => e.target === e.currentTarget && handleClose()}>
        <div style={s.card}>
          {/* Header */}
          <div style={s.header}>
            <Database size={16} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
            <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
              {titleMap[view]}
            </span>
            <button style={s.closeBtn} onClick={handleClose} title="Close">
              <X size={16} />
            </button>
          </div>

          {/* Body */}
          <div style={s.body}>
            {view === 'list' && <ListView />}
            {view === 'detail' && <DetailView />}
            {view === 'preview' && <PreviewView />}
          </div>
        </div>
      </div>

      {/* Delete Table Confirmation Modal */}
      <DeleteTableConfirmation />

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </>
  );

  return ReactDOM.createPortal(content, document.body);
};
