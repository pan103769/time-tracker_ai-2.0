import React, { useState } from 'react';
import { api } from '../api';
import type { CategoryModel } from '../types';
import { CloseIcon, TargetIcon, ZapIcon } from './Icons';

interface NewTaskModalProps {
  categories: CategoryModel[];
  selectedDate: string;
  onClose: () => void;
  onTaskCreated: () => void;
}

export const NewTaskModal: React.FC<NewTaskModalProps> = ({
  categories,
  selectedDate,
  onClose,
  onTaskCreated,
}) => {
  const [title, setTitle] = useState('');
  const [categoryId, setCategoryId] = useState<number | ''>(
    categories.length > 0 ? categories[0].id : ''
  );
  const [durationMinutes, setDurationMinutes] = useState<number>(25);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const durationPresets = [15, 25, 45, 60, 90];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setErrorMsg('Please enter a task title.');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      // Calculate start and end ISO strings based on current local time
      const now = new Date();
      const startTime = now.toISOString();
      const end = new Date(now.getTime() + durationMinutes * 60 * 1000);
      const endTime = end.toISOString();

      await api.createTimeBlock(
        selectedDate,
        startTime,
        endTime,
        title.trim(),
        categoryId === '' ? undefined : Number(categoryId)
      );

      onTaskCreated();
      onClose();
    } catch (err: any) {
      setErrorMsg(err?.message || 'Failed to start time block task.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ZapIcon size={20} color="var(--accent-purple, #8065FF)" />
            <h3 style={{ margin: 0, fontSize: 18, color: 'var(--text-primary)' }}>
              Start Focused Task
            </h3>
          </div>
          <button type="button" className="btn-icon" onClick={onClose}>
            <CloseIcon size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="form-group">
            <label htmlFor="task-title-input" style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
              Task or Goal Description
            </label>
            <input
              id="task-title-input"
              type="text"
              className="modal-input"
              placeholder="e.g., Code API endpoints, Review PRs, Design UI"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="task-category-select" style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
              Category
            </label>
            <select
              id="task-category-select"
              className="modal-select"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value === '' ? '' : Number(e.target.value))}
            >
              <option value="">No Category</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.type})
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
              Planned Duration: {durationMinutes} minutes
            </label>
            <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
              {durationPresets.map((mins) => (
                <button
                  key={mins}
                  type="button"
                  className={`chip-btn ${durationMinutes === mins ? 'active' : ''}`}
                  onClick={() => setDurationMinutes(mins)}
                  style={{ flex: 1, padding: '8px 0', fontSize: 13, textAlign: 'center' }}
                >
                  {mins}m
                </button>
              ))}
            </div>
          </div>

          {errorMsg && (
            <div className="error-banner" style={{ padding: '8px 12px', fontSize: 13 }}>
              {errorMsg}
            </div>
          )}

          <div className="modal-actions" style={{ marginTop: 8 }}>
            <button type="button" className="btn-secondary" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>
              <TargetIcon size={15} />
              <span>{isSubmitting ? 'Starting…' : 'Start Focus Session'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
