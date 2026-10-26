/**
 * activityTimelineEngine.ts — High-Performance Activity Timeline Data & Geometry Engine
 *
 * Implements:
 * 1. Time-to-Pixel Coordinate Converter: Exact, shared mathematical mapping across all rows.
 *    Supports left/right clipping detection and visible duration calculations.
 * 2. Primary Activities Row: Groups meaningful parent activities (5m/10m threshold, task-matching).
 * 3. Detailed Apps Row: Fine-grained app sessions with excursion debounce & dense switch aggregation (+N events).
 * 4. Dedicated Lanes: Continuous coalesced intervals for Focus, Breaks, Distractions, and Idle.
 * 5. Strict Data Preservation: Presentation layer only; zero alteration of underlying records.
 */

import type { SessionModel, TimeBlockModel } from '../types';

export type TaskMatchStatus = 'match' | 'mismatch' | 'neutral' | 'unknown';

export interface ChildAppEvent {
  id: string;
  app: string;
  title: string;
  start: string;
  end: string;
  duration_seconds: number;
  duration_label: string;
  url?: string | null;
  category_name?: string | null;
  category_color?: string | null;
  category_type?: string | null;
  is_interruption?: boolean;
  original_session?: SessionModel;
}

export interface ActivityBlockModel {
  id: string;
  title: string;
  subtitle?: string;
  category_name: string;
  category_color: string;
  category_type: 'focus' | 'work' | 'personal' | 'distraction' | 'break';
  start: string; // ISO
  end: string;   // ISO
  start_sec: number; // Seconds from midnight
  end_sec: number;
  duration_seconds: number;
  duration_label: string;
  task_match_status: TaskMatchStatus;
  planned_task_title?: string;
  is_explicit_task: boolean;
  underlying_sessions: SessionModel[];
  child_events: ChildAppEvent[];
  app_breakdown: { app: string; seconds: number; pct: number; label: string; color?: string }[];
  interruption_count: number;
}

export interface AppBlockModel {
  id: string;
  app: string;
  title: string;
  start: string;
  end: string;
  start_sec: number;
  end_sec: number;
  duration_seconds: number;
  duration_label: string;
  category_color: string;
  category_type: string;
  is_dense_cluster: boolean;
  switch_count: number;
  child_events: ChildAppEvent[];
  original_session?: SessionModel;
}

export interface GenericLaneBlockModel {
  id: string;
  label: string;
  kind: 'focus' | 'break' | 'distraction' | 'idle';
  color: string;
  start: string;
  end: string;
  start_sec: number;
  end_sec: number;
  duration_seconds: number;
  duration_label: string;
  reason?: string;
  associated_app?: string;
  sub_sessions?: SessionModel[];
  original_session?: SessionModel;
}

export interface PositionResult {
  leftPct: number;
  widthPct: number;
  isVisible: boolean;
  isClippedLeft: boolean;
  isClippedRight: boolean;
  visibleDurationSec: number;
}

export interface TimeToPositionHelper {
  (startSec: number, endSec: number): PositionResult;
}

export interface TimelineRenderModel {
  minHour: number;
  maxHour: number;
  startSec: number;
  endSec: number;
  totalSpanSec: number;
  hourMarkers: { hour: number; label: string; leftPct: number }[];
  activities: ActivityBlockModel[];
  apps: AppBlockModel[];
  focus: GenericLaneBlockModel[];
  breaks: GenericLaneBlockModel[];
  distractions: GenericLaneBlockModel[];
  idle: GenericLaneBlockModel[];
}

/**
 * Format duration into human readable string e.g. "1h 24m", "42m", "15s"
 */
export function formatDurationHuman(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec > 0 ? `${sec}s` : ''}`.trim();
  return `${sec}s`;
}

/**
 * Convert ISO string to seconds within the given local calendar day.
 * If selectedDateStr (YYYY-MM-DD) is provided:
 * - Timestamps before the local day start return 0
 * - Timestamps at or after the local day end (e.g. 24:00 / midnight next day) return 86400
 * - Midnight (00:00:00) returns 0, 24:00:00 returns 86400
 */
export function isoToSecondsInDay(isoStr: string, selectedDateStr?: string): number {
  if (!isoStr) return 0;
  try {
    const d = new Date(isoStr);
    if (!selectedDateStr) {
      return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
    }
    const [y, m, day] = selectedDateStr.split('-').map(Number);
    const dayStart = new Date(y, m - 1, day, 0, 0, 0, 0).getTime();
    const dayEnd = dayStart + 86400 * 1000;
    const t = d.getTime();

    if (t <= dayStart) return 0;
    if (t >= dayEnd) return 86400;
    return Math.max(0, Math.min(86400, Math.round((t - dayStart) / 1000)));
  } catch {
    return 0;
  }
}

/**
 * Convert ISO string to seconds from local midnight (backward-compatible)
 */
export function isoToSecondsFromMidnight(isoStr: string): number {
  return isoToSecondsInDay(isoStr);
}

/**
 * Create a shared time-to-pixel coordinate converter across all rows
 */
export function createTimePositionHelper(
  windowStartSec: number,
  windowEndSec: number,
  minWidthPct: number = 0.5
): TimeToPositionHelper {
  const totalSpan = Math.max(1, windowEndSec - windowStartSec);

  return (startSec: number, endSec: number): PositionResult => {
    // If completely outside the visible window
    if (endSec <= windowStartSec || startSec >= windowEndSec) {
      return {
        leftPct: 0,
        widthPct: 0,
        isVisible: false,
        isClippedLeft: false,
        isClippedRight: false,
        visibleDurationSec: 0,
      };
    }

    const isClippedLeft = startSec < windowStartSec;
    const isClippedRight = endSec > windowEndSec;

    const clampedStart = Math.max(windowStartSec, Math.min(windowEndSec, startSec));
    const clampedEnd = Math.max(windowStartSec, Math.min(windowEndSec, endSec));

    const offsetSec = clampedStart - windowStartSec;
    const durSec = Math.max(1, clampedEnd - clampedStart);

    const leftPct = Math.max(0, Math.min(100, (offsetSec / totalSpan) * 100));
    const rawWidthPct = (durSec / totalSpan) * 100;
    const widthPct = Math.max(minWidthPct, Math.min(100 - leftPct, rawWidthPct));

    return {
      leftPct,
      widthPct,
      isVisible: true,
      isClippedLeft,
      isClippedRight,
      visibleDurationSec: durSec,
    };
  };
}

/**
 * Derive meaningful activity label from app and window title.
 * Never returns generic "Other / Uncategorized" when application or title has identifiable context.
 */
export function inferActivityTitle(app: string, title: string, categoryName?: string | null): string {
  const a = (app || '').toLowerCase();
  const t = (title || '').toLowerCase();
  const c = (categoryName || '').toLowerCase();

  // If user or database has a genuine customized category that is not generic
  if (categoryName && !c.includes('other') && !c.includes('uncategorized') && !c.includes('general') && !c.includes('needs review')) {
    return categoryName;
  }

  // Python & Development
  if (a.includes('pythonw') || a.includes('python')) {
    return 'Python Application & Development';
  }
  if (a.includes('code') || a.includes('cursor') || a.includes('pycharm')) {
    if (t.includes('dsa') || t.includes('leetcode')) return 'DSA Practice';
    if (t.includes('.py') || t.includes('python')) return 'Python Development';
    return 'Software Development (VS Code)';
  }
  if (a.includes('terminal') || a.includes('powershell') || a.includes('cmd')) {
    return 'Terminal & System CLI';
  }

  // Reading & Document Study
  if (t.includes('.pdf') || t.includes('book') || t.includes('seduction') || t.includes('reader')) {
    return 'Reading & Document Study';
  }

  // Entertainment & Media
  if (t.includes('netflix') || a.includes('netflix')) {
    return 'Entertainment (Netflix)';
  }
  if (t.includes('youtube') || a.includes('youtube')) {
    return 'Video & Media (YouTube)';
  }
  if (t.includes('chess') || a.includes('chess')) {
    return 'Gaming (Chess.com)';
  }
  if (a.includes('spotify')) {
    return 'Music & Audio (Spotify)';
  }

  // Web Browsing & Research
  if (a.includes('chrome') || a.includes('edge') || a.includes('browser')) {
    if (t.includes('github') || t.includes('stackoverflow') || t.includes('docs') || t.includes('api')) {
      return 'Technical Research';
    }
    if (t.includes('moodle') || t.includes('log in') || t.includes('portal') || t.includes('sign in')) {
      return 'Study Portal & Authentication';
    }
    if (t.includes('dashboard') || t.includes('time tracker')) {
      return 'Time Tracker AI Dashboard';
    }
    return 'Web Browsing & Research';
  }

  // System & Utilities
  if (a.includes('snipping') || a.includes('explorer') || a.includes('host') || a.includes('widget')) {
    return 'System & Utilities';
  }

  // Fallback cleanly formatted app name
  return app ? app.replace('.exe', '') : 'General Activity';
}

/**
 * Determine task match status between observed activity and scheduled time block
 */
export function evaluateTaskMatch(
  activityTitle: string,
  observedApp: string,
  timeBlock?: TimeBlockModel
): TaskMatchStatus {
  if (!timeBlock) return 'unknown';

  const planned = (timeBlock.title || '').toLowerCase();
  const act = activityTitle.toLowerCase();
  const app = observedApp.toLowerCase();

  // If observed is clearly a distraction during planned work
  if (
    app.includes('netflix') ||
    app.includes('valorant') ||
    app.includes('tiktok') ||
    app.includes('reddit') ||
    act.includes('netflix') ||
    act.includes('gaming')
  ) {
    return 'mismatch';
  }

  // If title or app matches planned keywords
  if (
    act.includes(planned) ||
    planned.includes(act) ||
    (planned.includes('code') && (app.includes('code') || app.includes('cursor') || app.includes('python'))) ||
    (planned.includes('python') && (app.includes('python') || app.includes('code'))) ||
    (planned.includes('dsa') && (app.includes('code') || app.includes('chrome'))) ||
    (planned.includes('study') && (app.includes('pdf') || app.includes('chrome') || app.includes('edge'))) ||
    (planned.includes('project') && (app.includes('code') || app.includes('terminal')))
  ) {
    return 'match';
  }

  return 'neutral';
}

/**
 * Helper to coalesce raw category sessions into continuous spans
 */
function coalesceCategoryIntervals(
  items: SessionModel[],
  kind: 'focus' | 'break' | 'distraction' | 'idle',
  color: string,
  label: string,
  maxGapSec: number = 120,
  selectedDate?: string
): GenericLaneBlockModel[] {
  const result: GenericLaneBlockModel[] = [];
  const toSec = (iso: string) => isoToSecondsInDay(iso, selectedDate);
  let i = 0;
  const n = items.length;

  while (i < n) {
    const cur = items[i];
    let j = i + 1;
    let endIso = cur.end;
    let totalSec = cur.duration_seconds;
    const subSessions = [cur];

    while (j < n) {
      const next = items[j];
      const gap = toSec(next.start) - toSec(endIso);
      if (gap > maxGapSec) break;
      endIso = next.end;
      totalSec += next.duration_seconds;
      subSessions.push(next);
      j++;
    }

    result.push({
      id: `${kind}_${i}_${cur.session_key}`,
      label: cur.title ? `${label}: ${cur.title.slice(0, 30)}` : label,
      kind,
      color,
      start: cur.start,
      end: endIso,
      start_sec: toSec(cur.start),
      end_sec: toSec(endIso),
      duration_seconds: totalSec,
      duration_label: formatDurationHuman(totalSec),
      associated_app: cur.app,
      reason: cur.title,
      sub_sessions: subSessions,
      original_session: cur,
    });

    i = j;
  }

  return result;
}

/**
 * Main Data Transformation Pipeline
 * Pure, deterministic function that transforms raw sessions and time blocks into
 * the 6-row timeline render hierarchy with shared geometry and accurate time coordinates.
 */
export function processTimelineData(
  sessions: SessionModel[],
  timeBlocks: TimeBlockModel[] = [],
  _minDurationSeconds: number = 600, // 10 min default (600s) or 5 min (300s)
  maxGapSeconds: number = 180, // 3 min gap coalesce
  zoomMode: 'day' | '4h' | '2h' = '4h',
  startHour: number = 0,
  viewMode: 'apps' | 'categories' = 'apps',
  selectedDate?: string
): TimelineRenderModel {
  const toSec = (iso: string) => isoToSecondsInDay(iso, selectedDate);

  // Filter valid sessions sorted by start; exclude internal widget utility processes
  const isWidgetSelf = (s: SessionModel) => {
    const a = (s.app || '').toLowerCase();
    const t = (s.title || '').toLowerCase();
    return (a.includes('pythonw') || a.includes('python')) && (t === 'tk' || t.includes('widget'));
  };

  const validSessions = sessions
    .filter((s) => s.start && s.end && (s.duration_seconds || 0) > 0 && !isWidgetSelf(s))
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());

  // 1. Establish time range window (§1)
  // Day: 00:00 to 24:00 full day
  // 4h: 4-hour window
  // 2h: 2-hour window
  let minHour = 0;
  let maxHour = 24;

  if (zoomMode === 'day') {
    minHour = 0;
    maxHour = 24;
  } else if (zoomMode === '4h') {
    minHour = Math.max(0, Math.min(20, Math.round(startHour * 2) / 2));
    maxHour = minHour + 4;
  } else if (zoomMode === '2h') {
    minHour = Math.max(0, Math.min(22, Math.round(startHour * 2) / 2));
    maxHour = minHour + 2;
  }

  const startSec = Math.round(minHour * 3600);
  const endSec = Math.round(maxHour * 3600);
  const totalSpanSec = endSec - startSec;

  // Generate evenly distributed hour marks & vertical guidelines (§4)
  const hourMarkers: { hour: number; label: string; leftPct: number }[] = [];
  if (zoomMode === 'day') {
    // 2-hour increments across 24h day (13 ticks)
    for (let h = 0; h <= 24; h += 2) {
      const pct = (h / 24) * 100;
      let label = '';
      if (h === 0 || h === 24) {
        label = '12 AM';
      } else if (h === 12) {
        label = '12 PM';
      } else {
        label = `${h % 12} ${h >= 12 ? 'PM' : 'AM'}`;
      }
      hourMarkers.push({
        hour: h,
        label,
        leftPct: pct,
      });
    }
  } else if (zoomMode === '4h') {
    // 1-hour increments across 4h window (5 ticks)
    for (let offset = 0; offset <= 4; offset += 1) {
      const h = minHour + offset;
      const pct = (offset / 4) * 100;
      const wholeH = Math.floor(h);
      const fracM = Math.round((h - wholeH) * 60);
      const ampm = (wholeH >= 12 && wholeH < 24) ? 'PM' : 'AM';
      const dispH = wholeH % 12 === 0 ? 12 : wholeH % 12;
      let label = '';
      if (h === 0 || h === 24) {
        label = '12 AM';
      } else if (h === 12) {
        label = '12 PM';
      } else if (fracM === 0) {
        label = `${dispH} ${ampm}`;
      } else {
        label = `${dispH}:${fracM.toString().padStart(2, '0')}`;
      }
      hourMarkers.push({
        hour: h,
        label,
        leftPct: pct,
      });
    }
  } else {
    // 2h mode: 30-minute intervals across 2h window (5 ticks)
    for (let m = 0; m <= 120; m += 30) {
      const pct = (m / 120) * 100;
      const totalMin = Math.round(minHour * 60) + m;
      const h = Math.floor(totalMin / 60);
      const min = totalMin % 60;
      const ampm = (h >= 12 && h < 24) ? 'PM' : 'AM';
      const dispH = h % 12 === 0 ? 12 : h % 12;
      const label = min === 0 ? `${dispH} ${ampm}` : `${dispH}:${min.toString().padStart(2, '0')}`;
      hourMarkers.push({
        hour: h + min / 60,
        label,
        leftPct: pct,
      });
    }
  }

  // -------------------------------------------------------------------------
  // ROW 1: PRIMARY ACTIVITIES ROW (§3)
  // Coalesces consecutive compatible sessions, absorbs micro-excursions (< 90s),
  // respects minimum grouping threshold, and derives clear activity titles.
  // -------------------------------------------------------------------------
  const activities: ActivityBlockModel[] = [];
  const activeOnly = validSessions.filter((s) => s.kind !== 'idle');
  let i = 0;
  const numActive = activeOnly.length;

  while (i < numActive) {
    const current = activeOnly[i];
    const curStartSec = toSec(current.start);

    // Check matching scheduled time block
    const matchingTimeBlock = timeBlocks.find((b) => {
      const bStartSec = toSec(b.start_time);
      const bEndSec = toSec(b.end_time);
      return curStartSec >= bStartSec - 180 && curStartSec <= bEndSec;
    });

    const isExplicit = Boolean(matchingTimeBlock);
    const rawActivityName = matchingTimeBlock?.title || inferActivityTitle(current.app, current.title, current.category_name);
    const categoryColor = current.category_color || matchingTimeBlock?.category_color || '#8065FF';
    const categoryName = current.category_name || matchingTimeBlock?.category_name || 'Development';
    const categoryType = (current.category_type as any) || (matchingTimeBlock?.category_type as any) || 'work';

    const activityName = viewMode === 'categories' ? categoryName : rawActivityName;

    let j = i;
    const groupSessions: SessionModel[] = [];
    let groupDur = 0;
    let groupEndIso = current.end;
    let interruptions = 0;

    while (j < numActive) {
      const candidate = activeOnly[j];
      const candStartSec = toSec(candidate.start);
      const prevEndSec = toSec(activeOnly[j - 1]?.end || current.start);

      // Gap check (meaningful gap or idle break ends current activity)
      if (j > i && candStartSec - prevEndSec > maxGapSeconds) {
        break;
      }

      const candRawName = matchingTimeBlock?.title || inferActivityTitle(candidate.app, candidate.title, candidate.category_name);
      const candCatName = candidate.category_name || matchingTimeBlock?.category_name || 'Development';
      const candActivityName = viewMode === 'categories' ? candCatName : candRawName;
      const isSameTask = candActivityName === activityName || (matchingTimeBlock && matchingTimeBlock.title === candActivityName);

      // Check if candidate is genuinely an interruption:
      // An interruption must be a single brief transient excursion (< 60s) returning to the main task,
      // or a brief system overlay. Distraction activities (e.g. YouTube entertainment) or sustained
      // switches are semantic boundaries and must NOT be absorbed into a focus task!
      const candCatType = candidate.category_type || 'work';
      const isSystemOverlay = ['explorer.exe', 'shellexperiencehost.exe', 'searchapp.exe', 'taskmgr.exe'].includes((candidate.app || '').toLowerCase());
      const isDistraction = candCatType === 'distraction' || (candidate.category_name || '').toLowerCase().includes('entertainment');

      const nextSession = j + 1 < numActive ? activeOnly[j + 1] : null;
      const nextTaskName = nextSession ? (matchingTimeBlock?.title || inferActivityTitle(nextSession.app, nextSession.title, nextSession.category_name)) : null;
      const returnsToSameTask = nextTaskName === activityName || (nextSession && nextSession.category_name === categoryName);

      const isTransientInterruption = !isDistraction && candidate.duration_seconds < 60 && (isSystemOverlay || returnsToSameTask);

      if (!isSameTask && isTransientInterruption) {
        interruptions++;
        groupSessions.push(candidate);
        groupDur += candidate.duration_seconds;
        groupEndIso = candidate.end;
        j++;
        continue;
      }

      // Different task breaks the activity group
      if (!isSameTask) {
        break;
      }

      // Same task continuation
      groupSessions.push(candidate);
      groupDur += candidate.duration_seconds;
      groupEndIso = candidate.end;
      j++;
    }

    // Build child events
    const childEvents: ChildAppEvent[] = groupSessions.map((s, idx) => ({
      id: `${s.session_key}_${idx}`,
      app: s.app,
      title: s.title,
      start: s.start,
      end: s.end,
      duration_seconds: s.duration_seconds,
      duration_label: formatDurationHuman(s.duration_seconds),
      url: s.url,
      category_name: s.category_name,
      category_color: s.category_color,
      category_type: s.category_type,
      is_interruption: (s.duration_seconds < 90 && inferActivityTitle(s.app, s.title, s.category_name) !== activityName),
      original_session: s,
    }));

    // Build app breakdown
    const appTotals: Record<string, number> = {};
    for (const s of groupSessions) {
      const a = s.app ? s.app.replace('.exe', '') : 'Unknown';
      appTotals[a] = (appTotals[a] || 0) + s.duration_seconds;
    }
    const breakdown = Object.entries(appTotals)
      .sort((a, b) => b[1] - a[1])
      .map(([app, secs]) => ({
        app,
        seconds: secs,
        pct: Math.round((secs / (groupDur || 1)) * 100),
        label: formatDurationHuman(secs),
      }));

    const taskMatchStatus = evaluateTaskMatch(activityName, breakdown[0]?.app || '', matchingTimeBlock);

    activities.push({
      id: `act_${i}_${groupSessions[0].session_key}`,
      title: activityName,
      subtitle: breakdown[0]?.app,
      category_name: categoryName,
      category_color: categoryColor,
      category_type: categoryType,
      start: groupSessions[0].start,
      end: groupEndIso,
      start_sec: toSec(groupSessions[0].start),
      end_sec: toSec(groupEndIso),
      duration_seconds: groupDur,
      duration_label: formatDurationHuman(groupDur),
      task_match_status: taskMatchStatus,
      planned_task_title: matchingTimeBlock?.title,
      is_explicit_task: isExplicit,
      underlying_sessions: groupSessions,
      child_events: childEvents,
      app_breakdown: breakdown,
      interruption_count: interruptions,
    });

    i = Math.max(i + 1, j);
  }

  // -------------------------------------------------------------------------
  // ROW 2: DETAILED APPS ROW (§4)
  // Coalesces same-app sequences and clusters rapid multi-app micro-switches
  // into clean "+N events" pills. Never draws overlapping labels or clipped text.
  // -------------------------------------------------------------------------
  const apps: AppBlockModel[] = [];
  let k = 0;

  while (k < numActive) {
    const s = activeOnly[k];

    // Check if part of a dense multi-app micro-switch cluster (< 75s each, sequence >= 3)
    let m = k;
    const clusterEvents: ChildAppEvent[] = [];
    let clusterDur = 0;

    while (m < numActive) {
      const item = activeOnly[m];
      const prevItem = activeOnly[m - 1];
      if (m > k) {
        const gap = toSec(item.start) - toSec(prevItem.end);
        if (gap > 60) break;
      }
      if (item.duration_seconds >= 90) break; // sustained session breaks rapid cluster
      clusterEvents.push({
        id: `app_ev_${item.session_key}`,
        app: item.app ? item.app.replace('.exe', '') : 'Unknown',
        title: item.title,
        start: item.start,
        end: item.end,
        duration_seconds: item.duration_seconds,
        duration_label: formatDurationHuman(item.duration_seconds),
        url: item.url,
        category_color: item.category_color,
        category_type: item.category_type,
        original_session: item,
      });
      clusterDur += item.duration_seconds;
      m++;
      if (clusterEvents.length >= 25) break; // cap cluster block span
    }

    if (clusterEvents.length >= 3) {
      const cEndS = toSec(clusterEvents[clusterEvents.length - 1].end);
      const catCount: Record<string, number> = {};
      const typeCount: Record<string, number> = {};
      const colorMap: Record<string, string> = {};
      for (const ev of clusterEvents) {
        const c = ev.original_session?.category_name || 'Other';
        catCount[c] = (catCount[c] || 0) + ev.duration_seconds;
        const ct = ev.category_type || 'work';
        typeCount[ct] = (typeCount[ct] || 0) + ev.duration_seconds;
        if (ev.category_color) colorMap[c] = ev.category_color;
      }
      const topCat = Object.entries(catCount).sort((a, b) => b[1] - a[1])[0]?.[0] || 'Task Switching';
      const topType = Object.entries(typeCount).sort((a, b) => b[1] - a[1])[0]?.[0] || 'work';
      const topColor = colorMap[topCat] || (topType === 'distraction' ? '#FA5275' : '#8065FF');

      apps.push({
        id: `dense_apps_${k}`,
        app: `+${clusterEvents.length} events`,
        title: topType === 'distraction' ? `Entertainment & media (${clusterEvents.length} events)` : `Rapid task switching (${clusterEvents.length} events)`,
        start: clusterEvents[0].start,
        end: clusterEvents[clusterEvents.length - 1].end,
        start_sec: toSec(clusterEvents[0].start),
        end_sec: cEndS,
        duration_seconds: clusterDur,
        duration_label: formatDurationHuman(clusterDur),
        category_color: topColor,
        category_type: topType,
        is_dense_cluster: true,
        switch_count: clusterEvents.length,
        child_events: clusterEvents,
      });
      k = m;
      continue;
    }

    // Standalone / same-app sequence: coalesce consecutive sessions of SAME app (gap <= 60s)
    let p = k;
    let appDur = 0;
    let appEnd = s.end;
    const sameAppEvents: ChildAppEvent[] = [];

    while (p < numActive) {
      const cand = activeOnly[p];
      if (cand.app !== s.app) break;
      if (p > k) {
        const gap = toSec(cand.start) - toSec(activeOnly[p - 1].end);
        if (gap > 90) break;
      }
      sameAppEvents.push({
        id: `single_app_${cand.session_key}`,
        app: cand.app ? cand.app.replace('.exe', '') : 'Unknown',
        title: cand.title,
        start: cand.start,
        end: cand.end,
        duration_seconds: cand.duration_seconds,
        duration_label: formatDurationHuman(cand.duration_seconds),
        url: cand.url,
        original_session: cand,
      });
      appDur += cand.duration_seconds;
      appEnd = cand.end;
      p++;
    }

    const appClean = s.app ? s.app.replace('.exe', '') : 'App';
    apps.push({
      id: `app_${s.session_key}_${k}`,
      app: appClean,
      title: s.title,
      start: s.start,
      end: appEnd,
      start_sec: toSec(s.start),
      end_sec: toSec(appEnd),
      duration_seconds: appDur,
      duration_label: formatDurationHuman(appDur),
      category_color: s.category_color || '#8065FF',
      category_type: s.category_type || 'work',
      is_dense_cluster: false,
      switch_count: sameAppEvents.length,
      child_events: sameAppEvents,
      original_session: s,
    });

    k = p;
  }

  // -------------------------------------------------------------------------
  // ROWS 3-6: CATEGORY LANES (§5)
  // Continuous coalesced intervals for Focus, Breaks, Distractions, and Idle.
  // -------------------------------------------------------------------------

  // Focus: productive work sessions or category_type === 'focus'
  const focusRaw = validSessions.filter(
    (s) => s.kind === 'active' && (s.category_type === 'focus' || (s.category_type !== 'distraction' && s.category_type !== 'break' && s.duration_seconds >= 90))
  );
  const focus = coalesceCategoryIntervals(focusRaw, 'focus', '#35D68A', 'Focus Session', 120, selectedDate);

  // Breaks: idle gaps (3m-30m) or explicit category_type === 'break'
  const breakRaw = validSessions.filter(
    (s) => s.category_type === 'break' || (s.kind === 'idle' && s.duration_seconds >= 180 && s.duration_seconds < 1800)
  );
  const breaks = coalesceCategoryIntervals(breakRaw, 'break', '#16D5E2', 'Rest / Break', 180, selectedDate);

  // Distractions: distraction category, netflix, youtube, gaming
  const distractionRaw = validSessions.filter(
    (s) =>
      s.category_type === 'distraction' ||
      s.app.toLowerCase().includes('netflix') ||
      (s.title && s.title.toLowerCase().includes('netflix')) ||
      (s.title && s.title.toLowerCase().includes('youtube')) ||
      s.app.toLowerCase().includes('valorant') ||
      (s.title && s.title.toLowerCase().includes('chess'))
  );
  const distractions = coalesceCategoryIntervals(distractionRaw, 'distraction', '#FA5275', 'Distraction', 120, selectedDate);

  // Idle: inactivity gaps
  const idleRaw = validSessions.filter((s) => s.kind === 'idle');
  const idle = coalesceCategoryIntervals(idleRaw, 'idle', '#5A6679', 'Inactivity Gap', 120, selectedDate);

  return {
    minHour,
    maxHour,
    startSec,
    endSec,
    totalSpanSec,
    hourMarkers,
    activities,
    apps,
    focus,
    breaks,
    distractions,
    idle,
  };
}
