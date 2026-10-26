export interface SessionModel {
  display_number: number;
  session_key: string;
  kind: 'active' | 'idle';
  app: string;
  title: string;
  start: string; // ISO-8601
  end: string;   // ISO-8601
  duration_seconds: number;
  duration_label: string;
  description: string | null;
  ai_description: string | null;
  user_description: string | null;
  is_uncertain: boolean;
  confidence: number | null;
  source: string | null;
  url: string | null;
  observation_ids: number[];
  is_ongoing?: boolean;
  domain?: string | null;
  task?: string | null;
  task_category?: string | null;
  task_confidence?: number | null;

  // Custom Category Fields
  category_id?: number | null;
  category_name?: string | null;
  category_color?: string | null;
  category_type?: 'focus' | 'work' | 'personal' | 'distraction' | string | null;
  category_source?: string | null;

  // Activity Intelligence & Specific Attribution
  activity_name?: string | null;
  specific_task?: string | null;
  site_name?: string | null;
  document_name?: string | null;
  context_label?: string | null;
  is_browser?: boolean;
}

export interface AppBreakdownItem {
  app: string;
  seconds: number;
  label: string;
  pct: number;
}

export interface StatsModel {
  date: string;
  active_seconds: number;
  idle_seconds: number;
  active_label: string;
  idle_label: string;
  session_count: number;
  app_breakdown: AppBreakdownItem[];
  has_data: boolean;

  // Explicit productive work metrics
  productive_work_seconds?: number;
  productive_work_label?: string;
  total_tracked_seconds?: number;
  total_tracked_label?: string;
  focus_seconds?: number;
  focus_label?: string;
  distraction_seconds?: number;
  distraction_label?: string;
  unclassified_seconds?: number;
  unclassified_label?: string;
}

export interface WeeklyDayItem {
  date: string;
  active_seconds: number;
  label: string;
  productive_work_seconds?: number;
  productive_work_label?: string;
  focus_seconds?: number;
  distraction_seconds?: number;
}

export interface WeeklyStatsModel {
  days: WeeklyDayItem[];
}

export interface HealthResponse {
  status: string;
  db: string;
  db_exists: boolean;
}

export interface ActiveDatesResponse {
  dates: string[];
}

export interface ActiveTaskModel {
  observation_id: number;
  kind: string;
  app: string;
  title: string;
  start_time: string;
  is_open: boolean;
  user_task?: string | null;
  activity_name?: string | null;
  specific_task?: string | null;
  site_name?: string | null;
  context_label?: string | null;
  is_browser?: boolean;
  category_id?: number | null;
  category_name?: string | null;
}

export interface TrackingStatusResponse {
  is_tracking: boolean;
  pid: number | null;
  status_text: string;
  message: string;
  active_task?: ActiveTaskModel | null;
}

export interface AutostartStatusResponse {
  enabled: boolean;
  command: string;
  supported: boolean;
  message: string;
}

// ---------------------------------------------------------------------------
// Categories & Rules
// ---------------------------------------------------------------------------

export interface CategoryModel {
  id: number;
  name: string;
  color: string;
  type: 'focus' | 'work' | 'personal' | 'distraction';
  created_at: string;
}

export interface CategoryRuleModel {
  id: number;
  category_id: number;
  match_type: 'domain' | 'url' | 'app' | 'title_contains';
  pattern: string;
  priority: number;
  created_at: string;
  category_name?: string;
  category_color?: string;
  category_type?: string;
}

// ---------------------------------------------------------------------------
// Goals & Time Blocks
// ---------------------------------------------------------------------------

export interface GoalModel {
  id: number;
  title: string;
  metric: 'work_time' | 'focus_time' | 'distraction_time' | 'category_time';
  target_seconds: number;
  is_inversion: boolean;
  category_id?: number | null;
  category_name?: string | null;
  category_color?: string | null;
  period: string;
  is_active: boolean;
  created_at: string;
}

export interface GoalProgressModel {
  id: number;
  title: string;
  metric: string;
  target_seconds: number;
  target_label: string;
  actual_seconds: number;
  actual_label: string;
  is_inversion: boolean;
  progress_pct: number;
  is_achieved: boolean;
  status_text: string;
  category_name?: string | null;
  category_color?: string | null;
}

export interface TimeBlockModel {
  id: number;
  date: string;
  start_time: string;
  end_time: string;
  title: string;
  category_id?: number | null;
  category_name?: string | null;
  category_color?: string | null;
  category_type?: string | null;
  display_time_label?: string;
  created_at: string;
}

export interface TimeBlockAnalysisModel {
  block_id: number;
  title: string;
  date?: string;
  start_time: string;
  end_time: string;
  display_time_label?: string;
  planned_duration_seconds: number;
  planned_label: string;
  matching_seconds: number;
  matching_label: string;
  distraction_seconds: number;
  distraction_label: string;
  idle_seconds: number;
  match_pct: number;
  status: 'Completed' | 'Partial' | 'Interrupted' | 'Missed' | 'In Progress' | 'Upcoming' | 'Skipped';
  is_current?: boolean;
  is_active_focus?: boolean;
  interruptions: number;
  category_name?: string | null;
  category_color?: string | null;
  category_type?: string | null;
  observed_apps: string[];
}

export interface TimeBlockDailySummaryModel {
  date: string;
  total_blocks: number;
  planned_seconds: number;
  planned_label: string;
  focus_seconds: number;
  focus_label: string;
  adherence_pct: number;
  distraction_seconds: number;
  distraction_label: string;
  idle_seconds: number;
  idle_label: string;
  in_progress_count: number;
  upcoming_count: number;
  completed_count: number;
  missed_count: number;
  skipped_count: number;
}

// ---------------------------------------------------------------------------
// Productivity & AI Insights
// ---------------------------------------------------------------------------

export interface TopInterruptor {
  app: string;
  count: number;
  lost_seconds: number;
  lost_label: string;
}

export interface FocusStreak {
  app: string;
  title: string;
  start: string;
  end: string;
  duration_seconds: number;
  duration_label: string;
}

export interface CategoryBreakdownItem {
  name: string;
  type: string;
  color: string;
  seconds: number;
  label: string;
  pct: number;
}

export interface DayComparison {
  work_change_seconds?: number;
  work_change_label?: string;
  work_improved?: boolean;
  focus_change_seconds: number;
  focus_change_label: string;
  focus_improved: boolean;
  distraction_change_seconds: number;
  distraction_change_label: string;
  distraction_improved: boolean;
  interruption_change: number;
}

export interface ProductivityModel {
  date: string;
  total_work_seconds: number;
  total_work_label: string;
  productive_work_seconds?: number;
  productive_work_label?: string;
  total_tracked_seconds?: number;
  total_tracked_label?: string;
  total_idle_seconds: number;
  total_idle_label: string;
  focus_seconds: number;
  focus_label: string;
  study_seconds?: number;
  study_label?: string;
  distraction_seconds: number;
  distraction_label: string;
  unclassified_seconds?: number;
  unclassified_label?: string;
  productivity_score: number;
  category_breakdown: CategoryBreakdownItem[];
  total_interruptions: number;
  top_interruptors: TopInterruptor[];
  longest_streak?: FocusStreak | null;
  comparison?: DayComparison | null;
  goals: GoalProgressModel[];
  time_blocks: TimeBlockAnalysisModel[];
}

export interface AiSuggestionItem {
  id?: string;
  icon?: string;
  text: string;
  type?: string;
}

export interface DailyAiSummaryModel {
  headline?: string;
  key_takeaway: string;
  narrative?: string;
  key_win?: string;
  main_challenge?: string;
  suggestion?: string;
  what_went_well?: string;
  what_got_in_way?: string;
  focus_streak_summary: string;
  interruption_analysis: string;
  goals_summary: string;
  recommendations: string[];
  suggestions?: AiSuggestionItem[];
  source: string;
  generated_at: string;
  generated_time_label?: string;
}

// ---------------------------------------------------------------------------
// Notifications, App Settings & Missed Activity Recovery
// ---------------------------------------------------------------------------

export interface NotificationModel {
  id: number;
  type: 'idle' | 'focus' | 'recovery' | 'time_block' | 'missed_block' | 'milestone' | 'warning' | string;
  title: string;
  body: string;
  details?: any;
  unread: boolean;
  dismissed: boolean;
  status?: 'delivered' | 'snoozed' | 'acted_upon' | 'skipped' | 'dismissed' | string;
  created_at: string;
}

export interface NotificationsResponse {
  notifications: NotificationModel[];
  unread_count: number;
}

export interface AppSettingsModel {
  user_name?: string;
  notifications_enabled: boolean;
  windows_toasts_enabled: boolean;
  notification_sound: 'default' | 'silent' | 'custom' | string;
  idle_alert_threshold_minutes: number;
  idle_alerts_enabled?: boolean;
  focus_mismatch_alerts_enabled?: boolean;
  mismatch_grace_minutes: number;
  distraction_cooldown_minutes: number;
  missed_recovery_threshold_minutes: number;
  missed_recovery_enabled: boolean;
  missed_block_recovery_enabled?: boolean;
  time_block_reminders_enabled?: boolean;
  time_block_autostart_focus?: boolean;
  default_snooze_minutes?: number;
  notification_rate_limit_seconds?: number;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  overnight_suppression_enabled?: boolean;
  overnight_sleep_start?: string;
  overnight_sleep_end?: string;
}

export interface NotificationDiagnosticsModel {
  platform: string;
  is_windows: boolean;
  notifications_enabled: boolean;
  windows_toasts_enabled: boolean;
  aumid: string;
  aumid_registered: boolean;
  show_banner_registry: boolean;
  shortcut_installed: boolean;
  shortcut_target: string | null;
  notifier_setting: string;
  user_notification_state: string;
  action_center_count: number;
  last_attempt_time: string | null;
  last_submission_result: string | null;
  last_delivery_error: string | null;
  total_dispatched: number;
  total_failed: number;
  troubleshooting_hints: string[];
}

export interface DesktopToastTestResponse {
  status: 'submitted' | 'failed' | string;
  supported: boolean;
  result: {
    success: boolean;
    status: string;
    notifier_setting?: string;
    error?: string | null;
  };
  diagnostics?: NotificationDiagnosticsModel;
}

export interface RecoveryGapModel {
  id: number;
  gap_start: string;
  gap_end: string;
  duration_seconds: number;
  status: 'pending' | 'resolved_added' | 'skipped' | 'snoozed';
  created_at: string;
  reviewed_at?: string | null;
}

export interface RecoveryPromptResponse {
  has_pending: boolean;
  gap: RecoveryGapModel | null;
}

export interface ManualEntryRequestPayload {
  task_name: string;
  start_time: string;
  end_time: string;
  category_id?: number | null;
  notes?: string;
  recovery_gap_id?: number | null;
}

/**
 * Format local date as YYYY-MM-DD using user's system timezone.
 * Avoids toISOString().slice(0, 10) UTC day-boundary drift.
 */
export function getLocalTodayString(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function formatLocalDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export interface PeriodComparisonItem {
  change_seconds: number;
  change_label: string;
  change_pct: number;
  display_str: string;
  improved: boolean;
  previous_seconds: number;
  previous_label: string;
}

export interface AnalyticsKpiModel {
  productive_work_seconds: number;
  productive_work_label: string;
  deep_focus_seconds: number;
  deep_focus_label: string;
  distraction_seconds: number;
  distraction_label: string;
  total_tracked_seconds: number;
  total_tracked_label: string;
  total_idle_seconds: number;
  total_idle_label: string;
  comparison: {
    productive_work: PeriodComparisonItem;
    deep_focus: PeriodComparisonItem;
    distraction: PeriodComparisonItem;
    total_tracked: PeriodComparisonItem;
    prior_period_label: string;
  };
}

export interface AnalyticsScoreModel {
  score: number;
  label: string;
  color: string;
  focus_ratio_pct: number;
  distraction_ratio_pct: number;
  explanation: string;
  longest_streak: {
    app: string;
    title: string;
    start: string;
    end: string;
    duration_seconds: number;
    duration_label: string;
  } | null;
  total_interruptions: number;
}

export interface HierarchicalUsageItem {
  id: string;
  app: string;
  activity_name: string;
  specific_task: string;
  site_name?: string;
  browser_name?: string | null;
  category: string;
  category_color: string;
  category_type: string;
  duration_seconds: number;
  duration_label: string;
  pct: number;
  switches: number;
  is_browser: boolean;
  is_uncertain: boolean;
  children?: HierarchicalUsageItem[];
}

export interface DailyTrendPoint {
  date: string;
  day_name: string;
  active_seconds: number;
  active_label: string;
  productive_seconds: number;
  productive_label: string;
  distraction_seconds: number;
  distraction_label: string;
  focus_seconds: number;
  focus_label: string;
}

export interface AnalyticsRangeResponse {
  start_date: string;
  end_date: string;
  days_count: number;
  kpi: AnalyticsKpiModel;
  productivity_score: AnalyticsScoreModel;
  ai_synthesis: {
    key_takeaway: string;
    focus_streak_summary: string;
    interruption_analysis: string;
    recommendations: string[];
    source: string;
    generated_at: string;
  };
  category_breakdown: Array<{
    name: string;
    type: string;
    color: string;
    seconds: number;
    label: string;
    pct: number;
  }>;
  app_breakdown: HierarchicalUsageItem[];
  browser_breakdown?: HierarchicalUsageItem[];
  daily_trends: DailyTrendPoint[];
  top_interruptors: Array<{
    app: string;
    count: number;
    lost_seconds: number;
    lost_label: string;
  }>;
  detailed_sessions: SessionModel[];
}

export interface AiCoachChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  grounded?: boolean;
  sources?: string[];
  quick_actions?: Array<{
    label: string;
    action: string;
    param: string;
  }>;
}

export interface AiCoachChatPayload {
  message: string;
  selected_date?: string;
  history?: Array<{
    role: string;
    content: string;
    date_scope?: string;
  }>;
  preset_action?: string;
}

export interface AiCoachChatResponse {
  response: string;
  grounded: boolean;
  sources: string[];
  quick_actions: Array<{
    label: string;
    action: string;
    param: string;
  }>;
  date_scope: string;
  meta?: Record<string, any>;
}
