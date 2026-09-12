import { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { ChatInput } from './components/ChatInput';
import { CredentialsModal } from './components/CredentialsModal';
import { NewProjectModal } from './components/NewProjectModal';
import { NewDatabaseModal } from './components/NewDatabaseModal';
import { DemoInitModal } from './components/DemoInitModal';
import { DeleteDatabaseModal } from './components/DeleteDatabaseModal';
import type {
  Project,
  Database,
  Message,
  FileAttachment,
  LLMCredentials,
  StepEvent,
  FinalEvent,
  WSAckFrame,
  AskUserEvent,
} from './types';
import { DEFAULT_MODEL_ID } from './constants/models';
import { useSession } from './hooks/useSession';
import { useModels } from './hooks/useModels';
import { useStepTracking } from './hooks/useStepTracking';
import { projectService } from './services/projectService';
import { databaseService } from './services/databaseService';

const STORAGE_KEYS = {
  CREDENTIALS: 'nirnaya_llm_credentials_v1',
  SELECTED_MODEL: 'nirnaya_selected_model_v1',
  DEMO_PROMPTED: 'nirnaya_demo_prompted',
};

function App() {
  const { sessionStatus, submitKey, wsClient, onWSMessage } = useSession();
  const { models: availableModels, refresh: refreshModels } = useModels(sessionStatus === 'ready');

  const [projects, setProjects] = useState<Project[]>([]);
  const [databases, setDatabases] = useState<Database[]>([]);
  const [isLoadingData, setIsLoadingData] = useState(false);
  const [isDataLoaded, setIsDataLoaded] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [pendingDatabaseId, setPendingDatabaseId] = useState<string | null>(null);

  const [isNewProjectModalOpen, setIsNewProjectModalOpen] = useState(false);
  const [isNewDatabaseModalOpen, setIsNewDatabaseModalOpen] = useState(false);
  const [isCredentialsModalOpen, setIsCredentialsModalOpen] = useState(false);
  const [isDemoModalOpen, setIsDemoModalOpen] = useState(false);
  const [deleteDatabaseId, setDeleteDatabaseId] = useState<string | null>(null);

  const [uploadTargetDbId, setUploadTargetDbId] = useState<string | null>(null);
  const sidebarUploadRef = useRef<HTMLInputElement | null>(null);
  const streamingRef = useRef<Record<string, { projectId: string; placeholderId: string }>>({});
  const currentTurnContextRef = useRef<{ projectId: string; placeholderId: string } | null>(null);
  const demoPromptedRef = useRef(false);
  const lastSeqRef = useRef<number>(-1);
  const activeTurnIdRef = useRef<string | null>(null);

  const [selectedModelId, setSelectedModelId] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEYS.SELECTED_MODEL) || DEFAULT_MODEL_ID;
  });

  const [credentials, setCredentials] = useState<LLMCredentials>(() => {
    const saved = localStorage.getItem(STORAGE_KEYS.CREDENTIALS);
    if (saved) {
      try { return JSON.parse(saved); } catch { /* fallback */ }
    }
    return { anthropicApiKey: '', openaiApiKey: '', preferredProvider: 'anthropic' };
  });

  const [isLoading, setIsLoading] = useState(false);

  const {
    artifacts,
    finalMarkdown,
    isProcessing,
    turnId,
    startTime,
    handleAckFrame,
    handleStepEvent,
    handleFinalEvent,
    handleErrorEvent,
    reset: resetStepTracking,
  } = useStepTracking();

  console.log('[App] useStepTracking result:', { artifactsCount: artifacts.length, isProcessing });

  const currentProject = projects.find((p) => p.id === currentProjectId) ?? null;
  const activeDatabase = currentProject?.database_id
    ? databases.find((d) => d.id === currentProject.database_id)
    : databases.find((d) => d.id === pendingDatabaseId) ?? databases[0];

  // ---------------------------------------------------------------------------
  // WS frame handler
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const unsub = onWSMessage((frame) => {
      console.log('[App] WS frame received:', frame.type, frame);

      if (frame.type === 'ack') {
        const ackFrame = frame as WSAckFrame;
        activeTurnIdRef.current = ackFrame.turn_id;
        lastSeqRef.current = -1;
        handleAckFrame(ackFrame);
        return;
      }

      if (frame.type === 'step') {
        const stepEvent = frame as StepEvent;
        lastSeqRef.current = Math.max(lastSeqRef.current, stepEvent.seq);
        handleStepEvent(stepEvent);
        if (currentTurnContextRef.current) {
          const { projectId, placeholderId } = currentTurnContextRef.current;
          setProjects((prev) =>
            prev.map((p) =>
              p.id === projectId
                ? {
                    ...p,
                    messages: (p.messages || []).map((m) =>
                      m.id === placeholderId
                        ? {
                            ...m,
                            steps: [
                              ...(m.steps || []).filter((s) => s.seq !== stepEvent.seq),
                              stepEvent,
                            ].sort((a, b) => a.seq - b.seq),
                          }
                        : m
                    ),
                  }
                : p
            )
          );
        }
        return;
      }

      if (frame.type === 'ask_user') {
        const askEvent = frame as unknown as AskUserEvent;
        lastSeqRef.current = Math.max(lastSeqRef.current, askEvent.seq);
        if (currentTurnContextRef.current) {
          const { projectId, placeholderId } = currentTurnContextRef.current;
          setProjects((prev) =>
            prev.map((p) =>
              p.id === projectId
                ? {
                    ...p,
                    messages: (p.messages || []).map((m) =>
                      m.id === placeholderId ? { ...m, askUser: askEvent } : m
                    ),
                  }
                : p
            )
          );
        }
        return;
      }

      if (frame.type === 'project_title_updated') {
        const newTitle = frame.title as string;
        const projectId = frame.project_id as string;
        if (newTitle && projectId) {
          setProjects((prev) =>
            prev.map((p) =>
              p.id === projectId && (!p.title || p.title === 'Untitled')
                ? { ...p, title: newTitle }
                : p
            )
          );
        }
        return;
      }

      if (frame.type === 'final') {
        const finalEvent = frame as FinalEvent;
        lastSeqRef.current = Math.max(lastSeqRef.current, finalEvent.seq ?? -1);
        activeTurnIdRef.current = null;
        const thinkingSeconds = startTime ? Math.round((Date.now() - startTime) / 1000) : 0;
        const freshArtifacts = (finalEvent.artifacts || []).filter((a) => a.status === 'fresh');
        if (currentTurnContextRef.current) {
          const { projectId, placeholderId } = currentTurnContextRef.current;
          setProjects((prev) =>
            prev.map((p) =>
              p.id === projectId
                ? {
                    ...p,
                    messages: (p.messages || []).map((m) =>
                      m.id === placeholderId
                        ? {
                            ...m,
                            content: finalEvent.markdown || m.content,
                            isStreaming: false,
                            thinkingSeconds,
                            executionTimeMs: finalEvent.execution_time_ms,
                            artifacts: freshArtifacts,
                            followUpQuestions: finalEvent.follow_up_questions || [],
                            askUser: undefined,
                          }
                        : m
                    ),
                  }
                : p
            )
          );
          currentTurnContextRef.current = null;
        }
        handleFinalEvent(finalEvent);
        setIsLoading(false);
        return;
      }

      if (frame.type === 'error') {
        const errTurnId = frame.turn_id as string;
        const message = (frame.message as string) || 'Unknown error';
        handleErrorEvent(errTurnId, message);
        setIsLoading(false);
        return;
      }

      // Legacy stream handling (backward compat)
      const entry = streamingRef.current[frame.transactionId!];
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

      if (frame.type === 'complete') {
        setProjects((prev) =>
          prev.map((p) =>
            p.id === projectId
              ? {
                  ...p,
                  messages: (p.messages || []).map((m) =>
                    m.id === placeholderId
                      ? {
                          ...m,
                          content: m.content || '',
                          isStreaming: false,
                          sqlQuery: (frame as any).sql_query,
                          tableData: (frame as any).table_data,
                        }
                      : m
                  ),
                }
              : p
          )
        );
        delete streamingRef.current[frame.transactionId!];
        setIsLoading(false);
      }
    });
    return unsub;
  }, [onWSMessage, currentProject, handleAckFrame, handleStepEvent, handleFinalEvent, handleErrorEvent, startTime]);

  // ---------------------------------------------------------------------------
  // Fetch projects + databases once session is ready
  // ---------------------------------------------------------------------------
  const fetchAllData = useCallback(async () => {
    setIsLoadingData(true);
    try {
      const [projs, dbs] = await Promise.all([
        projectService.getProjects(),
        databaseService.getDatabases(),
      ]);

      setProjects((prev) => {
        const localMessages: Record<string, Message[]> = {};
        prev.forEach((p) => { localMessages[p.id] = p.messages || []; });
        return projs.map((p) => ({ ...p, messages: localMessages[p.id] || [] }));
      });
      setDatabases(dbs);

      setCurrentProjectId((cur) => cur ?? projs[0]?.id ?? null);

      // Auto-select first database if no project is selected yet
      setPendingDatabaseId((cur) => cur ?? dbs[0]?.id ?? null);

      // Show demo init popup on first load if no databases exist
      if (dbs.length === 0 && !demoPromptedRef.current && !sessionStorage.getItem(STORAGE_KEYS.DEMO_PROMPTED)) {
        demoPromptedRef.current = true;
        setIsDemoModalOpen(true);
      }
    } catch (err) {
      console.error('[App] Failed to load projects/databases:', err);
    } finally {
      setIsLoadingData(false);
      setIsDataLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (sessionStatus === 'ready') fetchAllData();
  }, [sessionStatus, fetchAllData]);

  // ---------------------------------------------------------------------------
  // Persist settings
  // ---------------------------------------------------------------------------
  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.SELECTED_MODEL, selectedModelId);
  }, [selectedModelId]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CREDENTIALS, JSON.stringify(credentials));
  }, [credentials]);

  // Ctrl/Cmd+N → New Chat
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
  const loadProjectHistory = useCallback(async (projectId: string) => {
    const proj = projects.find((p) => p.id === projectId);
    if (!proj || (proj.messages && proj.messages.length > 0)) return;
    const turns = await projectService.getProjectMessages(projectId);
    if (!turns || turns.length === 0) return;
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const historicalMessages: Message[] = turns.flatMap((turn) => {
      const ts = turn.created_at
        ? new Date(turn.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : timeStr;
      const user: Message = {
        id: `hist-user-${turn.turn_id}`,
        role: 'user',
        content: turn.user_message,
        timestamp: ts,
      };
      const assistant: Message = {
        id: `hist-asst-${turn.turn_id}`,
        role: 'assistant',
        content: turn.markdown,
        timestamp: ts,
        executionTimeMs: turn.execution_time_ms,
        thinkingSeconds: turn.execution_time_ms ? Math.round(turn.execution_time_ms / 1000) : undefined,
        steps: turn.steps || [],
        artifacts: (turn.artifacts || []).filter((a) => a.status === 'fresh'),
        followUpQuestions: turn.follow_up_questions || [],
      };
      return [user, assistant];
    });
    setProjects((prev) =>
      prev.map((p) =>
        p.id === projectId && (!p.messages || p.messages.length === 0)
          ? { ...p, messages: historicalMessages }
          : p
      )
    );
  }, [projects]);

  const handleAskUserResponse = useCallback((turnId: string, answer: string, modelId: string) => {
    if (!wsClient?.isReady) return;
    wsClient.sendAskUserResponse(turnId, answer, modelId);
    // Clear the askUser from the message
    setProjects((prev) =>
      prev.map((p) => ({
        ...p,
        messages: (p.messages || []).map((m) =>
          m.askUser?.turn_id === turnId ? { ...m, askUser: undefined } : m
        ),
      }))
    );
  }, [wsClient]);

  const handleSelectProject = (projectId: string) => {
    setCurrentProjectId(projectId);
    const proj = projects.find((p) => p.id === projectId);
    if (proj?.database_id) setPendingDatabaseId(proj.database_id);
    loadProjectHistory(projectId);
  };

  const handleSelectDatabase = async (dbId: string) => {
    // Early return if already on this database
    if (activeDatabase?.id === dbId) {
      return;
    }

    // Prevent switching during message processing
    if (isLoading) {
      console.warn('[App] Cannot switch database while message is processing');
      return;
    }

    // Check if current project has messages (user has invested work)
    const hasActiveProjectWithMessages =
      currentProject &&
      currentProject.messages &&
      currentProject.messages.length > 0;

    if (hasActiveProjectWithMessages) {
      // Create new blank project linked to the new database
      try {
        const newProject = await projectService.createProject({
          database_id: dbId,
        });

        // Add new project to list (at beginning) and switch to it
        setProjects((prev) => [{ ...newProject, messages: [] }, ...prev]);
        setCurrentProjectId(newProject.id);
        setPendingDatabaseId(dbId);
      } catch (err) {
        console.error('[App] Failed to create project on database switch:', err);
        // Fallback: just update pending database
        setPendingDatabaseId(dbId);
      }
    } else {
      // No active project or empty project - just update pending database
      // When user sends first message, it will use this database
      setPendingDatabaseId(dbId);
    }
  };

  const handleCreateProject = async (databaseId?: string) => {
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
    // Auto-select the first/newly added database
    if (dbs.length > 0) {
      setPendingDatabaseId(dbs[0].id);
    }
  };

  const handleDeleteDatabase = async (databaseId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteDatabaseId(databaseId);
  };

  const handleConfirmDeleteDatabase = async () => {
    if (!deleteDatabaseId) return;
    try {
      await databaseService.deleteDatabase(deleteDatabaseId);
      setDatabases((prev) => prev.filter((d) => d.id !== deleteDatabaseId));
      setDeleteDatabaseId(null);
    } catch (err) {
      console.error('[App] Delete database failed:', err);
    }
  };

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
  // Handler: Demo
  // ---------------------------------------------------------------------------
  const handleDemoModalClose = () => {
    sessionStorage.setItem(STORAGE_KEYS.DEMO_PROMPTED, 'true');
    setIsDemoModalOpen(false);
  };

  const handleOpenDemoModal = () => {
    setIsDemoModalOpen(true);
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

    const userMessage: Message = {
      id: `msg-user-${Date.now()}`,
      role: 'user',
      content: prompt,
      timestamp: timeStr,
      files: files.length > 0 ? files : undefined,
      model: modelId,
    };

    let targetProjectId = currentProjectId;

    if (!targetProjectId) {
      try {
        const newProject = await projectService.createProject({
          database_id: pendingDatabaseId || undefined,
        });
        setProjects((prev) => [{ ...newProject, messages: [userMessage] }, ...prev]);
        setCurrentProjectId(newProject.id);
        if (newProject.database_id) setPendingDatabaseId(newProject.database_id);
        targetProjectId = newProject.id;
      } catch (err) {
        console.error('[App] Failed to create project on send:', err);
        return;
      }
    } else {
      setProjects((prev) =>
        prev.map((p) =>
          p.id === targetProjectId
            ? { ...p, updatedAt: now.toISOString(), messages: [...(p.messages || []), userMessage] }
            : p
        )
      );
    }

    // Auto-update title on first user message
    const targetProject = projects.find((p) => p.id === targetProjectId);
    const isFirstMessage = !targetProject || (targetProject.messages || []).length === 0;
    if (isFirstMessage && targetProjectId) {
      const snippet = prompt.length > 60 ? `${prompt.substring(0, 60)}…` : prompt;
      projectService.updateProjectTitle(targetProjectId, snippet).then((updated) => {
        setProjects((prev) =>
          prev.map((p) => (p.id === targetProjectId ? { ...p, title: updated.title } : p))
        );
      }).catch(() => { /* non-critical */ });
    }

    resetStepTracking();
    setIsLoading(true);

    const placeholderId = `msg-assistant-${Date.now()}`;
    const placeholder: Message = {
      id: placeholderId,
      role: 'assistant',
      content: '',
      timestamp: timeStr,
      model: modelId,
      isStreaming: false,
      turnStartTime: Date.now(),
    };

    setProjects((prev) =>
      prev.map((p) =>
        p.id === targetProjectId
          ? { ...p, messages: [...(p.messages || []), placeholder] }
          : p
      )
    );

    currentTurnContextRef.current = { projectId: targetProjectId, placeholderId };

    try {
      if (wsClient?.isReady && targetProjectId) {
        // Use new ChatAgent format with project_id and text
        const txId = wsClient.sendChatMessage(
          targetProjectId,
          prompt,
          turnId || undefined,
          { model: modelId }
        );
        streamingRef.current[txId] = { projectId: targetProjectId, placeholderId };
      } else {
        setProjects((prev) =>
          prev.map((p) =>
            p.id === targetProjectId
              ? {
                  ...p,
                  messages: (p.messages || []).map((m) =>
                    m.id === placeholderId
                      ? { ...m, content: '*(WebSocket is not connected — please refresh.)*', isStreaming: false }
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

  const pendingDatabaseName =
    databases.find((d) => d.id === pendingDatabaseId)?.name ??
    (pendingDatabaseId ? 'Loading…' : 'Select a Database');

  const chatAreaProject = currentProject
    ? { id: currentProject.id, name: currentProject.title || 'Untitled', description: '', datasetsCount: 0, createdAt: currentProject.created_at }
    : null;

  return (
    <div className="nirnaya-app">
      <input
        type="file"
        ref={sidebarUploadRef}
        accept=".csv,.xlsx,.xls,.parquet"
        style={{ display: 'none' }}
        onChange={handleSidebarFileSelect}
      />

      <Sidebar
        currentProjectId={currentProjectId}
        projects={projects}
        databases={databases}
        credentials={credentials}
        pendingDatabaseId={pendingDatabaseId ?? undefined}
        isDataLoaded={isDataLoaded}
        onSelectProject={handleSelectProject}
        onSelectDatabase={handleSelectDatabase}
        onNewChat={() => setIsNewProjectModalOpen(true)}
        onDeleteProject={handleDeleteProject}
        onNewDatabase={() => setIsNewDatabaseModalOpen(true)}
        onDeleteDatabase={handleDeleteDatabase}
        onUploadToDatabase={handleUploadToDatabase}
        onOpenCredentials={() => setIsCredentialsModalOpen(true)}
        onAddDemo={handleOpenDemoModal}
        onTableDeleted={handleDatabaseCreated}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'row', height: '100%', position: 'relative' }}>
        {/* Left: Chat + Input */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ flex: 1, overflow: 'auto' }}>
              <ChatArea
                currentProject={chatAreaProject as any}
                messages={activeMessages}
                selectedModelId={selectedModelId}
                isLoading={isLoading || isLoadingData}
                isDataLoaded={isDataLoaded}
                pendingDatabaseName={pendingDatabaseName}
                availableDatabasesForPicker={databases}
                onSelectDatabase={handleSelectDatabase}
                onSendSuggestedPrompt={(suggested) => handleSendMessage(suggested, [], selectedModelId)}
                availableModels={availableModels}
                onOpenCredentials={() => setIsCredentialsModalOpen(true)}
                onAskUserResponse={handleAskUserResponse}
              />
            </div>
          </div>

          <ChatInput
            onSendMessage={handleSendMessage}
            selectedModelId={selectedModelId}
            onSelectModel={(modelId) => setSelectedModelId(modelId)}
            isLoading={isLoading}
            isDataLoaded={isDataLoaded}
            availableModels={availableModels}
            onOpenCredentials={() => setIsCredentialsModalOpen(true)}
          />
        </div>
      </div>

      <CredentialsModal
        isOpen={isCredentialsModalOpen}
        onClose={() => setIsCredentialsModalOpen(false)}
        credentials={credentials}
        onSave={handleSaveCredentials}
      />

      <NewProjectModal
        isOpen={isNewProjectModalOpen}
        onClose={() => setIsNewProjectModalOpen(false)}
        databases={databases}
        onCreateProject={handleCreateProject}
      />

      <NewDatabaseModal
        isOpen={isNewDatabaseModalOpen}
        onClose={() => setIsNewDatabaseModalOpen(false)}
        onDatabaseCreated={handleDatabaseCreated}
      />

      <DemoInitModal
        isOpen={isDemoModalOpen}
        onClose={handleDemoModalClose}
        onDemoCreated={fetchAllData}
      />

      <DeleteDatabaseModal
        isOpen={deleteDatabaseId !== null}
        databaseName={databases.find((d) => d.id === deleteDatabaseId)?.name}
        onConfirm={handleConfirmDeleteDatabase}
        onCancel={() => setDeleteDatabaseId(null)}
      />
    </div>
  );
}

export default App;
