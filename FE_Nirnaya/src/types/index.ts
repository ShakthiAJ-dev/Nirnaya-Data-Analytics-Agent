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

export interface Database {
  id: string;
  name: string;
  schema_name: string;
  is_demo: boolean;
  metadata_path?: string;
  created_at: string;
  metadata?: any;
}

export interface DatasetMetadata {
  name: string;
  tableName: string;
  rows: number;
  columns: string[];
  description: string;
  useCase?: string;
  keyNotes?: string;
  domainTags?: string[];
}

export interface Project {
  id: string;
  title: string;
  database_id?: string;
  session_id: string;
  created_at: string;
  updated_at: string;
  // Local state for the chat interface
  messages: Message[];
  model?: string;
  is_demo?: boolean;
  datasets?: DatasetMetadata[];
  name?: string;
  description?: string;
  datasetsCount?: number;
}

export interface LLMCredentials {
  anthropicApiKey: string;
  openaiApiKey: string;
  geminiApiKey?: string;
  customEndpoint?: string;
  preferredProvider?: 'anthropic' | 'openai';
}
