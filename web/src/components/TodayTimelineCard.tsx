import React, { useState } from 'react';
import type { SessionModel } from '../types';
import { AppIconHelper, ClockIcon } from './Icons';

interface TodayTimelineCardProps {
  sessions: SessionModel[];
  onSelectSession: (s: SessionModel) => void;
}

export const TodayTimelineCard: React.FC<TodayTimelineCardProps> = ({
  sessions,
  onSelectSession,
}) => {
  const [viewMode, setViewMode] = useState<'detailed' | 'summary'>('detailed');

  const formatTimeOnly = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  const formatDur = (sec: number) => {
    const s = Math.round(sec);
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    if (h > 0) return `${h}h ${m % 60}m`;
    if (m > 0) return `${m}m`;
    return `${s}s`;
  };

  // Sort and filter sessions
  const displaySessions = (viewMode === 'summary'
    ? sessions.filter((s) => s.duration_seconds >= 120 && s.kind !== 'idle')
    : sessions
  ).slice(0, 8);

  return (
    <div className="card-panel today-timeline-card-rize">
      <div className="panel-header" style={{ marginBottom: 12 }}>
        <div className="panel-title-group">
          <ClockIcon size={16} color="var(--accent-purple, #8065FF)" />
          <h3 className="panel-title">Today&apos;s Timeline</h3>
        </div>

        <div className="timeline-view-switch">
          <span className="view-switch-lbl">View:</span>
          <button
            type="button"
            className={`view-mode-pill ${viewMode === 'detailed' ? 'active' : ''}`}
            onClick={() => setViewMode('detailed')}
          >
            Detailed
          </button>
          <span className="switch-sep">|</span>
          <button
            type="button"
            className={`view-mode-pill ${viewMode === 'summary' ? 'active' : ''}`}
            onClick={() => setViewMode('summary')}
          >
            Summary
          </button>
        </div>
      </div>

      <div className="today-timeline-list">
        {displaySessions.length > 0 ? (
          displaySessions.map((s) => {
            const timeRange = `${formatTimeOnly(s.start)} - ${formatTimeOnly(s.end)}`;
            const isIdle = s.kind === 'idle';
            const catName = s.category_name || (isIdle ? 'Break' : 'Development');
            const catColor = s.category_color || (isIdle ? '#16D5E2' : '#8065FF');

            return (
              <div
                key={s.session_key}
                className="today-timeline-row"
                onClick={() => onSelectSession(s)}
                title="Click to view details"
              >
                <span className="row-time">{timeRange}</span>

                <div className="row-app-info">
                  <AppIconHelper app={s.app} size={13} />
                  <span className="row-app-title">
                    {s.app.replace('.exe', '')} {s.title && s.title !== s.app ? `- ${s.title.slice(0, 18)}` : ''}
                  </span>
                </div>

                <div className="row-cat-pill">
                  <span className="cat-dot" style={{ backgroundColor: catColor }} />
                  <span className="cat-lbl">{catName}</span>
                </div>

                <span className="row-duration">{formatDur(s.duration_seconds)}</span>
              </div>
            );
          })
        ) : (
          <div style={{ padding: '16px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            No activity sessions recorded today yet.
          </div>
        )}
      </div>
    </div>
  );
};

