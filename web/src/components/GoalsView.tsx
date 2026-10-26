import React, { useState } from 'react';
import type {
  CategoryModel,
  GoalModel,
  GoalProgressModel,
  TimeBlockAnalysisModel,
  TimeBlockModel,
} from '../types';
import {
  ClockIcon,
  CloseIcon,
  PlusIcon,
  TargetIcon,
  TrashIcon,
} from './Icons';

interface GoalsViewProps {
  goals: GoalModel[];
  goalsProgress: GoalProgressModel[];
  timeBlocks: TimeBlockModel[];
  timeBlocksAnalysis: TimeBlockAnalysisModel[];
  categories: CategoryModel[];
  selectedDate: string;
  onCreateGoal: (data: {
    title: string;
    metric: string;
    target_seconds: number;
    is_inversion: boolean;
    category_id?: number | null;
  }) => Promise<void>;
  onDeleteGoal: (id: number) => Promise<void>;
  onCreateTimeBlock: (data: {
    date: string;
    start_time: string;
    end_time: string;
    title: string;
    category_id?: number | null;
  }) => Promise<void>;
  onDeleteTimeBlock: (id: number) => Promise<void>;
}

export const GoalsView: React.FC<GoalsViewProps> = ({
  goals: _goals = [],
  goalsProgress = [],
  timeBlocks: _timeBlocks = [],
  timeBlocksAnalysis = [],
  categories = [],
  selectedDate,
  onCreateGoal,
  onDeleteGoal,
  onCreateTimeBlock,
  onDeleteTimeBlock,
}) => {
  const safeGoalsProgress = goalsProgress || [];
  const safeTimeBlocksAnalysis = timeBlocksAnalysis || [];
  const safeCategories = categories || [];
  const [showGoalModal, setShowGoalModal] = useState(false);
  const [showBlockModal, setShowBlockModal] = useState(false);

  // Goal Form State
  const [goalTitle, setGoalTitle] = useState('');
  const [goalMetric, setGoalMetric] = useState('work_time');
  const [goalHours, setGoalHours] = useState('4');
  const [goalMinutes, setGoalMinutes] = useState('0');
  const [goalIsInversion, setGoalIsInversion] = useState(false);
  const [goalCategoryId, setGoalCategoryId] = useState<string>('');

  // Time Block Form State
  const [blockTitle, setBlockTitle] = useState('');
  const [blockStart, setBlockStart] = useState('09:00');
  const [blockEnd, setBlockEnd] = useState('11:00');
  const [blockCategoryId, setBlockCategoryId] = useState<string>('');

  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleGoalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!goalTitle.trim()) return;
    const targetSeconds = (parseInt(goalHours || '0', 10) * 3600) + (parseInt(goalMinutes || '0', 10) * 60);
    if (targetSeconds <= 0) return;

    setIsSubmitting(true);
    try {
      await onCreateGoal({
        title: goalTitle.trim(),
        metric: goalMetric,
        target_seconds: targetSeconds,
        is_inversion: goalIsInversion,
        category_id: goalCategoryId ? parseInt(goalCategoryId, 10) : null,
      });
      setShowGoalModal(false);
      setGoalTitle('');
      setGoalHours('4');
      setGoalMinutes('0');
      setGoalIsInversion(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleBlockSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!blockTitle.trim()) return;

    setIsSubmitting(true);
    try {
      await onCreateTimeBlock({
        date: selectedDate,
        start_time: blockStart,
        end_time: blockEnd,
        title: blockTitle.trim(),
        category_id: blockCategoryId ? parseInt(blockCategoryId, 10) : null,
      });
      setShowBlockModal(false);
      setBlockTitle('');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="goals-view-container">
      {/* ---------------- 1. PRODUCTIVITY GOALS SECTION ---------------- */}
      <div className="section-header">
        <div className="section-title-wrap">
          <TargetIcon size={20} color="var(--accent-teal)" />
          <h2>Productivity Goals</h2>
        </div>
        <button className="btn-primary" onClick={() => setShowGoalModal(true)}>
          <PlusIcon size={14} />
          <span>New Goal</span>
        </button>
      </div>

      <div className="goals-grid">
        {safeGoalsProgress.length === 0 ? (
          <div className="empty-panel">
            <p>No active goals configured. Click "New Goal" to set daily work or focus targets.</p>
          </div>
        ) : (
          safeGoalsProgress.map((p) => {
            const isAchieved = p.is_achieved;
            const isInversion = p.is_inversion;
            return (
              <div key={p.id} className="goal-card">
                <div className="goal-card-header">
                  <div>
                    <span className="goal-card-title">{p.title}</span>
                    <span className="goal-metric-badge">
                      {p.metric.replace('_', ' ')}
                      {isInversion ? ' (Limit Goal)' : ''}
                    </span>
                  </div>
                  <button
                    className="btn-icon-danger"
                    onClick={() => onDeleteGoal(p.id)}
                    title="Delete goal"
                  >
                    <TrashIcon size={14} />
                  </button>
                </div>

                <div className="goal-metric-numbers">
                  <span className="actual-time">{p.actual_label}</span>
                  <span className="target-time">/ {p.target_label}</span>
                </div>

                <div className="progress-bar-container">
                  <div
                    className={`progress-bar-fill ${isInversion ? 'inversion' : ''}`}
                    style={{
                      width: `${Math.min(100, p.progress_pct)}%`,
                      backgroundColor: isAchieved ? 'var(--accent-teal)' : isInversion ? '#ef4444' : 'var(--accent-violet)',
                    }}
                  />
                </div>

                <div className="goal-footer">
                  <span className={`status-pill ${isAchieved ? 'success' : isInversion ? 'danger' : 'neutral'}`}>
                    {isAchieved ? '✓ Target Achieved' : isInversion ? 'Limit Exceeded' : 'In Progress'}
                  </span>
                  <span className="status-note">{p.status_text}</span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* ---------------- 2. TIME BLOCKING SECTION ---------------- */}
      <div className="section-header" style={{ marginTop: '40px' }}>
        <div className="section-title-wrap">
          <ClockIcon size={20} color="var(--accent-violet)" />
          <h2>Time Blocking & Planned vs Actual Activity</h2>
          <span className="date-subtag">for {selectedDate}</span>
        </div>
        <button className="btn-secondary" onClick={() => setShowBlockModal(true)}>
          <PlusIcon size={14} />
          <span>Plan Time Block</span>
        </button>
      </div>

      <div className="timeblocks-analysis-grid">
        {safeTimeBlocksAnalysis.length === 0 ? (
          <div className="empty-panel">
            <p>No time blocks scheduled for {selectedDate}. Plan a block above to verify actual tracked focus against your schedule.</p>
          </div>
        ) : (
          safeTimeBlocksAnalysis.map((ba) => {
            const statusClass =
              ba.status === 'Completed'
                ? 'status-completed'
                : ba.status === 'Partial'
                ? 'status-partial'
                : ba.status === 'Interrupted'
                ? 'status-interrupted'
                : 'status-missed';

            return (
              <div key={ba.block_id} className="timeblock-card">
                <div className="timeblock-header">
                  <div className="timeblock-time-range">
                    <ClockIcon size={14} />
                    <span>{ba.start_time} – {ba.end_time}</span>
                    <span className="block-duration">({ba.planned_label})</span>
                  </div>
                  <div className="timeblock-actions">
                    <span className={`block-status-badge ${statusClass}`}>
                      {ba.status} ({ba.match_pct}%)
                    </span>
                    <button
                      className="btn-icon-danger"
                      onClick={() => onDeleteTimeBlock(ba.block_id)}
                      title="Delete block"
                    >
                      <TrashIcon size={13} />
                    </button>
                  </div>
                </div>

                <h4 className="timeblock-title">{ba.title}</h4>
                {ba.category_name && (
                  <span className="block-category-pill" style={{ borderColor: ba.category_color || '#8b5cf6' }}>
                    Category: {ba.category_name}
                  </span>
                )}

                <div className="timeblock-stats-row">
                  <div className="stat-col">
                    <span className="stat-label">Matching Focus</span>
                    <span className="stat-val highlight">{ba.matching_label}</span>
                  </div>
                  <div className="stat-col">
                    <span className="stat-label">Distractions</span>
                    <span className="stat-val" style={{ color: ba.distraction_seconds > 180 ? '#ef4444' : 'inherit' }}>
                      {ba.distraction_label}
                    </span>
                  </div>
                  <div className="stat-col">
                    <span className="stat-label">Interruptions</span>
                    <span className="stat-val">{ba.interruptions}</span>
                  </div>
                </div>

                {ba.observed_apps && ba.observed_apps.length > 0 && (
                  <div className="observed-apps-row">
                    <span className="observed-label">Apps during block:</span>
                    <div className="observed-chips">
                      {ba.observed_apps.map((app) => (
                        <span key={app} className="chip">{app}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* ---------------- CREATE GOAL MODAL ---------------- */}
      {showGoalModal && (
        <div className="modal-overlay" onClick={() => setShowGoalModal(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Productivity Goal</h3>
              <button className="btn-close" onClick={() => setShowGoalModal(false)}>
                <CloseIcon size={18} />
              </button>
            </div>

            <form onSubmit={handleGoalSubmit}>
              <div className="form-group">
                <label>Goal Title</label>
                <input
                  type="text"
                  placeholder="e.g. Daily Deep Work"
                  value={goalTitle}
                  onChange={(e) => setGoalTitle(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label>Metric</label>
                <select value={goalMetric} onChange={(e) => setGoalMetric(e.target.value)}>
                  <option value="work_time">Total Work Time</option>
                  <option value="focus_time">Deep Focus Time</option>
                  <option value="distraction_time">Distraction Limit</option>
                  <option value="category_time">Specific Category Time</option>
                </select>
              </div>

              {goalMetric === 'category_time' && (
                <div className="form-group">
                  <label>Select Category</label>
                  <select value={goalCategoryId} onChange={(e) => setGoalCategoryId(e.target.value)} required>
                    <option value="">-- Choose Category --</option>
                    {safeCategories.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className="form-row">
                <div className="form-group">
                  <label>Hours</label>
                  <input
                    type="number"
                    min="0"
                    max="24"
                    value={goalHours}
                    onChange={(e) => setGoalHours(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label>Minutes</label>
                  <input
                    type="number"
                    min="0"
                    max="59"
                    value={goalMinutes}
                    onChange={(e) => setGoalMinutes(e.target.value)}
                  />
                </div>
              </div>

              <div className="form-group checkbox-group">
                <label>
                  <input
                    type="checkbox"
                    checked={goalIsInversion || goalMetric === 'distraction_time'}
                    onChange={(e) => setGoalIsInversion(e.target.checked)}
                  />
                  <span>Inversion Goal (Success means staying BELOW this limit)</span>
                </label>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setShowGoalModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={isSubmitting}>
                  {isSubmitting ? 'Saving...' : 'Create Goal'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ---------------- CREATE TIME BLOCK MODAL ---------------- */}
      {showBlockModal && (
        <div className="modal-overlay" onClick={() => setShowBlockModal(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Plan Time Block for {selectedDate}</h3>
              <button className="btn-close" onClick={() => setShowBlockModal(false)}>
                <CloseIcon size={18} />
              </button>
            </div>

            <form onSubmit={handleBlockSubmit}>
              <div className="form-group">
                <label>Block Title</label>
                <input
                  type="text"
                  placeholder="e.g. Core Feature Implementation"
                  value={blockTitle}
                  onChange={(e) => setBlockTitle(e.target.value)}
                  required
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Start Time (HH:MM)</label>
                  <input
                    type="time"
                    value={blockStart}
                    onChange={(e) => setBlockStart(e.target.value)}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>End Time (HH:MM)</label>
                  <input
                    type="time"
                    value={blockEnd}
                    onChange={(e) => setBlockEnd(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Target Category (Optional)</label>
                <select value={blockCategoryId} onChange={(e) => setBlockCategoryId(e.target.value)}>
                  <option value="">Any Focus Activity</option>
                  {safeCategories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.type})</option>
                  ))}
                </select>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setShowBlockModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={isSubmitting}>
                  {isSubmitting ? 'Saving...' : 'Save Block'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
