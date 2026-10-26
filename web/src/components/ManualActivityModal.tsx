import React, { useState } from 'react';
import type { CategoryModel, RecoveryGapModel } from '../types';
import { CalendarIcon, CheckIcon, CloseIcon, ClockIcon } from './Icons';

interface ManualActivityModalProps {
  isOpen: boolean;
  gap?: RecoveryGapModel | null;
  categories: CategoryModel[];
  onClose: () => void;
  onSaved: () => void;
  onRecordManual: (payload: {
    task_name: string;
    start_time: string;
    end_time: string;
    category_id?: number | null;
    notes?: string;
    recovery_gap_id?: number | null;
  }) => Promise<void>;
}

export const ManualActivityModal: React.FC<ManualActivityModalProps> = ({
  isOpen,
  gap,
  categories,
  onClose,
  onSaved,
  onRecordManual,
}) => {
  if (!isOpen) return null;

  // Format ISO strings to local datetime-local format (YYYY-MM-DDTHH:MM)
  const toLocalInputFormat = (isoString?: string) => {
    if (!isoString) {
      const now = new Date();
      return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16);
    }
    const d = new Date(isoString);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
  };

  const [taskName, setTaskName] = useState<string>('');
  const [startTime, setStartTime] = useState<string>(toLocalInputFormat(gap?.gap_start));
  const [endTime, setEndTime] = useState<string>(toLocalInputFormat(gap?.gap_end));
  const [categoryId, setCategoryId] = useState<number | null>(
    categories.length > 0 ? categories[0].id : null
  );
  const [notes, setNotes] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    const cleanTask = taskName.trim();
    if (!cleanTask) {
      setErrorMessage('Please enter an activity or task name.');
      return;
    }

    const startDt = new Date(startTime);
    const endDt = new Date(endTime);

    if (isNaN(startDt.getTime()) || isNaN(endDt.getTime())) {
      setErrorMessage('Please provide valid start and end times.');
      return;
    }

    if (endDt <= startDt) {
      setErrorMessage('End time must be after start time.');
      return;
    }

    const durationSecs = (endDt.getTime() - startDt.getTime()) / 1000;
    if (durationSecs > 86400) {
      setErrorMessage('Duration cannot exceed 24 hours.');
      return;
    }

    setIsSubmitting(true);
    try {
      await onRecordManual({
        task_name: cleanTask,
        start_time: startDt.toISOString(),
        end_time: endDt.toISOString(),
        category_id: categoryId,
        notes: notes.trim() || undefined,
        recovery_gap_id: gap?.id,
      });
      onSaved();
      onClose();
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to record manual activity.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Calculate duration preview
  let durationPreview = '';
  try {
    const s = new Date(startTime).getTime();
    const e = new Date(endTime).getTime();
    if (e > s) {
      const mins = Math.round((e - s) / 60000);
      const h = Math.floor(mins / 60);
      const m = mins % 60;
      durationPreview = h > 0 ? `${h}h ${m}m` : `${m} minutes`;
    }
  } catch {
    durationPreview = '';
  }

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div
        className="modal-card manual-activity-modal animate-scale-up"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: 480,
          background: 'rgba(15, 20, 32, 0.95)',
          backdropFilter: 'blur(20px)',
          borderRadius: 16,
          border: '1px solid rgba(128, 101, 255, 0.35)',
          boxShadow: '0 20px 50px rgba(0, 0, 0, 0.7), 0 0 25px rgba(128, 101, 255, 0.15)',
          color: '#FFFFFF',
          padding: 24,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 10,
                background: 'rgba(128, 101, 255, 0.2)',
                border: '1px solid rgba(128, 101, 255, 0.4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <ClockIcon size={18} color="#8065FF" />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#FFFFFF' }}>
                {gap ? 'Recover Missed Activity' : 'Record Manual Activity'}
              </h3>
              <p style={{ margin: '2px 0 0 0', fontSize: 12, color: '#8994A8' }}>
                {gap
                  ? 'Add your off-screen or untracked work to your timeline.'
                  : 'Manually add an activity block without overwriting raw tracking data.'}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="smart-alert-close-btn"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#8994A8',
              cursor: 'pointer',
              padding: 4,
            }}
          >
            <CloseIcon size={16} />
          </button>
        </div>

        {errorMessage && (
          <div
            style={{
              background: 'rgba(250, 82, 117, 0.15)',
              border: '1px solid rgba(250, 82, 117, 0.3)',
              borderRadius: 8,
              padding: '8px 12px',
              fontSize: 12,
              color: '#FA5275',
              marginBottom: 16,
            }}
          >
            {errorMessage}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Activity / Task Name */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#CBD5E1', marginBottom: 6 }}>
              Activity / Task Title <span style={{ color: '#FA5275' }}>*</span>
            </label>
            <input
              type="text"
              className="text-input"
              placeholder="e.g. Code Architecture Planning, Design Sync, Reading..."
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              required
              autoFocus
              style={{
                width: '100%',
                padding: '9px 12px',
                borderRadius: 8,
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                color: '#FFFFFF',
                fontSize: 13,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {/* Time Interval: Start & End */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#CBD5E1', marginBottom: 6 }}>
                Start Time
              </label>
              <input
                type="datetime-local"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                required
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  color: '#FFFFFF',
                  fontSize: 12,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#CBD5E1', marginBottom: 6 }}>
                End Time
              </label>
              <input
                type="datetime-local"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                required
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  color: '#FFFFFF',
                  fontSize: 12,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          </div>

          {durationPreview && (
            <div
              style={{
                fontSize: 11,
                color: '#00F0FF',
                marginBottom: 14,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <CalendarIcon size={12} color="#00F0FF" />
              <span>Calculated duration: <strong>{durationPreview}</strong></span>
            </div>
          )}

          {/* Category Dropdown */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#CBD5E1', marginBottom: 6 }}>
              Category
            </label>
            <div style={{ position: 'relative' }}>
              <select
                value={categoryId ?? ''}
                onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : null)}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  color: '#FFFFFF',
                  fontSize: 13,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              >
                <option value="" style={{ background: '#0F1420' }}>
                  No Category (Uncategorized)
                </option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id} style={{ background: '#0F1420' }}>
                    {c.name} ({c.type})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Optional Notes */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#CBD5E1', marginBottom: 6 }}>
              Notes / Sub-task <span style={{ color: '#8994A8', fontWeight: 400 }}>(Optional)</span>
            </label>
            <input
              type="text"
              placeholder="e.g. Discussed database schema with team"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              style={{
                width: '100%',
                padding: '9px 12px',
                borderRadius: 8,
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                color: '#FFFFFF',
                fontSize: 13,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            <button
              type="button"
              className="btn-alert-ghost"
              onClick={onClose}
              disabled={isSubmitting}
              style={{ padding: '8px 16px', borderRadius: 8, fontSize: 13 }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-alert-primary"
              disabled={isSubmitting}
              style={{
                padding: '8px 20px',
                borderRadius: 8,
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <CheckIcon size={14} />
              <span>{isSubmitting ? 'Saving…' : 'Record Activity'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
