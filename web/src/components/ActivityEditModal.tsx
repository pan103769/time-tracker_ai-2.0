import React, { useState, useEffect } from 'react';
import { api } from '../api';
import type { ActiveTaskModel, CategoryModel } from '../types';
import { CloseIcon, TargetIcon } from './Icons';

interface ActivityEditModalProps {
  isOpen: boolean;
  onClose: () => void;
  activeTask: ActiveTaskModel | null;
  categories: CategoryModel[];
  onTaskSaved?: () => void;
}

export const ActivityEditModal: React.FC<ActivityEditModalProps> = ({
  isOpen,
  onClose,
  activeTask,
  categories,
  onTaskSaved,
}) => {
  const [taskName, setTaskName] = useState('');
  const [categoryId, setCategoryId] = useState<number | ''>('');
  const [isSaving, setIsSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (activeTask) {
      setTaskName(activeTask.user_task || activeTask.title || '');
      setCategoryId(activeTask.category_id || '');
    }
    setErrorMsg(null);
  }, [activeTask, isOpen]);

  if (!isOpen) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskName.trim()) {
      setErrorMsg('Please enter a valid activity or task name.');
      return;
    }

    setIsSaving(true);
    setErrorMsg(null);

    try {
      await api.assignActiveTask(
        taskName.trim(),
        categoryId === '' ? null : Number(categoryId),
        activeTask?.observation_id
      );
      if (onTaskSaved) {
        onTaskSaved();
      }
      onClose();
    } catch (err: any) {
      setErrorMsg(err?.message || 'Failed to assign activity name.');
    } finally {
      setIsSaving(false);
    }
  };

  const rawApp = activeTask?.app ? activeTask.app.replace('.exe', '') : 'Unknown Application';
  const rawTitle = activeTask?.title || 'No window title detected';

  return (
    <div
      className="modal-backdrop"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(5, 8, 15, 0.75)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
      }}
      onClick={onClose}
    >
      <div
        className="card-panel activity-edit-modal-card"
        style={{
          width: '100%',
          maxWidth: '480px',
          background: 'linear-gradient(135deg, rgba(20, 27, 45, 0.98), rgba(15, 20, 32, 0.98))',
          border: '1.5px solid rgba(128, 101, 255, 0.45)',
          boxShadow: '0 0 35px rgba(128, 101, 255, 0.25), 0 16px 40px rgba(0, 0, 0, 0.7)',
          borderRadius: '18px',
          padding: '24px',
          color: '#EDF0F7',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                background: 'rgba(128, 101, 255, 0.2)',
                border: '1px solid rgba(128, 101, 255, 0.35)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#8065FF',
              }}
            >
              <TargetIcon size={18} />
            </div>
            <div>
              <h3 style={{ fontSize: '17px', fontWeight: 700, margin: 0, color: '#FFFFFF' }}>
                Edit Current Activity
              </h3>
              <span style={{ fontSize: '11px', color: 'var(--text-muted, #5A6679)' }}>
                Assign a meaningful task name to the recording session
              </span>
            </div>
          </div>
          <button
            type="button"
            className="btn-icon"
            onClick={onClose}
            title="Close dialog"
            style={{ color: 'var(--text-secondary, #8994A8)' }}
          >
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Observed Application Metadata Banner (Read-only) */}
        <div
          style={{
            background: 'rgba(26, 34, 48, 0.7)',
            border: '1px solid rgba(39, 53, 74, 0.7)',
            borderRadius: '10px',
            padding: '10px 14px',
            marginBottom: '18px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span style={{ fontSize: '11px', fontWeight: 600, color: '#16D5E2', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Detected Window
            </span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted, #5A6679)', fontFamily: 'var(--font-mono)' }}>
              PID #{activeTask?.observation_id || 'active'}
            </span>
          </div>
          <div style={{ fontSize: '13px', fontWeight: 600, color: '#FFFFFF' }}>
            {rawApp}
          </div>
          <div
            style={{
              fontSize: '11.5px',
              color: 'var(--text-secondary, #8994A8)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              marginTop: '2px',
            }}
            title={rawTitle}
          >
            {rawTitle}
          </div>
        </div>

        {/* Edit Form */}
        <form onSubmit={handleSave}>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#EDF0F7', marginBottom: '6px' }}>
              Meaningful Activity / Task Name *
            </label>
            <input
              type="text"
              className="input-field"
              placeholder="e.g., Python Development, DSA Practice, Project Research"
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              autoFocus
              style={{
                width: '100%',
                boxSizing: 'border-box',
                fontSize: '13.5px',
                padding: '9px 12px',
                background: 'rgba(15, 20, 32, 0.9)',
                border: '1px solid rgba(128, 101, 255, 0.4)',
                borderRadius: '8px',
                color: '#FFFFFF',
              }}
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#EDF0F7', marginBottom: '6px' }}>
              Assign Category
            </label>
            <div style={{ position: 'relative' }}>
              <select
                className="input-field select-field"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : '')}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  fontSize: '13px',
                  padding: '9px 12px',
                  background: 'rgba(15, 20, 32, 0.9)',
                  border: '1px solid rgba(39, 53, 74, 0.7)',
                  borderRadius: '8px',
                  color: '#FFFFFF',
                }}
              >
                <option value="">No Category Override (Use Automatic Rules)</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.type})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {errorMsg && (
            <div
              style={{
                padding: '8px 12px',
                borderRadius: '6px',
                marginBottom: '14px',
                fontSize: '12px',
                backgroundColor: 'rgba(250, 82, 117, 0.15)',
                color: '#FA5275',
                border: '1px solid rgba(250, 82, 117, 0.3)',
              }}
            >
              {errorMsg}
            </div>
          )}

          {/* Action Buttons */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={onClose}
              disabled={isSaving}
              style={{ padding: '8px 16px', fontSize: '13px' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={isSaving || !taskName.trim()}
              style={{ padding: '8px 20px', fontSize: '13px' }}
            >
              {isSaving ? 'Saving...' : 'Save Activity'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
