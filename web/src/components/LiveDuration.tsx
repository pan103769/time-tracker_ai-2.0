import React, { useEffect, useState } from 'react';

/**
 * Format total elapsed seconds into human-readable duration:
 * - >= 1 hour: 1h 05m 23s
 * - >= 1 min:  1m 23s, 1m 24s, 1m 25s (matches requested format)
 * - < 1 min:   23s
 */
export function formatLiveDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const secStr = sec < 10 ? `0${sec}` : `${sec}`;

  if (h > 0) {
    const mStr = m < 10 ? `0${m}` : `${m}`;
    return `${h}h ${mStr}m ${secStr}s`;
  }
  if (m > 0) {
    return `${m}m ${secStr}s`;
  }
  return `${sec}s`;
}

interface LiveDurationProps {
  startTime: string;            // ISO-8601 start timestamp
  endTime?: string | null;      // ISO-8601 end timestamp (optional)
  isLive?: boolean;             // True when activity is ongoing
  fallbackLabel?: string;       // Fallback label if not live and no endTime
  className?: string;
  style?: React.CSSProperties;
}

/**
 * LiveDuration — An isolated, lightweight component that advances every second
 * only when `isLive` is true. Calculates elapsed time directly from `startTime`
 * and system clock (preventing timer drift). Freezes on `endTime` when `isLive` is false.
 * Only re-renders its own text element without triggering dashboard reloads.
 */
export const LiveDuration: React.FC<LiveDurationProps> = ({
  startTime,
  endTime,
  isLive = false,
  fallbackLabel,
  className,
  style,
}) => {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isLive) return;

    // 1-second interval to update current time
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 1000);

    // Immediately re-sync on tab focus / window visibility (survives tab switches/minimization)
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        setNow(Date.now());
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isLive, startTime]);

  let elapsedSeconds: number;

  if (isLive) {
    const startMs = new Date(startTime).getTime();
    if (isNaN(startMs)) {
      return <span className={className} style={style}>{fallbackLabel || '0s'}</span>;
    }
    elapsedSeconds = Math.max(0, Math.floor((now - startMs) / 1000));
  } else if (endTime) {
    const startMs = new Date(startTime).getTime();
    const endMs = new Date(endTime).getTime();
    if (isNaN(startMs) || isNaN(endMs)) {
      return <span className={className} style={style}>{fallbackLabel || '0s'}</span>;
    }
    elapsedSeconds = Math.max(0, Math.floor((endMs - startMs) / 1000));
  } else if (fallbackLabel) {
    return <span className={className} style={style}>{fallbackLabel}</span>;
  } else {
    elapsedSeconds = 0;
  }

  return (
    <span className={className} style={style}>
      {formatLiveDuration(elapsedSeconds)}
    </span>
  );
};

