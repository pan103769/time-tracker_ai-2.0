import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { ZapIcon } from './Icons';

interface WindowTitleBarProps {
  onMinimize?: () => void;
  onToggleMaximize?: () => void;
  onClose?: () => void;
}

export const WindowTitleBar: React.FC<WindowTitleBarProps> = ({
  onMinimize,
  onToggleMaximize,
  onClose,
}) => {
  const [isMaximized, setIsMaximized] = useState<boolean>(true);
  const [isDesktop, setIsDesktop] = useState<boolean>(true);

  // Sync window state on mount and window resize
  const checkWindowState = useCallback(async () => {
    try {
      const state = await api.getWindowState();
      if (state) {
        setIsDesktop(state.is_desktop);
        setIsMaximized(state.is_maximized);
      }
    } catch {
      // Non-critical in standalone browser dev mode
    }
  }, []);

  useEffect(() => {
    checkWindowState();
    const handleResize = () => {
      checkWindowState();
    };
    const handleReady = () => {
      checkWindowState();
    };
    window.addEventListener('resize', handleResize);
    window.addEventListener('pywebviewready', handleReady);
    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('pywebviewready', handleReady);
    };
  }, [checkWindowState]);

  const handleMinimize = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onMinimize) {
      onMinimize();
      return;
    }
    try {
      await api.minimizeWindow();
    } catch {
      // Fallback
    }
  };

  const handleToggleMaximize = async (e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (onToggleMaximize) {
      onToggleMaximize();
      return;
    }
    try {
      const res = await api.toggleMaximizeWindow();
      if (res && typeof res.is_maximized === 'boolean') {
        setIsMaximized(res.is_maximized);
      }
    } catch {
      // Fallback
    }
  };

  const handleClose = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onClose) {
      onClose();
      return;
    }
    try {
      await api.closeWindow();
    } catch {
      // Fallback
    }
  };

  return (
    <header
      className="window-title-bar pywebview-drag-region"
      onDoubleClick={() => handleToggleMaximize()}
      title="Double-click to toggle maximize/restore"
    >
      {/* Brand Identity / Window Title */}
      <div className="window-title-drag-region pywebview-drag-region">
        <div className="window-title-brand pywebview-drag-region">
          <ZapIcon size={14} color="#8065FF" />
          <span>Time Tracker AI</span>
          <span className="window-title-badge">2.0</span>
        </div>
      </div>

      {/* Flexible Draggable Middle Spacer */}
      <div
        className="window-title-center-spacer pywebview-drag-region"
        onDoubleClick={() => handleToggleMaximize()}
      />

      {/* Window Controls (Minimize, Maximize/Restore, Close) */}
      {isDesktop && (
        <div className="window-controls-group" data-no-drag="true">
          {/* Minimize Button */}
          <button
            type="button"
            className="window-control-btn btn-minimize"
            onClick={handleMinimize}
            title="Minimize"
            aria-label="Minimize"
            tabIndex={-1}
            data-no-drag="true"
          >
            <svg width="10" height="1" viewBox="0 0 10 1" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="10" height="1" fill="currentColor" />
            </svg>
          </button>

          {/* Maximize / Restore Button */}
          <button
            type="button"
            className="window-control-btn btn-maximize"
            onClick={handleToggleMaximize}
            title={isMaximized ? 'Restore' : 'Maximize'}
            aria-label={isMaximized ? 'Restore' : 'Maximize'}
            tabIndex={-1}
            data-no-drag="true"
          >
            {isMaximized ? (
              // Native Windows Restore icon (two overlapping squares)
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                  d="M2.5 0.5H9.5V7.5H8.5V1.5H2.5V0.5Z"
                  fill="currentColor"
                />
                <rect
                  x="0.5"
                  y="2.5"
                  width="7"
                  height="7"
                  stroke="currentColor"
                  strokeWidth="1"
                  fill="none"
                />
              </svg>
            ) : (
              // Native Windows Maximize icon (single square)
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect
                  x="0.5"
                  y="0.5"
                  width="9"
                  height="9"
                  stroke="currentColor"
                  strokeWidth="1"
                  fill="none"
                />
              </svg>
            )}
          </button>

          {/* Close Button */}
          <button
            type="button"
            className="window-control-btn btn-close"
            onClick={handleClose}
            title="Close"
            aria-label="Close"
            tabIndex={-1}
            data-no-drag="true"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M0.5 0.5L9.5 9.5M9.5 0.5L0.5 9.5"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      )}
    </header>
  );
};
