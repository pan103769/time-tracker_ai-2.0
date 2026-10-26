import React from 'react';
import {
  BellIcon,
  CalendarIcon,
  DashboardIcon,
  InsightsIcon,
  SettingsIcon,
  SparklesIcon,
  TagIcon,
  TargetIcon,
  TimelineIcon,
  WidgetIcon,
  ZapIcon,
} from './Icons';

export type DashboardTab =
  | 'overview'
  | 'timeline'
  | 'timeblocks'
  | 'goals'
  | 'categories'
  | 'insights'
  | 'settings'
  | 'reports'
  | 'aicoach'
  | 'notifications';

interface SidebarProps {
  currentTab: DashboardTab;
  onSelectTab: (tab: DashboardTab) => void;
  isBackendConnected: boolean;
  isTracking: boolean;
  dbPath?: string;
  isAutostartEnabled?: boolean;
  onToggleAutostart?: () => void;
  onLaunchWidget?: () => void;
  onOpenNewTaskModal?: () => void;
  unreadNotificationsCount?: number;
  userName?: string;
  onEditProfile?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onSelectTab,
  isBackendConnected,
  isTracking,
  onLaunchWidget,
  onOpenNewTaskModal: _onOpenNewTaskModal,
  unreadNotificationsCount = 0,
  userName = 'pant',
  onEditProfile,
}) => {
  const avatarInitial = (userName?.trim() ? userName.trim().charAt(0) : 'P').toUpperCase();
  return (
    <aside className="sidebar">
      {/* Brand Header matching Reference Image */}
      <div className="sidebar-header">
        <div className="brand-logo-icon-rize">
          <ZapIcon size={18} color="#8065FF" />
        </div>
        <div className="brand-text-row">
          <span className="brand-name">Time Tracker AI</span>
          <span className="brand-version-pill">2.0</span>
        </div>
      </div>

      {/* Main Nav Items (10 Items matching Master Reference) */}
      <nav className="sidebar-nav">
        {/* 1. Dashboard */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'overview' ? 'active' : ''}`}
          onClick={() => onSelectTab('overview')}
        >
          <DashboardIcon size={18} />
          <span>Dashboard</span>
        </button>

        {/* 2. Timeline */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'timeline' ? 'active' : ''}`}
          onClick={() => onSelectTab('timeline')}
        >
          <TimelineIcon size={18} />
          <span>Timeline</span>
        </button>

        {/* 3. Time Blocks */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'timeblocks' ? 'active' : ''}`}
          onClick={() => onSelectTab('timeblocks')}
        >
          <CalendarIcon size={18} />
          <span>Time Blocks</span>
        </button>

        {/* 4. Goals */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'goals' ? 'active' : ''}`}
          onClick={() => onSelectTab('goals')}
        >
          <TargetIcon size={18} />
          <span>Goals</span>
        </button>

        {/* 5. Analytics & Reports */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'insights' || currentTab === 'reports' ? 'active' : ''}`}
          onClick={() => onSelectTab('insights')}
        >
          <InsightsIcon size={18} />
          <span>Analytics &amp; Reports</span>
        </button>

        {/* 6. Categories */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'categories' ? 'active' : ''}`}
          onClick={() => onSelectTab('categories')}
        >
          <TagIcon size={18} />
          <span>Categories</span>
        </button>

        {/* 7. AI Coach */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'aicoach' ? 'active' : ''}`}
          onClick={() => onSelectTab('aicoach')}
        >
          <SparklesIcon size={18} />
          <span>AI Coach</span>
        </button>

        {/* 9. Notifications with Dynamic Unread Count Badge */}
        <button
          type="button"
          className={`nav-link nav-link-notifications ${currentTab === 'notifications' ? 'active' : ''}`}
          onClick={() => onSelectTab('notifications')}
        >
          <div className="nav-icon-badge-wrap">
            <BellIcon size={18} />
            {unreadNotificationsCount > 0 && <span className="unread-dot-badge" />}
          </div>
          <span>Notifications</span>
          {unreadNotificationsCount > 0 && (
            <span className="unread-badge-pill">{unreadNotificationsCount}</span>
          )}
        </button>

        {/* 10. Settings */}
        <button
          type="button"
          className={`nav-link ${currentTab === 'settings' ? 'active' : ''}`}
          onClick={() => onSelectTab('settings')}
        >
          <SettingsIcon size={18} />
          <span>Settings</span>
        </button>
      </nav>

      {/* Sidebar Bottom: Forest Backdrop visible behind Quote & Profile Cards */}
      <div className="sidebar-bottom">
        {/* Quote Card (Matching Image 5 & Master Reference) */}
        <div className="sidebar-quote-card">
          <div className="quote-moon-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          </div>
          <span className="quote-text">
            Small consistent steps lead to big results.
          </span>
        </div>

        {/* User Profile Card (Clickable to Edit Profile) */}
        <button
          type="button"
          className="sidebar-profile-card"
          onClick={onEditProfile}
          title="Click to edit profile"
          aria-label={`Edit Profile: ${userName || 'pant'}, Free Plan`}
        >
          <div className="profile-left">
            <div className="profile-avatar-circle">
              {avatarInitial}
            </div>
            <div className="profile-info-col">
              <span className="profile-name">{userName || 'pant'}</span>
              <span className="profile-plan-lbl">Free Plan</span>
            </div>
          </div>
          <span className="profile-chevron">›</span>
        </button>

        {/* Tracking Status Footer */}
        <div className="sidebar-footer">
          <div className="sidebar-footer-row">
            <div className="sidebar-status-group">
              <div className={`status-dot-pulse ${isBackendConnected ? (isTracking ? 'active' : 'paused') : 'error'}`} />
              <span className="sidebar-status-label">
                {isBackendConnected
                  ? (isTracking ? 'Tracking active' : 'Tracking paused')
                  : 'Backend offline'}
              </span>
            </div>

            {onLaunchWidget && (
              <button
                type="button"
                className="btn-widget-mini"
                onClick={onLaunchWidget}
                title="Float Desktop Focus Widget"
              >
                <WidgetIcon size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
};
