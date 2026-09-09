import { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { ChatInput } from './components/ChatInput';
import { CredentialsModal } from './components/CredentialsModal';
import { NewProjectModal } from './components/NewProjectModal';
import { NewDatabaseModal } from './components/NewDatabaseModal';
import type {
  Project,
  Database,
  Message,
  FileAttachment,
  LLMCredentials,
} from './types';
import { DEFAULT_MODEL_ID } from './constants/models';
import { useSession } from './hooks/useSession';
import { useModels } from './hooks/useModels';
import { projectService } from './services/projectService';
import { databaseService } from './services/databaseService';

const STORAGE_KEYS = {
  CREDENTIALS: 'nirnaya_llm_credentials_v1',
  SELECTED_MODEL: 'nirnaya_selected_model_v1',
};

// ---------------------------------------------------------------------------
// Helper to build chat payload extra fields
// ---------------------------------------------------------------------------
function buildChatPayload(projectId: string, databaseId: string | undefined, modelId: string) {
  return {
    project_id: projectId,
    database_id: databaseId ?? null,
    model_id: modelId,
  };
}

function App() {
  // ── Backend session + WebSocket (auto-init on mount) ──────────────────────
  const { sessionStatus, submitKey, wsClient, onWSMessage } = useSession();

  // ── Live models from BE ───────────────────────────────────────────────────
  const { models: availableModels, refresh: refreshModels } = useModels(sessionStatus === 'ready');

  // ── Projects & Databases — real BE state ─────────────────────────────────
  const [projects, setProjects] = useState<Project[]>([]);
  const [databases, setDatabases] = useState<Database[]>([]);
  const [isLoadingData, setIsLoadingData] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  // pendingDatabaseId: the database selected for next/current chat (before project exists)
  const [pendingDatabaseId, setPendingDatabaseId] = useState<string>('demo-database');

  // ── Modal state ───────────────────────────────────────────────────────────
  const [isNewProjectModalOpen, setIsNewProjectModalOpen] = useState(false);
  const [isNewDatabaseModalOpen, setIsNewDatabaseModalOpen] = useState(false);
  const [isCredentialsModalOpen, setIsCredentialsModalOpen] = useState(false);

  // ── Upload-to-database state (from sidebar) ───────────────────────────────
  const [uploadTargetDbId, setUploadTargetDbId] = useState<string | null>(null);
  const sidebarUploadRef = useRef<HTMLInputElement | null>(null);

  // ── Streaming state: map txId → projectId+placeholderId ──────────────────
  const streamingRef = useRef<Record<string, { projectId: string; placeholderId: string }>>({});

  // ── Selected model ────────────────────────────────────────────────────────
  const [selectedModelId, setSelectedModelId] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEYS.SELECTED_MODEL) || DEFAULT_MODEL_ID;
  });

  // ── Credentials ───────────────────────────────────────────────────────────
  const [credentials, setCredentials] = useState<LLMCredentials>(() => {
    const saved = localStorage.getItem(STORAGE_KEYS.CREDENTIALS);
    if (saved) {
      try { return JSON.parse(saved); } catch { /* fallback */ }
    }
    return { anthropicApiKey: '', openaiApiKey: '', preferredProvider: 'anthropic' };
  });

  // ── Chat state ────────────────────────────────────────────────────────────
  const [isLoading, setIsLoading] = useState(false);

  // ---------------------------------------------------------------------------
  // Helpers to get project/database
  // ---------------------------------------------------------------------------
  const currentProject = projects.find((p) => p.id === currentProjectId) ?? null;
  const activeDatabase = currentProject?.database_id
    ? databases.find((d) => d.id === currentProject.database_id)
    : databases.find((d) => d.is_demo) ?? databases[0];

  // ---------------------------------------------------------------------------
  // Subscribe to WS frames → handle stream / complete / error
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const unsub = onWSMessage((frame) => {
      const entry = streamingRef.current[frame.transactionId];
      if (!entry) return;
      const { projectId, placeholderId } = entry;

      if (frame.type === 'stream') {
        setProjects((prev) =>
          prev.map((p) =>
            p.id === projectId
              ? {
                  ...p,
                  messages: (p.messages || []).map((m) =>
                    m.id === placeholderId
                      ? { ...m, content: (m.content || '') + (frame.content || '') }
                      : m
                  ),
                }
              : p
          )
        );
      }

      if (frame.type === 'complete' || frame.type === 'error') {
        setProjects((prev) =>
          prev.map((p) =>
            p.id === projectId
              ? {
                  ...p,
                  messages: (p.messages || []).map((m) =>
                    m.id === placeholderId
                      ? {
                          ...m,
                          content: m.content || (frame.type === 'error' ? '*(Agent error)*' : ''),
                          isStreaming: false,
                          sqlQuery: (frame as any).sql_query,
                          tableData: (frame as any).table_data,
                          insights: (frame as any).insights,
                          suggestions: (frame as any).suggestions,
                        }
                      : m
                  ),
                }
              : p
          )
        );
        delete streamingRef.current[frame.transactionId];
        setIsLoading(false);
      }
    });
    return unsub;
  }, [onWSMessage]);

  // ---------------------------------------------------------------------------
  // Fetch real BE data once session is ready
  // ---------------------------------------------------------------------------
  // ── Fetch Demo Project on mount ──────────────────────────────────────────
  useEffect(() => {
    const fetchDemo = async () => {
      try {
        const { demoService } = await import('./services/demoService');
        const demoProj = await demoService.getDemoProject();
        setProjects((prev) => {
          const existingDemoIndex = prev.findIndex((p) => p.is_demo || p.id === demoProj.id);
          if (existingDemoIndex >= 0) {
            const updated = [...prev];
            updated[existingDemoIndex] = { ...updated[existingDemoIndex], ...demoProj };
            return updated;
          }
          return [demoProj, ...prev];
        });
      } catch (err) {
        console.error('[App] Failed to fetch demo project:', err);
      }
    };
    fetchDemo();
  }, []);

  // ---------------------------------------------------------------------------
  // Fetch real BE data once session is ready
  // ---------------------------------------------------------------------------
  const fetchAllData = useCallback(async () => {
    setIsLoadingData(true);
    try {
      const [projs, dbs] = await Promise.all([
        projectService.getProjects(),
        databaseService.getDatabases(),
      ]);

      setProjects((prev) => {
        const demoProj = prev.find((p) => p.is_demo || p.id === 'demo-project');
        const localMessages: Record<string, Message[]> = {};
        prev.forEach((p) => { localMessages[p.id] = p.messages || []; });
        
        const mergedUserProjs = projs.map((p) => ({ ...p, messages: localMessages[p.id] || [] }));
        if (demoProj && !mergedUserProjs.find((p) => p.id === demoProj.id)) {
          return [demoProj, ...mergedUserProjs];
        }
        return mergedUserProjs;
      });
      setDatabases(dbs);

      // Auto-select demo project or first project if none selected
      setCurrentProjectId((cur) => {
        if (cur) return cur;
        return projs[0]?.id ?? 'demo-project';
      });
    } catch (err) {
      console.error('[App] Failed to load projects/databases:', err);
    } finally {
      setIsLoadingData(false);
    }
  }, []);

  // Fetch projects + databases once session is ready
  useEffect(() => {
    if (sessionStatus === 'ready') fetchAllData();
  }, [sessionStatus, fetchAllData]);

  // ---------------------------------------------------------------------------
  // Persist selected model
  // ---------------------------------------------------------------------------
  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.SELECTED_MODEL, selectedModelId);
  }, [selectedModelId]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CREDENTIALS, JSON.stringify(credentials));
  }, [credentials]);

  // ---------------------------------------------------------------------------
  // Keyboard shortcut: Ctrl/Cmd+N → New Chat modal
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        setIsNewProjectModalOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // ---------------------------------------------------------------------------
  // Handlers: Credentials
  // ---------------------------------------------------------------------------
  const handleSaveCredentials = useCallback(async (newCreds: LLMCredentials) => {
    setCredentials(newCreds);
    const tasks: Promise<void>[] = [];
    if (newCreds.anthropicApiKey.trim()) tasks.push(submitKey('anthropic', newCreds.anthropicApiKey));
    if (newCreds.openaiApiKey.trim()) tasks.push(submitKey('openai', newCreds.openaiApiKey));
    if (tasks.length > 0) {
      await Promise.all(tasks);
      await refreshModels();
    }
  }, [submitKey, refreshModels]);

  // ---------------------------------------------------------------------------
  // Handlers: Projects
  // ---------------------------------------------------------------------------
  const handleSelectProject = (projectId: string) => {
    setCurrentProjectId(projectId);
    const proj = projects.find((p) => p.id === projectId);
    if (proj?.is_demo || proj?.isDemo || proj?.id === 'demo-project') {
      setPendingDatabaseId('demo-database');
    } else if (proj?.database_id) {
      setPendingDatabaseId(proj.database_id);
    }
  };

  // Select a database (pre-project): sets pending db; for demo also activates demo project
  const handleSelectDatabase = (dbId: string) => {
    setPendingDatabaseId(dbId);
    if (dbId === 'demo-database') {
      const demoProj = projects.find((p) => p.is_demo || p.isDemo || p.id === 'demo-project');
      if (demoProj) setCurrentProjectId(demoProj.id);
      else setCurrentProjectId(null);
    }
    // For user databases: don't change current project (user must create a new chat)
  };

  const handleCreateProject = async (databaseId?: string) => {
    if (databaseId === 'demo-database') {
      // Demo doesn't create a real project — just activate demo project
      const demoProj = projects.find((p) => p.is_demo || p.isDemo || p.id === 'demo-project');
      if (demoProj) {
        setCurrentProjectId(demoProj.id);
        setPendingDatabaseId('demo-database');
      }
      return;
    }
    const newProject = await projectService.createProject({ database_id: databaseId });
    setProjects((prev) => [{ ...newProject, messages: [] }, ...prev]);
    setCurrentProjectId(newProject.id);
    if (databaseId) setPendingDatabaseId(databaseId);
  };

  const handleDeleteProject = async (projectId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await projectService.deleteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
      if (currentProjectId === projectId) {
        setCurrentProjectId(projects.find((p) => p.id !== projectId)?.id ?? null);
      }
    } catch (err) {
      console.error('[App] Delete project failed:', err);
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers: Databases
  // ---------------------------------------------------------------------------
  const handleDatabaseCreated = async () => {
    const dbs = await databaseService.getDatabases();
    setDatabases(dbs);
  };

  const handleDeleteDatabase = async (databaseId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await databaseService.deleteDatabase(databaseId);
      setDatabases((prev) => prev.filter((d) => d.id !== databaseId));
    } catch (err) {
      console.error('[App] Delete database failed:', err);
    }
  };

  // Upload-to-database from sidebar upload button
  const handleUploadToDatabase = (databaseId: string) => {
    setUploadTargetDbId(databaseId);
    setTimeout(() => sidebarUploadRef.current?.click(), 50);
  };

  const handleSidebarFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !uploadTargetDbId) return;
    try {
      await databaseService.uploadFile(uploadTargetDbId, file);
      await handleDatabaseCreated();
    } catch (err) {
      console.error('[App] Sidebar upload failed:', err);
    } finally {
      if (sidebarUploadRef.current) sidebarUploadRef.current.value = '';
      setUploadTargetDbId(null);
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers: Send Message
  // ---------------------------------------------------------------------------
  const handleSendMessage = async (
    prompt: string,
    files: FileAttachment[],
    modelId: string
  ) => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const txId = `tx-${Date.now()}`;

    // Upload any attached files first to the active database
    if (files.length > 0 && activeDatabase) {
      // Files from ChatInput are FileAttachment objects (metadata only in current UI)
      // The actual File objects are handled via the databaseService.uploadFile in ChatInput
    }

    const userMessage: Message = {
      id: `msg-user-${Date.now()}`,
      role: 'user',
      content: prompt,
      timestamp: timeStr,
      files: files.length > 0 ? files : undefined,
      model: modelId,
    };

    // Create a new project if there isn't a current one (use pending database)
    let targetProjectId = currentProjectId;
    const isDemoPending = pendingDatabaseId === 'demo-database';

    if (!targetProjectId && !isDemoPending) {
      try {
        const newProject = await projectService.createProject({
          database_id: pendingDatabaseId || undefined,
        });
        setProjects((prev) => [{ ...newProject, messages: [userMessage] }, ...prev]);
        setCurrentProjectId(newProject.id);
        setPendingDatabaseId(newProject.database_id || pendingDatabaseId);
        targetProjectId = newProject.id;
      } catch (err) {
        console.error('[App] Failed to create project on send:', err);
        return;
      }
    } else if (!targetProjectId && isDemoPending) {
      // Route to demo project, append user message
      const demoProj = projects.find((p) => p.is_demo || p.isDemo || p.id === 'demo-project');
      if (demoProj) {
        targetProjectId = demoProj.id;
        setCurrentProjectId(demoProj.id);
        setProjects((prev) =>
          prev.map((p) =>
            p.id === demoProj.id
              ? { ...p, messages: [...(p.messages || []), userMessage] }
              : p
          )
        );
      }
    } else {
      // Append user message to existing project
      setProjects((prev) =>
        prev.map((p) =>
          p.id === targetProjectId
            ? { ...p, updatedAt: now.toISOString(), messages: [...(p.messages || []), userMessage] }
            : p
        )
      );
    }

    // Auto-update title on first user message (skip for demo project)
    const targetProject = projects.find((p) => p.id === targetProjectId);
    const isFirstMessage = !targetProject || (targetProject.messages || []).length === 0;
    const isRealProject = targetProjectId && targetProjectId !== 'demo-project'
      && !targetProject?.is_demo && !targetProject?.isDemo;
    if (isFirstMessage && isRealProject) {
      const snippet = prompt.length > 60 ? `${prompt.substring(0, 60)}…` : prompt;
      projectService.updateProjectTitle(targetProjectId!, snippet).then((updated) => {
        setProjects((prev) =>
          prev.map((p) => (p.id === targetProjectId ? { ...p, title: updated.title } : p))
        );
      }).catch(() => { /* non-critical */ });
    }

    setIsLoading(true);

    // Add a streaming placeholder
    const placeholderId = `msg-assistant-${Date.now()}`;
    const placeholder: Message = {
      id: placeholderId,
      role: 'assistant',
      content: '',
      timestamp: timeStr,
      model: modelId,
      isStreaming: true,
    };

    setProjects((prev) =>
      prev.map((p) =>
        p.id === targetProjectId
          ? { ...p, messages: [...(p.messages || []), placeholder] }
          : p
      )
    );

    // Send over WebSocket if client is ready, or use demo service if demo project
    const resolvedProject = projects.find((p) => p.id === targetProjectId);
    try {
      if (resolvedProject?.is_demo || resolvedProject?.isDemo || isDemoPending) {
        const { demoService } = await import('./services/demoService');
        const resp = await demoService.sendDemoChat(prompt);
        setProjects((prev) =>
          prev.map((p) =>
            p.id === targetProjectId
              ? {
                  ...p,
                  messages: (p.messages || []).map((m) =>
                    m.id === placeholderId
                      ? {
                          ...m,
                          content: resp.reply || resp.content || '',
                          isStreaming: false,
                        }
                      : m
                  ),
                }
              : p
          )
        );
        setIsLoading(false);
      } else if (wsClient?.isReady) {
        const txId = wsClient.sendChatMessage(prompt, buildChatPayload(
          targetProjectId!,
          activeDatabase?.id,
          modelId
        ) as any);
        // Register this tx for streaming updates
        streamingRef.current[txId] = { projectId: targetProjectId!, placeholderId };
        // Note: setIsLoading(false) is called when we receive 'complete' frame
      } else {
        // WS not available — show connection notice
        setProjects((prev) =>
          prev.map((p) =>
            p.id === targetProjectId
              ? {
                  ...p,
                  messages: (p.messages || []).map((m) =>
                    m.id === placeholderId
                      ? {
                          ...m,
                          content: '*(WebSocket is not connected — please refresh and ensure the session is active.)*',
                          isStreaming: false,
                        }
                      : m
                  ),
                }
              : p
          )
        );
        setIsLoading(false);
      }
    } catch (err) {
      console.error('[App] WS send failed:', err);
      setProjects((prev) =>
        prev.map((p) =>
          p.id === targetProjectId
            ? {
                ...p,
                messages: (p.messages || []).map((m) =>
                  m.id === placeholderId
                    ? { ...m, content: '*(Error sending message — please try again.)*', isStreaming: false }
                    : m
                ),
              }
            : p
        )
      );
      setIsLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  const activeMessages = currentProject?.messages ?? [];

  // Pending database name for header display
  const demoProject = projects.find((p) => p.is_demo || p.isDemo || p.id === 'demo-project');
  const pendingDatabaseName =
    pendingDatabaseId === 'demo-database'
      ? 'Music E-commerce (Demo)'
      : databases.find((d) => d.id === pendingDatabaseId)?.name ?? 'Select a Database';

  // Build a minimal Project-like object for ChatArea (which still uses .name)
  const chatAreaProject = currentProject
    ? { id: currentProject.id, name: currentProject.title || 'Untitled', description: '', datasetsCount: 0, createdAt: currentProject.created_at }
    : null;

  // All databases including demo (for NewProjectModal)
  const allDatabasesForModal: Database[] = [
    ...(demoProject ? [{
      id: 'demo-database',
      name: 'Music E-commerce (Demo)',
      schema_name: demoProject.raw_metadata?.schema_name || demoProject.raw_metadata?.schema || 'demo',
      is_demo: true as const,
      created_at: '',
    }] : []),
    ...databases.filter((d) => !d.is_demo),
  ];

  return (
    <div className="nirnaya-app">
      {/* Hidden file input for sidebar database upload */}
      <input
        type="file"
        ref={sidebarUploadRef}
        accept=".csv,.xlsx,.xls,.parquet"
        style={{ display: 'none' }}
        onChange={handleSidebarFileSelect}
      />

      {/* 1. Sidebar */}
      <Sidebar
        currentProjectId={currentProjectId}
        projects={projects}
        databases={databases}
        credentials={credentials}
        pendingDatabaseId={pendingDatabaseId}
        onSelectProject={handleSelectProject}
        onSelectDatabase={handleSelectDatabase}
        onNewChat={() => setIsNewProjectModalOpen(true)}
        onDeleteProject={handleDeleteProject}
        onNewDatabase={() => setIsNewDatabaseModalOpen(true)}
        onDeleteDatabase={handleDeleteDatabase}
        onUploadToDatabase={handleUploadToDatabase}
        onOpenCredentials={() => setIsCredentialsModalOpen(true)}
      />

      {/* 2. Main Chat Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>
        <ChatArea
          currentProject={chatAreaProject as any}
          messages={activeMessages}
          selectedModelId={selectedModelId}
          isLoading={isLoading || isLoadingData}
          pendingDatabaseName={pendingDatabaseName}
          availableDatabasesForPicker={allDatabasesForModal}
          onSelectDatabase={handleSelectDatabase}
          onSendSuggestedPrompt={(suggested) => handleSendMessage(suggested, [], selectedModelId)}
          availableModels={availableModels}
          onOpenCredentials={() => setIsCredentialsModalOpen(true)}
        />

        {/* 3. Chat Input */}
        <ChatInput
          onSendMessage={handleSendMessage}
          selectedModelId={selectedModelId}
          onSelectModel={(modelId) => setSelectedModelId(modelId)}
          isLoading={isLoading}
          availableModels={availableModels}
          onOpenCredentials={() => setIsCredentialsModalOpen(true)}
        />
      </div>

      {/* 4. Credentials Modal */}
      <CredentialsModal
        isOpen={isCredentialsModalOpen}
        onClose={() => setIsCredentialsModalOpen(false)}
        credentials={credentials}
        onSave={handleSaveCredentials}
      />

      {/* 5. New Project Modal */}
      <NewProjectModal
        isOpen={isNewProjectModalOpen}
        onClose={() => setIsNewProjectModalOpen(false)}
        databases={allDatabasesForModal}
        onCreateProject={handleCreateProject}
      />

      {/* 6. New Database Modal */}
      <NewDatabaseModal
        isOpen={isNewDatabaseModalOpen}
        onClose={() => setIsNewDatabaseModalOpen(false)}
        onDatabaseCreated={handleDatabaseCreated}
      />
    </div>
  );
}

export default App;
