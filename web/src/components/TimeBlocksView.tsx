import React, { useState, useEffect, useCallback, useMemo } from 'react';
import type {
  ActiveTaskModel,
  CategoryModel,
  TimeBlockAnalysisModel,
  TimeBlockDailySummaryModel,
  TimeBlockModel,
} from '../types';
import { api } from '../api';
import {
  AlertTriangleIcon,
  AppIconHelper,
  CalendarIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  CopyIcon,
  EditIcon,
  PlayIcon,
  PlusIcon,
  SparklesIcon,
  TargetIcon,
  TrashIcon,
} from './Icons';

interface TimeBlocksViewProps {
  timeBlocks: TimeBlockModel[];
  timeBlocksAnalysis: TimeBlockAnalysisModel[];
  categories: CategoryModel[];
  selectedDate: string;
  onCreateTimeBlock: (block: {
    date: string;
    start_time: string;
    end_time: string;
    title: string;
    category_id?: number | null;
  }) => Promise<void> | Promise<boolean>;
  onDeleteTimeBlock: (id: number) => Promise<void> | Promise<boolean>;
  onUpdateTimeBlock?: (
    id: number,
    data: {
      date?: string;
      start_time?: string;
      end_time?: string;
      title?: string;
      category_id?: number | null;
    }
  ) => Promise<void> | Promise<boolean>;
  onDuplicateTimeBlock?: (
    id: number,
    targetDate?: string,
    timeOffsetMinutes?: number
  ) => Promise<void> | Promise<boolean>;
  onStartFocus?: (blockId: number) => Promise<void>;
  onSkipTimeBlock?: (blockId: number) => Promise<void>;
  onSelectDate?: (dateStr: string) => void;
  onNavigateTimeline?: () => void;
  activeTask?: ActiveTaskModel | null;
  isTracking?: boolean;
  onRefresh?: () => void;
}

// ---------------------------------------------------------------------------
// Date & Time Helpers
// ---------------------------------------------------------------------------

function formatTime12h(timeStr: string): string {
  if (!timeStr) return '';
  let clean = timeStr;
  if (clean.includes('T')) {
    clean = clean.split('T')[1].slice(0, 5);
  } else if (clean.length > 5) {
    clean = clean.slice(0, 5);
  }
  const parts = clean.split(':');
  if (parts.length < 2) return clean;
  const hours = parseInt(parts[0], 10);
  const minutes = parts[1];
  if (isNaN(hours)) return clean;
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const h12 = hours % 12 || 12;
  return `${h12}:${minutes} ${ampm}`;
}

function formatTimeRange(startStr: string, endStr: string): string {
  return `${formatTime12h(startStr)} – ${formatTime12h(endStr)}`;
}

function calculateDurationMinutes(startStr: string, endStr: string): number {
  try {
    const cleanStart = startStr.includes('T') ? startStr.split('T')[1].slice(0, 5) : startStr.slice(0, 5);
    const cleanEnd = endStr.includes('T') ? endStr.split('T')[1].slice(0, 5) : endStr.slice(0, 5);
    const [sh, sm] = cleanStart.split(':').map(Number);
    const [eh, em] = cleanEnd.split(':').map(Number);
    let diff = (eh * 60 + em) - (sh * 60 + sm);
    if (diff < 0) diff += 24 * 60; // overnight
    return diff;
  } catch {
    return 0;
  }
}

function formatDurationLabel(mins: number): string {
  if (mins <= 0) return '0m';
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  return `${m}m`;
}

function getTodayString(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function formatFriendlyDate(dateStr: string): string {
  try {
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      const year = parseInt(parts[0], 10);
      const month = parseInt(parts[1], 10) - 1;
      const day = parseInt(parts[2], 10);
      const d = new Date(year, month, day);
      return d.toLocaleDateString(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
    }
  } catch {
    // fallback
  }
  return dateStr;
}

function addDaysToDateStr(dateStr: string, days: number): string {
  try {
    const parts = dateStr.split('-');
    const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
    d.setDate(d.getDate() + days);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  } catch {
    return dateStr;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const TimeBlocksView: React.FC<TimeBlocksViewProps> = ({
  timeBlocks = [],
  timeBlocksAnalysis = [],
  categories = [],
  selectedDate,
  onCreateTimeBlock,
  onDeleteTimeBlock,
  onUpdateTimeBlock,
  onDuplicateTimeBlock,
  onStartFocus,
  onSkipTimeBlock,
  onSelectDate,
  onNavigateTimeline,
  activeTask,
  isTracking = false,
  onRefresh,
}) => {
  const todayStr = getTodayString();
  const isSelectedDateToday = selectedDate === todayStr;

  // Mental model collapsible state
  const [showMentalModel, setShowMentalModel] = useState<boolean>(() => {
    try {
      return localStorage.getItem('tt_hide_mental_model') !== 'true';
    } catch {
      return true;
    }
  });

  const toggleMentalModel = () => {
    setShowMentalModel((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('tt_hide_mental_model', String(!next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  // Daily Summary state
  const [dailySummary, setDailySummary] = useState<TimeBlockDailySummaryModel | null>(null);

  const fetchDailySummary = useCallback(async (dateStr: string) => {
    try {
      const res = await api.getTimeBlocksDailySummary(dateStr);
      setDailySummary(res);
    } catch {
      setDailySummary(null);
    }
  }, []);

  useEffect(() => {
    fetchDailySummary(selectedDate);
  }, [selectedDate, fetchDailySummary, timeBlocks.length]);

  // Modal States
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingBlock, setEditingBlock] = useState<TimeBlockModel | null>(null);
  const [duplicatingBlock, setDuplicatingBlock] = useState<TimeBlockModel | null>(null);

  // Form State for Create & Edit
  const [modalTitle, setModalTitle] = useState('');
  const [modalDate, setModalDate] = useState(selectedDate);
  const [modalStartTime, setModalStartTime] = useState('09:00');
  const [modalEndTime, setModalEndTime] = useState('09:45');
  const [modalCategoryId, setModalCategoryId] = useState<number | ''>('');
  const [modalError, setModalError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Overlap Warning State
  const [overlapWarning, setOverlapWarning] = useState<string | null>(null);

  // Check overlap debounced
  useEffect(() => {
    if (!isCreateModalOpen && !editingBlock) return;
    const timer = setTimeout(async () => {
      try {
        const res = await api.checkTimeBlockOverlap(
          modalDate,
          modalStartTime,
          modalEndTime,
          editingBlock?.id
        );
        if (res.has_overlap && res.overlaps.length > 0) {
          const conflicting = res.overlaps[0];
          const timeRange = conflicting.display_time_label || formatTimeRange(conflicting.start_time, conflicting.end_time);
          setOverlapWarning(
            `Overlaps with "${conflicting.title}" (${timeRange}). You can still save if intentional, or adjust times.`
          );
        } else {
          setOverlapWarning(null);
        }
      } catch {
        setOverlapWarning(null);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [modalDate, modalStartTime, modalEndTime, editingBlock, isCreateModalOpen]);

  // Open Create Modal
  const openCreateModal = (presetDuration = 45, presetTitle = '') => {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    const startH = pad(now.getHours());
    const startM = pad(Math.floor(now.getMinutes() / 5) * 5);
    const startStr = `${startH}:${startM}`;
    const endDate = new Date(now.getTime() + presetDuration * 60000);
    const endStr = `${pad(endDate.getHours())}:${pad(endDate.getMinutes())}`;

    setModalTitle(presetTitle);
    setModalDate(selectedDate);
    setModalStartTime(startStr);
    setModalEndTime(endStr);
    setModalCategoryId('');
    setModalError(null);
    setOverlapWarning(null);
    setEditingBlock(null);
    setIsCreateModalOpen(true);
  };

  // Open Edit Modal
  const openEditModal = (block: TimeBlockModel) => {
    setEditingBlock(block);
    setModalTitle(block.title);
    setModalDate(block.date);
    setModalStartTime(block.start_time.slice(0, 5));
    setModalEndTime(block.end_time.slice(0, 5));
    setModalCategoryId(block.category_id ?? '');
    setModalError(null);
    setOverlapWarning(null);
    setIsCreateModalOpen(true);
  };

  // Handle Form Submit (Create or Update)
  const handleSaveModal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!modalTitle.trim()) {
      setModalError('Please provide a title or task name.');
      return;
    }

    const dur = calculateDurationMinutes(modalStartTime, modalEndTime);
    if (dur <= 0) {
      setModalError('End time must be later than start time.');
      return;
    }

    setIsSubmitting(true);
    setModalError(null);

    try {
      if (editingBlock) {
        if (onUpdateTimeBlock) {
          await onUpdateTimeBlock(editingBlock.id, {
            title: modalTitle.trim(),
            date: modalDate,
            start_time: modalStartTime,
            end_time: modalEndTime,
            category_id: modalCategoryId === '' ? null : Number(modalCategoryId),
          });
        } else {
          await api.updateTimeBlock(editingBlock.id, {
            title: modalTitle.trim(),
            date: modalDate,
            start_time: modalStartTime,
            end_time: modalEndTime,
            category_id: modalCategoryId === '' ? null : Number(modalCategoryId),
          });
          onRefresh?.();
        }
      } else {
        await onCreateTimeBlock({
          title: modalTitle.trim(),
          date: modalDate,
          start_time: modalStartTime,
          end_time: modalEndTime,
          category_id: modalCategoryId === '' ? null : Number(modalCategoryId),
        });
      }

      setIsCreateModalOpen(false);
      setEditingBlock(null);
      fetchDailySummary(selectedDate);
    } catch (err: any) {
      setModalError(err?.message || 'Failed to save time block.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Duplicate Block handler
  const handleExecuteDuplicate = async (block: TimeBlockModel, targetDate: string, offsetMins: number) => {
    setIsSubmitting(true);
    try {
      if (onDuplicateTimeBlock) {
        await onDuplicateTimeBlock(block.id, targetDate, offsetMins);
      } else {
        await api.duplicateTimeBlock(block.id, { target_date: targetDate, time_offset_minutes: offsetMins });
        onRefresh?.();
      }
      setDuplicatingBlock(null);
      fetchDailySummary(selectedDate);
    } catch (err: any) {
      alert(err?.message || 'Failed to duplicate time block.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Start Focus Session for a block
  const [startingFocusId, setStartingFocusId] = useState<number | null>(null);
  const handleStartFocus = async (blockId: number) => {
    setStartingFocusId(blockId);
    try {
      if (onStartFocus) {
        await onStartFocus(blockId);
      } else {
        await api.startFocusForTimeBlock(blockId);
        onRefresh?.();
      }
      fetchDailySummary(selectedDate);
    } catch (err: any) {
      alert(err?.message || 'Failed to start focus session for time block.');
    } finally {
      setStartingFocusId(null);
    }
  };

  // Skip a block
  const handleSkip = async (blockId: number) => {
    try {
      if (onSkipTimeBlock) {
        await onSkipTimeBlock(blockId);
      } else {
        await api.skipTimeBlock(blockId);
        onRefresh?.();
      }
      fetchDailySummary(selectedDate);
    } catch (err: any) {
      alert(err?.message || 'Failed to skip time block.');
    }
  };

  // Delete a block with confirmation
  const handleDelete = async (blockId: number, title: string) => {
    if (window.confirm(`Delete time block "${title}"?`)) {
      await onDeleteTimeBlock(blockId);
      fetchDailySummary(selectedDate);
    }
  };

  // Sort blocks chronologically
  const sortedBlocks = useMemo(() => {
    return [...timeBlocks].sort((a, b) => {
      const aStart = a.start_time.slice(0, 5);
      const bStart = b.start_time.slice(0, 5);
      if (aStart !== bStart) return aStart.localeCompare(bStart);
      return a.id - b.id;
    });
  }, [timeBlocks]);

  // Derived metrics from summary or fallback calculation
  const plannedLabel = dailySummary?.planned_label || '0m';
  const focusLabel = dailySummary?.focus_label || '0m';
  const adherencePct = dailySummary?.adherence_pct !== undefined ? Math.round(dailySummary.adherence_pct) : 0;
  const distractionLabel = dailySummary?.distraction_label || '0m';
  const totalBlocksCount = dailySummary?.total_blocks ?? sortedBlocks.length;

  return (
    <div className="view-container timeblocks-view" style={{ maxWidth: 1280, margin: '0 auto', paddingBottom: 60 }}>
      {/* 1. Header & Navigation Row */}
      <div
        className="timeblocks-header-nav"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          marginBottom: 20,
          padding: '16px 20px',
          background: 'rgba(17, 25, 39, 0.7)',
          border: '1px solid var(--border-subtle, #27354A)',
          borderRadius: 14,
          backdropFilter: 'blur(10px)',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
              Time Blocks &amp; Planned Schedules
            </h2>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: '3px 8px',
                borderRadius: 20,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                background: isTracking ? 'rgba(53, 214, 138, 0.15)' : 'rgba(255, 178, 62, 0.15)',
                color: isTracking ? '#35D68A' : '#FFB23E',
                border: `1px solid ${isTracking ? 'rgba(53, 214, 138, 0.3)' : 'rgba(255, 178, 62, 0.3)'}`,
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: isTracking ? '#35D68A' : '#FFB23E',
                }}
              />
              {isTracking ? 'Tracking Active' : 'Tracking Paused'}
            </span>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-secondary, #98A5BA)', margin: '4px 0 0 0' }}>
            Plan structured focus intervals, execute with live sessions, and verify adherence against ground-truth activity.
          </p>
        </div>

        {/* Date Controls & Action Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* Date Picker Controls */}
          {onSelectDate && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                background: 'rgba(23, 33, 49, 0.8)',
                border: '1px solid var(--border-subtle, #27354A)',
                borderRadius: 8,
                padding: '4px 6px',
                gap: 4,
              }}
            >
              <button
                type="button"
                className="btn-icon"
                onClick={() => onSelectDate(addDaysToDateStr(selectedDate, -1))}
                title="Previous Day"
                style={{ padding: '4px 8px', color: 'var(--text-secondary, #98A5BA)' }}
              >
                <ChevronLeftIcon size={16} />
              </button>

              <span
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#EDF0F7',
                  padding: '2px 8px',
                  minWidth: 140,
                  textAlign: 'center',
                }}
              >
                {formatFriendlyDate(selectedDate)}
              </span>

              <button
                type="button"
                className="btn-icon"
                onClick={() => onSelectDate(addDaysToDateStr(selectedDate, 1))}
                title="Next Day"
                style={{ padding: '4px 8px', color: 'var(--text-secondary, #98A5BA)' }}
              >
                <ChevronRightIcon size={16} />
              </button>

              {!isSelectedDateToday && (
                <button
                  type="button"
                  onClick={() => onSelectDate(todayStr)}
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: '3px 8px',
                    marginLeft: 4,
                    borderRadius: 4,
                    background: 'rgba(128, 101, 255, 0.18)',
                    color: '#9B85FF',
                    border: '1px solid rgba(128, 101, 255, 0.3)',
                    cursor: 'pointer',
                  }}
                >
                  Today
                </button>
              )}
            </div>
          )}

          {onNavigateTimeline && (
            <button
              type="button"
              className="btn-secondary"
              onClick={onNavigateTimeline}
              style={{ fontSize: 13, padding: '7px 12px', display: 'flex', alignItems: 'center', gap: 6 }}
              title="Jump to timeline activity evidence for this date"
            >
              <ClockIcon size={15} />
              <span>Activity Evidence</span>
            </button>
          )}

          <button
            type="button"
            className="btn-primary"
            onClick={() => openCreateModal(45)}
            style={{ fontSize: 13, padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <PlusIcon size={15} />
            <span>Create Time Block</span>
          </button>
        </div>
      </div>

      {/* 2. Mental Model Guide Panel */}
      <div
        style={{
          marginBottom: 20,
          background: 'linear-gradient(135deg, rgba(17, 25, 39, 0.85) 0%, rgba(26, 34, 48, 0.6) 100%)',
          border: '1px solid rgba(128, 101, 255, 0.25)',
          borderRadius: 12,
          overflow: 'hidden',
          boxShadow: '0 4px 14px rgba(0,0,0,0.25)',
        }}
      >
        <div
          onClick={toggleMentalModel}
          style={{
            padding: '10px 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            cursor: 'pointer',
            background: 'rgba(128, 101, 255, 0.08)',
            borderBottom: showMentalModel ? '1px solid rgba(128, 101, 255, 0.15)' : 'none',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <SparklesIcon size={16} color="#9B85FF" />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#EDF0F7' }}>
              How Time Blocks &amp; Focus Sessions Work Together
            </span>
            <span style={{ fontSize: 11, color: 'var(--text-muted, #5A6679)' }}>
              (The Plan vs. The Execution vs. The Evidence)
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary, #98A5BA)', fontSize: 12 }}>
            <span>{showMentalModel ? 'Hide Guide' : 'Show Guide'}</span>
            <span
              style={{
                transform: showMentalModel ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.2s ease',
                display: 'inline-block',
              }}
            >
              <ChevronDownIcon size={14} />
            </span>
          </div>
        </div>

        {showMentalModel && (
          <div
            style={{
              padding: '14px 18px',
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              gap: 14,
            }}
          >
            {/* Concept 1 */}
            <div
              style={{
                background: 'rgba(23, 33, 49, 0.5)',
                border: '1px solid rgba(39, 53, 74, 0.7)',
                borderRadius: 8,
                padding: '12px 14px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    background: 'rgba(128, 101, 255, 0.2)',
                    color: '#8065FF',
                  }}
                >
                  <CalendarIcon size={14} />
                </span>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#FFFFFF' }}>1. Time Block = The Plan</span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary, #98A5BA)', margin: 0, lineHeight: 1.5 }}>
                A scheduled commitment: what you intend to work on, when, and under which category or goal (e.g. <em>9:00 – 10:00 AM Backend Development</em>).
              </p>
            </div>

            {/* Concept 2 */}
            <div
              style={{
                background: 'rgba(23, 33, 49, 0.5)',
                border: '1px solid rgba(39, 53, 74, 0.7)',
                borderRadius: 8,
                padding: '12px 14px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    background: 'rgba(22, 213, 226, 0.2)',
                    color: '#16D5E2',
                  }}
                >
                  <PlayIcon size={12} />
                </span>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#FFFFFF' }}>2. Focus Session = The Execution</span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary, #98A5BA)', margin: 0, lineHeight: 1.5 }}>
                A live timer on a task: <em>"I am actively executing this block now."</em> Start directly from any block with one click to keep your focus anchored.
              </p>
            </div>

            {/* Concept 3 */}
            <div
              style={{
                background: 'rgba(23, 33, 49, 0.5)',
                border: '1px solid rgba(39, 53, 74, 0.7)',
                borderRadius: 8,
                padding: '12px 14px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    background: 'rgba(53, 214, 138, 0.2)',
                    color: '#35D68A',
                  }}
                >
                  <TargetIcon size={14} />
                </span>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#FFFFFF' }}>3. Tracked Activity = The Evidence</span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary, #98A5BA)', margin: 0, lineHeight: 1.5 }}>
                Ground truth from your active software &amp; sites. Running a timer alone does not count as work; Plan Adherence is computed from real activity.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* 3. KPI Cards Row (4 Consistent Metrics) */}
      <div className="kpi-cards-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 24 }}>
        {/* KPI 1: Planned Time */}
        <div
          className="kpi-card-rize"
          style={{
            background: 'rgba(17, 25, 39, 0.7)',
            border: '1px solid var(--border-subtle, #27354A)',
            borderRadius: 12,
            padding: '16px 18px',
            position: 'relative',
          }}
          title="Total non-overlapping planned focus time across all scheduled blocks for this date."
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Planned Time
            </span>
            <div className="kpi-icon-circle purple" style={{ width: 32, height: 32 }}>
              <CalendarIcon size={16} color="#8065FF" />
            </div>
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#EDF0F7', fontFamily: 'var(--font-mono)' }}>
            {plannedLabel}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted, #5A6679)', marginTop: 4 }}>
            {totalBlocksCount} scheduled block{totalBlocksCount === 1 ? '' : 's'}
          </div>
        </div>

        {/* KPI 2: Focus in Blocks */}
        <div
          className="kpi-card-rize"
          style={{
            background: 'rgba(17, 25, 39, 0.7)',
            border: '1px solid var(--border-subtle, #27354A)',
            borderRadius: 12,
            padding: '16px 18px',
          }}
          title="Ground-truth active time spent working on tasks matching your scheduled block categories."
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Focus in Blocks
            </span>
            <div className="kpi-icon-circle cyan" style={{ width: 32, height: 32 }}>
              <ClockIcon size={16} color="#16D5E2" />
            </div>
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#EDF0F7', fontFamily: 'var(--font-mono)' }}>
            {focusLabel}
          </div>
          <div style={{ fontSize: 12, color: adherencePct >= 80 ? '#35D68A' : adherencePct >= 50 ? '#FFB23E' : 'var(--text-muted, #5A6679)', marginTop: 4 }}>
            {adherencePct}% of planned time
          </div>
        </div>

        {/* KPI 3: Schedule Adherence */}
        <div
          className="kpi-card-rize"
          style={{
            background: 'rgba(17, 25, 39, 0.7)',
            border: '1px solid var(--border-subtle, #27354A)',
            borderRadius: 12,
            padding: '16px 18px',
          }}
          title="Percentage of scheduled block time verified by active window and task activity."
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Plan Adherence
            </span>
            <div
              className="kpi-icon-circle"
              style={{
                width: 32,
                height: 32,
                background: adherencePct >= 80 ? 'rgba(53, 214, 138, 0.15)' : 'rgba(255, 178, 62, 0.15)',
              }}
            >
              <TargetIcon size={16} color={adherencePct >= 80 ? '#35D68A' : '#FFB23E'} />
            </div>
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#EDF0F7', fontFamily: 'var(--font-mono)' }}>
            {totalBlocksCount === 0 ? '—' : `${adherencePct}%`}
          </div>
          <div style={{ fontSize: 12, color: adherencePct >= 80 ? '#35D68A' : adherencePct >= 50 ? '#FFB23E' : '#FA5275', marginTop: 4 }}>
            {totalBlocksCount === 0
              ? 'No scheduled blocks'
              : adherencePct >= 80
              ? '▲ High flow alignment'
              : adherencePct >= 50
              ? '● Moderate alignment'
              : '▼ Low alignment'}
          </div>
        </div>

        {/* KPI 4: Distraction in Blocks */}
        <div
          className="kpi-card-rize"
          style={{
            background: 'rgba(17, 25, 39, 0.7)',
            border: '1px solid var(--border-subtle, #27354A)',
            borderRadius: 12,
            padding: '16px 18px',
          }}
          title="Time spent on entertainment or unaligned activities during scheduled focus intervals."
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Distraction in Blocks
            </span>
            <div className="kpi-icon-circle coral" style={{ width: 32, height: 32 }}>
              <AlertTriangleIcon size={16} color="#FA5275" />
            </div>
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#EDF0F7', fontFamily: 'var(--font-mono)' }}>
            {distractionLabel}
          </div>
          <div style={{ fontSize: 12, color: distractionLabel === '0m' ? '#35D68A' : '#FA5275', marginTop: 4 }}>
            {distractionLabel === '0m' ? 'Zero leakage' : 'Leakage detected'}
          </div>
        </div>
      </div>

      {/* 4. Central Chronological Schedule List */}
      <div
        className="card-panel"
        style={{
          background: 'rgba(17, 25, 39, 0.7)',
          border: '1px solid var(--border-subtle, #27354A)',
          borderRadius: 14,
          padding: 24,
          backdropFilter: 'blur(10px)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 20,
            borderBottom: '1px solid rgba(39, 53, 74, 0.6)',
            paddingBottom: 14,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <CalendarIcon size={18} color="#8065FF" />
            <h3 style={{ fontSize: 16, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
              Chronological Schedule — {formatFriendlyDate(selectedDate)}
            </h3>
            <span
              style={{
                fontSize: 12,
                padding: '2px 8px',
                borderRadius: 12,
                background: 'rgba(128, 101, 255, 0.15)',
                color: '#9B85FF',
                fontWeight: 600,
              }}
            >
              {sortedBlocks.length} Block{sortedBlocks.length === 1 ? '' : 's'}
            </span>
          </div>

          <button
            type="button"
            className="btn-secondary"
            onClick={() => openCreateModal(45)}
            style={{ fontSize: 12, padding: '5px 12px', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <PlusIcon size={14} />
            <span>Add Block</span>
          </button>
        </div>

        {/* Empty State */}
        {sortedBlocks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '50px 20px', color: 'var(--text-muted, #5A6679)' }}>
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: '50%',
                background: 'rgba(128, 101, 255, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px auto',
              }}
            >
              <CalendarIcon size={28} color="#8065FF" />
            </div>
            <h4 style={{ fontSize: 16, fontWeight: 600, color: '#EDF0F7', margin: '0 0 6px 0' }}>
              No time blocks scheduled for {formatFriendlyDate(selectedDate)}
            </h4>
            <p style={{ fontSize: 13, color: 'var(--text-secondary, #98A5BA)', maxWidth: 440, margin: '0 auto 20px auto', lineHeight: 1.5 }}>
              Structure your day into intentional focus blocks. Start a block to stay focused on deep work and get notified when you drift off-course.
            </p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 10 }}>
              <button
                type="button"
                className="btn-primary"
                onClick={() => openCreateModal(25, 'Pomodoro Sprint')}
                style={{ fontSize: 13, padding: '8px 16px' }}
              >
                + Plan 25m Pomodoro
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openCreateModal(50, 'Deep Work Session')}
                style={{ fontSize: 13, padding: '8px 16px' }}
              >
                + Plan 50m Deep Work
              </button>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {sortedBlocks.map((block) => {
              const cat = categories.find((c) => c.id === block.category_id);
              const analysis = timeBlocksAnalysis.find((a) => a.block_id === block.id);
              const durationMins = calculateDurationMinutes(block.start_time, block.end_time);
              const durationLabel = formatDurationLabel(durationMins);
              const timeDisplay = block.display_time_label || formatTimeRange(block.start_time, block.end_time);

              // Status
              const status = analysis?.status || 'Upcoming';
              const matchPct = analysis?.match_pct !== undefined ? Math.round(analysis.match_pct) : 0;
              const isCurrent = analysis?.is_current || false;
              const isActiveFocus = analysis?.is_active_focus || (activeTask && activeTask.user_task === block.title);

              // Category styling
              const categoryColor = cat?.color || block.category_color || '#8065FF';
              const categoryName = cat?.name || block.category_name || 'General Work';

              return (
                <div
                  key={block.id}
                  style={{
                    background: isCurrent ? 'rgba(22, 213, 226, 0.05)' : 'rgba(23, 33, 49, 0.65)',
                    border: isCurrent
                      ? '1px solid rgba(22, 213, 226, 0.4)'
                      : '1px solid rgba(39, 53, 74, 0.65)',
                    borderLeft: `4px solid ${categoryColor}`,
                    borderRadius: 10,
                    padding: '16px 20px',
                    transition: 'all 0.2s ease',
                    position: 'relative',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 14,
                    }}
                  >
                    {/* Left: Time & Block Details */}
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, flex: 1, minWidth: 260 }}>
                      <div
                        style={{
                          width: 42,
                          height: 42,
                          borderRadius: 8,
                          backgroundColor: `${categoryColor}18`,
                          border: `1px solid ${categoryColor}40`,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: categoryColor,
                          flexShrink: 0,
                          marginTop: 2,
                        }}
                      >
                        <ClockIcon size={20} />
                      </div>

                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                          <span style={{ fontSize: 16, fontWeight: 700, color: '#EDF0F7' }}>
                            {block.title}
                          </span>

                          {/* Category Badge */}
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: '2px 8px',
                              borderRadius: 4,
                              backgroundColor: `${categoryColor}22`,
                              color: categoryColor,
                              border: `1px solid ${categoryColor}44`,
                            }}
                          >
                            {categoryName}
                          </span>

                          {/* Dynamic Status Badge */}
                          {status === 'In Progress' && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 700,
                                padding: '2px 8px',
                                borderRadius: 4,
                                backgroundColor: 'rgba(22, 213, 226, 0.18)',
                                color: '#16D5E2',
                                border: '1px solid rgba(22, 213, 226, 0.4)',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                              }}
                            >
                              <span
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: '50%',
                                  background: '#16D5E2',
                                  animation: 'pulse 1.5s infinite',
                                }}
                              />
                              In Progress
                            </span>
                          )}

                          {status === 'Completed' && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                backgroundColor: 'rgba(53, 214, 138, 0.15)',
                                color: '#35D68A',
                                border: '1px solid rgba(53, 214, 138, 0.3)',
                              }}
                            >
                              Completed ({matchPct}% Match)
                            </span>
                          )}

                          {status === 'Partial' && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                backgroundColor: 'rgba(255, 178, 62, 0.15)',
                                color: '#FFB23E',
                                border: '1px solid rgba(255, 178, 62, 0.3)',
                              }}
                            >
                              Partial ({matchPct}% Match)
                            </span>
                          )}

                          {status === 'Missed' && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                backgroundColor: 'rgba(250, 82, 117, 0.15)',
                                color: '#FA5275',
                                border: '1px solid rgba(250, 82, 117, 0.3)',
                              }}
                            >
                              Missed (0% Match)
                            </span>
                          )}

                          {status === 'Skipped' && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                backgroundColor: 'rgba(90, 102, 121, 0.2)',
                                color: '#98A5BA',
                              }}
                            >
                              Skipped
                            </span>
                          )}

                          {status === 'Upcoming' && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                backgroundColor: 'rgba(128, 101, 255, 0.12)',
                                color: '#9B85FF',
                              }}
                            >
                              Upcoming
                            </span>
                          )}

                          {/* Active Focus Session Badge */}
                          {isActiveFocus && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 700,
                                padding: '2px 8px',
                                borderRadius: 4,
                                backgroundColor: 'rgba(22, 213, 226, 0.22)',
                                color: '#16D5E2',
                                border: '1px solid #16D5E2',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                              }}
                            >
                              ⚡ Focus Session Running
                            </span>
                          )}
                        </div>

                        {/* Localized Time Range & Duration */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: 'var(--text-secondary, #98A5BA)' }}>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#EDF0F7' }}>
                            {timeDisplay}
                          </span>
                          <span>•</span>
                          <span>{durationLabel}</span>
                          {analysis && analysis.matching_seconds > 0 && (
                            <>
                              <span>•</span>
                              <span style={{ color: '#35D68A', fontWeight: 600 }}>
                                {analysis.matching_label} active focus
                              </span>
                            </>
                          )}
                          {analysis && analysis.distraction_seconds > 0 && (
                            <>
                              <span>•</span>
                              <span style={{ color: '#FA5275' }}>
                                {analysis.distraction_label} distraction
                              </span>
                            </>
                          )}
                        </div>

                        {/* Observed Apps preview pills */}
                        {analysis && analysis.observed_apps && analysis.observed_apps.length > 0 && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                            <span style={{ fontSize: 11, color: 'var(--text-muted, #5A6679)' }}>Observed:</span>
                            {analysis.observed_apps.map((app) => (
                              <span
                                key={app}
                                style={{
                                  fontSize: 11,
                                  padding: '1px 6px',
                                  borderRadius: 4,
                                  background: 'rgba(39, 53, 74, 0.6)',
                                  color: 'var(--text-secondary, #98A5BA)',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                }}
                              >
                                <AppIconHelper app={app} size={12} />
                                <span>{app}</span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Right: Actions */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      {/* Start Focus Session Button */}
                      {!isActiveFocus && (status === 'In Progress' || status === 'Upcoming') && (
                        <button
                          type="button"
                          className="btn-primary"
                          onClick={() => handleStartFocus(block.id)}
                          disabled={startingFocusId === block.id}
                          style={{
                            fontSize: 12,
                            padding: '6px 12px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                            background: 'linear-gradient(135deg, #16D5E2 0%, #398BFF 100%)',
                            color: '#080D17',
                            fontWeight: 700,
                            border: 'none',
                          }}
                          title="Start live Focus Session on this scheduled block"
                        >
                          <PlayIcon size={12} />
                          <span>{startingFocusId === block.id ? 'Starting...' : 'Start Focus'}</span>
                        </button>
                      )}

                      {/* Missed block resolution actions */}
                      {status === 'Missed' && (
                        <>
                          <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => openEditModal(block)}
                            style={{ fontSize: 11, padding: '4px 8px' }}
                            title="Reschedule block for another time"
                          >
                            Reschedule
                          </button>
                          <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => handleSkip(block.id)}
                            style={{ fontSize: 11, padding: '4px 8px', color: 'var(--text-muted, #5A6679)' }}
                            title="Dismiss reminder without logging fake work"
                          >
                            Skip
                          </button>
                          {onNavigateTimeline && (
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={onNavigateTimeline}
                              style={{ fontSize: 11, padding: '4px 8px', color: '#16D5E2' }}
                              title="Review what happened during this interval"
                            >
                              Review Evidence
                            </button>
                          )}
                        </>
                      )}

                      {/* Edit / Reschedule */}
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => openEditModal(block)}
                        title="Edit or Reschedule"
                        style={{
                          color: 'var(--text-secondary, #98A5BA)',
                          padding: '6px 8px',
                          borderRadius: 6,
                          background: 'rgba(39, 53, 74, 0.4)',
                        }}
                      >
                        <EditIcon size={15} />
                      </button>

                      {/* Duplicate Block */}
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => setDuplicatingBlock(block)}
                        title="Duplicate Time Block"
                        style={{
                          color: 'var(--text-secondary, #98A5BA)',
                          padding: '6px 8px',
                          borderRadius: 6,
                          background: 'rgba(39, 53, 74, 0.4)',
                        }}
                      >
                        <CopyIcon size={15} />
                      </button>

                      {/* Delete Block */}
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => handleDelete(block.id, block.title)}
                        title="Delete Time Block"
                        style={{
                          color: '#FA5275',
                          padding: '6px 8px',
                          borderRadius: 6,
                          background: 'rgba(250, 82, 117, 0.1)',
                        }}
                      >
                        <TrashIcon size={15} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 5. Create / Edit / Reschedule Modal */}
      {isCreateModalOpen && (
        <div
          className="modal-backdrop"
          onClick={() => {
            if (!isSubmitting) {
              setIsCreateModalOpen(false);
              setEditingBlock(null);
            }
          }}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(8, 13, 23, 0.75)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 20,
          }}
        >
          <div
            className="modal-content"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#111927',
              border: '1px solid var(--border-strong, #33435C)',
              borderRadius: 14,
              width: '100%',
              maxWidth: 480,
              padding: 24,
              boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <CalendarIcon size={18} color="#8065FF" />
                <h3 style={{ fontSize: 18, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
                  {editingBlock ? 'Edit / Reschedule Time Block' : 'Create Time Block'}
                </h3>
              </div>
              <button
                type="button"
                className="btn-icon"
                onClick={() => {
                  setIsCreateModalOpen(false);
                  setEditingBlock(null);
                }}
                disabled={isSubmitting}
                style={{ color: 'var(--text-muted, #5A6679)' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveModal}>
              {/* Quick Presets */}
              {!editingBlock && (
                <div style={{ marginBottom: 16 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', marginBottom: 6 }}>
                    Quick Presets
                  </label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      style={{ fontSize: 12, padding: '5px 10px', flex: 1 }}
                      onClick={() => {
                        const now = new Date();
                        const pad = (n: number) => String(n).padStart(2, '0');
                        setModalStartTime(`${pad(now.getHours())}:${pad(now.getMinutes())}`);
                        const end = new Date(now.getTime() + 25 * 60000);
                        setModalEndTime(`${pad(end.getHours())}:${pad(end.getMinutes())}`);
                        if (!modalTitle) setModalTitle('Pomodoro Focus');
                      }}
                    >
                      25m Pomodoro
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      style={{ fontSize: 12, padding: '5px 10px', flex: 1 }}
                      onClick={() => {
                        const now = new Date();
                        const pad = (n: number) => String(n).padStart(2, '0');
                        setModalStartTime(`${pad(now.getHours())}:${pad(now.getMinutes())}`);
                        const end = new Date(now.getTime() + 50 * 60000);
                        setModalEndTime(`${pad(end.getHours())}:${pad(end.getMinutes())}`);
                        if (!modalTitle) setModalTitle('Deep Work Session');
                      }}
                    >
                      50m Deep Work
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      style={{ fontSize: 12, padding: '5px 10px', flex: 1 }}
                      onClick={() => {
                        const now = new Date();
                        const pad = (n: number) => String(n).padStart(2, '0');
                        setModalStartTime(`${pad(now.getHours())}:${pad(now.getMinutes())}`);
                        const end = new Date(now.getTime() + 90 * 60000);
                        setModalEndTime(`${pad(end.getHours())}:${pad(end.getMinutes())}`);
                        if (!modalTitle) setModalTitle('Sprint Focus');
                      }}
                    >
                      90m Sprint
                    </button>
                  </div>
                </div>
              )}

              {/* Title Input */}
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', marginBottom: 6 }}>
                  Block Title / Task Name *
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. Backend API Optimization, LeetCode, Study"
                  value={modalTitle}
                  onChange={(e) => setModalTitle(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    background: 'rgba(23, 33, 49, 0.8)',
                    border: '1px solid var(--border-subtle, #27354A)',
                    borderRadius: 8,
                    color: '#FFFFFF',
                    fontSize: 14,
                  }}
                />
              </div>

              {/* Date Input */}
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', marginBottom: 6 }}>
                  Scheduled Date
                </label>
                <input
                  type="date"
                  className="input-field"
                  value={modalDate}
                  onChange={(e) => setModalDate(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'rgba(23, 33, 49, 0.8)',
                    border: '1px solid var(--border-subtle, #27354A)',
                    borderRadius: 8,
                    color: '#FFFFFF',
                    fontSize: 13,
                  }}
                />
              </div>

              {/* Start & End Times */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', marginBottom: 6 }}>
                    Start Time
                  </label>
                  <input
                    type="time"
                    className="input-field"
                    value={modalStartTime}
                    onChange={(e) => setModalStartTime(e.target.value)}
                    required
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      background: 'rgba(23, 33, 49, 0.8)',
                      border: '1px solid var(--border-subtle, #27354A)',
                      borderRadius: 8,
                      color: '#FFFFFF',
                      fontSize: 14,
                      fontFamily: 'var(--font-mono)',
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', marginBottom: 6 }}>
                    End Time
                  </label>
                  <input
                    type="time"
                    className="input-field"
                    value={modalEndTime}
                    onChange={(e) => setModalEndTime(e.target.value)}
                    required
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      background: 'rgba(23, 33, 49, 0.8)',
                      border: '1px solid var(--border-subtle, #27354A)',
                      borderRadius: 8,
                      color: '#FFFFFF',
                      fontSize: 14,
                      fontFamily: 'var(--font-mono)',
                    }}
                  />
                </div>
              </div>

              {/* Duration calculation info */}
              <div style={{ fontSize: 12, color: 'var(--text-muted, #5A6679)', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 }}>
                <ClockIcon size={14} />
                <span>
                  Duration: {formatDurationLabel(calculateDurationMinutes(modalStartTime, modalEndTime))} ({formatTimeRange(modalStartTime, modalEndTime)})
                </span>
              </div>

              {/* Category Dropdown */}
              <div style={{ marginBottom: 18 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary, #98A5BA)', marginBottom: 6 }}>
                  Target Category
                </label>
                <select
                  className="input-field select-field"
                  value={modalCategoryId}
                  onChange={(e) => setModalCategoryId(e.target.value ? Number(e.target.value) : '')}
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    background: 'rgba(23, 33, 49, 0.8)',
                    border: '1px solid var(--border-subtle, #27354A)',
                    borderRadius: 8,
                    color: '#FFFFFF',
                    fontSize: 13,
                  }}
                >
                  <option value="">No Category (Any Focused Work)</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.type})
                    </option>
                  ))}
                </select>
              </div>

              {/* Overlap Warning Banner */}
              {overlapWarning && (
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    marginBottom: 16,
                    fontSize: 12,
                    lineHeight: 1.4,
                    backgroundColor: 'rgba(255, 178, 62, 0.12)',
                    color: '#FFB23E',
                    border: '1px solid rgba(255, 178, 62, 0.3)',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 8,
                  }}
                >
                  <AlertTriangleIcon size={16} color="#FFB23E" style={{ flexShrink: 0, marginTop: 2 }} />
                  <span>{overlapWarning}</span>
                </div>
              )}

              {/* Error Message */}
              {modalError && (
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    marginBottom: 16,
                    fontSize: 12,
                    backgroundColor: 'rgba(250, 82, 117, 0.15)',
                    color: '#FA5275',
                    border: '1px solid rgba(250, 82, 117, 0.3)',
                  }}
                >
                  {modalError}
                </div>
              )}

              {/* Buttons */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    setIsCreateModalOpen(false);
                    setEditingBlock(null);
                  }}
                  disabled={isSubmitting}
                  style={{ padding: '8px 16px', fontSize: 13 }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={isSubmitting || !modalTitle.trim()}
                  style={{ padding: '8px 20px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  {isSubmitting ? (
                    <span>Saving...</span>
                  ) : (
                    <>
                      <CheckIcon size={14} />
                      <span>{editingBlock ? 'Update Block' : 'Schedule Block'}</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 6. Duplicate Time Block Modal */}
      {duplicatingBlock && (
        <div
          className="modal-backdrop"
          onClick={() => {
            if (!isSubmitting) setDuplicatingBlock(null);
          }}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(8, 13, 23, 0.75)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 20,
          }}
        >
          <div
            className="modal-content"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#111927',
              border: '1px solid var(--border-strong, #33435C)',
              borderRadius: 14,
              width: '100%',
              maxWidth: 420,
              padding: 24,
              boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <CopyIcon size={18} color="#8065FF" />
              <h3 style={{ fontSize: 17, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
                Duplicate Time Block
              </h3>
            </div>
            <p style={{ fontSize: 13, color: 'var(--text-secondary, #98A5BA)', margin: '0 0 16px 0' }}>
              Duplicate <strong>"{duplicatingBlock.title}"</strong> ({duplicatingBlock.display_time_label || formatTimeRange(duplicatingBlock.start_time, duplicatingBlock.end_time)}).
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
              <button
                type="button"
                className="btn-secondary"
                disabled={isSubmitting}
                onClick={() => handleExecuteDuplicate(duplicatingBlock, addDaysToDateStr(duplicatingBlock.date, 1), 0)}
                style={{ justifyContent: 'flex-start', padding: '10px 14px', fontSize: 13 }}
              >
                📅 Duplicate to Tomorrow ({addDaysToDateStr(duplicatingBlock.date, 1)})
              </button>

              <button
                type="button"
                className="btn-secondary"
                disabled={isSubmitting}
                onClick={() => handleExecuteDuplicate(duplicatingBlock, duplicatingBlock.date, 60)}
                style={{ justifyContent: 'flex-start', padding: '10px 14px', fontSize: 13 }}
              >
                ⏰ Duplicate for Later Today (+1 Hour)
              </button>

              <button
                type="button"
                className="btn-secondary"
                disabled={isSubmitting}
                onClick={() => handleExecuteDuplicate(duplicatingBlock, duplicatingBlock.date, 0)}
                style={{ justifyContent: 'flex-start', padding: '10px 14px', fontSize: 13 }}
              >
                📋 Exact Clone on Same Day
              </button>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDuplicatingBlock(null)}
                disabled={isSubmitting}
                style={{ padding: '7px 14px', fontSize: 13 }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
