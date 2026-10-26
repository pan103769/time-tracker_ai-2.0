import React, { useMemo, useState, useEffect, useRef } from 'react';
import type { SessionModel, TimeBlockModel } from '../types';
import {
  processTimelineData,
  createTimePositionHelper,
  formatDurationHuman,
  type ActivityBlockModel,
  type AppBlockModel,
  type GenericLaneBlockModel,
} from '../utils/activityTimelineEngine';
import {
  AppIconHelper,
  ChevronLeftIcon,
  ChevronRightIcon,
  CheckIcon,
  AlertTriangleIcon,
  CloseIcon,
  FilterIcon,
  InfoIcon,
  ClockIcon,
  ExternalLinkIcon,
} from './Icons';

interface ActivityTimelineProps {
  sessions: SessionModel[];
  timeBlocks?: TimeBlockModel[];
  selectedDate: string;
  onSelectSession?: (session: SessionModel) => void;
  onOpenNewBlock?: () => void;
}

export const ActivityTimeline: React.FC<ActivityTimelineProps> = ({
  sessions,
  timeBlocks = [],
  selectedDate,
  onSelectSession,
  onOpenNewBlock,
}) => {
  // Timeline zoom & pan controls (§1: 4h default, Day 00:00-24:00, 2h)
  const [zoomMode, setZoomMode] = useState<'day' | '4h' | '2h'>('4h');
  const [windowStartHour, setWindowStartHour] = useState<number>(() => {
    const h = new Date().getHours();
    return Math.max(0, Math.min(20, Math.floor(h / 4) * 4));
  });

  // Aggregation duration threshold: 10 min (600s) default vs 5 min (300s) (§2)
  const [minDurationThreshold, setMinDurationThreshold] = useState<300 | 600>(600);

  // Row visibility toggles (§3)
  // Apps (Detailed) is UNCHECKED by default, reducing clutter
  const [visibleRows, setVisibleRows] = useState({
    activities: true,
    apps: false,
    focus: true,
    breaks: true,
    distractions: true,
    idle: true,
  });

  // Full-Day Horizontal Scrollbar Dragging state & refs
  const scrollbarTrackRef = useRef<HTMLDivElement>(null);
  const [isDraggingScrollbar, setIsDraggingScrollbar] = useState<boolean>(false);
  const dragStartXRef = useRef<number>(0);
  const dragStartHourRef = useRef<number>(0);

  const [showFilterMenu, setShowFilterMenu] = useState(false);
  const filterMenuRef = useRef<HTMLDivElement>(null);

  // Selection & Inspector state
  const [selectedActivity, setSelectedActivity] = useState<ActivityBlockModel | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<AppBlockModel | null>(null);

  // Timeline view mode: Apps vs Categories matching Reference Image
  const [viewMode, setViewMode] = useState<'apps' | 'categories'>('apps');

  // Viewport-aware mouse-following tooltip state
  const [hoveredTooltip, setHoveredTooltip] = useState<{
    type: 'activity' | 'app' | 'lane';
    title: string;
    subtitle?: string;
    category?: string;
    fullDuration: string;
    visibleDuration?: string;
    timeRange: string;
    isClippedLeft?: boolean;
    isClippedRight?: boolean;
    taskMatch?: string;
    plannedTitle?: string;
    interruptions?: number;
    appBreakdown?: { app: string; pct: number; label: string }[];
    x: number;
    y: number;
    renderBelow: boolean;
  } | null>(null);

  // Close filter menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (filterMenuRef.current && !filterMenuRef.current.contains(e.target as Node)) {
        setShowFilterMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Execute deterministic timeline engine
  const timelineData = useMemo(() => {
    return processTimelineData(
      sessions,
      timeBlocks,
      minDurationThreshold,
      180, // 3 min gap coalesce
      zoomMode,
      windowStartHour,
      viewMode,
      selectedDate
    );
  }, [sessions, timeBlocks, minDurationThreshold, zoomMode, windowStartHour, viewMode, selectedDate]);

  // Live Current Time Marker calculation (§4)
  // Only display current time marker when selectedDate IS today AND inside the visible range!
  const [currentTimeOffsetPct, setCurrentTimeOffsetPct] = useState<number | null>(null);
  const [currentTimeLabel, setCurrentTimeLabel] = useState<string>('');

  useEffect(() => {
    const updateCurrentTime = () => {
      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, '0');
      const todayIso = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;

      if (selectedDate !== todayIso) {
        setCurrentTimeOffsetPct(null);
        setCurrentTimeLabel('');
        return;
      }

      const h = now.getHours();
      const m = now.getMinutes();
      const s = now.getSeconds();
      const ampm = h >= 12 ? 'PM' : 'AM';
      const dispH = h % 12 === 0 ? 12 : h % 12;
      const dispM = m.toString().padStart(2, '0');
      setCurrentTimeLabel(`${dispH}:${dispM} ${ampm}`);

      const nowSec = h * 3600 + m * 60 + s;
      const winStartSec = timelineData.startSec;
      const winEndSec = timelineData.endSec;

      if (nowSec >= winStartSec && nowSec <= winEndSec) {
        const pct = ((nowSec - winStartSec) / (winEndSec - winStartSec)) * 100;
        setCurrentTimeOffsetPct(pct);
      } else {
        setCurrentTimeOffsetPct(null);
      }
    };

    updateCurrentTime();
    const interval = setInterval(updateCurrentTime, 10000);
    return () => clearInterval(interval);
  }, [selectedDate, timelineData.startSec, timelineData.endSec]);

  // Time-to-pixel coordinate helper shared across all rows
  const getPosition = useMemo(() => {
    return createTimePositionHelper(timelineData.startSec, timelineData.endSec, 0.5);
  }, [timelineData.startSec, timelineData.endSec]);

  // Compute scrollbar thumb geometry across the full 24-hour day
  const windowSpanHours = zoomMode === 'day' ? 24 : zoomMode === '4h' ? 4 : 2;
  const maxStartHour = Math.max(0, 24 - windowSpanHours);
  const thumbWidthPct = (windowSpanHours / 24) * 100;
  const thumbLeftPct = zoomMode === 'day' ? 0 : Math.max(0, Math.min(100 - thumbWidthPct, (windowStartHour / 24) * 100));

  // Keep windowStartHour clamped when date or zoomMode changes
  useEffect(() => {
    setWindowStartHour((prev) => Math.max(0, Math.min(maxStartHour, prev)));
  }, [selectedDate, maxStartHour]);

  // Thumb drag listeners attached to window for smooth dragging even when cursor leaves track
  useEffect(() => {
    if (!isDraggingScrollbar) return;

    const handleWindowMouseMove = (e: MouseEvent) => {
      if (!scrollbarTrackRef.current) return;
      const trackRect = scrollbarTrackRef.current.getBoundingClientRect();
      if (trackRect.width <= 0) return;

      const deltaX = e.clientX - dragStartXRef.current;
      const deltaHours = (deltaX / trackRect.width) * 24;
      const targetStart = dragStartHourRef.current + deltaHours;
      const clamped = Math.max(0, Math.min(maxStartHour, targetStart));
      // Snap to 30-minute intervals (0.5 hour) for fluid, responsive dragging
      const snapped = Math.round(clamped * 2) / 2;
      setWindowStartHour(snapped);
    };

    const handleWindowMouseUp = () => {
      setIsDraggingScrollbar(false);
    };

    window.addEventListener('mousemove', handleWindowMouseMove);
    window.addEventListener('mouseup', handleWindowMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleWindowMouseMove);
      window.removeEventListener('mouseup', handleWindowMouseUp);
    };
  }, [isDraggingScrollbar, maxStartHour]);

  // Click on track to jump window position
  const handleTrackMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (zoomMode === 'day' || !scrollbarTrackRef.current) return;
    if ((e.target as HTMLElement).closest('.timeline-scrollbar-thumb')) return;

    const trackRect = scrollbarTrackRef.current.getBoundingClientRect();
    const clickX = e.clientX - trackRect.left;
    const ratio = Math.max(0, Math.min(1, clickX / trackRect.width));
    const clickedHour = ratio * 24;

    const targetStart = clickedHour - windowSpanHours / 2;
    const clamped = Math.max(0, Math.min(maxStartHour, targetStart));
    const snapped = Math.round(clamped * 2) / 2;
    setWindowStartHour(snapped);
  };

  const handleThumbMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (zoomMode === 'day') return;
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingScrollbar(true);
    dragStartXRef.current = e.clientX;
    dragStartHourRef.current = windowStartHour;
  };

  const handleScrollbarKeyDown = (e: React.KeyboardEvent) => {
    if (zoomMode === 'day') return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault();
      setWindowStartHour((prev) => Math.max(0, Math.round((prev - 0.5) * 2) / 2));
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault();
      setWindowStartHour((prev) => Math.min(maxStartHour, Math.round((prev + 0.5) * 2) / 2));
    } else if (e.key === 'PageUp') {
      e.preventDefault();
      setWindowStartHour((prev) => Math.max(0, Math.round((prev - windowSpanHours) * 2) / 2));
    } else if (e.key === 'PageDown') {
      e.preventDefault();
      setWindowStartHour((prev) => Math.min(maxStartHour, Math.round((prev + windowSpanHours) * 2) / 2));
    } else if (e.key === 'Home') {
      e.preventDefault();
      setWindowStartHour(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      setWindowStartHour(maxStartHour);
    }
  };

  // Navigation handlers (§1)
  const handlePrevWindow = () => {
    if (zoomMode === 'day') return;
    const step = zoomMode === '4h' ? 4 : 2;
    setWindowStartHour((prev) => Math.max(0, Math.round((prev - step) * 2) / 2));
  };

  const handleNextWindow = () => {
    if (zoomMode === 'day') return;
    const step = zoomMode === '4h' ? 4 : 2;
    setWindowStartHour((prev) => Math.min(maxStartHour, Math.round((prev + step) * 2) / 2));
  };

  const isPrevDisabled = zoomMode === 'day' || windowStartHour <= 0;
  const isNextDisabled = zoomMode === 'day' || windowStartHour >= maxStartHour;

  const handleSelectZoomMode = (mode: 'day' | '4h' | '2h') => {
    setZoomMode(mode);
    if (mode === 'day') {
      setWindowStartHour(0);
    } else if (mode === '4h') {
      setWindowStartHour((prev) => {
        if (prev === 0) {
          const nowH = new Date().getHours();
          return Math.max(0, Math.min(20, Math.floor(nowH / 4) * 4));
        }
        return Math.max(0, Math.min(20, Math.round(prev)));
      });
    } else if (mode === '2h') {
      setWindowStartHour((prev) => {
        if (prev === 0) {
          const nowH = new Date().getHours();
          return Math.max(0, Math.min(22, Math.floor(nowH / 2) * 2));
        }
        return Math.max(0, Math.min(22, Math.round(prev)));
      });
    }
  };

  // Format start & end time
  const formatTimeOnly = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  // Human label for current visible window range e.g. "00:00 – 24:00" or "4:00 PM – 8:00 PM" (§1)
  const visibleRangeLabel = useMemo(() => {
    if (zoomMode === 'day') {
      return '00:00 – 24:00';
    }
    const sH = timelineData.minHour;
    const eH = timelineData.maxHour;
    const formatH = (h: number) => {
      if (h === 0 || h === 24) return '12:00 AM';
      const wholeH = Math.floor(h);
      const fracM = Math.round((h - wholeH) * 60);
      const ampm = (wholeH >= 12 && wholeH < 24) ? 'PM' : 'AM';
      const dispH = wholeH % 12 === 0 ? 12 : wholeH % 12;
      if (fracM === 0) {
        return `${dispH}:00 ${ampm}`;
      }
      return `${dispH}:${fracM.toString().padStart(2, '0')} ${ampm}`;
    };
    return `${formatH(sH)} – ${formatH(eH)}`;
  }, [timelineData.minHour, timelineData.maxHour, zoomMode]);

  // Tooltip mouse position handler with viewport clamping
  const handleMouseMove = (
    e: React.MouseEvent,
    type: 'activity' | 'app' | 'lane',
    data: any,
    pos: { isClippedLeft: boolean; isClippedRight: boolean; visibleDurationSec: number }
  ) => {
    const mouseX = e.clientX;
    const mouseY = e.clientY;

    // Viewport horizontal clamping
    const clampedX = Math.max(160, Math.min(window.innerWidth - 180, mouseX));

    // Vertical placement: if near the top of the viewport (< 280px), render BELOW cursor
    // so it NEVER covers the title, toolbar, or hour axis!
    const renderBelow = mouseY < 280;
    const clampedY = renderBelow ? mouseY + 18 : mouseY - 14;

    const visibleDurLabel = formatDurationHuman(pos.visibleDurationSec);

    if (type === 'activity') {
      const act = data as ActivityBlockModel;
      setHoveredTooltip({
        type,
        title: act.title,
        subtitle: act.subtitle,
        category: act.category_name,
        fullDuration: act.duration_label,
        visibleDuration: (pos.isClippedLeft || pos.isClippedRight) ? visibleDurLabel : undefined,
        timeRange: `${formatTimeOnly(act.start)} – ${formatTimeOnly(act.end)}`,
        isClippedLeft: pos.isClippedLeft,
        isClippedRight: pos.isClippedRight,
        taskMatch: act.task_match_status,
        plannedTitle: act.planned_task_title,
        interruptions: act.interruption_count,
        appBreakdown: act.app_breakdown,
        x: clampedX,
        y: clampedY,
        renderBelow,
      });
    } else if (type === 'app') {
      const app = data as AppBlockModel;
      setHoveredTooltip({
        type,
        title: app.is_dense_cluster ? 'Micro-Switch Cluster' : (app.title || app.app),
        subtitle: app.app,
        fullDuration: app.duration_label,
        visibleDuration: (pos.isClippedLeft || pos.isClippedRight) ? visibleDurLabel : undefined,
        timeRange: `${formatTimeOnly(app.start)} – ${formatTimeOnly(app.end)}`,
        isClippedLeft: pos.isClippedLeft,
        isClippedRight: pos.isClippedRight,
        interruptions: app.is_dense_cluster ? app.switch_count : undefined,
        x: clampedX,
        y: clampedY,
        renderBelow,
      });
    } else {
      const lane = data as GenericLaneBlockModel;
      setHoveredTooltip({
        type,
        title: lane.label,
        subtitle: lane.associated_app,
        fullDuration: lane.duration_label,
        visibleDuration: (pos.isClippedLeft || pos.isClippedRight) ? visibleDurLabel : undefined,
        timeRange: `${formatTimeOnly(lane.start)} – ${formatTimeOnly(lane.end)}`,
        isClippedLeft: pos.isClippedLeft,
        isClippedRight: pos.isClippedRight,
        plannedTitle: lane.reason,
        x: clampedX,
        y: clampedY,
        renderBelow,
      });
    }
  };

  const handleMouseLeave = () => {
    setHoveredTooltip(null);
  };

  // Cross-row selection highlight beam coordinates
  const selectedBeamPos = useMemo(() => {
    if (!selectedActivity) return null;
    return getPosition(selectedActivity.start_sec, selectedActivity.end_sec);
  }, [selectedActivity, getPosition]);

  // Count active rows for filter badge
  const activeRowsCount = Object.values(visibleRows).filter(Boolean).length;

  return (
    <div className="activity-timeline-card-root">
      {/* Top Header & Structured Toolbar matching Master Reference */}
      <div className="activity-timeline-header-bar">
        <div className="activity-timeline-header-title-group">
          <div className="activity-timeline-icon-badge">
            <ClockIcon size={16} />
          </div>
          <h3 className="activity-timeline-title">Activity Timeline</h3>
          <span className="activity-timeline-info-trigger" title="Consolidated timeline matching master reference">
            <InfoIcon size={14} />
          </span>

          {/* Apps / Categories View Mode Toggle Pill matching Reference */}
          <div className="timeline-view-mode-pill-group">
            <button
              type="button"
              className={`timeline-mode-pill ${viewMode === 'apps' ? 'active' : ''}`}
              onClick={() => setViewMode('apps')}
            >
              Apps
            </button>
            <button
              type="button"
              className={`timeline-mode-pill ${viewMode === 'categories' ? 'active' : ''}`}
              onClick={() => setViewMode('categories')}
            >
              Categories
            </button>
          </div>
        </div>

        <div className="activity-timeline-controls-cluster">
          {/* Min Block duration selector (§2) */}
          <div className="timeline-pill-group">
            <span className="timeline-control-sublabel">Min Block</span>
            <button
              type="button"
              className={`timeline-pill-btn ${minDurationThreshold === 300 ? 'active' : ''}`}
              onClick={() => setMinDurationThreshold(300)}
              title="Group sessions shorter than 5 minutes"
            >
              5m
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${minDurationThreshold === 600 ? 'active' : ''}`}
              onClick={() => setMinDurationThreshold(600)}
              title="Group sessions shorter than 10 minutes"
            >
              10m
            </button>
          </div>

          {/* Timeline Range: Day / 4h / 2h (§1) */}
          <div className="timeline-pill-group">
            <button
              type="button"
              className={`timeline-pill-btn ${zoomMode === 'day' ? 'active' : ''}`}
              onClick={() => handleSelectZoomMode('day')}
              title="Full 24-hour day overview (00:00 – 24:00)"
            >
              Day
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${zoomMode === '4h' ? 'active' : ''}`}
              onClick={() => handleSelectZoomMode('4h')}
              title="4-hour detailed window"
            >
              4h
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${zoomMode === '2h' ? 'active' : ''}`}
              onClick={() => handleSelectZoomMode('2h')}
              title="2-hour micro window"
            >
              2h
            </button>
          </div>

          {/* Pan Navigation Chevrons with Visible Window Badge (§1) */}
          <div className="timeline-pan-controls-wrap">
            <button
              type="button"
              className="timeline-pan-btn"
              onClick={handlePrevWindow}
              disabled={isPrevDisabled}
              title="Previous time window"
              style={{
                opacity: isPrevDisabled ? 0.35 : 1,
                cursor: isPrevDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              <ChevronLeftIcon size={13} />
            </button>
            <span className="timeline-visible-window-badge">
              {visibleRangeLabel}
            </span>
            <button
              type="button"
              className="timeline-pan-btn"
              onClick={handleNextWindow}
              disabled={isNextDisabled}
              title="Next time window"
              style={{
                opacity: isNextDisabled ? 0.35 : 1,
                cursor: isNextDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              <ChevronRightIcon size={13} />
            </button>
          </div>

          {/* Rows Menu Dropdown (§3: Rows (5/6) by default with Apps unchecked) */}
          <div className="timeline-filter-dropdown-container" ref={filterMenuRef}>
            <button
              type="button"
              className={`timeline-filter-btn ${showFilterMenu ? 'active' : ''}`}
              onClick={() => setShowFilterMenu((prev) => !prev)}
              title="Toggle timeline rows visibility"
            >
              <FilterIcon size={12} />
              <span>Rows ({activeRowsCount}/6)</span>
              <span style={{ fontSize: 9, opacity: 0.7 }}>▾</span>
            </button>

            {showFilterMenu && (
              <div className="timeline-filter-menu-popover">
                <div className="filter-menu-header">
                  Row Visibility ({activeRowsCount}/6)
                </div>
                <label className="filter-menu-item">
                  <input
                    type="checkbox"
                    checked={visibleRows.activities}
                    onChange={(e) =>
                      setVisibleRows((p) => ({ ...p, activities: e.target.checked }))
                    }
                  />
                  <span>1. Activities (Primary)</span>
                </label>
                <label className="filter-menu-item">
                  <input
                    type="checkbox"
                    checked={visibleRows.apps}
                    onChange={(e) =>
                      setVisibleRows((p) => ({ ...p, apps: e.target.checked }))
                    }
                  />
                  <span>2. Apps (Detailed)</span>
                </label>
                <label className="filter-menu-item">
                  <input
                    type="checkbox"
                    checked={visibleRows.focus}
                    onChange={(e) =>
                      setVisibleRows((p) => ({ ...p, focus: e.target.checked }))
                    }
                  />
                  <span>3. Focus</span>
                </label>
                <label className="filter-menu-item">
                  <input
                    type="checkbox"
                    checked={visibleRows.breaks}
                    onChange={(e) =>
                      setVisibleRows((p) => ({ ...p, breaks: e.target.checked }))
                    }
                  />
                  <span>4. Breaks</span>
                </label>
                <label className="filter-menu-item">
                  <input
                    type="checkbox"
                    checked={visibleRows.distractions}
                    onChange={(e) =>
                      setVisibleRows((p) => ({ ...p, distractions: e.target.checked }))
                    }
                  />
                  <span>5. Distractions</span>
                </label>
                <label className="filter-menu-item">
                  <input
                    type="checkbox"
                    checked={visibleRows.idle}
                    onChange={(e) =>
                      setVisibleRows((p) => ({ ...p, idle: e.target.checked }))
                    }
                  />
                  <span>6. Idle</span>
                </label>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Multi-lane Timeline Board */}
      <div className="activity-timeline-board-wrap">
        {/* Live Vertical Current Time Marker */}
        {currentTimeOffsetPct !== null && (
          <div
            className="timeline-current-time-marker"
            style={{
              left: `calc(96px + (100% - 96px) * ${Math.max(0, Math.min(100, currentTimeOffsetPct))} / 100)`,
            }}
          >
            <div className="timeline-current-time-badge">{currentTimeLabel}</div>
          </div>
        )}

        {/* Cross-row Selection Highlight Beam (§6) */}
        {selectedBeamPos && selectedBeamPos.isVisible && (
          <div
            className="cross-row-selection-beam"
            style={{
              left: `calc(96px + (100% - 96px) * ${selectedBeamPos.leftPct} / 100)`,
              width: `calc((100% - 96px) * ${selectedBeamPos.widthPct} / 100)`,
            }}
          />
        )}

        {/* Shared Hour Header Axis with Vertical Guidelines */}
        <div className="activity-timeline-hour-axis">
          <div className="lane-header-label-col">TIME</div>
          <div className="hour-axis-track">
            {timelineData.hourMarkers.map((hm) => (
              <div
                key={hm.hour}
                className="hour-tick-node"
                style={{ left: `${hm.leftPct}%` }}
              >
                <span className="hour-tick-label">{hm.label}</span>
                <div className="hour-vertical-guideline" />
              </div>
            ))}
          </div>
        </div>

        {/* Multi-lane Rows Body */}
        <div className="activity-timeline-rows-container">
          {/* ROW 1: ACTIVITIES (Primary Row, ~38px height) (§3) */}
          {visibleRows.activities && (
            <div className="activity-lane-row primary-activity-row">
              <div className="lane-header-label-col">
                <span className="row-lane-name highlight">Activities</span>
                <span className="row-lane-tag">Primary</span>
              </div>
              <div className="lane-track-canvas activities-track-canvas">
                {timelineData.activities.map((act) => {
                  const pos = getPosition(act.start_sec, act.end_sec);
                  if (!pos.isVisible) return null;
                  const isSelected = selectedActivity?.id === act.id;

                  const isMatch = act.task_match_status === 'match';
                  const isMismatch = act.task_match_status === 'mismatch';

                  const showFullLabel = pos.widthPct >= 7;
                  const showShortLabel = pos.widthPct >= 3.5 && pos.widthPct < 7;
                  const isTinyPip = pos.widthPct < 3.5;

                  return (
                    <div
                      key={act.id}
                      className={`primary-activity-block ${isSelected ? 'selected' : ''} ${pos.isClippedLeft ? 'clipped-left' : ''} ${pos.isClippedRight ? 'clipped-right' : ''} ${isTinyPip ? 'tiny-pip' : ''}`}
                      style={{
                        left: `${pos.leftPct}%`,
                        width: `${pos.widthPct}%`,
                        borderColor: isMismatch
                          ? '#FA5275'
                          : isMatch
                          ? '#35D68A'
                          : act.category_color || '#8065FF',
                        backgroundColor: `${act.category_color || '#8065FF'}24`,
                      }}
                      onClick={() => {
                        setSelectedActivity(isSelected ? null : act);
                        setSelectedCluster(null);
                      }}
                      onMouseMove={(e) => handleMouseMove(e, 'activity', act, pos)}
                      onMouseLeave={handleMouseLeave}
                    >
                      {/* Left/Right clipping indicator tags */}
                      {pos.isClippedLeft && <span className="clip-indicator-left">◀</span>}

                      {/* Task-match status icon badge */}
                      {isMatch && !isTinyPip && (
                        <span className="activity-badge-status match" title="Matches scheduled time block">
                          <CheckIcon size={10} />
                        </span>
                      )}
                      {isMismatch && !isTinyPip && (
                        <span className="activity-badge-status mismatch" title="Mismatch with scheduled time block">
                          <AlertTriangleIcon size={10} />
                        </span>
                      )}

                      {/* Absorbed brief interruption indicator */}
                      {act.interruption_count > 0 && !isTinyPip && (
                        <span
                          className="activity-interruption-dot"
                          title={`${act.interruption_count} absorbed switch(es)`}
                        />
                      )}

                      {/* Text label depending on available width */}
                      {showFullLabel && (
                        <div className="activity-block-text-wrap">
                          <span className="activity-block-title">{act.title}</span>
                          <span className="activity-block-duration">{act.duration_label}</span>
                        </div>
                      )}
                      {showShortLabel && (
                        <div className="activity-block-text-wrap">
                          <span className="activity-block-title">{act.title}</span>
                        </div>
                      )}
                      {isTinyPip && (
                        <div
                          className="activity-tiny-pip-dot"
                          style={{ backgroundColor: act.category_color || '#8065FF' }}
                        />
                      )}

                      {pos.isClippedRight && <span className="clip-indicator-right">▶</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ROW 2: APPS (Detailed Application Activity, ~24px height) (§4) */}
          {visibleRows.apps && (
            <div className="activity-lane-row subordinate-app-row">
              <div className="lane-header-label-col">
                <span className="row-lane-name">Apps</span>
              </div>
              <div className="lane-track-canvas apps-track-canvas">
                {timelineData.apps.map((app) => {
                  const pos = getPosition(app.start_sec, app.end_sec);
                  if (!pos.isVisible) return null;

                  if (app.is_dense_cluster) {
                    return (
                      <div
                        key={app.id}
                        className="app-micro-cluster-pill"
                        style={{
                          left: `${pos.leftPct}%`,
                          width: `${Math.max(2.2, pos.widthPct)}%`,
                        }}
                        onClick={() => setSelectedCluster(app)}
                        onMouseMove={(e) => handleMouseMove(e, 'app', app, pos)}
                        onMouseLeave={handleMouseLeave}
                      >
                        <span className="cluster-badge-text">+{app.switch_count} events</span>
                      </div>
                    );
                  }

                  const showAppText = pos.widthPct >= 5;
                  const showAppIcon = pos.widthPct >= 2;

                  return (
                    <div
                      key={app.id}
                      className={`app-detail-pill ${pos.isClippedLeft ? 'clipped-left' : ''} ${pos.isClippedRight ? 'clipped-right' : ''}`}
                      style={{
                        left: `${pos.leftPct}%`,
                        width: `${pos.widthPct}%`,
                        borderColor: `${app.category_color}55`,
                        backgroundColor: `${app.category_color}1a`,
                      }}
                      onClick={() => {
                        if (app.original_session && onSelectSession) {
                          onSelectSession(app.original_session);
                        }
                      }}
                      onMouseMove={(e) => handleMouseMove(e, 'app', app, pos)}
                      onMouseLeave={handleMouseLeave}
                    >
                      {showAppIcon && <AppIconHelper app={app.app} size={11} />}
                      {showAppText && (
                        <span className="app-detail-label">
                          {app.app} {pos.widthPct > 9 ? `(${app.duration_label})` : ''}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ROW 3: FOCUS (~14px height, green/teal) (§5) */}
          {visibleRows.focus && (
            <div className="activity-lane-row slim-status-row">
              <div className="lane-header-label-col">
                <span className="row-lane-name">Focus</span>
              </div>
              <div className="lane-track-canvas slim-track-canvas">
                {timelineData.focus.map((fc) => {
                  const pos = getPosition(fc.start_sec, fc.end_sec);
                  if (!pos.isVisible) return null;
                  return (
                    <div
                      key={fc.id}
                      className="lane-segment-bar focus-segment"
                      style={{ left: `${pos.leftPct}%`, width: `${pos.widthPct}%` }}
                      onClick={() => fc.original_session && onSelectSession?.(fc.original_session)}
                      onMouseMove={(e) => handleMouseMove(e, 'lane', fc, pos)}
                      onMouseLeave={handleMouseLeave}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {/* ROW 4: BREAKS (~14px height, cyan) (§5) */}
          {visibleRows.breaks && (
            <div className="activity-lane-row slim-status-row">
              <div className="lane-header-label-col">
                <span className="row-lane-name">Breaks</span>
              </div>
              <div className="lane-track-canvas slim-track-canvas">
                {timelineData.breaks.map((brk) => {
                  const pos = getPosition(brk.start_sec, brk.end_sec);
                  if (!pos.isVisible) return null;
                  return (
                    <div
                      key={brk.id}
                      className="lane-segment-bar break-segment"
                      style={{ left: `${pos.leftPct}%`, width: `${pos.widthPct}%` }}
                      onClick={() => brk.original_session && onSelectSession?.(brk.original_session)}
                      onMouseMove={(e) => handleMouseMove(e, 'lane', brk, pos)}
                      onMouseLeave={handleMouseLeave}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {/* ROW 5: DISTRACTIONS (~14px height, coral red) (§5) */}
          {visibleRows.distractions && (
            <div className="activity-lane-row slim-status-row">
              <div className="lane-header-label-col">
                <span className="row-lane-name">Distractions</span>
              </div>
              <div className="lane-track-canvas slim-track-canvas">
                {timelineData.distractions.map((dis) => {
                  const pos = getPosition(dis.start_sec, dis.end_sec);
                  if (!pos.isVisible) return null;
                  return (
                    <div
                      key={dis.id}
                      className="lane-segment-bar distraction-segment"
                      style={{ left: `${pos.leftPct}%`, width: `${pos.widthPct}%` }}
                      onClick={() => dis.original_session && onSelectSession?.(dis.original_session)}
                      onMouseMove={(e) => handleMouseMove(e, 'lane', dis, pos)}
                      onMouseLeave={handleMouseLeave}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {/* ROW 6: IDLE (~14px height, slate muted) (§5) */}
          {visibleRows.idle && (
            <div className="activity-lane-row slim-status-row">
              <div className="lane-header-label-col">
                <span className="row-lane-name">Idle</span>
              </div>
              <div className="lane-track-canvas slim-track-canvas">
                {timelineData.idle.map((idl) => {
                  const pos = getPosition(idl.start_sec, idl.end_sec);
                  if (!pos.isVisible) return null;
                  return (
                    <div
                      key={idl.id}
                      className="lane-segment-bar idle-segment"
                      style={{ left: `${pos.leftPct}%`, width: `${pos.widthPct}%` }}
                      onClick={() => idl.original_session && onSelectSession?.(idl.original_session)}
                      onMouseMove={(e) => handleMouseMove(e, 'lane', idl, pos)}
                      onMouseLeave={handleMouseLeave}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {/* HORIZONTAL FULL-DAY SCROLLBAR ROW (Directly below Idle) */}
          <div className="activity-lane-row timeline-scrollbar-row">
            <div className="lane-header-label-col scrollbar-header-col" aria-hidden="true" />
            <div
              className={`lane-track-canvas timeline-scrollbar-track ${zoomMode === 'day' ? 'disabled' : ''}`}
              ref={scrollbarTrackRef}
              onMouseDown={handleTrackMouseDown}
              title={zoomMode === 'day' ? 'Complete 24-hour day visible' : 'Click or drag anywhere to navigate through the selected day'}
            >
              {/* Draggable Visible Window Thumb */}
              <div
                className={`timeline-scrollbar-thumb ${isDraggingScrollbar ? 'dragging' : ''} ${zoomMode === 'day' ? 'full-day' : ''}`}
                style={{
                  left: `${thumbLeftPct}%`,
                  width: `${thumbWidthPct}%`,
                }}
                onMouseDown={handleThumbMouseDown}
                onKeyDown={handleScrollbarKeyDown}
                role="scrollbar"
                aria-valuenow={windowStartHour}
                aria-valuemin={0}
                aria-valuemax={maxStartHour}
                aria-orientation="horizontal"
                aria-label="Timeline visible window"
                tabIndex={zoomMode === 'day' ? -1 : 0}
                title={zoomMode === 'day' ? 'Full Day View' : `Drag to navigate day: ${visibleRangeLabel}`}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Viewport-Aware, Mouse-Following Floating Tooltip (§2) */}
      {hoveredTooltip && (
        <div
          className="timeline-floating-tooltip"
          style={{
            left: `${hoveredTooltip.x}px`,
            top: `${hoveredTooltip.y}px`,
            transform: hoveredTooltip.renderBelow ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
          }}
        >
          <div className="tooltip-header">
            <span className="tooltip-title">{hoveredTooltip.title}</span>
            <span className="tooltip-duration-badge">{hoveredTooltip.fullDuration}</span>
          </div>

          <div className="tooltip-time-range">{hoveredTooltip.timeRange}</div>

          {/* Window clipping explanation if event extends past visible window */}
          {hoveredTooltip.visibleDuration && (
            <div className="tooltip-clipping-notice">
              <span className="clipping-tag">Visible in window: {hoveredTooltip.visibleDuration}</span>
              {hoveredTooltip.isClippedLeft && (
                <span className="clipping-note">◀ Started before visible window</span>
              )}
              {hoveredTooltip.isClippedRight && (
                <span className="clipping-note">▶ Continues past visible window</span>
              )}
            </div>
          )}

          {hoveredTooltip.category && (
            <div className="tooltip-meta-row">
              <span className="tooltip-meta-label">Category:</span>
              <span className="tooltip-meta-val">{hoveredTooltip.category}</span>
            </div>
          )}

          {hoveredTooltip.taskMatch && hoveredTooltip.taskMatch !== 'unknown' && (
            <div className={`tooltip-match-tag ${hoveredTooltip.taskMatch}`}>
              {hoveredTooltip.taskMatch === 'match'
                ? '✓ Matches planned task'
                : hoveredTooltip.taskMatch === 'mismatch'
                ? '⚠️ Off-track from planned task'
                : 'Neutral activity'}
            </div>
          )}

          {hoveredTooltip.plannedTitle && (
            <div className="tooltip-meta-row">
              <span className="tooltip-meta-label">Note:</span>
              <span className="tooltip-meta-val">{hoveredTooltip.plannedTitle}</span>
            </div>
          )}

          {hoveredTooltip.interruptions !== undefined && hoveredTooltip.interruptions > 0 && (
            <div className="tooltip-interruption-note">
              {hoveredTooltip.interruptions} brief interruption(s) absorbed
            </div>
          )}

          {hoveredTooltip.appBreakdown && hoveredTooltip.appBreakdown.length > 0 && (
            <div className="tooltip-app-breakdown-list">
              <div className="tooltip-breakdown-label">Applications:</div>
              {hoveredTooltip.appBreakdown.slice(0, 3).map((item) => (
                <div key={item.app} className="tooltip-breakdown-item">
                  <span className="app-name">{item.app}</span>
                  <span className="app-pct">{item.pct}% ({item.label})</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Selected Activity Detail Inspector Drawer / Modal (§3, §4) */}
      {selectedActivity && (
        <div className="activity-inspector-card">
          <div className="inspector-card-header">
            <div className="inspector-title-group">
              <div
                className="category-dot-indicator"
                style={{ backgroundColor: selectedActivity.category_color || '#8065FF' }}
              />
              <h4 className="inspector-activity-title">{selectedActivity.title}</h4>
              <span className="inspector-duration-pill">{selectedActivity.duration_label}</span>
            </div>
            <button
              type="button"
              className="inspector-close-btn"
              onClick={() => setSelectedActivity(null)}
              title="Close inspector"
            >
              <CloseIcon size={14} />
            </button>
          </div>

          <div className="inspector-body-grid">
            {/* Meta summary column */}
            <div className="inspector-meta-col">
              <div className="inspector-meta-item">
                <span className="meta-lbl">Time Interval</span>
                <span className="meta-val">
                  {formatTimeOnly(selectedActivity.start)} – {formatTimeOnly(selectedActivity.end)}
                </span>
              </div>
              <div className="inspector-meta-item">
                <span className="meta-lbl">Category</span>
                <span className="meta-val">{selectedActivity.category_name}</span>
              </div>
              <div className="inspector-meta-item">
                <span className="meta-lbl">Task Match</span>
                <span className={`meta-val task-status ${selectedActivity.task_match_status}`}>
                  {selectedActivity.task_match_status === 'match' && '✓ Aligned with Schedule'}
                  {selectedActivity.task_match_status === 'mismatch' && '⚠️ Schedule Mismatch'}
                  {selectedActivity.task_match_status === 'neutral' && 'Neutral Work'}
                  {selectedActivity.task_match_status === 'unknown' && 'Unscheduled Activity'}
                </span>
              </div>
              {selectedActivity.planned_task_title ? (
                <div className="inspector-meta-item">
                  <span className="meta-lbl">Scheduled Task</span>
                  <span className="meta-val highlight">{selectedActivity.planned_task_title}</span>
                </div>
              ) : onOpenNewBlock ? (
                <div style={{ marginTop: 6 }}>
                  <button
                    type="button"
                    className="timeline-pill-btn active"
                    onClick={onOpenNewBlock}
                    style={{ fontSize: 11, padding: '3px 8px' }}
                  >
                    + Schedule as Time Block
                  </button>
                </div>
              ) : null}
            </div>

            {/* Application breakdown column */}
            <div className="inspector-breakdown-col">
              <span className="meta-lbl">Application Distribution</span>
              <div className="inspector-progress-bars">
                {selectedActivity.app_breakdown.map((item) => (
                  <div key={item.app} className="inspector-app-row">
                    <div className="app-info-line">
                      <div className="app-name-wrap">
                        <AppIconHelper app={item.app} size={13} />
                        <span>{item.app}</span>
                      </div>
                      <span className="app-dur-text">{item.label} ({item.pct}%)</span>
                    </div>
                    <div className="app-meter-track">
                      <div
                        className="app-meter-fill"
                        style={{
                          width: `${item.pct}%`,
                          backgroundColor: selectedActivity.category_color || '#8065FF',
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Child App Events chronological list */}
          <div className="inspector-events-section">
            <div className="events-section-header">
              <span>Granular App Events ({selectedActivity.child_events.length})</span>
            </div>
            <div className="inspector-events-list">
              {selectedActivity.child_events.map((ev) => (
                <div
                  key={ev.id}
                  className={`inspector-event-item ${ev.is_interruption ? 'is-interruption' : ''}`}
                  onClick={() => ev.original_session && onSelectSession?.(ev.original_session)}
                >
                  <div className="event-item-main">
                    <AppIconHelper app={ev.app} size={14} />
                    <div className="event-item-text">
                      <span className="event-app-name">{ev.app}</span>
                      <span className="event-window-title">{ev.title || 'No window title'}</span>
                    </div>
                  </div>
                  <div className="event-item-meta">
                    <span className="event-time">
                      {formatTimeOnly(ev.start)} – {formatTimeOnly(ev.end)}
                    </span>
                    <span className="event-dur">{ev.duration_label}</span>
                    <span className="event-inspect-icon" title="Inspect raw session">
                      <ExternalLinkIcon size={12} />
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Dense Micro-switch Cluster Modal Inspector (§4) */}
      {selectedCluster && (
        <div className="activity-inspector-card cluster-inspector">
          <div className="inspector-card-header">
            <div className="inspector-title-group">
              <div className="category-dot-indicator" style={{ backgroundColor: '#8065FF' }} />
              <h4 className="inspector-activity-title">
                Rapid Task Switching ({selectedCluster.switch_count} events in {selectedCluster.duration_label})
              </h4>
            </div>
            <button
              type="button"
              className="inspector-close-btn"
              onClick={() => setSelectedCluster(null)}
              title="Close"
            >
              <CloseIcon size={14} />
            </button>
          </div>
          <div className="inspector-events-list">
            {selectedCluster.child_events.map((ev) => (
              <div
                key={ev.id}
                className="inspector-event-item"
                onClick={() => ev.original_session && onSelectSession?.(ev.original_session)}
              >
                <div className="event-item-main">
                  <AppIconHelper app={ev.app} size={14} />
                  <div className="event-item-text">
                    <span className="event-app-name">{ev.app}</span>
                    <span className="event-window-title">{ev.title}</span>
                  </div>
                </div>
                <div className="event-item-meta">
                  <span className="event-time">
                    {formatTimeOnly(ev.start)} – {formatTimeOnly(ev.end)}
                  </span>
                  <span className="event-dur">{ev.duration_label}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
