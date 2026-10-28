import { useCallback, useEffect, useRef, useState } from 'react';
import forestArtwork from './assets/forest-artwork.svg';
import { api, ApiError } from './api';
import { AiCoachView } from './components/AiCoachView';
import { AnalyticsReportsView } from './components/AnalyticsReportsView';
import { CategoriesView } from './components/CategoriesView';
import { EditProfileModal } from './components/EditProfileModal';
import { GoalsView } from './components/GoalsView';
import { AlertIcon, RefreshIcon } from './components/Icons';
import { ManualActivityModal } from './components/ManualActivityModal';
import { MissedActivityBanner } from './components/MissedActivityBanner';
import { NotificationsView } from './components/NotificationsView';
import { PlanTimeBlockPanel } from './components/PlanTimeBlockPanel';
import { Overview } from './components/Overview';
import { SessionDetailModal } from './components/SessionDetailModal';
import { SettingsView } from './components/SettingsView';
import { Sidebar, type DashboardTab } from './components/Sidebar';
import { SmartNotifications } from './components/SmartNotifications';
import { TimeBlocksView } from './components/TimeBlocksView';
import { TimelineView } from './components/TimelineView';
import { Topbar } from './components/Topbar';
import { WindowTitleBar } from './components/WindowTitleBar';
import {
  type ActiveTaskModel,
  type CategoryModel,
  type CategoryRuleModel,
  type DailyAiSummaryModel,
  type GoalModel,
  type GoalProgressModel,
  type ProductivityModel,
  type RecoveryGapModel,
  type SessionModel,
  type StatsModel,
  type TimeBlockAnalysisModel,
  type TimeBlockModel,
  type WeeklyStatsModel,
  getLocalTodayString,
} from './types';

function getTodayString(): string {
  return getLocalTodayString();
}

export function App() {
  const [currentTab, setCurrentTab] = useState<DashboardTab>('overview');
  const [selectedDate, setSelectedDate] = useState<string>(getTodayString());
  const [activeDates, setActiveDates] = useState<string[]>([]);

  // Core Data
  const [sessions, setSessions] = useState<SessionModel[]>([]);
  const [stats, setStats] = useState<StatsModel | null>(null);
  const [weeklyStats, setWeeklyStats] = useState<WeeklyStatsModel | null>(null);

  // Productivity & AI Insights
  const [productivity, setProductivity] = useState<ProductivityModel | null>(null);
  const [aiSummary, setAiSummary] = useState<DailyAiSummaryModel | null>(null);
  const [isAiRefreshing, setIsAiRefreshing] = useState<boolean>(false);

  // Categories & Rules
  const [categories, setCategories] = useState<CategoryModel[]>([]);
  const [rules, setRules] = useState<CategoryRuleModel[]>([]);

  // Goals & Time Blocks
  const [goals, setGoals] = useState<GoalModel[]>([]);
  const [goalsProgress, setGoalsProgress] = useState<GoalProgressModel[]>([]);
  const [timeBlocks, setTimeBlocks] = useState<TimeBlockModel[]>([]);
  const [timeBlocksAnalysis, setTimeBlocksAnalysis] = useState<TimeBlockAnalysisModel[]>([]);

  // Modal State
  const [selectedSession, setSelectedSession] = useState<SessionModel | null>(null);
  const [isNewTaskModalOpen, setIsNewTaskModalOpen] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Status & Connectivity
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isBackendConnected, setIsBackendConnected] = useState<boolean>(false);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [trackerError, setTrackerError] = useState<string | null>(null);
  const [dbPath, setDbPath] = useState<string>('');

  const [isTracking, setIsTracking] = useState<boolean>(false);
  const [isTogglingTracker, setIsTogglingTracker] = useState<boolean>(false);
  const [trackerMessage, setTrackerMessage] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<ActiveTaskModel | null>(null);
  const [isAutostartEnabled, setIsAutostartEnabled] = useState<boolean>(false);

  // User Profile State
  const [userName, setUserName] = useState<string>(() => {
    try {
      return localStorage.getItem('time_tracker_user_name') || 'pant';
    } catch {
      return 'pant';
    }
  });
  const [isEditProfileModalOpen, setIsEditProfileModalOpen] = useState<boolean>(false);

  const handleSaveProfileName = async (newName: string) => {
    const trimmed = newName.trim();
    setUserName(trimmed);
    try {
      localStorage.setItem('time_tracker_user_name', trimmed);
    } catch {
      // ignore
    }
    await api.updateSettings({ user_name: trimmed });
  };

  // Notification Center & Missed-Activity Recovery State
  const [unreadNotificationsCount, setUnreadNotificationsCount] = useState<number>(0);
  const [pendingRecoveryGap, setPendingRecoveryGap] = useState<RecoveryGapModel | null>(null);
  const [isManualActivityModalOpen, setIsManualActivityModalOpen] = useState<boolean>(false);
  const [selectedRecoveryGap, setSelectedRecoveryGap] = useState<RecoveryGapModel | null>(null);

  const lastActiveTaskRef = useRef<ActiveTaskModel | null>(null);
  const periodicSyncCounterRef = useRef<number>(0);
  const selectedDateRef = useRef<string>(selectedDate);
  selectedDateRef.current = selectedDate;

  // Load Categories & Rules
  const loadCategoriesAndRules = useCallback(async () => {
    try {
      const [cats, rls, gls] = await Promise.all([
        api.getCategories(),
        api.getRules(),
        api.getGoals(),
      ]);
      setCategories(cats);
      setRules(rls);
      setGoals(gls);
    } catch {
      // Non-critical background failure
    }
  }, []);

  // Fetch full data for the currently selected date
  const loadDataForDate = useCallback(
    async (dateStr: string, refreshAi = false, silent = false) => {
      if (!silent) {
        setIsLoading(true);
      }
      setBackendError(null);

      try {
        const [
          timelineData,
          statsData,
          weeklyData,
          productivityData,
          aiSummaryData,
          goalsProgData,
          blocksData,
          blocksAnalysisData,
        ] = await Promise.all([
          api.getTimeline(dateStr, refreshAi),
          api.getStats(dateStr),
          api.getWeeklyStats(dateStr),
          api.getProductivity(dateStr).catch(() => null),
          api.getInsightsSummary(dateStr, refreshAi).catch(() => null),
          api.getGoalsProgress(dateStr).catch(() => []),
          api.getTimeBlocks(dateStr).catch(() => []),
          api.getTimeBlocksAnalysis(dateStr).catch(() => []),
        ]);

        setSessions(timelineData);
        setStats(statsData);
        setWeeklyStats(weeklyData);
        if (productivityData) setProductivity(productivityData);
        if (aiSummaryData) setAiSummary(aiSummaryData);
        setGoalsProgress(goalsProgData);
        setTimeBlocks(blocksData);
        setTimeBlocksAnalysis(blocksAnalysisData);

        setIsBackendConnected(true);
      } catch (err) {
        if (err instanceof ApiError && err.status === 0) {
          setIsBackendConnected(false);
          setBackendError(err.message);
        } else if (!silent) {
          setBackendError(err instanceof Error ? err.message : 'Error loading dashboard data');
        }
      } finally {
        if (!silent) {
          setIsLoading(false);
        }
      }
    },
    []
  );

  // Initial load
  useEffect(() => {
    let mounted = true;

    async function init() {
      try {
        const [health, trackerStatus, datesRes] = await Promise.all([
          api.getHealth(),
          api.getTrackerStatus(),
          api.getActiveDates(30),
        ]);

        if (mounted) {
          setIsBackendConnected(health.status === 'ok');
          setDbPath(health.db || '');
          setIsTracking(trackerStatus.is_tracking);
          setBackendError(null);

          if (trackerStatus.active_task) {
            setActiveTask(trackerStatus.active_task);
            lastActiveTaskRef.current = trackerStatus.active_task;
          }

          if (datesRes.dates && datesRes.dates.length > 0) {
            setActiveDates(datesRes.dates);
          }
        }

        // Fetch autostart status & categories
        try {
          const autoRes = await api.getAutostartStatus();
          if (mounted) {
            setIsAutostartEnabled(autoRes.enabled);
          }
        } catch {
          // non-critical
        }

        try {
          const settings = await api.getSettings();
          if (mounted && settings && settings.user_name) {
            setUserName(settings.user_name);
            try {
              localStorage.setItem('time_tracker_user_name', settings.user_name);
            } catch {
              // ignore
            }
          }
        } catch {
          // non-critical
        }

        loadCategoriesAndRules();
      } catch (err) {
        if (mounted) {
          setIsBackendConnected(false);
          setBackendError(
            err instanceof ApiError
              ? err.message
              : 'Cannot connect to backend at http://127.0.0.1:8000. Start it with `python api/server.py`.'
          );
        }
      }
    }

    init();

    // Centralized action dispatcher for Windows Desktop Notification routing and deep links
    const dispatchAction = (actionName: string, params: Record<string, any> = {}) => {
      if (!actionName) return;
      const act = actionName.toLowerCase();
      if (act === 'snooze_mismatch_15' || act === 'snooze_mismatch_30') {
        const mins = act === 'snooze_mismatch_30' ? 30 : 15;
        api.snoozeNotification('focus', mins).catch(() => {});
      } else if (act === 'snooze_idle_5') {
        api.snoozeNotification('idle', 5).catch(() => {});
      } else if (act === 'resume_work') {
        api.startTracker().catch(() => {});
        setCurrentTab('overview');
      } else if (act === 'start_break') {
        api.stopTracker().catch(() => {});
        setCurrentTab('overview');
      } else if (act === 'review_activity') {
        setCurrentTab('reports');
      } else if (act === 'switch_task') {
        setCurrentTab('overview');
      } else if (act === 'add_activity') {
        setIsManualActivityModalOpen(true);
      } else if (act === 'return_to_task') {
        api.startTracker().catch(() => {});
        setCurrentTab('overview');
      } else if (act === 'start_focus_block') {
        const bId = Number(params.block_id);
        if (bId) {
          api.startFocusForTimeBlock(bId).then(() => {
            checkActiveTask();
            setCurrentTab('overview');
          }).catch(() => {});
        }
      } else if (act === 'snooze_block') {
        const bId = Number(params.block_id);
        const mins = Number(params.minutes) || 5;
        if (bId) {
          api.snoozeTimeBlock(bId, mins).catch(() => {});
        }
      } else if (act === 'skip_block' || act === 'dismiss_missed_block' || act === 'complete_block') {
        const bId = Number(params.block_id);
        if (bId) {
          api.skipTimeBlock(bId).catch(() => {});
        }
      } else if (act === 'reschedule_block' || act === 'open_planner' || act === 'open_timeblocks') {
        setCurrentTab('timeblocks');
      } else if (act === 'overview') {
        setCurrentTab('overview');
      }
    };

    // Handle action parameter from initial URL load (e.g. cold launch from notification)
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const action = urlParams.get('action');
      if (action) {
        const params: Record<string, any> = {};
        urlParams.forEach((val, key) => {
          if (key !== 'action') params[key] = val;
        });
        dispatchAction(action, params);
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    } catch {
      // Non-critical
    }

    // Helper to poll for pending actions forwarded by desktop app second instances
    const checkPendingDesktopAction = async () => {
      try {
        const pending = await api.getPendingDesktopAction();
        if (pending && pending.action) {
          dispatchAction(pending.action, pending.params || {});
        }
      } catch {
        // Non-critical
      }
    };

    // Check status and automatically detect active task changes
    const checkActiveTask = async () => {
      try {
        await checkPendingDesktopAction();

        const status = await api.getTrackerStatus();
        if (!mounted) return;

        setIsTracking(status.is_tracking);
        setIsBackendConnected(true);

        const currentTask = status.active_task ?? null;
        setActiveTask(currentTask);

        const prevTask = lastActiveTaskRef.current;
        const taskChanged =
          (!prevTask && currentTask !== null) ||
          (prevTask !== null && currentTask === null) ||
          (prevTask !== null && currentTask !== null && (
            prevTask.observation_id !== currentTask.observation_id ||
            prevTask.app !== currentTask.app ||
            prevTask.title !== currentTask.title ||
            prevTask.is_open !== currentTask.is_open
          ));

        lastActiveTaskRef.current = currentTask;

        if (taskChanged) {
          periodicSyncCounterRef.current = 0;
          if (selectedDateRef.current === getTodayString()) {
            loadDataForDate(selectedDateRef.current, false, true);
          }
        } else if (status.is_tracking && selectedDateRef.current === getTodayString()) {
          periodicSyncCounterRef.current += 1;
          if (periodicSyncCounterRef.current >= 3) {
            periodicSyncCounterRef.current = 0;
            loadDataForDate(selectedDateRef.current, false, true);
          }
        }

        if (!status.is_tracking && status.message && status.message !== 'Tracking is stopped.') {
          setTrackerMessage(status.message);
        }
      } catch {
        // Handled by main load
      }
    };

    const interval = setInterval(checkActiveTask, 1500);

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        checkActiveTask();
        if (selectedDateRef.current === getTodayString()) {
          loadDataForDate(selectedDateRef.current, false, true);
        }
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleVisibilityChange);

    return () => {
      mounted = false;
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleVisibilityChange);
    };
  }, [loadDataForDate, loadCategoriesAndRules]);

  // Poll notifications and missed activity prompt
  const checkNotificationsAndRecovery = useCallback(async () => {
    try {
      const [notifRes, recRes] = await Promise.all([
        api.getNotifications(10),
        api.getRecoveryPrompt(),
      ]);
      setUnreadNotificationsCount(notifRes.unread_count);
      if (recRes.has_pending && recRes.gap) {
        setPendingRecoveryGap(recRes.gap);
      } else {
        setPendingRecoveryGap(null);
      }
    } catch {
      // Ignore background errors
    }
  }, []);

  useEffect(() => {
    checkNotificationsAndRecovery();
    const interval = setInterval(checkNotificationsAndRecovery, 4000);
    return () => clearInterval(interval);
  }, [checkNotificationsAndRecovery]);

  const handleOpenManualRecovery = (gap: RecoveryGapModel) => {
    setSelectedRecoveryGap(gap);
    setIsManualActivityModalOpen(true);
  };

  const handleOpenManualActivity = () => {
    setSelectedRecoveryGap(null);
    setIsManualActivityModalOpen(true);
  };

  const handleSkipRecovery = async (gapId: number) => {
    try {
      await api.resolveRecoveryPrompt(gapId, 'skip');
      setPendingRecoveryGap(null);
      checkNotificationsAndRecovery();
    } catch {
      // Ignore
    }
  };

  const handleSnoozeRecovery = async (gapId: number) => {
    try {
      await api.resolveRecoveryPrompt(gapId, 'snooze');
      setPendingRecoveryGap(null);
      checkNotificationsAndRecovery();
    } catch {
      // Ignore
    }
  };

  const handleRecordManualActivity = async (payload: any) => {
    await api.recordManualActivity(payload);
    setPendingRecoveryGap(null);
    checkNotificationsAndRecovery();
    loadDataForDate(selectedDateRef.current, false, true);
  };

  useEffect(() => {
    loadDataForDate(selectedDate);
  }, [selectedDate, loadDataForDate]);

  // Handle session description edit
  const handleSaveEdit = async (sessionKey: string, newDesc: string) => {
    await api.editSession(selectedDate, sessionKey, newDesc);
    setSessions((prev) =>
      prev.map((s) =>
        s.session_key === sessionKey
          ? { ...s, user_description: newDesc, description: newDesc }
          : s
      )
    );
    setSelectedSession((prev) =>
      prev && prev.session_key === sessionKey
        ? { ...prev, user_description: newDesc, description: newDesc }
        : prev
    );
  };

  const handleDeleteEdit = async (sessionKey: string) => {
    await api.deleteSessionEdit(selectedDate, sessionKey);
    setSessions((prev) =>
      prev.map((s) =>
        s.session_key === sessionKey
          ? { ...s, user_description: null, description: s.ai_description }
          : s
      )
    );
    setSelectedSession((prev) =>
      prev && prev.session_key === sessionKey
        ? { ...prev, user_description: null, description: prev.ai_description }
        : prev
    );
  };

  // Category Assignment & Overrides
  const handleAssignCategory = async (sessionKey: string, categoryId: number) => {
    await api.overrideSessionCategory(selectedDate, sessionKey, categoryId);
    const cat = categories.find((c) => c.id === categoryId);
    setSessions((prev) =>
      prev.map((s) =>
        s.session_key === sessionKey
          ? {
              ...s,
              category_id: categoryId,
              category_name: cat?.name || null,
              category_color: cat?.color || null,
              category_type: cat?.type || null,
              category_source: 'manual',
            }
          : s
      )
    );
    loadDataForDate(selectedDate, false, true);
  };

  const handleRemoveCategoryOverride = async (sessionKey: string) => {
    await api.removeSessionCategoryOverride(selectedDate, sessionKey);
    loadDataForDate(selectedDate, false, true);
  };

  // Category & Rules CRUD
  const handleCreateCategory = async (data: { name: string; color: string; type: string }) => {
    await api.createCategory(data.name, data.color, data.type);
    await loadCategoriesAndRules();
    loadDataForDate(selectedDate, false, true);
  };

  const handleDeleteCategory = async (id: number) => {
    await api.deleteCategory(id);
    await loadCategoriesAndRules();
    loadDataForDate(selectedDate, false, true);
  };

  const handleCreateRule = async (data: { category_id: number; match_type: string; pattern: string; priority: number }) => {
    await api.createRule(data.category_id, data.match_type, data.pattern, data.priority);
    await loadCategoriesAndRules();
    loadDataForDate(selectedDate, false, true);
  };

  const handleDeleteRule = async (id: number) => {
    await api.deleteRule(id);
    await loadCategoriesAndRules();
    loadDataForDate(selectedDate, false, true);
  };

  // Goals & Time Blocks CRUD
  const handleCreateGoal = async (data: {
    title: string;
    metric: string;
    target_seconds: number;
    is_inversion: boolean;
    category_id?: number | null;
  }) => {
    await api.createGoal(data.title, data.metric, data.target_seconds, data.is_inversion, data.category_id);
    loadDataForDate(selectedDate, false, true);
  };

  const handleDeleteGoal = async (id: number) => {
    await api.deleteGoal(id);
    loadDataForDate(selectedDate, false, true);
  };

  const handleCreateTimeBlock = async (data: {
    date: string;
    start_time: string;
    end_time: string;
    title: string;
    category_id?: number | null;
  }) => {
    await api.createTimeBlock(data.date, data.start_time, data.end_time, data.title, data.category_id);
    loadDataForDate(selectedDate, false, true);
  };

  const handleDeleteTimeBlock = async (id: number) => {
    try {
      await api.deleteTimeBlock(id);
      loadDataForDate(selectedDate, false, true);
    } catch {
      loadDataForDate(selectedDate, false, true);
    }
  };

  const handleUpdateTimeBlock = async (
    id: number,
    data: {
      date?: string;
      start_time?: string;
      end_time?: string;
      title?: string;
      category_id?: number | null;
    }
  ) => {
    await api.updateTimeBlock(id, data);
    loadDataForDate(selectedDate, false, true);
  };

  const handleDuplicateTimeBlock = async (
    id: number,
    targetDate?: string,
    timeOffsetMinutes?: number
  ) => {
    await api.duplicateTimeBlock(id, { target_date: targetDate, time_offset_minutes: timeOffsetMinutes });
    loadDataForDate(selectedDate, false, true);
  };

  const handleStartFocusForBlock = async (blockId: number) => {
    await api.startFocusForTimeBlock(blockId);
    try {
      const status = await api.getTrackerStatus();
      setIsTracking(status.is_tracking);
      if (status.active_task) {
        setActiveTask(status.active_task);
      }
    } catch {
      // non-critical
    }
    loadDataForDate(selectedDate, false, true);
  };

  const handleSkipTimeBlock = async (blockId: number) => {
    await api.skipTimeBlock(blockId);
    loadDataForDate(selectedDate, false, true);
  };

  // Tracking Toggle
  const handleToggleTracking = async () => {
    setIsTogglingTracker(true);
    setTrackerError(null);
    try {
      const res = await api.toggleTracker();
      setIsTracking(res.is_tracking);
      setTrackerMessage(res.message);
      setTimeout(() => setTrackerMessage(null), 3500);
      loadDataForDate(selectedDate);
    } catch (err: unknown) {
      setTrackerError(
        err instanceof Error
          ? err.message
          : 'Failed to toggle tracking state.'
      );
    } finally {
      setIsTogglingTracker(false);
    }
  };

  // Autostart Toggle
  const handleToggleAutostart = async () => {
    try {
      const res = await api.toggleAutostart();
      setIsAutostartEnabled(res.enabled);
      setTrackerMessage(res.message);
      setTimeout(() => setTrackerMessage(null), 3500);
    } catch (err: unknown) {
      setTrackerMessage(err instanceof Error ? err.message : 'Failed to update autostart.');
      setTimeout(() => setTrackerMessage(null), 4000);
    }
  };

  // Refresh AI Daily Insights
  const handleRefreshAiSummary = async () => {
    setIsAiRefreshing(true);
    try {
      const sum = await api.getInsightsSummary(selectedDate, true);
      setAiSummary(sum);
    } finally {
      setIsAiRefreshing(false);
    }
  };

  // Floating Widget Launcher
  const handleLaunchWidget = async () => {
    try {
      const res = await api.launchWidget();
      setTrackerMessage(res.status === 'already_running' ? 'Desktop widget is already floating on screen.' : 'Desktop widget launched successfully!');
      setTimeout(() => setTrackerMessage(null), 3500);
    } catch {
      setTrackerMessage('Could not launch widget. Start it with `python widget.py`');
      setTimeout(() => setTrackerMessage(null), 3500);
    }
  };

  return (
    <div className="app-shell">
      {/* Native-style Frameless Window Title Bar with Integrated Window Controls */}
      <WindowTitleBar />

      <div className="app-container">
        {/* Atmospheric Background Layers (Forest Artwork & Ambient Glow) */}
        <div className="ambient-lighting-layer" aria-hidden="true" />
        <div
          className="forest-landscape-backdrop"
          style={{ backgroundImage: `url(${forestArtwork})` }}
          aria-hidden="true"
        />

      {/* Sidebar Navigation */}
      <Sidebar
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        isBackendConnected={isBackendConnected}
        isTracking={isTracking}
        dbPath={dbPath}
        isAutostartEnabled={isAutostartEnabled}
        onToggleAutostart={handleToggleAutostart}
        onLaunchWidget={handleLaunchWidget}
        onOpenNewTaskModal={() => setIsNewTaskModalOpen(true)}
        unreadNotificationsCount={unreadNotificationsCount}
        userName={userName}
        onEditProfile={() => setIsEditProfileModalOpen(true)}
      />

      <div className="main-wrapper">
        {/* Top bar on non-overview views */}
        {currentTab !== 'overview' && (
          <Topbar
            selectedDate={selectedDate}
            onDateChange={setSelectedDate}
            onRefresh={(refreshAi) => loadDataForDate(selectedDate, refreshAi)}
            isLoading={isLoading}
            activeDates={activeDates}
            isTracking={isTracking}
            isToggling={isTogglingTracker}
            onToggleTracking={handleToggleTracking}
            onLaunchWidget={handleLaunchWidget}
            activeTask={activeTask}
          />
        )}

        {/* Content Body */}
        <main className="content-area">
          {/* Missed Activity Recovery Banner */}
          <MissedActivityBanner
            gap={pendingRecoveryGap}
            onOpenManualEntry={handleOpenManualRecovery}
            onSkip={handleSkipRecovery}
            onSnooze={handleSnoozeRecovery}
          />
          {trackerMessage && (
            <div
              style={{
                backgroundColor: isTracking ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                border: isTracking ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
                color: isTracking ? '#6ee7b7' : '#fca5a5',
                borderRadius: 'var(--radius-md)',
                padding: '10px 16px',
                marginBottom: '18px',
                fontSize: '13px',
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <div className={`status-orb ${isTracking ? 'orb-on' : 'orb-off'}`} />
              <span>{trackerMessage}</span>
            </div>
          )}

          {backendError && (
            <div className="error-banner">
              <AlertIcon size={20} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <strong>Backend Disconnected:</strong> {backendError}
                <div style={{ marginTop: 8 }}>
                  To launch the backend, run in PowerShell:{' '}
                  <span className="banner-code">.\.venv\Scripts\python.exe api/server.py</span>
                </div>
                <button
                  className="btn-secondary"
                  onClick={() => loadDataForDate(selectedDate)}
                  style={{ marginTop: 10, fontSize: 12, padding: '4px 10px' }}
                >
                  <RefreshIcon size={12} /> Retry Connection
                </button>
              </div>
            </div>
          )}

          {trackerError && (
            <div className="error-banner" style={{ borderColor: 'rgba(239, 68, 68, 0.4)' }}>
              <AlertIcon size={20} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <strong>Tracker Error:</strong> {trackerError}
                <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                  <button
                    className="btn-secondary"
                    onClick={handleToggleTracking}
                    disabled={isTogglingTracker}
                    style={{ fontSize: 12, padding: '4px 10px' }}
                  >
                    <RefreshIcon size={12} /> Retry Tracker
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => setTrackerError(null)}
                    style={{ fontSize: 12, padding: '4px 10px' }}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          )}

          {currentTab === 'overview' && (
            <Overview
              stats={stats}
              weeklyStats={weeklyStats}
              productivity={productivity}
              aiSummary={aiSummary}
              sessions={sessions}
              categories={categories}
              timeBlocks={timeBlocks}
              activeTask={activeTask}
              selectedDate={selectedDate}
              onSelectDate={setSelectedDate}
              onSelectSession={setSelectedSession}
              onRefreshAiSummary={handleRefreshAiSummary}
              isAiRefreshing={isAiRefreshing}
              activeDates={activeDates}
              isTracking={isTracking}
              onToggleTracking={handleToggleTracking}
              onLaunchNativeWidget={handleLaunchWidget}
              onBlockCreated={() => loadDataForDate(selectedDate, false, true)}
              onNavigateGoals={() => setCurrentTab('goals')}
              onNavigateCategories={() => setCurrentTab('categories')}
              onNavigateInsights={() => setCurrentTab('insights')}
              onNavigateTimeline={() => setCurrentTab('timeline')}
              onOpenNewBlock={() => setIsNewTaskModalOpen(true)}
              onOpenManualActivity={handleOpenManualActivity}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              userName={userName}
            />
          )}

          {currentTab === 'timeline' && (
            <TimelineView
              sessions={sessions}
              categories={categories}
              timeBlocks={timeBlocks}
              selectedDate={selectedDate}
              onSelectSession={setSelectedSession}
              activeDates={activeDates}
              onSelectDate={setSelectedDate}
              isTracking={isTracking}
              onOpenManualActivity={handleOpenManualActivity}
            />
          )}

          {currentTab === 'timeblocks' && (
            <TimeBlocksView
              timeBlocks={timeBlocks}
              timeBlocksAnalysis={timeBlocksAnalysis}
              categories={categories}
              selectedDate={selectedDate}
              onCreateTimeBlock={handleCreateTimeBlock}
              onDeleteTimeBlock={handleDeleteTimeBlock}
              onUpdateTimeBlock={handleUpdateTimeBlock}
              onDuplicateTimeBlock={handleDuplicateTimeBlock}
              onStartFocus={handleStartFocusForBlock}
              onSkipTimeBlock={handleSkipTimeBlock}
              onSelectDate={setSelectedDate}
              onNavigateTimeline={() => setCurrentTab('timeline')}
              activeTask={activeTask}
              isTracking={isTracking}
              onRefresh={() => loadDataForDate(selectedDate, false, true)}
            />
          )}

          {currentTab === 'goals' && (
            <GoalsView
              goals={goals}
              goalsProgress={goalsProgress}
              timeBlocks={timeBlocks}
              timeBlocksAnalysis={timeBlocksAnalysis}
              categories={categories}
              selectedDate={selectedDate}
              onCreateGoal={handleCreateGoal}
              onDeleteGoal={handleDeleteGoal}
              onCreateTimeBlock={handleCreateTimeBlock}
              onDeleteTimeBlock={handleDeleteTimeBlock}
            />
          )}

          {currentTab === 'categories' && (
            <CategoriesView
              categories={categories}
              rules={rules}
              onCreateCategory={handleCreateCategory}
              onDeleteCategory={handleDeleteCategory}
              onCreateRule={handleCreateRule}
              onDeleteRule={handleDeleteRule}
            />
          )}

          {(currentTab === 'insights' || currentTab === 'reports') && (
            <AnalyticsReportsView
              selectedDate={selectedDate}
              onSelectDate={setSelectedDate}
              categories={categories}
            />
          )}

          {currentTab === 'aicoach' && (
            <AiCoachView
              selectedDate={selectedDate}
              onSelectDate={setSelectedDate}
              productivity={productivity}
              aiSummary={aiSummary}
              stats={stats}
              weeklyStats={weeklyStats}
              onRefreshAi={handleRefreshAiSummary}
              isAiRefreshing={isAiRefreshing}
              onNavigateTab={setCurrentTab}
            />
          )}

          {currentTab === 'notifications' && (
            <NotificationsView
              activeTask={activeTask}
              timeBlocks={timeBlocks}
              categories={categories}
              isTracking={isTracking}
              productivity={productivity}
              onNavigateOverview={() => setCurrentTab('overview')}
              onNavigateGoals={() => setCurrentTab('goals')}
              onNotificationsChanged={checkNotificationsAndRecovery}
            />
          )}

          {currentTab === 'settings' && (
            <SettingsView
              isAutostartEnabled={isAutostartEnabled}
              onToggleAutostart={handleToggleAutostart}
              onLaunchWidget={handleLaunchWidget}
              isTracking={isTracking}
              onToggleTracking={handleToggleTracking}
              dbPath={dbPath}
              goals={goals}
              onReloadGoals={loadCategoriesAndRules}
              onNavigateCategories={() => setCurrentTab('categories')}
            />
          )}
        </main>
      </div>

      {/* Session Details & Editing Modal */}
      <SessionDetailModal
        session={selectedSession}
        selectedDate={selectedDate}
        categories={categories}
        onClose={() => setSelectedSession(null)}
        onSaveEdit={handleSaveEdit}
        onDeleteEdit={handleDeleteEdit}
        onAssignCategory={handleAssignCategory}
        onRemoveCategoryOverride={handleRemoveCategoryOverride}
      />

      {/* Plan Time Block Panel (Slide-over / Modal matching Image A) */}
      <PlanTimeBlockPanel
        categories={categories}
        selectedDate={selectedDate}
        isOpen={isNewTaskModalOpen}
        onClose={() => setIsNewTaskModalOpen(false)}
        onBlockCreated={() => {
          loadDataForDate(selectedDate, false, true);
        }}
      />

      {/* Smart Notifications: Idle Alert & Focus Check-in Toasts */}
      <SmartNotifications
        activeTask={activeTask}
        timeBlocks={timeBlocks}
        isTracking={isTracking}
        onReturnToTask={() => {
          setCurrentTab('overview');
        }}
      />

      {/* Manual Activity Recording Modal */}
      <ManualActivityModal
        isOpen={isManualActivityModalOpen}
        gap={selectedRecoveryGap}
        categories={categories}
        onClose={() => {
          setIsManualActivityModalOpen(false);
          setSelectedRecoveryGap(null);
        }}
        onSaved={checkNotificationsAndRecovery}
        onRecordManual={handleRecordManualActivity}
      />

      {/* Edit Profile Modal */}
      <EditProfileModal
        isOpen={isEditProfileModalOpen}
        onClose={() => setIsEditProfileModalOpen(false)}
        currentName={userName}
        onSave={handleSaveProfileName}
      />
      </div>
    </div>
  );
}

export default App;
