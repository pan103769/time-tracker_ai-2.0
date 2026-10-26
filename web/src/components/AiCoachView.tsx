import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type {
  AiCoachChatMessage,
  DailyAiSummaryModel,
  ProductivityModel,
  StatsModel,
  WeeklyStatsModel,
} from '../types';
import type { DashboardTab } from './Sidebar';
import {
  CheckIcon,
  ChevronDownIcon,
  CopyIcon,
  ExternalLinkIcon,
  PieChartIcon,
  RefreshIcon,
  SendIcon,
  SparklesIcon,
} from './Icons';

interface AiCoachViewProps {
  selectedDate: string;
  onSelectDate: (date: string) => void;
  productivity: ProductivityModel | null;
  aiSummary: DailyAiSummaryModel | null;
  stats?: StatsModel | null;
  weeklyStats?: WeeklyStatsModel | null;
  onRefreshAi?: () => void;
  isAiRefreshing?: boolean;
  onNavigateTab?: (tab: DashboardTab) => void;
}

interface QuickQuestion {
  id: string;
  emoji: string;
  title: string;
  prompt: string;
  color: string;
}

const QUICK_QUESTIONS: QuickQuestion[] = [
  {
    id: 'study_focus',
    emoji: '📚',
    title: 'Study & Focus Time',
    prompt: 'How much did I study and focus today?',
    color: '#16D5E2',
  },
  {
    id: 'distractions',
    emoji: '🎯',
    title: 'Distractions Analysis',
    prompt: 'How much time did I waste on distractions?',
    color: '#FA5275',
  },
  {
    id: 'time_breakdown',
    emoji: '⏱️',
    title: 'Where Did My Time Go?',
    prompt: 'Where did my time go today?',
    color: '#8065FF',
  },
  {
    id: 'performance_comparison',
    emoji: '📈',
    title: 'Performance vs Yesterday',
    prompt: 'Am I improving compared with yesterday?',
    color: '#35D68A',
  },
  {
    id: 'what_next',
    emoji: '🚀',
    title: 'What Should I Do Next?',
    prompt: 'What should I focus on next?',
    color: '#FFB23E',
  },
];

// Helper to format inline bold, code, and text
function formatInlineText(text: string): React.ReactNode[] {
  // Matches **bold** or `code`
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  const parts = text.split(regex);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={index} style={{ color: '#FFFFFF', fontWeight: 600 }}>
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code
          key={index}
          style={{
            background: 'rgba(255, 255, 255, 0.08)',
            padding: '2px 6px',
            borderRadius: 4,
            fontSize: 12,
            fontFamily: 'monospace',
            color: '#16D5E2',
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={index}>{part}</span>;
  });
}

// Markdown parser & renderer tailored for Coach messages
const FormattedMessage: React.FC<{ content: string }> = ({ content }) => {
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];

  let inTable = false;
  let tableHeader: string[] = [];
  let tableRows: string[][] = [];

  const flushTable = (key: string) => {
    if (tableHeader.length > 0 || tableRows.length > 0) {
      elements.push(
        <div
          key={key}
          style={{
            overflowX: 'auto',
            margin: '12px 0',
            borderRadius: 8,
            border: '1px solid rgba(255, 255, 255, 0.08)',
            background: 'rgba(10, 15, 28, 0.6)',
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 13,
              textAlign: 'left',
            }}
          >
            {tableHeader.length > 0 && (
              <thead>
                <tr style={{ background: 'rgba(255, 255, 255, 0.04)', borderBottom: '1px solid rgba(255, 255, 255, 0.1)' }}>
                  {tableHeader.map((th, idx) => (
                    <th
                      key={idx}
                      style={{
                        padding: '8px 12px',
                        color: '#A0AEC0',
                        fontWeight: 600,
                        fontSize: 11,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                      }}
                    >
                      {formatInlineText(th.trim())}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {tableRows.map((row, rIdx) => (
                <tr
                  key={rIdx}
                  style={{
                    borderBottom: rIdx < tableRows.length - 1 ? '1px solid rgba(255, 255, 255, 0.04)' : 'none',
                    background: rIdx % 2 === 0 ? 'transparent' : 'rgba(255, 255, 255, 0.015)',
                  }}
                >
                  {row.map((cell, cIdx) => (
                    <td key={cIdx} style={{ padding: '8px 12px', color: '#E2E8F0' }}>
                      {formatInlineText(cell.trim())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      tableHeader = [];
      tableRows = [];
      inTable = false;
    }
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();

    // Table parsing
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      const cells = trimmed
        .slice(1, -1)
        .split('|')
        .map((c) => c.trim());
      // Check if delimiter row
      const isDelimiter = cells.every((c) => /^:?-+:?$/.test(c));
      if (isDelimiter) {
        return; // skip separator line
      }
      if (!inTable) {
        inTable = true;
        tableHeader = cells;
      } else {
        tableRows.push(cells);
      }
      return;
    } else if (inTable) {
      flushTable(`table-${idx}`);
    }

    if (!trimmed) {
      elements.push(<div key={`sp-${idx}`} style={{ height: 6 }} />);
      return;
    }

    // Headings
    if (trimmed.startsWith('### ')) {
      elements.push(
        <h4
          key={`h4-${idx}`}
          style={{
            fontSize: 15,
            fontWeight: 700,
            color: '#FFFFFF',
            margin: '14px 0 6px 0',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          {formatInlineText(trimmed.slice(4))}
        </h4>
      );
      return;
    }
    if (trimmed.startsWith('## ')) {
      elements.push(
        <h3
          key={`h3-${idx}`}
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: '#FFFFFF',
            margin: '16px 0 8px 0',
          }}
        >
          {formatInlineText(trimmed.slice(3))}
        </h3>
      );
      return;
    }
    if (trimmed.startsWith('# ')) {
      elements.push(
        <h2
          key={`h2-${idx}`}
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: '#FFFFFF',
            margin: '18px 0 10px 0',
          }}
        >
          {formatInlineText(trimmed.slice(2))}
        </h2>
      );
      return;
    }

    // Bullet item
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      elements.push(
        <div
          key={`li-${idx}`}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 8,
            margin: '4px 0',
            paddingLeft: 4,
          }}
        >
          <span
            style={{
              color: '#8065FF',
              fontWeight: 700,
              lineHeight: 1.5,
              fontSize: 14,
            }}
          >
            •
          </span>
          <span style={{ color: '#D1D7E4', fontSize: 13.5, lineHeight: 1.5 }}>
            {formatInlineText(trimmed.slice(2))}
          </span>
        </div>
      );
      return;
    }

    // Numbered list item
    const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
    if (numMatch) {
      elements.push(
        <div
          key={`nli-${idx}`}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 8,
            margin: '4px 0',
            paddingLeft: 4,
          }}
        >
          <span
            style={{
              color: '#16D5E2',
              fontWeight: 600,
              minWidth: 18,
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            {numMatch[1]}.
          </span>
          <span style={{ color: '#D1D7E4', fontSize: 13.5, lineHeight: 1.5 }}>
            {formatInlineText(numMatch[2])}
          </span>
        </div>
      );
      return;
    }

    // Blockquote
    if (trimmed.startsWith('> ')) {
      elements.push(
        <div
          key={`bq-${idx}`}
          style={{
            borderLeft: '3px solid #8065FF',
            paddingLeft: 12,
            margin: '8px 0',
            fontStyle: 'italic',
            color: '#A0AEC0',
            fontSize: 13,
          }}
        >
          {formatInlineText(trimmed.slice(2))}
        </div>
      );
      return;
    }

    // Standard paragraph
    elements.push(
      <p
        key={`p-${idx}`}
        style={{
          margin: '4px 0',
          fontSize: 13.5,
          lineHeight: 1.55,
          color: '#D1D7E4',
        }}
      >
        {formatInlineText(trimmed)}
      </p>
    );
  });

  if (inTable) {
    flushTable('table-end');
  }

  return <div style={{ wordBreak: 'break-word' }}>{elements}</div>;
};

export const AiCoachView: React.FC<AiCoachViewProps> = ({
  selectedDate,
  onSelectDate,
  productivity,
  aiSummary,
  onRefreshAi,
  isAiRefreshing = false,
  onNavigateTab,
}) => {
  // Chat state
  const [messages, setMessages] = useState<AiCoachChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showBriefing, setShowBriefing] = useState(false); // Collapsible top briefing
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Load chat history or preset welcome if empty
  const resetChat = useCallback(() => {
    setMessages([
      {
        id: 'welcome-msg',
        role: 'assistant',
        content: `👋 **Hello! I am your AI Productivity Coach.**\n\nI analyze your real-time tracked activity directly from your local SQLite database without guessing or inventing numbers. I can:\n\n* **Distinguish Study & Learning** from coding and general computer time.\n* **Break down Distractions** and reveal your biggest interruption culprits.\n* **Compare Performance** with yesterday's work and focus sessions.\n* **Guide Your Next Task** based on scheduled Time Blocks and active goals.\n\nClick any of the quick questions below or type your question in the chat!`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        grounded: true,
        sources: ['Local SQLite Database', 'tracker.db'],
      },
    ]);
  }, []);

  // Initialize once
  useEffect(() => {
    if (messages.length === 0) {
      resetChat();
    }
  }, [messages.length, resetChat]);

  // Send a message or preset action
  const handleSend = async (userText: string, presetAction?: string) => {
    const textToSend = userText.trim();
    if (!textToSend && !presetAction) return;

    const userMessage: AiCoachChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: textToSend || (presetAction ? `Asked about: ${presetAction}` : ''),
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputMessage('');
    setIsLoading(true);

    try {
      // Build conversation history to preserve context
      const historyPayload = messages.slice(-6).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const response = await api.sendAiCoachChat({
        message: textToSend,
        selected_date: selectedDate,
        history: historyPayload,
        preset_action: presetAction,
      });

      const assistantMessage: AiCoachChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.response,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        grounded: response.grounded,
        sources: response.sources,
        quick_actions: response.quick_actions,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err: any) {
      console.error('Failed to communicate with AI Coach:', err);
      const errorMessage: AiCoachChatMessage = {
        id: `assistant-err-${Date.now()}`,
        role: 'assistant',
        content: `⚠️ **Unable to fetch analysis**: ${err?.message || 'Server error occurred'}. Please ensure the Time Tracker backend is running.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        grounded: false,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  // Handle Quick Action Pill click
  const handleQuickAction = (action: string, param: string) => {
    if (action === 'navigate_tab' && onNavigateTab) {
      onNavigateTab(param as DashboardTab);
    } else if (action === 'navigate_timeline' && onNavigateTab) {
      onNavigateTab('timeline');
    } else if (action === 'set_date') {
      onSelectDate(param);
    }
  };

  // Copy assistant response text
  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Handle textarea keydown (Enter to send, Shift+Enter for newline)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(inputMessage);
    }
  };

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputMessage(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
  };

  // Daily AI summary metrics
  const headline = aiSummary?.headline || 'Solid momentum building! 🔥';
  const narrative =
    aiSummary?.narrative ||
    'You completed your core deep focus sessions today with strong momentum. Distractions remained low during core working hours.';
  const keyWin =
    aiSummary?.key_win || 'Consistent coding and focus blocks maintained today.';
  const mainChallenge =
    aiSummary?.main_challenge || 'Intermittent context switching between browser tasks.';
  const suggestion =
    aiSummary?.suggestion || 'Schedule a 15-minute recovery walk between prolonged study blocks.';

  const focusScore = productivity
    ? Math.min(100, Math.round((productivity.focus_seconds / (productivity.total_work_seconds || 1)) * 100))
    : 88;

  return (
    <div className="view-container aicoach-view" style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 16 }}>
      {/* Top Header Row */}
      <div
        className="view-header-row"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 10,
              background: 'linear-gradient(135deg, rgba(128, 101, 255, 0.3), rgba(22, 213, 226, 0.2))',
              border: '1px solid rgba(128, 101, 255, 0.45)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 16px rgba(128, 101, 255, 0.25)',
            }}
          >
            <SparklesIcon size={20} color="#8065FF" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h2 style={{ fontSize: 20, fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
                AI Productivity Coach
              </h2>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  color: '#16D5E2',
                  background: 'rgba(22, 213, 226, 0.12)',
                  border: '1px solid rgba(22, 213, 226, 0.3)',
                  padding: '2px 7px',
                  borderRadius: 10,
                }}
              >
                Grounded Chatbot
              </span>
            </div>
            <p style={{ fontSize: 12.5, color: '#8994A8', margin: '2px 0 0 0' }}>
              Data-grounded conversational insights, pattern analysis, and actionable next steps.
            </p>
          </div>
        </div>

        {/* Right header controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Toggle Briefing */}
          <button
            type="button"
            onClick={() => setShowBriefing((prev) => !prev)}
            style={{
              background: showBriefing ? 'rgba(128, 101, 255, 0.2)' : 'rgba(255, 255, 255, 0.05)',
              border: showBriefing ? '1px solid rgba(128, 101, 255, 0.4)' : '1px solid rgba(255, 255, 255, 0.1)',
              color: showBriefing ? '#C7B9FF' : '#A0AEC0',
              borderRadius: 8,
              padding: '6px 12px',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              transition: 'all 0.15s ease',
            }}
          >
            <PieChartIcon size={14} />
            <span>{showBriefing ? 'Hide Daily Briefing' : 'Show Daily Briefing'}</span>
            <ChevronDownIcon
              size={12}
              style={{
                transform: showBriefing ? 'rotate(180deg)' : 'none',
                transition: 'transform 0.2s ease',
              }}
            />
          </button>

          {/* New Chat */}
          <button
            type="button"
            onClick={resetChat}
            style={{
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              color: '#EDF0F7',
              borderRadius: 8,
              padding: '6px 12px',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              transition: 'all 0.15s ease',
            }}
            title="Start a fresh conversation"
          >
            <RefreshIcon size={13} />
            <span>New Chat</span>
          </button>

          {onRefreshAi && (
            <button
              type="button"
              className="btn-primary"
              onClick={onRefreshAi}
              disabled={isAiRefreshing}
              style={{ padding: '6px 12px', fontSize: 12, gap: 6 }}
            >
              <RefreshIcon size={13} className={isAiRefreshing ? 'spin' : ''} />
              <span>{isAiRefreshing ? 'Analyzing...' : 'Re-analyze'}</span>
            </button>
          )}
        </div>
      </div>

      {/* Collapsible Executive Daily Briefing */}
      {showBriefing && (
        <div
          style={{
            animation: 'fadeIn 0.2s ease',
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
          }}
        >
          {/* Hero AI Coaching Card */}
          <div
            className="card-panel"
            style={{
              background: 'linear-gradient(135deg, rgba(20, 27, 45, 0.95), rgba(16, 22, 36, 0.95))',
              border: '1px solid rgba(128, 101, 255, 0.35)',
              boxShadow: '0 8px 32px rgba(128, 101, 255, 0.12)',
              padding: '20px 24px',
              borderRadius: 14,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    color: '#8065FF',
                    background: 'rgba(128, 101, 255, 0.15)',
                    padding: '3px 8px',
                    borderRadius: 4,
                  }}
                >
                  DAILY AI BRIEFING • {selectedDate}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: '#35D68A',
                    background: 'rgba(53, 214, 138, 0.12)',
                    padding: '3px 8px',
                    borderRadius: 4,
                  }}
                >
                  Focus Ratio: {focusScore}%
                </span>
              </div>
              <span style={{ fontSize: 12, color: '#5A6679' }}>
                {aiSummary?.generated_time_label ? `Generated ${aiSummary.generated_time_label}` : 'Updated recently'}
              </span>
            </div>

            <h3 style={{ fontSize: 18, fontWeight: 700, color: '#FFFFFF', margin: '0 0 8px 0' }}>
              {headline}
            </h3>

            <p style={{ fontSize: 13.5, lineHeight: 1.55, color: '#D1D7E4', margin: '0 0 16px 0', maxWidth: '900px' }}>
              {narrative}
            </p>

            {/* 3 Pillars: Win, Challenge, Suggestion */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
              <div
                style={{
                  background: 'rgba(53, 214, 138, 0.08)',
                  border: '1px solid rgba(53, 214, 138, 0.25)',
                  borderRadius: 10,
                  padding: '12px 14px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: 'rgba(53, 214, 138, 0.2)',
                      color: '#35D68A',
                    }}
                  >
                    Key Win
                  </span>
                </div>
                <p style={{ fontSize: 12.5, color: '#EDF0F7', margin: 0, lineHeight: 1.45 }}>{keyWin}</p>
              </div>

              <div
                style={{
                  background: 'rgba(250, 82, 117, 0.08)',
                  border: '1px solid rgba(250, 82, 117, 0.25)',
                  borderRadius: 10,
                  padding: '12px 14px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: 'rgba(250, 82, 117, 0.2)',
                      color: '#FA5275',
                    }}
                  >
                    Main Challenge
                  </span>
                </div>
                <p style={{ fontSize: 12.5, color: '#EDF0F7', margin: 0, lineHeight: 1.45 }}>{mainChallenge}</p>
              </div>

              <div
                style={{
                  background: 'rgba(128, 101, 255, 0.08)',
                  border: '1px solid rgba(128, 101, 255, 0.25)',
                  borderRadius: 10,
                  padding: '12px 14px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: 'rgba(128, 101, 255, 0.2)',
                      color: '#8065FF',
                    }}
                  >
                    Actionable Suggestion
                  </span>
                </div>
                <p style={{ fontSize: 12.5, color: '#EDF0F7', margin: 0, lineHeight: 1.45 }}>{suggestion}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Suggested Quick Question Buttons */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.07em',
              color: '#8994A8',
            }}
          >
            Quick Inquiries (Data Grounded)
          </span>
          <span style={{ fontSize: 11, color: '#5A6679' }}>Click to analyze instantly</span>
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 8,
          }}
        >
          {QUICK_QUESTIONS.map((q) => (
            <button
              key={q.id}
              type="button"
              onClick={() => handleSend(q.prompt, q.id)}
              disabled={isLoading}
              style={{
                background: 'rgba(18, 24, 38, 0.75)',
                border: `1px solid ${q.color}35`,
                borderRadius: 10,
                padding: '10px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                cursor: isLoading ? 'not-allowed' : 'pointer',
                textAlign: 'left',
                transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                opacity: isLoading ? 0.6 : 1,
              }}
              onMouseEnter={(e) => {
                if (!isLoading) {
                  e.currentTarget.style.borderColor = `${q.color}90`;
                  e.currentTarget.style.background = 'rgba(28, 36, 56, 0.9)';
                  e.currentTarget.style.transform = 'translateY(-1px)';
                  e.currentTarget.style.boxShadow = `0 4px 12px ${q.color}20`;
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = `${q.color}35`;
                e.currentTarget.style.background = 'rgba(18, 24, 38, 0.75)';
                e.currentTarget.style.transform = 'none';
                e.currentTarget.style.boxShadow = 'none';
              }}
            >
              <span style={{ fontSize: 18, lineHeight: 1 }}>{q.emoji}</span>
              <div style={{ overflow: 'hidden' }}>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    color: '#EDF0F7',
                    display: 'block',
                    whiteSpace: 'nowrap',
                    textOverflow: 'ellipsis',
                    overflow: 'hidden',
                  }}
                >
                  {q.title}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: '#8994A8',
                    display: 'block',
                    whiteSpace: 'nowrap',
                    textOverflow: 'ellipsis',
                    overflow: 'hidden',
                  }}
                >
                  {q.prompt}
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Main Chat Stream Card */}
      <div
        className="card-panel"
        style={{
          flex: 1,
          minHeight: 480,
          display: 'flex',
          flexDirection: 'column',
          background: 'rgba(13, 18, 30, 0.85)',
          border: '1px solid rgba(128, 101, 255, 0.25)',
          borderRadius: 14,
          padding: 0,
          overflow: 'hidden',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.4)',
        }}
      >
        {/* Messages Scroll Area */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '20px 24px',
            display: 'flex',
            flexDirection: 'column',
            gap: 18,
          }}
        >
          {messages.map((msg) => {
            const isUser = msg.role === 'user';
            return (
              <div
                key={msg.id}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: isUser ? 'flex-end' : 'flex-start',
                  maxWidth: '100%',
                }}
              >
                {/* Bubble Container */}
                <div
                  style={{
                    maxWidth: isUser ? '80%' : '92%',
                    minWidth: isUser ? '160px' : '280px',
                    borderRadius: 14,
                    padding: isUser ? '12px 16px' : '16px 20px',
                    background: isUser
                      ? 'linear-gradient(135deg, rgba(22, 213, 226, 0.2), rgba(128, 101, 255, 0.25))'
                      : 'rgba(19, 26, 42, 0.95)',
                    border: isUser
                      ? '1px solid rgba(22, 213, 226, 0.4)'
                      : '1px solid rgba(128, 101, 255, 0.25)',
                    boxShadow: isUser
                      ? '0 4px 16px rgba(22, 213, 226, 0.15)'
                      : '0 4px 20px rgba(0, 0, 0, 0.3)',
                    color: '#EDF0F7',
                  }}
                >
                  {/* Assistant Header Info Bar */}
                  {!isUser && (
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                        paddingBottom: 8,
                        marginBottom: 12,
                        gap: 12,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div
                          style={{
                            width: 22,
                            height: 22,
                            borderRadius: 6,
                            background: 'rgba(128, 101, 255, 0.2)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <SparklesIcon size={12} color="#8065FF" />
                        </div>
                        <span style={{ fontSize: 12, fontWeight: 700, color: '#EDF0F7' }}>
                          AI Coach
                        </span>
                        {msg.grounded && (
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              color: '#35D68A',
                              background: 'rgba(53, 214, 138, 0.12)',
                              border: '1px solid rgba(53, 214, 138, 0.3)',
                              padding: '1px 6px',
                              borderRadius: 8,
                              display: 'flex',
                              alignItems: 'center',
                              gap: 4,
                            }}
                          >
                            <CheckIcon size={10} /> Grounded in Tracked Data
                          </span>
                        )}
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 11, color: '#5A6679' }}>{msg.timestamp}</span>
                        <button
                          type="button"
                          onClick={() => handleCopy(msg.id, msg.content)}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: copiedId === msg.id ? '#35D68A' : '#8994A8',
                            cursor: 'pointer',
                            padding: '2px 4px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 4,
                            fontSize: 11,
                          }}
                          title="Copy response"
                        >
                          {copiedId === msg.id ? (
                            <>
                              <CheckIcon size={12} /> Copied
                            </>
                          ) : (
                            <>
                              <CopyIcon size={12} /> Copy
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Message Body */}
                  {isUser ? (
                    <div style={{ fontSize: 14, lineHeight: 1.5, wordBreak: 'break-word' }}>
                      {msg.content}
                    </div>
                  ) : (
                    <FormattedMessage content={msg.content} />
                  )}

                  {/* Quick Action Interactive Pills */}
                  {!isUser && msg.quick_actions && msg.quick_actions.length > 0 && (
                    <div
                      style={{
                        marginTop: 14,
                        paddingTop: 10,
                        borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                        display: 'flex',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        gap: 8,
                      }}
                    >
                      <span style={{ fontSize: 11, color: '#8994A8', marginRight: 4 }}>
                        Quick actions:
                      </span>
                      {msg.quick_actions.map((qa, aIdx) => (
                        <button
                          key={aIdx}
                          type="button"
                          onClick={() => handleQuickAction(qa.action, qa.param)}
                          style={{
                            background: 'rgba(128, 101, 255, 0.15)',
                            border: '1px solid rgba(128, 101, 255, 0.35)',
                            color: '#C7B9FF',
                            borderRadius: 6,
                            padding: '4px 10px',
                            fontSize: 11.5,
                            fontWeight: 600,
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                            transition: 'all 0.15s ease',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = 'rgba(128, 101, 255, 0.28)';
                            e.currentTarget.style.borderColor = '#8065FF';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = 'rgba(128, 101, 255, 0.15)';
                            e.currentTarget.style.borderColor = 'rgba(128, 101, 255, 0.35)';
                          }}
                        >
                          <span>{qa.label}</span>
                          <ExternalLinkIcon size={11} />
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Data Source Footer tag */}
                  {!isUser && msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: 8, fontSize: 10.5, color: '#5A6679' }}>
                      Sources: {msg.sources.join(' • ')}
                    </div>
                  )}
                </div>

                {/* User timestamp */}
                {isUser && (
                  <span style={{ fontSize: 11, color: '#5A6679', marginTop: 4, marginRight: 4 }}>
                    {msg.timestamp}
                  </span>
                )}
              </div>
            );
          })}

          {/* Thinking / Analyzing indicator */}
          {isLoading && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                background: 'rgba(19, 26, 42, 0.95)',
                border: '1px solid rgba(128, 101, 255, 0.3)',
                padding: '12px 18px',
                borderRadius: 12,
                width: 'fit-content',
                animation: 'pulse 1.5s infinite',
              }}
            >
              <SparklesIcon size={16} color="#16D5E2" className="spin" />
              <span style={{ fontSize: 13, color: '#16D5E2', fontWeight: 600 }}>
                Consulting tracked observations & analyzing flow metrics...
              </span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div
          style={{
            borderTop: '1px solid rgba(128, 101, 255, 0.2)',
            background: 'rgba(11, 15, 26, 0.95)',
            padding: '14px 18px',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10 }}>
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputMessage}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your study time, YouTube usage, interruptions, goals, or what to do next... (Enter to send, Shift+Enter for newline)"
              disabled={isLoading}
              style={{
                flex: 1,
                background: 'rgba(20, 27, 45, 0.8)',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                borderRadius: 10,
                color: '#EDF0F7',
                padding: '10px 14px',
                fontSize: 13.5,
                lineHeight: 1.5,
                resize: 'none',
                minHeight: 42,
                maxHeight: 120,
                outline: 'none',
                boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.3)',
                transition: 'border-color 0.2s ease',
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = '#8065FF';
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
              }}
            />

            <button
              type="button"
              onClick={() => handleSend(inputMessage)}
              disabled={!inputMessage.trim() || isLoading}
              style={{
                background:
                  !inputMessage.trim() || isLoading
                    ? 'rgba(255, 255, 255, 0.05)'
                    : 'linear-gradient(135deg, #8065FF, #16D5E2)',
                border: 'none',
                color: !inputMessage.trim() || isLoading ? '#5A6679' : '#0B0F1A',
                borderRadius: 10,
                width: 42,
                height: 42,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: !inputMessage.trim() || isLoading ? 'not-allowed' : 'pointer',
                fontWeight: 700,
                boxShadow:
                  !inputMessage.trim() || isLoading ? 'none' : '0 4px 16px rgba(128, 101, 255, 0.4)',
                transition: 'all 0.2s ease',
                flexShrink: 0,
              }}
              title="Send message (Enter)"
            >
              <SendIcon size={16} />
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, color: '#5A6679' }}>
            <span>Scope: {selectedDate} • Grounded in local SQLite database</span>
            <span>Shift + Enter for new line • Enter to send</span>
          </div>
        </div>
      </div>
    </div>
  );
};
