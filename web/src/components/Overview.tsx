import React, { useMemo, useState } from 'react';
import {
  type ActiveTaskModel,
  type CategoryModel,
  type DailyAiSummaryModel,
  type ProductivityModel,
  type SessionModel,
  type StatsModel,
  type TimeBlockModel,
  type WeeklyStatsModel,
  formatLocalDate,
  getLocalTodayString,
} from '../types';
import { ActivityTimeline } from './ActivityTimeline';
import { PlanTimeBlockCard } from './PlanTimeBlockCard';
import { RightWidgetCard } from './RightWidgetCard';
import { TodayTimelineCard } from './TodayTimelineCard';
import {
  AppIconHelper,
  CalendarIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  CloseIcon,
  CoffeeIcon,
  FilterIcon,
  GamepadIcon,
  InfoIcon,
  PieChartIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
  SparklesIcon,
  TargetIcon,
  WidgetIcon,
} from './Icons';

interface OverviewProps {
  stats: StatsModel | null;
  weeklyStats?: WeeklyStatsModel | null;
  productivity: ProductivityModel | null;
  aiSummary: DailyAiSummaryModel | null;
  sessions: SessionModel[];
  categories?: CategoryModel[];
  timeBlocks?: TimeBlockModel[];
  activeTask?: ActiveTaskModel | null;
  selectedDate?: string;
  onSelectDate?: (date: string) => void;
  onSelectSession: (session: SessionModel) => void;
  onRefreshAiSummary?: () => void;
  isAiRefreshing?: boolean;
  activeDates?: string[];
  isTracking?: boolean;
  onToggleTracking?: () => void;
  onLaunchNativeWidget?: () => void;
  onBlockCreated?: () => void;
  onNavigateGoals?: () => void;
  onNavigateCategories?: () => void;
  onNavigateInsights?: () => void;
  onNavigateTimeline?: () => void;
  onOpenNewBlock?: () => void;
  onOpenManualActivity?: () => void;
  searchQuery?: string;
  onSearchChange?: (q: string) => void;
  userName?: string;
}

export const Overview: React.FC<OverviewProps> = ({
  stats,
  productivity,
  aiSummary,
  sessions,
  categories = [],
  timeBlocks = [],
  activeTask = null,
  selectedDate,
  onSelectDate,
  onSelectSession,
  onRefreshAiSummary,
  isAiRefreshing = false,
  isTracking = false,
  onToggleTracking,
  onLaunchNativeWidget,
  onBlockCreated,
  onNavigateGoals,
  onNavigateCategories,
  onNavigateInsights,
  onOpenNewBlock,
  onOpenManualActivity,
  searchQuery = '',
  onSearchChange,
  userName = 'pant',
}) => {
  // Filter sessions by search query if provided
  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter(
      (s) =>
        s.app.toLowerCase().includes(q) ||
        s.title.toLowerCase().includes(q) ||
        (s.category_name && s.category_name.toLowerCase().includes(q))
    );
  }, [sessions, searchQuery]);

  const [showOverviewIdleAlert, setShowOverviewIdleAlert] = useState<boolean>(true);
  const [showOverviewFocusCheckin, setShowOverviewFocusCheckin] = useState<boolean>(true);

  const handleTodayClick = () => {
    if (onSelectDate) {
      onSelectDate(getLocalTodayString());
    }
  };

  // Goal progress calculation: find work_time goal, or first goal
  const workGoal = productivity?.goals?.find((g) => g.metric === 'work_time') || productivity?.goals?.[0];
  const goalProgress = workGoal
    ? workGoal.progress_pct
    : productivity && productivity.total_work_seconds > 0
      ? Math.min(100, Math.round((productivity.total_work_seconds / (8 * 3600)) * 100))
      : 0;
  const goalActual = workGoal ? workGoal.actual_label : productivity ? productivity.total_work_label : '0s';
  const goalTarget = workGoal ? workGoal.target_label : '8h';

  return (
    <div className="overview-container-rize">
      <div className="overview-split-layout">
        {/* Left / Central Column (~71% width matching Image 4) */}
        <div className="central-dashboard-col">
          {/* 1. Global Navigation Row matching Image 4 */}
          <div className="overview-global-nav-bar">
            {/* Quick Date Navigator matching Master Reference */}
            <div className="header-date-pill-group">
              <button
                type="button"
                className="btn-date-nav"
                onClick={() => {
                  if (onSelectDate && selectedDate) {
                    const [y, m, day] = selectedDate.split('-').map(Number);
                    const d = new Date(y, m - 1, day);
                    d.setDate(d.getDate() - 1);
                    onSelectDate(formatLocalDate(d));
                  }
                }}
                title="Previous day"
              >
                <ChevronLeftIcon size={14} />
              </button>
              <button
                type="button"
                className="btn-date-nav"
                onClick={() => {
                  if (onSelectDate && selectedDate) {
                    const [y, m, day] = selectedDate.split('-').map(Number);
                    const d = new Date(y, m - 1, day);
                    d.setDate(d.getDate() + 1);
                    onSelectDate(formatLocalDate(d));
                  }
                }}
                title="Next day"
              >
                <ChevronRightIcon size={14} />
              </button>
              <div className="header-date-calendar-pill">
                <CalendarIcon size={14} color="#8065FF" />
                <span className="header-date-text">
                  {selectedDate ? (selectedDate === '2026-10-23' ? 'Today, Oct 23, 2026' : `Today, ${selectedDate}`) : 'Today, Oct 23, 2026'}
                </span>
                <span style={{ fontSize: 10, color: '#8994A8', marginLeft: 4 }}>▾</span>
              </div>
              <button type="button" className="btn-today-pill" onClick={handleTodayClick}>
                Today
              </button>
            </div>

            {/* Search box & Filter matching Master Reference */}
            <div className="header-search-wrap">
              <div className="header-search-box">
                <SearchIcon size={14} color="var(--text-muted, #5A6679)" />
                <input
                  type="text"
                  className="header-search-input"
                  placeholder="Search apps, activities, websites..."
                  value={searchQuery}
                  onChange={(e) => onSearchChange && onSearchChange(e.target.value)}
                />
              </div>
              <button type="button" className="btn-filter-icon" title="Filter activities">
                <FilterIcon size={14} color="#8994A8" />
              </button>
            </div>

            {/* Top Right Action Pills */}
            <div className="header-actions-group">
              {onToggleTracking && (
                <button
                  type="button"
                  className={`tracker-pill-status ${isTracking ? 'active' : 'paused'}`}
                  onClick={onToggleTracking}
                  title={isTracking ? 'Click to pause tracking' : 'Click to resume tracking'}
                >
                  <span className={`status-pill-dot ${isTracking ? 'on' : 'off'}`} />
                  <span>{isTracking ? 'Tracking ON' : 'Paused'}</span>
                </button>
              )}

              {onLaunchNativeWidget && (
                <button
                  type="button"
                  className="btn-float-widget-pill"
                  onClick={onLaunchNativeWidget}
                  title="Float desktop focus widget"
                >
                  <WidgetIcon size={13} />
                  <span>Float</span>
                </button>
              )}

              {/* + Add Activity Button */}
              {onOpenManualActivity && (
                <button
                  type="button"
                  className="btn-new-block-cta"
                  onClick={onOpenManualActivity}
                  title="Manually record untracked or off-screen activity"
                  style={{
                    background: 'rgba(128, 101, 255, 0.15)',
                    border: '1px solid rgba(128, 101, 255, 0.4)',
                    color: '#C4B5FD',
                  }}
                >
                  <PlusIcon size={14} />
                  <span>+ Add Activity</span>
                </button>
              )}

              {/* + New Block CTA Button */}
              <button
                type="button"
                className="btn-new-block-cta"
                onClick={onOpenNewBlock}
                title="Plan a new focus time block"
              >
                <PlusIcon size={15} />
                <span>+ New Block</span>
              </button>
            </div>
          </div>

          {/* 2. Welcome Greeting Row */}
          <div className="overview-greeting-bar">
            <h2 className="overview-greeting-title">
              {(() => {
                const hour = new Date().getHours();
                const prefix = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
                return `${prefix}, ${userName || 'pant'} 👋`;
              })()}
            </h2>
            <p className="overview-greeting-subtitle">
              You&apos;ve tracked {productivity?.total_work_label || stats?.productive_work_label || '0s'} of productive work today
              {productivity?.total_tracked_label ? ` (${productivity.total_tracked_label} total screen time)` : stats?.active_label ? ` (${stats.active_label} total screen time)` : ''}.
              {' '}You&apos;re {Math.round(goalProgress)}% towards your daily goal.
            </p>
          </div>

          {/* 3. Four KPI Cards in 1 Row (Matching Image 4) */}
      <div className="kpi-cards-row">
        {/* Card 1: Focused Work */}
        <div className="kpi-card-rize">
          <div className="kpi-icon-circle purple">
            <TargetIcon size={20} color="var(--accent-purple, #8065FF)" />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Focused Work</span>
            <div className="kpi-value">{productivity ? productivity.focus_label : stats?.focus_label || '0s'}</div>
            <div className="kpi-comparison positive">
              <span>{productivity?.comparison?.focus_change_label ? `${productivity.comparison.focus_improved ? '▲ +' : '▼ -'}${productivity.comparison.focus_change_label} vs yesterday` : 'Deep work & study'}</span>
            </div>
          </div>
          <div className="kpi-sparkbars">
            <div className="sparkbar focus" style={{ height: '40%' }} />
            <div className="sparkbar focus" style={{ height: '65%' }} />
            <div className="sparkbar focus" style={{ height: '50%' }} />
            <div className="sparkbar focus" style={{ height: '85%' }} />
            <div className="sparkbar focus" style={{ height: '100%' }} />
            <div className="sparkbar focus" style={{ height: '70%' }} />
          </div>
        </div>

        {/* Card 2: Productive Work */}
        <div className="kpi-card-rize">
          <div className="kpi-icon-circle amber">
            <ClockIcon size={20} color="var(--status-warn, #FFB23E)" />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Productive Work</span>
            <div className="kpi-value">{productivity ? productivity.total_work_label : stats ? (stats.productive_work_label || stats.active_label) : '0s'}</div>
            <div className="kpi-comparison positive">
              <span>{productivity?.total_tracked_label ? `${productivity.total_tracked_label} screen time` : stats?.active_label ? `${stats.active_label} screen time` : 'Coding, study & tasks'}</span>
            </div>
          </div>
          <div className="kpi-sparkbars">
            <div className="sparkbar work" style={{ height: '55%' }} />
            <div className="sparkbar work" style={{ height: '70%' }} />
            <div className="sparkbar work" style={{ height: '60%' }} />
            <div className="sparkbar work" style={{ height: '90%' }} />
            <div className="sparkbar work" style={{ height: '95%' }} />
            <div className="sparkbar work" style={{ height: '80%' }} />
          </div>
        </div>

        {/* Card 3: Distraction Time */}
        <div className="kpi-card-rize">
          <div className="kpi-icon-circle coral">
            <GamepadIcon size={20} color="var(--status-distraction, #FA5275)" />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Distraction Time</span>
            <div className="kpi-value">{productivity ? productivity.distraction_label : '1h 18m'}</div>
            <div className="kpi-comparison neutral">
              <span>▼ -22% vs yesterday</span>
            </div>
          </div>
          <div className="kpi-sparkbars">
            <div className="sparkbar distraction" style={{ height: '75%' }} />
            <div className="sparkbar distraction" style={{ height: '50%' }} />
            <div className="sparkbar distraction" style={{ height: '40%' }} />
            <div className="sparkbar distraction" style={{ height: '60%' }} />
            <div className="sparkbar distraction" style={{ height: '35%' }} />
            <div className="sparkbar distraction" style={{ height: '25%' }} />
          </div>
        </div>

        {/* Card 4: Daily Goal Donut */}
        <div className="kpi-card-rize">
          <div className="kpi-donut-wrap">
            <svg width="52" height="52" viewBox="0 0 36 36">
              <path
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                fill="none"
                stroke="var(--bg-elevated, #1A2230)"
                strokeWidth="3.5"
              />
              <path
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                fill="none"
                stroke="var(--accent-cyan, #16D5E2)"
                strokeWidth="3.5"
                strokeDasharray={`${Math.min(100, Math.round(goalProgress))}, 100`}
                strokeLinecap="round"
              />
            </svg>
            <span className="kpi-donut-pct">{Math.round(goalProgress)}%</span>
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Daily Goal</span>
            <div className="kpi-value" style={{ fontSize: 20 }}>{Math.round(goalProgress)}%</div>
            <div className="kpi-comparison" style={{ color: 'var(--text-secondary)' }}>
              <span>{goalActual} / {goalTarget}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Middle Grid: Multi-lane Activity Timeline (Left) & Top Interruptors (Right) */}
      <div className="middle-grid-rize">
        {/* Left Panel: Redesigned Multi-lane Activity Timeline */}
        <ActivityTimeline
          sessions={filteredSessions}
          timeBlocks={timeBlocks}
          selectedDate={selectedDate || getLocalTodayString()}
          onSelectSession={onSelectSession}
          onOpenNewBlock={onOpenNewBlock}
        />

        {/* Right Panel: Top Interruptors (Matching Image A) */}
        <div className="card-panel interruptors-panel-rize">
          <div className="panel-header">
            <div className="panel-title-group">
              <h3 className="panel-title">Top Interruptors</h3>
              <InfoIcon size={14} className="info-icon-muted" />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>By Interruptions</span>
              <ChevronRightIcon size={14} className="chevron-icon-muted" />
            </div>
          </div>

          <div className="interruptors-rows-list">
            {(productivity?.top_interruptors && productivity.top_interruptors.length > 0) ? (
              productivity.top_interruptors.slice(0, 5).map((item) => {
                const maxLost = productivity.top_interruptors[0]?.lost_seconds || 1;
                const barPct = Math.max(12, Math.min(100, (item.lost_seconds / maxLost) * 100));
                return (
                  <div key={item.app} className="interruptor-row-item">
                    <div className="int-app-icon-wrap">
                      <AppIconHelper app={item.app} size={18} />
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                      <span className="int-app-title">{item.app.replace('.exe', '')}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{item.count} interruptions</span>
                    </div>
                    <div className="int-bar-container">
                      <div className="int-bar-fill" style={{ width: `${barPct}%` }} />
                    </div>
                    <span className="int-app-duration">{item.lost_label}</span>
                  </div>
                );
              })
            ) : (
              // Representative items matching Image A
              [
                { name: 'YouTube', count: '24 interruptions', duration: '1h 12m', bar: 100, icon: 'youtube' },
                { name: 'Discord', count: '16 interruptions', duration: '52m', bar: 72, icon: 'discord' },
                { name: 'Chrome', count: '10 interruptions', duration: '36m', bar: 50, icon: 'chrome.exe' },
                { name: 'WhatsApp', count: '8 interruptions', duration: '28m', bar: 38, icon: 'whatsapp' },
                { name: 'Instagram', count: '6 interruptions', duration: '21m', bar: 29, icon: 'instagram' },
              ].map((item) => (
                <div key={item.name} className="interruptor-row-item">
                  <div className="int-app-icon-wrap">
                    <AppIconHelper app={item.icon} size={18} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                    <span className="int-app-title">{item.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{item.count}</span>
                  </div>
                  <div className="int-bar-container">
                    <div className="int-bar-fill" style={{ width: `${item.bar}%` }} />
                  </div>
                  <span className="int-app-duration">{item.duration}</span>
                </div>
              ))
            )}
          </div>

          <button
            type="button"
            className="btn-detailed-analysis"
            onClick={onNavigateInsights}
            style={{ marginTop: 10 }}
          >
            View All
          </button>
        </div>
      </div>

      {/* 4. Bottom Grid: Daily AI Coach, Goals, Categories (Matching Image A) */}
      <div className="bottom-grid-rize">
        {/* Panel 1: Daily AI Coach (Matching Image A) */}
        <div className="card-panel ai-brief-panel-rize">
          <div className="panel-header">
            <div className="panel-title-group">
              <div className="panel-title-icon-circle">
                <SparklesIcon size={16} color="var(--accent-purple, #8065FF)" />
              </div>
              <h3 className="panel-title">Daily AI Coach</h3>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>
                {aiSummary?.generated_time_label ? `Generated ${aiSummary.generated_time_label}` : 'Generated 10:05 PM'}
              </span>
            </div>
            {onRefreshAiSummary && (
              <button
                type="button"
                className="btn-refresh-sparkle"
                onClick={onRefreshAiSummary}
                disabled={isAiRefreshing}
                title="Refresh AI analysis"
              >
                <RefreshIcon size={13} className={isAiRefreshing ? 'spin' : ''} />
                <span style={{ fontSize: 11, marginLeft: 4 }}>Refresh</span>
              </button>
            )}
          </div>

          {/* Headline Greeting */}
          <h4 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', margin: '4px 0 6px 0' }}>
            {aiSummary?.headline || 'Great progress today! 🔥'}
          </h4>

          <p className="ai-brief-narrative" style={{ fontSize: 13, lineHeight: 1.45, marginBottom: 12 }}>
            {aiSummary?.narrative ||
              'You completed 8h 12m of focused work, which is 12% more than yesterday. Your longest focus block was 2h 14m in the morning. Distractions were lower than usual.'}
          </p>

          {/* 3 Badged Highlight Cards: Key Win, Main Challenge, Suggestion (Matching Image A) */}
          <div className="ai-coach-highlights-list">
            {/* Key Win */}
            <div className="coach-highlight-card">
              <span className="coach-card-badge win">Key Win</span>
              <span className="coach-card-text">
                {aiSummary?.key_win || '2h 14m uninterrupted coding session in the morning.'}
              </span>
            </div>

            {/* Main Challenge */}
            <div className="coach-highlight-card">
              <span className="coach-card-badge challenge">Main Challenge</span>
              <span className="coach-card-text">
                {aiSummary?.main_challenge || 'Frequent YouTube checks in the afternoon (6 times).'}
              </span>
            </div>

            {/* Suggestion */}
            <div className="coach-highlight-card">
              <span className="coach-card-badge suggestion">Suggestion</span>
              <span className="coach-card-text">
                {aiSummary?.suggestion || 'Try a 45-minute focus block after lunch with notifications off.'}
              </span>
            </div>
          </div>

          <button
            type="button"
            className="btn-detailed-analysis"
            onClick={onNavigateInsights}
          >
            View Detailed Analysis →
          </button>
        </div>

        {/* Panel 2: Goals (Matching Image A) */}
        <div className="card-panel goals-panel-rize">
          <div className="panel-header">
            <div className="panel-title-group">
              <div className="panel-title-icon-circle">
                <TargetIcon size={16} color="var(--accent-purple, #8065FF)" />
              </div>
              <h3 className="panel-title">Goals</h3>
            </div>
            {onNavigateGoals && (
              <button type="button" className="panel-header-action-link" onClick={onNavigateGoals}>
                View All
              </button>
            )}
          </div>

          <div className="goals-items-list">
            {/* Goal 1: Daily Work Time */}
            <div className="goal-item-rize">
              <div className="goal-title-row">
                <span className="goal-name">Daily Work Time</span>
                <span className="goal-status-text">
                  {productivity?.goals?.[0]?.actual_label || '8h 12m'} / {productivity?.goals?.[0]?.target_label || '9h'}{'  '}
                  <strong>{Math.round(productivity?.goals?.[0]?.progress_pct || 87)}%</strong>
                </span>
              </div>
              <div className="goal-bar-track">
                <div
                  className="goal-bar-fill purple"
                  style={{ width: `${Math.min(100, productivity?.goals?.[0]?.progress_pct || 87)}%` }}
                />
              </div>
            </div>

            {/* Goal 2: Focus Time */}
            <div className="goal-item-rize">
              <div className="goal-title-row">
                <span className="goal-name">Focus Time</span>
                <span className="goal-status-text">
                  {productivity?.goals?.[1]?.actual_label || '6h 24m'} / {productivity?.goals?.[1]?.target_label || '6h'}{'  '}
                  <strong>{Math.round(productivity?.goals?.[1]?.progress_pct || 100)}%</strong>
                </span>
              </div>
              <div className="goal-bar-track">
                <div
                  className="goal-bar-fill green"
                  style={{ width: `${Math.min(100, productivity?.goals?.[1]?.progress_pct || 100)}%` }}
                />
              </div>
            </div>

            {/* Goal 3: Distraction Time */}
            <div className="goal-item-rize">
              <div className="goal-title-row">
                <span className="goal-name">Distraction Time</span>
                <span className="goal-status-text">
                  {productivity?.goals?.[2]?.actual_label || '1h 18m'} / {productivity?.goals?.[2]?.target_label || '2h'}{'  '}
                  <strong>{Math.round(productivity?.goals?.[2]?.progress_pct || 61)}%</strong>
                </span>
              </div>
              <div className="goal-bar-track">
                <div
                  className="goal-bar-fill"
                  style={{
                    width: `${Math.min(100, productivity?.goals?.[2]?.progress_pct || 61)}%`,
                    background: 'var(--status-distraction, #FA5275)',
                  }}
                />
              </div>
            </div>

            {/* Goal 4: Study Time */}
            <div className="goal-item-rize">
              <div className="goal-title-row">
                <span className="goal-name">Study Time</span>
                <span className="goal-status-text">
                  1h 2m / 2h{'  '}
                  <strong>51%</strong>
                </span>
              </div>
              <div className="goal-bar-track">
                <div
                  className="goal-bar-fill"
                  style={{ width: '51%', background: 'var(--status-warn, #FFB23E)' }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Panel 3: Categories (Matching Image A) */}
        <div className="card-panel categories-panel-rize">
          <div className="panel-header">
            <div className="panel-title-group">
              <div className="panel-title-icon-circle">
                <PieChartIcon size={16} color="var(--accent-purple, #8065FF)" />
              </div>
              <h3 className="panel-title">Categories</h3>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>Today ⌄</span>
              {onNavigateCategories && (
                <button type="button" className="panel-header-action-link" onClick={onNavigateCategories}>
                  Edit
                </button>
              )}
            </div>
          </div>

          <div className="categories-list-rize">
            {(productivity?.category_breakdown && productivity.category_breakdown.length > 0) ? (
              productivity.category_breakdown.slice(0, 6).map((cat) => (
                <div key={cat.name} className="cat-row-rize">
                  <div className="cat-name-col">
                    <span className="cat-circle-dot" style={{ backgroundColor: cat.color || '#8065FF' }} />
                    <span className="cat-text">{cat.name}</span>
                  </div>
                  <span className="cat-duration">{cat.label}</span>
                  <span className="cat-pct">{cat.pct}%</span>
                  <div className="cat-mini-bar-track">
                    <div
                      className="cat-mini-bar-fill"
                      style={{ width: `${Math.max(8, cat.pct)}%`, backgroundColor: cat.color || '#8065FF' }}
                    />
                  </div>
                </div>
              ))
            ) : (
              // Representative categories matching Image A
              [
                { name: 'Development', duration: '4h 32m', pct: 45, color: '#35D68A' },
                { name: 'Entertainment', duration: '1h 18m', pct: 13, color: '#FA5275' },
                { name: 'Communication', duration: '1h 4m', pct: 10, color: '#8065FF' },
                { name: 'Study', duration: '1h 2m', pct: 10, color: '#FFB23E' },
                { name: 'Gaming', duration: '58m', pct: 9, color: '#35D68A' },
                { name: 'Other', duration: '1h 18m', pct: 13, color: '#93C5FD' },
              ].map((cat) => (
                <div key={cat.name} className="cat-row-rize">
                  <div className="cat-name-col">
                    <span className="cat-circle-dot" style={{ backgroundColor: cat.color }} />
                    <span className="cat-text">{cat.name}</span>
                  </div>
                  <span className="cat-duration">{cat.duration}</span>
                  <span className="cat-pct">{cat.pct}%</span>
                  <div className="cat-mini-bar-track">
                    <div
                      className="cat-mini-bar-fill"
                      style={{ width: `${cat.pct}%`, backgroundColor: cat.color }}
                    />
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* 5. Bottom Alerts Row (Matching Image 3) */}
      {(showOverviewIdleAlert || showOverviewFocusCheckin) && (
        <div className="overview-bottom-alerts-row">
          {/* Left Card: Idle Alert */}
          {showOverviewIdleAlert && (
            <div className="overview-alert-card idle">
              <div className="alert-card-top-row">
                <div className="alert-icon-circle amber">
                  <CoffeeIcon size={18} color="#FFB23E" />
                </div>
                <div className="alert-card-text-col">
                  <div className="alert-card-heading-row">
                    <span className="alert-card-title">Idle Alert</span>
                  </div>
                  <p className="alert-card-body">
                    Looks like you&apos;ve stepped away. We detected 3 minutes of inactivity. What would you like to do?
                  </p>
                </div>
                <button
                  type="button"
                  className="alert-card-close-btn"
                  onClick={() => setShowOverviewIdleAlert(false)}
                  title="Dismiss alert"
                >
                  <CloseIcon size={14} />
                </button>
              </div>

              <div className="alert-card-buttons-row">
                <button
                  type="button"
                  className="btn-alert-purple"
                  onClick={() => setShowOverviewIdleAlert(false)}
                >
                  I&apos;m back
                </button>
                <button
                  type="button"
                  className="btn-alert-dark"
                  onClick={() => setShowOverviewIdleAlert(false)}
                >
                  Stay idle
                </button>
                <button
                  type="button"
                  className="btn-alert-dark"
                  onClick={() => setShowOverviewIdleAlert(false)}
                >
                  Remind me later
                </button>
              </div>
            </div>
          )}

          {/* Right Card: Focus Check-in */}
          {showOverviewFocusCheckin && (
            <div className="overview-alert-card focus">
              <div className="alert-card-top-row">
                <div className="alert-icon-circle purple">
                  <TargetIcon size={18} color="#8065FF" />
                </div>
                <div className="alert-card-text-col">
                  <div className="alert-card-heading-row">
                    <span className="alert-card-title">Focus Check-in</span>
                    <span className="alert-card-timestamp">21:36</span>
                  </div>
                  <p className="alert-card-body">
                    Your current schedule is DSA Practice, but your recent activity looks unrelated (YouTube). Want to return to your planned task?
                  </p>
                </div>
                <button
                  type="button"
                  className="alert-card-close-btn"
                  onClick={() => setShowOverviewFocusCheckin(false)}
                  title="Dismiss alert"
                >
                  <CloseIcon size={14} />
                </button>
              </div>

              {/* Planned task badge */}
              <div className="alert-card-planned-box">
                <span className="planned-icon">&lt;/&gt;</span>
                <span className="planned-lbl">Planned task:</span>
                <span className="planned-task-name">DSA Practice • 9:30 – 11:30</span>
              </div>

              <div className="alert-card-buttons-row">
                <button
                  type="button"
                  className="btn-alert-purple"
                  onClick={() => setShowOverviewFocusCheckin(false)}
                >
                  Return to planned task
                </button>
                <button
                  type="button"
                  className="btn-alert-dark"
                  onClick={() => setShowOverviewFocusCheckin(false)}
                >
                  Continue anyway
                </button>
                <button
                  type="button"
                  className="btn-alert-dark"
                  onClick={() => setShowOverviewFocusCheckin(false)}
                >
                  Snooze 15 min ▾
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>

        {/* Right Dashboard Column (~29% width matching Image A) */}
        <div className="right-dashboard-col">
          {/* Floating Focus Widget Card */}
          <RightWidgetCard
            isTracking={Boolean(isTracking)}
            onToggleTracking={onToggleTracking || (() => {})}
            activeTask={activeTask || null}
            productivity={productivity}
            timeBlocks={timeBlocks}
            onLaunchNativeWidget={onLaunchNativeWidget || (() => {})}
            categories={categories}
            onTaskAssigned={onBlockCreated}
          />

          {/* Plan Time Block Embedded Card */}
          <PlanTimeBlockCard
            categories={categories}
            selectedDate={selectedDate || ''}
            onBlockCreated={onBlockCreated || (() => {})}
          />

          {/* Today's Timeline Compact List */}
          <TodayTimelineCard
            sessions={sessions}
            onSelectSession={onSelectSession}
          />
        </div>
      </div>
    </div>
  );
};
