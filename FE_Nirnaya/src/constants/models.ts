import type { ModelOption, Project } from '../types';

export const AVAILABLE_MODELS: ModelOption[] = [];

export const DEFAULT_MODEL_ID = '';

export const DEFAULT_PROJECTS: Project[] = [
  {
    id: 'proj-ecommerce-q3',
    name: 'E-Commerce Q3 Performance',
    description: 'Revenue, margin, customer acquisition & cohort retention analysis',
    datasetsCount: 4,
    createdAt: '2026-08-15',
  },
  {
    id: 'proj-churn-intel',
    name: 'SaaS Churn Intelligence',
    description: 'Customer health scores, churn triggers & usage drop detection',
    datasetsCount: 2,
    createdAt: '2026-08-28',
  },
  {
    id: 'proj-supply-chain',
    name: 'Supply Chain & Inventory',
    description: 'Lead times, buffer stock variance, supplier SLA analytics',
    datasetsCount: 3,
    createdAt: '2026-09-01',
  },
];
