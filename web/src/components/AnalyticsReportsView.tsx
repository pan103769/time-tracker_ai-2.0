import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type {
  AnalyticsRangeResponse,
  CategoryModel,
  HierarchicalUsageItem,
} from '../types';
import { formatLocalDate, getLocalTodayString } from '../types';
import {
  AppIconHelper,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  FileTextIcon,
  GamepadIcon,
  InsightsIcon,
  PieChartIcon,
  RefreshIcon,
  SearchIcon,
  SparklesIcon,
  ZapIcon,
} from './Icons';

type DatePreset = 'today' | 'yesterday' | '7days' | '30days' | 'this_week' | 'this_month' | 'custom';

interface AnalyticsReportsViewProps {
  selectedDate: string;
  onSelectDate: (date: string) => void;
  categories: CategoryModel[];
}

export const AnalyticsReportsView: React.FC<AnalyticsReportsViewProps> = ({
  selectedDate,
  onSelectDate,
  categories = [],
}) => {
  const [datePreset, setDatePreset] = useState<DatePreset>('7days');
  const [startDate, setStartDate] = useState<string>(() => {
    const end = new Date(selectedDate || getLocalTodayString());
    const start = new Date(end);
    start.setDate(end.getDate() - 6);
    return formatLocalDate(start);
  });
  const [endDate, setEndDate] = useState<string>(() => selectedDate || getLocalTodayString());

  // Custom date picker temporary inputs
  const [customStart, setCustomStart] = useState<string>(startDate);
  const [customEnd, setCustomEnd] = useState<string>(endDate);
  const [customError, setCustomError] = useState<string>('');

  // Data & loading states
  const [data, setData] = useState<AnalyticsRangeResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [isRefreshingAi, setIsRefreshingAi] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  // Search & filter states
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [exportToast, setExportToast] = useState<string | null>(null);
  const [breakdownViewMode, setBreakdownViewMode] = useState<'activities' | 'browsers'>('activities');

  // Accordion state for expandable rows
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  const toggleRow = (rowId: string) => {
    setExpandedRows((prev) => ({
      ...prev,
      [rowId]: !prev[rowId],
    }));
  };

  // Compute preset ranges accurately with local time (no UTC shift)
  const applyPreset = useCallback((preset: DatePreset) => {
    setDatePreset(preset);
    setCustomError('');

    const today = new Date();
    const todayStr = getLocalTodayString(today);

    if (preset === 'today') {
      setStartDate(todayStr);
      setEndDate(todayStr);
    } else if (preset === 'yesterday') {
      const y = new Date(today);
      y.setDate(today.getDate() - 1);
      const yStr = formatLocalDate(y);
      setStartDate(yStr);
      setEndDate(yStr);
    } else if (preset === '7days') {
      const start = new Date(today);
      start.setDate(today.getDate() - 6);
      setStartDate(formatLocalDate(start));
      setEndDate(todayStr);
    } else if (preset === '30days') {
      const start = new Date(today);
      start.setDate(today.getDate() - 29);
      setStartDate(formatLocalDate(start));
      setEndDate(todayStr);
    } else if (preset === 'this_week') {
      const start = new Date(today);
      const day = start.getDay();
      const diff = start.getDate() - day + (day === 0 ? -6 : 1); // Monday start
      start.setDate(diff);
      setStartDate(formatLocalDate(start));
      setEndDate(todayStr);
    } else if (preset === 'this_month') {
      const start = new Date(today.getFullYear(), today.getMonth(), 1);
      setStartDate(formatLocalDate(start));
      setEndDate(todayStr);
    }
  }, []);

  // Fetch range data from backend
  const fetchData = useCallback(async (start: string, end: string, refreshAi = false) => {
    try {
      if (refreshAi) {
        setIsRefreshingAi(true);
      } else {
        setLoading(true);
      }
      setError('');
      const res = await api.getAnalyticsRange(start, end, refreshAi);
      setData(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to load analytics and reports data.');
    } finally {
      setLoading(false);
      setIsRefreshingAi(false);
    }
  }, []);

  useEffect(() => {
    fetchData(startDate, endDate);
  }, [startDate, endDate, fetchData]);

  // Handle custom date apply
  const handleApplyCustom = () => {
    if (!customStart || !customEnd) {
      setCustomError('Please choose both start and end dates.');
      return;
    }
    if (customStart > customEnd) {
      setCustomError('Start date must be before or equal to end date.');
      return;
    }
    setCustomError('');
    setStartDate(customStart);
    setEndDate(customEnd);
  };

  // Previous & Next period navigation
  const handleNavigatePeriod = (direction: -1 | 1) => {
    const s = new Date(startDate + 'T00:00:00');
    const e = new Date(endDate + 'T00:00:00');
    const diffDays = Math.max(1, Math.round((e.getTime() - s.getTime()) / (1000 * 3600 * 24)) + 1);

    const newStart = new Date(s);
    newStart.setDate(s.getDate() + direction * diffDays);
    const newEnd = new Date(e);
    newEnd.setDate(e.getDate() + direction * diffDays);

    const todayStr = getLocalTodayString();
    if (direction === 1 && formatLocalDate(newStart) > todayStr) {
      return; // Can't navigate beyond today
    }

    setStartDate(formatLocalDate(newStart));
    setEndDate(formatLocalDate(newEnd));
    setCustomStart(formatLocalDate(newStart));
    setCustomEnd(formatLocalDate(newEnd));
  };

  // Filtered Top Activities & Tools or Browser Diagnostics
  const filteredBreakdown = useMemo(() => {
    const sourceList =
      breakdownViewMode === 'browsers'
        ? (data?.browser_breakdown || [])
        : (data?.app_breakdown || []);

    if (!sourceList.length) return [];

    const q = searchQuery.trim().toLowerCase();
    const cat = selectedCategory;

    return sourceList
      .map((item) => {
        // Filter children if present
        if (item.children && item.children.length > 0) {
          const matchingChildren = item.children.filter((c) => {
            const matchesCat = cat === 'all' || c.category.toLowerCase() === cat.toLowerCase();
            const matchesQ =
              !q ||
              c.app.toLowerCase().includes(q) ||
              c.activity_name.toLowerCase().includes(q) ||
              c.specific_task.toLowerCase().includes(q) ||
              (c.site_name ? c.site_name.toLowerCase().includes(q) : false) ||
              (c.browser_name ? c.browser_name.toLowerCase().includes(q) : false) ||
              c.category.toLowerCase().includes(q);
            return matchesCat && matchesQ;
          });

          if (matchingChildren.length > 0) {
            return {
              ...item,
              children: matchingChildren,
            };
          }

          // If query matches parent itself, keep parent
          const parentMatches =
            (!q ||
              item.app.toLowerCase().includes(q) ||
              item.activity_name.toLowerCase().includes(q) ||
              item.specific_task.toLowerCase().includes(q) ||
              (item.site_name ? item.site_name.toLowerCase().includes(q) : false) ||
              (item.browser_name ? item.browser_name.toLowerCase().includes(q) : false)) &&
            (cat === 'all' || item.category.toLowerCase() === cat.toLowerCase());

          if (parentMatches) {
            return item;
          }

          return null;
        }

        // Non-child row
        const matchesCat = cat === 'all' || item.category.toLowerCase() === cat.toLowerCase();
        const matchesQ =
          !q ||
          item.app.toLowerCase().includes(q) ||
          item.activity_name.toLowerCase().includes(q) ||
          item.specific_task.toLowerCase().includes(q) ||
          (item.site_name ? item.site_name.toLowerCase().includes(q) : false) ||
          (item.browser_name ? item.browser_name.toLowerCase().includes(q) : false) ||
          item.category.toLowerCase().includes(q);

        return matchesCat && matchesQ ? item : null;
      })
      .filter(Boolean) as HierarchicalUsageItem[];
  }, [data?.app_breakdown, data?.browser_breakdown, breakdownViewMode, searchQuery, selectedCategory]);

  // Filtered Detailed Sessions
  const filteredSessions = useMemo(() => {
    if (!data?.detailed_sessions) return [];
    const q = searchQuery.trim().toLowerCase();
    const cat = selectedCategory;

    return data.detailed_sessions.filter((s) => {
      if (s.kind === 'idle') return false;
      const cName = s.category_name || '';
      const matchesCat = cat === 'all' || cName.toLowerCase() === cat.toLowerCase();
      const matchesQ =
        !q ||
        (s.activity_name && s.activity_name.toLowerCase().includes(q)) ||
        (s.specific_task && s.specific_task.toLowerCase().includes(q)) ||
        s.app.toLowerCase().includes(q) ||
        s.title.toLowerCase().includes(q) ||
        cName.toLowerCase().includes(q);
      return matchesCat && matchesQ;
    });
  }, [data?.detailed_sessions, searchQuery, selectedCategory]);

  // Mapping for clean application display names
  const APP_NAME_MAP: Record<string, string> = {
    'chrome.exe': 'Google Chrome',
    'msedge.exe': 'Microsoft Edge',
    'firefox.exe': 'Mozilla Firefox',
    'code.exe': 'Visual Studio Code',
    'explorer.exe': 'Windows Explorer',
    'cmd.exe': 'Command Prompt',
    'powershell.exe': 'Windows PowerShell',
    'windowsterminal.exe': 'Windows Terminal',
    'notepad.exe': 'Notepad',
    'slack.exe': 'Slack',
    'discord.exe': 'Discord',
    'spotify.exe': 'Spotify',
  };

  // Helper to escape CSV cell according to RFC 4180
  const escapeCsv = (val: string | number | boolean | null | undefined): string => {
    if (val === null || val === undefined) return '""';
    const s = String(val);
    return `"${s.replace(/"/g, '""')}"`;
  };

  // Helper for HH:MM:SS duration format
  const formatDurationHms = (sec: number): string => {
    const s = Math.max(0, Math.round(sec));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const ss = s % 60;
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(h)}:${pad(m)}:${pad(ss)}`;
  };

  // Export Detailed CSV Handler (Exports every matching canonical interval with 36 rich columns)
  const handleExportCsv = () => {
    if (!filteredSessions.length) return;

    const headers = [
      'Record ID',
      'Local Date',
      'Start Time',
      'End Time',
      'Start Timestamp',
      'End Timestamp',
      'Duration (Seconds)',
      'Duration (Formatted)',
      'Application Name',
      'Process Name',
      'Window Title',
      'Website / Domain',
      'Page / Document Name',
      'Specific Activity Description',
      'Assigned Task Name',
      'Project Name',
      'Category',
      'Category Type',
      'Classification Source',
      'Confidence',
      'Needs Review',
      'Uncertain Activity',
      'Manually Corrected',
      'Productive Activity',
      'Deep Focus',
      'Distraction',
      'Idle Time',
      'Associated Focus Session ID',
      'Associated Time Block ID',
      'Planned Task',
      'Planned Match',
      'Observation Source',
      'Canonical Interval Key',
      'Observation IDs',
      'Matched Rule',
      'Metadata Level',
    ];

    const rows = filteredSessions.map((s) => {
      const sDt = s.start;
      const eDt = s.end;
      const localDate = sDt.slice(0, 10);
      const startTime = sDt.slice(11, 19);
      const endTime = eDt.slice(11, 19);
      const durSec = s.duration_seconds;
      const durHms = formatDurationHms(durSec);

      const appLower = s.app.toLowerCase();
      const appDisplay =
        APP_NAME_MAP[appLower] ||
        (appLower.includes('python') ? 'Python Background' : s.app.replace('.exe', ''));

      const catType = s.category_type || 'uncategorized';
      const isProd = catType === 'focus' || catType === 'work' ? 'Yes' : 'No';
      const isFocus = catType === 'focus' ? 'Yes' : 'No';
      const isDist = catType === 'distraction' ? 'Yes' : 'No';
      const needsReview = catType === 'uncategorized' || s.is_uncertain ? 'Yes' : 'No';
      const uncertain = s.is_uncertain ? 'Yes' : 'No';
      const manual = s.user_description || s.category_source === 'manual_override' ? 'Yes' : 'No';

      const metaLevel =
        s.domain && (s.document_name || s.site_name)
          ? 'Full'
          : s.domain
            ? 'Domain Only'
            : s.title
              ? 'Title Only'
              : 'Process Only';

      return [
        escapeCsv(`REC-${String(s.display_number).padStart(5, '0')}`),
        escapeCsv(localDate),
        escapeCsv(startTime),
        escapeCsv(endTime),
        escapeCsv(sDt),
        escapeCsv(eDt),
        Math.round(durSec * 100) / 100,
        escapeCsv(durHms),
        escapeCsv(appDisplay),
        escapeCsv(s.app),
        escapeCsv(s.title),
        escapeCsv(s.domain || ''),
        escapeCsv(s.document_name || s.site_name || ''),
        escapeCsv(s.activity_name || s.title),
        escapeCsv(s.task || ''),
        escapeCsv(''), // Project Name
        escapeCsv(s.category_name || 'Other / Needs Review'),
        escapeCsv(catType),
        escapeCsv(s.category_source || 'inference'),
        escapeCsv(s.confidence != null ? s.confidence.toFixed(2) : ''),
        escapeCsv(needsReview),
        escapeCsv(uncertain),
        escapeCsv(manual),
        escapeCsv(isProd),
        escapeCsv(isFocus),
        escapeCsv(isDist),
        escapeCsv('No'), // Idle Time
        escapeCsv(''), // Associated Focus Session ID
        escapeCsv(''), // Associated Time Block ID
        escapeCsv(''), // Planned Task
        escapeCsv('Unplanned'), // Planned Match
        escapeCsv('Automatic Tracking'),
        escapeCsv(s.session_key),
        escapeCsv((s.observation_ids || []).join(';')),
        escapeCsv(''), // Matched Rule
        escapeCsv(metaLevel),
      ];
    });

    const csvString = [headers.join(','), ...rows.map((r) => r.join(','))].join('\r\n');
    const blob = new Blob(['\uFEFF' + csvString], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `detailed-activity-report-${startDate}-to-${endDate}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setExportToast(`✓ Exported ${filteredSessions.length} activity records to CSV`);
    setTimeout(() => setExportToast(null), 4000);
  };

  // Export Executive Summary CSV (Category, Application, and Daily aggregate breakdowns)
  const handleExportSummaryCsv = () => {
    if (!data) return;

    const totActive = data.kpi?.total_tracked_seconds || 0;
    const prodActive = data.kpi?.productive_work_seconds || 0;
    const focusActive = data.kpi?.deep_focus_seconds || 0;
    const distActive = data.kpi?.distraction_seconds || 0;

    const lines: string[] = [
      '=== TIME TRACKER AI 2 — ANALYTICS EXECUTIVE SUMMARY ===',
      `"Date Range","${startDate} to ${endDate} (${data.days_count} days)"`,
      `"Generated At","${new Date().toISOString()}"`,
      `"Productivity Score","${data.productivity_score?.score || 0}/100 (${data.productivity_score?.label || ''})"`,
      '',
      '=== EXECUTIVE KPI METRICS ===',
      '"Metric","Duration (Formatted)","Duration (Seconds)","% of Total Active"',
      `"Productive Work Time","${data.kpi?.productive_work_label || '0s'}",${prodActive},"${totActive > 0 ? ((prodActive / totActive) * 100).toFixed(1) : '0'}%"`,
      `"Deep Focus Time","${data.kpi?.deep_focus_label || '0s'}",${focusActive},"${totActive > 0 ? ((focusActive / totActive) * 100).toFixed(1) : '0'}%"`,
      `"Distraction Time","${data.kpi?.distraction_label || '0s'}",${distActive},"${totActive > 0 ? ((distActive / totActive) * 100).toFixed(1) : '0'}%"`,
      `"Total Tracked Active Time","${data.kpi?.total_tracked_label || '0s'}",${totActive},"100.0%"`,
      '',
      '=== CATEGORY DISTRIBUTION BREAKDOWN ===',
      '"Category","Category Type","Duration (Formatted)","Duration (Seconds)","Percentage"',
      ...(data.category_breakdown || []).map((c) =>
        `"${c.name.replace(/"/g, '""')}","${c.type}","${c.label}",${c.seconds},"${c.pct}%"`
      ),
      '',
      '=== TOP ACTIVITIES & WEBSITES BREAKDOWN ===',
      '"Activity / Website","Category","Specific Task / Context","Duration (Formatted)","Duration (Seconds)","Percentage","Browser"',
      ...(data.app_breakdown || []).map((a) =>
        `"${a.app.replace(/"/g, '""')}","${a.category.replace(/"/g, '""')}","${a.specific_task.replace(/"/g, '""')}","${a.duration_label}",${a.duration_seconds},"${a.pct}%","${(a.browser_name || '').replace(/"/g, '""')}"`
      ),
      '',
      '=== DAILY PRODUCTIVITY TRENDS ===',
      '"Date","Day","Total Active (Formatted)","Total Active (Seconds)","Productive (Formatted)","Productive (Seconds)","Deep Focus (Seconds)","Distraction (Seconds)"',
      ...(data.daily_trends || []).map((d) =>
        `"${d.date}","${d.day_name}","${d.active_label}",${d.active_seconds},"${d.productive_label}",${d.productive_seconds},${d.focus_seconds},${d.distraction_seconds}`
      ),
    ];

    const blob = new Blob(['\uFEFF' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `analytics-summary-${startDate}-to-${endDate}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setExportToast(`✓ Exported executive summary report for ${startDate} to ${endDate}`);
    setTimeout(() => setExportToast(null), 4000);
  };

  const hasActiveFilters = searchQuery.trim() !== '' || selectedCategory !== 'all';
  const resetFilters = () => {
    setSearchQuery('');
    setSelectedCategory('all');
  };

  const kpi = data?.kpi;
  const scoreInfo = data?.productivity_score;
  const ai = data?.ai_synthesis;
  const maxTrendSecs = useMemo(() => {
    if (!data?.daily_trends?.length) return 3600;
    return Math.max(...data.daily_trends.map((d) => d.active_seconds), 3600);
  }, [data?.daily_trends]);

  return (
    <div className="view-container analytics-reports-view">
      {/* 1. Header & Global Controls */}
      <div className="view-header-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 9,
                background: 'rgba(128, 101, 255, 0.16)',
                border: '1px solid rgba(128, 101, 255, 0.35)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <InsightsIcon size={19} color="#8065FF" />
            </div>
            <div>
              <h2 style={{ fontSize: 22, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
                Analytics &amp; Reports
              </h2>
            </div>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-secondary, #8994A8)', margin: '4px 0 0 44px' }}>
            Understand your time, focus, habits, and progress.
          </p>
        </div>

        {/* Action Buttons: Refresh & Export */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => fetchData(startDate, endDate)}
            disabled={loading}
            style={{ fontSize: 12, padding: '7px 13px', gap: 6 }}
            title="Refresh current range metrics"
          >
            <RefreshIcon size={14} className={loading ? 'spin' : ''} />
            <span>{loading ? 'Refreshing…' : 'Refresh'}</span>
          </button>

          <button
            type="button"
            className="btn-secondary"
            onClick={handleExportSummaryCsv}
            disabled={loading || !data}
            style={{ fontSize: 12, padding: '7px 13px', gap: 6 }}
            title="Export executive category and application summary to CSV"
          >
            <FileTextIcon size={14} />
            <span>Summary CSV</span>
          </button>

          <button
            type="button"
            className="btn-secondary"
            onClick={handleExportCsv}
            disabled={loading || !filteredSessions.length}
            style={{ fontSize: 12, padding: '7px 13px', gap: 6 }}
            title="Export all matching canonical activity records as detailed CSV"
          >
            <FileTextIcon size={14} />
            <span>Export CSV ({filteredSessions.length})</span>
          </button>
        </div>
      </div>

      {/* 2. Global Range Selector & Filters Bar */}
      <div
        className="card"
        style={{
          padding: '12px 18px',
          marginBottom: 20,
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 14,
        }}
      >
        {/* Date Preset Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <div className="timeline-pill-group">
            <button
              type="button"
              className={`timeline-pill-btn ${datePreset === 'today' ? 'active' : ''}`}
              onClick={() => applyPreset('today')}
            >
              Today
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${datePreset === 'yesterday' ? 'active' : ''}`}
              onClick={() => applyPreset('yesterday')}
            >
              Yesterday
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${datePreset === '7days' ? 'active' : ''}`}
              onClick={() => applyPreset('7days')}
            >
              7 Days
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${datePreset === '30days' ? 'active' : ''}`}
              onClick={() => applyPreset('30days')}
            >
              30 Days
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${datePreset === 'this_week' ? 'active' : ''}`}
              onClick={() => applyPreset('this_week')}
            >
              This Week
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${datePreset === 'this_month' ? 'active' : ''}`}
              onClick={() => applyPreset('this_month')}
            >
              This Month
            </button>
            <button
              type="button"
              className={`timeline-pill-btn ${datePreset === 'custom' ? 'active' : ''}`}
              onClick={() => setDatePreset('custom')}
            >
              Custom Range
            </button>
          </div>

          {/* Period Arrows */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginLeft: 6 }}>
            <button
              type="button"
              className="btn-icon-subtle"
              onClick={() => handleNavigatePeriod(-1)}
              title="Previous equivalent period"
              style={{ padding: '6px 9px', borderRadius: 6, background: '#1A2230', border: '1px solid #27354A', color: '#EDF0F7', cursor: 'pointer' }}
            >
              &lt;
            </button>
            <button
              type="button"
              className="btn-icon-subtle"
              onClick={() => handleNavigatePeriod(1)}
              title="Next equivalent period"
              style={{ padding: '6px 9px', borderRadius: 6, background: '#1A2230', border: '1px solid #27354A', color: '#EDF0F7', cursor: 'pointer' }}
            >
              &gt;
            </button>
          </div>

          <span style={{ fontSize: 13, fontWeight: 600, color: '#EDF0F7', marginLeft: 6 }}>
            {startDate === endDate ? startDate : `${startDate} – ${endDate}`}
          </span>
        </div>

        {/* Search & Category Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* Search Input */}
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <span style={{ position: 'absolute', left: 10, color: 'var(--text-muted)' }}>
              <SearchIcon size={14} />
            </span>
            <input
              type="text"
              placeholder="Search activities, tools…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                background: '#0E131D',
                border: '1px solid #27354A',
                borderRadius: 6,
                padding: '6px 10px 6px 30px',
                color: '#EDF0F7',
                fontSize: 12,
                width: 175,
              }}
            />
          </div>

          {/* Category Dropdown */}
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            style={{
              background: '#0E131D',
              border: '1px solid #27354A',
              borderRadius: 6,
              padding: '6px 10px',
              color: '#EDF0F7',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            <option value="all">All Categories</option>
            {categories.map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>

          {/* Reset Filters button */}
          {hasActiveFilters && (
            <button
              type="button"
              onClick={resetFilters}
              style={{
                fontSize: 12,
                background: 'rgba(250, 82, 117, 0.15)',
                border: '1px solid rgba(250, 82, 117, 0.4)',
                color: '#FA5275',
                padding: '5px 10px',
                borderRadius: 6,
                cursor: 'pointer',
              }}
            >
              Reset Filters
            </button>
          )}
        </div>
      </div>

      {/* Custom Date Range Picker Dropdown (when Custom is selected) */}
      {datePreset === 'custom' && (
        <div
          className="card"
          style={{
            padding: '12px 18px',
            marginBottom: 20,
            background: 'rgba(19, 26, 38, 0.95)',
            border: '1px solid rgba(128, 101, 255, 0.3)',
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>From:</span>
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              style={{
                background: '#0E131D',
                border: '1px solid #27354A',
                borderRadius: 6,
                padding: '5px 10px',
                color: '#EDF0F7',
                fontSize: 12,
              }}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>To:</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              style={{
                background: '#0E131D',
                border: '1px solid #27354A',
                borderRadius: 6,
                padding: '5px 10px',
                color: '#EDF0F7',
                fontSize: 12,
              }}
            />
          </div>

          <button
            type="button"
            className="btn-primary"
            onClick={handleApplyCustom}
            style={{ fontSize: 12, padding: '6px 14px' }}
          >
            Apply Range
          </button>

          {customError && (
            <span style={{ fontSize: 12, color: '#FA5275', fontWeight: 500 }}>
              {customError}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="alert-box error" style={{ marginBottom: 20 }}>
          {error}
        </div>
      )}

      {/* 3. Four Primary KPI Cards */}
      <div className="kpi-cards-row" style={{ marginBottom: 20 }}>
        {/* KPI 1: Productive Work */}
        <div className="kpi-card-rize" title="Time spent on focus and work categories (excludes entertainment, distractions, and idle breaks)">
          <div className="kpi-icon-circle amber">
            <ClockIcon size={20} color="#FFB23E" />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Productive Work</span>
            <div className="kpi-value">{kpi ? kpi.productive_work_label : '0s'}</div>
            <div className={`kpi-comparison ${kpi?.comparison?.productive_work?.improved ? 'positive' : 'neutral'}`}>
              <span>
                {kpi?.comparison?.productive_work?.display_str
                  ? `${kpi.comparison.productive_work.improved ? '▲' : '▼'} ${kpi.comparison.productive_work.display_str} vs prior`
                  : 'Grounded work metrics'}
              </span>
            </div>
          </div>
        </div>

        {/* KPI 2: Deep Focus */}
        <div className="kpi-card-rize" title="High-concentration sessions meeting deep focus criteria (coding, writing, deliberate practice)">
          <div className="kpi-icon-circle purple">
            <ZapIcon size={20} color="#8065FF" />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Deep Focus</span>
            <div className="kpi-value" style={{ color: '#8065FF' }}>
              {kpi ? kpi.deep_focus_label : '0s'}
            </div>
            <div className={`kpi-comparison ${kpi?.comparison?.deep_focus?.improved ? 'positive' : 'neutral'}`}>
              <span>
                {kpi?.comparison?.deep_focus?.display_str
                  ? `${kpi.comparison.deep_focus.improved ? '▲' : '▼'} ${kpi.comparison.deep_focus.display_str} vs prior`
                  : `${scoreInfo?.focus_ratio_pct ?? 0}% focus ratio`}
              </span>
            </div>
          </div>
        </div>

        {/* KPI 3: Distraction Time */}
        <div className="kpi-card-rize" title="Time spent on entertainment, social media, and distracting sites">
          <div className="kpi-icon-circle coral">
            <GamepadIcon size={20} color="#FA5275" />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Distraction Time</span>
            <div className="kpi-value" style={{ color: kpi && kpi.distraction_seconds > 1800 ? '#FA5275' : '#EDF0F7' }}>
              {kpi ? kpi.distraction_label : '0s'}
            </div>
            <div className={`kpi-comparison ${kpi?.comparison?.distraction?.improved ? 'positive' : 'neutral'}`}>
              <span>
                {kpi?.comparison?.distraction?.display_str
                  ? `${kpi.comparison.distraction.improved ? '▼' : '▲'} ${kpi.comparison.distraction.display_str} vs prior`
                  : `${scoreInfo?.distraction_ratio_pct ?? 0}% distraction ratio`}
              </span>
            </div>
          </div>
        </div>

        {/* KPI 4: Total Tracked Time */}
        <div className="kpi-card-rize" title="Total observed active computer time, distinguished from productive work">
          <div className="kpi-icon-circle cyan">
            <PieChartIcon size={20} color="#16D5E2" />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Total Tracked Time</span>
            <div className="kpi-value">{kpi ? kpi.total_tracked_label : '0s'}</div>
            <div className="kpi-comparison positive">
              <span>{kpi?.comparison?.prior_period_label || 'Across observed activity'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 4. Productivity Score & AI Productivity Synthesis Combined Section */}
      <div className="card" style={{ marginBottom: 24, padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, borderBottom: '1px solid rgba(39, 53, 74, 0.6)', paddingBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <SparklesIcon size={20} color="#8065FF" />
            <h3 style={{ fontSize: 16, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
              Productivity Score &amp; AI Productivity Synthesis
            </h3>
            {ai?.source && (
              <span className="badge badge-source" style={{ fontSize: 10 }}>
                {ai.source.toUpperCase()}
              </span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {ai?.generated_at ? new Date(ai.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
            </span>
            <button
              type="button"
              className="btn-refresh-ai"
              onClick={() => fetchData(startDate, endDate, true)}
              disabled={isRefreshingAi || loading}
              style={{ fontSize: 12, padding: '6px 12px' }}
            >
              <SparklesIcon size={13} color="#8065FF" className={isRefreshingAi ? 'spin' : ''} />
              <span>{isRefreshingAi ? 'Analyzing with AI…' : 'Regenerate Analysis'}</span>
            </button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 24, alignItems: 'center' }}>
          {/* Score Ring & Meta */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '16px 20px',
              background: '#0E131D',
              borderRadius: 12,
              border: '1px solid #27354A',
            }}
          >
            <div
              className="score-ring-wrap"
              style={{
                width: 90,
                height: 90,
                borderRadius: '50%',
                border: `3px solid ${scoreInfo?.color || '#35D68A'}`,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: 10,
              }}
            >
              <span style={{ fontSize: 28, fontWeight: 800, color: scoreInfo?.color || '#35D68A', lineHeight: 1 }}>
                {scoreInfo?.score ?? 0}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>/ 100</span>
            </div>

            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: scoreInfo?.color || '#35D68A',
                backgroundColor: `${scoreInfo?.color || '#35D68A'}22`,
                padding: '3px 10px',
                borderRadius: 12,
                marginBottom: 6,
              }}
            >
              {scoreInfo?.label || 'Balanced'}
            </span>

            <p style={{ fontSize: 11, color: 'var(--text-secondary)', textAlign: 'center', margin: 0 }}>
              {scoreInfo?.explanation || 'Grounded in deterministic metrics'}
            </p>
          </div>

          {/* AI Synthesis Details */}
          <div className="ai-summary-content" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {ai ? (
              <>
                <p className="ai-takeaway" style={{ fontSize: 14, lineHeight: 1.5, margin: 0, color: '#EDF0F7', fontWeight: 500 }}>
                  {ai.key_takeaway}
                </p>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                  <div className="ai-sub-box" style={{ background: '#0E131D', padding: 12, borderRadius: 8, border: '1px solid #27354A' }}>
                    <span className="ai-sub-label" style={{ fontSize: 11, fontWeight: 700, color: '#16D5E2', textTransform: 'uppercase' }}>
                      Focus &amp; Continuity
                    </span>
                    <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '4px 0 0 0', lineHeight: 1.4 }}>
                      {ai.focus_streak_summary}
                    </p>
                  </div>

                  <div className="ai-sub-box" style={{ background: '#0E131D', padding: 12, borderRadius: 8, border: '1px solid #27354A' }}>
                    <span className="ai-sub-label" style={{ fontSize: 11, fontWeight: 700, color: '#FA5275', textTransform: 'uppercase' }}>
                      Context Switching &amp; Distraction
                    </span>
                    <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '4px 0 0 0', lineHeight: 1.4 }}>
                      {ai.interruption_analysis}
                    </p>
                  </div>
                </div>

                {ai.recommendations && ai.recommendations.length > 0 && (
                  <div style={{ background: 'rgba(128, 101, 255, 0.08)', padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(128, 101, 255, 0.2)' }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#A78BFA' }}>
                      Actionable Recommendations
                    </span>
                    <ul style={{ margin: '6px 0 0 16px', padding: 0, fontSize: 12, color: '#EDF0F7' }}>
                      {ai.recommendations.map((rec, i) => (
                        <li key={i} style={{ marginBottom: 3 }}>
                          {rec}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className="loading-placeholder">Computing metrics and intelligence…</p>
            )}
          </div>
        </div>
      </div>

      {/* 5. Grid: Multi-Day Trends Chart (Left) & Top Focus Interruptors (Right) */}
      <div className="dash-grid" style={{ marginBottom: 24 }}>
        {/* Trend & Work Volume Chart */}
        <div className="card">
          <div className="card-title-bar">
            <span className="card-title">Activity Trend &amp; Work Volume</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {data?.daily_trends?.length ?? 0} days in range
            </span>
          </div>

          {data?.daily_trends && data.daily_trends.length > 0 ? (
            <div className="weekly-bars-container" style={{ minHeight: 140, display: 'flex', alignItems: 'flex-end', gap: 8, padding: '16px 0' }}>
              {data.daily_trends.map((day) => {
                const isSelected = day.date === selectedDate;
                const totalHeightPct =
                  maxTrendSecs > 0
                    ? Math.max(8, Math.round((day.active_seconds / maxTrendSecs) * 100))
                    : 8;

                const productivePct =
                  day.active_seconds > 0
                    ? Math.round((day.productive_seconds / day.active_seconds) * 100)
                    : 0;

                return (
                  <div
                    key={day.date}
                    className="weekly-bar-col"
                    onClick={() => onSelectDate(day.date)}
                    style={{ cursor: 'pointer', flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}
                    title={`${day.date}: ${day.active_label} total (${day.productive_label} productive, ${day.distraction_label} distraction)`}
                  >
                    <div className="bar-wrapper" style={{ width: '100%', height: 110, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
                      <div
                        className={`bar-fill ${isSelected ? 'current-day' : ''}`}
                        style={{
                          height: `${totalHeightPct}%`,
                          width: '75%',
                          maxWidth: 36,
                          borderRadius: '4px 4px 0 0',
                          backgroundColor: isSelected ? '#8065FF' : '#27354A',
                          position: 'relative',
                          overflow: 'hidden',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'flex-end',
                        }}
                      >
                        {/* Productive inner portion */}
                        <div
                          style={{
                            height: `${productivePct}%`,
                            width: '100%',
                            backgroundColor: '#35D68A',
                            opacity: 0.85,
                          }}
                        />
                      </div>
                    </div>
                    <span className={`bar-label ${isSelected ? 'active' : ''}`} style={{ fontSize: 11, marginTop: 6 }}>
                      {day.day_name}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                      {day.date.slice(5)}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="no-data-text">No trend data available for this range.</p>
          )}

          {/* Chart Legend */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, marginTop: 10, fontSize: 11, color: 'var(--text-muted)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: '#35D68A' }} />
              <span>Productive Work</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: '#27354A' }} />
              <span>Other / Distraction</span>
            </div>
          </div>
        </div>

        {/* Primary Focus Interruptors */}
        <div className="card">
          <div className="card-title-bar">
            <span className="card-title">Primary Focus Interruptors</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {scoreInfo?.total_interruptions || 0} switch events
            </span>
          </div>

          {data?.top_interruptors && data.top_interruptors.length > 0 ? (
            <div className="interruptors-list" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {data.top_interruptors.map((item, idx) => (
                <div key={item.app + idx} className="interruptor-item">
                  <div className="interruptor-rank">#{idx + 1}</div>
                  <div className="interruptor-icon">
                    <AppIconHelper app={item.app} size={18} />
                  </div>
                  <div className="interruptor-info">
                    <div className="interruptor-name-row">
                      <span className="interruptor-name">{item.app}</span>
                      <span className="interruptor-lost">{item.lost_label} lost</span>
                    </div>
                    <div className="interruptor-bar-track">
                      <div
                        className="interruptor-bar-fill"
                        style={{
                          width: `${Math.min(100, Math.max(12, (item.lost_seconds / (kpi?.distraction_seconds || 1)) * 100))}%`,
                        }}
                      />
                    </div>
                    <span className="interruptor-sub">{item.count} interruption switches</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--text-muted)' }}>
              <ZapIcon size={32} color="#35D68A" style={{ marginBottom: 8, opacity: 0.8 }} />
              <p>Zero interruptions logged during focus sessions.</p>
            </div>
          )}
        </div>
      </div>

      {/* 6. Main Grid: Top Activities & Websites (Hierarchical) & Category Allocation */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.65fr 1fr', gap: 20, marginBottom: 24 }}>
        {/* Top Application & Tool Usage Table */}
        <div className="card-panel">
          <div className="panel-header" style={{ marginBottom: 14, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <h3 className="panel-title" style={{ margin: 0, fontSize: 16 }}>
                  {breakdownViewMode === 'activities' ? 'Top Activities & Websites' : 'Browser Diagnostics & Process Usage'}
                </h3>
                <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: 'rgba(128, 101, 255, 0.15)', color: '#A78BFA', fontWeight: 600 }}>
                  {filteredBreakdown.length} {breakdownViewMode === 'activities' ? 'activities' : 'containers'}
                </span>
              </div>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {breakdownViewMode === 'activities'
                  ? 'Website-level time attribution with purpose-separated categories (zero browser double-counting)'
                  : 'Diagnostic view grouping background browser containers with neutral activity labels'}
              </span>
            </div>

            {/* View Mode Toggle Segmented Control */}
            <div style={{ display: 'inline-flex', alignItems: 'center', background: '#0A0F18', border: '1px solid var(--border-subtle, #252E3C)', borderRadius: 7, padding: 2 }}>
              <button
                type="button"
                className={`timeline-pill-btn ${breakdownViewMode === 'activities' ? 'active' : ''}`}
                onClick={() => setBreakdownViewMode('activities')}
                title="Website-first activity breakdown (recommended)"
                style={{ fontSize: 11.5, padding: '4px 10px' }}
              >
                Websites &amp; Tools
              </button>
              <button
                type="button"
                className={`timeline-pill-btn ${breakdownViewMode === 'browsers' ? 'active' : ''}`}
                onClick={() => setBreakdownViewMode('browsers')}
                title="Show raw browser diagnostic containers"
                style={{ fontSize: 11.5, padding: '4px 10px' }}
              >
                Browser Diagnostics
              </button>
            </div>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(39, 53, 74, 0.65)', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '8px 10px', fontWeight: 600 }}>Activity / Tool</th>
                  <th style={{ padding: '8px 10px', fontWeight: 600 }}>Specific Task / Context</th>
                  <th style={{ padding: '8px 10px', fontWeight: 600 }}>Category</th>
                  <th style={{ padding: '8px 10px', fontWeight: 600 }}>Time</th>
                  <th style={{ padding: '8px 10px', fontWeight: 600 }}>Share</th>
                  <th style={{ padding: '8px 10px', fontWeight: 600 }}>Switches</th>
                </tr>
              </thead>
              <tbody>
                {filteredBreakdown.length > 0 ? (
                  filteredBreakdown.map((row) => {
                    const isExpanded = !!expandedRows[row.id];
                    const hasChildren = row.children && row.children.length > 0;

                    return (
                      <React.Fragment key={row.id}>
                        {/* Parent Row */}
                        <tr
                          style={{
                            borderBottom: '1px solid rgba(26, 34, 48, 0.6)',
                            background: hasChildren ? 'rgba(26, 34, 48, 0.4)' : 'transparent',
                            transition: 'background 0.15s',
                          }}
                        >
                          <td style={{ padding: '10px 10px', fontWeight: 600, color: '#EDF0F7' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              {hasChildren ? (
                                <button
                                  type="button"
                                  onClick={() => toggleRow(row.id)}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    color: '#8065FF',
                                    cursor: 'pointer',
                                    padding: 2,
                                    display: 'flex',
                                    alignItems: 'center',
                                  }}
                                  title={isExpanded ? 'Collapse specific items' : 'Expand specific items'}
                                >
                                  {isExpanded ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}
                                </button>
                              ) : (
                                <span style={{ width: 14 }} />
                              )}
                              <AppIconHelper app={row.site_name || row.app} size={16} />
                              <span>{row.app}</span>
                              {row.browser_name && (
                                <span
                                  style={{
                                    fontSize: 10,
                                    padding: '1px 5px',
                                    borderRadius: 3,
                                    background: 'rgba(22, 213, 226, 0.12)',
                                    color: '#16D5E2',
                                    border: '1px solid rgba(22, 213, 226, 0.25)',
                                    fontWeight: 500,
                                    whiteSpace: 'nowrap',
                                  }}
                                  title={`Tracked via ${row.browser_name}`}
                                >
                                  via {row.browser_name.replace('Google ', '').replace('Microsoft ', '')}
                                </span>
                              )}
                            </div>
                          </td>

                          <td style={{ padding: '10px 10px', color: 'var(--text-secondary)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span style={{ color: '#EDF0F7', fontWeight: 500 }}>
                                {row.specific_task || row.activity_name}
                              </span>
                              {row.is_uncertain && (
                                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'rgba(255, 178, 62, 0.2)', color: '#FFB23E' }}>
                                  Needs Review
                                </span>
                              )}
                            </div>
                          </td>

                          <td style={{ padding: '10px 10px' }}>
                            <span
                              style={{
                                fontSize: 11,
                                padding: '2px 7px',
                                borderRadius: 4,
                                background: `${row.category_color}22`,
                                color: row.category_color || '#8065FF',
                              }}
                            >
                              {row.category}
                            </span>
                          </td>

                          <td style={{ padding: '10px 10px', fontFamily: 'var(--font-mono)', color: '#EDF0F7', fontWeight: 600 }}>
                            {row.duration_label}
                          </td>

                          <td style={{ padding: '10px 10px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ fontSize: 12, minWidth: 32 }}>{row.pct}%</span>
                              <div style={{ flex: 1, height: 6, background: '#1A2230', borderRadius: 3, overflow: 'hidden' }}>
                                <div style={{ width: `${row.pct}%`, height: '100%', background: row.category_color || '#8065FF', borderRadius: 3 }} />
                              </div>
                            </div>
                          </td>

                          <td style={{ padding: '10px 10px', color: 'var(--text-muted)' }}>
                            {row.switches}
                          </td>
                        </tr>

                        {/* Child Rows (Level 2: Specific activity detail, videos, pages) */}
                        {hasChildren &&
                          isExpanded &&
                          row.children!.map((child) => (
                            <tr
                              key={child.id}
                              style={{
                                borderBottom: '1px solid rgba(26, 34, 48, 0.35)',
                                background: 'rgba(14, 19, 29, 0.7)',
                              }}
                            >
                              <td style={{ padding: '8px 10px 8px 38px', color: '#EDF0F7', fontSize: 12 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: child.category_color }} />
                                  <span style={{ fontWeight: 500 }}>{child.site_name || child.app}</span>
                                </div>
                              </td>

                              <td style={{ padding: '8px 10px', color: 'var(--text-secondary)', fontSize: 12 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <span style={{ color: '#E2E8F0' }}>{child.activity_name}</span>
                                  {child.is_uncertain && (
                                    <span style={{ fontSize: 9, padding: '1px 4px', borderRadius: 3, background: 'rgba(255, 178, 62, 0.2)', color: '#FFB23E' }}>
                                      Needs Review
                                    </span>
                                  )}
                                </div>
                              </td>

                              <td style={{ padding: '8px 10px' }}>
                                <span
                                  style={{
                                    fontSize: 10,
                                    padding: '1px 6px',
                                    borderRadius: 3,
                                    background: `${child.category_color}22`,
                                    color: child.category_color,
                                  }}
                                >
                                  {child.category}
                                </span>
                              </td>

                              <td style={{ padding: '8px 10px', fontFamily: 'var(--font-mono)', color: '#CBD5E1', fontSize: 12 }}>
                                {child.duration_label}
                              </td>

                              <td style={{ padding: '8px 10px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                  <span style={{ fontSize: 11, minWidth: 28, color: 'var(--text-muted)' }}>{child.pct}%</span>
                                  <div style={{ flex: 1, height: 4, background: '#1A2230', borderRadius: 2, overflow: 'hidden' }}>
                                    <div style={{ width: `${child.pct}%`, height: '100%', background: child.category_color, borderRadius: 2 }} />
                                  </div>
                                </div>
                              </td>

                              <td style={{ padding: '8px 10px', color: 'var(--text-muted)', fontSize: 11 }}>
                                {child.switches}
                              </td>
                            </tr>
                          ))}
                      </React.Fragment>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={6} style={{ padding: '24px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      No matching activities found for the selected range and filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Category Breakdown Panel */}
        <div className="card-panel">
          <div className="panel-header" style={{ marginBottom: 14 }}>
            <h3 className="panel-title" style={{ margin: 0, fontSize: 16 }}>
              Category Distribution
            </h3>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Canonical non-overlapping allocation
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {data?.category_breakdown && data.category_breakdown.length > 0 ? (
              data.category_breakdown.map((cat) => (
                <div key={cat.name}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: cat.color }} />
                      <span style={{ fontSize: 13, fontWeight: 500, color: '#EDF0F7' }}>{cat.name}</span>
                      <span className={`badge-type ${cat.type}`} style={{ fontSize: 9, padding: '1px 6px' }}>
                        {cat.type === 'uncategorized' ? 'Needs Review' : cat.type}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{cat.label}</span>
                      <strong style={{ fontSize: 12, color: '#EDF0F7', minWidth: 32, textAlign: 'right' }}>{cat.pct}%</strong>
                    </div>
                  </div>
                  <div style={{ height: 6, background: '#1A2230', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${cat.pct}%`, height: '100%', backgroundColor: cat.color, borderRadius: 3 }} />
                  </div>
                </div>
              ))
            ) : (
              <p className="no-data-text">No category data logged for this period.</p>
            )}
          </div>
        </div>
      </div>

      {/* 7. Detailed Activity Report & Canonical Record Drill-down */}
      <div className="card" style={{ padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
              Detailed Activity Records
            </h3>
            <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '2px 0 0 0' }}>
              Showing {filteredSessions.length} canonical intervals matching current range and filters
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={handleExportSummaryCsv}
              disabled={!data}
              style={{ fontSize: 12, padding: '6px 12px', gap: 6 }}
              title="Export executive summary of categories and applications to CSV"
            >
              <FileTextIcon size={13} />
              <span>Summary CSV</span>
            </button>

            <button
              type="button"
              className="btn-secondary"
              onClick={handleExportCsv}
              disabled={!filteredSessions.length}
              style={{ fontSize: 12, padding: '6px 12px', gap: 6 }}
              title="Export every matching canonical activity interval with complete 36-column metadata"
            >
              <FileTextIcon size={13} />
              <span>Export CSV ({filteredSessions.length})</span>
            </button>
          </div>
        </div>

        <div style={{ maxHeight: 380, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(39, 53, 74, 0.65)', color: 'var(--text-secondary)', position: 'sticky', top: 0, background: '#131A26', zIndex: 1 }}>
                <th style={{ padding: '8px 10px', fontWeight: 600 }}>Date &amp; Time</th>
                <th style={{ padding: '8px 10px', fontWeight: 600 }}>Application</th>
                <th style={{ padding: '8px 10px', fontWeight: 600 }}>Specific Activity &amp; Task</th>
                <th style={{ padding: '8px 10px', fontWeight: 600 }}>Category</th>
                <th style={{ padding: '8px 10px', fontWeight: 600 }}>Duration</th>
              </tr>
            </thead>
            <tbody>
              {filteredSessions.slice(0, 150).map((s) => (
                <tr
                  key={s.session_key}
                  style={{
                    borderBottom: '1px solid rgba(26, 34, 48, 0.45)',
                    transition: 'background 0.15s',
                  }}
                >
                  <td style={{ padding: '8px 10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {s.start.slice(0, 10)} {s.start.slice(11, 16)}
                  </td>
                  <td style={{ padding: '8px 10px', fontWeight: 600, color: '#EDF0F7' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <AppIconHelper app={s.site_name || s.app} size={14} />
                      <span>{s.site_name || APP_NAME_MAP[s.app.toLowerCase()] || s.app.replace('.exe', '')}</span>
                      {s.site_name && (
                        <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 400 }}>
                          ({s.app.replace('.exe', '')})
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '8px 10px', color: '#EDF0F7' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span>{s.activity_name || s.title}</span>
                      {s.is_uncertain && (
                        <span style={{ fontSize: 9, padding: '1px 4px', borderRadius: 3, background: 'rgba(255, 178, 62, 0.2)', color: '#FFB23E' }}>
                          Needs Review
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <span
                      style={{
                        fontSize: 10,
                        padding: '1px 6px',
                        borderRadius: 3,
                        background: `${s.category_color || '#8065FF'}22`,
                        color: s.category_color || '#8065FF',
                      }}
                    >
                      {s.category_name || 'Uncategorized'}
                    </span>
                  </td>
                  <td style={{ padding: '8px 10px', fontFamily: 'var(--font-mono)', color: '#16D5E2', fontWeight: 600 }}>
                    {s.duration_label}
                  </td>
                </tr>
              ))}
              {filteredSessions.length > 150 && (
                <tr>
                  <td colSpan={5} style={{ padding: '12px 10px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 11 }}>
                    Showing first 150 sessions. Use CSV export to view all {filteredSessions.length} records.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Export Success Feedback Toast */}
      {exportToast && (
        <div className="export-feedback-toast" role="status" aria-live="polite">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16D5E2" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <span>{exportToast}</span>
        </div>
      )}
    </div>
  );
};
