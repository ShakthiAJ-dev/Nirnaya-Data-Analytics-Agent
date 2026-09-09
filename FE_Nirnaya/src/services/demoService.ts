import { api } from './apiClient';
import type { Project } from '../types';
import { DEFAULT_DEMO_DATASETS, INITIAL_DEMO_PROJECT } from '../constants/demoData';

export interface PreviewResponse {
  rows: Record<string, any>[];
  columns: string[];
  total_count: number;
  has_more: boolean;
  offset: number;
  limit: number;
}

interface RawDemoProjectResponse {
  id: string;
  name: string;
  description: string;
  is_demo: boolean;
  datasets?: any[];
  raw_metadata?: any;
}

export const demoService = {
  /**
   * Fetches the demo project metadata from the backend and normalises field
   * names from snake_case (Python) to camelCase (TypeScript Project type).
   */
  async getDemoProject(): Promise<Project> {
    try {
      const raw = await api.get<RawDemoProjectResponse>('/demo/project');

      const datasets = (raw.datasets && raw.datasets.length > 0)
        ? raw.datasets.map((d: any) => ({
            name: d.name,
            tableName: d.tableName,
            rows: d.rows ?? 0,
            columns: d.columns ?? [],
            description: d.description ?? '',
            useCase: d.useCase ?? '',
            keyNotes: d.keyNotes ?? '',
            domainTags: d.domainTags ?? [],
          }))
        : DEFAULT_DEMO_DATASETS;

      return {
        id: raw.id || 'demo-project',
        name: raw.name || 'Music E-commerce (Demo)',
        title: raw.name || 'Music E-commerce (Demo)',
        description: raw.description,
        is_demo: true,
        isDemo: true,
        datasets,
        raw_metadata: raw.raw_metadata ?? null,
        datasetsCount: datasets.length,
        session_id: 'demo-session',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        messages: [],
      };
    } catch (err) {
      console.warn('[demoService] Backend demo endpoint unavailable, using initial demo project fallback:', err);
      return INITIAL_DEMO_PROJECT as Project;
    }
  },

  /**
   * Sends a chat message to the demo backend using the server's Bedrock configuration.
   */
  async sendDemoChat(message: string): Promise<any> {
    return api.post<any>('/demo/chat', { message });
  },

  /**
   * Preview rows from a demo table with pagination.
   */
  async previewDemoTable(tableName: string, limit = 20, offset = 0): Promise<PreviewResponse> {
    const res = await api.get<{ success: boolean; data: PreviewResponse }>(
      `/demo/tables/${encodeURIComponent(tableName)}/preview?limit=${limit}&offset=${offset}`
    );
    return res.data;
  },
};
