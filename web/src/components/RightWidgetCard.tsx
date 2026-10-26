import React, { useState, useEffect } from 'react';
import type { ActiveTaskModel, CategoryModel, ProductivityModel, TimeBlockModel } from '../types';
import { ActivityEditModal } from './ActivityEditModal';
import {
  EditIcon,
  SettingsIcon,
  WidgetIcon,
} from './Icons';

interface RightWidgetCardProps {
  isTracking: boolean;
  onToggleTracking: () => void;
  activeTask: ActiveTaskModel | null;
  productivity: ProductivityModel | null;
  timeBlocks: TimeBlockModel[];
  onLaunchNativeWidget: () => void;
  categories?: CategoryModel[];
  onTaskAssigned?: () => void;
}

export const RightWidgetCard: React.FC<RightWidgetCardProps> = ({
  isTracking,
  onToggleTracking,
  activeTask,
  productivity,
  timeBlocks,
  onLaunchNativeWidget,
  categories = [],
  onTaskAssigned,
}) => {
  const [elapsedSec, setElapsedSec] = useState<number>(7638); // Representative 02:07:18
  const [isCompact, setIsCompact] = useState<boolean>(false);
  const [isEditingTask, setIsEditingTask] = useState<boolean>(false);

  // Live timer calculation from active task start time
  useEffect(() => {
    if (!isTracking) {
      return;
    }

    if (!activeTask?.start_time) {
      const interval = setInterval(() => {
        setElapsedSec((prev) => prev + 1);
      }, 1000);
      return () => clearInterval(interval);
    }

    const calcElapsed = () => {
      try {
        const start = new Date(activeTask.start_time).getTime();
        const now = Date.now();
        const diff = Math.max(0, Math.floor((now - start) / 1000));
        setElapsedSec(diff);
      } catch {
        setElapsedSec(7638);
      }
    };

    calcElapsed();
    const interval = setInterval(calcElapsed, 1000);
    return () => clearInterval(interval);
  }, [isTracking, activeTask]);

  // Format large timer display HH:MM:SS
  const formatTimer = (sec: number) => {
    const s = Math.max(0, sec);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const ss = s % 60;
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(h)}:${pad(m)}:${pad(ss)}`;
  };

  // Find active scheduled block or fallback to task
  const currentBlock = timeBlocks.find((b) => {
    const nowHHMM = new Date().toTimeString().slice(0, 5);
    return nowHHMM >= b.start_time.slice(0, 5) && nowHHMM <= b.end_time.slice(0, 5);
  });

  const activeTaskTitle = activeTask?.user_task
    ? activeTask.user_task
    : activeTask?.app
      ? (activeTask.title && activeTask.title !== activeTask.app
          ? `${activeTask.app.replace('.exe', '')} — ${activeTask.title.slice(0, 24)}`
          : activeTask.app.replace('.exe', ''))
      : 'Coding — VS Code';

  const activeBlockLabel = currentBlock ? currentBlock.title : 'Deep Work';
  const todayWorkLabel = productivity?.total_work_label || '0s';
  const workGoal = productivity?.goals?.find((g) => g.metric === 'work_time') || productivity?.goals?.[0];
  const goalPct = Math.round(
    workGoal
      ? workGoal.progress_pct
      : productivity && productivity.total_work_seconds > 0
        ? Math.min(100, (productivity.total_work_seconds / (8 * 3600)) * 100)
        : 0
  );

  // Exactly 14 Segmented Progress Ticks matching Reference
  const totalSegments = 14;
  const activeSegments = Math.min(
    totalSegments,
    Math.max(goalPct > 0 ? 1 : 0, Math.round((goalPct / 100) * totalSegments))
  );

  // Cyan to purple glowing segment gradient colors
  const segmentGradients = [
    '#16D5E2', // 0: Cyan
    '#16D5E2', // 1: Cyan
    '#19D3E6', // 2: Cyan
    '#1FD1EA', // 3: Cyan
    '#38BDF8', // 4: Sky blue
    '#4F9CF8', // 5: Blue
    '#6385F8', // 6: Royal blue
    '#818CF8', // 7: Indigo
    '#A78BFA', // 8: Lavender
    '#B575EC', // 9: Purple
    '#C084FC', // 10: Violet
    '#8065FF', // 11: Purple
    '#8065FF', // 12: Purple
    '#8065FF', // 13: Purple
  ];

  // COMPACT SINGLE-STRIP MODE (520x68 matching widget.py)
  if (isCompact) {
    return (
      <>
        <div className="right-widget-card-rize compact-strip-mode">
          <div className="widget-compact-strip-inner">
            {/* Drag Handle Dots */}
            <div className="widget-drag-dots-6 compact" title="Drag handle">
              <div className="drag-dot-col">
                <span className="drag-dot" />
                <span className="drag-dot" />
                <span className="drag-dot" />
              </div>
              <div className="drag-dot-col">
                <span className="drag-dot" />
                <span className="drag-dot" />
                <span className="drag-dot" />
              </div>
            </div>

            {/* Compact Timer */}
            <div className="widget-compact-timer-val">
              {formatTimer(elapsedSec)}
            </div>

            {/* Compact Task Name & Dot */}
            <div className="widget-compact-task-info">
              <span className={`status-indicator-dot ${isTracking ? 'active' : 'paused'}`} />
              <span className="compact-task-title" title={activeTaskTitle}>
                {activeTaskTitle}
              </span>
              <button
                type="button"
                className="widget-task-edit-btn compact"
                onClick={() => setIsEditingTask(true)}
                title="Edit activity name or category"
              >
                <EditIcon size={11} color="#8065FF" />
              </button>
            </div>

            {/* Actions */}
            <div className="widget-compact-actions">
              <button
                type="button"
                className="widget-circle-pause-btn compact"
                onClick={onToggleTracking}
                title={isTracking ? 'Pause tracking' : 'Resume tracking'}
              >
                {isTracking ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="4" width="4" height="16" rx="1.5" />
                    <rect x="14" y="4" width="4" height="16" rx="1.5" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style={{ marginLeft: 2 }}>
                    <polygon points="6,4 20,12 6,20" />
                  </svg>
                )}
              </button>

              <button
                type="button"
                className="widget-icon-btn"
                onClick={() => setIsCompact(false)}
                title="Expand to full widget"
              >
                <span style={{ fontSize: 13, color: '#A78BFA' }}>⤢</span>
              </button>

              <button
                type="button"
                className="widget-icon-btn"
                onClick={onLaunchNativeWidget}
                title="Float desktop focus widget"
              >
                <WidgetIcon size={13} color="#8065FF" />
              </button>
            </div>
          </div>
        </div>

        {isEditingTask && (
          <ActivityEditModal
            isOpen={isEditingTask}
            onClose={() => setIsEditingTask(false)}
            activeTask={activeTask}
            categories={categories}
            onTaskSaved={() => {
              setIsEditingTask(false);
              if (onTaskAssigned) onTaskAssigned();
            }}
          />
        )}
      </>
    );
  }

  // FULL EXPANDED MODE (520x190 matching Image 4 & Image 6)
  return (
    <div className="right-widget-card-rize">
      {/* 1. Top Header Row */}
      <div className="widget-card-top-row">
        <div className="widget-status-badge">
          <span className={`widget-status-text ${isTracking ? 'cyan' : 'paused'}`}>
            {isTracking ? 'FOCUS SESSION' : 'TRACKING PAUSED'}
          </span>
          <span className={`status-indicator-dot ${isTracking ? 'active' : 'paused'}`} />
          <span className="widget-task-name" title={activeTaskTitle}>
            {activeTaskTitle}
          </span>
          <button
            type="button"
            className="widget-task-edit-btn"
            onClick={() => setIsEditingTask(true)}
            title="Edit activity name or category"
          >
            <EditIcon size={12} color="#8065FF" />
          </button>
        </div>

        <div className="widget-top-actions">
          {/* 1. Dashboard / Pop out as floating desktop window */}
          <button
            type="button"
            className="widget-icon-btn"
            onClick={onLaunchNativeWidget}
            title="Pop out as floating desktop window"
          >
            <WidgetIcon size={14} color="#8065FF" />
          </button>

          {/* 2. Compact / Minimize Mode */}
          <button
            type="button"
            className="widget-icon-btn"
            onClick={() => setIsCompact(!isCompact)}
            title="Compact strip mode"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#8994A8" strokeWidth="2.5" strokeLinecap="round">
              <line x1="4" y1="12" x2="20" y2="12" />
            </svg>
          </button>

          {/* 3. Widget settings gear */}
          <button
            type="button"
            className="widget-icon-btn"
            title="Widget settings"
            onClick={() => setIsCompact(!isCompact)}
          >
            <SettingsIcon size={14} color="#8994A8" />
          </button>

          {/* 4. Three-dot context menu */}
          <button
            type="button"
            className="widget-icon-btn"
            title="Activity options"
            onClick={() => setIsEditingTask(true)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="#8994A8">
              <circle cx="12" cy="5" r="1.6" />
              <circle cx="12" cy="12" r="1.6" />
              <circle cx="12" cy="19" r="1.6" />
            </svg>
          </button>
        </div>
      </div>

      {/* 2. Main Digital Timer & Royal Purple Circular Action Row */}
      <div className="widget-timer-main-row">
        <div className="widget-timer-left">
          {/* 6-dot drag handle */}
          <div className="widget-drag-dots-6" title="Drag handle">
            <div className="drag-dot-col">
              <span className="drag-dot" />
              <span className="drag-dot" />
              <span className="drag-dot" />
            </div>
            <div className="drag-dot-col">
              <span className="drag-dot" />
              <span className="drag-dot" />
              <span className="drag-dot" />
            </div>
          </div>

          <div className="widget-timer-display">
            {formatTimer(elapsedSec)}
          </div>
        </div>

        <div className="widget-action-btns">
          <div className="widget-circle-pause-halo">
            <button
              type="button"
              className="widget-circle-pause-btn"
              onClick={onToggleTracking}
              title={isTracking ? 'Pause tracking' : 'Resume tracking'}
            >
              {isTracking ? (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="4" width="4" height="16" rx="1.5" />
                  <rect x="14" y="4" width="4" height="16" rx="1.5" />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style={{ marginLeft: 2 }}>
                  <polygon points="6,4 20,12 6,20" />
                </svg>
              )}
            </button>
          </div>
          <span className="widget-dots-menu">⋮</span>
        </div>
      </div>

      {/* 3. 14-Segmented Horizontal Progress Strip matching Reference */}
      <div className="widget-segmented-bar-14" title={`Daily Goal: ${goalPct}%`}>
        {Array.from({ length: totalSegments }).map((_, i) => {
          const isLit = i < activeSegments;
          const bg = isLit ? segmentGradients[i] : '#141A28';
          const glow = isLit ? `0 0 7px ${segmentGradients[i]}88` : 'none';
          return (
            <div
              key={i}
              className={`widget-segment-pill ${isLit ? 'lit' : 'unlit'}`}
              style={{
                backgroundColor: bg,
                boxShadow: glow,
              }}
            />
          );
        })}
      </div>

      {/* 4. Horizontal Divider Line */}
      <div className="widget-horizontal-divider" />

      {/* 5. Bottom 3-Column Metrics Row */}
      <div className="widget-bottom-metrics-row-3col">
        {/* Column 1: Today work */}
        <div className="widget-metric-col">
          <span className="metric-lbl">Today work</span>
          <span className="metric-val-bold">{todayWorkLabel}</span>
        </div>

        <div className="widget-col-divider" />

        {/* Column 2: Daily goal */}
        <div className="widget-metric-col">
          <span className="metric-lbl">Daily goal</span>
          <span className="metric-val-bold">{goalPct}%</span>
          <div className="widget-mini-bar-track">
            <div
              className="widget-mini-bar-fill"
              style={{ width: `${Math.min(100, Math.max(6, goalPct))}%` }}
            />
          </div>
        </div>

        <div className="widget-col-divider" />

        {/* Column 3: Current block */}
        <div className="widget-metric-col right-badge-col">
          <span className="metric-lbl">Current block</span>
          <div className="widget-current-block-badge">
            <span className="code-bracket-icon">&lt;/&gt;</span>
            <span className="badge-text" title={activeBlockLabel}>
              {activeBlockLabel}
            </span>
          </div>
        </div>
      </div>

      {isEditingTask && (
        <ActivityEditModal
          isOpen={isEditingTask}
          onClose={() => setIsEditingTask(false)}
          activeTask={activeTask}
          categories={categories}
          onTaskSaved={() => {
            setIsEditingTask(false);
            if (onTaskAssigned) onTaskAssigned();
          }}
        />
      )}
    </div>
  );
};
