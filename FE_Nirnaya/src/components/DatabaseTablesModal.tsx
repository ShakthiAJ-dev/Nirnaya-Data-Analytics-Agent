import React, { useState, useCallback, useRef, useEffect, useImperativeHandle } from 'react';
import ReactDOM from 'react-dom';
import {
  X, ArrowLeft, Table as TableIcon, Database, Eye,
  Tag, Key, Globe, Clock, User, AlertCircle, Hash, Rows,
  Loader2, Trash2, RefreshCw, FileText, Pencil, Save, XCircle,
  ChevronDown, Check,
} from 'lucide-react';
import { databaseService } from '../services/databaseService';
import type { PreviewResponse } from '../services/databaseService';

interface ColumnInfo {
  name: string;
  data_type: string;
  type_class: string;
}

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
  columns?: ColumnInfo[];
}

interface DatabaseTablesModalProps {
  isOpen: boolean;
  onClose: () => void;
  databaseId: string;
  databaseName: string;
  metadata: any;
  onTableDeleted?: () => void;
}

type View = 'list' | 'detail';
type DetailTab = 'preview' | 'schema';

const FIELD_DEFS: {
  key: keyof TableMeta;
  label: string;
  icon: React.ReactNode;
  isArray?: boolean;
  isColumnRef?: boolean;
}[] = [
  { key: 'overview', label: 'Overview', icon: <Database size={13} /> },
  { key: 'use_case', label: 'Use Case', icon: <Globe size={13} /> },
  { key: 'grain', label: 'Grain', icon: <Rows size={13} /> },
  { key: 'domain_tags', label: 'Domain Tags', icon: <Tag size={13} />, isArray: true },
  { key: 'key_columns', label: 'Key Columns', icon: <Key size={13} />, isArray: true, isColumnRef: true },
  { key: 'currency', label: 'Currency', icon: <Hash size={13} /> },
  { key: 'timezone', label: 'Timezone', icon: <Clock size={13} /> },
  { key: 'tenant_column', label: 'Tenant Column', icon: <User size={13} />, isColumnRef: true },
  { key: 'key_notes', label: 'Key Notes', icon: <AlertCircle size={13} /> },
  { key: 'pii_columns', label: 'PII Columns', icon: <AlertCircle size={13} />, isArray: true, isColumnRef: true },
];

// ── Multi-select dropdown for column-ref array fields ────────────────────────
const MultiColumnSelect: React.FC<{
  selected: string[];
  columns: string[];
  onChange: (val: string[]) => void;
  placeholder?: string;
}> = ({ selected, columns, onChange, placeholder = 'Select columns…' }) => {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const toggle = (col: string) =>
    onChange(selected.includes(col) ? selected.filter((c) => c !== col) : [...selected, col]);

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%', textAlign: 'left', background: 'rgba(255,255,255,0.05)',
          border: '1px solid rgba(99,102,241,0.35)', borderRadius: '8px',
          padding: '9px 12px',
          color: selected.length ? 'var(--text-primary)' : 'var(--text-muted)',
          fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', gap: '8px',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selected.length > 0 ? selected.join(', ') : placeholder}
        </span>
        <ChevronDown
          size={14}
          style={{
            flexShrink: 0, opacity: 0.6,
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform 0.15s',
          }}
        />
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0,
          background: '#0d111a', border: '1px solid rgba(99,102,241,0.35)',
          borderRadius: '8px', zIndex: 200, maxHeight: '200px', overflowY: 'auto',
          boxShadow: '0 8px 24px rgba(0,0,0,0.55)',
        }}>
          {columns.length === 0 ? (
            <div style={{ padding: '10px 12px', fontSize: '12px', color: 'var(--text-muted)' }}>No columns found</div>
          ) : columns.map((col) => {
            const checked = selected.includes(col);
            return (
              <div
                key={col}
                onClick={() => toggle(col)}
                style={{
                  display: 'flex', alignItems: 'center', gap: '10px',
                  padding: '8px 12px', cursor: 'pointer', fontSize: '13px',
                  color: checked ? '#a5b4fc' : 'var(--text-secondary)',
                  background: checked ? 'rgba(99,102,241,0.08)' : 'transparent',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={(e) => { if (!checked) (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.04)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = checked ? 'rgba(99,102,241,0.08)' : 'transparent'; }}
              >
                <div style={{
                  width: '16px', height: '16px', borderRadius: '4px', flexShrink: 0,
                  border: `1px solid ${checked ? '#818cf8' : 'rgba(255,255,255,0.2)'}`,
                  background: checked ? 'rgba(99,102,241,0.3)' : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {checked && <Check size={10} style={{ color: '#a5b4fc' }} />}
                </div>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: '12.5px' }}>{col}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ── Isolated edit form — owns draft state so parent never re-renders on input ─
interface MetadataEditFormHandle {
  getValues: () => Partial<TableMeta>;
}

const MetadataEditForm = React.forwardRef<
  MetadataEditFormHandle,
  { initialMeta: Partial<TableMeta>; columnNames: string[] }
>(({ initialMeta, columnNames }, ref) => {
  const [draft, setDraft] = useState<Partial<TableMeta>>({ ...initialMeta });

  useImperativeHandle(ref, () => ({ getValues: () => draft }), [draft]);

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(99,102,241,0.35)', borderRadius: '8px',
    padding: '9px 12px', color: 'var(--text-primary)', fontSize: '13px',
    outline: 'none', boxSizing: 'border-box',
  };

  const fieldLabelStyle: React.CSSProperties = {
    fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600,
    display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px',
    textTransform: 'uppercase', letterSpacing: '0.04em',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {FIELD_DEFS.map(({ key, label, icon, isArray, isColumnRef }) => {
        const val = (draft as any)[key];

        return (
          <div key={key}>
            <div style={fieldLabelStyle}>{icon} {label}</div>

            {isColumnRef && isArray ? (
              <MultiColumnSelect
                selected={Array.isArray(val) ? val : []}
                columns={columnNames}
                onChange={(arr) => setDraft((d) => ({ ...d, [key]: arr }))}
                placeholder={`Select ${label.toLowerCase()}…`}
              />
            ) : isColumnRef && !isArray ? (
              <select
                value={(val as string) || ''}
                onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value || null }))}
                style={{
                  ...inputStyle,
                  background: '#0f1623',
                  color: '#f1f5f9',
                  cursor: 'pointer',
                  appearance: 'none' as any,
                  backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E")`,
                  backgroundRepeat: 'no-repeat',
                  backgroundPosition: 'calc(100% - 10px) center',
                  paddingRight: '32px',
                }}
              >
                <option value="" style={{ background: '#0f1623', color: '#94a3b8' }}>— None —</option>
                {columnNames.map((c) => (
                  <option key={c} value={c} style={{ background: '#0f1623', color: '#f1f5f9' }}>{c}</option>
                ))}
              </select>
            ) : isArray ? (
              <input
                type="text"
                placeholder="Comma-separated values…"
                value={Array.isArray(val) ? (val as string[]).join(', ') : (val as string) || ''}
                onChange={(e) => {
                  const arr = e.target.value ? e.target.value.split(',').map((v) => v.trim()).filter(Boolean) : [];
                  setDraft((d) => ({ ...d, [key]: arr }));
                }}
                style={inputStyle}
              />
            ) : (
              <textarea
                rows={key === 'overview' || key === 'use_case' || key === 'key_notes' ? 3 : 1}
                placeholder={`Enter ${label.toLowerCase()}…`}
                value={(val as string) || ''}
                onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
});
MetadataEditForm.displayName = 'MetadataEditForm';

// ── Main modal ───────────────────────────────────────────────────────────────
export const DatabaseTablesModal: React.FC<DatabaseTablesModalProps> = ({
  isOpen,
  onClose,
  databaseId,
  databaseName,
  metadata,
  onTableDeleted,
}) => {
  const [view, setView] = useState<View>('list');
  const [detailTab, setDetailTab] = useState<DetailTab>('schema');
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [activeMetadata, setActiveMetadata] = useState<any>(metadata);
  const [metaLoading, setMetaLoading] = useState(false);
  const [previewData, setPreviewData] = useState<PreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [deleteTableId, setDeleteTableId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const previewScrollRef = useRef<HTMLDivElement>(null);
  const savedScrollRef = useRef<number>(0);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const editFormRef = useRef<MetadataEditFormHandle>(null);

  useEffect(() => { setActiveMetadata(metadata); }, [metadata]);

  useEffect(() => {
    if (!isOpen || !databaseId) return;
    const hasTables = activeMetadata?.tables && Object.keys(activeMetadata.tables).length > 0;
    if (!hasTables) {
      let cancelled = false;
      setMetaLoading(true);
      databaseService.getMetadata(databaseId)
        .then((data) => { if (!cancelled && data) setActiveMetadata(data); })
        .catch((err) => { console.warn('[DatabaseTablesModal] Fallback metadata fetch error:', err); })
        .finally(() => { if (!cancelled) setMetaLoading(false); });
      return () => { cancelled = true; };
    }
  }, [isOpen, databaseId, activeMetadata]);

  const tables: [string, TableMeta][] = activeMetadata?.tables
    ? Object.entries<TableMeta>(activeMetadata.tables)
    : [];

  const selectedMeta: TableMeta | null = selectedTable && activeMetadata?.tables
    ? (activeMetadata.tables[selectedTable] ?? null)
    : null;

  const columnNames: string[] = selectedMeta?.columns?.map((c) => c.name) ?? [];

  const resetToList = () => {
    setView('list');
    setDetailTab('schema');
    setSelectedTable(null);
    setPreviewData(null);
    setPreviewError(null);
    setIsEditing(false);
  };

  const handleClose = () => { resetToList(); onClose(); };

  const loadPreview = useCallback(async (tableName: string, offset = 0) => {
    if (offset > 0 && previewScrollRef.current) {
      savedScrollRef.current = previewScrollRef.current.scrollTop;
    }
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

  useEffect(() => {
    if (savedScrollRef.current > 0 && previewScrollRef.current) {
      const top = savedScrollRef.current;
      savedScrollRef.current = 0;
      requestAnimationFrame(() => {
        if (previewScrollRef.current) previewScrollRef.current.scrollTop = top;
      });
    }
  }, [previewData]);

  const handleSelectTable = (name: string) => {
    setSelectedTable(name);
    setDetailTab('schema');
    setView('detail');
    setPreviewData(null);
    setIsEditing(false);
  };

  const cancelEdit = () => setIsEditing(false);

  const handleSaveMetadata = async () => {
    if (!selectedTable || !editFormRef.current) return;
    const values = editFormRef.current.getValues();
    setIsSaving(true);
    try {
      await databaseService.updateTableMetadata(databaseId, selectedTable, values as Record<string, unknown>);
      setActiveMetadata((prev: any) => {
        if (!prev?.tables) return prev;
        return {
          ...prev,
          tables: {
            ...prev.tables,
            [selectedTable]: { ...prev.tables[selectedTable], ...values },
          },
        };
      });
      setIsEditing(false);
    } catch (err: any) {
      alert(err?.message || 'Failed to save metadata.');
    } finally {
      setIsSaving(false);
    }
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
      if (activeMetadata?.tables) {
        const updated = { ...activeMetadata.tables };
        delete updated[tableName];
        setActiveMetadata({ ...activeMetadata, tables: updated });
      }
      setView('list');
      setSelectedTable(null);
      onTableDeleted?.();
    } catch (err: any) {
      console.error('[DatabaseTablesModal] Delete table failed:', err);
      alert(err?.message || 'Failed to delete table. Please try again.');
    } finally {
      setIsDeleting(false);
    }
  };

  useEffect(() => { if (!isOpen) resetToList(); }, [isOpen]);

  if (!isOpen) return null;

  const s = {
    backdrop: {
      position: 'fixed' as const, inset: 0, background: 'rgba(0,0,0,0.7)',
      backdropFilter: 'blur(4px)',
      zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '20px',
    },
    card: {
      background: '#0d111a', border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: '16px', width: '100%', maxWidth: '880px',
      maxHeight: '85vh', display: 'flex', flexDirection: 'column' as const,
      boxShadow: '0 24px 64px rgba(0,0,0,0.65), 0 0 0 1px rgba(99,102,241,0.1)',
      overflow: 'hidden',
    },
    header: {
      padding: '16px 22px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0,
      background: 'rgba(255,255,255,0.02)',
    },
    closeBtn: {
      marginLeft: 'auto', padding: '6px', borderRadius: '6px', border: 'none',
      background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer',
      display: 'flex', alignItems: 'center', transition: 'color 0.15s',
    },
    body: { overflowY: 'auto' as const, flex: 1, padding: '18px 22px' },
    backBtn: {
      display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 12px',
      borderRadius: '6px', border: '1px solid rgba(255,255,255,0.08)',
      background: 'rgba(255,255,255,0.04)',
      color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '12px',
      fontWeight: 500, transition: 'all 0.15s',
    },
    tableRow: {
      display: 'flex', alignItems: 'center', gap: '12px',
      padding: '12px 14px', borderRadius: '10px', cursor: 'pointer',
      border: '1px solid rgba(255,255,255,0.06)', marginBottom: '8px',
      background: 'rgba(255,255,255,0.02)', transition: 'all 0.15s ease',
    },
    badge: (color: string) => ({
      fontSize: '11px', padding: '3px 8px', borderRadius: '8px',
      background: `${color}18`, color: color, fontWeight: 600 as const,
      border: `1px solid ${color}30`,
      whiteSpace: 'nowrap' as const,
    }),
    fieldLabel: {
      fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 as const,
      display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px',
      textTransform: 'uppercase' as const, letterSpacing: '0.04em',
    },
    fieldValue: {
      fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.5,
      padding: '10px 12px', background: 'rgba(255,255,255,0.03)',
      borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)',
    },
    chip: {
      fontSize: '11.5px', padding: '3px 9px', borderRadius: '6px',
      background: 'rgba(99,102,241,0.12)', color: '#a5b4fc',
      border: '1px solid rgba(99,102,241,0.25)', fontFamily: 'ui-monospace, monospace',
    },
  };

  // ── Table list view ──────────────────────────────────────────────────────────
  const ListView = () => (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
        <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
          {tables.length} table{tables.length !== 1 ? 's' : ''} in this database
        </div>
        {metaLoading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--accent-cyan)' }}>
            <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
            <span>Refreshing schema…</span>
          </div>
        )}
      </div>

      {tables.length === 0 && !metaLoading && (
        <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)', fontSize: '13px' }}>
          <TableIcon size={32} style={{ opacity: 0.3, marginBottom: '8px' }} />
          <div>No tables found in this database.</div>
          <div style={{ fontSize: '11.5px', marginTop: '4px', opacity: 0.7 }}>Upload a CSV or SQLite file to add tables.</div>
        </div>
      )}

      {tables.map(([name, meta]) => (
        <div
          key={name}
          style={s.tableRow}
          onClick={() => handleSelectTable(name)}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(99,102,241,0.06)';
            e.currentTarget.style.borderColor = 'rgba(99,102,241,0.25)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(255,255,255,0.02)';
            e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
          }}
        >
          <div style={{
            width: '32px', height: '32px', borderRadius: '8px',
            background: 'rgba(6,182,212,0.12)', border: '1px solid rgba(6,182,212,0.25)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <TableIcon size={16} style={{ color: 'var(--accent-cyan)' }} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', flex: 1, minWidth: 0 }}>
            <span style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {name}
            </span>
            {meta.overview && (
              <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {meta.overview}
              </span>
            )}
          </div>

          <span style={s.badge('#06b6d4')}>
            {(meta.row_count ?? 0).toLocaleString()} rows
          </span>
          <span style={s.badge('#818cf8')}>
            {meta.column_count ?? 0} cols
          </span>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }} onClick={(e) => e.stopPropagation()}>
            <button
              className="btn-table-action-view"
              onClick={() => handleSelectTable(name)}
              title="View schema and table data"
            >
              <Eye size={13} />
              <span>View</span>
            </button>
            <button
              onClick={() => setDeleteTableId(name)}
              title="Delete table"
              style={{
                padding: '6px 8px', borderRadius: '6px', border: '1px solid transparent',
                background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer',
                display: 'flex', alignItems: 'center', transition: 'all 0.15s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = '#f87171';
                e.currentTarget.style.background = 'rgba(239,68,68,0.1)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--text-muted)';
                e.currentTarget.style.background = 'transparent';
              }}
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>
      ))}
    </>
  );

  // ── Detail & Preview view ───────────────────────────────────────────────────
  const DetailView = () => (
    <>
      {/* Navigation & Action Bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <button style={s.backBtn} onClick={resetToList}>
          <ArrowLeft size={13} /> Back to Tables
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <TableIcon size={16} style={{ color: 'var(--accent-cyan)' }} />
          <span style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {selectedTable}
          </span>
          <span style={s.badge('#06b6d4')}>{(selectedMeta?.row_count ?? 0).toLocaleString()} rows</span>
          <span style={s.badge('#818cf8')}>{selectedMeta?.column_count ?? 0} cols</span>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
          {detailTab === 'preview' && (
            <button
              onClick={() => selectedTable && loadPreview(selectedTable, 0)}
              disabled={previewLoading}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '6px 12px', borderRadius: '7px',
                border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.04)', color: 'var(--text-secondary)',
                cursor: previewLoading ? 'not-allowed' : 'pointer', fontSize: '12px',
              }}
              title="Refresh table data"
            >
              <RefreshCw size={12} className={previewLoading ? 'spin-icon' : ''} />
              <span>Refresh</span>
            </button>
          )}
          {detailTab === 'schema' && !isEditing && (
            <button
              onClick={() => setIsEditing(true)}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '6px 12px', borderRadius: '7px',
                border: '1px solid rgba(99,102,241,0.35)',
                background: 'rgba(99,102,241,0.1)', color: '#a5b4fc',
                cursor: 'pointer', fontSize: '12px', fontWeight: 600,
              }}
              title="Edit metadata fields"
            >
              <Pencil size={12} /> Edit
            </button>
          )}
          {detailTab === 'schema' && isEditing && (
            <>
              <button
                onClick={handleSaveMetadata}
                disabled={isSaving}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '6px 12px', borderRadius: '7px',
                  border: '1px solid rgba(16,185,129,0.35)',
                  background: 'rgba(16,185,129,0.12)', color: '#34d399',
                  cursor: isSaving ? 'not-allowed' : 'pointer', fontSize: '12px', fontWeight: 600,
                }}
              >
                {isSaving ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={12} />}
                {isSaving ? 'Saving…' : 'Save'}
              </button>
              <button
                onClick={cancelEdit}
                disabled={isSaving}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '6px 12px', borderRadius: '7px',
                  border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.04)', color: 'var(--text-muted)',
                  cursor: 'pointer', fontSize: '12px',
                }}
              >
                <XCircle size={12} /> Cancel
              </button>
            </>
          )}
          <button
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '6px 12px', borderRadius: '7px', border: '1px solid rgba(239,68,68,0.25)',
              background: 'rgba(239,68,68,0.1)', color: '#f87171',
              cursor: 'pointer', fontSize: '12px', fontWeight: 600,
            }}
            onClick={() => setDeleteTableId(selectedTable)}
            title="Delete this table"
          >
            <Trash2 size={13} /> Delete
          </button>
        </div>
      </div>

      {/* Segmented Tabs */}
      <div className="table-modal-tabs">
        <button
          type="button"
          className={`table-modal-tab ${detailTab === 'schema' ? 'active' : ''}`}
          onClick={() => setDetailTab('schema')}
        >
          <FileText size={13} />
          <span>Schema & Metadata</span>
        </button>
        <button
          type="button"
          className={`table-modal-tab ${detailTab === 'preview' ? 'active' : ''}`}
          onClick={() => {
            setDetailTab('preview');
            if (!previewData && selectedTable && !previewLoading) {
              loadPreview(selectedTable, 0);
            }
          }}
        >
          <Eye size={13} />
          <span>Data Preview</span>
          {previewData && (
            <span className="table-modal-tab-badge">{previewData.rows.length} rows</span>
          )}
        </button>
      </div>

      {/* TAB CONTENT 1: Data Preview */}
      {detailTab === 'preview' && (
        <div style={{ marginTop: '14px' }}>
          {previewError && (
            <div style={{
              padding: '12px 14px', borderRadius: '8px',
              background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)',
              color: '#f87171', fontSize: '12.5px', marginBottom: '14px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span>{previewError}</span>
              <button
                onClick={() => selectedTable && loadPreview(selectedTable, 0)}
                style={{
                  padding: '4px 10px', borderRadius: '5px',
                  background: 'rgba(239,68,68,0.2)', color: '#fff',
                  border: 'none', cursor: 'pointer', fontSize: '11.5px',
                }}
              >
                Retry
              </button>
            </div>
          )}

          {!previewData && previewLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '48px 0', gap: '10px' }}>
              <Loader2 size={24} style={{ color: 'var(--accent-cyan)', animation: 'spin 1s linear infinite' }} />
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Loading table data…</span>
            </div>
          )}

          {previewData && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-muted)', padding: '0 2px' }}>
                <span>
                  Showing <strong style={{ color: 'var(--text-primary)' }}>{previewData.rows.length}</strong> of{' '}
                  <strong style={{ color: 'var(--text-primary)' }}>{previewData.total_count.toLocaleString()}</strong> rows
                  {' • '}{previewData.columns.length} columns
                </span>
                {previewData.has_more && (
                  <span style={{ fontSize: '11px', color: 'var(--accent-cyan)' }}>Scroll or load more below</span>
                )}
              </div>

              <div
                ref={previewScrollRef}
                onScroll={handlePreviewScroll}
                className="table-modal-preview-container"
              >
                <table className="table-modal-grid">
                  <thead>
                    <tr>
                      <th style={{ width: '42px', textAlign: 'center', color: 'var(--text-muted)' }}>#</th>
                      {previewData.columns.map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewData.rows.map((row, i) => (
                      <tr key={i}>
                        <td style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '11px', opacity: 0.7 }}>
                          {i + 1}
                        </td>
                        {previewData.columns.map((col) => (
                          <td key={col} title={row[col] !== null && row[col] !== undefined ? String(row[col]) : 'null'}>
                            {row[col] === null || row[col] === undefined ? (
                              <span style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '11px' }}>null</span>
                            ) : (
                              String(row[col])
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>

                {previewLoading && (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: '14px', background: 'rgba(0,0,0,0.2)' }}>
                    <Loader2 size={18} style={{ color: 'var(--accent-cyan)', animation: 'spin 1s linear infinite' }} />
                  </div>
                )}

                {!previewLoading && previewData.has_more && (
                  <div style={{ textAlign: 'center', padding: '12px', background: 'rgba(255,255,255,0.01)' }}>
                    <button
                      onClick={() => loadPreview(selectedTable!, previewData.rows.length)}
                      style={{
                        padding: '7px 20px', borderRadius: '7px',
                        border: '1px solid rgba(6,182,212,0.35)',
                        background: 'rgba(6,182,212,0.1)', color: 'var(--accent-cyan)',
                        cursor: 'pointer', fontSize: '12.5px', fontWeight: 600,
                        transition: 'all 0.15s',
                      }}
                    >
                      Load next 20 rows
                    </button>
                  </div>
                )}

                {!previewLoading && !previewData.has_more && previewData.rows.length > 0 && (
                  <div style={{ textAlign: 'center', padding: '10px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    All {previewData.total_count.toLocaleString()} rows loaded
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT 2: Schema & Metadata */}
      {detailTab === 'schema' && (
        <div style={{ marginTop: '16px' }}>
          {isEditing ? (
            <MetadataEditForm
              ref={editFormRef}
              initialMeta={selectedMeta ?? {}}
              columnNames={columnNames}
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {FIELD_DEFS.map(({ key, label, icon, isArray }) => {
                const val = selectedMeta?.[key];
                const isEmpty = val === null || val === undefined || val === '' || (isArray && Array.isArray(val) && val.length === 0);

                return (
                  <div key={key}>
                    <div style={s.fieldLabel}>{icon} {label}</div>
                    {isEmpty ? (
                      <div style={{ ...s.fieldValue, color: 'var(--text-muted)', fontStyle: 'italic', opacity: 0.6 }}>—</div>
                    ) : isArray && Array.isArray(val) ? (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
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

              {!selectedMeta && (
                <div style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)', fontSize: '12.5px' }}>
                  No extra metadata found for this table.
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );

  // ── Delete Table Confirmation Modal ──────────────────────────────────────────
  const DeleteTableConfirmation = () => {
    if (!deleteTableId) return null;

    return (
      <div
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
          backdropFilter: 'blur(3px)', zIndex: 10001,
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px',
        }}
        onClick={() => !isDeleting && setDeleteTableId(null)}
      >
        <div
          style={{
            background: '#0f1117', border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: '14px', padding: '22px', maxWidth: '400px', width: '100%',
            boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
            <div style={{
              width: '32px', height: '32px', borderRadius: '8px',
              background: 'rgba(239,68,68,0.15)', display: 'flex',
              alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <AlertCircle size={18} style={{ color: '#f87171' }} />
            </div>
            <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Delete Table
            </span>
          </div>

          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '18px', lineHeight: 1.5 }}>
            Are you sure you want to delete table <strong>"{deleteTableId}"</strong>? This table and all its data will be permanently removed.
          </p>

          {isDeleting && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '8px', padding: '10px',
              borderRadius: '8px', marginBottom: '14px',
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
              fontSize: '12px', color: '#f87171',
            }}>
              <Loader2 size={14} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
              <span>Deleting table…</span>
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button
              onClick={() => setDeleteTableId(null)}
              disabled={isDeleting}
              style={{
                padding: '8px 16px', borderRadius: '8px',
                border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)',
                cursor: isDeleting ? 'not-allowed' : 'pointer',
                fontSize: '12.5px', fontWeight: 600, opacity: isDeleting ? 0.5 : 1,
              }}
            >
              Cancel
            </button>
            <button
              onClick={() => handleDeleteTable(deleteTableId)}
              disabled={isDeleting}
              style={{
                padding: '8px 18px', borderRadius: '8px',
                border: '1px solid #b91c1c', background: '#dc2626', color: '#fff',
                cursor: isDeleting ? 'not-allowed' : 'pointer',
                fontSize: '12.5px', fontWeight: 600,
                display: 'flex', alignItems: 'center', gap: '6px',
                opacity: isDeleting ? 0.8 : 1,
              }}
            >
              {isDeleting ? (
                <>
                  <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                  <span>Deleting…</span>
                </>
              ) : (
                <>
                  <Trash2 size={13} />
                  <span>Delete Table</span>
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
            <Database size={17} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '14.5px', fontWeight: 700, color: 'var(--text-primary)' }}>
                {databaseName}
              </span>
              {view === 'detail' && selectedTable && (
                <>
                  <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>/</span>
                  <span style={{ color: 'var(--accent-cyan)', fontSize: '14px', fontWeight: 600 }}>
                    {selectedTable}
                  </span>
                </>
              )}
            </div>
            <button style={s.closeBtn} onClick={handleClose} title="Close">
              <X size={17} />
            </button>
          </div>

          {/* Body */}
          <div style={s.body}>
            {view === 'list' && <ListView />}
            {view === 'detail' && <DetailView />}
          </div>
        </div>
      </div>

      <DeleteTableConfirmation />

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </>
  );

  return ReactDOM.createPortal(content, document.body);
};
