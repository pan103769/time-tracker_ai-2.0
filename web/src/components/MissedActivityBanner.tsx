import React from 'react';
import type { RecoveryGapModel } from '../types';
import { ClockIcon } from './Icons';

interface MissedActivityBannerProps {
  gap: RecoveryGapModel | null;
  onOpenManualEntry: (gap: RecoveryGapModel) => void;
  onSkip: (gapId: number) => void;
  onSnooze: (gapId: number) => void;
}

export const MissedActivityBanner: React.FC<MissedActivityBannerProps> = ({
  gap,
  onOpenManualEntry,
  onSkip,
  onSnooze,
}) => {
  if (!gap) return null;

  // Format time for prompt with relative date context when on previous days
  const formatRelativeTime = (isoString: string): string => {
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
        const dateStr = d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
        return `${dateStr} at ${timeStr}`;
      }
    } catch {
      return isoString.slice(11, 16);
    }
  };

  const endTimeLabel = formatRelativeTime(gap.gap_start);
  const gapMins = Math.round(gap.duration_seconds / 60);

  return (
    <div
      className="missed-activity-banner animate-slide-down"
      style={{
        background: 'linear-gradient(135deg, rgba(20, 28, 48, 0.95), rgba(15, 20, 32, 0.95))',
        border: '1px solid rgba(0, 240, 255, 0.35)',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5), 0 0 15px rgba(0, 240, 255, 0.15)',
        backdropFilter: 'blur(16px)',
        borderRadius: 14,
        padding: '12px 18px',
        marginBottom: 20,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, minWidth: 280 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: 'rgba(0, 240, 255, 0.15)',
            border: '1px solid rgba(0, 240, 255, 0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <ClockIcon size={18} color="#00F0FF" />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#FFFFFF' }}>
              Welcome back
            </span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                background: 'rgba(0, 240, 255, 0.2)',
                color: '#00F0FF',
                padding: '2px 6px',
                borderRadius: 8,
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              Missed Activity
            </span>
          </div>
          <p style={{ margin: '3px 0 0 0', fontSize: 12, color: '#A0AEC0', lineHeight: 1.4 }}>
            Your last recorded activity ended at <strong style={{ color: '#E2E8F0' }}>{endTimeLabel}</strong> (inactive for{' '}
            <span style={{ color: '#00F0FF', fontWeight: 600 }}>{gapMins} minutes</span>). Were you doing anything you&apos;d like to add?
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <button
          type="button"
          onClick={() => onOpenManualEntry(gap)}
          className="btn-alert-primary"
          style={{
            padding: '7px 14px',
            fontSize: 12,
            fontWeight: 600,
            background: 'linear-gradient(135deg, #00F0FF, #8065FF)',
            color: '#0B0F19',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          Add Activity
        </button>
        <button
          type="button"
          onClick={() => onSkip(gap.id)}
          className="btn-alert-ghost"
          style={{
            padding: '7px 12px',
            fontSize: 12,
            background: 'rgba(255, 255, 255, 0.05)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            color: '#CBD5E1',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          Skip
        </button>
        <button
          type="button"
          onClick={() => onSnooze(gap.id)}
          className="btn-alert-ghost"
          style={{
            padding: '7px 12px',
            fontSize: 12,
            background: 'transparent',
            border: 'none',
            color: '#8994A8',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          Remind Later
        </button>
      </div>
    </div>
  );
};
