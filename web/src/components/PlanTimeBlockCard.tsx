import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { type CategoryModel, getLocalTodayString } from '../types';
import { CalendarIcon, ClockIcon, EditIcon } from './Icons';

interface PlanTimeBlockCardProps {
  categories: CategoryModel[];
  selectedDate: string;
  onBlockCreated: () => void;
}

export const PlanTimeBlockCard: React.FC<PlanTimeBlockCardProps> = ({
  categories,
  selectedDate,
  onBlockCreated,
}) => {
  const [activeTab, setActiveTab] = useState<'quick' | 'custom'>('quick');
  const [title, setTitle] = useState('');
  const [categoryId, setCategoryId] = useState<number | ''>(
    categories.length > 0 ? categories[0].id : ''
  );

  // Time state
  const [startTimeStr, setStartTimeStr] = useState<string>('21:48');
  const [isEditingStartTime, setIsEditingStartTime] = useState<boolean>(false);
  const [selectedDurationMins, setSelectedDurationMins] = useState<number>(50);
  const [isCustomDuration, setIsCustomDuration] = useState<boolean>(false);
  const [customMinsInput, setCustomMinsInput] = useState<number>(45);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Default presets matching Image A
  const presets = [
    { mins: 25, label: '25 min', sub: 'Focus' },
    { mins: 50, label: '50 min', sub: 'Deep Work' },
    { mins: 90, label: '90 min', sub: 'Long' },
  ];

  // Set default start time to machine-local current time
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      setStartTimeStr(`${hh}:${mm}`);
    };
    updateTime();
  }, []);

  const effectiveMinutes = isCustomDuration ? customMinsInput : selectedDurationMins;

  const calculateEndTime = (startHHMM: string, addMinutes: number): string => {
    try {
      const [hStr, mStr] = startHHMM.split(':');
      let totalMins = parseInt(hStr, 10) * 60 + parseInt(mStr, 10) + addMinutes;
      totalMins = totalMins % (24 * 60);
      const endH = Math.floor(totalMins / 60);
      const endM = totalMins % 60;
      return `${String(endH).padStart(2, '0')}:${String(endM).padStart(2, '0')}`;
    } catch {
      return '22:38';
    }
  };

  const endTimeStr = calculateEndTime(startTimeStr, effectiveMinutes);

  const handleSelectPreset = (mins: number) => {
    setIsCustomDuration(false);
    setSelectedDurationMins(mins);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setErrorMsg('Please enter a task / block title.');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const baseDate = selectedDate || getLocalTodayString();
      const startIso = `${baseDate}T${startTimeStr}:00`;
      const endIso = `${baseDate}T${endTimeStr}:00`;

      await api.createTimeBlock(
        baseDate,
        startIso,
        endIso,
        title.trim(),
        categoryId === '' ? undefined : Number(categoryId)
      );

      setTitle('');
      setSuccessMsg('Time block scheduled!');
      setTimeout(() => setSuccessMsg(null), 3000);
      onBlockCreated();
    } catch (err: any) {
      setErrorMsg(err?.message || 'Failed to save time block.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="card-panel plan-time-block-card-embedded">
      {/* Header */}
      <div className="panel-header" style={{ marginBottom: 12 }}>
        <div className="panel-title-group">
          <CalendarIcon size={16} color="var(--accent-purple, #8065FF)" />
          <h3 className="panel-title">Plan Time Block</h3>
        </div>
      </div>

      {/* Tabs: Quick Add | Custom Time */}
      <div className="plan-block-tabs-row" style={{ marginBottom: 14 }}>
        <button
          type="button"
          className={`plan-tab-btn ${activeTab === 'quick' ? 'active' : ''}`}
          onClick={() => setActiveTab('quick')}
        >
          Quick Add
        </button>
        <button
          type="button"
          className={`plan-tab-btn ${activeTab === 'custom' ? 'active' : ''}`}
          onClick={() => setActiveTab('custom')}
        >
          Custom Time
        </button>
      </div>

      <form onSubmit={handleSubmit} className="plan-block-form">
        {/* Start Time */}
        <div className="plan-form-section">
          <span className="plan-section-label">Start Time</span>
          <div className="start-time-pill-row">
            <div className="start-time-display-pill">
              <ClockIcon size={14} color="var(--text-secondary)" />
              {isEditingStartTime ? (
                <input
                  type="time"
                  className="start-time-input"
                  value={startTimeStr}
                  onChange={(e) => setStartTimeStr(e.target.value)}
                  onBlur={() => setIsEditingStartTime(false)}
                  autoFocus
                />
              ) : (
                <span className="start-time-text">
                  Now ({startTimeStr})
                </span>
              )}
            </div>
            <button
              type="button"
              className="btn-edit-time"
              onClick={() => setIsEditingStartTime(!isEditingStartTime)}
              title="Edit start time"
            >
              <EditIcon size={13} />
            </button>
          </div>
        </div>

        {/* Duration Pills */}
        <div className="plan-form-section">
          <span className="plan-section-label">Duration</span>
          <div className="duration-pills-grid">
            {presets.map((preset) => (
              <button
                key={preset.mins}
                type="button"
                className={`duration-pill-card ${!isCustomDuration && selectedDurationMins === preset.mins ? 'selected' : ''}`}
                onClick={() => handleSelectPreset(preset.mins)}
              >
                <span className="dur-main-text">{preset.label}</span>
                <span className="dur-sub-text">{preset.sub}</span>
              </button>
            ))}

            <button
              type="button"
              className={`duration-pill-card ${isCustomDuration ? 'selected' : ''}`}
              onClick={() => setIsCustomDuration(true)}
            >
              <span className="dur-main-text">Custom</span>
              <span className="dur-sub-text">Set manually</span>
            </button>
          </div>

          {isCustomDuration && (
            <div className="custom-duration-input-wrap">
              <input
                type="number"
                min="5"
                max="480"
                className="custom-duration-num-input"
                value={customMinsInput}
                onChange={(e) => setCustomMinsInput(Math.max(5, parseInt(e.target.value, 10) || 5))}
              />
              <span className="custom-duration-unit">minutes</span>
            </div>
          )}
        </div>

        {/* End Time */}
        <div className="plan-form-section">
          <span className="plan-section-label">End Time</span>
          <div className="end-time-display-pill">
            <ClockIcon size={14} color="var(--text-secondary)" />
            <span className="end-time-text">{endTimeStr}</span>
            <span className="end-time-diff">({effectiveMinutes} minutes)</span>
          </div>
        </div>

        {/* Task / Block Title */}
        <div className="plan-form-section">
          <label htmlFor="plan-title-embedded" className="plan-section-label">
            Task / Block Title
          </label>
          <input
            id="plan-title-embedded"
            type="text"
            className="plan-input-text"
            placeholder="e.g. DSA Practice, Project Work"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>

        {/* Category */}
        <div className="plan-form-section">
          <label htmlFor="plan-cat-embedded" className="plan-section-label">
            Category
          </label>
          <div className="plan-category-select-wrap">
            <select
              id="plan-cat-embedded"
              className="plan-category-select"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value === '' ? '' : Number(e.target.value))}
            >
              <option value="">No Category</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  ● {c.name} ({c.type})
                </option>
              ))}
            </select>
          </div>
        </div>

        {errorMsg && <div className="plan-error-banner">{errorMsg}</div>}
        {successMsg && (
          <div style={{ color: 'var(--status-focus)', fontSize: 12, padding: '4px 0' }}>
            ✓ {successMsg}
          </div>
        )}

        {/* Actions */}
        <div className="plan-form-actions-row">
          <button
            type="button"
            className="btn-plan-cancel"
            onClick={() => setTitle('')}
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn-plan-save"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Saving…' : 'Save Block'}
          </button>
        </div>
      </form>
    </div>
  );
};

