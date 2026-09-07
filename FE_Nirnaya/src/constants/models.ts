import type { ModelOption, Project } from '../types';

export const AVAILABLE_MODELS: ModelOption[] = [
  {
    id: 'claude-3-5-haiku',
    name: 'Claude 3.5 Haiku',
    provider: 'anthropic',
    description: 'Fast, lightweight & highly capable for quick analytics queries',
    contextWindow: '200K tokens',
    badge: 'Default • Fast',
    isDefault: true,
  },
  {
    id: 'claude-3-7-sonnet',
    name: 'Claude 3.7 Sonnet',
    provider: 'anthropic',
    description: 'Hybrid reasoning & deep multi-step data exploration',
    contextWindow: '200K tokens',
    badge: 'Reasoning',
  },
  {
    id: 'claude-3-5-sonnet',
    name: 'Claude 3.5 Sonnet',
    provider: 'anthropic',
    description: 'Most versatile balance of intelligence and analytical coding',
    contextWindow: '200K tokens',
    badge: 'Popular',
  },
  {
    id: 'gpt-4o',
    name: 'GPT-4o',
    provider: 'openai',
    description: 'Flagship multimodal model for complex data extraction',
    contextWindow: '128K tokens',
  },
  {
    id: 'gpt-4o-mini',
    name: 'GPT-4o Mini',
    provider: 'openai',
    description: 'Cost-efficient model for standard queries & filtering',
    contextWindow: '128K tokens',
  },
  {
    id: 'gemini-2-5-flash',
    name: 'Gemini 2.5 Flash',
    provider: 'google',
    description: 'Massive context for analyzing large raw datasets',
    contextWindow: '1M tokens',
    badge: 'Large Context',
  },
];

export const DEFAULT_MODEL_ID = 'claude-3-5-haiku';

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
