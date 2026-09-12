import { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { ChatInput } from './components/ChatInput';
import { StepsPanel } from './components/StepsPanel';
import { ArtifactsPanel } from './components/ArtifactsPanel';
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

function buildChatPayload(projectId: string, databaseId: string | undefined, modelId: string) {
  return {
    project_id: projectId,
    database_id: databaseId ?? null,
    model_id: modelId,
  };
}

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
    steps,
    artifacts,
    finalMarkdown,
    isProcessing,
    turnId,
    startTime,
    endTime,
    handleAckFrame,
    handleStepEvent,
    handleFinalEvent,
    handleErrorEvent,
    reset: resetStepTracking,
  } = useStepTracking();

  console.log('[App] useStepTracking result:', { stepsCount: steps.length, artifactsCount: artifacts.length, isProcessing });

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
      // Handle new event types for steps/artifacts
      if (frame.type === 'ack') {
        const ackFrame = frame as WSAckFrame;
        console.log('[App] ACK frame:', ackFrame);
        handleAckFrame(ackFrame);
        return;
      }

      if (frame.type === 'step') {
        const stepEvent = frame as StepEvent;
        console.log('[App] Step event:', stepEvent);
        handleStepEvent(stepEvent);
        return;
      }

      if (frame.type === 'final') {
        const finalEvent = frame as FinalEvent;
        // Update project title if available
        if (finalEvent.markdown && currentProject) {
          setProjects((prev) =>
            prev.map((p) =>
              p.id === currentProject.id
                ? { ...p, title: finalEvent.markdown.split('\n')[0].slice(0, 50) || p.title }
                : p
            )
          );
        }
        // Update placeholder message with final markdown + artifacts
        if (currentTurnContextRef.current && finalEvent.markdown) {
          const { projectId, placeholderId } = currentTurnContextRef.current;
          setProjects((prev) =>
            prev.map((p) =>
              p.id === projectId
                ? {
                    ...p,
                    messages: (p.messages || []).map((m) =>
                      m.id === placeholderId
                        ? { ...m, content: finalEvent.markdown, isStreaming: false }
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
        const turnId = frame.turn_id as string;
        const message = frame.message || 'Unknown error';
        handleErrorEvent(turnId, message);
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
  }, [onWSMessage, currentProject, handleAckFrame, handleStepEvent, handleFinalEvent, handleErrorEvent]);

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
  const handleSelectProject = (projectId: string) => {
    setCurrentProjectId(projectId);
    const proj = projects.find((p) => p.id === projectId);
    if (proj?.database_id) setPendingDatabaseId(proj.database_id);
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
      content: finalMarkdown || '',
      timestamp: timeStr,
      model: modelId,
      isStreaming: false,
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
              />
            </div>
            <div style={{ minHeight: '1px', maxHeight: '250px', overflow: 'auto', borderTop: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}>
              <StepsPanel steps={steps} isLoading={isProcessing} startTime={startTime} endTime={endTime} />
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

        {/* Right: Artifacts */}
        {artifacts.length > 0 && (
          <div style={{ width: '400px', borderLeft: '1px solid var(--border-color)', overflow: 'hidden' }}>
            <ArtifactsPanel artifacts={artifacts} />
          </div>
        )}
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
