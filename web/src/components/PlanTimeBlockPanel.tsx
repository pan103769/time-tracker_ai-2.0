import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { type CategoryModel, getLocalTodayString } from '../types';
import { CalendarIcon, ClockIcon, CloseIcon, EditIcon } from './Icons';

interface PlanTimeBlockPanelProps {
  categories: CategoryModel[];
  selectedDate: string;
  isOpen: boolean;
  onClose: () => void;
  onBlockCreated: () => void;
}

export const PlanTimeBlockPanel: React.FC<PlanTimeBlockPanelProps> = ({
  categories,
  selectedDate,
  isOpen,
  onClose,
  onBlockCreated,
}) => {
  const [activeTab, setActiveTab] = useState<'quick' | 'custom'>('quick');
  const [title, setTitle] = useState('');
  const [categoryId, setCategoryId] = useState<number | ''>(
    categories.length > 0 ? categories[0].id : ''
  );

  // Time state
  const [startTimeStr, setStartTimeStr] = useState<string>('09:00');
  const [isEditingStartTime, setIsEditingStartTime] = useState<boolean>(false);
  const [selectedDurationMins, setSelectedDurationMins] = useState<number>(50);
  const [isCustomDuration, setIsCustomDuration] = useState<boolean>(false);
  const [customMinsInput, setCustomMinsInput] = useState<number>(45);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Preset configuration (defaults can be customized in localStorage)
  const [presets, setPresets] = useState([
    { mins: 25, label: '25 min', sub: 'Focus' },
    { mins: 50, label: '50 min', sub: 'Deep Work' },
    { mins: 90, label: '90 min', sub: 'Long' },
  ]);

  // Load presets from localStorage if available
  useEffect(() => {
    try {
      const saved = localStorage.getItem('timeblock_presets');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length >= 3) {
          setPresets(parsed);
        }
      }
    } catch {
      // Ignore fallback
    }
  }, []);

  // Set default start time to machine-local current time when opening
  useEffect(() => {
    if (isOpen) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      setStartTimeStr(`${hh}:${mm}`);
      setErrorMsg(null);
    }
  }, [isOpen]);

  // Calculate calculated end time
  const effectiveMinutes = isCustomDuration ? customMinsInput : selectedDurationMins;

  const calculateEndTime = (startHHMM: string, addMinutes: number): string => {
    try {
      const [hStr, mStr] = startHHMM.split(':');
      let totalMins = parseInt(hStr, 10) * 60 + parseInt(mStr, 10) + addMinutes;
      // Handle wrap-around
      totalMins = totalMins % (24 * 60);
      const endH = Math.floor(totalMins / 60);
      const endM = totalMins % 60;
      return `${String(endH).padStart(2, '0')}:${String(endM).padStart(2, '0')}`;
    } catch {
      return '10:00';
    }
  };

  const endTimeStr = calculateEndTime(startTimeStr, effectiveMinutes);

  const handleSelectPreset = (mins: number) => {
    setIsCustomDuration(false);
    setSelectedDurationMins(mins);
  };

  const handleSelectCustom = () => {
    setIsCustomDuration(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setErrorMsg('Please enter a task / block title.');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      const baseDate = selectedDate || getLocalTodayString();
      const cleanStart = startTimeStr.includes('T') ? startTimeStr.split('T')[1].slice(0, 5) : startTimeStr.slice(0, 5);
      const cleanEnd = endTimeStr.includes('T') ? endTimeStr.split('T')[1].slice(0, 5) : endTimeStr.slice(0, 5);

      await api.createTimeBlock(
        baseDate,
        cleanStart,
        cleanEnd,
        title.trim(),
        categoryId === '' ? undefined : Number(categoryId)
      );

      setTitle('');
      onBlockCreated();
      onClose();
    } catch (err: any) {
      setErrorMsg(err?.message || 'Failed to save time block.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="plan-time-block-overlay" onClick={onClose}>
      <div
        className="plan-time-block-card animate-slide-left"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="plan-block-header">
          <div className="plan-block-title-row">
            <CalendarIcon size={18} color="var(--accent-purple, #8065FF)" />
            <h3 className="plan-block-heading">Plan Time Block</h3>
          </div>
          <button type="button" className="btn-icon-close" onClick={onClose}>
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Tabs: Quick Add | Custom Time */}
        <div className="plan-block-tabs-row">
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
                <ClockIcon size={15} color="var(--text-secondary)" />
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
                <EditIcon size={14} />
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
                onClick={handleSelectCustom}
              >
                <span className="dur-main-text">Custom</span>
                <span className="dur-sub-text">Set manually</span>
              </button>
            </div>

            {/* Custom Minutes Input if selected */}
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

          {/* End Time (Calculated) */}
          <div className="plan-form-section">
            <span className="plan-section-label">End Time</span>
            <div className="end-time-display-pill">
              <ClockIcon size={15} color="var(--text-secondary)" />
              <span className="end-time-text">{endTimeStr}</span>
              <span className="end-time-diff">({effectiveMinutes} minutes)</span>
            </div>
          </div>

          {/* Task / Block Title */}
          <div className="plan-form-section">
            <label htmlFor="plan-task-title" className="plan-section-label">
              Task / Block Title
            </label>
            <input
              id="plan-task-title"
              type="text"
              className="plan-input-text"
              placeholder="e.g. DSA Practice, Project Work"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>

          {/* Category Dropdown */}
          <div className="plan-form-section">
            <label htmlFor="plan-task-category" className="plan-section-label">
              Category
            </label>
            <div className="plan-category-select-wrap">
              <select
                id="plan-task-category"
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

          {/* Actions */}
          <div className="plan-form-actions-row">
            <button
              type="button"
              className="btn-plan-cancel"
              onClick={onClose}
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
    </div>
  );
};

