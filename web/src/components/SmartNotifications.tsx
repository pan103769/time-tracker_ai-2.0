import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ActiveTaskModel, TimeBlockModel } from '../types';
import { CloseIcon, SparklesIcon, PlayIcon, ClockIcon } from './Icons';

interface SmartNotificationsProps {
  activeTask: ActiveTaskModel | null;
  timeBlocks: TimeBlockModel[];
  isTracking: boolean;
  onReturnToTask?: (block: TimeBlockModel) => void;
}

export const SmartNotifications: React.FC<SmartNotificationsProps> = ({
  activeTask,
  timeBlocks,
  isTracking,
  onReturnToTask,
}) => {
  // Idle Alert state
  const [showIdleAlert, setShowIdleAlert] = useState<boolean>(false);
  const [idleMinutes, setIdleMinutes] = useState<number>(3);
  const lastIdleObsIdRef = useRef<number | null>(null);
  const idleSnoozedUntilRef = useRef<number>(0);

  // Focus Check-in state
  const [showFocusCheckin, setShowFocusCheckin] = useState<boolean>(false);
  const [activeMismatchBlock, setActiveMismatchBlock] = useState<TimeBlockModel | null>(null);
  const lastMismatchEpisodeRef = useRef<string | null>(null);
  const mismatchSnoozedUntilRef = useRef<number>(0);
  const mismatchGraceCounterRef = useRef<number>(0);

  // 1. Evaluate Idle Inactivity Condition (§6)
  useEffect(() => {
    if (!isTracking || !activeTask) {
      setShowIdleAlert(false);
      return;
    }

    const now = Date.now();
    if (now < idleSnoozedUntilRef.current) {
      return;
    }

    // Tracker marks idle as kind === 'idle'
    if (activeTask.kind === 'idle') {
      if (lastIdleObsIdRef.current !== activeTask.observation_id) {
        lastIdleObsIdRef.current = activeTask.observation_id;
        setIdleMinutes(3);
        setShowIdleAlert(true);
      }
    } else {
      // User resumed active work
      if (showIdleAlert) {
        setShowIdleAlert(false);
      }
      lastIdleObsIdRef.current = null;
    }
  }, [activeTask, isTracking, showIdleAlert]);

  // 2. Evaluate Focus Check-in / Schedule Mismatch Condition (§7)
  useEffect(() => {
    if (!isTracking || !activeTask || activeTask.kind === 'idle') {
      mismatchGraceCounterRef.current = 0;
      return;
    }

    const now = Date.now();
    if (now < mismatchSnoozedUntilRef.current) {
      return;
    }

    // Find currently active scheduled time block
    const nowTimeStr = new Date().toTimeString().slice(0, 5); // HH:MM
    const currentBlock = timeBlocks.find((b) => {
      const start = b.start_time.slice(0, 5);
      const end = b.end_time.slice(0, 5);
      return nowTimeStr >= start && nowTimeStr <= end;
    });

    if (!currentBlock) {
      setShowFocusCheckin(false);
      mismatchGraceCounterRef.current = 0;
      return;
    }

    // Check if active app represents distraction
    const appLower = (activeTask.app || '').toLowerCase();
    const titleLower = (activeTask.title || '').toLowerCase();
    const isDistraction =
      appLower.includes('youtube') ||
      appLower.includes('netflix') ||
      appLower.includes('reddit') ||
      appLower.includes('twitter') ||
      appLower.includes('instagram') ||
      appLower.includes('discord') ||
      appLower.includes('tiktok') ||
      titleLower.includes('youtube') ||
      titleLower.includes('social media');

    if (isDistraction) {
      mismatchGraceCounterRef.current += 1;
      // Grace period: trigger after consecutive checks (~90 seconds in real polling, or 2 checks)
      if (mismatchGraceCounterRef.current >= 2) {
        const episodeKey = `${currentBlock.id}_${activeTask.app}`;
        if (lastMismatchEpisodeRef.current !== episodeKey) {
          lastMismatchEpisodeRef.current = episodeKey;
          setActiveMismatchBlock(currentBlock);
          setShowFocusCheckin(true);
        }
      }
    } else {
      mismatchGraceCounterRef.current = 0;
    }
  }, [activeTask, timeBlocks, isTracking]);

  // Handle Idle Actions
  const handleImBack = () => {
    setShowIdleAlert(false);
  };

  const handleStayIdle = () => {
    setShowIdleAlert(false);
  };

  const handleSnoozeIdle = () => {
    idleSnoozedUntilRef.current = Date.now() + 5 * 60 * 1000; // 5 min snooze
    setShowIdleAlert(false);
    api.snoozeNotification('idle', 5).catch(() => {});
  };

  // Handle Focus Check-in Actions
  const handleReturnToPlannedTask = () => {
    if (activeMismatchBlock && onReturnToTask) {
      onReturnToTask(activeMismatchBlock);
    }
    setShowFocusCheckin(false);
  };

  const handleContinueAnyway = () => {
    setShowFocusCheckin(false);
  };

  const handleSnoozeFocusCheckin = () => {
    mismatchSnoozedUntilRef.current = Date.now() + 30 * 60 * 1000; // 30 min snooze matching toast
    setShowFocusCheckin(false);
    api.snoozeNotification('focus', 30).catch(() => {});
  };

  if (!showIdleAlert && !showFocusCheckin) {
    return null;
  }

  const currentTimeString = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

  return (
    <div className="smart-notifications-container">
      {/* 1. Idle Alert Toast */}
      {showIdleAlert && (
        <div className="smart-alert-card idle-toast animate-slide-up">
          <div className="smart-alert-header">
            <div className="smart-alert-icon-wrap amber">
              <SparklesIcon size={18} color="#FFB23E" />
            </div>
            <div className="smart-alert-title-area">
              <span className="smart-alert-title">Idle Alert</span>
              <p className="smart-alert-desc">
                Looks like you've stepped away. We detected {idleMinutes} minutes of inactivity. What would you like to do?
              </p>
            </div>
            <button
              type="button"
              className="smart-alert-close-btn"
              onClick={() => setShowIdleAlert(false)}
            >
              <CloseIcon size={14} />
            </button>
          </div>

          <div className="smart-alert-actions">
            <button type="button" className="btn-alert-primary" onClick={handleImBack}>
              I'm back
            </button>
            <button type="button" className="btn-alert-ghost" onClick={handleStayIdle}>
              Stay idle
            </button>
            <button type="button" className="btn-alert-ghost" onClick={handleSnoozeIdle}>
              Remind me later
            </button>
          </div>
        </div>
      )}

      {/* 2. Focus Check-in Toast (Matching Windows 11 Toast Reference Image) */}
      {showFocusCheckin && activeMismatchBlock && (
        <div className="smart-alert-card focus-checkin-toast native-toast-card animate-slide-up">
          <div className="native-toast-header">
            <div className="native-toast-brand">
              <div className="native-toast-logo-icon">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="#8065FF" stroke="#00f0ff" strokeWidth="1.5" />
                </svg>
              </div>
              <span className="native-toast-app-name">Time Tracker AI</span>
            </div>
            <button
              type="button"
              className="smart-alert-close-btn"
              onClick={() => setShowFocusCheckin(false)}
              aria-label="Close"
            >
              <CloseIcon size={14} />
            </button>
          </div>

          <div className="native-toast-body">
            <h4 className="native-toast-title">Focus Check-in</h4>
            <p className="native-toast-message">
              Your schedule says {activeMismatchBlock.title}, but your current activity looks unrelated. Want to return to your planned task?
            </p>
            <div className="native-toast-timestamp">{currentTimeString}</div>
          </div>

          <div className="native-toast-actions-row">
            <button
              type="button"
              className="native-toast-btn"
              onClick={handleReturnToPlannedTask}
            >
              <PlayIcon size={13} style={{ color: '#00f0ff', fill: '#00f0ff' }} />
              <span>Return to Task</span>
            </button>
            <button
              type="button"
              className="native-toast-btn"
              onClick={handleContinueAnyway}
            >
              <CloseIcon size={13} style={{ color: '#edf0f7' }} />
              <span>Continue Anyway</span>
            </button>
            <button
              type="button"
              className="native-toast-btn"
              onClick={handleSnoozeFocusCheckin}
            >
              <ClockIcon size={13} style={{ color: '#edf0f7' }} />
              <span>Snooze 30 min</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

