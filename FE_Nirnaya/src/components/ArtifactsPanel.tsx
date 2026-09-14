import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import type { Artifact } from '../types';

interface ArtifactsPanelProps {
  artifacts: Artifact[];
}

export const ArtifactsPanel: React.FC<ArtifactsPanelProps> = ({ artifacts }) => {
  const [activeTab, setActiveTab] = useState<string | null>(
    artifacts.length > 0 ? artifacts[0].artifact_id : null
  );
  const [copiedSql, setCopiedSql] = useState(false);

  if (artifacts.length === 0) return null;

  const activeArtifact = artifacts.find((a) => a.artifact_id === activeTab);

  const getIcon = (type: string) => {
    switch (type) {
      case 'kpi':
        return '📊';
      case 'chart':
        return '📈';
      case 'table':
        return '📋';
      default:
        return '📦';
    }
  };

  const handleCopySql = () => {
    if (activeArtifact?.sql_query) {
      navigator.clipboard.writeText(activeArtifact.sql_query);
      setCopiedSql(true);
      setTimeout(() => setCopiedSql(false), 2000);
    }
  };

  return (
    <div className="artifacts-panel">
      {/* Tabs */}
      <div className="artifacts-tabs">
        {artifacts.map((artifact) => (
          <button
            key={artifact.artifact_id}
            onClick={() => setActiveTab(artifact.artifact_id)}
            className={`artifact-tab ${activeTab === artifact.artifact_id ? 'active' : ''}`}
            title={artifact.title}
          >
            <span className="artifact-icon">{getIcon(artifact.type)}</span>
            <span className="artifact-label">{artifact.title}</span>
          </button>
        ))}
      </div>

      {/* Content */}
      {activeArtifact && (
        <div className="artifacts-content">
          {activeArtifact.type === 'kpi' && (
            <div className="artifact-kpi">
              <div className="kpi-title">{activeArtifact.title}</div>
              <div className="kpi-note">{activeArtifact.note}</div>
              <div className="kpi-numbers">
                {Object.entries(activeArtifact.key_numbers).map(([key, value]) => (
                  <div key={key} className="kpi-item">
                    <span className="kpi-key">{key}:</span>
                    <span className="kpi-value">{String(value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeArtifact.type === 'chart' && (
            <div className="artifact-chart">
              <div className="chart-title">{activeArtifact.title}</div>
              <div className="chart-note">{activeArtifact.note}</div>
              <div className="chart-config">
                <pre>{JSON.stringify(activeArtifact.config, null, 2)}</pre>
              </div>
              {activeArtifact.result_data.length > 0 && (
                <div className="chart-data">
                  <div className="data-count">{activeArtifact.result_data.length} rows</div>
                  <pre>{JSON.stringify(activeArtifact.result_data.slice(0, 3), null, 2)}</pre>
                </div>
              )}
            </div>
          )}

          {activeArtifact.type === 'table' && (
            <div className="artifact-table">
              <div className="table-title">{activeArtifact.title}</div>
              <div className="table-note">{activeArtifact.note}</div>
              {activeArtifact.result_data.length > 0 && (
                <div className="table-wrapper">
                  <table className="data-table">
                    <thead>
                      <tr>
                        {Object.keys(activeArtifact.result_data[0]).map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {activeArtifact.result_data.slice(0, 10).map((row, idx) => (
                        <tr key={idx}>
                          {Object.values(row).map((val, vidx) => (
                            <td key={vidx}>{String(val)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {activeArtifact.result_data.length > 10 && (
                    <div className="table-more">+{activeArtifact.result_data.length - 10} more rows</div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* SQL Query */}
          {activeArtifact.sql_query && (
            <div className="artifact-sql">
              <div className="sql-header">
                <span className="sql-icon">📝</span>
                <span className="sql-title">SQL Query</span>
                <button
                  onClick={handleCopySql}
                  className="sql-copy"
                  title="Copy SQL"
                >
                  {copiedSql ? <Check size={14} /> : <Copy size={14} />}
                </button>
              </div>
              <pre className="sql-code">{activeArtifact.sql_query}</pre>
            </div>
          )}

          {activeArtifact.status === 'error' && activeArtifact.error_message && (
            <div className="artifact-error">
              <strong>Error:</strong> {activeArtifact.error_message}
            </div>
          )}
        </div>
      )}

      <style>{`
        .artifacts-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          background: var(--bg-primary);
          border-left: 1px solid var(--border-color);
          overflow: hidden;
        }
        .artifacts-tabs {
          display: flex;
          gap: 0;
          border-bottom: 1px solid var(--border-color);
          overflow-x: auto;
          flex-shrink: 0;
        }
        .artifact-tab {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 12px 16px;
          background: transparent;
          border: none;
          border-bottom: 2px solid transparent;
          cursor: pointer;
          font-size: 13px;
          white-space: nowrap;
          color: var(--text-secondary);
          transition: all 0.2s;
          max-width: 150px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .artifact-tab:hover {
          color: var(--text-primary);
          background: var(--bg-secondary);
        }
        .artifact-tab.active {
          color: var(--text-primary);
          border-bottom-color: var(--accent-color);
        }
        .artifact-icon {
          font-size: 16px;
        }
        .artifact-label {
          text-overflow: ellipsis;
          overflow: hidden;
        }
        .artifacts-content {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }
        .artifact-kpi,
        .artifact-chart,
        .artifact-table {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .kpi-title,
        .chart-title,
        .table-title {
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .kpi-note,
        .chart-note,
        .table-note {
          font-size: 12px;
          color: var(--text-secondary);
        }
        .kpi-numbers {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 8px;
        }
        .kpi-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
          padding: 8px;
          background: var(--bg-secondary);
          border-radius: 6px;
        }
        .kpi-key {
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          color: var(--text-secondary);
        }
        .kpi-value {
          font-size: 16px;
          font-weight: 700;
          color: var(--accent-color);
        }
        .chart-config,
        .chart-data {
          background: var(--bg-secondary);
          border-radius: 6px;
          padding: 8px;
          max-height: 200px;
          overflow-y: auto;
        }
        .data-count {
          font-size: 11px;
          color: var(--text-secondary);
          margin-bottom: 6px;
        }
        pre {
          margin: 0;
          font-size: 11px;
          font-family: 'Monaco', 'Courier New', monospace;
          color: var(--text-primary);
          white-space: pre-wrap;
          word-break: break-word;
          line-height: 1.4;
        }
        .table-wrapper {
          overflow-x: auto;
          border: 1px solid var(--border-color);
          border-radius: 6px;
        }
        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
        }
        .data-table th {
          background: var(--bg-secondary);
          padding: 8px;
          text-align: left;
          font-weight: 600;
          border-bottom: 1px solid var(--border-color);
          white-space: nowrap;
        }
        .data-table td {
          padding: 8px;
          border-bottom: 1px solid var(--border-color);
        }
        .data-table tbody tr:hover {
          background: var(--bg-secondary);
        }
        .table-more {
          padding: 8px;
          font-size: 12px;
          color: var(--text-secondary);
          text-align: center;
          border-top: 1px solid var(--border-color);
          background: var(--bg-secondary);
        }
        .artifact-sql {
          margin-top: 12px;
          border: 1px solid var(--border-color);
          border-radius: 6px;
          overflow: hidden;
        }
        .sql-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border-color);
        }
        .sql-icon {
          font-size: 14px;
        }
        .sql-title {
          flex: 1;
          font-size: 12px;
          font-weight: 600;
        }
        .sql-copy {
          background: none;
          border: none;
          cursor: pointer;
          padding: 4px;
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          transition: color 0.2s;
        }
        .sql-copy:hover {
          color: var(--text-primary);
        }
        .sql-code {
          padding: 12px;
          font-size: 11px;
          max-height: 250px;
          overflow-y: auto;
        }
        .artifact-error {
          padding: 12px;
          background: #fee2e2;
          border: 1px solid #fecaca;
          border-radius: 6px;
          font-size: 12px;
          color: #991b1b;
        }
      `}</style>
    </div>
  );
};
