import React from 'react';
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  RefreshIcon,
  WidgetIcon,
} from './Icons';
import { LiveDuration } from './LiveDuration';

interface TopbarProps {
  selectedDate: string;
  onDateChange: (newDate: string) => void;
  onRefresh: (refreshAi?: boolean) => void;
  isLoading: boolean;
  activeDates: string[];
  isTracking: boolean;
  isToggling: boolean;
  onToggleTracking: () => void;
  onLaunchWidget?: () => void;
  activeTask?: import('../types').ActiveTaskModel | null;
}

function formatDateHeading(dateStr: string): string {
  try {
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
      return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
    }
  } catch {
    // fallback
  }
  return dateStr;
}

function formatStartTime(isoStr?: string): string {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  } catch {
    return '';
  }
}

export const Topbar: React.FC<TopbarProps> = ({
  selectedDate,
  onDateChange,
  onRefresh,
  isLoading,
  isTracking,
  isToggling,
  onToggleTracking,
  onLaunchWidget,
  activeTask,
}) => {
  const handlePrevDay = () => {
    const parts = selectedDate.split('-').map(Number);
    const d = new Date(parts[0], parts[1] - 1, parts[2]);
    d.setDate(d.getDate() - 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    onDateChange(`${y}-${m}-${day}`);
  };

  const handleNextDay = () => {
    const parts = selectedDate.split('-').map(Number);
    const d = new Date(parts[0], parts[1] - 1, parts[2]);
    d.setDate(d.getDate() + 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    onDateChange(`${y}-${m}-${day}`);
  };

  const formattedDate = formatDateHeading(selectedDate);
  const startTimeStr = activeTask ? formatStartTime(activeTask.start_time) : '';

  return (
    <header className="page-header-rize">
      {/* Left: Date headline and tracking status subtitle matching Image A */}
      <div className="header-headline-col">
        <div className="date-heading-row">
          <h1 className="page-date-title">{formattedDate}</h1>
          <div className="date-nav-chevrons">
            <button
              type="button"
              className="btn-chevron-round"
              onClick={handlePrevDay}
              title="Previous day"
              disabled={isLoading}
            >
              <ChevronLeftIcon size={14} />
            </button>
            <button
              type="button"
              className="btn-chevron-round"
              onClick={handleNextDay}
              title="Next day"
              disabled={isLoading}
            >
              <ChevronRightIcon size={14} />
            </button>
          </div>
        </div>

        <div className="header-status-sub">
          <span className={`status-dot-inline ${isTracking ? 'active' : 'paused'}`} />
          <span className="status-sub-text">
            {isTracking ? (
              <>
                <strong>Tracking active</strong>
                {startTimeStr && ` • Started at ${startTimeStr}`}
                {activeTask && (
                  <>
                    {' • '}
                    <LiveDuration startTime={activeTask.start_time} isLive={true} />
                    {' elapsed'}
                  </>
                )}
              </>
            ) : (
              <span>Tracking paused • Click toggle to resume recording</span>
            )}
          </span>
        </div>
      </div>

      {/* Right: Quick Controls */}
      <div className="header-actions-row">
        {onLaunchWidget && (
          <button
            type="button"
            className="btn-widget-pill"
            onClick={onLaunchWidget}
            title="Open independent, floating always-on-top desktop widget"
          >
            <WidgetIcon size={14} />
            <span>Float Widget</span>
          </button>
        )}

        {/* Tracking ON / OFF Toggle */}
        <button
          type="button"
          className={`tracker-toggle-btn ${isTracking ? 'tracking-on' : 'tracking-off'}`}
          onClick={onToggleTracking}
          disabled={isToggling}
          title={isTracking ? 'Click to pause tracking' : 'Click to start tracking'}
        >
          <span className={`status-orb ${isTracking ? 'orb-on' : 'orb-off'}`} />
          <span>{isToggling ? 'Updating…' : isTracking ? 'Tracking ON' : 'Tracking OFF'}</span>
          <span className={`toggle-switch-track ${isTracking ? 'track-on' : ''}`}>
            <span className={`toggle-switch-thumb ${isTracking ? 'thumb-on' : ''}`} />
          </span>
        </button>

        <button
          className="btn-icon-refresh"
          onClick={() => onRefresh(false)}
          title="Reload data"
          disabled={isLoading}
        >
          <RefreshIcon
            size={14}
            style={{
              animation: isLoading ? 'spin 1s linear infinite' : 'none',
            }}
          />
        </button>
      </div>
    </header>
  );
};
