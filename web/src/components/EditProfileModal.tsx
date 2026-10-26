import React, { useState, useEffect, useRef } from 'react';
import { CloseIcon, UserIcon, CheckIcon } from './Icons';

interface EditProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentName: string;
  onSave: (newName: string) => Promise<void> | void;
}

export const EditProfileModal: React.FC<EditProfileModalProps> = ({
  isOpen,
  onClose,
  currentName,
  onSave,
}) => {
  const [displayName, setDisplayName] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setDisplayName(currentName || '');
      setErrorMsg(null);
      setIsSaving(false);
      // Auto-focus the input on open
      setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.focus();
          inputRef.current.select();
        }
      }, 50);
    }
  }, [isOpen, currentName]);

  // Handle Escape key to cancel
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = displayName.trim();
    if (!trimmed) {
      setErrorMsg('Display name cannot be empty.');
      if (inputRef.current) {
        inputRef.current.focus();
      }
      return;
    }

    if (trimmed.length > 50) {
      setErrorMsg('Display name must be 50 characters or less.');
      return;
    }

    setIsSaving(true);
    setErrorMsg(null);
    try {
      await onSave(trimmed);
      onClose();
    } catch (err: any) {
      setErrorMsg(err?.message || 'Failed to update profile name. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  const previewInitial = (displayName.trim() ? displayName.trim().charAt(0) : 'P').toUpperCase();
  const previewName = displayName.trim() || 'Your Name';

  return (
    <div
      className="modal-backdrop"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(5, 8, 15, 0.78)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        padding: '16px',
      }}
      onClick={onClose}
    >
      <div
        className="card-panel edit-profile-modal-card animate-slide-up"
        style={{
          width: '100%',
          maxWidth: '440px',
          background: 'linear-gradient(135deg, rgba(20, 27, 44, 0.98), rgba(14, 18, 30, 0.98))',
          border: '1.5px solid rgba(128, 101, 255, 0.45)',
          boxShadow: '0 0 35px rgba(128, 101, 255, 0.22), 0 20px 48px rgba(0, 0, 0, 0.75)',
          borderRadius: '18px',
          padding: '24px 26px',
          color: '#EDF0F7',
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-profile-modal-title"
      >
        {/* Modal Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '10px',
                backgroundColor: 'rgba(128, 101, 255, 0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#8065FF',
              }}
            >
              <UserIcon size={18} />
            </div>
            <div>
              <h3 id="edit-profile-modal-title" style={{ margin: 0, fontSize: '17px', fontWeight: 700, color: '#FFFFFF' }}>
                Edit Profile
              </h3>
              <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: '#8994A8' }}>
                Change your display name in Time Tracker AI
              </p>
            </div>
          </div>
          <button
            type="button"
            className="smart-alert-close-btn"
            onClick={onClose}
            aria-label="Close dialog"
            style={{
              background: 'transparent',
              border: 'none',
              color: '#8994A8',
              cursor: 'pointer',
              padding: '6px',
              borderRadius: '6px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Live Profile Card Preview */}
        <div
          style={{
            background: 'rgba(23, 33, 49, 0.72)',
            border: '1px solid rgba(39, 53, 74, 0.7)',
            borderRadius: '12px',
            padding: '10px 14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                width: '34px',
                height: '34px',
                borderRadius: '50%',
                background: '#0D7355',
                color: '#35D68A',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
                fontSize: '14px',
                boxShadow: '0 0 10px rgba(53, 214, 138, 0.35)',
                transition: 'all 0.15s ease',
              }}
            >
              {previewInitial}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '13px', fontWeight: 600, color: '#FFFFFF', lineHeight: 1.2 }}>
                {previewName}
              </span>
              <span style={{ fontSize: '11px', color: '#5A6679', marginTop: '2px' }}>
                Free Plan
              </span>
            </div>
          </div>
          <span
            style={{
              fontSize: '10px',
              fontWeight: 700,
              textTransform: 'uppercase',
              color: '#8065FF',
              background: 'rgba(128, 101, 255, 0.15)',
              padding: '2px 8px',
              borderRadius: '6px',
            }}
          >
            Preview
          </span>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '18px' }}>
            <label
              htmlFor="display-name-input"
              style={{
                display: 'block',
                fontSize: '12.5px',
                fontWeight: 600,
                color: '#EDF0F7',
                marginBottom: '8px',
              }}
            >
              Display Name
            </label>
            <input
              id="display-name-input"
              ref={inputRef}
              type="text"
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                if (errorMsg) setErrorMsg(null);
              }}
              placeholder="e.g. pant"
              maxLength={50}
              disabled={isSaving}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                background: '#0e131d',
                border: errorMsg ? '1px solid #FF5252' : '1px solid rgba(128, 101, 255, 0.35)',
                borderRadius: '10px',
                padding: '11px 14px',
                color: '#FFFFFF',
                fontSize: '14px',
                outline: 'none',
                transition: 'border-color 0.15s, box-shadow 0.15s',
              }}
              onFocus={(e) => {
                if (!errorMsg) {
                  e.currentTarget.style.borderColor = '#8065FF';
                  e.currentTarget.style.boxShadow = '0 0 0 3px rgba(128, 101, 255, 0.2)';
                }
              }}
              onBlur={(e) => {
                if (!errorMsg) {
                  e.currentTarget.style.borderColor = 'rgba(128, 101, 255, 0.35)';
                  e.currentTarget.style.boxShadow = 'none';
                }
              }}
            />
            {errorMsg && (
              <p style={{ margin: '6px 0 0 0', fontSize: '12px', color: '#FF5252' }}>
                {errorMsg}
              </p>
            )}
          </div>

          {/* Action Buttons */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '10px', marginTop: '24px' }}>
            <button
              type="button"
              className="btn-alert-ghost"
              onClick={onClose}
              disabled={isSaving}
              style={{
                padding: '9px 18px',
                fontSize: '13px',
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-alert-primary"
              disabled={isSaving}
              style={{
                padding: '9px 22px',
                fontSize: '13px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                cursor: isSaving ? 'not-allowed' : 'pointer',
                opacity: isSaving ? 0.7 : 1,
              }}
            >
              {isSaving ? (
                <span>Saving...</span>
              ) : (
                <>
                  <CheckIcon size={14} />
                  <span>Save</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

