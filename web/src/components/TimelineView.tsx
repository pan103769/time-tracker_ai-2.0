import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { CategoryModel, SessionModel, TimeBlockModel } from '../types';
import { formatLocalDate, getLocalTodayString } from '../types';
import {
  clusterTimelineSessions,
} from '../utils/timelineClustering';
import { ActivityTimeline } from './ActivityTimeline';
import {
  AlertIcon,
  AppIconHelper,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  EditIcon,
  FilterIcon,
  PlusIcon,
  SearchIcon,
} from './Icons';
import { LiveDuration } from './LiveDuration';

interface TimelineViewProps {
  sessions: SessionModel[];
  categories?: CategoryModel[];
  timeBlocks?: TimeBlockModel[];
  selectedDate: string;
  onSelectSession: (session: SessionModel) => void;
  activeDates: string[];
  onSelectDate: (date: string) => void;
  isTracking?: boolean;
  onOpenManualActivity?: () => void;
}

export const TimelineView: React.FC<TimelineViewProps> = ({
  sessions,
  categories = [],
  timeBlocks = [],
  selectedDate,
  onSelectSession,
  activeDates,
  onSelectDate,
  isTracking = false,
  onOpenManualActivity,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [showIdle, setShowIdle] = useState(true);
  const [showUncertainOnly, setShowUncertainOnly] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [displayMode, setDisplayMode] = useState<'clustered' | 'detailed'>('clustered');
  const [expandedClusterIds, setExpandedClusterIds] = useState<Record<string, boolean>>({});

  // Daily sessions cache for multi-day inspection
  const [dailyCache, setDailyCache] = useState<Record<string, SessionModel[]>>({});
  const [loadingDates, setLoadingDates] = useState<Record<string, boolean>>({});
  const [collapsedDates, setCollapsedDates] = useState<Record<string, boolean>>({});

  const todayStr = useMemo(() => getLocalTodayString(), []);

  // Synchronize incoming sessions for the selectedDate into the daily cache
  useEffect(() => {
    if (selectedDate && sessions) {
      setDailyCache((prev) => ({
        ...prev,
        [selectedDate]: sessions,
      }));
    }
  }, [selectedDate, sessions]);

  // Derive consolidated list of dates with activity, newest first
  const allDates = useMemo(() => {
    const set = new Set<string>();
    if (selectedDate) set.add(selectedDate);
    for (const d of activeDates || []) {
      if (d) set.add(d);
    }
    return Array.from(set).sort((a, b) => b.localeCompare(a));
  }, [selectedDate, activeDates]);

  // Load timeline data for an older date on demand
  const loadDateSessions = useCallback(
    async (dateStr: string) => {
      if (dailyCache[dateStr] || loadingDates[dateStr]) return;
      setLoadingDates((prev) => ({ ...prev, [dateStr]: true }));
      try {
        const data = await api.getTimeline(dateStr);
        setDailyCache((prev) => ({ ...prev, [dateStr]: data }));
      } catch (err) {
        console.error(`Failed to load timeline for ${dateStr}:`, err);
      } finally {
        setLoadingDates((prev) => ({ ...prev, [dateStr]: false }));
      }
    },
    [dailyCache, loadingDates]
  );

  const toggleDayCollapse = (dateStr: string) => {
    const isCurrentlyCollapsed = collapsedDates[dateStr] ?? (dateStr !== selectedDate);
    const willExpand = isCurrentlyCollapsed;
    setCollapsedDates((prev) => ({
      ...prev,
      [dateStr]: !willExpand,
    }));
    if (willExpand && !dailyCache[dateStr]) {
      loadDateSessions(dateStr);
    }
  };

  const handlePrevDay = () => {
    const [y, m, day] = selectedDate.split('-').map(Number);
    const d = new Date(y, m - 1, day);
    d.setDate(d.getDate() - 1);
    onSelectDate(formatLocalDate(d));
  };

  const handleNextDay = () => {
    const [y, m, day] = selectedDate.split('-').map(Number);
    const d = new Date(y, m - 1, day);
    d.setDate(d.getDate() + 1);
    onSelectDate(formatLocalDate(d));
  };

  const handleToday = () => {
    onSelectDate(todayStr);
  };

  const toggleClusterExpand = (clusterId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedClusterIds((prev) => ({
      ...prev,
      [clusterId]: !prev[clusterId],
    }));
  };

  const formatSecs = (secs: number) => {
    const s = Math.round(secs);
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    if (h > 0) return `${h}h ${m % 60}m`;
    if (m > 0) return `${m}m ${s % 60}s`;
    return `${s}s`;
  };

  const formatDateHeader = (dateStr: string) => {
    try {
      const [y, m, day] = dateStr.split('-').map(Number);
      const d = new Date(y, m - 1, day);
      const weekday = d.toLocaleDateString(undefined, { weekday: 'long' });
      const monthName = d.toLocaleDateString(undefined, { month: 'short' });
      if (dateStr === todayStr) {
        return `Today — ${weekday}, ${monthName} ${day}, ${y}`;
      }
      const yDate = new Date();
      yDate.setDate(yDate.getDate() - 1);
      const yesterdayStr = formatLocalDate(yDate);
      if (dateStr === yesterdayStr) {
        return `Yesterday — ${weekday}, ${monthName} ${day}, ${y}`;
      }
      return `${weekday}, ${monthName} ${day}, ${y}`;
    } catch {
      return dateStr;
    }
  };

  // Helper to filter a date's sessions according to active filters
  const filterDaySessions = useCallback(
    (raw: SessionModel[]) => {
      return (raw || []).filter((s) => {
        if (!showIdle && s.kind === 'idle') return false;
        if (showUncertainOnly && (!s.is_uncertain || s.user_description)) return false;
        if (categoryFilter !== 'all') {
          const catId = s.category_id ? String(s.category_id) : 'uncategorized';
          const catType = s.category_type || 'uncategorized';
          if (categoryFilter === 'focus' && catType !== 'focus') return false;
          if (categoryFilter === 'work' && catType !== 'work') return false;
          if (categoryFilter === 'distraction' && catType !== 'distraction') return false;
          if (categoryFilter.startsWith('id:') && catId !== categoryFilter.replace('id:', '')) return false;
        }
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase();
          const inApp = (s.app || '').toLowerCase().includes(q);
          const inDesc = (s.description || '').toLowerCase().includes(q);
          const inTitle = (s.title || '').toLowerCase().includes(q);
          const inAct = (s.activity_name || '').toLowerCase().includes(q);
          const inTask = (s.specific_task || '').toLowerCase().includes(q);
          const inUrl = (s.url || '').toLowerCase().includes(q);
          const inCat = (s.category_name || '').toLowerCase().includes(q);
          return inApp || inDesc || inTitle || inAct || inTask || inUrl || inCat;
        }
        return true;
      });
    },
    [showIdle, showUncertainOnly, categoryFilter, searchQuery]
  );

  return (
    <div>
      {/* Top Navigation & Date Bar */}
      <div className="overview-top-header" style={{ marginBottom: 14 }}>
        <div className="header-date-pill-group">
          <button type="button" className="btn-date-nav" onClick={handlePrevDay} title="Previous day">
            <ChevronLeftIcon size={14} />
          </button>
          <span className="header-date-text">
            {selectedDate === todayStr ? `Today, ${selectedDate}` : selectedDate}
          </span>
          <button type="button" className="btn-date-nav" onClick={handleNextDay} title="Next day">
            <ChevronRightIcon size={14} />
          </button>
          <button type="button" className="btn-today-pill" onClick={handleToday}>
            Today
          </button>
        </div>

        {/* View Mode Toggle: Clustered vs Detailed & Add Activity */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {onOpenManualActivity && (
            <button
              type="button"
              className="timeline-mode-btn"
              onClick={onOpenManualActivity}
              title="Manually record untracked or off-screen activity"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                borderColor: 'rgba(128, 101, 255, 0.4)',
                color: '#C4B5FD',
                background: 'rgba(128, 101, 255, 0.12)',
              }}
            >
              <PlusIcon size={13} />
              <span>+ Add Activity</span>
            </button>
          )}

          <div className="timeline-mode-toggle">
            <button
              type="button"
              className={`timeline-mode-btn ${displayMode === 'clustered' ? 'active' : ''}`}
              onClick={() => setDisplayMode('clustered')}
            >
              Clustered View
            </button>
            <button
              type="button"
              className={`timeline-mode-btn ${displayMode === 'detailed' ? 'active' : ''}`}
              onClick={() => setDisplayMode('detailed')}
            >
              Detailed View
            </button>
          </div>
        </div>
      </div>

      {/* Interactive Multi-lane Activity Timeline for Selected Focus Date */}
      <div style={{ marginBottom: 20 }}>
        <ActivityTimeline
          sessions={sessions}
          timeBlocks={timeBlocks}
          selectedDate={selectedDate}
          onSelectSession={onSelectSession}
        />
      </div>

      {/* Filter Toolbar */}
      <div className="timeline-filter-bar">
        <div className="filter-search-box">
          <SearchIcon size={15} style={{ color: 'var(--text-muted)' }} />
          <input
            type="text"
            className="filter-search-input"
            placeholder="Search activity, app, url, or category…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="filter-controls">
          {/* Category Filter Dropdown */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <FilterIcon size={14} color="var(--text-muted)" />
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="filter-category-select"
            >
              <option value="all">All Categories</option>
              <option value="focus">⚡ Focus Only</option>
              <option value="work">💼 Work Only</option>
              <option value="distraction">⚠️ Distractions Only</option>
              {categories.map((c) => (
                <option key={c.id} value={`id:${c.id}`}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <label className="filter-toggle">
            <input
              type="checkbox"
              checked={showIdle}
              onChange={(e) => setShowIdle(e.target.checked)}
              style={{ accentColor: 'var(--accent-purple)' }}
            />
            <span>Show Idle Gaps</span>
          </label>

          <label className="filter-toggle">
            <input
              type="checkbox"
              checked={showUncertainOnly}
              onChange={(e) => setShowUncertainOnly(e.target.checked)}
              style={{ accentColor: 'var(--status-distraction)' }}
            />
            <span>Uncertain Only</span>
          </label>
        </div>
      </div>

      {/* Multi-Day Collapsible Timeline Sections */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {allDates.map((dateStr) => {
          const isSelected = dateStr === selectedDate;
          const isCollapsed = collapsedDates[dateStr] ?? (!isSelected);
          const rawDaySessions = dailyCache[dateStr] || (isSelected ? sessions : []);
          const filtered = filterDaySessions(rawDaySessions);
          const isLoading = Boolean(loadingDates[dateStr]);

          // Compute day stats
          const activeSecs = filtered
            .filter((s) => s.kind !== 'idle')
            .reduce((acc, curr) => acc + (curr.duration_seconds || 0), 0);
          const idleSecs = filtered
            .filter((s) => s.kind === 'idle')
            .reduce((acc, curr) => acc + (curr.duration_seconds || 0), 0);
          const activeCount = filtered.filter((s) => s.kind !== 'idle').length;

          // Clustered representation
          const clusters = displayMode === 'clustered' ? clusterTimelineSessions(filtered, 60, 180, false) : [];

          return (
            <div
              key={dateStr}
              style={{
                background: 'rgba(15, 20, 32, 0.75)',
                border: isSelected
                  ? '1px solid rgba(56, 189, 248, 0.45)'
                  : '1px solid rgba(128, 101, 255, 0.18)',
                borderRadius: 12,
                boxShadow: isSelected
                  ? '0 0 16px rgba(56, 189, 248, 0.10)'
                  : '0 4px 12px rgba(0, 0, 0, 0.25)',
                overflow: 'hidden',
                transition: 'all 0.2s ease',
              }}
            >
              {/* Daily Section Header */}
              <div
                onClick={() => toggleDayCollapse(dateStr)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '12px 18px',
                  background: isSelected
                    ? 'rgba(56, 189, 248, 0.06)'
                    : 'rgba(25, 34, 52, 0.4)',
                  cursor: 'pointer',
                  borderBottom: isCollapsed ? 'none' : '1px solid rgba(128, 101, 255, 0.15)',
                  userSelect: 'none',
                }}
              >
                {/* Left: Date Heading & Badges */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 20,
                      height: 20,
                      color: 'var(--text-muted)',
                      transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                      transition: 'transform 0.2s ease',
                      fontSize: 12,
                    }}
                  >
                    ▼
                  </span>
                  <span
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: isSelected ? 'var(--accent-teal-light, #38BDF8)' : 'var(--text-primary)',
                    }}
                  >
                    {formatDateHeader(dateStr)}
                  </span>
                  {isSelected && (
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--accent-teal, #16D5E2)',
                        background: 'rgba(22, 213, 226, 0.12)',
                        border: '1px solid rgba(22, 213, 226, 0.3)',
                        borderRadius: 4,
                        padding: '1px 7px',
                      }}
                    >
                      Active Focus
                    </span>
                  )}
                  {dateStr === todayStr && !isSelected && (
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--accent-purple, #8065FF)',
                        background: 'rgba(128, 101, 255, 0.12)',
                        borderRadius: 4,
                        padding: '1px 7px',
                      }}
                    >
                      Today
                    </span>
                  )}
                </div>

                {/* Right: Summary Metrics */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12 }}>
                  <span style={{ color: 'var(--text-secondary)' }}>
                    Tracked:{' '}
                    <strong style={{ color: 'var(--status-focus, #35D68A)', fontFamily: 'var(--font-mono)' }}>
                      {formatSecs(activeSecs)}
                    </strong>
                  </span>
                  {showIdle && idleSecs > 0 && (
                    <span style={{ color: 'var(--text-muted)' }}>
                      Idle:{' '}
                      <strong style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                        {formatSecs(idleSecs)}
                      </strong>
                    </span>
                  )}
                  <span
                    style={{
                      background: 'rgba(255, 255, 255, 0.06)',
                      padding: '2px 8px',
                      borderRadius: 10,
                      color: 'var(--text-muted)',
                      fontSize: 11,
                    }}
                  >
                    {displayMode === 'clustered' ? `${clusters.length} smart clusters` : `${activeCount} activities`}
                  </span>

                  {!isSelected && (
                    <button
                      type="button"
                      className="chip-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectDate(dateStr);
                      }}
                      style={{
                        padding: '3px 9px',
                        fontSize: 11,
                        borderColor: 'rgba(56, 189, 248, 0.3)',
                        color: 'var(--accent-teal-light)',
                      }}
                      title="Load this day into the interactive multi-lane timeline"
                    >
                      Focus Timeline ↗
                    </button>
                  )}
                </div>
              </div>

              {/* Daily Section Body (Expanded) */}
              {!isCollapsed && (
                <div style={{ padding: '14px 18px' }}>
                  {isLoading ? (
                    <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-muted)', fontSize: 13 }}>
                      Loading activity records for {dateStr}…
                    </div>
                  ) : filtered.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '18px 0', color: 'var(--text-muted)', fontSize: 13 }}>
                      No matching activity logged for this day.
                    </div>
                  ) : displayMode === 'clustered' ? (
                    /* Clustered View */
                    <div className="timeline-container">
                      {clusters.map((c) => {
                        const isIdle = c.is_idle;
                        const isExpanded = Boolean(expandedClusterIds[c.cluster_id]);
                        const startTime = c.start.slice(11, 19);
                        const endTime = c.end.slice(11, 19);

                        return (
                          <div
                            key={c.cluster_id}
                            className={`session-block ${isIdle ? 'idle' : ''} ${c.cluster_type === 'mixed' ? 'mixed-cluster' : ''}`}
                            onClick={() => c.original_session && onSelectSession(c.original_session)}
                            style={{ cursor: 'pointer' }}
                          >
                            {/* Time & Duration Column */}
                            <div className="session-time-col">
                              <span className="session-time-range">
                                {startTime} – {endTime}
                              </span>
                              <span className="session-duration">
                                <ClockIcon size={12} style={{ display: 'inline', verticalAlign: -1, marginRight: 4 }} />
                                {formatSecs(c.duration_seconds)}
                              </span>
                            </div>

                            {/* Color Indicator Bar */}
                            <div
                              className="session-indicator-bar"
                              style={{ backgroundColor: c.category_color || '#8065FF' }}
                            />

                            {/* Main Content Column */}
                            <div className="session-content-col">
                              <div className="session-desc-row">
                                <div className="session-desc" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                  <strong>{c.label}</strong>
                                  {c.interruption_count > 0 && (
                                    <span
                                      style={{
                                        fontSize: 11,
                                        fontWeight: 600,
                                        color: 'var(--status-distraction, #FA5275)',
                                        background: 'rgba(250, 82, 117, 0.15)',
                                        padding: '2px 6px',
                                        borderRadius: 4,
                                      }}
                                    >
                                      ⚡ {c.interruption_count} switch(es)
                                    </span>
                                  )}
                                </div>

                                {/* Breakdown tag */}
                                {c.child_segments.length > 1 && (
                                  <button
                                    type="button"
                                    className="btn-date-nav"
                                    onClick={(e) => toggleClusterExpand(c.cluster_id, e)}
                                    style={{ fontSize: 11.5, padding: '3px 8px' }}
                                  >
                                    {isExpanded ? 'Hide breakdown ▴' : `View ${c.child_segments.length} segments ▾`}
                                  </button>
                                )}
                              </div>

                              {/* App breakdown chips */}
                              <div className="session-meta-row" style={{ marginTop: 4 }}>
                                <span className="meta-chip">
                                  <AppIconHelper app={c.dominant_app} size={13} />
                                  {c.dominant_app}
                                </span>

                                {c.app_breakdown.map((item) => (
                                  <span key={item.app} className="meta-chip" style={{ fontSize: 11 }}>
                                    {item.app}: {item.label} ({item.pct}%)
                                  </span>
                                ))}
                              </div>

                              {/* Expanded child segments list */}
                              {isExpanded && c.child_segments.length > 1 && (
                                <div
                                  style={{
                                    marginTop: 10,
                                    paddingTop: 8,
                                    borderTop: '1px solid var(--border-subtle, #252E3C)',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: 5,
                                  }}
                                >
                                  {c.child_segments.map((seg, idx) => (
                                    <div
                                      key={idx}
                                      style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        fontSize: 12,
                                        padding: '3px 6px',
                                        background: 'rgba(255, 255, 255, 0.02)',
                                        borderRadius: 4,
                                        color: seg.is_interruption ? 'var(--status-distraction)' : 'var(--text-secondary)',
                                      }}
                                    >
                                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <AppIconHelper app={seg.app} size={12} />
                                        <span>{seg.app}</span>
                                        {seg.title && (
                                          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                                            — {seg.title.slice(0, 50)}
                                          </span>
                                        )}
                                      </div>
                                      <span style={{ fontFamily: 'var(--font-mono)' }}>
                                        {formatSecs(seg.duration_seconds)}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    /* Detailed View (Raw Observations) */
                    <div className="timeline-container">
                      {filtered.map((s) => {
                        const startTime = s.start.slice(11, 19);
                        const endTime = s.end.slice(11, 19);
                        const isIdle = s.kind === 'idle';
                        const isOngoing = Boolean(s.is_ongoing && isTracking && dateStr === todayStr);

                        return (
                          <div
                            key={s.session_key || `${s.start}-${s.display_number}`}
                            className={`session-block ${isIdle ? 'idle' : ''} ${isOngoing ? 'ongoing' : ''}`}
                            onClick={() => onSelectSession(s)}
                            title="Click to view details and edit description"
                          >
                            {/* Time & Duration Column */}
                            <div className="session-time-col">
                              <span className="session-time-range">
                                {startTime} – {isOngoing ? 'Present' : endTime}
                              </span>
                              <span className="session-duration">
                                <ClockIcon size={12} style={{ display: 'inline', verticalAlign: -1, marginRight: 4 }} />
                                <LiveDuration
                                  startTime={s.start}
                                  endTime={s.end}
                                  isLive={isOngoing}
                                  fallbackLabel={s.duration_label}
                                  className={isOngoing ? 'session-duration-live' : ''}
                                />
                              </span>
                            </div>

                            {/* Color Indicator Bar */}
                            <div
                              className={`session-indicator-bar ${
                                isIdle ? 'idle' : s.user_description ? 'edited' : s.is_uncertain ? 'uncertain' : ''
                              }`}
                              style={s.category_color && !isIdle ? { backgroundColor: s.category_color } : {}}
                            />

                            {/* Main Content Column */}
                            <div className="session-content-col">
                              <div className="session-desc-row">
                                <div className="session-desc">
                                  {s.description || (isIdle ? 'Idle — no input detected' : s.title)}
                                </div>
                                {/* Category pill */}
                                {s.category_name && !isIdle && (
                                  <span
                                    className="session-category-pill"
                                    style={{
                                      backgroundColor: `${s.category_color || '#8b5cf6'}22`,
                                      borderColor: s.category_color || '#8b5cf6',
                                      color: s.category_color || '#8b5cf6',
                                    }}
                                  >
                                    <span
                                      className="cat-dot-sm"
                                      style={{ backgroundColor: s.category_color || '#8b5cf6' }}
                                    />
                                    {s.category_name}
                                  </span>
                                )}
                              </div>

                              <div className="session-meta-row">
                                <span className="meta-chip">
                                  <AppIconHelper app={s.app} size={12} />
                                  {s.context_label ? s.context_label : s.app}
                                </span>

                                {s.title && s.title !== s.app && !isIdle && !s.context_label && (
                                  <span
                                    style={{
                                      maxWidth: 320,
                                      overflow: 'hidden',
                                      textOverflow: 'ellipsis',
                                      whiteSpace: 'nowrap',
                                      color: 'var(--text-muted)',
                                    }}
                                    title={s.title}
                                  >
                                    ↳ {s.title}
                                  </span>
                                )}

                                {s.user_description && (
                                  <span className="badge-edited">
                                    <EditIcon size={10} style={{ display: 'inline', marginRight: 3 }} />
                                    User Edited
                                  </span>
                                )}

                                {s.is_uncertain && !s.user_description && (
                                  <span className="badge-uncertain">
                                    <AlertIcon size={10} style={{ display: 'inline', marginRight: 3 }} />
                                    Uncertain
                                  </span>
                                )}

                                {s.confidence !== null && s.confidence > 0 && !isIdle && (
                                  <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                                    {Math.round(s.confidence * 100)}% conf
                                  </span>
                                )}

                                {s.url && (
                                  <span
                                    style={{
                                      color: 'var(--accent-teal-light)',
                                      fontSize: 11,
                                      maxWidth: 240,
                                      overflow: 'hidden',
                                      textOverflow: 'ellipsis',
                                      whiteSpace: 'nowrap',
                                    }}
                                    title={s.url}
                                  >
                                    {s.url}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
