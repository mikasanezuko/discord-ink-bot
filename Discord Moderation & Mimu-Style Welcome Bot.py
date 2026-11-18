"""
================================================================================
DISCORD MODERATION & MIMU-STYLE WELCOME BOT (discord.py 2.x + Flask)
================================================================================
Designed for Replit 24/7 hosting with SQLite persistence, interactive Discord UI
Modals, Buttons, native timeouts, and Mimu-style welcome embed customization.

SETUP INSTRUCTIONS FOR REPLIT:
1. Create a new Python Repl and paste this entire file into `main.py`.
2. Add the required packages in Replit's Packages tab or `requirements.txt`:
   - discord.py>=2.3.2
   - flask>=3.0.0
3. In the Discord Developer Portal (https://discord.com/developers/applications):
   - Go to your Bot -> Privileged Gateway Intents -> Enable "SERVER MEMBERS INTENT"
     and "MESSAGE CONTENT INTENT".
4. In Replit Secrets (Tools -> Secrets), add:
   - Key: DISCORD_TOKEN
   - Value: <Your Discord Bot Token>
5. Run the Repl! Copy the Webview URL and ping it with UptimeRobot for 24/7 uptime.
================================================================================
"""

import os
import re
import sqlite3
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask


# ==============================================================================
# SECTION 1: RENDER & UPTIMEROBOT KEEP-ALIVE WEB SERVER (keep_alive.py)
# ==============================================================================

class KeepAliveHandler(BaseHTTPRequestHandler):
    """HTTP request handler supporting both GET and HEAD pings for Render & UptimeRobot."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = (
            "<h2>Bot is online and running!</h2>"
            "<p>Discord Moderation, VC Tracking, TempVoice & Study Suite are active.</p>"
        )
        self.wfile.write(html.encode("utf-8"))

    def do_HEAD(self):
        """Crucial for UptimeRobot HEAD checks so it doesn't throw 405 Method Not Allowed."""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        """Suppress default HTTP server access logs in console output."""
        return


def run_keep_alive():
    """Binds to 0.0.0.0 on Render's PORT environment variable (defaulting to 8080)."""
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    server.serve_forever()


def keep_alive():
    """Starts the HTTP keep-alive server in a non-blocking daemon thread."""
    server_thread = Thread(target=run_keep_alive, daemon=True)
    server_thread.start()


# ==============================================================================
# SECTION 2: SQLITE DATABASE MANAGER (Persistent Storage)
# ==============================================================================

DB_FILE = "bot_database.db"


class DatabaseManager:
    """Handles SQLite connections, table initialization, and CRUD operations."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Creates required tables for moderation logs and welcome settings."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Table for Warnings, Mutes (Timeouts), and Bans
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mod_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    internal_note TEXT,
                    duration TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )
            # Table for Mimu-style per-server welcome configurations
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    outside_content TEXT DEFAULT 'Haiii, {user}! Welcome to **{server}** (｡♥‿♥｡)',
                    embed_title TEXT DEFAULT '✨ Welcome to {server}!',
                    embed_description TEXT DEFAULT 'We are so happy to have you here, {user}!\nYou are member **#{member_count}** ♡',
                    footer_text TEXT DEFAULT 'Enjoy your stay • {username}',
                    embed_color TEXT DEFAULT '#f4c2c2',
                    thumbnail_url TEXT DEFAULT '{avatar}',
                    banner_url TEXT DEFAULT '',
                    footer_icon_url TEXT DEFAULT '',
                    show_author INTEGER DEFAULT 1
                )
                """
            )
            # Table for VC Study Time Tracking (Today, Week, Month, All-Time in seconds)
            # Tracks Total VC, Camera (self_video), Screen Share (self_stream), and non-overlapping Combined Cam/SS
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_study_stats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    daily_seconds INTEGER DEFAULT 0,
                    weekly_seconds INTEGER DEFAULT 0,
                    monthly_seconds INTEGER DEFAULT 0,
                    all_time_seconds INTEGER DEFAULT 0,
                    daily_cam_seconds INTEGER DEFAULT 0,
                    weekly_cam_seconds INTEGER DEFAULT 0,
                    monthly_cam_seconds INTEGER DEFAULT 0,
                    all_time_cam_seconds INTEGER DEFAULT 0,
                    daily_ss_seconds INTEGER DEFAULT 0,
                    weekly_ss_seconds INTEGER DEFAULT 0,
                    monthly_ss_seconds INTEGER DEFAULT 0,
                    all_time_ss_seconds INTEGER DEFAULT 0,
                    daily_cam_ss_seconds INTEGER DEFAULT 0,
                    weekly_cam_ss_seconds INTEGER DEFAULT 0,
                    monthly_cam_ss_seconds INTEGER DEFAULT 0,
                    all_time_cam_ss_seconds INTEGER DEFAULT 0,
                    last_day_key TEXT NOT NULL,
                    last_week_key TEXT NOT NULL,
                    last_month_key TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            # Lightweight schema migration if upgrading an existing database file
            existing_cols = {
                row[1] for row in cursor.execute("PRAGMA table_info(vc_study_stats)").fetchall()
            }
            new_metric_cols = [
                "daily_cam_seconds", "weekly_cam_seconds", "monthly_cam_seconds", "all_time_cam_seconds",
                "daily_ss_seconds", "weekly_ss_seconds", "monthly_ss_seconds", "all_time_ss_seconds",
                "daily_cam_ss_seconds", "weekly_cam_ss_seconds", "monthly_cam_ss_seconds", "all_time_cam_ss_seconds",
            ]
            for col_name in new_metric_cols:
                if col_name not in existing_cols:
                    cursor.execute(
                        f"ALTER TABLE vc_study_stats ADD COLUMN {col_name} INTEGER DEFAULT 0"
                    )
            # Table for Untracked (Excluded) Voice Channels per Guild
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_untracked_channels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )
                """
            )
            # Table for TempVoice per-guild configuration
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tempvoice_settings (
                    guild_id INTEGER PRIMARY KEY,
                    hub_channel_id INTEGER,
                    category_id INTEGER,
                    name_format TEXT DEFAULT '🌿・{username}''s study room',
                    interface_channel_id INTEGER,
                    interface_message_id INTEGER
                )
                """
            )
            # Table for active Temporary Voice Channels (persists ownership across restarts)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tempvoice_channels (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    owner_id INTEGER NOT NULL,
                    privacy_mode TEXT DEFAULT 'open',
                    chat_enabled INTEGER DEFAULT 1
                )
                """
            )
            # Table for Server Autoroles
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS server_autoroles (
                    guild_id INTEGER PRIMARY KEY,
                    role_ids TEXT DEFAULT '[]'
                )
                """
            )
            # Table for Challenge VCs (Cam-Only / SS-Only with grace periods)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS challenge_vcs (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    challenge_type TEXT NOT NULL,
                    grace_seconds INTEGER DEFAULT 30
                )
                """
            )
            # Table for Personal Tasks
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    due_date TEXT,
                    completed INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # --- Moderation DB Methods ---
    def add_mod_log(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        action_type: str,
        reason: str,
        internal_note: Optional[str] = None,
        duration: Optional[str] = None,
    ) -> int:
        """Inserts a moderation record and returns the new case ID."""
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO mod_logs (
                    guild_id, user_id, moderator_id, action_type,
                    reason, internal_note, duration, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    user_id,
                    moderator_id,
                    action_type,
                    reason,
                    internal_note or "None",
                    duration or "N/A",
                    timestamp,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_user_logs(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        """Fetches all moderation logs for a specific member in a guild."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM mod_logs
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC
                """,
                (guild_id, user_id),
            )
            return cursor.fetchall()

    # --- Welcome Settings DB Methods ---
    def get_welcome_config(self, guild_id: int) -> dict:
        """Retrieves or initializes default welcome settings for a server."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,)
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    "INSERT INTO welcome_settings (guild_id) VALUES (?)", (guild_id,)
                )
                conn.commit()
                cursor.execute(
                    "SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,)
                )
                row = cursor.fetchone()
            return dict(row)

    def update_welcome_config(self, guild_id: int, **kwargs):
        """Updates specific welcome setting columns for a guild."""
        self.get_welcome_config(guild_id)  # Ensure row exists
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE welcome_settings SET {columns} WHERE guild_id = ?", values
            )
            conn.commit()

    # --- VC Study Time DB Methods ---
    @staticmethod
    def get_ist_period_keys() -> tuple[str, str, str]:
        """Returns (day_key, week_key, month_key) in IST (UTC+5:30)."""
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.datetime.now(ist_tz)
        iso_year, iso_week, _ = now_ist.isocalendar()
        day_key = now_ist.strftime("%Y-%m-%d")
        week_key = f"{iso_year}-W{iso_week:02d}"
        month_key = now_ist.strftime("%Y-%m")
        return day_key, week_key, month_key

    def _sync_period_resets(self, conn: sqlite3.Connection, guild_id: int, user_id: int) -> sqlite3.Row:
        """Ensures a user's VC stats row exists and resets expired IST day/week/month counters."""
        day_key, week_key, month_key = self.get_ist_period_keys()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                """
                INSERT INTO vc_study_stats (
                    guild_id, user_id,
                    daily_seconds, weekly_seconds, monthly_seconds, all_time_seconds,
                    daily_cam_seconds, weekly_cam_seconds, monthly_cam_seconds, all_time_cam_seconds,
                    daily_ss_seconds, weekly_ss_seconds, monthly_ss_seconds, all_time_ss_seconds,
                    daily_cam_ss_seconds, weekly_cam_ss_seconds, monthly_cam_ss_seconds, all_time_cam_ss_seconds,
                    last_day_key, last_week_key, last_month_key
                ) VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?, ?, ?)
                """,
                (guild_id, user_id, day_key, week_key, month_key),
            )
            conn.commit()
            cursor.execute(
                "SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            return cursor.fetchone()

        same_day = row["last_day_key"] == day_key
        same_week = row["last_week_key"] == week_key
        same_month = row["last_month_key"] == month_key

        if not (same_day and same_week and same_month):
            cursor.execute(
                """
                UPDATE vc_study_stats
                SET daily_seconds = ?, weekly_seconds = ?, monthly_seconds = ?,
                    daily_cam_seconds = ?, weekly_cam_seconds = ?, monthly_cam_seconds = ?,
                    daily_ss_seconds = ?, weekly_ss_seconds = ?, monthly_ss_seconds = ?,
                    daily_cam_ss_seconds = ?, weekly_cam_ss_seconds = ?, monthly_cam_ss_seconds = ?,
                    last_day_key = ?, last_week_key = ?, last_month_key = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    row["daily_seconds"] if same_day else 0,
                    row["weekly_seconds"] if same_week else 0,
                    row["monthly_seconds"] if same_month else 0,
                    row["daily_cam_seconds"] if same_day else 0,
                    row["weekly_cam_seconds"] if same_week else 0,
                    row["monthly_cam_seconds"] if same_month else 0,
                    row["daily_ss_seconds"] if same_day else 0,
                    row["weekly_ss_seconds"] if same_week else 0,
                    row["monthly_ss_seconds"] if same_month else 0,
                    row["daily_cam_ss_seconds"] if same_day else 0,
                    row["weekly_cam_ss_seconds"] if same_week else 0,
                    row["monthly_cam_ss_seconds"] if same_month else 0,
                    day_key, week_key, month_key,
                    guild_id, user_id,
                ),
            )
            conn.commit()
            cursor.execute(
                "SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            return cursor.fetchone()
        return row

    def add_vc_metrics(
        self,
        guild_id: int,
        user_id: int,
        vc_seconds: int = 0,
        cam_seconds: int = 0,
        ss_seconds: int = 0,
        cam_ss_seconds: int = 0,
    ):
        """Adds tracked VC, Cam, SS, and non-overlapping Combined Cam/SS seconds across IST periods."""
        if vc_seconds <= 0 and cam_seconds <= 0 and ss_seconds <= 0 and cam_ss_seconds <= 0:
            return
        with self._get_connection() as conn:
            self._sync_period_resets(conn, guild_id, user_id)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE vc_study_stats
                SET daily_seconds = daily_seconds + ?,
                    weekly_seconds = weekly_seconds + ?,
                    monthly_seconds = monthly_seconds + ?,
                    all_time_seconds = all_time_seconds + ?,
                    daily_cam_seconds = daily_cam_seconds + ?,
                    weekly_cam_seconds = weekly_cam_seconds + ?,
                    monthly_cam_seconds = monthly_cam_seconds + ?,
                    all_time_cam_seconds = all_time_cam_seconds + ?,
                    daily_ss_seconds = daily_ss_seconds + ?,
                    weekly_ss_seconds = weekly_ss_seconds + ?,
                    monthly_ss_seconds = monthly_ss_seconds + ?,
                    all_time_ss_seconds = all_time_ss_seconds + ?,
                    daily_cam_ss_seconds = daily_cam_ss_seconds + ?,
                    weekly_cam_ss_seconds = weekly_cam_ss_seconds + ?,
                    monthly_cam_ss_seconds = monthly_cam_ss_seconds + ?,
                    all_time_cam_ss_seconds = all_time_cam_ss_seconds + ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    vc_seconds, vc_seconds, vc_seconds, vc_seconds,
                    cam_seconds, cam_seconds, cam_seconds, cam_seconds,
                    ss_seconds, ss_seconds, ss_seconds, ss_seconds,
                    cam_ss_seconds, cam_ss_seconds, cam_ss_seconds, cam_ss_seconds,
                    guild_id, user_id,
                ),
            )
            conn.commit()

    def adjust_vc_seconds(
        self, guild_id: int, user_id: int, metric: str, action: str, seconds: int
    ):
        """
        Admin manual adjustment: 'add', 'remove', or 'set' seconds for
        metric in ('vc', 'cam', 'ss'). Also keeps combined cam_ss consistent.
        """
        prefix_map = {
            "vc": ("daily_seconds", "weekly_seconds", "monthly_seconds", "all_time_seconds"),
            "cam": ("daily_cam_seconds", "weekly_cam_seconds", "monthly_cam_seconds", "all_time_cam_seconds"),
            "ss": ("daily_ss_seconds", "weekly_ss_seconds", "monthly_ss_seconds", "all_time_ss_seconds"),
        }
        cols = prefix_map.get(metric, prefix_map["vc"])

        with self._get_connection() as conn:
            row = self._sync_period_resets(conn, guild_id, user_id)
            new_vals = []
            for col in cols:
                cur = row[col]
                if action == "add":
                    new_vals.append(cur + seconds)
                elif action == "remove":
                    new_vals.append(max(0, cur - seconds))
                else:
                    new_vals.append(max(0, seconds))

            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE vc_study_stats
                SET {cols[0]} = ?, {cols[1]} = ?, {cols[2]} = ?, {cols[3]} = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (*new_vals, guild_id, user_id),
            )

            # Keep combined Cam+SS totals at least max(cam, ss) and synced with adjustments
            if metric in ("cam", "ss"):
                cursor.execute(
                    "SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
                updated_row = cursor.fetchone()
                comb_updates = {}
                for period in ("daily", "weekly", "monthly", "all_time"):
                    cam_v = updated_row[f"{period}_cam_seconds"]
                    ss_v = updated_row[f"{period}_ss_seconds"]
                    cur_comb = updated_row[f"{period}_cam_ss_seconds"]
                    if action == "add":
                        comb_updates[f"{period}_cam_ss_seconds"] = cur_comb + seconds
                    elif action == "remove":
                        comb_updates[f"{period}_cam_ss_seconds"] = max(
                            max(cam_v, ss_v), max(0, cur_comb - seconds)
                        )
                    else:
                        comb_updates[f"{period}_cam_ss_seconds"] = max(cam_v, ss_v)

                cursor.execute(
                    """
                    UPDATE vc_study_stats
                    SET daily_cam_ss_seconds = ?, weekly_cam_ss_seconds = ?,
                        monthly_cam_ss_seconds = ?, all_time_cam_ss_seconds = ?
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (
                        comb_updates["daily_cam_ss_seconds"],
                        comb_updates["weekly_cam_ss_seconds"],
                        comb_updates["monthly_cam_ss_seconds"],
                        comb_updates["all_time_cam_ss_seconds"],
                        guild_id,
                        user_id,
                    ),
                )
            conn.commit()

    def get_user_vc_stats(self, guild_id: int, user_id: int) -> dict:
        """Returns up-to-date IST study stats (VC, Cam, SS, Combined) and All-Time VC rank."""
        with self._get_connection() as conn:
            row = self._sync_period_resets(conn, guild_id, user_id)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) + 1 AS rank
                FROM vc_study_stats
                WHERE guild_id = ? AND all_time_seconds > ?
                """,
                (guild_id, row["all_time_seconds"]),
            )
            rank_row = cursor.fetchone()
            data = dict(row)
            data["rank"] = rank_row["rank"] if rank_row else 1
            return data

    def get_vc_leaderboard_all_rows(self, guild_id: int) -> list[dict]:
        """Normalizes IST resets across the guild and returns all user stat rows."""
        day_key, week_key, month_key = self.get_ist_period_keys()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE vc_study_stats
                SET daily_seconds = CASE WHEN last_day_key = ? THEN daily_seconds ELSE 0 END,
                    weekly_seconds = CASE WHEN last_week_key = ? THEN weekly_seconds ELSE 0 END,
                    monthly_seconds = CASE WHEN last_month_key = ? THEN monthly_seconds ELSE 0 END,
                    daily_cam_seconds = CASE WHEN last_day_key = ? THEN daily_cam_seconds ELSE 0 END,
                    weekly_cam_seconds = CASE WHEN last_week_key = ? THEN weekly_cam_seconds ELSE 0 END,
                    monthly_cam_seconds = CASE WHEN last_month_key = ? THEN monthly_cam_seconds ELSE 0 END,
                    daily_ss_seconds = CASE WHEN last_day_key = ? THEN daily_ss_seconds ELSE 0 END,
                    weekly_ss_seconds = CASE WHEN last_week_key = ? THEN weekly_ss_seconds ELSE 0 END,
                    monthly_ss_seconds = CASE WHEN last_month_key = ? THEN monthly_ss_seconds ELSE 0 END,
                    daily_cam_ss_seconds = CASE WHEN last_day_key = ? THEN daily_cam_ss_seconds ELSE 0 END,
                    weekly_cam_ss_seconds = CASE WHEN last_week_key = ? THEN weekly_cam_ss_seconds ELSE 0 END,
                    monthly_cam_ss_seconds = CASE WHEN last_month_key = ? THEN monthly_cam_ss_seconds ELSE 0 END,
                    last_day_key = ?, last_week_key = ?, last_month_key = ?
                WHERE guild_id = ? AND (
                    last_day_key != ? OR last_week_key != ? OR last_month_key != ?
                )
                """,
                (
                    day_key, week_key, month_key,
                    day_key, week_key, month_key,
                    day_key, week_key, month_key,
                    day_key, week_key, month_key,
                    day_key, week_key, month_key,
                    guild_id,
                    day_key, week_key, month_key,
                ),
            )
            conn.commit()
            cursor.execute(
                "SELECT * FROM vc_study_stats WHERE guild_id = ?",
                (guild_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_untracked_channels(self, guild_id: int) -> set[int]:
        """Returns a set of voice channel IDs excluded from tracking in a guild."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT channel_id FROM vc_untracked_channels WHERE guild_id = ?",
                (guild_id,),
            )
            return {row["channel_id"] for row in cursor.fetchall()}

    def set_untracked_channels(self, guild_id: int, channel_ids: list[int]):
        """Replaces the list of untracked voice channels for a guild."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM vc_untracked_channels WHERE guild_id = ?",
                (guild_id,),
            )
            for cid in set(channel_ids):
                cursor.execute(
                    "INSERT INTO vc_untracked_channels (guild_id, channel_id) VALUES (?, ?)",
                    (guild_id, cid),
                )
            conn.commit()

    # --- TempVoice DB Methods ---
    def get_tempvoice_config(self, guild_id: int) -> dict:
        """Retrieves or initializes TempVoice configuration for a server."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,)
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    "INSERT INTO tempvoice_settings (guild_id) VALUES (?)", (guild_id,)
                )
                conn.commit()
                cursor.execute(
                    "SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,)
                )
                row = cursor.fetchone()
            return dict(row)

    def update_tempvoice_config(self, guild_id: int, **kwargs):
        """Updates TempVoice configuration fields for a server."""
        self.get_tempvoice_config(guild_id)
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE tempvoice_settings SET {columns} WHERE guild_id = ?", values
            )
            conn.commit()

    def register_temp_channel(
        self,
        channel_id: int,
        guild_id: int,
        owner_id: int,
        privacy_mode: str = "open",
        chat_enabled: int = 1,
    ):
        """Saves a newly created temporary voice channel and its owner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO tempvoice_channels (
                    channel_id, guild_id, owner_id, privacy_mode, chat_enabled
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (channel_id, guild_id, owner_id, privacy_mode, chat_enabled),
            )
            conn.commit()

    def get_temp_channel(self, channel_id: int) -> Optional[dict]:
        """Fetches metadata for an active temporary voice channel."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tempvoice_channels WHERE channel_id = ?", (channel_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_temp_channel(self, channel_id: int, **kwargs):
        """Updates owner, privacy_mode, or chat_enabled for a temporary voice channel."""
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [channel_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE tempvoice_channels SET {columns} WHERE channel_id = ?", values
            )
            conn.commit()

    def delete_temp_channel(self, channel_id: int):
        """Removes a temporary voice channel record from SQLite."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM tempvoice_channels WHERE channel_id = ?", (channel_id,)
            )
            conn.commit()

    def get_all_temp_channels(self, guild_id: Optional[int] = None) -> list[dict]:
        """Returns all tracked temporary voice channels (optionally filtered by guild)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if guild_id is not None:
                cursor.execute(
                    "SELECT * FROM tempvoice_channels WHERE guild_id = ?", (guild_id,)
                )
            else:
                cursor.execute("SELECT * FROM tempvoice_channels")
            return [dict(r) for r in cursor.fetchall()]

    # --- Autorole DB Methods ---
    def get_autoroles(self, guild_id: int) -> list[int]:
        """Returns a list of role IDs configured for automatic assignment."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT role_ids FROM server_autoroles WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            if not row or not row["role_ids"]:
                return []
            try:
                return json.loads(row["role_ids"])
            except json.JSONDecodeError:
                return []

    def set_autoroles(self, guild_id: int, role_ids: list[int]):
        """Saves configured autorole IDs for a server."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO server_autoroles (guild_id, role_ids) VALUES (?, ?)",
                (guild_id, json.dumps(list(set(role_ids)))),
            )
            conn.commit()

    # --- Challenge VC DB Methods ---
    def get_challenge_vc(self, channel_id: int) -> Optional[dict]:
        """Fetches challenge VC settings if the channel is a Cam-Only or SS-Only room."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM challenge_vcs WHERE channel_id = ?", (channel_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_challenge_vc(self, channel_id: int, guild_id: int, challenge_type: str, grace_seconds: int):
        """Registers or updates a challenge voice channel."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO challenge_vcs (channel_id, guild_id, challenge_type, grace_seconds)
                VALUES (?, ?, ?, ?)
                """,
                (channel_id, guild_id, challenge_type, grace_seconds),
            )
            conn.commit()

    def remove_challenge_vc(self, channel_id: int):
        """Removes a channel from challenge tracking."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM challenge_vcs WHERE channel_id = ?", (channel_id,))
            conn.commit()

    # --- Task DB Methods ---
    def add_user_task(self, user_id: int, title: str, due_date: Optional[str]) -> int:
        """Adds a personal task for a user."""
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_tasks (user_id, title, due_date, completed, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (user_id, title, due_date or "No deadline", timestamp),
            )
            conn.commit()
            return cursor.lastrowid

    def get_user_tasks(self, user_id: int) -> list[sqlite3.Row]:
        """Fetches all active tasks for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_tasks WHERE user_id = ? ORDER BY id DESC", (user_id,))
            return cursor.fetchall()

    def update_task_status(self, task_id: int, user_id: int, completed: int):
        """Updates task completion status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_tasks SET completed = ? WHERE id = ? AND user_id = ?",
                (completed, task_id, user_id),
            )
            conn.commit()

    def clear_user_tasks(self, user_id: int):
        """Deletes completed tasks for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_tasks WHERE user_id = ? AND completed = 1", (user_id,))
            conn.commit()


db = DatabaseManager()


# ==============================================================================
# SECTION 9: COMPREHENSIVE HELP COMMAND COG (cogs/help.py)
# ==============================================================================

class HelpSelect(discord.ui.Select):
    """Interactive category selector for the help command dashboard."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label="Moderation & Modals",
                description="Warn, Mute, Ban, and ModLogs commands",
                emoji="🛡️",
                value="mod",
            ),
            discord.SelectOption(
                label="Welcome System",
                description="Mimu-style welcome setup and embed customization",
                emoji="🌸",
                value="welcome",
            ),
            discord.SelectOption(
                label="VC Tracking & Stats",
                description="Voice Study Time tracking, Cam/SS metrics & Leaderboards",
                emoji="⏱️",
                value="vctracker",
            ),
            discord.SelectOption(
                label="TempVoice (Join-to-Create)",
                description="Personal voice room creation and interactive controls",
                emoji="🎙️",
                value="tempvoice",
            ),
            discord.SelectOption(
                label="Study, Tasks & Challenge VCs",
                description="Pomodoro timers, To-Do list, and Cam/SS Challenge VCs",
                emoji="🍅",
                value="study",
            ),
            discord.SelectOption(
                label="Utility & Autoroles",
                description="Message purging and automated new member roles",
                emoji="⚙️",
                value="utility",
            ),
        ]
        super().__init__(placeholder="Select a command category to browse...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        embed = discord.Embed(
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        if val == "mod":
            embed.title = "🛡️ Moderation & Modal Commands"
            embed.description = (
                "Interactive UI Modal-based moderation suite requiring respective permissions:\n\n"
                "• `/warn <member>` — Opens a modal for Reason & Internal Note. Logs warning & DMs user.\n"
                "• `/mute <member>` — Opens a modal for Duration (e.g., 10m, 1h) & Reason. Applies native timeout.\n"
                "• `/ban <member>` — Opens a modal for Reason & Message History deletion (0-7 days).\n"
                "• `/modlogs <member>` — Displays paginated history of past warnings, mutes, and bans."
            )
        elif val == "welcome":
            embed.title = "🌸 Mimu-Style Welcome Embed Builder"
            embed.description = (
                "Automated welcome system supporting dynamic placeholders (`{user}`, `{username}`, `{server}`, `{member_count}`, `{avatar}`):\n\n"
                "• `/welcome-setup <channel>` — Sets the welcome channel and opens an interactive setup dashboard with buttons to edit text content, visuals, images, and test previews."
            )
        elif val == "vctracker":
            embed.title = "⏱️ Voice Tracking & Leaderboards"
            embed.description = (
                "Accurate IST (UTC+5:30) voice study time tracking for Total VC, Camera (`self_video`), Screen Share (`self_stream`), and Combined Cam/SS:\n\n"
                "• `/stats [member]` — Displays live session status, server rank, and time breakdowns (Today, Week, Month, All-Time).\n"
                "• `/leaderboard` — Paginated top studiers with timeframe filters ([Daily], [Weekly], [Monthly], [All-Time]) and category dropdowns.\n"
                "• `/vc-settings` — Admin panel to manage untracked VCs and manually adjust user hours."
            )
        elif val == "tempvoice":
            embed.title = "🎙️ TempVoice (Join-to-Create VCs)"
            embed.description = (
                "Personal voice channel spawning system with persistent 3-row button controls:\n\n"
                "• `/tempvoice-setup` — Configures the Hub VC, target category, name format, and control panel.\n"
                "• **Control Buttons** — Name, Limit, Privacy, Chat, Trust, Untrust, Kick, Region, Claim, Transfer, and Delete."
            )
        elif val == "study":
            embed.title = "🍅 Study Suite, Tasks & Challenge VCs"
            embed.description = (
                "Accountability and productivity tools:\n\n"
                "• `/task add <title> [due]` — Adds a personal to-do task.\n"
                "• `/task list` — Displays active tasks with interactive `[Complete]` and `[Delete]` buttons.\n"
                "• `/task clear` — Clears completed tasks.\n"
                "• `/pomodoro start [work] [break]` — Launches a guided Pomodoro study focus timer.\n"
                "• `/challenge-vc-setup` — Sets up Cam-Only or SS-Only VCs with automatic grace period disconnects."
            )
        elif val == "utility":
            embed.title = "⚙️ Utility & Autorole System"
            embed.description = (
                "Server management tools:\n\n"
                "• `/purge <amount> [member]` — Instantly deletes 1-100 messages (handles 14-day limit).\n"
                "• `/autorole-setup` — Configures default roles automatically assigned to new members."
            )

        embed.set_footer(text="Use the dropdown menu below to switch categories • Bot v2.x")
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    """Persistent view containing the help category dropdown."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HelpSelect())


class HelpCog(commands.Cog):
    """Cog for comprehensive bot help and command directory."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Displays the comprehensive categorized help command directory.",
    )
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✨ Bot Command Directory & Help",
            description=(
                "Welcome to the **Discord Moderation, VC Tracking, TempVoice & Study Bot**!\n"
                "Use the interactive dropdown menu below to explore categories and view command usage.\n\n"
                "📌 **Categories Available:**\n"
                "• 🛡️ Moderation & Modals (`/warn`, `/mute`, `/ban`, `/modlogs`)\n"
                "• 🌸 Welcome System (`/welcome-setup`)\n"
                "• ⏱️ VC Tracking & Leaderboards (`/stats`, `/leaderboard`, `/vc-settings`)\n"
                "• 🎙️ TempVoice / Join-to-Create (`/tempvoice-setup`)\n"
                "• 🍅 Study Suite, Tasks & Challenge VCs (`/task`, `/pomodoro`, `/challenge-vc-setup`)\n"
                "• ⚙️ Utility & Autoroles (`/purge`, `/autorole-setup`)"
            ),
            color=discord.Color.from_str("#f4c2c2"),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_footer(text="Select a category from the dropdown menu below 👇")
        view = HelpView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ==============================================================================
# SECTION 10: MAIN BOT INITIALIZATION & GLOBAL ERROR HANDLING (main.py)
# ==============================================================================


class ModWelcomeBot(commands.Bot):
    """Custom discord.py 2.x Bot subclass with automatic Cog & Slash Command syncing."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True          # Required for on_member_join & member lookups
        intents.voice_states = True     # Required for accurate VC study time tracking
        intents.message_content = True  # Recommended for full server functionality

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        """Registers Cogs, persistent UI views, and syncs application slash commands globally."""
        await self.add_cog(ModerationCog(self))
        await self.add_cog(WelcomeCog(self))
        await self.add_cog(VCTrackerCog(self))
        await self.add_cog(TempVoiceCog(self))
        await self.add_cog(UtilityCog(self))
        await self.add_cog(AutoroleCog(self))
        await self.add_cog(ChallengeVCsCog(self))
        await self.add_cog(PomodoroTasksCog(self))
        await self.add_cog(HelpCog(self))

        # Register persistent views so buttons and dropdowns survive restarts
        self.add_view(TempVoiceControlView())
        self.add_view(HelpView())

        # Global slash command error handler
        self.tree.on_error = self.on_app_command_error

        synced = await self.tree.sync()
        print(f"[Slash Commands] Synced {len(synced)} command(s) globally.")

    async def on_ready(self):
        print("=" * 55)
        print(f"Logged in as: {self.user} (ID: {self.user.id})")
        print(f"Connected to {len(self.guilds)} server(s).")
        print("Status: Ready & Listening for Modals / Events!")
        print("=" * 55)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="over the server 🌸",
            )
        )

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """Gracefully handles missing permissions or unexpected slash command errors."""
        if isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(error.missing_permissions)
            msg = f"🚫 You are missing required permission(s): `{missing}`."
        elif isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            msg = f"🚫 I am missing required permission(s): `{missing}`."
        else:
            msg = f"⚠️ Command Error: `{error}`"

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "CRITICAL ERROR: 'DISCORD_TOKEN' was not found in environment variables!\n"
            "Please add DISCORD_TOKEN in Render Environment Variables or Replit Secrets and restart."
        )

    # Start HTTP keep-alive server in a background thread for 24/7 Render/UptimeRobot uptime
    keep_alive()

    # Launch the Discord bot
    bot = ModWelcomeBot()
    bot.run(token)