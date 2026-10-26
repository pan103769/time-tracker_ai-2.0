import React, { useEffect, useState } from 'react';
import { api } from '../api';
import type { AppSettingsModel, GoalModel, NotificationDiagnosticsModel } from '../types';
import {
  AlertTriangleIcon,
  BellIcon,
  CheckIcon,
  ClockIcon,
  InfoIcon,
  RefreshIcon,
  SparklesIcon,
  TargetIcon,
  WidgetIcon,
} from './Icons';

interface SettingsViewProps {
  isAutostartEnabled: boolean;
  onToggleAutostart: () => void;
  onLaunchWidget: () => void;
  isTracking: boolean;
  onToggleTracking: () => void;
  dbPath?: string;
  goals: GoalModel[];
  onReloadGoals: () => void;
  onNavigateCategories: () => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({
  isAutostartEnabled,
  onToggleAutostart,
  onLaunchWidget,
  isTracking,
  onToggleTracking,
  dbPath,
  goals = [],
  onReloadGoals,
  onNavigateCategories,
}) => {
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [widgetResetStatus, setWidgetResetStatus] = useState<string | null>(null);
  const [notifSettings, setNotifSettings] = useState<AppSettingsModel>({
    notifications_enabled: true,
    windows_toasts_enabled: true,
    notification_sound: 'default',
    idle_alerts_enabled: true,
    idle_alert_threshold_minutes: 3,
    focus_mismatch_alerts_enabled: true,
    mismatch_grace_minutes: 2,
    distraction_cooldown_minutes: 15,
    time_block_reminders_enabled: true,
    time_block_autostart_focus: false,
    missed_block_recovery_enabled: true,
    missed_recovery_threshold_minutes: 30,
    missed_recovery_enabled: true,
    default_snooze_minutes: 5,
    notification_rate_limit_seconds: 20,
    quiet_hours_enabled: false,
    quiet_hours_start: '22:00',
    quiet_hours_end: '07:00',
    overnight_suppression_enabled: true,
    overnight_sleep_start: '23:00',
    overnight_sleep_end: '07:00',
  });
  const [notifSaveStatus, setNotifSaveStatus] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<NotificationDiagnosticsModel | null>(null);
  const [isDiagLoading, setIsDiagLoading] = useState<boolean>(false);
  const [testResultFeedback, setTestResultFeedback] = useState<{
    status: 'success' | 'error' | 'running';
    message: string;
    details?: string;
  } | null>(null);

  const loadDiagnostics = async () => {
    setIsDiagLoading(true);
    try {
      const diag = await api.getNotificationDiagnostics();
      setDiagnostics(diag);
    } catch {
      // ignore
    } finally {
      setIsDiagLoading(false);
    }
  };

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setNotifSettings(s))
      .catch(() => {});
    loadDiagnostics();
  }, []);

  const handleUpdateNotifSetting = async (key: keyof AppSettingsModel, val: any) => {
    const updated = { ...notifSettings, [key]: val };
    setNotifSettings(updated);
    try {
      await api.updateSettings({ [key]: val });
      setNotifSaveStatus('Saved');
      setTimeout(() => setNotifSaveStatus(null), 2500);
      loadDiagnostics();
    } catch {
      setNotifSaveStatus('Failed to save');
      setTimeout(() => setNotifSaveStatus(null), 2500);
    }
  };

  const handleTestDesktopToast = async () => {
    setTestResultFeedback({
      status: 'running',
      message: 'Dispatching desktop toast banner to Windows Shell (holding 2.5s)...',
    });
    try {
      const res = await api.testDesktopToast();
      if (res.diagnostics) {
        setDiagnostics(res.diagnostics);
      } else {
        loadDiagnostics();
      }
      if (res.status === 'submitted' || res.result?.success) {
        setTestResultFeedback({
          status: 'success',
          message: 'Desktop notification banner submitted successfully to Windows Shell!',
          details: `AUMID: TimeTrackerAI.App · WinRT Setting: ${res.result?.notifier_setting || 'Enabled'} · Mode: scenario="reminder"`,
        });
      } else {
        setTestResultFeedback({
          status: 'error',
          message: 'Notification submission failed.',
          details: res.result?.error || 'Windows rejected or dropped the notification.',
        });
      }
    } catch (err: any) {
      setTestResultFeedback({
        status: 'error',
        message: 'Error communicating with notification dispatcher.',
        details: err?.message || String(err),
      });
    }
  };

  const handleTestTimeBlockToast = async () => {
    setTestResultFeedback({
      status: 'running',
      message: 'Sending test preview of Time Block reminder alert...',
    });
    try {
      const res = await api.testTimeBlockToast();
      loadDiagnostics();
      if (res.status === 'queued' || res.status === 'submitted') {
        setTestResultFeedback({
          status: 'success',
          message: 'Time-block start reminder preview sent with interactive actions!',
          details: 'Clearly labeled as [TEST] preview with Start Focus, Snooze 5 min, Skip, and Open Planner.',
        });
      } else {
        setTestResultFeedback({
          status: 'error',
          message: 'Failed to send Time Block reminder preview.',
        });
      }
    } catch (err: any) {
      setTestResultFeedback({
        status: 'error',
        message: 'Error sending Time Block reminder preview.',
        details: err?.message || String(err),
      });
    }
  };

  // Goal targets state (default to existing goals or sensible defaults)
  const safeGoals = goals || [];
  const workGoal = safeGoals.find((g) => g.metric === 'work_time');
  const focusGoal = safeGoals.find((g) => g.metric === 'focus_time');
  const distractionGoal = safeGoals.find((g) => g.metric === 'distraction_time');

  const [workHours, setWorkHours] = useState<number>(
    workGoal ? Math.round((workGoal.target_seconds / 3600) * 10) / 10 : 5.0
  );
  const [focusHours, setFocusHours] = useState<number>(
    focusGoal ? Math.round((focusGoal.target_seconds / 3600) * 10) / 10 : 3.0
  );
  const [distractionHours, setDistractionHours] = useState<number>(
    distractionGoal ? Math.round((distractionGoal.target_seconds / 3600) * 10) / 10 : 1.0
  );

  const handleSaveGoals = async () => {
    setSaveStatus('Saving…');
    try {
      if (workGoal) {
        await api.updateGoal(workGoal.id, workGoal.title, Math.round(workHours * 3600), false, true);
      }
      if (focusGoal) {
        await api.updateGoal(focusGoal.id, focusGoal.title, Math.round(focusHours * 3600), false, true);
      }
      if (distractionGoal) {
        await api.updateGoal(distractionGoal.id, distractionGoal.title, Math.round(distractionHours * 3600), true, true);
      }
      onReloadGoals();
      setSaveStatus('Goals saved successfully!');
      setTimeout(() => setSaveStatus(null), 3000);
    } catch {
      setSaveStatus('Failed to save goals.');
      setTimeout(() => setSaveStatus(null), 3000);
    }
  };

  const handleResetWidgetPosition = () => {
    try {
      localStorage.removeItem('timetracker_widget_pos');
      setWidgetResetStatus('Widget position reset to top-left (60, 60).');
      setTimeout(() => setWidgetResetStatus(null), 3000);
    } catch {
      // Ignore
    }
  };

  return (
    <div className="settings-view-container">
      <div className="settings-header">
        <h2 className="settings-page-title">Application Settings</h2>
        <p className="settings-page-desc">
          Configure productivity goals, background tracking, floating desktop widget, and Windows startup preferences.
        </p>
      </div>

      <div className="settings-grid">
        {/* Daily Goal Targets Section */}
        <div className="card settings-card">
          <div className="card-title-bar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <TargetIcon size={18} color="var(--accent-purple, #8065FF)" />
              <span className="card-title">Productivity Goal Targets</span>
            </div>
          </div>
          <p className="settings-card-sub">
            Set your target hours for work, deep focus, and maximum allowable distraction per day.
          </p>

          <div className="settings-fields-group">
            <div className="settings-field-row">
              <label htmlFor="input-work-target">Daily Work Time Target</label>
              <div className="input-with-unit">
                <input
                  id="input-work-target"
                  type="number"
                  step="0.5"
                  min="0.5"
                  max="24"
                  value={workHours}
                  onChange={(e) => setWorkHours(parseFloat(e.target.value) || 0)}
                />
                <span className="unit-label">hours</span>
              </div>
            </div>

            <div className="settings-field-row">
              <label htmlFor="input-focus-target">Deep Focus Time Target</label>
              <div className="input-with-unit">
                <input
                  id="input-focus-target"
                  type="number"
                  step="0.5"
                  min="0.5"
                  max="24"
                  value={focusHours}
                  onChange={(e) => setFocusHours(parseFloat(e.target.value) || 0)}
                />
                <span className="unit-label">hours</span>
              </div>
            </div>

            <div className="settings-field-row">
              <label htmlFor="input-distraction-target">Max Distraction Limit (Inversion Goal)</label>
              <div className="input-with-unit">
                <input
                  id="input-distraction-target"
                  type="number"
                  step="0.25"
                  min="0.25"
                  max="12"
                  value={distractionHours}
                  onChange={(e) => setDistractionHours(parseFloat(e.target.value) || 0)}
                />
                <span className="unit-label">hours</span>
              </div>
            </div>
          </div>

          <div className="settings-actions-bar">
            <button
              type="button"
              className="btn-primary"
              onClick={handleSaveGoals}
            >
              <CheckIcon size={14} />
              <span>Save Goal Targets</span>
            </button>
            {saveStatus && <span className="settings-status-note">{saveStatus}</span>}
          </div>
        </div>

        {/* Windows Notifications & Smart Alerts Section */}
        <div className="card settings-card">
          <div className="card-title-bar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <BellIcon size={18} color="var(--accent-pink, #FA5275)" />
              <span className="card-title">Windows Notifications &amp; Smart Alerts</span>
            </div>
            {notifSaveStatus && <span className="settings-status-note">{notifSaveStatus}</span>}
          </div>
          <p className="settings-card-sub">
            Real Windows desktop toast notifications, idle detection, schedule-mismatch alerts, and missed-activity recovery.
          </p>

          <div className="settings-fields-group">
            {/* Master Notifications Toggle */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Enable All Notifications</span>
                <p className="settings-toggle-desc">
                  Master switch for in-app alerts and desktop notifications.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.notifications_enabled ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('notifications_enabled', !notifSettings.notifications_enabled)}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Native Windows Toast Notifications */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Native Windows Desktop Notifications</span>
                <p className="settings-toggle-desc">
                  Show real Windows toast banners with interactive actions even when minimized or closed.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.windows_toasts_enabled ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('windows_toasts_enabled', !notifSettings.windows_toasts_enabled)}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Time-Block Start Reminders */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Time-Block Start Reminders</span>
                <p className="settings-toggle-desc">
                  Notify right before scheduled time blocks begin, with quick Start Focus, Snooze, and Skip actions.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.time_block_reminders_enabled ?? true ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('time_block_reminders_enabled', !(notifSettings.time_block_reminders_enabled ?? true))}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Auto-start Focus Session */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Auto-Start Focus Sessions</span>
                <p className="settings-toggle-desc">
                  Automatically start tracking and set the active task when a planned time block starts.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.time_block_autostart_focus ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('time_block_autostart_focus', !notifSettings.time_block_autostart_focus)}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Focus Drift / Distraction Alerts */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Focus Drift &amp; Distraction Alerts</span>
                <p className="settings-toggle-desc">
                  Alert when sustained non-work or unrelated activity occurs during a planned focus block.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.focus_mismatch_alerts_enabled ?? true ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('focus_mismatch_alerts_enabled', !(notifSettings.focus_mismatch_alerts_enabled ?? true))}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Idle / Inactivity Alerts */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Inactivity &amp; Step-Away Alerts</span>
                <p className="settings-toggle-desc">
                  Notify once when away from the computer to help you resume tracking or take a break.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.idle_alerts_enabled ?? true ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('idle_alerts_enabled', !(notifSettings.idle_alerts_enabled ?? true))}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Missed-Block Recovery Prompts */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Missed-Block Recovery Prompts</span>
                <p className="settings-toggle-desc">
                  Offer low-friction rescheduling when a planned block finishes without a recorded focus session.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.missed_block_recovery_enabled ?? true ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('missed_block_recovery_enabled', !(notifSettings.missed_block_recovery_enabled ?? true))}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Missed Offline Activity Recovery */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Missed-Activity Recovery Prompt</span>
                <p className="settings-toggle-desc">
                  Prompt to record untracked offline work after pauses longer than threshold.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.missed_recovery_enabled ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('missed_recovery_enabled', !notifSettings.missed_recovery_enabled)}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {/* Notification Sound */}
            <div className="settings-field-row">
              <label htmlFor="select-notif-sound">Notification Sound</label>
              <div className="input-with-unit">
                <select
                  id="select-notif-sound"
                  value={notifSettings.notification_sound || 'default'}
                  onChange={(e) => handleUpdateNotifSetting('notification_sound', e.target.value)}
                  style={{
                    padding: '8px 12px',
                    borderRadius: 8,
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    color: '#FFFFFF',
                    fontSize: 13,
                  }}
                >
                  <option value="default" style={{ background: '#0F1420' }}>
                    Default Windows Sound
                  </option>
                  <option value="silent" style={{ background: '#0F1420' }}>
                    Silent (No Sound)
                  </option>
                  <option value="custom" style={{ background: '#0F1420' }}>
                    Custom Time Tracker Chime
                  </option>
                </select>
              </div>
            </div>

            {/* Inactivity Step-away Threshold */}
            <div className="settings-field-row">
              <label htmlFor="input-idle-threshold">Idle Step-Away Threshold</label>
              <div className="input-with-unit">
                <input
                  id="input-idle-threshold"
                  type="number"
                  min="1"
                  max="30"
                  value={notifSettings.idle_alert_threshold_minutes}
                  onChange={(e) => handleUpdateNotifSetting('idle_alert_threshold_minutes', parseInt(e.target.value) || 3)}
                />
                <span className="unit-label">minutes</span>
              </div>
            </div>

            {/* Schedule Mismatch Grace Period */}
            <div className="settings-field-row">
              <label htmlFor="input-mismatch-grace">Distraction Grace Period</label>
              <div className="input-with-unit">
                <input
                  id="input-mismatch-grace"
                  type="number"
                  min="1"
                  max="15"
                  value={notifSettings.mismatch_grace_minutes}
                  onChange={(e) => handleUpdateNotifSetting('mismatch_grace_minutes', parseInt(e.target.value) || 2)}
                />
                <span className="unit-label">minutes</span>
              </div>
            </div>

            {/* Default Snooze Duration */}
            <div className="settings-field-row">
              <label htmlFor="input-cooldown-mins">Default Snooze Duration</label>
              <div className="input-with-unit">
                <select
                  id="input-cooldown-mins"
                  value={notifSettings.default_snooze_minutes ?? notifSettings.distraction_cooldown_minutes ?? 5}
                  onChange={(e) => {
                    const val = parseInt(e.target.value) || 5;
                    handleUpdateNotifSetting('default_snooze_minutes', val);
                    handleUpdateNotifSetting('distraction_cooldown_minutes', val);
                  }}
                  style={{
                    padding: '8px 12px',
                    borderRadius: 8,
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    color: '#FFFFFF',
                    fontSize: 13,
                  }}
                >
                  <option value={5} style={{ background: '#0F1420' }}>5 minutes</option>
                  <option value={10} style={{ background: '#0F1420' }}>10 minutes</option>
                  <option value={15} style={{ background: '#0F1420' }}>15 minutes</option>
                  <option value={30} style={{ background: '#0F1420' }}>30 minutes</option>
                </select>
              </div>
            </div>

            {/* Missed Recovery Threshold */}
            <div className="settings-field-row">
              <label htmlFor="input-recovery-threshold">Missed Activity Threshold</label>
              <div className="input-with-unit">
                <input
                  id="input-recovery-threshold"
                  type="number"
                  min="10"
                  max="120"
                  step="5"
                  value={notifSettings.missed_recovery_threshold_minutes}
                  onChange={(e) => handleUpdateNotifSetting('missed_recovery_threshold_minutes', parseInt(e.target.value) || 30)}
                />
                <span className="unit-label">minutes</span>
              </div>
            </div>

            {/* Overnight Sleep Gap Suppression */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Overnight Sleep Gap Suppression</span>
                <p className="settings-toggle-desc">
                  Do not automatically prompt for missed activity during your normal sleep schedule.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.overnight_suppression_enabled ?? true ? 'active' : ''}`}
                onClick={() =>
                  handleUpdateNotifSetting(
                    'overnight_suppression_enabled',
                    !(notifSettings.overnight_suppression_enabled ?? true)
                  )
                }
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {(notifSettings.overnight_suppression_enabled ?? true) && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, padding: '6px 0' }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: '#8994A8', marginBottom: 4 }}>
                    Sleep Window Start
                  </label>
                  <input
                    type="time"
                    value={notifSettings.overnight_sleep_start || '23:00'}
                    onChange={(e) => handleUpdateNotifSetting('overnight_sleep_start', e.target.value)}
                    style={{
                      width: '100%',
                      padding: '7px 10px',
                      borderRadius: 8,
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid rgba(255, 255, 255, 0.12)',
                      color: '#FFFFFF',
                      fontSize: 12,
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: '#8994A8', marginBottom: 4 }}>
                    Sleep Window End
                  </label>
                  <input
                    type="time"
                    value={notifSettings.overnight_sleep_end || '07:00'}
                    onChange={(e) => handleUpdateNotifSetting('overnight_sleep_end', e.target.value)}
                    style={{
                      width: '100%',
                      padding: '7px 10px',
                      borderRadius: 8,
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid rgba(255, 255, 255, 0.12)',
                      color: '#FFFFFF',
                      fontSize: 12,
                    }}
                  />
                </div>
              </div>
            )}

            {/* Quiet Hours */}
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Quiet Hours</span>
                <p className="settings-toggle-desc">
                  Suppress desktop notifications during designated rest or sleep hours.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${notifSettings.quiet_hours_enabled ? 'active' : ''}`}
                onClick={() => handleUpdateNotifSetting('quiet_hours_enabled', !notifSettings.quiet_hours_enabled)}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            {notifSettings.quiet_hours_enabled && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, padding: '6px 0' }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: '#8994A8', marginBottom: 4 }}>
                    Start Time
                  </label>
                  <input
                    type="time"
                    value={notifSettings.quiet_hours_start}
                    onChange={(e) => handleUpdateNotifSetting('quiet_hours_start', e.target.value)}
                    style={{
                      width: '100%',
                      padding: '7px 10px',
                      borderRadius: 8,
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid rgba(255, 255, 255, 0.12)',
                      color: '#FFFFFF',
                      fontSize: 12,
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: '#8994A8', marginBottom: 4 }}>
                    End Time
                  </label>
                  <input
                    type="time"
                    value={notifSettings.quiet_hours_end}
                    onChange={(e) => handleUpdateNotifSetting('quiet_hours_end', e.target.value)}
                    style={{
                      width: '100%',
                      padding: '7px 10px',
                      borderRadius: 8,
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid rgba(255, 255, 255, 0.12)',
                      color: '#FFFFFF',
                      fontSize: 12,
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Windows Notification Platform Diagnostics & Delivery Health */}
          <div
            style={{
              marginTop: 22,
              padding: '16px',
              borderRadius: 12,
              background: 'rgba(15, 23, 42, 0.65)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              display: 'flex',
              flexDirection: 'column',
              gap: 14,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 13, color: '#FFFFFF' }}>
                  <BellIcon size={15} color="var(--accent-teal, #16D5E2)" />
                  <span>Windows Toast &amp; Banner Diagnostics</span>
                </div>
                <span style={{ fontSize: 11.5, color: '#8994A8' }}>
                  Real-time inspection of Windows Shell integration, AUMID registry status, and Focus Assist state
                </span>
              </div>
              <button
                type="button"
                className="btn-secondary"
                onClick={loadDiagnostics}
                disabled={isDiagLoading}
                style={{ padding: '4px 10px', fontSize: 11.5, display: 'flex', alignItems: 'center', gap: 5 }}
                title="Refresh notification pipeline diagnostics"
              >
                <RefreshIcon size={12} />
                <span>{isDiagLoading ? 'Checking…' : 'Refresh'}</span>
              </button>
            </div>

            {/* Status Badges Grid */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: 8,
              }}
            >
              {/* Platform */}
              <div
                style={{
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#8994A8' }}>
                  Platform
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 500, color: '#FFFFFF' }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: diagnostics?.is_windows ? '#35D68A' : '#FFA800',
                    }}
                  />
                  <span>{diagnostics?.is_windows ? 'Windows 10/11' : diagnostics?.platform || 'Unknown'}</span>
                </div>
              </div>

              {/* AUMID Identity */}
              <div
                style={{
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#8994A8' }}>
                  App Identity (AUMID)
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 500, color: '#FFFFFF' }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: diagnostics?.aumid_registered ? '#35D68A' : '#FA5275',
                    }}
                  />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {diagnostics?.aumid_registered ? 'TimeTrackerAI.App' : 'Unregistered'}
                  </span>
                </div>
              </div>

              {/* ShowBanner Registry */}
              <div
                style={{
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#8994A8' }}>
                  Registry Banner
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 500, color: '#FFFFFF' }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: diagnostics?.show_banner_registry ? '#35D68A' : '#FFA800',
                    }}
                  />
                  <span>{diagnostics?.show_banner_registry ? 'ShowBanner = 1' : 'Not Configured'}</span>
                </div>
              </div>

              {/* Start Menu Shortcut */}
              <div
                style={{
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#8994A8' }}>
                  Start Menu Shortcut
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 500, color: '#FFFFFF' }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: diagnostics?.shortcut_installed ? '#35D68A' : '#FFA800',
                    }}
                  />
                  <span>{diagnostics?.shortcut_installed ? 'Installed (pythonw.exe)' : 'Missing'}</span>
                </div>
              </div>

              {/* Windows Notifier Setting */}
              <div
                style={{
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#8994A8' }}>
                  Windows Setting
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 500, color: '#FFFFFF' }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: diagnostics?.notifier_setting === 'Enabled' ? '#35D68A' : '#FA5275',
                    }}
                  />
                  <span>{diagnostics?.notifier_setting || 'Unknown'}</span>
                </div>
              </div>

              {/* User Notification State (Focus Assist) */}
              <div
                style={{
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#8994A8' }}>
                  Notification State
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 500, color: '#FFFFFF' }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background:
                        diagnostics?.user_notification_state === 'QUNS_ACCEPTS_NOTIFICATIONS'
                          ? '#35D68A'
                          : '#16D5E2',
                    }}
                  />
                  <span title={diagnostics?.user_notification_state}>
                    {diagnostics?.user_notification_state === 'QUNS_ACCEPTS_NOTIFICATIONS'
                      ? 'Accepting Banners'
                      : diagnostics?.user_notification_state === 'QUNS_QUIET_TIME'
                      ? 'Focus Assist / DND'
                      : diagnostics?.user_notification_state === 'QUNS_BUSY'
                      ? 'Busy / Fullscreen (Elevated)'
                      : diagnostics?.user_notification_state || 'Unknown'}
                  </span>
                </div>
              </div>
            </div>

            {/* Troubleshooting Guidance Box */}
            {diagnostics?.troubleshooting_hints && diagnostics.troubleshooting_hints.length > 0 && (
              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: 8,
                  background: diagnostics.troubleshooting_hints.some(
                    (h) => h.includes('blocked') || h.includes('disabled')
                  )
                    ? 'rgba(250, 82, 117, 0.08)'
                    : 'rgba(22, 213, 226, 0.06)',
                  border:
                    '1px solid ' +
                    (diagnostics.troubleshooting_hints.some((h) => h.includes('blocked') || h.includes('disabled'))
                      ? 'rgba(250, 82, 117, 0.25)'
                      : 'rgba(22, 213, 226, 0.2)'),
                  fontSize: 12,
                  color: '#CBD5E1',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, color: '#FFFFFF' }}>
                  <InfoIcon size={14} color="var(--accent-teal, #16D5E2)" />
                  <span>System Guidance &amp; Delivery Policies:</span>
                </div>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {diagnostics.troubleshooting_hints.map((hint, idx) => (
                    <li key={idx} style={{ marginTop: 2 }}>
                      {hint}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Last Attempt Feedback Banner */}
            {testResultFeedback && (
              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: 8,
                  background:
                    testResultFeedback.status === 'success'
                      ? 'rgba(53, 214, 138, 0.1)'
                      : testResultFeedback.status === 'error'
                      ? 'rgba(250, 82, 117, 0.1)'
                      : 'rgba(22, 213, 226, 0.1)',
                  border:
                    '1px solid ' +
                    (testResultFeedback.status === 'success'
                      ? 'rgba(53, 214, 138, 0.3)'
                      : testResultFeedback.status === 'error'
                      ? 'rgba(250, 82, 117, 0.3)'
                      : 'rgba(22, 213, 226, 0.3)'),
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 12.5,
                    fontWeight: 600,
                    color:
                      testResultFeedback.status === 'success'
                        ? '#35D68A'
                        : testResultFeedback.status === 'error'
                        ? '#FA5275'
                        : '#16D5E2',
                  }}
                >
                  {testResultFeedback.status === 'success' && <CheckIcon size={14} color="#35D68A" />}
                  {testResultFeedback.status === 'error' && <AlertTriangleIcon size={14} color="#FA5275" />}
                  {testResultFeedback.status === 'running' && <RefreshIcon size={14} color="#16D5E2" />}
                  <span>{testResultFeedback.message}</span>
                </div>
                {testResultFeedback.details && (
                  <span style={{ fontSize: 11.5, color: '#94A3B8', paddingLeft: 20 }}>
                    {testResultFeedback.details}
                  </span>
                )}
              </div>
            )}

            {/* Action Buttons */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
              <button
                type="button"
                className="btn-secondary"
                onClick={handleTestDesktopToast}
                disabled={testResultFeedback?.status === 'running'}
                style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}
              >
                <BellIcon size={14} />
                <span>Test Desktop Notification Banner</span>
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={handleTestTimeBlockToast}
                disabled={testResultFeedback?.status === 'running'}
                style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}
              >
                <ClockIcon size={14} />
                <span>Test Time Block Reminder</span>
              </button>
            </div>
          </div>
        </div>

        {/* Windows Startup & Background Tracker */}
        <div className="card settings-card">
          <div className="card-title-bar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ClockIcon size={18} color="var(--accent-teal, #16D5E2)" />
              <span className="card-title">Windows Startup & Tracking</span>
            </div>
          </div>
          <p className="settings-card-sub">
            Control automatic background activity capture and system autostart.
          </p>

          <div className="settings-fields-group">
            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Launch on Windows Startup</span>
                <p className="settings-toggle-desc">
                  Start Time Tracker AI automatically in the background when you log into Windows.
                </p>
              </div>
              <button
                type="button"
                className={`settings-switch ${isAutostartEnabled ? 'active' : ''}`}
                onClick={onToggleAutostart}
              >
                <span className="settings-switch-thumb" />
              </button>
            </div>

            <div className="settings-toggle-row">
              <div>
                <span className="settings-toggle-title">Background Activity Tracking</span>
                <p className="settings-toggle-desc">
                  Currently {isTracking ? '🟢 Tracking is ACTIVE' : '🔴 Tracking is PAUSED'}.
                </p>
              </div>
              <button
                type="button"
                className={`btn-secondary ${isTracking ? 'btn-warn' : ''}`}
                onClick={onToggleTracking}
              >
                {isTracking ? 'Pause Tracking' : 'Resume Tracking'}
              </button>
            </div>
          </div>

          <div className="settings-info-box">
            <span className="settings-info-label">Active SQLite Database:</span>
            <code className="settings-info-code">{dbPath || 'tracker.db'}</code>
          </div>
        </div>

        {/* Floating Desktop Widget Settings */}
        <div className="card settings-card">
          <div className="card-title-bar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <WidgetIcon size={18} color="var(--accent-purple, #8065FF)" />
              <span className="card-title">Floating Desktop Widget</span>
            </div>
          </div>
          <p className="settings-card-sub">
            The always-on-top desktop widget stays visible over all full-screen IDEs and browsers.
          </p>

          <div className="settings-actions-group">
            <button
              type="button"
              className="btn-primary"
              onClick={onLaunchWidget}
            >
              <WidgetIcon size={15} />
              <span>Launch Desktop Widget</span>
            </button>

            <button
              type="button"
              className="btn-secondary"
              onClick={handleResetWidgetPosition}
            >
              <span>Reset Widget Screen Position</span>
            </button>
          </div>

          {widgetResetStatus && (
            <p className="settings-status-note" style={{ marginTop: 12 }}>
              {widgetResetStatus}
            </p>
          )}

          <div className="settings-features-list">
            <div className="settings-feature-item">
              <span className="feature-bullet">•</span>
              <span><strong>Frameless & Always-on-Top:</strong> Sits over code editors without stealing focus.</span>
            </div>
            <div className="settings-feature-item">
              <span className="feature-bullet">•</span>
              <span><strong>Live Session Ticking:</strong> Updates duration and daily goal progress in real-time.</span>
            </div>
            <div className="settings-feature-item">
              <span className="feature-bullet">•</span>
              <span><strong>Pause & Resume:</strong> Toggle background tracking with a single click.</span>
            </div>
          </div>
        </div>

        {/* Categories & AI Rules */}
        <div className="card settings-card">
          <div className="card-title-bar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <SparklesIcon size={18} color="var(--status-focus, #35D68A)" />
              <span className="card-title">Classification & Rules</span>
            </div>
          </div>
          <p className="settings-card-sub">
            Configure how applications, window titles, and URLs are categorized into Focus, Work, Distraction, or Break.
          </p>

          <div style={{ padding: '12px 0' }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={onNavigateCategories}
              style={{ width: '100%', justifyContent: 'center' }}
            >
              <span>Open Categories & Rules Manager</span>
            </button>
          </div>

          <div className="settings-info-box" style={{ marginTop: 12 }}>
            <span className="settings-info-label">Matching Precedence:</span>
            <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
              Manual User Override → Exact URL Rule → Domain Match → Window Title Pattern → Process Executable → Fallback
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
