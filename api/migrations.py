"""
api/migrations.py — Safe, additive database migrations for Time Tracker AI 2.

Ensures all required tables, default categories, default rules, and goals
exist in tracker.db. Never modifies, deletes, or recreates existing data.
"""

import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("TIME_TRACKER_DB_PATH", Path(__file__).resolve().parent.parent / "tracker.db"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_migrations(db: Optional[sqlite3.Connection] = None) -> bool:
    """
    Apply additive schema migrations.
    Safe to run repeatedly; uses IF NOT EXISTS and check-then-insert.
    """
    should_close = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        db.row_factory = sqlite3.Row
        should_close = True

    try:
        cur = db.cursor()

        # 0. Core tables (observations & tasks)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                app TEXT NOT NULL,
                title TEXT NOT NULL,
                task TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds REAL,
                CHECK (end_time IS NULL OR end_time >= start_time)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)

        # 1. Categories table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT NOT NULL DEFAULT '#8b5cf6',
                type TEXT NOT NULL DEFAULT 'work', -- 'focus' | 'work' | 'personal' | 'distraction'
                created_at TEXT NOT NULL
            )
        """)

        # 2. Category Rules table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS category_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                match_type TEXT NOT NULL, -- 'domain' | 'url' | 'app' | 'title_contains'
                pattern TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 10,
                created_at TEXT NOT NULL
            )
        """)

        # 3. Explicit Manual Session Category Overrides
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT UNIQUE NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                updated_at TEXT NOT NULL
            )
        """)

        # 4. Configurable Productivity Goals
        cur.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                metric TEXT NOT NULL, -- 'work_time' | 'focus_time' | 'distraction_time' | 'category_time'
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                target_seconds INTEGER NOT NULL,
                is_inversion BOOLEAN NOT NULL DEFAULT 0, -- 1 if staying below target is success
                period TEXT NOT NULL DEFAULT 'daily',    -- 'daily' | 'weekly'
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # 5. Time Blocks
        cur.execute("""
            CREATE TABLE IF NOT EXISTS time_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,       -- YYYY-MM-DD
                start_time TEXT NOT NULL, -- HH:MM
                end_time TEXT NOT NULL,   -- HH:MM
                title TEXT NOT NULL,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Sanitize any legacy time blocks with ISO timestamps to HH:MM format
        try:
            iso_blocks = cur.execute("SELECT id, start_time, end_time FROM time_blocks WHERE start_time LIKE '%T%' OR end_time LIKE '%T%'").fetchall()
            for b_id, st, et in iso_blocks:
                st_clean = st.split("T")[-1][:5]
                et_clean = et.split("T")[-1][:5]
                cur.execute("UPDATE time_blocks SET start_time = ?, end_time = ? WHERE id = ?", (st_clean, et_clean, b_id))
            if iso_blocks:
                db.commit()
        except Exception:
            pass

        # 6. Daily AI Summaries Cache
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_ai_summaries (
                date TEXT PRIMARY KEY,
                summary_json TEXT NOT NULL,
                obs_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # 7. Persistent Application Settings
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 8. Notification Center & Toast History
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,       -- 'idle' | 'focus' | 'time_block' | 'missed_block' | 'recovery' | 'milestone' | 'test'
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                details TEXT,             -- JSON string metadata (e.g. gap_id, block_id, etc.)
                unread INTEGER NOT NULL DEFAULT 1,
                dismissed INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'delivered', -- 'delivered' | 'snoozed' | 'acted_upon' | 'skipped' | 'dismissed'
                created_at TEXT NOT NULL
            )
        """)

        # Add status column to notifications if upgrading from older schema
        try:
            notif_cols = {row[1] for row in cur.execute("PRAGMA table_info(notifications)").fetchall()}
            if "status" not in notif_cols:
                cur.execute("ALTER TABLE notifications ADD COLUMN status TEXT NOT NULL DEFAULT 'delivered'")
        except Exception:
            pass

        # 9. Missed Activity Gaps & Recovery State
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recovery_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gap_start TEXT NOT NULL,
                gap_end TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'resolved_added' | 'skipped' | 'snoozed'
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            )
        """)

        # 10. Timeline Edits
        cur.execute("""
            CREATE TABLE IF NOT EXISTS timeline_edits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 11. Performance Indexes (additive, safe)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_start_end ON observations(start_time, end_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_kind ON observations(kind)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_app ON observations(app)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_time_blocks_date ON time_blocks(date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_category_rules_cat_id ON category_rules(category_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_unread_created ON notifications(unread, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_recovery_gaps_status ON recovery_gaps(status)")

        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_events_timestamp ON activity_events(timestamp)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_events_app ON activity_events(app)")
        except Exception:
            pass

        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_browser_visits_start_time ON browser_visits(start_time)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_browser_visits_url ON browser_visits(url)")
        except Exception:
            pass

        db.commit()

        # Seed default app settings if not present
        default_settings = [
            ("notifications_enabled", "true"),
            ("windows_toasts_enabled", "true"),
            ("notification_sound", "default"),  # "default" | "silent" | "custom"
            ("idle_alert_threshold_minutes", "3"),
            ("mismatch_grace_minutes", "2"),
            ("distraction_cooldown_minutes", "15"),
            ("missed_recovery_threshold_minutes", "30"),
            ("missed_recovery_enabled", "true"),
            ("time_block_reminders_enabled", "true"),
            ("time_block_autostart_focus", "false"),
            ("focus_mismatch_alerts_enabled", "true"),
            ("idle_alerts_enabled", "true"),
            ("missed_block_recovery_enabled", "true"),
            ("default_snooze_minutes", "5"),
            ("notification_rate_limit_seconds", "45"),
            ("quiet_hours_enabled", "false"),
            ("quiet_hours_start", "22:00"),
            ("quiet_hours_end", "07:00"),
            ("overnight_suppression_enabled", "true"),
            ("overnight_sleep_start", "23:00"),
            ("overnight_sleep_end", "07:00"),
        ]
        ts_now = now_iso()
        for k, v in default_settings:
            cur.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (k, v, ts_now),
            )
        db.commit()

        # Seed default categories if table is empty
        count = cur.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if count == 0:
            default_categories = [
                ("Coding & Development", "#8b5cf6", "focus"),      # Violet
                ("Research & Learning", "#06b6d4", "focus"),        # Cyan
                ("Communication & Meetings", "#3b82f6", "work"),    # Blue
                ("Planning & Management", "#10b981", "work"),       # Emerald
                ("Entertainment & Media", "#ef4444", "distraction"),# Red
                ("Social & Browsing", "#f59e0b", "distraction"),    # Amber
                ("Utilities & System", "#6b7280", "work"),          # Gray
                ("Other / Needs Review", "#9ca3af", "uncategorized"), # Slate - honest uncertain fallback, NOT personal
            ]
            ts = now_iso()
            for name, color, c_type in default_categories:
                cur.execute(
                    "INSERT INTO categories (name, color, type, created_at) VALUES (?, ?, ?, ?)",
                    (name, color, c_type, ts),
                )
            db.commit()

        # Seed default rules if category_rules is empty
        rules_count = cur.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
        if rules_count == 0:
            cat_map = {row[1]: row[0] for row in cur.execute("SELECT id, name FROM categories").fetchall()}
            
            ts = now_iso()
            default_rules = [
                # Coding (focus)
                (cat_map.get("Coding & Development"), "app", "code.exe", 20),
                (cat_map.get("Coding & Development"), "app", "cursor.exe", 20),
                (cat_map.get("Coding & Development"), "app", "devenv.exe", 20),
                (cat_map.get("Coding & Development"), "domain", "github.com", 30),
                (cat_map.get("Coding & Development"), "domain", "gitlab.com", 30),
                (cat_map.get("Coding & Development"), "domain", "stackoverflow.com", 30),

                # Research (focus)
                (cat_map.get("Research & Learning"), "domain", "chatgpt.com", 30),
                (cat_map.get("Research & Learning"), "domain", "claude.ai", 30),
                (cat_map.get("Research & Learning"), "domain", "docs.python.org", 30),
                (cat_map.get("Research & Learning"), "domain", "developer.mozilla.org", 30),
                (cat_map.get("Research & Learning"), "domain", "arxiv.org", 30),
                (cat_map.get("Research & Learning"), "domain", "medium.com", 25),

                # Communication (work)
                (cat_map.get("Communication & Meetings"), "app", "slack.exe", 20),
                (cat_map.get("Communication & Meetings"), "app", "teams.exe", 20),
                (cat_map.get("Communication & Meetings"), "app", "discord.exe", 20),
                (cat_map.get("Communication & Meetings"), "app", "whatsapp.root.exe", 20),
                (cat_map.get("Communication & Meetings"), "app", "whatsapp.exe", 20),
                (cat_map.get("Communication & Meetings"), "app", "outlook.exe", 20),
                (cat_map.get("Communication & Meetings"), "domain", "mail.google.com", 30),
                (cat_map.get("Communication & Meetings"), "domain", "outlook.office.com", 30),

                # Planning (work)
                (cat_map.get("Planning & Management"), "app", "notion.exe", 20),
                (cat_map.get("Planning & Management"), "domain", "notion.so", 30),
                (cat_map.get("Planning & Management"), "domain", "trello.com", 30),
                (cat_map.get("Planning & Management"), "domain", "linear.app", 30),
                (cat_map.get("Planning & Management"), "domain", "jira.atlassian.com", 30),

                # Entertainment (distraction)
                (cat_map.get("Entertainment & Media"), "app", "spotify.exe", 20),
                (cat_map.get("Entertainment & Media"), "app", "steam.exe", 20),
                (cat_map.get("Entertainment & Media"), "app", "steamwebhelper.exe", 20),
                (cat_map.get("Entertainment & Media"), "domain", "youtube.com", 30),
                (cat_map.get("Entertainment & Media"), "domain", "netflix.com", 30),
                (cat_map.get("Entertainment & Media"), "domain", "twitch.tv", 30),

                # Social (distraction)
                (cat_map.get("Social & Browsing"), "domain", "reddit.com", 30),
                (cat_map.get("Social & Browsing"), "domain", "twitter.com", 30),
                (cat_map.get("Social & Browsing"), "domain", "x.com", 30),
                (cat_map.get("Social & Browsing"), "domain", "facebook.com", 30),
                (cat_map.get("Social & Browsing"), "domain", "instagram.com", 30),

                # Utilities (work)
                (cat_map.get("Utilities & System"), "app", "explorer.exe", 10),
                (cat_map.get("Utilities & System"), "app", "cmd.exe", 10),
                (cat_map.get("Utilities & System"), "app", "powershell.exe", 10),
                (cat_map.get("Utilities & System"), "app", "windowsterminal.exe", 10),
            ]

            for cat_id, m_type, pattern, priority in default_rules:
                if cat_id is not None:
                    cur.execute(
                        """
                        INSERT INTO category_rules (category_id, match_type, pattern, priority, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (cat_id, m_type, pattern.lower(), priority, ts),
                    )
            db.commit()

        # Seed default goals if goals table is empty
        goals_count = cur.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
        if goals_count == 0:
            ts = now_iso()
            default_goals = [
                ("Daily Work Time", "work_time", None, 5 * 3600, 0, "daily", 1, ts),          # 5 hours
                ("Deep Focus Time", "focus_time", None, 3 * 3600, 0, "daily", 1, ts),          # 3 hours
                ("Distraction Limit", "distraction_time", None, 1 * 3600, 1, "daily", 1, ts), # Max 1 hour
            ]
            for title, metric, cat_id, target, is_inv, period, active, created in default_goals:
                cur.execute(
                    """
                    INSERT INTO goals (title, metric, category_id, target_seconds, is_inversion, period, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (title, metric, cat_id, target, is_inv, period, active, created),
                )
            db.commit()

        # -------------------------------------------------------------------
        # 7. Audit & Safely Repair Stale Unclosed Recovery Observations
        # -------------------------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS observation_recovery_audit (
                observation_id INTEGER PRIMARY KEY,
                old_end_time TEXT,
                old_duration_seconds REAL,
                new_end_time TEXT,
                new_duration_seconds REAL,
                reason TEXT,
                created_at TEXT
            )
        """)
        db.commit()

        # Update category ID 8 to never use 'personal' fallback
        cur.execute("""
            UPDATE categories
            SET type = 'uncategorized', name = 'Other / Needs Review'
            WHERE (name LIKE '%Uncategorized%' OR name LIKE '%Needs Review%') AND type = 'personal'
        """)
        db.commit()

        # Identify stale unclosed observations closed with now() across offline/shutdown gaps
        stale_candidates = cur.execute("""
            SELECT id, app, title, start_time, end_time, duration_seconds
            FROM observations
            WHERE duration_seconds > 1800 AND kind = 'active'
        """).fetchall()

        def _safe_parse_dt(dt_str: str) -> datetime:
            if not dt_str:
                return datetime.now(timezone.utc)
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        ts = now_iso()
        for r in stale_candidates:
            obs_id = r[0]
            st_str = r[3]
            et_str = r[4]
            old_dur = r[5] or 0.0

            try:
                st_dt = _safe_parse_dt(st_str)
                # Check for activity events during this observation
                ev_row = cur.execute("""
                    SELECT MAX(timestamp) FROM activity_events
                    WHERE timestamp >= ? AND timestamp <= ?
                """, (st_str, et_str)).fetchone()

                last_ev_str = ev_row[0] if ev_row else None
                event_span_sec = 0.0
                if last_ev_str:
                    last_ev_dt = _safe_parse_dt(last_ev_str)
                    event_span_sec = max(0.0, (last_ev_dt - st_dt).total_seconds())

                # If the entire observation duration is > 1800s but activity events ceased within 120s:
                # The observation was stretched across an unmonitored shutdown/sleep period!
                if event_span_sec <= 120.0 and old_dur > 1800.0:
                    if last_ev_str and event_span_sec > 0.0:
                        new_et = last_ev_str
                        new_dur = round(max(3.0, event_span_sec), 3)
                    else:
                        new_et = (st_dt + timedelta(seconds=3.0)).isoformat()
                        new_dur = 3.0

                    cur.execute("""
                        INSERT OR REPLACE INTO observation_recovery_audit
                            (observation_id, old_end_time, old_duration_seconds, new_end_time, new_duration_seconds, reason, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (obs_id, et_str, old_dur, new_et, new_dur, "stale_unclosed_recovery_gap", ts))

                    cur.execute("""
                        UPDATE observations
                        SET end_time = ?, duration_seconds = ?
                        WHERE id = ?
                    """, (new_et, new_dur, obs_id))
            except Exception as repair_err:
                pass

        db.commit()

        # Ensure high-value evidence rules exist for frequent study, search, and development patterns
        cat_map = {row[1]: row[0] for row in cur.execute("SELECT id, name FROM categories").fetchall()}
        research_cat = cat_map.get("Research & Learning")
        coding_cat = cat_map.get("Coding & Development")
        social_cat = cat_map.get("Social & Browsing")

        additional_rules = [
            (social_cat, "domain", "pinterest.com", 30),
            (research_cat, "domain", "monkeytype.com", 25),
            (research_cat, "title_contains", " - google search", 20),
            (coding_cat, "title_contains", "github", 25),
            (research_cat, "title_contains", "chatgpt", 25),
            (research_cat, "title_contains", "gemini", 25),
            (research_cat, "title_contains", "claude", 25),
        ]
        for c_id, m_t, pat, pri in additional_rules:
            if c_id:
                exists = cur.execute("""
                    SELECT 1 FROM category_rules WHERE match_type = ? AND pattern = ?
                """, (m_t, pat.lower())).fetchone()
                if not exists:
                    cur.execute("""
                        INSERT INTO category_rules (category_id, match_type, pattern, priority, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (c_id, m_t, pat.lower(), pri, ts))
        db.commit()

        return True
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    success = run_migrations()
    print("Database migrations applied successfully:", success)
