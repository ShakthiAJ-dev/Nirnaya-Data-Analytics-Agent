import { api } from './apiClient';
import type { Project } from '../types';

export interface CreateProjectPayload {
  database_id?: string;
}

export const projectService = {
  getProjects: async (): Promise<Project[]> => {
    const res = await api.get<{ success: boolean; data: { projects: Project[]; total: number } }>('/projects');
    return res.data.projects;
  },

  getProject: async (projectId: string): Promise<Project> => {
    const res = await api.get<{ success: boolean; data: Project }>(`/projects/${projectId}`);
    return res.data;
  },

  createProject: async (payload?: CreateProjectPayload): Promise<Project> => {
    const res = await api.post<{ success: boolean; data: Project }>('/projects', payload || {});
    return res.data;
  },

  updateProjectTitle: async (projectId: string, title: string): Promise<Project> => {
    const res = await api.patch<{ success: boolean; data: Project }>(`/projects/${projectId}/title`, { title });
    return res.data;
  },

  deleteProject: async (projectId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}`);
  },
};
