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

  deleteDatabase: async (databaseId: string): Promise<void> => {
    await api.delete(`/databases/${databaseId}`);
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

  // Helper method that orchestrates the 2-step presigned flow
  uploadFile: async (databaseId: string, file: File): Promise<UploadProcessResponse> => {
    // 1. Get presigned URL
    const { upload_url, file_path } = await databaseService.presignUpload(databaseId, file.name);

    // 2. Upload file directly to Supabase Storage
    const uploadRes = await fetch(upload_url, {
      method: 'PUT',
      body: file,
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
      },
    });

    if (!uploadRes.ok) {
      throw new Error(`Failed to upload file to storage: ${uploadRes.statusText}`);
    }

    // 3. Tell BE to process the uploaded file
    return databaseService.processUpload(databaseId, file_path, file.name);
  },
};
