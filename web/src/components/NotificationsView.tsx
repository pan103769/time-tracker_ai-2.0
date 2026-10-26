import React, { useEffect, useState } from 'react';
import { api } from '../api';
import type {
  ActiveTaskModel,
  AppSettingsModel,
  CategoryModel,
  NotificationModel,
  ProductivityModel,
  RecoveryGapModel,
  TimeBlockModel,
} from '../types';
import {
  BellIcon,
  CalendarIcon,
  CheckIcon,
  ClockIcon,
  CloseIcon,
  CoffeeIcon,
  SettingsIcon,
  SparklesIcon,
  TargetIcon,
} from './Icons';
import { ManualActivityModal } from './ManualActivityModal';

interface NotificationsViewProps {
  activeTask?: ActiveTaskModel | null;
  timeBlocks?: TimeBlockModel[];
  categories?: CategoryModel[];
  isTracking?: boolean;
  productivity?: ProductivityModel | null;
  onNavigateOverview?: () => void;
  onNavigateGoals?: () => void;
  onNotificationsChanged?: () => void;
}

export const NotificationsView: React.FC<NotificationsViewProps> = ({
  categories = [],
  onNavigateOverview,
  onNavigateGoals,
  onNotificationsChanged,
}) => {
  const [notifications, setNotifications] = useState<NotificationModel[]>([]);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [filterType, setFilterType] = useState<string>('all');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [settings, setSettings] = useState<AppSettingsModel | null>(null);
  const [toastStatus, setToastStatus] = useState<string | null>(null);

  // Manual activity modal state
  const [isManualModalOpen, setIsManualModalOpen] = useState<boolean>(false);
  const [activeRecoveryGap, setActiveRecoveryGap] = useState<RecoveryGapModel | null>(null);

  const loadNotifications = async () => {
    try {
      const res = await api.getNotifications(60, filterType);
      setNotifications(res.notifications);
      setUnreadCount(res.unread_count);
      if (onNotificationsChanged) {
        onNotificationsChanged();
      }
    } catch {
      // Ignore network errors in polling
    } finally {
      setIsLoading(false);
    }
  };

  const loadSettings = async () => {
    try {
      const s = await api.getSettings();
      setSettings(s);
    } catch {
      // Ignore
    }
  };

  useEffect(() => {
    loadNotifications();
    loadSettings();
    const interval = setInterval(loadNotifications, 4000);
    return () => clearInterval(interval);
  }, [filterType]);

  const handleMarkAllRead = async () => {
    try {
      await api.markAllNotificationsRead();
      loadNotifications();
    } catch {
      // Ignore
    }
  };

  const handleMarkRead = async (id: number) => {
    try {
      await api.markNotificationRead(id);
      loadNotifications();
    } catch {
      // Ignore
    }
  };

  const handleDismiss = async (id: number) => {
    try {
      await api.dismissNotification(id);
      loadNotifications();
    } catch {
      // Ignore
    }
  };

  const handleSendTestToast = async () => {
    setToastStatus('Sending…');
    try {
      const res = await api.testDesktopToast();
      if (res.status === 'queued') {
        setToastStatus('Windows desktop toast queued!');
      } else {
        setToastStatus('Failed to send toast.');
      }
      loadNotifications();
      setTimeout(() => setToastStatus(null), 3500);
    } catch {
      setToastStatus('Error sending toast.');
      setTimeout(() => setToastStatus(null), 3500);
    }
  };

  const handleSendTimeBlockTestToast = async () => {
    setToastStatus('Sending Time Block toast…');
    try {
      const res = await api.testTimeBlockToast();
      if (res.status === 'queued') {
        setToastStatus('Time-block reminder toast queued!');
      } else {
        setToastStatus('Failed to send toast.');
      }
      loadNotifications();
      setTimeout(() => setToastStatus(null), 3500);
    } catch {
      setToastStatus('Error sending toast.');
      setTimeout(() => setToastStatus(null), 3500);
    }
  };

  const handleUpdateSetting = async (key: keyof AppSettingsModel, val: any) => {
    try {
      const updated = await api.updateSettings({ [key]: val });
      setSettings(updated);
    } catch {
      // Ignore
    }
  };

  const handleOpenRecoveryModal = (notif: NotificationModel) => {
    if (notif.details && notif.details.gap_id) {
      setActiveRecoveryGap({
        id: notif.details.gap_id,
        gap_start: notif.details.gap_start || notif.created_at,
        gap_end: notif.details.gap_end || new Date().toISOString(),
        duration_seconds: (notif.details.duration_minutes || 30) * 60,
        status: 'pending',
        created_at: notif.created_at,
      });
      setIsManualModalOpen(true);
    } else {
      setActiveRecoveryGap(null);
      setIsManualModalOpen(true);
    }
  };

  const formatTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return isoString.slice(11, 16);

      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const targetDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());
      const diffTime = today.getTime() - targetDate.getTime();
      const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

      const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      if (diffDays === 0) {
        return `Today at ${timeStr}`;
      } else if (diffDays === 1) {
        return `Yesterday at ${timeStr}`;
      } else {
        const dateStr = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
        return `${dateStr} at ${timeStr}`;
      }
    } catch {
      return isoString.slice(11, 16);
    }
  };

  return (
    <div className="view-container notifications-view">
      {/* Header */}
      <div
        className="view-header-row"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 20,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 10,
                background: 'rgba(250, 82, 117, 0.2)',
                border: '1px solid rgba(250, 82, 117, 0.4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <BellIcon size={18} color="#FA5275" />
            </div>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
              Notifications &amp; Smart Alerts
            </h2>
            {unreadCount > 0 && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  background: '#FA5275',
                  color: '#FFFFFF',
                  padding: '2px 8px',
                  borderRadius: 12,
                }}
              >
                {unreadCount} Unread
              </span>
            )}
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-secondary, #8994A8)', margin: '4px 0 0 0' }}>
            Real-time focus interventions, idle step-away alerts, and missed-activity recovery prompts.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleMarkAllRead}
            disabled={unreadCount === 0}
            style={{ fontSize: 12, padding: '7px 14px', gap: 6, display: 'flex', alignItems: 'center' }}
          >
            <CheckIcon size={14} />
            <span>Mark All as Read</span>
          </button>
        </div>
      </div>

      {/* Main Grid: Alerts Feed (Left) & Alert Settings (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 20 }}>
        {/* Left Column: Filter Pills & List of Alerts */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Filter Pills */}
          <div className="timeline-pill-group" style={{ alignSelf: 'flex-start' }}>
            <button
              type="button"
              className={`timeline-pill-btn ${filterType === 'all' ? 'active' : ''}`}
              onClick={() => setFilterType('all')}
            >
              All
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${filterType === 'unread' ? 'active' : ''}`}
              onClick={() => setFilterType('unread')}
            >
              Unread ({unreadCount})
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${filterType === 'focus' ? 'active' : ''}`}
              onClick={() => setFilterType('focus')}
            >
              Focus Check-ins
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${filterType === 'time_block' ? 'active' : ''}`}
              onClick={() => setFilterType('time_block')}
            >
              Time Blocks
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${filterType === 'idle' ? 'active' : ''}`}
              onClick={() => setFilterType('idle')}
            >
              Idle Alerts
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${filterType === 'recovery' ? 'active' : ''}`}
              onClick={() => setFilterType('recovery')}
            >
              Missed Activity
            </button>
          </div>

          {/* Alerts Feed */}
          {isLoading ? (
            <div className="card-panel" style={{ textAlign: 'center', padding: '40px 20px', color: '#5A6679' }}>
              <p style={{ margin: 0, fontSize: 13 }}>Loading notifications…</p>
            </div>
          ) : notifications.length === 0 ? (
            <div className="card-panel" style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted, #5A6679)' }}>
              <BellIcon size={36} color="var(--border-subtle, #27354A)" style={{ marginBottom: 10 }} />
              <p style={{ margin: 0, fontSize: 14 }}>No notifications in this view.</p>
            </div>
          ) : (
            notifications.map((alert) => (
              <div
                key={alert.id}
                className="card-panel"
                style={{
                  border: alert.unread
                    ? '1px solid rgba(128, 101, 255, 0.45)'
                    : '1px solid rgba(39, 53, 74, 0.65)',
                  background: alert.unread
                    ? 'linear-gradient(135deg, rgba(20, 27, 45, 0.95), rgba(15, 20, 32, 0.95))'
                    : '#111927',
                  position: 'relative',
                  padding: '18px 20px',
                  borderRadius: 14,
                  boxShadow: alert.unread ? '0 4px 20px rgba(128, 101, 255, 0.08)' : 'none',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 8,
                        background:
                          alert.type === 'focus'
                            ? 'rgba(128, 101, 255, 0.2)'
                            : alert.type === 'time_block'
                            ? 'rgba(22, 213, 226, 0.2)'
                            : alert.type === 'idle'
                            ? 'rgba(255, 178, 62, 0.2)'
                            : alert.type === 'recovery'
                            ? 'rgba(0, 240, 255, 0.2)'
                            : alert.type === 'milestone'
                            ? 'rgba(53, 214, 138, 0.2)'
                            : 'rgba(250, 82, 117, 0.2)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      {alert.type === 'focus' && <TargetIcon size={16} color="#8065FF" />}
                      {alert.type === 'time_block' && <CalendarIcon size={16} color="#16D5E2" />}
                      {alert.type === 'idle' && <CoffeeIcon size={16} color="#FFB23E" />}
                      {alert.type === 'recovery' && <ClockIcon size={16} color="#00F0FF" />}
                      {alert.type === 'milestone' && <SparklesIcon size={16} color="#35D68A" />}
                      {alert.type !== 'focus' && alert.type !== 'time_block' && alert.type !== 'idle' && alert.type !== 'recovery' && alert.type !== 'milestone' && (
                        <BellIcon size={16} color="#FA5275" />
                      )}
                    </div>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <h4 style={{ fontSize: 15, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
                          {alert.title}
                        </h4>
                        {alert.unread && (
                          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#8065FF' }} />
                        )}
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-muted, #5A6679)' }}>
                        {formatTime(alert.created_at)}
                      </span>
                    </div>
                  </div>

                  <button
                    type="button"
                    className="btn-icon"
                    onClick={() => handleDismiss(alert.id)}
                    title="Dismiss alert"
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--text-muted, #5A6679)',
                      cursor: 'pointer',
                    }}
                  >
                    <CloseIcon size={14} />
                  </button>
                </div>

                <p style={{ fontSize: 13.5, color: '#D1D7E4', lineHeight: 1.5, margin: '8px 0 14px 0' }}>
                  {alert.body}
                </p>

                {alert.details && alert.details.block_title && (
                  <div
                    style={{
                      background: 'rgba(128, 101, 255, 0.12)',
                      border: '1px solid rgba(128, 101, 255, 0.3)',
                      borderRadius: 6,
                      padding: '8px 12px',
                      fontSize: 12,
                      color: '#A78BFA',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      marginBottom: 14,
                    }}
                  >
                    <span style={{ fontFamily: 'var(--font-mono)' }}>&lt;/&gt;</span>
                    <strong>Planned Task:</strong> {alert.details.block_title} ({alert.details.start_time}–{alert.details.end_time})
                  </div>
                )}

                {/* Action Buttons */}
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  {alert.type === 'focus' && (
                    <>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => {
                          handleMarkRead(alert.id);
                          if (onNavigateOverview) onNavigateOverview();
                        }}
                        style={{ fontSize: 12, padding: '6px 14px' }}
                      >
                        Return to planned task
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => handleMarkRead(alert.id)}
                        style={{ fontSize: 12, padding: '6px 14px' }}
                      >
                        Continue anyway
                      </button>
                    </>
                  )}

                  {alert.type === 'idle' && (
                    <>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => handleMarkRead(alert.id)}
                        style={{ fontSize: 12, padding: '6px 14px' }}
                      >
                        I&apos;m back
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => handleMarkRead(alert.id)}
                        style={{ fontSize: 12, padding: '6px 14px' }}
                      >
                        Stay idle
                      </button>
                    </>
                  )}

                  {alert.type === 'recovery' && (
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => handleOpenRecoveryModal(alert)}
                      style={{
                        fontSize: 12,
                        padding: '6px 14px',
                        background: 'linear-gradient(135deg, #00F0FF, #8065FF)',
                        color: '#0B0F19',
                        fontWeight: 600,
                      }}
                    >
                      Add Missed Activity
                    </button>
                  )}

                  {alert.type === 'time_block' && (
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={async () => {
                          if (alert.details?.block_id) {
                            try {
                              await api.startFocusForTimeBlock(alert.details.block_id);
                            } catch {}
                          }
                          handleMarkRead(alert.id);
                          if (onNavigateOverview) onNavigateOverview();
                        }}
                        style={{
                          fontSize: 12,
                          padding: '6px 14px',
                          background: 'linear-gradient(135deg, #16D5E2, #5D6BFF)',
                          color: '#FFFFFF',
                          fontWeight: 600,
                        }}
                      >
                        Start Focus
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={async () => {
                          if (alert.details?.block_id) {
                            try {
                              await api.snoozeTimeBlock(alert.details.block_id, 5);
                            } catch {}
                          }
                          handleMarkRead(alert.id);
                        }}
                        style={{ fontSize: 12, padding: '6px 12px' }}
                      >
                        Snooze 5m
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={async () => {
                          if (alert.details?.block_id) {
                            try {
                              await api.snoozeTimeBlock(alert.details.block_id, 10);
                            } catch {}
                          }
                          handleMarkRead(alert.id);
                        }}
                        style={{ fontSize: 12, padding: '6px 12px' }}
                      >
                        Snooze 10m
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={async () => {
                          if (alert.details?.block_id) {
                            try {
                              await api.skipTimeBlock(alert.details.block_id);
                            } catch {}
                          }
                          handleDismiss(alert.id);
                        }}
                        style={{ fontSize: 12, padding: '6px 12px' }}
                      >
                        Skip this block
                      </button>
                      {onNavigateGoals && (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => onNavigateGoals()}
                          style={{ fontSize: 12, padding: '6px 12px' }}
                        >
                          Open Planner
                        </button>
                      )}
                    </div>
                  )}

                  {alert.type === 'milestone' && onNavigateGoals && (
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => onNavigateGoals()}
                      style={{ fontSize: 12, padding: '6px 14px' }}
                    >
                      View Goals
                    </button>
                  )}

                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => handleDismiss(alert.id)}
                    style={{ fontSize: 12, padding: '6px 14px', marginLeft: 'auto' }}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Right Column: Alert Thresholds & Preferences */}
        <div className="card-panel" style={{ height: 'fit-content' }}>
          <h3 className="panel-title" style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
            <SettingsIcon size={16} color="#8065FF" />
            <span>Alert Preferences</span>
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {/* Windows Desktop Notifications Toggle */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#EDF0F7', display: 'block' }}>
                    Windows Desktop Toasts
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary, #8994A8)' }}>
                    Display native notifications even when browser is closed
                  </span>
                </div>
                <input
                  type="checkbox"
                  checked={settings?.windows_toasts_enabled ?? true}
                  onChange={(e) => handleUpdateSetting('windows_toasts_enabled', e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#8065FF' }}
                />
              </div>

              {/* Test Buttons */}
              <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleSendTestToast}
                  style={{ width: '100%', fontSize: 12, padding: '7px 12px' }}
                >
                  Send Focus Check-in Toast
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleSendTimeBlockTestToast}
                  style={{ width: '100%', fontSize: 12, padding: '7px 12px' }}
                >
                  Send Time-Block Toast
                </button>
                {toastStatus && (
                  <span style={{ display: 'block', fontSize: 11, color: '#00F0FF', marginTop: 4, textAlign: 'center' }}>
                    {toastStatus}
                  </span>
                )}
              </div>
            </div>

            {/* Notification Sound */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#EDF0F7', marginBottom: 6 }}>
                Notification Sound
              </label>
              <select
                value={settings?.notification_sound || 'default'}
                onChange={(e) => handleUpdateSetting('notification_sound', e.target.value)}
                style={{
                  width: '100%',
                  padding: '7px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  color: '#FFFFFF',
                  fontSize: 12,
                }}
              >
                <option value="default" style={{ background: '#0F1420' }}>Default Windows Sound</option>
                <option value="silent" style={{ background: '#0F1420' }}>Silent (No Sound)</option>
                <option value="custom" style={{ background: '#0F1420' }}>Custom Time Tracker Chime</option>
              </select>
            </div>

            {/* Inactivity Threshold */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#EDF0F7', marginBottom: 6 }}>
                Inactivity Detection Threshold
              </label>
              <p style={{ fontSize: 12, color: 'var(--text-secondary, #8994A8)', margin: '0 0 10px 0' }}>
                Minutes of no input before triggering Idle step-away prompt.
              </p>
              <div style={{ display: 'flex', gap: 8 }}>
                {[1, 2, 3, 5, 10].map((mins) => (
                  <button
                    key={mins}
                    type="button"
                    className={`timeline-pill-btn ${(settings?.idle_alert_threshold_minutes ?? 3) === mins ? 'active' : ''}`}
                    onClick={() => handleUpdateSetting('idle_alert_threshold_minutes', mins)}
                  >
                    {mins}m
                  </button>
                ))}
              </div>
            </div>

            {/* Schedule Mismatch Grace Period */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#EDF0F7', marginBottom: 6 }}>
                Distraction Grace Period
              </label>
              <p style={{ fontSize: 12, color: 'var(--text-secondary, #8994A8)', margin: '0 0 10px 0' }}>
                Minutes of sustained distraction during planned blocks before alerting.
              </p>
              <div style={{ display: 'flex', gap: 8 }}>
                {[1, 2, 3, 5].map((mins) => (
                  <button
                    key={mins}
                    type="button"
                    className={`timeline-pill-btn ${(settings?.mismatch_grace_minutes ?? 2) === mins ? 'active' : ''}`}
                    onClick={() => handleUpdateSetting('mismatch_grace_minutes', mins)}
                  >
                    {mins}m
                  </button>
                ))}
              </div>
            </div>

            {/* Time-Block Start Reminders Toggle */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#EDF0F7', display: 'block' }}>
                    Time-Block Start Reminders
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary, #8994A8)' }}>
                    Send native toasts when a scheduled block reaches start time
                  </span>
                </div>
                <input
                  type="checkbox"
                  checked={settings?.time_block_reminders_enabled ?? true}
                  onChange={(e) => handleUpdateSetting('time_block_reminders_enabled', e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#8065FF' }}
                />
              </div>
            </div>

            {/* Auto-Start Focus Session Toggle */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#EDF0F7', display: 'block' }}>
                    Auto-Start Focus Session
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary, #8994A8)' }}>
                    Automatically begin tracking and linked focus session at block start
                  </span>
                </div>
                <input
                  type="checkbox"
                  checked={settings?.time_block_autostart_focus ?? false}
                  onChange={(e) => handleUpdateSetting('time_block_autostart_focus', e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#8065FF' }}
                />
              </div>
            </div>

            {/* Missed Activity Recovery Toggle */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#EDF0F7', display: 'block' }}>
                    Missed-Activity Recovery
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary, #8994A8)' }}>
                    Prompt to record activity after long pauses (&gt; 30 min)
                  </span>
                </div>
                <input
                  type="checkbox"
                  checked={settings?.missed_recovery_enabled ?? true}
                  onChange={(e) => handleUpdateSetting('missed_recovery_enabled', e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#8065FF' }}
                />
              </div>
            </div>

            {/* Overnight Sleep Suppression Toggle */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#EDF0F7', display: 'block' }}>
                    Overnight Sleep Suppression
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary, #8994A8)' }}>
                    Suppress recovery prompts during normal sleep periods
                  </span>
                </div>
                <input
                  type="checkbox"
                  checked={settings?.overnight_suppression_enabled ?? true}
                  onChange={(e) => handleUpdateSetting('overnight_suppression_enabled', e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#8065FF' }}
                />
              </div>

              {(settings?.overnight_suppression_enabled ?? true) && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 11, color: '#8994A8', marginBottom: 4 }}>
                      Sleep Start
                    </label>
                    <input
                      type="time"
                      value={settings?.overnight_sleep_start || '23:00'}
                      onChange={(e) => handleUpdateSetting('overnight_sleep_start', e.target.value)}
                      style={{
                        width: '100%',
                        padding: '6px 8px',
                        borderRadius: 6,
                        background: 'rgba(255, 255, 255, 0.05)',
                        border: '1px solid rgba(255, 255, 255, 0.12)',
                        color: '#FFFFFF',
                        fontSize: 12,
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 11, color: '#8994A8', marginBottom: 4 }}>
                      Sleep End
                    </label>
                    <input
                      type="time"
                      value={settings?.overnight_sleep_end || '07:00'}
                      onChange={(e) => handleUpdateSetting('overnight_sleep_end', e.target.value)}
                      style={{
                        width: '100%',
                        padding: '6px 8px',
                        borderRadius: 6,
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

            {/* Manual Activity Button */}
            <div style={{ borderTop: '1px solid rgba(39, 53, 74, 0.65)', paddingTop: 16 }}>
              <button
                type="button"
                className="btn-primary full-width"
                onClick={() => {
                  setActiveRecoveryGap(null);
                  setIsManualModalOpen(true);
                }}
                style={{ width: '100%', fontSize: 12, padding: '8px 12px' }}
              >
                + Record Manual Activity
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Manual Activity Entry Modal */}
      <ManualActivityModal
        isOpen={isManualModalOpen}
        gap={activeRecoveryGap}
        categories={categories}
        onClose={() => setIsManualModalOpen(false)}
        onSaved={loadNotifications}
        onRecordManual={async (payload) => {
          await api.recordManualActivity(payload);
          loadNotifications();
        }}
      />
    </div>
  );
};
