import { useState, useEffect, useCallback } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { ChatInput } from './components/ChatInput';
import { CredentialsModal } from './components/CredentialsModal';
import type {
  ChatSession,
  Message,
  Project,
  FileAttachment,
  LLMCredentials,
} from './types';
import {
  DEFAULT_MODEL_ID,
  DEFAULT_PROJECTS,
} from './constants/models';
import { generateAnalyticsResponse } from './services/analyticsAgent';
import { useSession } from './hooks/useSession';
import { useModels } from './hooks/useModels';

const STORAGE_KEYS = {
  SESSIONS: 'nirnaya_chat_sessions_v1',
  CREDENTIALS: 'nirnaya_llm_credentials_v1',
  SELECTED_MODEL: 'nirnaya_selected_model_v1',
  ACTIVE_PROJECT: 'nirnaya_active_project_id_v1',
};

function App() {
  // ── Backend session + WebSocket (auto-init on mount) ────────────────────
  const { sessionStatus, submitKey } = useSession();

  // ── Live models from BE (populated once session is ready + keys stored) ─────
  const { models: availableModels, refresh: refreshModels } = useModels(sessionStatus === 'ready');

  // 1. Projects State
  const [projects] = useState<Project[]>(DEFAULT_PROJECTS);
  const [currentProjectId, setCurrentProjectId] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEYS.ACTIVE_PROJECT) || DEFAULT_PROJECTS[0].id;
  });

  const currentProject =
    projects.find((p) => p.id === currentProjectId) || projects[0];

  // 2. Selected Model (Default: Claude 3.5 Haiku)
  const [selectedModelId, setSelectedModelId] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEYS.SELECTED_MODEL) || DEFAULT_MODEL_ID;
  });

  // 3. Credentials State
  const [credentials, setCredentials] = useState<LLMCredentials>(() => {
    const saved = localStorage.getItem(STORAGE_KEYS.CREDENTIALS);
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch {
        // fallback
      }
    }
    return {
      anthropicApiKey: '',
      openaiApiKey: '',
      preferredProvider: 'anthropic',
    };
  });

  const [isCredentialsModalOpen, setIsCredentialsModalOpen] = useState(false);

  // 4. Chat Sessions State
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    const saved = localStorage.getItem(STORAGE_KEYS.SESSIONS);
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch {
        // fallback
      }
    }
    // Initial sample session
    return [
      {
        id: 'session-demo-1',
        projectId: DEFAULT_PROJECTS[0].id,
        title: 'Q3 Revenue Variance & Margin Drilldown',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        model: 'claude-3-5-haiku',
        messages: [
          {
            id: 'msg-demo-1',
            role: 'user',
            content: 'Can you analyze our Q3 gross revenue breakdown and highlight if any categories had margin compression?',
            timestamp: '11:42 AM',
            model: 'claude-3-5-haiku',
          },
          {
            id: 'msg-demo-2',
            role: 'assistant',
            content: 'Analyzing quarterly metrics for **E-Commerce Q3 Performance**: Overall gross revenue reached **$1,480,000** (+18.4% QoQ). However, blended gross margin softened by 1.8% primarily driven by higher fulfillment and carrier surcharges in Add-on Services.',
            timestamp: '11:42 AM',
            model: 'claude-3-5-haiku',
            sqlQuery: `SELECT 
    product_category,
    SUM(gross_revenue) AS total_revenue,
    ROUND(AVG(gross_margin_pct), 2) AS avg_margin_pct,
    SUM(order_count) AS total_orders
FROM sales_transactions
WHERE date_trunc('quarter', transaction_date) = '2026-Q3'
GROUP BY product_category
ORDER BY total_revenue DESC;`,
            tableData: {
              title: 'Q3 Category Revenue & Margin Matrix',
              headers: ['Category', 'Gross Revenue', 'Avg Margin', 'Total Orders'],
              rows: [
                ['Enterprise Suite', '$680,000', '78.4%', '420'],
                ['Pro Subscriptions', '$440,000', '82.1%', '2,200'],
                ['Add-on Services', '$240,000', '52.3%', '860'],
                ['Custom Integrations', '$120,000', '64.0%', '45'],
              ],
            },
            insights: [
              'Enterprise Suite leads expansion at 46% of aggregate revenue.',
              'Add-on Services margins dipped by 420 bps due to third-party API surcharges.',
              'Strategic Decision (Nirnaya): Shift high-frequency customer accounts to bulk licensing tiers.',
            ],
            suggestions: [
              'Break down revenue by geographic region',
              'What is the payback period for Enterprise accounts?',
            ],
          },
        ],
      },
    ];
  });

  const [currentSessionId, setCurrentSessionId] = useState<string | null>(() => {
    return sessions.length > 0 ? sessions[0].id : null;
  });

  const [isLoading, setIsLoading] = useState(false);

  // Sync state to LocalStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.SESSIONS, JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CREDENTIALS, JSON.stringify(credentials));
  }, [credentials]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.SELECTED_MODEL, selectedModelId);
  }, [selectedModelId]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.ACTIVE_PROJECT, currentProjectId);
  }, [currentProjectId]);

  // Handlers
  const handleNewChat = () => {
    setCurrentSessionId(null);
  };

  // Keyboard shortcut: Ctrl+N or Cmd+N for New Chat
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        handleNewChat();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const activeMessages = currentSession ? currentSession.messages : [];

  const handleSelectSession = (sessionId: string) => {
    setCurrentSessionId(sessionId);
  };

  const handleDeleteSession = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    if (currentSessionId === sessionId) {
      setCurrentSessionId(null);
    }
  };

  const handleSelectProject = (projectId: string) => {
    setCurrentProjectId(projectId);
    // Find if there's an existing session in that project
    const projectSession = sessions.find((s) => s.projectId === projectId);
    if (projectSession) {
      setCurrentSessionId(projectSession.id);
    } else {
      setCurrentSessionId(null);
    }
  };

  const handleSaveCredentials = useCallback(async (newCreds: LLMCredentials) => {
    setCredentials(newCreds);

    // ── Submit keys to the BE (encrypted + stored in Redis) ──────────────
    const tasks: Promise<void>[] = [];

    if (newCreds.anthropicApiKey.trim()) {
      tasks.push(submitKey('anthropic', newCreds.anthropicApiKey));
    }
    if (newCreds.openaiApiKey.trim()) {
      tasks.push(submitKey('openai', newCreds.openaiApiKey));
    }

    if (tasks.length > 0) {
      await Promise.all(tasks);
      console.debug('[App] All LLM keys stored on BE successfully');
      // ── Re-fetch model list immediately ───────────────────────────
      await refreshModels();
    }
  }, [submitKey, refreshModels]);

  const handleSendMessage = async (
    prompt: string,
    files: FileAttachment[],
    modelId: string
  ) => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // Format new user message (Right-aligned)
    const userMessage: Message = {
      id: `msg-user-${Date.now()}`,
      role: 'user',
      content: prompt,
      timestamp: timeStr,
      files: files.length > 0 ? files : undefined,
      model: modelId,
    };

    let targetSessionId = currentSessionId;

    // If starting a fresh chat session
    if (!targetSessionId) {
      const newSessionTitle =
        prompt.length > 36 ? `${prompt.substring(0, 36)}...` : prompt || `Analysis: ${files[0]?.name || 'Data'}`;
      const newSession: ChatSession = {
        id: `session-${Date.now()}`,
        projectId: currentProjectId,
        title: newSessionTitle,
        createdAt: now.toISOString(),
        updatedAt: now.toISOString(),
        model: modelId,
        messages: [userMessage],
      };

      targetSessionId = newSession.id;
      setSessions((prev) => [newSession, ...prev]);
      setCurrentSessionId(targetSessionId);
    } else {
      setSessions((prev) =>
        prev.map((s) =>
          s.id === targetSessionId
            ? {
                ...s,
                updatedAt: now.toISOString(),
                messages: [...s.messages, userMessage],
              }
            : s
        )
      );
    }

    setIsLoading(true);

    try {
      // Streamed response generation
      const agentResponse = await generateAnalyticsResponse(
        prompt,
        currentProject.name,
        files,
        modelId
      );

      const assistantMessage: Message = {
        id: `msg-assistant-${Date.now()}`,
        role: 'assistant',
        content: agentResponse.content || '',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        model: modelId,
        sqlQuery: agentResponse.sqlQuery,
        tableData: agentResponse.tableData,
        insights: agentResponse.insights,
        suggestions: agentResponse.suggestions,
      };

      setSessions((prev) =>
        prev.map((s) =>
          s.id === targetSessionId
            ? {
                ...s,
                updatedAt: new Date().toISOString(),
                messages: [...s.messages, assistantMessage],
              }
            : s
        )
      );
    } catch (err) {
      console.error('Error generating analytics response:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="nirnaya-app">
      {/* 1. Left Hand Side Sidebar (Credentials, New Chat, Project Switcher, History) */}
      <Sidebar
        currentSessionId={currentSessionId}
        sessions={sessions.filter((s) => s.projectId === currentProjectId)}
        currentProject={currentProject}
        projects={projects}
        credentials={credentials}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onSelectProject={handleSelectProject}
        onOpenCredentials={() => setIsCredentialsModalOpen(true)}
      />

      {/* 2. Main Chat Area (Right-aligned User, Left-aligned Agent, Empty State) */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>
        <ChatArea
          currentProject={currentProject}
          messages={activeMessages}
          selectedModelId={selectedModelId}
          isLoading={isLoading}
          onSendSuggestedPrompt={(suggested) =>
            handleSendMessage(suggested, [], selectedModelId)
          }
          availableModels={availableModels}
          onOpenCredentials={() => setIsCredentialsModalOpen(true)}
        />

        {/* 3. Bottom Chat Bar (Plus icon for files, Default Haiku model selector, Send button) */}
        <ChatInput
          onSendMessage={handleSendMessage}
          selectedModelId={selectedModelId}
          onSelectModel={(modelId) => setSelectedModelId(modelId)}
          isLoading={isLoading}
          availableModels={availableModels}
          onOpenCredentials={() => setIsCredentialsModalOpen(true)}
        />
      </div>

      {/* 4. LLM Credentials Modal */}
      <CredentialsModal
        isOpen={isCredentialsModalOpen}
        onClose={() => setIsCredentialsModalOpen(false)}
        credentials={credentials}
        onSave={handleSaveCredentials}
      />
    </div>
  );
}

export default App;
