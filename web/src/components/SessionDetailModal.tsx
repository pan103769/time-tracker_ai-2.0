import React, { useEffect, useState } from 'react';
import type { CategoryModel, SessionModel } from '../types';
import {
  AlertIcon,
  AppIconHelper,
  CheckIcon,
  ClockIcon,
  CloseIcon,
  EditIcon,
  ExternalLinkIcon,
  TagIcon,
  UndoIcon,
} from './Icons';
import { LiveDuration } from './LiveDuration';

interface SessionDetailModalProps {
  session: SessionModel | null;
  selectedDate: string;
  categories?: CategoryModel[];
  onClose: () => void;
  onSaveEdit: (sessionKey: string, newDesc: string) => Promise<void>;
  onDeleteEdit: (sessionKey: string) => Promise<void>;
  onAssignCategory?: (sessionKey: string, categoryId: number) => Promise<void>;
  onRemoveCategoryOverride?: (sessionKey: string) => Promise<void>;
}

export const SessionDetailModal: React.FC<SessionDetailModalProps> = ({
  session,
  selectedDate,
  categories = [],
  onClose,
  onSaveEdit,
  onDeleteEdit,
  onAssignCategory,
  onRemoveCategoryOverride,
}) => {
  const [descriptionInput, setDescriptionInput] = useState('');
  const [selectedCatId, setSelectedCatId] = useState<number | ''>('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Quick Rule Creator state
  const [showRuleCreator, setShowRuleCreator] = useState(false);
  const [ruleMatchType, setRuleMatchType] = useState<'domain' | 'app' | 'title_contains'>('domain');
  const [rulePattern, setRulePattern] = useState('');
  const [ruleSubmitting, setRuleSubmitting] = useState(false);
  const [ruleSuccessMsg, setRuleSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      setDescriptionInput(session.user_description || session.ai_description || '');
      setSelectedCatId(session.category_id || '');
      setSaveSuccess(false);
      setErrorMsg(null);

      // Default rule pattern based on available metadata
      if (session.domain) {
        setRuleMatchType('domain');
        setRulePattern(session.domain);
      } else if (session.app && session.app !== 'Unknown') {
        setRuleMatchType('app');
        setRulePattern(session.app);
      } else {
        setRuleMatchType('title_contains');
        setRulePattern(session.title || '');
      }
      setShowRuleCreator(false);
      setRuleSuccessMsg(null);
    }
  }, [session]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!session) return null;

  const isIdle = session.kind === 'idle';

  const handleSaveDescription = async () => {
    if (!descriptionInput.trim()) return;
    setIsSaving(true);
    setErrorMsg(null);
    try {
      await onSaveEdit(session.session_key, descriptionInput.trim());
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to save description');
    } finally {
      setIsSaving(false);
    }
  };

  const handleRestoreDescription = async () => {
    setIsSaving(true);
    setErrorMsg(null);
    try {
      await onDeleteEdit(session.session_key);
      setDescriptionInput(session.ai_description || '');
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to restore description');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCategoryChange = async (catId: number | '') => {
    setSelectedCatId(catId);
    if (!catId) {
      if (onRemoveCategoryOverride) {
        await onRemoveCategoryOverride(session.session_key);
      }
    } else {
      if (onAssignCategory) {
        await onAssignCategory(session.session_key, Number(catId));
      }
    }
  };

  const handleSaveRule = async () => {
    if (!selectedCatId || !rulePattern.trim()) return;
    setRuleSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await fetch('/api/categories/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category_id: Number(selectedCatId),
          match_type: ruleMatchType,
          pattern: rulePattern.trim(),
          priority: 40,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to create rule');
      }
      const matchedCat = categories.find((c) => c.id === Number(selectedCatId));
      setRuleSuccessMsg(`Saved rule: ${ruleMatchType} '${rulePattern.trim()}' will classify as ${matchedCat ? matchedCat.name : 'selected category'}.`);
      setShowRuleCreator(false);
      setTimeout(() => setRuleSuccessMsg(null), 4000);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to save rule');
    } finally {
      setRuleSubmitting(false);
    }
  };

  const startTime = session.start.slice(11, 19);
  const endTime = session.end.slice(11, 19);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title">
            <AppIconHelper app={session.app} size={20} />
            <span>Session #{session.display_number} Details ({selectedDate})</span>
          </div>
          <button className="btn-icon" onClick={onClose} title="Close (Esc)">
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="modal-body">
          {errorMsg && (
            <div className="error-banner" style={{ margin: 0 }}>
              <AlertIcon size={16} />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Timing & Meta details */}
          <div className="meta-grid">
            <div>
              <span className="detail-label">Time Window</span>
              <p className="detail-text" style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                {startTime} → {session.is_ongoing ? 'Present' : endTime}
              </p>
            </div>
            <div>
              <span className="detail-label">Duration</span>
              <p className="detail-text" style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-teal-light)' }}>
                <ClockIcon size={13} style={{ display: 'inline', verticalAlign: -1, marginRight: 4 }} />
                <LiveDuration
                  startTime={session.start}
                  endTime={session.end}
                  isLive={session.is_ongoing}
                  fallbackLabel={session.duration_label}
                />
              </p>
            </div>
            <div>
              <span className="detail-label">Application</span>
              <p className="detail-text">
                {session.app}
                {session.domain && (
                  <span style={{ color: 'var(--accent-teal-light)', marginLeft: 6, fontSize: '12px' }}>
                    ({session.domain})
                  </span>
                )}
              </p>
            </div>
            <div>
              <span className="detail-label">Classification Source</span>
              <p className="detail-text" style={{ textTransform: 'capitalize' }}>
                {session.category_source || session.source || (isIdle ? 'System (Idle)' : 'Rule/AI')}
              </p>
            </div>
            {session.activity_name && (
              <div style={{ gridColumn: 'span 2' }}>
                <span className="detail-label">Activity &amp; Task Attribution</span>
                <p className="detail-text" style={{ fontWeight: 600, color: '#A78BFA' }}>
                  {session.activity_name}
                  {session.context_label && (
                    <span style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)', fontWeight: 400, marginTop: 2 }}>
                      {session.context_label}
                    </span>
                  )}
                </p>
              </div>
            )}
            {session.domain && (
              <div>
                <span className="detail-label">Extracted Domain</span>
                <p className="detail-text" style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-teal-light)' }}>
                  {session.domain}
                </p>
              </div>
            )}
            {session.task && (
              <div>
                <span className="detail-label">Assigned Task</span>
                <p className="detail-text" style={{ color: 'var(--accent-violet-light)', fontWeight: 600 }}>
                  {session.task}
                </p>
              </div>
            )}
          </div>

          {/* Category Assignment Section */}
          <div className="detail-section" style={{ background: 'var(--bg-card-elevated)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <TagIcon size={16} color="var(--accent-violet)" />
                <span className="detail-label" style={{ margin: 0 }}>Category</span>
              </div>
              {session.category_source && (
                <span className="badge-source" style={{ fontSize: 10 }}>{session.category_source.toUpperCase()}</span>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <select
                className="category-select"
                value={selectedCatId}
                onChange={(e) => handleCategoryChange(e.target.value ? Number(e.target.value) : '')}
                style={{
                  background: 'var(--bg-main)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '6px',
                  padding: '6px 10px',
                  fontSize: '13px',
                }}
              >
                <option value="">-- Automatic Rule / Uncategorized --</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.type})
                  </option>
                ))}
              </select>

              {session.category_name && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    className="cat-dot-sm"
                    style={{ backgroundColor: session.category_color || '#8b5cf6' }}
                  />
                  <span style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500 }}>
                    {session.category_name}
                  </span>
                  {session.category_type && (
                    <span className={`cat-type-pill ${session.category_type}`}>
                      {session.category_type}
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Quick Rule Creator Option */}
            {selectedCatId && (
              <div style={{ marginTop: 10, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
                {!showRuleCreator ? (
                  <button
                    className="btn-secondary"
                    style={{ fontSize: 12, padding: '4px 10px' }}
                    onClick={() => setShowRuleCreator(true)}
                  >
                    + Save Rule for Similar Activities
                  </button>
                ) : (
                  <div style={{ background: 'var(--bg-main)', padding: 10, borderRadius: 6, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                      Save permanent rule: future activities matching this condition will automatically classify as selected category.
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <select
                        value={ruleMatchType}
                        onChange={(e) => {
                          const val = e.target.value as 'domain' | 'app' | 'title_contains';
                          setRuleMatchType(val);
                          if (val === 'domain' && session.domain) setRulePattern(session.domain);
                          else if (val === 'app') setRulePattern(session.app);
                          else if (val === 'title_contains') setRulePattern(session.title);
                        }}
                        style={{
                          background: 'var(--bg-card)',
                          color: 'var(--text-primary)',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 4,
                          padding: '4px 8px',
                          fontSize: 12,
                        }}
                      >
                        <option value="domain">Domain</option>
                        <option value="app">Application</option>
                        <option value="title_contains">Title Contains</option>
                      </select>
                      <input
                        type="text"
                        value={rulePattern}
                        onChange={(e) => setRulePattern(e.target.value)}
                        placeholder="e.g. youtube.com or code.exe"
                        style={{
                          flex: 1,
                          minWidth: 160,
                          background: 'var(--bg-card)',
                          color: 'var(--text-primary)',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 4,
                          padding: '4px 8px',
                          fontSize: 12,
                          fontFamily: 'var(--font-mono)',
                        }}
                      />
                      <button
                        className="btn-primary"
                        onClick={handleSaveRule}
                        disabled={ruleSubmitting || !rulePattern.trim()}
                        style={{ fontSize: 12, padding: '4px 12px' }}
                      >
                        {ruleSubmitting ? 'Saving…' : 'Save Rule'}
                      </button>
                      <button
                        className="btn-secondary"
                        onClick={() => setShowRuleCreator(false)}
                        style={{ fontSize: 12, padding: '4px 8px' }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            {ruleSuccessMsg && (
              <div style={{ marginTop: 8, color: 'var(--status-active)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                <CheckIcon size={13} /> {ruleSuccessMsg}
              </div>
            )}
          </div>

          {/* Full Window Title */}
          {session.title && (
            <div className="detail-section">
              <span className="detail-label">Recorded Window Title</span>
              <div
                style={{
                  background: 'var(--bg-main)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '8px 12px',
                  fontSize: '13px',
                  color: 'var(--text-secondary)',
                  wordBreak: 'break-all',
                }}
              >
                {session.title}
              </div>
            </div>
          )}

          {/* Browser URL if present */}
          {session.url && (
            <div className="detail-section">
              <span className="detail-label">Browser URL</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <a
                  href={session.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    color: 'var(--accent-teal-light)',
                    fontSize: '13px',
                    wordBreak: 'break-all',
                    textDecoration: 'none',
                  }}
                >
                  {session.url}
                </a>
                <ExternalLinkIcon size={12} style={{ color: 'var(--accent-teal-light)', flexShrink: 0 }} />
              </div>
            </div>
          )}

          {/* Confidence and Uncertainty */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            {session.confidence !== null && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                <span className="detail-label">Classification Confidence:</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                  {Math.round(session.confidence * 100)}%
                </span>
              </div>
            )}

            {session.is_uncertain && (
              <span className="badge-uncertain">
                <AlertIcon size={11} style={{ display: 'inline', marginRight: 4 }} />
                Uncertain / Needs Review
              </span>
            )}
          </div>

          {/* Description Editor */}
          <div className="detail-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span className="detail-label" style={{ margin: 0 }}>
                {session.user_description ? 'User-Corrected Description' : 'Activity Description'}
              </span>
              {saveSuccess && (
                <span style={{ fontSize: 12, color: 'var(--status-active)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <CheckIcon size={12} /> Saved!
                </span>
              )}
            </div>

            <textarea
              className="description-input"
              rows={3}
              value={descriptionInput}
              onChange={(e) => setDescriptionInput(e.target.value)}
              placeholder="Provide a specific, accurate description for this session…"
              disabled={isSaving}
            />

            <div className="btn-actions-row">
              <button
                className="btn-primary"
                onClick={handleSaveDescription}
                disabled={isSaving || !descriptionInput.trim()}
              >
                <EditIcon size={13} />
                <span>{isSaving ? 'Saving…' : 'Save Description'}</span>
              </button>

              {session.user_description && (
                <button
                  className="btn-secondary"
                  onClick={handleRestoreDescription}
                  disabled={isSaving}
                  title="Revert back to the automatic AI description"
                >
                  <UndoIcon size={13} />
                  <span>Revert to AI</span>
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
