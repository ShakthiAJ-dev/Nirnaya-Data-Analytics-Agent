import React, { useState, useRef } from 'react';
import { X, Database, Upload, FileSpreadsheet, Check, AlertCircle } from 'lucide-react';
import { databaseService } from '../services/databaseService';

interface NewDatabaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDatabaseCreated: () => void;
}

type Step = 'name' | 'upload' | 'done';

export const NewDatabaseModal: React.FC<NewDatabaseModalProps> = ({
  isOpen,
  onClose,
  onDatabaseCreated,
}) => {
  const [step, setStep] = useState<Step>('name');
  const [dbName, setDbName] = useState('');
  const [createdDbId, setCreatedDbId] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'processing' | 'done' | 'error'>('idle');
  const [uploadedTables, setUploadedTables] = useState<any[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const handleClose = () => {
    setStep('name');
    setDbName('');
    setCreatedDbId('');
    setError('');
    setUploadStatus('idle');
    setUploadedTables([]);
    onClose();
  };

  const handleCreateDb = async () => {
    if (!dbName.trim()) { setError('Database name is required.'); return; }
    setError('');
    setIsLoading(true);
    try {
      const db = await databaseService.createDatabase({ name: dbName.trim() });
      setCreatedDbId(db.id);
      setStep('upload');
      onDatabaseCreated();
    } catch (e: any) {
      setError(e.message || 'Failed to create database.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !createdDbId) return;

    setUploadStatus('uploading');
    setError('');
    try {
      // Step 1+2: presign + direct PUT upload
      setUploadStatus('uploading');
      // Step 3: process
      setUploadStatus('processing');
      const result = await databaseService.uploadFile(createdDbId, file);
      setUploadedTables(result.tables_created || []);
      setUploadStatus('done');
      setStep('done');
      onDatabaseCreated();
    } catch (e: any) {
      setError(e.message || 'Upload failed.');
      setUploadStatus('error');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div
        className="modal-content"
        style={{ maxWidth: '460px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '32px', height: '32px', borderRadius: '8px',
              background: 'rgba(6,182,212,0.15)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <Database size={16} style={{ color: 'var(--accent-cyan)' }} />
            </div>
            <div>
              <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                {step === 'done' ? 'Database Ready' : 'New Database'}
              </h2>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
                {step === 'name' && 'Give your database a name'}
                {step === 'upload' && 'Optionally upload a data file now'}
                {step === 'done' && `${uploadedTables.length} table(s) created`}
              </p>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={handleClose}>
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px' }}>
          {step === 'name' && (
            <div>
              <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '8px' }}>
                Database Name
              </label>
              <input
                type="text"
                value={dbName}
                onChange={(e) => setDbName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateDb()}
                placeholder="e.g. Sales Q4, Customer Data, …"
                autoFocus
                style={{
                  width: '100%', padding: '10px 14px', borderRadius: '8px',
                  border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)',
                  fontSize: '14px', outline: 'none', boxSizing: 'border-box',
                }}
              />
            </div>
          )}

          {step === 'upload' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{
                padding: '20px', borderRadius: '10px',
                border: '1px dashed rgba(255,255,255,0.15)',
                background: 'rgba(255,255,255,0.02)', textAlign: 'center',
              }}>
                <input
                  type="file"
                  ref={fileInputRef}
                  accept=".csv,.xlsx,.xls,.parquet"
                  onChange={handleFileUpload}
                  style={{ display: 'none' }}
                  id="db-file-input"
                />
                <Upload size={28} style={{ color: 'var(--accent-cyan)', margin: '0 auto 8px', display: 'block', opacity: 0.7 }} />
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '0 0 12px' }}>
                  Upload a CSV, Excel, or Parquet file into <strong style={{ color: 'var(--text-primary)' }}>{dbName}</strong>
                </p>

                {uploadStatus === 'idle' && (
                  <button
                    type="button"
                    className="btn-modal-primary"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <FileSpreadsheet size={14} />
                    <span>Choose File</span>
                  </button>
                )}

                {(uploadStatus === 'uploading' || uploadStatus === 'processing') && (
                  <div style={{ fontSize: '13px', color: 'var(--accent-cyan)' }}>
                    {uploadStatus === 'uploading' ? '⬆ Uploading to storage…' : '⚙ Processing tables…'}
                  </div>
                )}
              </div>
            </div>
          )}

          {step === 'done' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-emerald, #34d399)' }}>
                <Check size={18} />
                <span style={{ fontWeight: 600 }}>Upload complete</span>
              </div>
              {uploadedTables.map((t: any) => (
                <div
                  key={t.table_name}
                  style={{
                    padding: '10px 12px', borderRadius: '8px',
                    background: 'rgba(52,211,153,0.06)', border: '1px solid rgba(52,211,153,0.15)',
                    fontSize: '13px', color: 'var(--text-secondary)',
                  }}
                >
                  <strong style={{ color: 'var(--text-primary)' }}>{t.table_name}</strong>
                  {' '}— {t.row_count?.toLocaleString()} rows, {t.columns?.length} columns
                </div>
              ))}
            </div>
          )}

          {error && (
            <div style={{
              marginTop: '12px', padding: '10px 12px', borderRadius: '8px',
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
              display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#f87171',
            }}>
              <AlertCircle size={14} />
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '16px 24px', borderTop: '1px solid rgba(255,255,255,0.07)',
          display: 'flex', justifyContent: 'flex-end', gap: '10px',
        }}>
          {step === 'name' && (
            <>
              <button type="button" className="btn-modal-cancel" onClick={handleClose}>Cancel</button>
              <button type="button" className="btn-modal-primary" onClick={handleCreateDb} disabled={isLoading}>
                {isLoading ? 'Creating…' : 'Create'}
              </button>
            </>
          )}
          {step === 'upload' && (
            <>
              <button type="button" className="btn-modal-cancel" onClick={handleClose}>Skip for now</button>
            </>
          )}
          {step === 'done' && (
            <button type="button" className="btn-modal-primary" onClick={handleClose}>Done</button>
          )}
        </div>
      </div>
    </div>
  );
};
