import { api } from './apiClient';
import type { Database } from '../types';

export interface CreateDatabasePayload {
  name: string;
}

export interface PresignUploadResponse {
  upload_url: string;
  file_path: string;
  expires_in: number;
}

export interface UploadProcessResponse {
  database_id: string;
  tables_created: any[];
  metadata_path?: string;
  message: string;
}

export interface PreviewResponse {
  rows: Record<string, any>[];
  columns: string[];
  total_count: number;
  has_more: boolean;
  offset: number;
  limit: number;
}

export interface DemoCreateResponse {
  database_id: string;
  database_name: string;
  schema_name: string;
  metadata_path?: string;
}

export const databaseService = {
  getDatabases: async (): Promise<Database[]> => {
    const res = await api.get<{ success: boolean; data: { databases: Database[]; total: number } }>('/databases');
    return res.data.databases;
  },

  getDatabase: async (databaseId: string): Promise<Database> => {
    const res = await api.get<{ success: boolean; data: Database }>(`/databases/${databaseId}`);
    return res.data;
  },

  createDatabase: async (payload: CreateDatabasePayload): Promise<Database> => {
    const res = await api.post<{ success: boolean; data: Database }>('/databases', payload);
    return res.data;
  },

  /** Create the pre-loaded Music E-commerce demo database for the current session. Idempotent. */
  createDemoDatabase: async (): Promise<DemoCreateResponse> => {
    return api.post<DemoCreateResponse>('/demo/create', {});
  },

  deleteDatabase: async (databaseId: string): Promise<void> => {
    await api.delete(`/databases/${databaseId}`);
  },

  getMetadata: async (databaseId: string): Promise<any> => {
    const res = await api.get<{ success: boolean; data: any }>(`/databases/${databaseId}/metadata`);
    return res.data;
  },

  presignUpload: async (databaseId: string, filename: string): Promise<PresignUploadResponse> => {
    const res = await api.post<{ success: boolean; data: PresignUploadResponse }>(
      `/databases/${databaseId}/upload/presign`,
      { filename }
    );
    return res.data;
  },

  processUpload: async (databaseId: string, filePath: string, filename: string): Promise<UploadProcessResponse> => {
    const res = await api.post<{ success: boolean; data: UploadProcessResponse }>(
      `/databases/${databaseId}/upload/process`,
      { file_path: filePath, filename }
    );
    return res.data;
  },

  previewTable: async (databaseId: string, tableName: string, limit = 20, offset = 0): Promise<PreviewResponse> => {
    const res = await api.get<{ success: boolean; data: PreviewResponse }>(
      `/databases/${databaseId}/tables/${encodeURIComponent(tableName)}/preview?limit=${limit}&offset=${offset}`
    );
    return res.data;
  },

  uploadFile: async (databaseId: string, file: File): Promise<UploadProcessResponse> => {
    const { upload_url, file_path } = await databaseService.presignUpload(databaseId, file.name);

    const uploadRes = await fetch(upload_url, {
      method: 'PUT',
      body: file,
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
    });

    if (!uploadRes.ok) {
      throw new Error(`Failed to upload file to storage: ${uploadRes.statusText}`);
    }

    return databaseService.processUpload(databaseId, file_path, file.name);
  },

  updateTableMetadata: async (databaseId: string, tableName: string, updates: Record<string, unknown>): Promise<any> => {
    const res = await api.patch<{ success: boolean; data: any }>(
      `/databases/${databaseId}/tables/${encodeURIComponent(tableName)}/metadata`,
      updates,
    );
    return res.data;
  },

  deleteTable: async (databaseId: string, tableName: string): Promise<void> => {
    await api.delete(`/databases/${databaseId}/tables/${encodeURIComponent(tableName)}`);
  },
};
