import type {
  ActiveDatesResponse,
  AiCoachChatPayload,
  AiCoachChatResponse,
  AnalyticsRangeResponse,
  AppSettingsModel,
  CategoryModel,
  CategoryRuleModel,
  DailyAiSummaryModel,
  GoalModel,
  GoalProgressModel,
  HealthResponse,
  ManualEntryRequestPayload,
  NotificationDiagnosticsModel,
  DesktopToastTestResponse,
  NotificationsResponse,
  ProductivityModel,
  RecoveryPromptResponse,
  SessionModel,
  StatsModel,
  TimeBlockAnalysisModel,
  TimeBlockDailySummaryModel,
  TimeBlockModel,
  WeeklyStatsModel,
} from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
    });
  } catch {
    throw new ApiError(
      'Unable to connect to Time Tracker backend at http://127.0.0.1:8000. Is api/server.py running?',
      0
    );
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (data && data.detail) {
        detail = data.detail;
      }
    } catch {
      // ignore json parse error on non-json error responses
    }
    throw new ApiError(detail, response.status);
  }

  return response.json() as Promise<T>;
}

export const api = {
  // Health & Dates
  getHealth(): Promise<HealthResponse> {
    return request<HealthResponse>('/health');
  },

  getActiveDates(limit = 30): Promise<ActiveDatesResponse> {
    return request<ActiveDatesResponse>(`/dates/active?limit=${limit}`);
  },

  // Stats & Timeline
  getStats(dateStr: string): Promise<StatsModel> {
    return request<StatsModel>(`/stats/${encodeURIComponent(dateStr)}`);
  },

  getWeeklyStats(dateStr: string): Promise<WeeklyStatsModel> {
    return request<WeeklyStatsModel>(`/stats/weekly/${encodeURIComponent(dateStr)}`);
  },

  getTimeline(dateStr: string, refreshAi = false): Promise<SessionModel[]> {
    const query = refreshAi ? '?refresh_ai=true' : '';
    return request<SessionModel[]>(`/timeline/${encodeURIComponent(dateStr)}${query}`);
  },

  editSession(dateStr: string, sessionKey: string, description: string): Promise<{ status: string; session_key: string }> {
    return request<{ status: string; session_key: string }>(
      `/timeline/${encodeURIComponent(dateStr)}/sessions/${encodeURIComponent(sessionKey)}/edit`,
      {
        method: 'POST',
        body: JSON.stringify({ description }),
      }
    );
  },

  deleteSessionEdit(dateStr: string, sessionKey: string): Promise<{ status: string; session_key: string }> {
    return request<{ status: string; session_key: string }>(
      `/timeline/${encodeURIComponent(dateStr)}/sessions/${encodeURIComponent(sessionKey)}/edit`,
      {
        method: 'DELETE',
      }
    );
  },

  // Tracker Process Control
  getTrackerStatus(): Promise<import('./types').TrackingStatusResponse> {
    return request<import('./types').TrackingStatusResponse>('/tracker/status');
  },

  getActiveTask(): Promise<import('./types').ActiveTaskModel | null> {
    return request<import('./types').ActiveTaskModel | null>('/tracker/active-task');
  },

  startTracker(): Promise<import('./types').TrackingStatusResponse> {
    return request<import('./types').TrackingStatusResponse>('/tracker/start', {
      method: 'POST',
    });
  },

  stopTracker(): Promise<import('./types').TrackingStatusResponse> {
    return request<import('./types').TrackingStatusResponse>('/tracker/stop', {
      method: 'POST',
    });
  },

  toggleTracker(): Promise<import('./types').TrackingStatusResponse> {
    return request<import('./types').TrackingStatusResponse>('/tracker/toggle', {
      method: 'POST',
    });
  },

  assignActiveTask(
    taskName: string,
    categoryId?: number | null,
    observationId?: number | null
  ): Promise<import('./types').ActiveTaskModel | null> {
    return request<import('./types').ActiveTaskModel | null>('/tracker/assign-task', {
      method: 'POST',
      body: JSON.stringify({
        task_name: taskName,
        category_id: categoryId,
        observation_id: observationId,
      }),
    });
  },

  // Windows Startup
  getAutostartStatus(): Promise<import('./types').AutostartStatusResponse> {
    return request<import('./types').AutostartStatusResponse>('/autostart/status');
  },

  enableAutostart(): Promise<import('./types').AutostartStatusResponse> {
    return request<import('./types').AutostartStatusResponse>('/autostart/enable', {
      method: 'POST',
    });
  },

  disableAutostart(): Promise<import('./types').AutostartStatusResponse> {
    return request<import('./types').AutostartStatusResponse>('/autostart/disable', {
      method: 'POST',
    });
  },

  toggleAutostart(): Promise<import('./types').AutostartStatusResponse> {
    return request<import('./types').AutostartStatusResponse>('/autostart/toggle', {
      method: 'POST',
    });
  },

  // -------------------------------------------------------------------------
  // Categories & Rules
  // -------------------------------------------------------------------------
  getCategories(): Promise<CategoryModel[]> {
    return request<CategoryModel[]>('/categories');
  },

  createCategory(name: string, color: string, type: string): Promise<CategoryModel> {
    return request<CategoryModel>('/categories', {
      method: 'POST',
      body: JSON.stringify({ name, color, type }),
    });
  },

  updateCategory(id: number, name: string, color: string, type: string): Promise<CategoryModel> {
    return request<CategoryModel>(`/categories/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ name, color, type }),
    });
  },

  deleteCategory(id: number): Promise<{ status: string; id: number }> {
    return request<{ status: string; id: number }>(`/categories/${id}`, {
      method: 'DELETE',
    });
  },

  getRules(): Promise<CategoryRuleModel[]> {
    return request<CategoryRuleModel[]>('/categories/rules');
  },

  createRule(category_id: number, match_type: string, pattern: string, priority = 10): Promise<CategoryRuleModel> {
    return request<CategoryRuleModel>('/categories/rules', {
      method: 'POST',
      body: JSON.stringify({ category_id, match_type, pattern, priority }),
    });
  },

  deleteRule(rule_id: number): Promise<{ status: string; id: number }> {
    return request<{ status: string; id: number }>(`/categories/rules/${rule_id}`, {
      method: 'DELETE',
    });
  },

  overrideSessionCategory(dateStr: string, sessionKey: string, category_id: number): Promise<any> {
    return request(`/timeline/${encodeURIComponent(dateStr)}/sessions/${encodeURIComponent(sessionKey)}/category`, {
      method: 'POST',
      body: JSON.stringify({ category_id }),
    });
  },

  removeSessionCategoryOverride(dateStr: string, sessionKey: string): Promise<any> {
    return request(`/timeline/${encodeURIComponent(dateStr)}/sessions/${encodeURIComponent(sessionKey)}/category`, {
      method: 'DELETE',
    });
  },

  // -------------------------------------------------------------------------
  // Goals & Time Blocks
  // -------------------------------------------------------------------------
  getGoals(): Promise<GoalModel[]> {
    return request<GoalModel[]>('/goals');
  },

  createGoal(title: string, metric: string, target_seconds: number, is_inversion = false, category_id?: number | null): Promise<GoalModel> {
    return request<GoalModel>('/goals', {
      method: 'POST',
      body: JSON.stringify({ title, metric, target_seconds, is_inversion, category_id }),
    });
  },

  updateGoal(id: number, title: string, target_seconds: number, is_inversion = false, is_active = true): Promise<GoalModel> {
    return request<GoalModel>(`/goals/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ title, target_seconds, is_inversion, is_active }),
    });
  },

  deleteGoal(id: number): Promise<{ status: string; id: number }> {
    return request<{ status: string; id: number }>(`/goals/${id}`, {
      method: 'DELETE',
    });
  },

  getGoalsProgress(dateStr: string): Promise<GoalProgressModel[]> {
    return request<GoalProgressModel[]>(`/goals/progress/${encodeURIComponent(dateStr)}`);
  },

  getTimeBlocks(dateStr: string): Promise<TimeBlockModel[]> {
    return request<TimeBlockModel[]>(`/time-blocks/${encodeURIComponent(dateStr)}`);
  },

  createTimeBlock(date: string, start_time: string, end_time: string, title: string, category_id?: number | null): Promise<TimeBlockModel> {
    return request<TimeBlockModel>('/time-blocks', {
      method: 'POST',
      body: JSON.stringify({ date, start_time, end_time, title, category_id }),
    });
  },

  updateTimeBlock(
    blockId: number,
    data: {
      date?: string;
      start_time?: string;
      end_time?: string;
      title?: string;
      category_id?: number | null;
    }
  ): Promise<TimeBlockModel> {
    return request<TimeBlockModel>(`/time-blocks/${blockId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  duplicateTimeBlock(
    blockId: number,
    data?: {
      target_date?: string;
      time_offset_minutes?: number;
    }
  ): Promise<TimeBlockModel> {
    return request<TimeBlockModel>(`/time-blocks/${blockId}/duplicate`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    });
  },

  checkTimeBlockOverlap(
    date: string,
    start_time: string,
    end_time: string,
    exclude_id?: number
  ): Promise<{ has_overlap: boolean; overlaps: TimeBlockModel[] }> {
    return request<{ has_overlap: boolean; overlaps: TimeBlockModel[] }>('/time-blocks/check-overlap', {
      method: 'POST',
      body: JSON.stringify({ date, start_time, end_time, exclude_id }),
    });
  },

  getTimeBlocksDailySummary(dateStr: string): Promise<TimeBlockDailySummaryModel> {
    return request<TimeBlockDailySummaryModel>(`/time-blocks/summary/${encodeURIComponent(dateStr)}`);
  },

  deleteTimeBlock(id: number): Promise<{ status: string; id: number }> {
    return request<{ status: string; id: number }>(`/time-blocks/${id}`, {
      method: 'DELETE',
    });
  },

  getTimeBlocksAnalysis(dateStr: string): Promise<TimeBlockAnalysisModel[]> {
    return request<TimeBlockAnalysisModel[]>(`/time-blocks/analysis/${encodeURIComponent(dateStr)}`);
  },

  startFocusForTimeBlock(blockId: number): Promise<{ status: string; block_id: number; title: string }> {
    return request<{ status: string; block_id: number; title: string }>(`/time-blocks/${blockId}/start-focus`, {
      method: 'POST',
    });
  },

  snoozeTimeBlock(blockId: number, minutes = 5): Promise<{ status: string; block_id: number; minutes: number }> {
    return request<{ status: string; block_id: number; minutes: number }>(`/time-blocks/${blockId}/snooze`, {
      method: 'POST',
      body: JSON.stringify({ minutes }),
    });
  },

  skipTimeBlock(blockId: number): Promise<{ status: string; block_id: number }> {
    return request<{ status: string; block_id: number }>(`/time-blocks/${blockId}/skip`, {
      method: 'POST',
    });
  },

  rescheduleTimeBlock(
    blockId: number,
    date: string,
    startTime: string,
    endTime: string,
  ): Promise<{ status: string; block_id: number; date: string; start_time: string; end_time: string }> {
    return request<{ status: string; block_id: number; date: string; start_time: string; end_time: string }>(
      `/time-blocks/${blockId}/reschedule`,
      {
        method: 'POST',
        body: JSON.stringify({ date, start_time: startTime, end_time: endTime }),
      },
    );
  },

  getCurrentPlannedBlock(): Promise<{ has_block: boolean; block: TimeBlockModel | null }> {
    return request<{ has_block: boolean; block: TimeBlockModel | null }>('/time-blocks/current');
  },

  testTimeBlockToast(): Promise<{ status: string; supported: boolean }> {
    return request<{ status: string; supported: boolean }>('/notifications/test-time-block-toast', {
      method: 'POST',
    });
  },

  // -------------------------------------------------------------------------
  // Productivity Analysis & Daily AI Insights
  // -------------------------------------------------------------------------
  getProductivity(dateStr: string): Promise<ProductivityModel> {
    return request<ProductivityModel>(`/productivity/${encodeURIComponent(dateStr)}`);
  },

  getInsightsSummary(dateStr: string, refreshAi = false): Promise<DailyAiSummaryModel> {
    const query = refreshAi ? '?refresh_ai=true' : '';
    return request<DailyAiSummaryModel>(`/insights/summary/${encodeURIComponent(dateStr)}${query}`);
  },

  // -------------------------------------------------------------------------
  // Desktop Widget Control
  // -------------------------------------------------------------------------
  getWidgetStatus(): Promise<{ is_running: boolean; pids: number[] }> {
    return request<{ is_running: boolean; pids: number[] }>('/widget/status');
  },

  launchWidget(): Promise<{ status: string; pid?: number }> {
    return request<{ status: string; pid?: number }>('/widget/launch', {
      method: 'POST',
    });
  },

  // -------------------------------------------------------------------------
  // Notifications, Windows Toasts & Missed Activity Recovery
  // -------------------------------------------------------------------------
  getNotifications(limit = 50, filterType?: string): Promise<NotificationsResponse> {
    const query = filterType && filterType !== 'all' ? `?limit=${limit}&filter_type=${encodeURIComponent(filterType)}` : `?limit=${limit}`;
    return request<NotificationsResponse>(`/notifications${query}`);
  },

  markNotificationRead(notificationId: number): Promise<{ status: string; id: number }> {
    return request<{ status: string; id: number }>(`/notifications/${notificationId}/read`, {
      method: 'POST',
    });
  },

  markAllNotificationsRead(): Promise<{ status: string; marked_read_count: number }> {
    return request<{ status: string; marked_read_count: number }>('/notifications/read-all', {
      method: 'POST',
    });
  },

  dismissNotification(notificationId: number): Promise<{ status: string; id: number }> {
    return request<{ status: string; id: number }>(`/notifications/${notificationId}`, {
      method: 'DELETE',
    });
  },

  testDesktopToast(): Promise<DesktopToastTestResponse> {
    return request<DesktopToastTestResponse>('/notifications/test-desktop-toast', {
      method: 'POST',
    });
  },

  getNotificationDiagnostics(): Promise<NotificationDiagnosticsModel> {
    return request<NotificationDiagnosticsModel>('/notifications/diagnostics');
  },

  snoozeNotification(alertType: string, minutes = 15): Promise<{ status: string }> {
    return request<{ status: string }>('/notifications/snooze', {
      method: 'POST',
      body: JSON.stringify({ alert_type: alertType, minutes }),
    });
  },

  getRecoveryPrompt(): Promise<RecoveryPromptResponse> {
    return request<RecoveryPromptResponse>('/notifications/recovery-prompt');
  },

  resolveRecoveryPrompt(gapId: number, action: 'skip' | 'snooze'): Promise<{ status: string }> {
    return request<{ status: string }>('/notifications/recovery-prompt/resolve', {
      method: 'POST',
      body: JSON.stringify({ gap_id: gapId, action }),
    });
  },

  recordManualActivity(payload: ManualEntryRequestPayload): Promise<any> {
    return request<any>('/activity/manual-entry', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getAnalyticsRange(startDate: string, endDate: string, refreshAi = false): Promise<AnalyticsRangeResponse> {
    return request<AnalyticsRangeResponse>(
      `/analytics/range?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}${refreshAi ? '&refresh_ai=true' : ''}`
    );
  },

  sendAiCoachChat(payload: AiCoachChatPayload): Promise<AiCoachChatResponse> {
    return request<AiCoachChatResponse>('/aicoach/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getSettings(): Promise<AppSettingsModel> {
    return request<AppSettingsModel>('/settings');
  },

  updateSettings(settings: Partial<AppSettingsModel>): Promise<AppSettingsModel> {
    return request<AppSettingsModel>('/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  },

  getPendingDesktopAction(): Promise<{ action: string; params?: Record<string, any>; timestamp: number } | null> {
    return request<{ action: string; params?: Record<string, any>; timestamp: number } | null>('/desktop/pending-action');
  },

  async minimizeWindow(): Promise<{ status: string }> {
    const pyApi = (window as any).pywebview?.api;
    if (pyApi && typeof pyApi.minimize_window === 'function') {
      try {
        await pyApi.minimize_window();
        return { status: 'ok' };
      } catch {
        // Fallback to HTTP
      }
    }
    return request<{ status: string }>('/desktop/window/minimize', { method: 'POST' });
  },

  async maximizeWindow(): Promise<{ status: string; is_maximized: boolean }> {
    const pyApi = (window as any).pywebview?.api;
    if (pyApi && typeof pyApi.maximize_window === 'function') {
      try {
        const res = await pyApi.maximize_window();
        return { status: 'ok', is_maximized: res?.is_maximized ?? true };
      } catch {
        // Fallback to HTTP
      }
    }
    return request<{ status: string; is_maximized: boolean }>('/desktop/window/maximize', { method: 'POST' });
  },

  async restoreWindow(): Promise<{ status: string; is_maximized: boolean }> {
    const pyApi = (window as any).pywebview?.api;
    if (pyApi && typeof pyApi.restore_window === 'function') {
      try {
        const res = await pyApi.restore_window();
        return { status: 'ok', is_maximized: res?.is_maximized ?? false };
      } catch {
        // Fallback to HTTP
      }
    }
    return request<{ status: string; is_maximized: boolean }>('/desktop/window/restore', { method: 'POST' });
  },

  async toggleMaximizeWindow(): Promise<{ status: string; is_maximized: boolean }> {
    const pyApi = (window as any).pywebview?.api;
    if (pyApi && typeof pyApi.toggle_maximize_window === 'function') {
      try {
        const res = await pyApi.toggle_maximize_window();
        return { status: 'ok', is_maximized: res?.is_maximized ?? true };
      } catch {
        // Fallback to HTTP
      }
    }
    return request<{ status: string; is_maximized: boolean }>('/desktop/window/toggle-maximize', { method: 'POST' });
  },

  async closeWindow(): Promise<{ status: string }> {
    const pyApi = (window as any).pywebview?.api;
    if (pyApi && typeof pyApi.close_window === 'function') {
      try {
        await pyApi.close_window();
        return { status: 'ok' };
      } catch {
        // Fallback to HTTP
      }
    }
    return request<{ status: string }>('/desktop/window/close', { method: 'POST' });
  },

  async getWindowState(): Promise<{ is_desktop: boolean; is_maximized: boolean; is_minimized: boolean }> {
    const pyApi = (window as any).pywebview?.api;
    if (pyApi && typeof pyApi.get_window_state === 'function') {
      try {
        const res = await pyApi.get_window_state();
        if (res && typeof res.is_desktop === 'boolean') {
          return res;
        }
      } catch {
        // Fallback to HTTP
      }
    }
    try {
      return await request<{ is_desktop: boolean; is_maximized: boolean; is_minimized: boolean }>('/desktop/window/state');
    } catch {
      return { is_desktop: Boolean((window as any).pywebview), is_maximized: true, is_minimized: false };
    }
  },
};
