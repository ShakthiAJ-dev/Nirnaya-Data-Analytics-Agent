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
  messages: Message[];
  model?: string;
}

export interface LLMCredentials {
  anthropicApiKey: string;
  openaiApiKey: string;
  geminiApiKey?: string;
  customEndpoint?: string;
  preferredProvider?: 'anthropic' | 'openai';
}

// WebSocket step event
export interface StepEvent {
  type: 'step';
  chat_id: string;
  turn_id: string;
  seq: number;
  name: string;
  status: 'in_progress' | 'done' | 'error';
  title: string;
  detail: string;
  reasoning: string;
  artifact_id?: string;
  worker_id?: string;
  ts: string;
}

// Final event with artifacts
export interface Artifact {
  artifact_id: string;
  type: 'kpi' | 'chart' | 'table';
  title: string;
  note: string;
  key_numbers: Record<string, any>;
  status: 'fresh' | 'error';
  error_message?: string;
  config: Record<string, any>;
  result_data: Record<string, any>[];
  sql_query: string;
}

export interface FinalEvent {
  type: 'final';
  chat_id: string;
  turn_id: string;
  seq: number;
  markdown: string;
  artifacts: Artifact[];
  follow_up_questions: string[];
  ts: string;
}

export interface WSAckFrame {
  type: 'ack';
  transactionId: string;
  content: string;
  turn_id: string;
  chat_id: string;
  project_id: string;
  timestamp: number;
}
