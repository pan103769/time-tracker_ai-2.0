import React, { useState } from 'react';
import type { CategoryModel, CategoryRuleModel } from '../types';
import { CloseIcon, PlusIcon, TagIcon, TrashIcon } from './Icons';

interface CategoriesViewProps {
  categories: CategoryModel[];
  rules: CategoryRuleModel[];
  onCreateCategory: (data: { name: string; color: string; type: string }) => Promise<void>;
  onDeleteCategory: (id: number) => Promise<void>;
  onCreateRule: (data: { category_id: number; match_type: string; pattern: string; priority: number }) => Promise<void>;
  onDeleteRule: (id: number) => Promise<void>;
}

const PRESET_COLORS = [
  '#8b5cf6', // Violet
  '#06b6d4', // Cyan
  '#3b82f6', // Blue
  '#10b981', // Emerald
  '#f59e0b', // Amber
  '#ef4444', // Red
  '#ec4899', // Pink
  '#6b7280', // Gray
];

export const CategoriesView: React.FC<CategoriesViewProps> = ({
  categories = [],
  rules = [],
  onCreateCategory,
  onDeleteCategory,
  onCreateRule,
  onDeleteRule,
}) => {
  const safeCategories = categories || [];
  const safeRules = rules || [];
  const [showCatModal, setShowCatModal] = useState(false);
  const [showRuleModal, setShowRuleModal] = useState(false);

  // Category Form
  const [catName, setCatName] = useState('');
  const [catColor, setCatColor] = useState('#8b5cf6');
  const [catType, setCatType] = useState<'focus' | 'work' | 'personal' | 'distraction'>('work');

  // Rule Form
  const [ruleCatId, setRuleCatId] = useState<number | ''>('');
  const [ruleMatchType, setRuleMatchType] = useState<'domain' | 'url' | 'app' | 'title_contains'>('app');
  const [rulePattern, setRulePattern] = useState('');
  const [rulePriority, setRulePriority] = useState('10');

  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleCatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!catName.trim()) return;

    setIsSubmitting(true);
    try {
      await onCreateCategory({
        name: catName.trim(),
        color: catColor,
        type: catType,
      });
      setShowCatModal(false);
      setCatName('');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRuleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ruleCatId || !rulePattern.trim()) return;

    setIsSubmitting(true);
    try {
      await onCreateRule({
        category_id: Number(ruleCatId),
        match_type: ruleMatchType,
        pattern: rulePattern.trim(),
        priority: parseInt(rulePriority, 10) || 10,
      });
      setShowRuleModal(false);
      setRulePattern('');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="categories-view-container">
      {/* Precedence Banner */}
      <div className="precedence-card">
        <div className="precedence-header">
          <TagIcon size={18} color="var(--accent-violet)" />
          <span className="precedence-title">Automatic Rule Precedence</span>
        </div>
        <p className="precedence-desc">
          When activities are classified, Time Tracker evaluates rules in strict order:
          <strong> 1. User manual override</strong> &gt;
          <strong> 2. Exact URL rule</strong> &gt;
          <strong> 3. Website domain rule</strong> &gt;
          <strong> 4. Window title rule</strong> &gt;
          <strong> 5. Application name rule</strong> &gt;
          <strong> 6. Fallback category</strong>.
        </p>
      </div>

      {/* ---------------- 1. CATEGORIES MANAGEMENT ---------------- */}
      <div className="section-header">
        <div className="section-title-wrap">
          <h2>Activity Categories</h2>
          <span className="count-pill">{categories.length}</span>
        </div>
        <button className="btn-primary" onClick={() => setShowCatModal(true)}>
          <PlusIcon size={14} />
          <span>New Category</span>
        </button>
      </div>

      <div className="categories-cards-grid">
        {safeCategories.length === 0 ? (
          <div className="empty-panel">
            <p>No categories configured yet. Click "New Category" to create one.</p>
          </div>
        ) : (
          safeCategories.map((c) => (
            <div key={c.id} className="category-card">
              <div className="cat-card-top">
                <div className="cat-badge-wrap">
                  <div className="cat-dot-lg" style={{ backgroundColor: c.color }} />
                  <span className="cat-card-name">{c.name}</span>
                </div>
                <button
                  className="btn-icon-danger"
                  onClick={() => onDeleteCategory(c.id)}
                  title="Delete category"
                >
                  <TrashIcon size={14} />
                </button>
              </div>
              <div className="cat-card-bottom">
                <span className={`cat-type-pill ${c.type}`}>{c.type.toUpperCase()}</span>
                <span className="cat-color-hex">{c.color}</span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* ---------------- 2. RULES MANAGEMENT ---------------- */}
      <div className="section-header" style={{ marginTop: '40px' }}>
        <div className="section-title-wrap">
          <h2>Classification Rules</h2>
          <span className="count-pill">{rules.length}</span>
        </div>
        <button className="btn-secondary" onClick={() => setShowRuleModal(true)}>
          <PlusIcon size={14} />
          <span>Add Rule</span>
        </button>
      </div>

      <div className="rules-table-container">
        <table className="rules-table">
          <thead>
            <tr>
              <th>Pattern / Identifier</th>
              <th>Match Type</th>
              <th>Assigned Category</th>
              <th>Category Type</th>
              <th>Priority</th>
              <th style={{ width: '50px' }}></th>
            </tr>
          </thead>
          <tbody>
            {safeRules.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                  No classification rules found. Add a rule to automatically categorize window titles or applications.
                </td>
              </tr>
            ) : (
              safeRules.map((r) => (
              <tr key={r.id}>
                <td className="rule-pattern-cell">
                  <code>{r.pattern}</code>
                </td>
                <td>
                  <span className={`rule-type-badge ${r.match_type}`}>
                    {r.match_type.replace('_', ' ')}
                  </span>
                </td>
                <td>
                  <div className="cat-cell-wrap">
                    <span className="cat-dot-sm" style={{ backgroundColor: r.category_color || '#8b5cf6' }} />
                    <span>{r.category_name}</span>
                  </div>
                </td>
                <td>
                  <span className={`cat-type-pill ${r.category_type || 'work'}`}>
                    {r.category_type || 'work'}
                  </span>
                </td>
                <td className="rule-priority-cell">{r.priority}</td>
                <td>
                  <button
                    className="btn-icon-danger"
                    onClick={() => onDeleteRule(r.id)}
                    title="Delete rule"
                  >
                    <TrashIcon size={13} />
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
        </table>
      </div>

      {/* ---------------- NEW CATEGORY MODAL ---------------- */}
      {showCatModal && (
        <div className="modal-overlay" onClick={() => setShowCatModal(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Custom Category</h3>
              <button className="btn-close" onClick={() => setShowCatModal(false)}>
                <CloseIcon size={18} />
              </button>
            </div>

            <form onSubmit={handleCatSubmit}>
              <div className="form-group">
                <label>Category Name</label>
                <input
                  type="text"
                  placeholder="e.g. Graphic Design / 3D"
                  value={catName}
                  onChange={(e) => setCatName(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label>Category Type (for productivity scoring)</label>
                <select
                  value={catType}
                  onChange={(e) => setCatType(e.target.value as any)}
                >
                  <option value="focus">Focus (Deep productive work)</option>
                  <option value="work">Work (General business & communication)</option>
                  <option value="personal">Personal (Utility & miscellaneous)</option>
                  <option value="distraction">Distraction (Media, social, gaming)</option>
                </select>
              </div>

              <div className="form-group">
                <label>Color Accent</label>
                <div className="color-palette">
                  {PRESET_COLORS.map((c) => (
                    <button
                      type="button"
                      key={c}
                      className={`color-swatch ${catColor === c ? 'selected' : ''}`}
                      style={{ backgroundColor: c }}
                      onClick={() => setCatColor(c)}
                    />
                  ))}
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setShowCatModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={isSubmitting}>
                  {isSubmitting ? 'Saving...' : 'Create Category'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ---------------- NEW RULE MODAL ---------------- */}
      {showRuleModal && (
        <div className="modal-overlay" onClick={() => setShowRuleModal(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add Classification Rule</h3>
              <button className="btn-close" onClick={() => setShowRuleModal(false)}>
                <CloseIcon size={18} />
              </button>
            </div>

            <form onSubmit={handleRuleSubmit}>
              <div className="form-group">
                <label>Match Type</label>
                <select
                  value={ruleMatchType}
                  onChange={(e) => setRuleMatchType(e.target.value as any)}
                >
                  <option value="app">Application process (e.g. Code.exe, figma.exe)</option>
                  <option value="domain">Website domain (e.g. github.com, youtube.com)</option>
                  <option value="title_contains">Window title substring (e.g. 'Project Alpha')</option>
                  <option value="url">URL substring (e.g. 'jira.atlassian.com/browse')</option>
                </select>
              </div>

              <div className="form-group">
                <label>Match Pattern</label>
                <input
                  type="text"
                  placeholder="e.g. github.com or Code.exe"
                  value={rulePattern}
                  onChange={(e) => setRulePattern(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label>Assign to Category</label>
                <select
                  value={ruleCatId}
                  onChange={(e) => setRuleCatId(Number(e.target.value))}
                  required
                >
                  <option value="">-- Choose Category --</option>
                  {safeCategories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.type})
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Priority (Higher evaluated first)</label>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={rulePriority}
                  onChange={(e) => setRulePriority(e.target.value)}
                />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setShowRuleModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={isSubmitting}>
                  {isSubmitting ? 'Saving...' : 'Add Rule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

