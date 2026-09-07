export interface ModelOption {
  id: string;
  name: string;
  provider: 'anthropic' | 'openai' | 'google' | 'local';
  description: string;
  contextWindow: string;
  badge?: string;
  isDefault?: boolean;
}

export interface FileAttachment {
  id: string;
  name: string;
  size: number;
  type: string;
  extension: string;
  contentSnippet?: string;
  uploadedAt: string;
}

export interface TableData {
  title?: string;
  headers: string[];
  rows: (string | number)[][];
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  model?: string;
  files?: FileAttachment[];
  sqlQuery?: string;
  tableData?: TableData;
  insights?: string[];
  suggestions?: string[];
  isStreaming?: boolean;
}

export interface ChatSession {
  id: string;
  projectId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: Message[];
  model: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  icon?: string;
  datasetsCount: number;
  createdAt: string;
}

export interface LLMCredentials {
  anthropicApiKey: string;
  openaiApiKey: string;
  geminiApiKey?: string;
  customEndpoint?: string;
  preferredProvider?: 'anthropic' | 'openai';
}
