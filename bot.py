"""
================================================================================
DISCORD MODERATION, STUDY, & UTILITY SUITE BOT (discord.py 2.x)
================================================================================
Designed for 24/7 hosting on Render / Replit with SQLite persistence, interactive
Discord UI Modals, Buttons, Select menus, native timeouts, AFK system, mutually
exclusive VC accountability buckets, IST daily study streaks, challenge window
lookup, leaderboard exclusions, audit logs, and custom activity presence.
================================================================================
"""

import os
import re
import json
import asyncio
import sqlite3
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks


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
            "<p>Discord Moderation, VC Tracking, TempVoice, AFK, Streaks, Presence & Audit Suite are active.</p>"
        )
        self.wfile.write(html.encode("utf-8"))

    def do_HEAD(self):
        """Crucial for UptimeRobot HEAD checks so it doesn't throw 405 Method Not Allowed."""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        return


def run_keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    server.serve_forever()


def keep_alive():
    server_thread = Thread(target=run_keep_alive, daemon=True)
    server_thread.start()


# ==============================================================================
# SECTION 2: SQLITE DATABASE MANAGER (Persistent Storage)
# ==============================================================================

os.makedirs("data", exist_ok=True)
DB_FILE = os.path.join("data", "bot_data.db")
IST_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class DatabaseManager:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str):
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        cols = {row["name"] for row in cursor.fetchall()}
        if column not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_study_stats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    daily_seconds INTEGER DEFAULT 0,
                    weekly_seconds INTEGER DEFAULT 0,
                    monthly_seconds INTEGER DEFAULT 0,
                    all_time_seconds INTEGER DEFAULT 0,
                    daily_cam_only_seconds INTEGER DEFAULT 0,
                    weekly_cam_only_seconds INTEGER DEFAULT 0,
                    monthly_cam_only_seconds INTEGER DEFAULT 0,
                    all_time_cam_only_seconds INTEGER DEFAULT 0,
                    daily_ss_only_seconds INTEGER DEFAULT 0,
                    weekly_ss_only_seconds INTEGER DEFAULT 0,
                    monthly_ss_only_seconds INTEGER DEFAULT 0,
                    all_time_ss_only_seconds INTEGER DEFAULT 0,
                    daily_both_seconds INTEGER DEFAULT 0,
                    weekly_both_seconds INTEGER DEFAULT 0,
                    monthly_both_seconds INTEGER DEFAULT 0,
                    all_time_both_seconds INTEGER DEFAULT 0,
                    daily_plain_seconds INTEGER DEFAULT 0,
                    weekly_plain_seconds INTEGER DEFAULT 0,
                    monthly_plain_seconds INTEGER DEFAULT 0,
                    all_time_plain_seconds INTEGER DEFAULT 0,
                    last_day_key TEXT NOT NULL,
                    last_week_key TEXT NOT NULL,
                    last_month_key TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )

            for period in ("daily", "weekly", "monthly", "all_time"):
                self._ensure_column(conn, "vc_study_stats", f"{period}_cam_only_seconds", "INTEGER DEFAULT 0")
                self._ensure_column(conn, "vc_study_stats", f"{period}_ss_only_seconds", "INTEGER DEFAULT 0")
                self._ensure_column(conn, "vc_study_stats", f"{period}_both_seconds", "INTEGER DEFAULT 0")
                self._ensure_column(conn, "vc_study_stats", f"{period}_plain_seconds", "INTEGER DEFAULT 0")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_interval_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    bucket TEXT NOT NULL,
                    start_utc REAL NOT NULL,
                    end_utc REAL NOT NULL,
                    duration_seconds INTEGER NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vc_interval_lookup
                ON vc_interval_logs (guild_id, start_utc, end_utc)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_untracked_channels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_excluded_users (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS server_autoroles (
                    guild_id INTEGER PRIMARY KEY,
                    role_ids TEXT DEFAULT '[]'
                )
                """
            )
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_afk (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS streak_config (
                    guild_id INTEGER PRIMARY KEY,
                    min_daily_seconds INTEGER DEFAULT 1800
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_streaks (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    last_qualified_day TEXT,
                    last_evaluated_day TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_presence_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    custom_override INTEGER DEFAULT 0,
                    activity_type TEXT DEFAULT 'watching',
                    activity_name TEXT DEFAULT '🌛 The Study Hall',
                    online_status TEXT DEFAULT 'online'
                )
                """
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO bot_presence_config (id, custom_override, activity_type, activity_name, online_status)
                VALUES (1, 0, 'watching', '🌛 The Study Hall', 'online')
                """
            )
            conn.commit()

    def get_presence_config(self) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_presence_config WHERE id = 1")
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    "INSERT INTO bot_presence_config (id, custom_override, activity_type, activity_name, online_status) VALUES (1, 0, 'watching', '🌛 The Study Hall', 'online')"
                )
                conn.commit()
                cursor.execute("SELECT * FROM bot_presence_config WHERE id = 1")
                row = cursor.fetchone()
            return dict(row)

    def set_presence_config(self, custom_override: int, activity_type: str, activity_name: str, online_status: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE bot_presence_config
                SET custom_override = ?, activity_type = ?, activity_name = ?, online_status = ?
                WHERE id = 1
                """,
                (custom_override, activity_type, activity_name, online_status),
            )
            conn.commit()

    def add_mod_log(self, guild_id: int, user_id: int, moderator_id: int, action_type: str, reason: str, internal_note: Optional[str] = None, duration: Optional[str] = None) -> int:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO mod_logs (guild_id, user_id, moderator_id, action_type, reason, internal_note, duration, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, moderator_id, action_type, reason, internal_note or "None", duration or "N/A", timestamp),
            )
            conn.commit()
            return cursor.lastrowid

    def get_user_logs(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mod_logs WHERE guild_id = ? AND user_id = ? ORDER BY id DESC", (guild_id, user_id))
            return cursor.fetchall()

    def get_welcome_config(self, guild_id: int) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO welcome_settings (guild_id) VALUES (?)", (guild_id,))
                conn.commit()
                cursor.execute("SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,))
                row = cursor.fetchone()
            return dict(row)

    def update_welcome_config(self, guild_id: int, **kwargs):
        self.get_welcome_config(guild_id)
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE welcome_settings SET {columns} WHERE guild_id = ?", values)
            conn.commit()

    @staticmethod
    def get_ist_now() -> datetime.datetime:
        return datetime.datetime.now(IST_TZ)

    @classmethod
    def get_ist_period_keys(cls, now_ist: Optional[datetime.datetime] = None) -> tuple[str, str, str]:
        if now_ist is None:
            now_ist = cls.get_ist_now()
        iso_year, iso_week, _ = now_ist.isocalendar()
        day_key = now_ist.strftime("%Y-%m-%d")
        week_key = f"{iso_year}-W{iso_week:02d}"
        month_key = now_ist.strftime("%Y-%m")
        return day_key, week_key, month_key

    def _sync_period_resets(self, conn: sqlite3.Connection, guild_id: int, user_id: int) -> sqlite3.Row:
        day_key, week_key, month_key = self.get_ist_period_keys()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                """
                INSERT INTO vc_study_stats (
                    guild_id, user_id,
                    daily_seconds, weekly_seconds, monthly_seconds, all_time_seconds,
                    daily_cam_only_seconds, weekly_cam_only_seconds, monthly_cam_only_seconds, all_time_cam_only_seconds,
                    daily_ss_only_seconds, weekly_ss_only_seconds, monthly_ss_only_seconds, all_time_ss_only_seconds,
                    daily_both_seconds, weekly_both_seconds, monthly_both_seconds, all_time_both_seconds,
                    daily_plain_seconds, weekly_plain_seconds, monthly_plain_seconds, all_time_plain_seconds,
                    last_day_key, last_week_key, last_month_key
                ) VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?, ?, ?)
                """,
                (guild_id, user_id, day_key, week_key, month_key),
            )
            conn.commit()
            cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            return cursor.fetchone()

        same_day = row["last_day_key"] == day_key
        same_week = row["last_week_key"] == week_key
        same_month = row["last_month_key"] == month_key

        if not (same_day and same_week and same_month):
            def pick(col: str, keep: bool) -> int:
                return row[col] if keep else 0

            cursor.execute(
                """
                UPDATE vc_study_stats
                SET daily_seconds = ?, weekly_seconds = ?, monthly_seconds = ?,
                    daily_cam_only_seconds = ?, weekly_cam_only_seconds = ?, monthly_cam_only_seconds = ?,
                    daily_ss_only_seconds = ?, weekly_ss_only_seconds = ?, monthly_ss_only_seconds = ?,
                    daily_both_seconds = ?, weekly_both_seconds = ?, monthly_both_seconds = ?,
                    daily_plain_seconds = ?, weekly_plain_seconds = ?, monthly_plain_seconds = ?,
                    last_day_key = ?, last_week_key = ?, last_month_key = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    pick("daily_seconds", same_day), pick("weekly_seconds", same_week), pick("monthly_seconds", same_month),
                    pick("daily_cam_only_seconds", same_day), pick("weekly_cam_only_seconds", same_week), pick("monthly_cam_only_seconds", same_month),
                    pick("daily_ss_only_seconds", same_day), pick("weekly_ss_only_seconds", same_week), pick("monthly_ss_only_seconds", same_month),
                    pick("daily_both_seconds", same_day), pick("weekly_both_seconds", same_week), pick("monthly_both_seconds", same_month),
                    pick("daily_plain_seconds", same_day), pick("weekly_plain_seconds", same_week), pick("monthly_plain_seconds", same_month),
                    day_key, week_key, month_key, guild_id, user_id,
                ),
            )
            conn.commit()
            cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            return cursor.fetchone()
        return row

    def record_interval_log(self, guild_id: int, user_id: int, channel_id: int, bucket: str, start_ts: float, end_ts: float):
        secs = int(end_ts - start_ts)
        if secs <= 0:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO vc_interval_logs (guild_id, user_id, channel_id, bucket, start_utc, end_utc, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, channel_id, bucket, start_ts, end_ts, secs),
            )
            conn.commit()

    def query_challenge_window(
        self,
        guild_id: int,
        start_ts: float,
        end_ts: float,
        untracked_channels: set[int],
        target_user_id: Optional[int] = None,
        excluded_users: Optional[set[int]] = None,
    ) -> list[dict]:
        if end_ts <= start_ts:
            return []
        excluded_users = excluded_users or set()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            if target_user_id is not None:
                cursor.execute(
                    """
                    SELECT user_id, channel_id, bucket, start_utc, end_utc
                    FROM vc_interval_logs
                    WHERE guild_id = ? AND user_id = ? AND end_utc > ? AND start_utc < ?
                    """,
                    (guild_id, target_user_id, start_ts, end_ts),
                )
            else:
                cursor.execute(
                    """
                    SELECT user_id, channel_id, bucket, start_utc, end_utc
                    FROM vc_interval_logs
                    WHERE guild_id = ? AND end_utc > ? AND start_utc < ?
                    """,
                    (guild_id, start_ts, end_ts),
                )
            rows = cursor.fetchall()

        per_user: dict[int, dict[str, int]] = {}
        for r in rows:
            cid = r["channel_id"]
            if cid in untracked_channels:
                continue
            uid = r["user_id"]
            if target_user_id is None and uid in excluded_users:
                continue

            overlap_start = max(start_ts, float(r["start_utc"]))
            overlap_end = min(end_ts, float(r["end_utc"]))
            overlap_secs = max(0, int(overlap_end - overlap_start))
            if overlap_secs <= 0:
                continue

            b = r["bucket"]
            if b not in ("cam_only", "ss_only", "both", "plain"):
                b = "plain"

            if uid not in per_user:
                per_user[uid] = {"cam_only": 0, "ss_only": 0, "both": 0, "plain": 0}
            per_user[uid][b] += overlap_secs

        results = []
        for uid, b_map in per_user.items():
            cam_only = b_map["cam_only"]
            ss_only = b_map["ss_only"]
            both = b_map["both"]
            plain = b_map["plain"]
            total_vc = cam_only + ss_only + both + plain
            any_cam_ss = cam_only + ss_only + both
            results.append(
                {
                    "user_id": uid,
                    "cam_only": cam_only,
                    "ss_only": ss_only,
                    "both": both,
                    "plain": plain,
                    "any_cam_ss": any_cam_ss,
                    "total_vc": total_vc,
                }
            )

        results.sort(key=lambda item: item["total_vc"], reverse=True)
        return results

    def add_exclusive_vc_buckets(
        self,
        guild_id: int,
        user_id: int,
        cam_only_seconds: int = 0,
        ss_only_seconds: int = 0,
        both_seconds: int = 0,
        plain_seconds: int = 0,
    ):
        cam_only_seconds = max(0, int(cam_only_seconds))
        ss_only_seconds = max(0, int(ss_only_seconds))
        both_seconds = max(0, int(both_seconds))
        plain_seconds = max(0, int(plain_seconds))
        total_vc = cam_only_seconds + ss_only_seconds + both_seconds + plain_seconds
        if total_vc <= 0:
            return

        with self._get_connection() as conn:
            self._sync_period_resets(conn, guild_id, user_id)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE vc_study_stats
                SET daily_seconds = daily_seconds + ?, weekly_seconds = weekly_seconds + ?, monthly_seconds = monthly_seconds + ?, all_time_seconds = all_time_seconds + ?,
                    daily_cam_only_seconds = daily_cam_only_seconds + ?, weekly_cam_only_seconds = weekly_cam_only_seconds + ?, monthly_cam_only_seconds = monthly_cam_only_seconds + ?, all_time_cam_only_seconds = all_time_cam_only_seconds + ?,
                    daily_ss_only_seconds = daily_ss_only_seconds + ?, weekly_ss_only_seconds = weekly_ss_only_seconds + ?, monthly_ss_only_seconds = monthly_ss_only_seconds + ?, all_time_ss_only_seconds = all_time_ss_only_seconds + ?,
                    daily_both_seconds = daily_both_seconds + ?, weekly_both_seconds = weekly_both_seconds + ?, monthly_both_seconds = monthly_both_seconds + ?, all_time_both_seconds = all_time_both_seconds + ?,
                    daily_plain_seconds = daily_plain_seconds + ?, weekly_plain_seconds = weekly_plain_seconds + ?, monthly_plain_seconds = monthly_plain_seconds + ?, all_time_plain_seconds = all_time_plain_seconds + ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    total_vc, total_vc, total_vc, total_vc,
                    cam_only_seconds, cam_only_seconds, cam_only_seconds, cam_only_seconds,
                    ss_only_seconds, ss_only_seconds, ss_only_seconds, ss_only_seconds,
                    both_seconds, both_seconds, both_seconds, both_seconds,
                    plain_seconds, plain_seconds, plain_seconds, plain_seconds,
                    guild_id, user_id,
                ),
            )
            conn.commit()

    def adjust_vc_bucket_seconds(self, guild_id: int, user_id: int, bucket: str, action: str, seconds: int):
        bucket_map = {
            "vc": ("daily_seconds", "weekly_seconds", "monthly_seconds", "all_time_seconds"),
            "plain": ("daily_plain_seconds", "weekly_plain_seconds", "monthly_plain_seconds", "all_time_plain_seconds"),
            "cam_only": ("daily_cam_only_seconds", "weekly_cam_only_seconds", "monthly_cam_only_seconds", "all_time_cam_only_seconds"),
            "ss_only": ("daily_ss_only_seconds", "weekly_ss_only_seconds", "monthly_ss_only_seconds", "all_time_ss_only_seconds"),
            "both": ("daily_both_seconds", "weekly_both_seconds", "monthly_both_seconds", "all_time_both_seconds"),
        }
        cols = bucket_map.get(bucket, bucket_map["vc"])

        with self._get_connection() as conn:
            row = self._sync_period_resets(conn, guild_id, user_id)
            new_vals = []
            for col in cols:
                cur = row[col] or 0
                if action == "add":
                    new_vals.append(cur + seconds)
                elif action == "remove":
                    new_vals.append(max(0, cur - seconds))
                else:
                    new_vals.append(max(0, seconds))

            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE vc_study_stats SET {cols[0]} = ?, {cols[1]} = ?, {cols[2]} = ?, {cols[3]} = ? WHERE guild_id = ? AND user_id = ?",
                (*new_vals, guild_id, user_id),
            )

            if bucket in ("plain", "cam_only", "ss_only", "both"):
                cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
                updated = cursor.fetchone()
                for p in ("daily", "weekly", "monthly", "all_time"):
                    recomputed_total = (
                        (updated[f"{p}_cam_only_seconds"] or 0)
                        + (updated[f"{p}_ss_only_seconds"] or 0)
                        + (updated[f"{p}_both_seconds"] or 0)
                        + (updated[f"{p}_plain_seconds"] or 0)
                    )
                    tot_col = "all_time_seconds" if p == "all_time" else f"{p}_seconds"
                    cursor.execute(f"UPDATE vc_study_stats SET {tot_col} = ? WHERE guild_id = ? AND user_id = ?", (recomputed_total, guild_id, user_id))

            conn.commit()

    @staticmethod
    def enrich_row_with_derived_metrics(row_dict: dict) -> dict:
        out = dict(row_dict)
        for prefix, total_key in [("daily", "daily_seconds"), ("weekly", "weekly_seconds"), ("monthly", "monthly_seconds"), ("all_time", "all_time_seconds")]:
            cam_only = out.get(f"{prefix}_cam_only_seconds", 0) or 0
            ss_only = out.get(f"{prefix}_ss_only_seconds", 0) or 0
            both = out.get(f"{prefix}_both_seconds", 0) or 0
            plain = out.get(f"{prefix}_plain_seconds", 0) or 0
            raw_total = out.get(total_key, 0) or 0

            bucket_sum = cam_only + ss_only + both + plain
            total_vc = bucket_sum if bucket_sum > 0 else raw_total
            if bucket_sum == 0 and raw_total > 0 and plain == 0:
                plain = raw_total
                bucket_sum = plain

            out[f"{prefix}_cam_only_seconds"] = cam_only
            out[f"{prefix}_ss_only_seconds"] = ss_only
            out[f"{prefix}_both_seconds"] = both
            out[f"{prefix}_plain_seconds"] = plain
            out[total_key] = total_vc
            out[f"{prefix}_any_cam_ss_seconds"] = cam_only + ss_only + both
            out[f"{prefix}_total_cam_seconds"] = cam_only + both
            out[f"{prefix}_total_ss_seconds"] = ss_only + both
        return out

    def get_user_vc_stats(self, guild_id: int, user_id: int) -> dict:
        with self._get_connection() as conn:
            row = self._sync_period_resets(conn, guild_id, user_id)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) + 1 AS rank FROM vc_study_stats WHERE guild_id = ? AND all_time_seconds > ?", (guild_id, row["all_time_seconds"]))
            rank_row = cursor.fetchone()
            data = self.enrich_row_with_derived_metrics(dict(row))
            data["rank"] = rank_row["rank"] if rank_row else 1
            return data

    def get_vc_leaderboard_all_rows(self, guild_id: int, excluded_users: Optional[set[int]] = None) -> list[dict]:
        excluded_users = excluded_users or set()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ?", (guild_id,))
            rows = []
            for r in cursor.fetchall():
                if r["user_id"] in excluded_users:
                    continue
                rows.append(self.enrich_row_with_derived_metrics(dict(r)))
            return rows

    def get_untracked_channels(self, guild_id: int) -> set[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel_id FROM vc_untracked_channels WHERE guild_id = ?", (guild_id,))
            return {row["channel_id"] for row in cursor.fetchall()}

    def set_untracked_channels(self, guild_id: int, channel_ids: list[int]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vc_untracked_channels WHERE guild_id = ?", (guild_id,))
            for cid in set(channel_ids):
                cursor.execute("INSERT INTO vc_untracked_channels (guild_id, channel_id) VALUES (?, ?)", (guild_id, cid))
            conn.commit()

    def get_excluded_leaderboard_users(self, guild_id: int) -> set[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM vc_excluded_users WHERE guild_id = ?", (guild_id,))
            return {row["user_id"] for row in cursor.fetchall()}

    def add_excluded_leaderboard_user(self, guild_id: int, user_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO vc_excluded_users (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
            conn.commit()

    def remove_excluded_leaderboard_user(self, guild_id: int, user_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vc_excluded_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_tempvoice_config(self, guild_id: int) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO tempvoice_settings (guild_id) VALUES (?)", (guild_id,))
                conn.commit()
                cursor.execute("SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,))
                row = cursor.fetchone()
            return dict(row)

    def update_tempvoice_config(self, guild_id: int, **kwargs):
        self.get_tempvoice_config(guild_id)
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE tempvoice_settings SET {columns} WHERE guild_id = ?", values)
            conn.commit()

    def register_temp_channel(self, channel_id: int, guild_id: int, owner_id: int, privacy_mode: str = "open", chat_enabled: int = 1):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO tempvoice_channels (channel_id, guild_id, owner_id, privacy_mode, chat_enabled) VALUES (?, ?, ?, ?, ?)",
                (channel_id, guild_id, owner_id, privacy_mode, chat_enabled),
            )
            conn.commit()

    def update_temp_channel(self, channel_id: int, **kwargs):
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [channel_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE tempvoice_channels SET {columns} WHERE channel_id = ?", values)
            conn.commit()

    def get_temp_channel(self, channel_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tempvoice_channels WHERE channel_id = ?", (channel_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_temp_channel(self, channel_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tempvoice_channels WHERE channel_id = ?", (channel_id,))
            conn.commit()

    def get_all_temp_channels(self, guild_id: Optional[int] = None) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if guild_id is not None:
                cursor.execute("SELECT * FROM tempvoice_channels WHERE guild_id = ?", (guild_id,))
            else:
                cursor.execute("SELECT * FROM tempvoice_channels")
            return [dict(r) for r in cursor.fetchall()]

    def get_autoroles(self, guild_id: int) -> list[int]:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO server_autoroles (guild_id, role_ids) VALUES (?, ?)", (guild_id, json.dumps(list(set(role_ids)))))
            conn.commit()

    def get_challenge_vc(self, channel_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM challenge_vcs WHERE channel_id = ?", (channel_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_challenge_vc(self, channel_id: int, guild_id: int, challenge_type: str, grace_seconds: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO challenge_vcs (channel_id, guild_id, challenge_type, grace_seconds) VALUES (?, ?, ?, ?)", (channel_id, guild_id, challenge_type, grace_seconds))
            conn.commit()

    def add_user_task(self, user_id: int, title: str, due_date: Optional[str]) -> int:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO user_tasks (user_id, title, due_date, completed, created_at) VALUES (?, ?, ?, 0, ?)", (user_id, title, due_date or "No deadline", timestamp))
            conn.commit()
            return cursor.lastrowid

    def get_user_tasks(self, user_id: int) -> list[sqlite3.Row]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_tasks WHERE user_id = ? ORDER BY id DESC", (user_id,))
            return cursor.fetchall()

    def clear_completed_tasks(self, user_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_tasks WHERE user_id = ? AND completed = 1", (user_id,))
            conn.commit()
            return cursor.rowcount

    def set_afk(self, guild_id: int, user_id: int, reason: str):
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO user_afk (guild_id, user_id, reason, timestamp) VALUES (?, ?, ?, ?)", (guild_id, user_id, reason, timestamp))
            conn.commit()

    def get_afk(self, guild_id: int, user_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = cursor.fetchone()
            return dict(row) if row else None

    def remove_afk(self, guild_id: int, user_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            conn.commit()

    def get_streak_threshold_seconds(self, guild_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT min_daily_seconds FROM streak_config WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            return row["min_daily_seconds"] if row else 1800

    def set_streak_threshold_seconds(self, guild_id: int, seconds: int):
        seconds = max(60, int(seconds))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO streak_config (guild_id, min_daily_seconds) VALUES (?, ?)", (guild_id, seconds))
            conn.commit()

    def get_user_streak_record(self, guild_id: int, user_id: int) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_streaks WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    "INSERT INTO user_streaks (guild_id, user_id, current_streak, best_streak, last_qualified_day, last_evaluated_day) VALUES (?, ?, 0, 0, NULL, NULL)",
                    (guild_id, user_id),
                )
                conn.commit()
                cursor.execute("SELECT * FROM user_streaks WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
                row = cursor.fetchone()
            return dict(row)

    def update_user_streak_record(self, guild_id: int, user_id: int, **kwargs):
        self.get_user_streak_record(guild_id, user_id)
        if not kwargs:
            return
        columns = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [guild_id, user_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE user_streaks SET {columns} WHERE guild_id = ? AND user_id = ?", values)
            conn.commit()

    def get_audit_log_channel_id(self, guild_id: int) -> Optional[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel_id FROM audit_log_settings WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            return row["channel_id"] if row else None

    def set_audit_log_channel_id(self, guild_id: int, channel_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO audit_log_settings (guild_id, channel_id) VALUES (?, ?)", (guild_id, channel_id))
            conn.commit()


db = DatabaseManager()


def format_duration_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hrs, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs}h {mins}m"
    return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"


def parse_ist_datetime(date_str: str) -> Optional[datetime.datetime]:
    """
    Parses IST date/time inputs flexibly:
    - 'YYYY-MM-DD HH:MM'
    - 'YYYY-MM-DDTHH:MM'
    - 'YYYY-MM-DD HH:MM:SS'
    - 'YYYY-MM-DD' (assumes 00:00 IST)
    """
    raw = date_str.strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            naive_dt = datetime.datetime.strptime(raw, fmt)
            return naive_dt.replace(tzinfo=IST_TZ)
        except ValueError:
            continue
    return None


# ==============================================================================
# SECTION 3: ACTIVITY PRESENCE & /set-status COG (cogs/status.py)
# ==============================================================================

DEFAULT_ROTATING_ACTIVITIES = [
    "🌛 The Study Hall",
    "🌛 The Quiet Desk",
    "🌛 The Lock-In Room",
    "🌛 Late Night Focus",
]


def parse_activity_type(raw_type: str) -> Optional[discord.ActivityType]:
    val = (raw_type or "").strip().lower()
    mapping = {
        "watching": discord.ActivityType.watching,
        "watch": discord.ActivityType.watching,
        "playing": discord.ActivityType.playing,
        "play": discord.ActivityType.playing,
        "listening": discord.ActivityType.listening,
        "listen": discord.ActivityType.listening,
        "competing": discord.ActivityType.competing,
        "compete": discord.ActivityType.competing,
    }
    return mapping.get(val)


def parse_online_status(raw_status: str) -> Optional[discord.Status]:
    val = (raw_status or "").strip().lower()
    mapping = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "do_not_disturb": discord.Status.dnd,
    }
    return mapping.get(val)


class SetStatusModal(discord.ui.Modal, title="Configure Bot Activity & Status"):
    activity_type_input = discord.ui.TextInput(
        label="Activity Type (watching/playing/listening/competing)",
        style=discord.TextStyle.short,
        placeholder="watching",
        required=True,
        max_length=20,
    )
    activity_name_input = discord.ui.TextInput(
        label="Activity Name",
        style=discord.TextStyle.short,
        placeholder="🌛 The Library Hall",
        required=True,
        max_length=128,
    )
    online_status_input = discord.ui.TextInput(
        label="Online Status (online / idle / dnd)",
        style=discord.TextStyle.short,
        placeholder="online",
        required=True,
        max_length=20,
    )

    def __init__(self, status_cog: "StatusCog", current_cfg: dict):
        super().__init__()
        self.status_cog = status_cog
        self.activity_type_input.default = current_cfg.get("activity_type", "watching")
        self.activity_name_input.default = current_cfg.get("activity_name", "🌛 The Study Hall")
        self.online_status_input.default = current_cfg.get("online_status", "online")

    async def on_submit(self, interaction: discord.Interaction):
        act_type = parse_activity_type(self.activity_type_input.value)
        if not act_type:
            return await interaction.response.send_message(
                "❌ Invalid Activity Type! Use `watching`, `playing`, `listening`, or `competing`.",
                ephemeral=True,
            )

        status_obj = parse_online_status(self.online_status_input.value)
        if not status_obj:
            return await interaction.response.send_message(
                "❌ Invalid Online Status! Use `online`, `idle`, or `dnd`.",
                ephemeral=True,
            )

        clean_name = self.activity_name_input.value.strip()
        if not clean_name:
            return await interaction.response.send_message("❌ Activity Name cannot be empty.", ephemeral=True)

        normalized_type = act_type.name.lower()
        normalized_status = status_obj.name.lower()

        db.set_presence_config(
            custom_override=1,
            activity_type=normalized_type,
            activity_name=clean_name,
            online_status=normalized_status,
        )
        await self.status_cog.apply_presence(act_type, clean_name, status_obj)

        embed = discord.Embed(
            title="✨ Bot Presence Updated & Saved",
            description=(
                f"**Activity:** `{normalized_type.title()}` **{clean_name}**\n"
                f"**Status:** `{normalized_status.upper()}`\n"
                f"*Saved to SQLite — will automatically reapply after restarts.*"
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class StatusCog(commands.Cog):
    """Manages Discord bot presence, rotating atmospheric focus activities, and /set-status."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._rotate_index = 0
        self.rotate_presence_task.start()

    def cog_unload(self):
        self.rotate_presence_task.cancel()

    async def apply_presence(self, activity_type: discord.ActivityType, activity_name: str, status: discord.Status):
        activity = discord.Activity(type=activity_type, name=activity_name)
        await self.bot.change_presence(status=status, activity=activity)

    async def apply_saved_or_default_presence(self):
        cfg = db.get_presence_config()
        act_type = parse_activity_type(cfg.get("activity_type", "watching")) or discord.ActivityType.watching
        status_obj = parse_online_status(cfg.get("online_status", "online")) or discord.Status.online
        name = cfg.get("activity_name") or DEFAULT_ROTATING_ACTIVITIES[0]
        await self.apply_presence(act_type, name, status_obj)

    @tasks.loop(minutes=7)
    async def rotate_presence_task(self):
        cfg = db.get_presence_config()
        if cfg.get("custom_override", 0) == 1:
            return
        name = DEFAULT_ROTATING_ACTIVITIES[self._rotate_index % len(DEFAULT_ROTATING_ACTIVITIES)]
        self._rotate_index += 1
        status_obj = parse_online_status(cfg.get("online_status", "online")) or discord.Status.online
        await self.apply_presence(discord.ActivityType.watching, name, status_obj)

    @rotate_presence_task.before_loop
    async def before_rotate_presence(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="set-status", description="Opens a modal to customize the bot's activity and online status.")
    async def set_status_cmd(self, interaction: discord.Interaction):
        is_owner = await self.bot.is_owner(interaction.user)
        has_perm = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        if not (is_owner or has_perm):
            return await interaction.response.send_message(
                "❌ You need **Manage Guild** permission or bot owner access to use `/set-status`.",
                ephemeral=True,
            )
        current_cfg = db.get_presence_config()
        await interaction.response.send_modal(SetStatusModal(self, current_cfg))


# ==============================================================================
# SECTION 4: CENTRALIZED AUDIT LOGS COG (cogs/auditlogs.py)
# ==============================================================================

class AuditLogsCog(commands.Cog):
    """Centralized Mod & Challenge Audit Log system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_audit_embed(self, guild: Optional[discord.Guild], embed: discord.Embed):
        if not guild:
            return
        try:
            channel_id = db.get_audit_log_channel_id(guild.id)
            if not channel_id:
                return
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                return
            await channel.send(embed=embed)
        except Exception:
            pass

    async def log_moderation_action(
        self,
        guild: discord.Guild,
        action_type: str,
        moderator: discord.abc.User,
        target_label: str,
        reason: str,
        duration: Optional[str] = None,
        extra_info: Optional[str] = None,
    ):
        color_map = {
            "WARN": discord.Color.orange(),
            "MUTE": discord.Color.red(),
            "BAN": discord.Color.dark_red(),
            "PURGE": discord.Color.blurple(),
        }
        embed = discord.Embed(
            title=f"🛡️ Audit Log • {action_type}",
            color=color_map.get(action_type, discord.Color.blurple()),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
        embed.add_field(name="Target / Scope", value=target_label, inline=True)
        if duration:
            embed.add_field(name="Duration / Details", value=duration, inline=True)
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        if extra_info:
            embed.add_field(name="Additional Info", value=extra_info, inline=False)
        await self.send_audit_embed(guild, embed)

    async def log_tracker_adjustment(
        self,
        guild: discord.Guild,
        admin: discord.abc.User,
        target_user_id: int,
        bucket: str,
        action: str,
        hours: float,
    ):
        embed = discord.Embed(
            title="⏱️ Audit Log • Manual Tracker Adjustment",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Admin", value=f"{admin.mention} (`{admin.id}`)", inline=True)
        embed.add_field(name="Target User", value=f"<@{target_user_id}> (`{target_user_id}`)", inline=True)
        embed.add_field(name="Bucket & Action", value=f"`{bucket}` • `{action.upper()}` (`{hours}h`)", inline=True)
        await self.send_audit_embed(guild, embed)

    async def log_challenge_disconnect(
        self,
        guild: discord.Guild,
        member: discord.Member,
        channel: discord.VoiceChannel,
        challenge_type: str,
        reason: str,
    ):
        embed = discord.Embed(
            title="🚨 Audit Log • Challenge VC Disconnect",
            color=discord.Color.from_str("#ff5555"),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Challenge VC", value=f"{channel.mention} (`{challenge_type.upper()}`)", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await self.send_audit_embed(guild, embed)

    @app_commands.command(name="auditlog-setup", description="Sets the centralized moderation & challenge audit log channel.")
    @app_commands.describe(channel="Text channel where audit embeds will be sent")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def auditlog_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.set_audit_log_channel_id(interaction.guild.id, channel.id)
        embed = discord.Embed(
            title="📜 Centralized Audit Log Configured",
            description=f"All moderation, manual tracker edits, and challenge VC disconnect events will be logged in {channel.mention}.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==============================================================================
# SECTION 5: MODERATION COG (cogs/moderation.py)
# ==============================================================================

class WarnModal(discord.ui.Modal, title="Issue Warning"):
    reason = discord.ui.TextInput(label="Reason for Warning", style=discord.TextStyle.paragraph, placeholder="e.g., Spamming", required=True, max_length=500)
    internal_note = discord.ui.TextInput(label="Internal Mod Note (Optional)", style=discord.TextStyle.short, placeholder="Note...", required=False, max_length=200)

    def __init__(self, member: discord.Member):
        super().__init__()
        self.target_member = member

    async def on_submit(self, interaction: discord.Interaction):
        case_id = db.add_mod_log(interaction.guild.id, self.target_member.id, interaction.user.id, "WARN", self.reason.value, self.internal_note.value)
        try:
            dm_embed = discord.Embed(title=f"⚠️ Warning in {interaction.guild.name}", description=f"**Reason:** {self.reason.value}", color=discord.Color.orange())
            await self.target_member.send(embed=dm_embed)
        except Exception:
            pass
        embed = discord.Embed(title=f"⚠️ Member Warned [Case #{case_id}]", description=f"**User:** {self.target_member.mention}\n**Reason:** {self.reason.value}", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)

        audit_cog: Optional[AuditLogsCog] = interaction.client.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_moderation_action(
                interaction.guild, "WARN", interaction.user, f"{self.target_member.mention} (`{self.target_member.id}`)",
                self.reason.value, extra_info=f"Case #{case_id} | Note: {self.internal_note.value or 'None'}"
            )


class MuteModal(discord.ui.Modal, title="Apply Timeout (Mute)"):
    duration_str = discord.ui.TextInput(label="Duration (e.g., 10m, 1h, 1d)", style=discord.TextStyle.short, placeholder="10m", required=True, max_length=20)
    reason = discord.ui.TextInput(label="Reason for Mute", style=discord.TextStyle.paragraph, placeholder="Reason...", required=True, max_length=500)

    def __init__(self, member: discord.Member):
        super().__init__()
        self.target_member = member

    @staticmethod
    def parse_duration(duration_str: str) -> Optional[datetime.timedelta]:
        match = re.match(r"^(\d+)([smhd])$", duration_str.strip().lower())
        if not match:
            return None
        val, unit = int(match.group(1)), match.group(2)
        if unit == "s":
            return datetime.timedelta(seconds=val)
        elif unit == "m":
            return datetime.timedelta(minutes=val)
        elif unit == "h":
            return datetime.timedelta(hours=val)
        elif unit == "d":
            return datetime.timedelta(days=val)
        return None

    async def on_submit(self, interaction: discord.Interaction):
        delta = self.parse_duration(self.duration_str.value)
        if not delta:
            await interaction.response.send_message("❌ Invalid duration format! Use `10m`, `2h`, `1d`.", ephemeral=True)
            return
        until = datetime.datetime.now(datetime.timezone.utc) + delta
        case_id = db.add_mod_log(interaction.guild.id, self.target_member.id, interaction.user.id, "MUTE", self.reason.value, duration=self.duration_str.value)
        try:
            await self.target_member.timeout(until, reason=self.reason.value)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to timeout this member.", ephemeral=True)
            return
        embed = discord.Embed(title=f"🔇 Member Muted [Case #{case_id}]", description=f"**User:** {self.target_member.mention}\n**Duration:** {self.duration_str.value}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

        audit_cog: Optional[AuditLogsCog] = interaction.client.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_moderation_action(
                interaction.guild, "MUTE", interaction.user, f"{self.target_member.mention} (`{self.target_member.id}`)",
                self.reason.value, duration=self.duration_str.value, extra_info=f"Case #{case_id}"
            )


class BanModal(discord.ui.Modal, title="Ban Member"):
    reason = discord.ui.TextInput(label="Reason for Ban", style=discord.TextStyle.paragraph, placeholder="Reason...", required=True, max_length=500)
    delete_days = discord.ui.TextInput(label="Delete Messages (0-7 days)", style=discord.TextStyle.short, placeholder="1", required=True, max_length=1)

    def __init__(self, member: discord.Member):
        super().__init__()
        self.target_member = member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            del_days = max(0, min(7, int(self.delete_days.value.strip())))
        except ValueError:
            del_days = 0
        case_id = db.add_mod_log(interaction.guild.id, self.target_member.id, interaction.user.id, "BAN", self.reason.value)
        try:
            await interaction.guild.ban(self.target_member, reason=self.reason.value, delete_message_days=del_days)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to ban this member.", ephemeral=True)
            return
        embed = discord.Embed(title=f"🔨 Member Banned [Case #{case_id}]", description=f"**User:** {self.target_member.mention}", color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed)

        audit_cog: Optional[AuditLogsCog] = interaction.client.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_moderation_action(
                interaction.guild, "BAN", interaction.user, f"{self.target_member.mention} (`{self.target_member.id}`)",
                self.reason.value, duration=f"Msg Delete: {del_days}d", extra_info=f"Case #{case_id}"
            )


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Warns a member.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn_cmd(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(WarnModal(member))

    @app_commands.command(name="mute", description="Timeouts a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute_cmd(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(MuteModal(member))

    @app_commands.command(name="ban", description="Bans a member.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_cmd(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(BanModal(member))

    @app_commands.command(name="modlogs", description="Displays mod history for a member.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def modlogs_cmd(self, interaction: discord.Interaction, member: discord.Member):
        logs = db.get_user_logs(interaction.guild.id, member.id)
        if not logs:
            await interaction.response.send_message(f"✨ No records for {member.mention}.", ephemeral=True)
            return
        embed = discord.Embed(title=f"🛡️ Mod History for {member}", color=discord.Color.blurple())
        for log in logs[:10]:
            embed.add_field(name=f"[{log['action_type']}] Case #{log['id']}", value=f"**Reason:** {log['reason']}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==============================================================================
# SECTION 6: WELCOME SYSTEM COG (cogs/welcome.py)
# ==============================================================================

class WelcomeTextModal(discord.ui.Modal, title="Edit Welcome Content"):
    outside_content = discord.ui.TextInput(label="Outside Content", style=discord.TextStyle.short, required=False)
    embed_title = discord.ui.TextInput(label="Embed Title", style=discord.TextStyle.short, required=True)
    embed_description = discord.ui.TextInput(label="Embed Description", style=discord.TextStyle.paragraph, required=True)
    footer_text = discord.ui.TextInput(label="Footer Text", style=discord.TextStyle.short, required=False)

    def __init__(self, guild_id: int, current_data: dict):
        super().__init__()
        self.guild_id = guild_id
        self.outside_content.default = current_data.get("outside_content", "")
        self.embed_title.default = current_data.get("embed_title", "")
        self.embed_description.default = current_data.get("embed_description", "")
        self.footer_text.default = current_data.get("footer_text", "")

    async def on_submit(self, interaction: discord.Interaction):
        db.update_welcome_config(self.guild_id, outside_content=self.outside_content.value, embed_title=self.embed_title.value, embed_description=self.embed_description.value, footer_text=self.footer_text.value)
        await interaction.response.send_message("🌸 Welcome text updated!", ephemeral=True)


class WelcomeVisualsModal(discord.ui.Modal, title="Edit Welcome Visuals"):
    embed_color = discord.ui.TextInput(label="Hex Color", style=discord.TextStyle.short, required=True, max_length=7)
    thumbnail_url = discord.ui.TextInput(label="Thumbnail URL", style=discord.TextStyle.short, required=False)
    banner_url = discord.ui.TextInput(label="Banner URL", style=discord.TextStyle.short, required=False)
    footer_icon_url = discord.ui.TextInput(label="Footer Icon URL", style=discord.TextStyle.short, required=False)
    show_author = discord.ui.TextInput(label="Show Author (1/0)", style=discord.TextStyle.short, required=True, max_length=1)

    def __init__(self, guild_id: int, current_data: dict):
        super().__init__()
        self.guild_id = guild_id
        self.embed_color.default = current_data.get("embed_color", "#f4c2c2")
        self.thumbnail_url.default = current_data.get("thumbnail_url", "{avatar}")
        self.banner_url.default = current_data.get("banner_url", "")
        self.footer_icon_url.default = current_data.get("footer_icon_url", "")
        self.show_author.default = str(current_data.get("show_author", 1))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            show_auth = 1 if int(self.show_author.value.strip()) > 0 else 0
        except ValueError:
            show_auth = 1
        db.update_welcome_config(self.guild_id, embed_color=self.embed_color.value.strip(), thumbnail_url=self.thumbnail_url.value.strip(), banner_url=self.banner_url.value.strip(), footer_icon_url=self.footer_icon_url.value.strip(), show_author=show_auth)
        await interaction.response.send_message("🌸 Welcome visuals updated!", ephemeral=True)


class WelcomeDashboardView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Edit Content", style=discord.ButtonStyle.primary, emoji="✍️")
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = db.get_welcome_config(self.guild_id)
        await interaction.response.send_modal(WelcomeTextModal(self.guild_id, config))

    @discord.ui.button(label="Edit Visuals", style=discord.ButtonStyle.secondary, emoji="🎨")
    async def edit_visuals(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = db.get_welcome_config(self.guild_id)
        await interaction.response.send_modal(WelcomeVisualsModal(self.guild_id, config))

    @discord.ui.button(label="Test Welcome", style=discord.ButtonStyle.success, emoji="🧪")
    async def test_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("WelcomeCog")
        if cog:
            await cog.trigger_welcome(interaction.member, interaction.channel, test_mode=True)
            await interaction.response.send_message("✨ Test welcome sent!", ephemeral=True)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="welcome-setup", description="Configures Mimu-style welcome system.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.update_welcome_config(interaction.guild.id, channel_id=channel.id)
        embed = discord.Embed(title="🌸 Welcome Dashboard", description=f"Welcome messages configured in {channel.mention}!", color=discord.Color.from_str("#f4c2c2"))
        await interaction.response.send_message(embed=embed, view=WelcomeDashboardView(interaction.guild.id), ephemeral=True)

    def format_template(self, template: str, member: discord.Member) -> str:
        if not template:
            return ""
        return template.replace("{user}", member.mention).replace("{username}", member.name).replace("{server}", member.guild.name).replace("{member_count}", str(member.guild.member_count)).replace("{avatar}", member.display_avatar.url)

    async def trigger_welcome(self, member: discord.Member, channel: discord.TextChannel, test_mode: bool = False):
        config = db.get_welcome_config(member.guild.id)
        if not config or (not config["channel_id"] and not test_mode):
            return
        target_channel = channel if test_mode else member.guild.get_channel(config["channel_id"])
        if not target_channel:
            return

        outside_txt = self.format_template(config["outside_content"], member)
        title = self.format_template(config["embed_title"], member)
        desc = self.format_template(config["embed_description"], member)
        footer = self.format_template(config["footer_text"], member)
        thumb = self.format_template(config["thumbnail_url"], member)
        banner = self.format_template(config["banner_url"], member)
        footer_icon = self.format_template(config["footer_icon_url"], member)

        try:
            color = discord.Color.from_str(config["embed_color"])
        except Exception:
            color = discord.Color.from_str("#f4c2c2")

        embed = discord.Embed(title=title, description=desc, color=color)
        if thumb:
            embed.set_thumbnail(url=thumb)
        if banner:
            embed.set_image(url=banner)
        if footer:
            embed.set_footer(text=footer, icon_url=footer_icon if footer_icon else None)
        if config["show_author"] == 1:
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)

        await target_channel.send(content=outside_txt if outside_txt else None, embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = db.get_welcome_config(member.guild.id)
        if config and config["channel_id"]:
            ch = member.guild.get_channel(config["channel_id"])
            if ch:
                await self.trigger_welcome(member, ch, test_mode=False)


# ==============================================================================
# SECTION 7: DAILY STUDY STREAKS IN IST COG (cogs/streaks.py)
# ==============================================================================

class StreaksCog(commands.Cog):
    """Tracks consecutive daily study streaks in IST (UTC+5:30) with 00:00 IST rollover evaluation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_streak_rollover.start()

    def cog_unload(self):
        self.daily_streak_rollover.cancel()

    @staticmethod
    def _previous_ist_day_key(day_key: str) -> str:
        dt = datetime.datetime.strptime(day_key, "%Y-%m-%d")
        return (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    def evaluate_user_streak(self, guild_id: int, user_id: int, now_ist: Optional[datetime.datetime] = None) -> dict:
        if now_ist is None:
            now_ist = db.get_ist_now()
        today_key, _, _ = db.get_ist_period_keys(now_ist)
        yesterday_key = self._previous_ist_day_key(today_key)

        threshold = db.get_streak_threshold_seconds(guild_id)
        vc_stats = db.get_user_vc_stats(guild_id, user_id)
        today_seconds = vc_stats.get("daily_seconds", 0) or 0

        rec = db.get_user_streak_record(guild_id, user_id)
        current_streak = rec["current_streak"] or 0
        best_streak = rec["best_streak"] or 0
        last_qualified = rec["last_qualified_day"]
        last_eval = rec["last_evaluated_day"]

        if last_qualified and last_qualified not in (today_key, yesterday_key):
            current_streak = 0
        elif not last_qualified and last_eval and last_eval != today_key:
            current_streak = 0

        if today_seconds >= threshold:
            if last_qualified != today_key:
                if last_qualified == yesterday_key:
                    current_streak += 1
                else:
                    current_streak = 1
                last_qualified = today_key
                if current_streak > best_streak:
                    best_streak = current_streak

        db.update_user_streak_record(
            guild_id,
            user_id,
            current_streak=current_streak,
            best_streak=best_streak,
            last_qualified_day=last_qualified,
            last_evaluated_day=today_key,
        )

        goal_met = today_seconds >= threshold
        pct = min(100, int((today_seconds / max(1, threshold)) * 100))
        filled = min(10, pct // 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)

        return {
            "current_streak": current_streak,
            "best_streak": best_streak,
            "today_seconds": today_seconds,
            "threshold_seconds": threshold,
            "goal_met": goal_met,
            "percent": pct,
            "progress_bar": bar,
            "today_key": today_key,
        }

    @tasks.loop(minutes=1)
    async def daily_streak_rollover(self):
        now_ist = db.get_ist_now()
        if not (now_ist.hour == 0 and now_ist.minute == 0):
            return

        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT guild_id, user_id FROM vc_study_stats")
            pairs = [(r["guild_id"], r["user_id"]) for r in cursor.fetchall()]

        for gid, uid in pairs:
            try:
                self.evaluate_user_streak(gid, uid, now_ist=now_ist)
            except Exception:
                pass

    @daily_streak_rollover.before_loop
    async def before_rollover(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="streak-config", description="Sets the minimum daily study time required to maintain an IST streak.")
    @app_commands.describe(minutes="Minimum daily minutes in tracked VCs (e.g., 30)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def streak_config_cmd(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 720]):
        db.set_streak_threshold_seconds(interaction.guild.id, minutes * 60)
        embed = discord.Embed(
            title="🔥 Daily Streak Goal Updated",
            description=f"Members must now study for at least **{minutes} minutes** (`{minutes}m`) per IST day (00:00 IST reset) to build/keep their daily streak.",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="streak", description="Displays a member's IST daily study streak and today's goal progress.")
    async def streak_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        info = self.evaluate_user_streak(interaction.guild.id, target.id)
        status_text = "✅ Goal Completed Today!" if info["goal_met"] else f"⏳ {format_duration_hms(max(0, info['threshold_seconds'] - info['today_seconds']))} remaining"

        embed = discord.Embed(
            title=f"🔥 Study Streak • {target.display_name}",
            description=f"**Today's Progress ({info['percent']}%):** {status_text}\n{info['progress_bar']}",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Current Streak", value=f"**{info['current_streak']}** day(s)", inline=True)
        embed.add_field(name="Best Streak", value=f"**{info['best_streak']}** day(s)", inline=True)
        embed.add_field(
            name="Today / Daily Goal (IST)",
            value=f"`{format_duration_hms(info['today_seconds'])}` / `{format_duration_hms(info['threshold_seconds'])}`",
            inline=True,
        )
        embed.set_footer(text="Resets daily at 00:00 IST (UTC+5:30)")
        await interaction.response.send_message(embed=embed)


# ==============================================================================
# SECTION 8: VC STUDY TRACKER COG — BUCKETS, CHALLENGE WINDOW & EXCLUSIONS
# ==============================================================================

class VcAdjustBucketModal(discord.ui.Modal, title="Adjust User VC Bucket Hours"):
    user_id_input = discord.ui.TextInput(label="Target User ID", style=discord.TextStyle.short, required=True)
    bucket_input = discord.ui.TextInput(
        label="Bucket: plain, cam_only, ss_only, both, vc",
        style=discord.TextStyle.short,
        placeholder="cam_only",
        required=True,
    )
    action_input = discord.ui.TextInput(label="Action: add, remove, set", style=discord.TextStyle.short, required=True)
    hours_input = discord.ui.TextInput(label="Hours (e.g., 1.5)", style=discord.TextStyle.short, required=True)

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
            bucket = self.bucket_input.value.strip().lower()
            action = self.action_input.value.strip().lower()
            hrs = float(self.hours_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid numerical input.", ephemeral=True)
            return

        valid_buckets = ("plain", "cam_only", "ss_only", "both", "vc")
        if bucket not in valid_buckets or action not in ("add", "remove", "set"):
            await interaction.response.send_message(
                "❌ Invalid bucket or action! Buckets: `plain`, `cam_only`, `ss_only`, `both`, `vc`. Actions: `add`, `remove`, `set`.",
                ephemeral=True,
            )
            return

        db.adjust_vc_bucket_seconds(self.guild_id, uid, bucket, action, int(hrs * 3600))
        await interaction.response.send_message(f"✅ Adjusted `{bucket}` (`{action}` `{hrs}h`) for <@{uid}>.", ephemeral=True)

        audit_cog: Optional[AuditLogsCog] = interaction.client.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_tracker_adjustment(interaction.guild, interaction.user, uid, bucket, action, hrs)


class LeaderboardExclusionModal(discord.ui.Modal, title="Manage Leaderboard Excluded User"):
    user_id_input = discord.ui.TextInput(label="User ID", style=discord.TextStyle.short, placeholder="e.g., 123456789012345678", required=True)
    mode_input = discord.ui.TextInput(label="Action: add or remove", style=discord.TextStyle.short, placeholder="add", required=True, max_length=10)

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Invalid User ID.", ephemeral=True)

        mode = self.mode_input.value.strip().lower()
        if mode == "add":
            db.add_excluded_leaderboard_user(self.guild_id, uid)
            await interaction.response.send_message(
                f"🚫 Added <@{uid}> (`{uid}`) to leaderboard/challenge top exclusions. Their personal `/stats` and tracking still work normally.",
                ephemeral=True,
            )
        elif mode == "remove":
            removed = db.remove_excluded_leaderboard_user(self.guild_id, uid)
            msg = f"✅ Removed <@{uid}> (`{uid}`) from leaderboard exclusions." if removed else f"ℹ️ `{uid}` was not in the exclusion list."
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Action must be `add` or `remove`.", ephemeral=True)


class UntrackedChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="Select voice channels to exclude from tracking...", min_values=0, max_values=10, channel_types=[discord.ChannelType.voice])

    async def callback(self, interaction: discord.Interaction):
        selected_ids = [ch.id for ch in self.values]
        db.set_untracked_channels(interaction.guild.id, selected_ids)
        await interaction.response.send_message(f"✅ Updated untracked voice channels ({len(selected_ids)} excluded).", ephemeral=True)


class VcSettingsView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.add_item(UntrackedChannelSelect())

    @discord.ui.button(label="View Untracked", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def view_untracked(self, interaction: discord.Interaction, button: discord.ui.Button):
        untracked = db.get_untracked_channels(self.guild_id)
        if not untracked:
            await interaction.response.send_message("✨ No untracked channels.", ephemeral=True)
            return
        await interaction.response.send_message("📋 **Untracked VCs:** " + ", ".join([f"<#{cid}>" for cid in untracked]), ephemeral=True)

    @discord.ui.button(label="Adjust Bucket Hours", style=discord.ButtonStyle.primary, emoji="⏱️", row=1)
    async def adjust_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VcAdjustBucketModal(self.guild_id))

    @discord.ui.button(label="Edit Excluded Users", style=discord.ButtonStyle.danger, emoji="🙈", row=2)
    async def edit_excluded_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LeaderboardExclusionModal(self.guild_id))

    @discord.ui.button(label="View Excluded Users", style=discord.ButtonStyle.secondary, emoji="👥", row=2)
    async def view_excluded_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        excluded = sorted(db.get_excluded_leaderboard_users(self.guild_id))
        if not excluded:
            return await interaction.response.send_message("✨ No users are currently excluded from leaderboards.", ephemeral=True)
        formatted = ", ".join([f"<@{uid}> (`{uid}`)" for uid in excluded])
        await interaction.response.send_message(f"🙈 **Excluded from Leaderboard/Challenge Top:**\n{formatted}", ephemeral=True)


class StatsTimeframeView(discord.ui.View):
    """Interactive timeframe switcher inside /stats (daily, weekly, monthly, all_time)."""

    def __init__(self, cog: "VCTrackerCog", guild: discord.Guild, member: discord.Member, timeframe: str = "daily"):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.member = member
        self.timeframe = timeframe

    def build_embed(self) -> discord.Embed:
        return self.cog.build_stats_embed(self.guild, self.member, self.timeframe)

    @discord.ui.button(label="Today", style=discord.ButtonStyle.secondary, row=0)
    async def btn_today(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "daily"
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "weekly"
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Monthly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "monthly"
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="All-Time", style=discord.ButtonStyle.success, row=0)
    async def btn_all_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "all_time"
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class LeaderboardModeSelect(discord.ui.Select):
    def __init__(self, parent_view: "LeaderboardView"):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(label="All VC (Total)", value="total", emoji="⏱️", description="Total tracked VC time (all buckets)"),
            discord.SelectOption(label="Without Cam/SS (Plain VC)", value="plain", emoji="🎧", description="Plain VC only (no Cam, no SS)"),
            discord.SelectOption(label="Cam Only", value="cam_only", emoji="📹", description="Camera ON only (Screen Share OFF)"),
            discord.SelectOption(label="SS Only", value="ss_only", emoji="🖥️", description="Screen Share ON only (Camera OFF)"),
            discord.SelectOption(label="Cam + SS (Both)", value="both", emoji="🎥", description="Both Camera & Screen Share ON together"),
            discord.SelectOption(label="Any Cam/SS Combined", value="any_cam_ss", emoji="✨", description="Cam Only + SS Only + Both combined"),
        ]
        super().__init__(placeholder="Rank by accountability mode...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.mode = self.values[0]
        self.parent_view.page = 0
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)


class LeaderboardView(discord.ui.View):
    def __init__(self, guild: discord.Guild, rows: list[dict], timeframe: str = "all_time", mode: str = "total"):
        super().__init__(timeout=180)
        self.guild = guild
        self.rows = rows
        self.timeframe = timeframe
        self.mode = mode
        self.page = 0
        self.per_page = 10
        self.add_item(LeaderboardModeSelect(self))

    def _metric_key(self) -> str:
        tf = self.timeframe
        mapping = {
            "total": "all_time_seconds" if tf == "all_time" else f"{tf}_seconds",
            "plain": f"{tf}_plain_seconds",
            "cam_only": f"{tf}_cam_only_seconds",
            "ss_only": f"{tf}_ss_only_seconds",
            "both": f"{tf}_both_seconds",
            "any_cam_ss": f"{tf}_any_cam_ss_seconds",
        }
        return mapping.get(self.mode, f"{tf}_seconds")

    def _mode_label(self) -> str:
        labels = {
            "total": "All VC (Total)",
            "plain": "Without Cam/SS (Plain VC)",
            "cam_only": "Cam Only",
            "ss_only": "SS Only",
            "both": "Cam + SS (Both)",
            "any_cam_ss": "Any Cam/SS Combined",
        }
        return labels.get(self.mode, "All VC (Total)")

    def sort_rows(self) -> list[dict]:
        key = self._metric_key()
        return sorted(self.rows, key=lambda x: x.get(key, 0) or 0, reverse=True)

    def build_embed(self) -> discord.Embed:
        sorted_data = self.sort_rows()
        max_pages = max(1, (len(sorted_data) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, max_pages - 1))
        chunk = sorted_data[self.page * self.per_page : (self.page + 1) * self.per_page]

        tf_title = "Today" if self.timeframe == "daily" else self.timeframe.replace("_", " ").title()
        embed = discord.Embed(
            title=f"🏆 Challenge Leaderboard • {self._mode_label()} ({tf_title})",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        key = self._metric_key()
        tf = self.timeframe

        if not chunk:
            embed.add_field(name="No Data", value="No tracked VC records found yet!", inline=False)
        else:
            lines = []
            for idx, r in enumerate(chunk, start=self.page * self.per_page + 1):
                primary_val = format_duration_hms(r.get(key, 0) or 0)
                cam_s = format_duration_hms(r.get(f"{tf}_cam_only_seconds", 0) or 0)
                ss_s = format_duration_hms(r.get(f"{tf}_ss_only_seconds", 0) or 0)
                both_s = format_duration_hms(r.get(f"{tf}_both_seconds", 0) or 0)
                plain_s = format_duration_hms(r.get(f"{tf}_plain_seconds", 0) or 0)
                lines.append(
                    f"`#{idx}` <@{r['user_id']}> — **{primary_val}**\n"
                    f"└ `Cam: {cam_s} | SS: {ss_s} | Both: {both_s} | Plain: {plain_s}`"
                )
            embed.add_field(name="Standings (Untracked VCs & Excluded Users Hidden)", value="\n".join(lines), inline=False)

        embed.set_footer(text=f"Page {self.page + 1}/{max_pages} • IST Period Tracking")
        return embed

    @discord.ui.button(label="Daily", style=discord.ButtonStyle.secondary, row=1)
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "daily", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=1)
    async def btn_weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "weekly", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Monthly", style=discord.ButtonStyle.secondary, row=1)
    async def btn_monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "monthly", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="All-Time", style=discord.ButtonStyle.success, row=1)
    async def btn_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "all_time", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.primary, row=2)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=2)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class VCTrackerCog(commands.Cog):
    """
    Tracks every second inside tracked VCs into four mutually exclusive buckets:
    - cam_only: self_video == True and self_stream == False
    - ss_only: self_stream == True and self_video == False
    - both: self_video == True and self_stream == True
    - plain: self_video == False and self_stream == False
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_sessions: dict[tuple[int, int], dict] = {}
        self.flush_vc_sessions.start()

    def cog_unload(self):
        self.flush_vc_sessions.cancel()

    @staticmethod
    def _classify_state(self_video: bool, self_stream: bool) -> str:
        if self_video and self_stream:
            return "both"
        if self_video:
            return "cam_only"
        if self_stream:
            return "ss_only"
        return "plain"

    @staticmethod
    def _new_session_dict(vc_id: int, self_video: bool, self_stream: bool, now: datetime.datetime) -> dict:
        return {
            "vc_id": vc_id,
            "bucket": VCTrackerCog._classify_state(self_video, self_stream),
            "bucket_start": now,
            "live_buckets": {"cam_only": 0, "ss_only": 0, "both": 0, "plain": 0},
        }

    def _roll_current_bucket_into_live(self, guild_id: int, user_id: int, session: dict, now: datetime.datetime):
        cur_bucket = session["bucket"]
        start_dt = session["bucket_start"]
        elapsed = max(0, int((now - start_dt).total_seconds()))
        if elapsed > 0:
            db.record_interval_log(guild_id, user_id, session["vc_id"], cur_bucket, start_dt.timestamp(), now.timestamp())
            session["live_buckets"][cur_bucket] = session["live_buckets"].get(cur_bucket, 0) + elapsed
        session["bucket_start"] = now

    def _commit_and_reset_live_buckets(self, guild_id: int, user_id: int, session: dict, now: datetime.datetime):
        self._roll_current_bucket_into_live(guild_id, user_id, session, now)
        lb = session["live_buckets"]
        db.add_exclusive_vc_buckets(
            guild_id=guild_id,
            user_id=user_id,
            cam_only_seconds=lb.get("cam_only", 0),
            ss_only_seconds=lb.get("ss_only", 0),
            both_seconds=lb.get("both", 0),
            plain_seconds=lb.get("plain", 0),
        )
        session["live_buckets"] = {"cam_only": 0, "ss_only": 0, "both": 0, "plain": 0}
        session["bucket_start"] = now

    @commands.Cog.listener()
    async def on_ready(self):
        self.active_sessions.clear()
        now = datetime.datetime.now(datetime.timezone.utc)
        for guild in self.bot.guilds:
            untracked = db.get_untracked_channels(guild.id)
            for vc in guild.voice_channels:
                if vc.id in untracked:
                    continue
                for member in vc.members:
                    if member.bot:
                        continue
                    has_cam = bool(member.voice and member.voice.self_video)
                    has_ss = bool(member.voice and member.voice.self_stream)
                    self.active_sessions[(guild.id, member.id)] = self._new_session_dict(vc.id, has_cam, has_ss, now)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        guild = member.guild
        untracked = db.get_untracked_channels(guild.id)
        now = datetime.datetime.now(datetime.timezone.utc)
        key = (guild.id, member.id)

        before_tracked = bool(before.channel and before.channel.id not in untracked)
        after_tracked = bool(after.channel and after.channel.id not in untracked)

        if before_tracked and (not after_tracked or before.channel.id != after.channel.id):
            session = self.active_sessions.pop(key, None)
            if session:
                self._commit_and_reset_live_buckets(guild.id, member.id, session, now)
                streaks_cog: Optional[StreaksCog] = self.bot.get_cog("StreaksCog")
                if streaks_cog:
                    streaks_cog.evaluate_user_streak(guild.id, member.id)

        if after_tracked:
            if not before_tracked or (before.channel and before.channel.id != after.channel.id):
                self.active_sessions[key] = self._new_session_dict(
                    after.channel.id, bool(after.self_video), bool(after.self_stream), now
                )
            else:
                session = self.active_sessions.get(key)
                if not session:
                    self.active_sessions[key] = self._new_session_dict(
                        after.channel.id, bool(after.self_video), bool(after.self_stream), now
                    )
                else:
                    new_bucket = self._classify_state(bool(after.self_video), bool(after.self_stream))
                    if new_bucket != session["bucket"]:
                        self._roll_current_bucket_into_live(guild.id, member.id, session, now)
                        session["bucket"] = new_bucket
                        session["bucket_start"] = now

    @tasks.loop(minutes=5)
    async def flush_vc_sessions(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for key, session in list(self.active_sessions.items()):
            guild_id, user_id = key
            self._commit_and_reset_live_buckets(guild_id, user_id, session, now)
            streaks_cog: Optional[StreaksCog] = self.bot.get_cog("StreaksCog")
            if streaks_cog:
                streaks_cog.evaluate_user_streak(guild_id, user_id)

    @flush_vc_sessions.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    def build_stats_embed(self, guild: discord.Guild, member: discord.Member, timeframe: str = "daily") -> discord.Embed:
        stats = db.get_user_vc_stats(guild.id, member.id)
        now = datetime.datetime.now(datetime.timezone.utc)
        session = self.active_sessions.get((guild.id, member.id))

        live_add = {"cam_only": 0, "ss_only": 0, "both": 0, "plain": 0}
        status_badges = []
        if session:
            cur_b = session["bucket"]
            pending = max(0, int((now - session["bucket_start"]).total_seconds()))
            for b_key in live_add:
                live_add[b_key] = session["live_buckets"].get(b_key, 0) + (pending if b_key == cur_b else 0)

            vc_obj = guild.get_channel(session["vc_id"])
            vc_name = vc_obj.mention if vc_obj else "Tracked VC"
            status_badges.append(f"🟢 **In VC:** {vc_name}")
            if member.voice and member.voice.self_video:
                status_badges.append("📹 **Cam ON**")
            if member.voice and member.voice.self_stream:
                status_badges.append("🖥️ **Screen Sharing**")
        else:
            status_badges.append("⚪ **Not currently in a tracked VC**")

        tf = timeframe
        cam_only_s = (stats.get(f"{tf}_cam_only_seconds", 0) or 0) + live_add["cam_only"]
        ss_only_s = (stats.get(f"{tf}_ss_only_seconds", 0) or 0) + live_add["ss_only"]
        both_s = (stats.get(f"{tf}_both_seconds", 0) or 0) + live_add["both"]
        plain_s = (stats.get(f"{tf}_plain_seconds", 0) or 0) + live_add["plain"]
        total_vc_s = cam_only_s + ss_only_s + both_s + plain_s
        any_cam_ss_s = cam_only_s + ss_only_s + both_s
        total_cam_s = cam_only_s + both_s
        total_ss_s = ss_only_s + both_s

        tf_label = "Today (IST)" if tf == "daily" else tf.replace("_", " ").title()
        embed = discord.Embed(
            title=f"⏱️ Accountability & Study Stats • {member.display_name}",
            description=f"**Live Status:** {' • '.join(status_badges)}\n**Viewing Timeframe:** `{tf_label}`",
            color=discord.Color.blurple(),
            timestamp=now,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Server Rank", value=f"`#{stats['rank']}`", inline=True)
        embed.add_field(name="Total VC Time", value=f"**{format_duration_hms(total_vc_s)}**", inline=True)
        embed.add_field(name="Any Cam/SS Combined", value=f"**{format_duration_hms(any_cam_ss_s)}**", inline=True)

        embed.add_field(
            name="Mutually Exclusive Buckets (No Double Counting)",
            value=(
                f"• **Without Cam/SS (Plain VC):** `{format_duration_hms(plain_s)}`\n"
                f"• **Cam Only:** `{format_duration_hms(cam_only_s)}`\n"
                f"• **SS Only:** `{format_duration_hms(ss_only_s)}`\n"
                f"• **Cam + SS (Both Active):** `{format_duration_hms(both_s)}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Derived Totals",
            value=f"• **Total Cam Time (`Cam Only + Both`):** `{format_duration_hms(total_cam_s)}`\n• **Total SS Time (`SS Only + Both`):** `{format_duration_hms(total_ss_s)}`",
            inline=False,
        )

        streaks_cog: Optional[StreaksCog] = self.bot.get_cog("StreaksCog")
        if streaks_cog:
            st = streaks_cog.evaluate_user_streak(guild.id, member.id)
            embed.add_field(
                name="🔥 Daily Streak (IST)",
                value=f"**Current:** `{st['current_streak']}d` • **Best:** `{st['best_streak']}d` • **Goal:** `{st['percent']}%` {st['progress_bar']}",
                inline=False,
            )

        return embed

    @app_commands.command(name="stats", description="Displays detailed tracked VC stats with mutually exclusive Cam/SS/Plain buckets.")
    async def stats_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        view = StatsTimeframeView(self, interaction.guild, target, timeframe="daily")
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="leaderboard", description="Displays challenge leaderboard by accountability mode and IST timeframe.")
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        excluded = db.get_excluded_leaderboard_users(interaction.guild.id)
        rows = db.get_vc_leaderboard_all_rows(interaction.guild.id, excluded_users=excluded)
        if not rows:
            await interaction.response.send_message("✨ No tracked VC records found yet.", ephemeral=True)
            return
        view = LeaderboardView(interaction.guild, rows)
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="challenge-stats", description="Staff lookup for mutually exclusive VC study hours within an IST date/time window.")
    @app_commands.describe(
        start_ist="Start time in IST (e.g., '2026-11-18 00:00' or '2026-11-18')",
        end_ist="End time in IST (e.g., '2026-11-19 23:59' or '2026-11-19')",
        member="Optional specific member to inspect (omit to view top challenge leaderboard users)",
        top_limit="Number of top users to display when member is omitted (default 10)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def challenge_stats_cmd(
        self,
        interaction: discord.Interaction,
        start_ist: str,
        end_ist: str,
        member: Optional[discord.Member] = None,
        top_limit: app_commands.Range[int, 1, 20] = 10,
    ):
        dt_start = parse_ist_datetime(start_ist)
        dt_end = parse_ist_datetime(end_ist)
        if not dt_start or not dt_end:
            return await interaction.response.send_message(
                "❌ Invalid IST date/time format! Use `YYYY-MM-DD HH:MM` or `YYYY-MM-DD` (e.g., `2026-11-18 09:00`).",
                ephemeral=True,
            )
        if dt_end <= dt_start:
            return await interaction.response.send_message("❌ `end_ist` must be after `start_ist`.", ephemeral=True)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        for key, session in list(self.active_sessions.items()):
            if key[0] == interaction.guild.id:
                self._commit_and_reset_live_buckets(key[0], key[1], session, now_utc)

        untracked = db.get_untracked_channels(interaction.guild.id)
        excluded_users = db.get_excluded_leaderboard_users(interaction.guild.id)
        window_rows = db.query_challenge_window(
            guild_id=interaction.guild.id,
            start_ts=dt_start.timestamp(),
            end_ts=dt_end.timestamp(),
            untracked_channels=untracked,
            target_user_id=member.id if member else None,
            excluded_users=excluded_users,
        )

        window_label = f"`{dt_start.strftime('%Y-%m-%d %H:%M IST')}` → `{dt_end.strftime('%Y-%m-%d %H:%M IST')}`"

        if member:
            data = window_rows[0] if window_rows else {
                "user_id": member.id,
                "cam_only": 0,
                "ss_only": 0,
                "both": 0,
                "plain": 0,
                "any_cam_ss": 0,
                "total_vc": 0,
            }
            embed = discord.Embed(
                title=f"📊 Challenge Window Lookup • {member.display_name}",
                description=f"**Window (IST):** {window_label}\n*Untracked VCs strictly excluded.*",
                color=discord.Color.blurple(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(
                name="Mutually Exclusive Buckets",
                value=(
                    f"• **Cam Only:** `{format_duration_hms(data['cam_only'])}`\n"
                    f"• **SS Only:** `{format_duration_hms(data['ss_only'])}`\n"
                    f"• **Cam + SS (Both):** `{format_duration_hms(data['both'])}`\n"
                    f"• **Plain VC (No Cam / No SS):** `{format_duration_hms(data['plain'])}`"
                ),
                inline=False,
            )
            embed.add_field(
                name="Combined & Total",
                value=(
                    f"• **Any Cam/SS Combined:** `{format_duration_hms(data['any_cam_ss'])}`\n"
                    f"• **Total Tracked VC Time:** **{format_duration_hms(data['total_vc'])}**"
                ),
                inline=False,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(
            title="🏆 Challenge Window Leaderboard",
            description=f"**Window (IST):** {window_label}\n*Untracked VCs & excluded users strictly excluded.*",
            color=discord.Color.gold(),
        )
        if not window_rows:
            embed.add_field(name="No Activity", value="No tracked VC activity recorded in this IST window.", inline=False)
        else:
            lines = []
            for idx, r in enumerate(window_rows[:top_limit], start=1):
                lines.append(
                    f"`#{idx}` <@{r['user_id']}> — **Total: {format_duration_hms(r['total_vc'])}** | **Any Cam/SS: {format_duration_hms(r['any_cam_ss'])}**\n"
                    f"└ `Cam Only: {format_duration_hms(r['cam_only'])} | SS Only: {format_duration_hms(r['ss_only'])} | Both: {format_duration_hms(r['both'])} | Plain: {format_duration_hms(r['plain'])}`"
                )
            embed.add_field(name=f"Top {min(top_limit, len(window_rows))} Participants", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="vc-settings", description="Configures untracked VCs, bucket hours, and leaderboard user exclusions.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def vc_settings_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ VC Tracker Admin Configuration",
            description=(
                "• Use the dropdown to select **Untracked Voice Channels**.\n"
                "• Use **Adjust Bucket Hours** to manually add/remove/set bucket time.\n"
                "• Use **Edit Excluded Users / View Excluded Users** to manage users hidden from leaderboards."
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        await interaction.response.send_message(embed=embed, view=VcSettingsView(interaction.guild.id), ephemeral=True)


# ==============================================================================
# SECTION 9: TEMPVOICE COG (cogs/tempvoice.py)
# ==============================================================================

async def verify_tempvoice_owner(interaction: discord.Interaction, require_owner: bool = True) -> Optional[tuple[discord.VoiceChannel, dict]]:
    if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ You must be connected to a temporary voice channel first!", ephemeral=True)
        return None

    vc = interaction.user.voice.channel
    meta = db.get_temp_channel(vc.id)
    if not meta:
        await interaction.response.send_message("❌ Your current voice channel is not a temporary room.", ephemeral=True)
        return None

    if require_owner and meta["owner_id"] != interaction.user.id:
        await interaction.response.send_message(f"🚫 Only the room owner (<@{meta['owner_id']}>) can use this control!", ephemeral=True)
        return None

    return vc, meta


class TempVoiceNameModal(discord.ui.Modal, title="Rename Temporary Room"):
    new_name = discord.ui.TextInput(label="New Room Name", style=discord.TextStyle.short, required=True, max_length=100)

    def __init__(self, vc: discord.VoiceChannel):
        super().__init__()
        self.vc = vc
        self.new_name.default = vc.name

    async def on_submit(self, interaction: discord.Interaction):
        meta = db.get_temp_channel(self.vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            return await interaction.response.send_message("🚫 Ownership verification failed.", ephemeral=True)
        clean_name = self.new_name.value.strip()
        await self.vc.edit(name=clean_name)
        await interaction.response.send_message(f"✏️ Room renamed to **{clean_name}**!", ephemeral=True)


class TempVoiceLimitModal(discord.ui.Modal, title="Set Room User Limit"):
    limit_val = discord.ui.TextInput(label="User Limit (0 = Unlimited, 1-99)", style=discord.TextStyle.short, required=True, max_length=2)

    def __init__(self, vc: discord.VoiceChannel):
        super().__init__()
        self.vc = vc
        self.limit_val.default = str(vc.user_limit)

    async def on_submit(self, interaction: discord.Interaction):
        meta = db.get_temp_channel(self.vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            return await interaction.response.send_message("🚫 Ownership verification failed.", ephemeral=True)
        try:
            val = max(0, min(99, int(self.limit_val.value.strip())))
        except ValueError:
            return await interaction.response.send_message("❌ Please enter a valid number between `0` and `99`.", ephemeral=True)
        await self.vc.edit(user_limit=val)
        label = "Unlimited" if val == 0 else f"{val} users"
        await interaction.response.send_message(f"👥 User limit set to **{label}**!", ephemeral=True)


class TempVoiceMemberSelect(discord.ui.UserSelect):
    def __init__(self, action: str, vc: discord.VoiceChannel):
        self.action = action
        self.vc = vc
        placeholders = {
            "trust": "Select a member to trust (allow entry)...",
            "untrust": "Select a member to untrust...",
            "kick": "Select a member to disconnect from VC...",
            "transfer": "Select a member in VC to transfer ownership...",
        }
        super().__init__(placeholder=placeholders.get(action, "Select member..."), min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        meta = db.get_temp_channel(self.vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            return await interaction.response.send_message("🚫 Only the room owner can perform this action.", ephemeral=True)

        target = self.values[0]
        if not isinstance(target, discord.Member):
            return await interaction.response.send_message("❌ Member not found in this server.", ephemeral=True)

        if self.action == "trust":
            await self.vc.set_permissions(target, connect=True, view_channel=True)
            await interaction.response.send_message(f"✅ {target.mention} is now trusted and can join even when locked/hidden.", ephemeral=True)
        elif self.action == "untrust":
            await self.vc.set_permissions(target, overwrite=None)
            await interaction.response.send_message(f"🚫 Removed custom trust permissions for {target.mention}.", ephemeral=True)
        elif self.action == "kick":
            if target.id == interaction.user.id:
                return await interaction.response.send_message("❌ You cannot kick yourself.", ephemeral=True)
            if target not in self.vc.members:
                return await interaction.response.send_message(f"❌ {target.mention} is not in your voice channel.", ephemeral=True)
            await target.move_to(None)
            await interaction.response.send_message(f"👢 Disconnected {target.mention} from the room.", ephemeral=True)
        elif self.action == "transfer":
            if target.bot or target not in self.vc.members:
                return await interaction.response.send_message("❌ You can only transfer ownership to a human member currently inside your VC.", ephemeral=True)
            await self.vc.set_permissions(interaction.user, overwrite=None)
            await self.vc.set_permissions(target, manage_channels=True, move_members=True, connect=True, view_channel=True)
            db.update_temp_channel(self.vc.id, owner_id=target.id)
            await interaction.response.send_message(f"👑 Transferred room ownership to {target.mention}!", ephemeral=True)


class TempVoiceMemberSelectView(discord.ui.View):
    def __init__(self, action: str, vc: discord.VoiceChannel):
        super().__init__(timeout=60)
        self.add_item(TempVoiceMemberSelect(action, vc))


class TempVoiceRegionSelect(discord.ui.Select):
    def __init__(self, vc: discord.VoiceChannel):
        self.vc = vc
        options = [
            discord.SelectOption(label="Automatic", value="auto", emoji="🌐"),
            discord.SelectOption(label="India", value="india", emoji="🇮🇳"),
            discord.SelectOption(label="Singapore", value="singapore", emoji="🇸🇬"),
            discord.SelectOption(label="US East", value="us-east", emoji="🇺🇸"),
            discord.SelectOption(label="Europe (Rotterdam)", value="rotterdam", emoji="🇪🇺"),
            discord.SelectOption(label="Japan", value="japan", emoji="🇯🇵"),
        ]
        super().__init__(placeholder="Select RTC Voice Region...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        meta = db.get_temp_channel(self.vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            return await interaction.response.send_message("🚫 Only the room owner can change region.", ephemeral=True)
        val = None if self.values[0] == "auto" else self.values[0]
        await self.vc.edit(rtc_region=val)
        await interaction.response.send_message(f"🌍 Voice region updated to **{self.values[0].title()}**!", ephemeral=True)


class TempVoiceRegionView(discord.ui.View):
    def __init__(self, vc: discord.VoiceChannel):
        super().__init__(timeout=60)
        self.add_item(TempVoiceRegionSelect(vc))


class TempVoiceControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Name", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="tv_name", row=0)
    async def btn_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        await interaction.response.send_modal(TempVoiceNameModal(vc))

    @discord.ui.button(label="Limit", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="tv_limit", row=0)
    async def btn_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        await interaction.response.send_modal(TempVoiceLimitModal(vc))

    @discord.ui.button(label="Lock / Unlock", style=discord.ButtonStyle.primary, emoji="🔒", custom_id="tv_lock_toggle", row=0)
    async def btn_lock_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        everyone = interaction.guild.default_role
        overwrite = vc.overwrites_for(everyone)
        is_locked = overwrite.connect is False
        if not is_locked:
            overwrite.connect = False
            await vc.set_permissions(everyone, overwrite=overwrite)
            await vc.set_permissions(interaction.user, connect=True, view_channel=True, manage_channels=True, move_members=True)
            db.update_temp_channel(vc.id, privacy_mode="locked")
            await interaction.response.send_message("🔒 **Room Locked!** `@everyone` cannot join; trusted/current members keep access.", ephemeral=True)
        else:
            overwrite.connect = None
            await vc.set_permissions(everyone, overwrite=overwrite)
            db.update_temp_channel(vc.id, privacy_mode="open")
            await interaction.response.send_message("🔓 **Room Unlocked!** Anyone in the server can now join.", ephemeral=True)

    @discord.ui.button(label="Privacy", style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="tv_privacy", row=0)
    async def btn_privacy(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, meta = res
        everyone = interaction.guild.default_role
        overwrite = vc.overwrites_for(everyone)
        if meta.get("privacy_mode", "open") != "hidden":
            overwrite.view_channel = False
            overwrite.connect = False
            await vc.set_permissions(everyone, overwrite=overwrite)
            await vc.set_permissions(interaction.user, connect=True, view_channel=True, manage_channels=True, move_members=True)
            db.update_temp_channel(vc.id, privacy_mode="hidden")
            await interaction.response.send_message("🙈 **Room Hidden!**", ephemeral=True)
        else:
            overwrite.view_channel = None
            overwrite.connect = None
            await vc.set_permissions(everyone, overwrite=overwrite)
            db.update_temp_channel(vc.id, privacy_mode="open")
            await interaction.response.send_message("👁️ **Room Visible & Open!**", ephemeral=True)

    @discord.ui.button(label="Chat", style=discord.ButtonStyle.secondary, emoji="💬", custom_id="tv_chat", row=0)
    async def btn_chat(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, meta = res
        everyone = interaction.guild.default_role
        overwrite = vc.overwrites_for(everyone)
        new_chat = 0 if meta.get("chat_enabled", 1) == 1 else 1
        overwrite.send_messages = None if new_chat == 1 else False
        await vc.set_permissions(everyone, overwrite=overwrite)
        db.update_temp_channel(vc.id, chat_enabled=new_chat)
        await interaction.response.send_message(f"Text-in-voice chat is now **{'Enabled 💬' if new_chat == 1 else 'Disabled 🔇'}**.", ephemeral=True)

    @discord.ui.button(label="Trust", style=discord.ButtonStyle.success, emoji="✅", custom_id="tv_trust", row=1)
    async def btn_trust(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        await interaction.response.send_message("Select a member to trust:", view=TempVoiceMemberSelectView("trust", vc), ephemeral=True)

    @discord.ui.button(label="Untrust", style=discord.ButtonStyle.secondary, emoji="🚫", custom_id="tv_untrust", row=1)
    async def btn_untrust(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        await interaction.response.send_message("Select a member to untrust:", view=TempVoiceMemberSelectView("untrust", vc), ephemeral=True)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢", custom_id="tv_kick", row=1)
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        await interaction.response.send_message("Select a member to kick:", view=TempVoiceMemberSelectView("kick", vc), ephemeral=True)

    @discord.ui.button(label="Region", style=discord.ButtonStyle.secondary, emoji="🌍", custom_id="tv_region", row=1)
    async def btn_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        await interaction.response.send_message("Select RTC region:", view=TempVoiceRegionView(vc), ephemeral=True)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, emoji="👑", custom_id="tv_claim", row=2)
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=False)
        if not res:
            return
        vc, meta = res
        current_owner = interaction.guild.get_member(meta["owner_id"])
        if current_owner and current_owner in vc.members:
            return await interaction.response.send_message(f"❌ Current owner ({current_owner.mention}) is still in the room!", ephemeral=True)
        await vc.set_permissions(interaction.user, manage_channels=True, move_members=True, connect=True, view_channel=True)
        db.update_temp_channel(vc.id, owner_id=interaction.user.id)
        await interaction.response.send_message(f"👑 You now own **{vc.name}**!", ephemeral=True)

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.secondary, emoji="🔁", custom_id="tv_transfer", row=2)
    async def btn_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        await interaction.response.send_message("Select member to transfer ownership to:", view=TempVoiceMemberSelectView("transfer", vc), ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="tv_delete", row=2)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await verify_tempvoice_owner(interaction, require_owner=True)
        if not res:
            return
        vc, _ = res
        db.delete_temp_channel(vc.id)
        await interaction.response.send_message("🗑️ Deleting room...", ephemeral=True)
        await vc.delete()


class TempVoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            for row in db.get_all_temp_channels(guild.id):
                ch = guild.get_channel(row["channel_id"])
                if not ch or len(ch.members) == 0:
                    if ch:
                        try:
                            await ch.delete()
                        except Exception:
                            pass
                    db.delete_temp_channel(row["channel_id"])

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        config = db.get_tempvoice_config(guild.id)

        if config.get("hub_channel_id") and after.channel and after.channel.id == config["hub_channel_id"]:
            cat = guild.get_channel(config["category_id"]) if config.get("category_id") else after.channel.category
            fmt = config.get("name_format") or "🌿・{username}'s study room"
            room_name = fmt.replace("{username}", member.display_name)
            overwrites = {
                member: discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True, view_channel=True),
            }
            new_vc = await guild.create_voice_channel(name=room_name, category=cat, overwrites=overwrites)
            db.register_temp_channel(new_vc.id, guild.id, member.id)
            try:
                await member.move_to(new_vc)
            except Exception:
                pass

        if before.channel:
            meta = db.get_temp_channel(before.channel.id)
            if meta and len(before.channel.members) == 0:
                db.delete_temp_channel(before.channel.id)
                try:
                    await before.channel.delete(reason="TempVoice empty cleanup")
                except Exception:
                    pass

    @app_commands.command(name="tempvoice-setup", description="Configures TempVoice hub and persistent control interface.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tempvoice_setup(
        self,
        interaction: discord.Interaction,
        hub_channel: discord.VoiceChannel,
        interface_channel: discord.TextChannel,
        category: Optional[discord.CategoryChannel] = None,
        name_format: Optional[str] = "🌿・{username}'s study room",
    ):
        db.update_tempvoice_config(
            interaction.guild.id,
            hub_channel_id=hub_channel.id,
            category_id=category.id if category else (hub_channel.category.id if hub_channel.category else None),
            name_format=name_format,
            interface_channel_id=interface_channel.id,
        )
        panel_embed = discord.Embed(
            title="🎙️ TempVoice Room Control Interface",
            description=(
                "Join the **Create VC** hub to spawn your private room, then use the buttons below to customize it!\n\n"
                "**Row 1:** `✏️ Name` • `👥 Limit` • `🔒 Lock / Unlock` • `👁️ Privacy` • `💬 Chat`\n"
                "**Row 2:** `✅ Trust` • `🚫 Untrust` • `👢 Kick` • `🌍 Region`\n"
                "**Row 3:** `👑 Claim` • `🔁 Transfer` • `🗑️ Delete`"
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        msg = await interface_channel.send(embed=panel_embed, view=TempVoiceControlView())
        db.update_tempvoice_config(interaction.guild.id, interface_message_id=msg.id)
        await interaction.response.send_message(f"✅ TempVoice configured in {interface_channel.mention}!", ephemeral=True)


# ==============================================================================
# SECTION 10: UTILITY, AUTOROLE & AFK COGS
# ==============================================================================

class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="purge", description="Purges messages in the current channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_cmd(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted `{len(deleted)}` messages.", ephemeral=True)

        audit_cog: Optional[AuditLogsCog] = interaction.client.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_moderation_action(
                interaction.guild,
                "PURGE",
                interaction.user,
                interaction.channel.mention,
                f"Bulk deleted {len(deleted)} message(s)",
                duration=f"{len(deleted)} msgs",
            )


class AutoroleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Select autoroles...", min_values=1, max_values=5)

    async def callback(self, interaction: discord.Interaction):
        db.set_autoroles(interaction.guild.id, [r.id for r in self.values])
        await interaction.response.send_message("⚙️ Autoroles updated!", ephemeral=True)


class AutoroleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(AutoroleSelect())


class AutoroleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="autorole-setup", description="Configures autoroles.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_setup(self, interaction: discord.Interaction):
        await interaction.response.send_message("Select autoroles:", view=AutoroleView(), ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        roles = [member.guild.get_role(rid) for rid in db.get_autoroles(member.guild.id) if member.guild.get_role(rid)]
        if roles:
            try:
                await member.add_roles(*roles)
            except discord.Forbidden:
                pass


class AfkCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="afk", description="Sets your AFK status.")
    async def afk_cmd(self, interaction: discord.Interaction, *, reason: str = "AFK"):
        db.set_afk(interaction.guild.id, interaction.user.id, reason)
        await interaction.response.send_message(f"💤 {interaction.user.mention}, you are now AFK: **{reason}**", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        afk_data = db.get_afk(message.guild.id, message.author.id)
        if afk_data:
            db.remove_afk(message.guild.id, message.author.id)
            try:
                await message.channel.send(f"Welcome back {message.author.mention}! I've removed your AFK status.", delete_after=10)
            except Exception:
                pass

        for mentioned in message.mentions:
            target_afk = db.get_afk(message.guild.id, mentioned.id)
            if target_afk:
                embed = discord.Embed(title=f"💤 {mentioned.display_name} is AFK", description=f"**Reason:** {target_afk['reason']}\n*Since {target_afk['timestamp']}*", color=discord.Color.orange())
                await message.channel.send(embed=embed, delete_after=15)


# ==============================================================================
# SECTION 11: CHALLENGE VCS & POMODORO TASKS
# ==============================================================================

class ChallengeVCsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.grace_tasks: dict[tuple[int, int], asyncio.Task] = {}

    def cog_unload(self):
        for t in self.grace_tasks.values():
            if not t.done():
                t.cancel()
        self.grace_tasks.clear()

    @staticmethod
    def _meets_requirement(member: discord.Member, challenge_type: str) -> bool:
        if not member.voice:
            return False
        if challenge_type == "cam":
            return bool(member.voice.self_video)
        if challenge_type == "ss":
            return bool(member.voice.self_stream)
        return True

    async def _enforce_grace(self, member: discord.Member, channel: discord.VoiceChannel, challenge_type: str, grace_seconds: int):
        key = (member.guild.id, member.id)
        try:
            await asyncio.sleep(grace_seconds)
            refreshed_member = member.guild.get_member(member.id)
            if not refreshed_member or not refreshed_member.voice or refreshed_member.voice.channel != channel:
                return
            if not self._meets_requirement(refreshed_member, challenge_type):
                req_label = "Camera (`self_video`)" if challenge_type == "cam" else "Screen Share (`self_stream`)"
                reason = f"Failed to enable {req_label} within {grace_seconds}s in {channel.name}."
                try:
                    await refreshed_member.move_to(None, reason=reason)
                except Exception:
                    pass
                try:
                    await refreshed_member.send(
                        f"⚠️ You were disconnected from **{channel.name}** in **{member.guild.name}** because you didn't turn on **{req_label}** within `{grace_seconds}s`."
                    )
                except Exception:
                    pass
                audit_cog: Optional[AuditLogsCog] = self.bot.get_cog("AuditLogsCog")
                if audit_cog:
                    await audit_cog.log_challenge_disconnect(member.guild, refreshed_member, channel, challenge_type, reason)
        except asyncio.CancelledError:
            return
        finally:
            self.grace_tasks.pop(key, None)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        key = (member.guild.id, member.id)

        existing_task = self.grace_tasks.get(key)
        if not after.channel:
            if existing_task and not existing_task.done():
                existing_task.cancel()
            self.grace_tasks.pop(key, None)
            return

        cfg = db.get_challenge_vc(after.channel.id)
        if not cfg:
            if existing_task and not existing_task.done():
                existing_task.cancel()
            self.grace_tasks.pop(key, None)
            return

        c_type = cfg["challenge_type"]
        grace = cfg["grace_seconds"]

        if self._meets_requirement(member, c_type):
            if existing_task and not existing_task.done():
                existing_task.cancel()
            self.grace_tasks.pop(key, None)
        else:
            if not existing_task or existing_task.done():
                self.grace_tasks[key] = asyncio.create_task(self._enforce_grace(member, after.channel, c_type, grace))

    @app_commands.command(name="challenge-vc-setup", description="Designates a Cam-Only or SS-Only timed challenge VC.")
    @app_commands.describe(channel="Target challenge voice channel", challenge_type="Choose 'cam' or 'ss'", grace_seconds="Grace period in seconds before disconnect")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def challenge_vc_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        challenge_type: str,
        grace_seconds: app_commands.Range[int, 5, 300] = 30,
    ):
        ctype = challenge_type.strip().lower()
        if ctype not in ("cam", "ss"):
            return await interaction.response.send_message("❌ `challenge_type` must be either `cam` or `ss`.", ephemeral=True)
        db.set_challenge_vc(channel.id, interaction.guild.id, ctype, grace_seconds)
        await interaction.response.send_message(
            f"✅ Configured {channel.mention} as **{ctype.upper()}-Only** (`{grace_seconds}s` grace timer).",
            ephemeral=True,
        )


class PomodoroActiveView(discord.ui.View):
    def __init__(self, cog: "PomodoroTasksCog", owner_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.owner_id = owner_id

    @discord.ui.button(label="Stop Session", style=discord.ButtonStyle.danger, emoji="🛑")
    async def btn_stop_session(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Only the user who started this Pomodoro session can stop it!", ephemeral=True)

        embed = self.cog.cancel_user_session(interaction.user)
        if not embed:
            return await interaction.response.send_message("ℹ️ You don't have an active Pomodoro session running.", ephemeral=True)

        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.response.send_message(embed=embed)


class PomodoroDuplicateGuardView(discord.ui.View):
    def __init__(self, cog: "PomodoroTasksCog", owner_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.owner_id = owner_id

    @discord.ui.button(label="Stop Current Session", style=discord.ButtonStyle.danger, emoji="🛑")
    async def btn_stop_existing(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ This button isn't for you.", ephemeral=True)

        embed = self.cog.cancel_user_session(interaction.user)
        if not embed:
            return await interaction.response.send_message("ℹ️ Your previous session has already finished.", ephemeral=True)

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="✅ Previous session stopped! You can now run `/pomodoro start`.", embed=embed, view=self)


class PomodoroTasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_pomodoros: dict[int, dict] = {}

    def cog_unload(self):
        for uid, session in list(self.active_pomodoros.items()):
            task: asyncio.Task = session.get("task")
            if task and not task.done():
                task.cancel()
        self.active_pomodoros.clear()

    @staticmethod
    def _format_remaining(seconds: int) -> str:
        seconds = max(0, seconds)
        mins, secs = divmod(seconds, 60)
        return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    def cancel_user_session(self, user: discord.abc.User) -> Optional[discord.Embed]:
        session = self.active_pomodoros.pop(user.id, None)
        if not session:
            return None

        task: asyncio.Task = session.get("task")
        if task and not task.done():
            task.cancel()

        now = datetime.datetime.now(datetime.timezone.utc)
        elapsed_secs = max(0, int((now - session["start_time"]).total_seconds()))
        completed_focus_secs = min(elapsed_secs, session["work_mins"] * 60) if session["phase"] == "focus" else session["work_mins"] * 60
        mins_done, secs_done = divmod(completed_focus_secs, 60)

        return discord.Embed(
            title="🛑 Pomodoro Session Stopped",
            description=(
                f"{user.mention}, your Pomodoro timer has been stopped.\n\n"
                f"• **Completed Focus Time:** `{mins_done}m {secs_done}s` / `{session['work_mins']}m`\n"
                f"• **Status:** Cancelled cleanly — no further notifications will fire."
            ),
            color=discord.Color.red(),
            timestamp=now,
        )

    async def _run_pomodoro_cycle(self, user: discord.abc.User, channel: discord.abc.Messageable, work_mins: int, break_mins: int):
        try:
            await asyncio.sleep(work_mins * 60)
            session = self.active_pomodoros.get(user.id)
            if not session:
                return

            now = datetime.datetime.now(datetime.timezone.utc)
            session["phase"] = "break"
            session["end_time"] = now + datetime.timedelta(minutes=break_mins)

            break_embed = discord.Embed(
                title="🔔 Focus Block Complete — Break Time!",
                description=f"Great job {user.mention}! You completed **{work_mins} minutes** of focused study.\nTake a **{break_mins}-minute** break! 🍵",
                color=discord.Color.green(),
                timestamp=now,
            )
            await channel.send(content=user.mention, embed=break_embed)

            if break_mins > 0:
                await asyncio.sleep(break_mins * 60)
                if user.id not in self.active_pomodoros:
                    return
                done_embed = discord.Embed(
                    title="✨ Pomodoro Cycle Finished!",
                    description=f"{user.mention}, your **{break_mins}-minute** break is over! Ready for another round? 📚",
                    color=discord.Color.blurple(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                await channel.send(content=user.mention, embed=done_embed)

        except asyncio.CancelledError:
            return
        finally:
            finished_session = self.active_pomodoros.pop(user.id, None)
            if finished_session and finished_session.get("message"):
                try:
                    disabled_view = PomodoroActiveView(self, user.id)
                    for child in disabled_view.children:
                        child.disabled = True
                    await finished_session["message"].edit(view=disabled_view)
                except Exception:
                    pass

    pomodoro_group = app_commands.Group(name="pomodoro", description="Manage your guided Pomodoro focus sessions.")

    @pomodoro_group.command(name="start", description="Start a guided Pomodoro focus & break session.")
    async def pomodoro_start(self, interaction: discord.Interaction, work_mins: app_commands.Range[int, 1, 240] = 50, break_mins: app_commands.Range[int, 0, 120] = 10):
        existing = self.active_pomodoros.get(interaction.user.id)
        if existing:
            now = datetime.datetime.now(datetime.timezone.utc)
            rem_str = self._format_remaining(int((existing["end_time"] - now).total_seconds()))
            phase_label = "Focus" if existing["phase"] == "focus" else "Break"
            guard_embed = discord.Embed(
                title="⏳ Active Pomodoro Session Already Running",
                description=(
                    f"You already have an active **{phase_label}** session in progress!\n\n"
                    f"• **Time Remaining:** `{rem_str}`\n"
                    f"• **Configured Cycle:** `{existing['work_mins']}m` focus / `{existing['break_mins']}m` break\n\n"
                    f"Use `/pomodoro stop` or click **Stop Current Session** below first."
                ),
                color=discord.Color.orange(),
            )
            return await interaction.response.send_message(embed=guard_embed, view=PomodoroDuplicateGuardView(self, interaction.user.id), ephemeral=True)

        now = datetime.datetime.now(datetime.timezone.utc)
        end_time = now + datetime.timedelta(minutes=work_mins)
        end_unix = int(end_time.timestamp())

        start_embed = discord.Embed(
            title="🍅 Pomodoro Focus Session Started!",
            description=(
                f"{interaction.user.mention} is locking in for **{work_mins} minutes**!\n\n"
                f"• **Focus Duration:** `{work_mins}m`\n"
                f"• **Break Duration:** `{break_mins}m`\n"
                f"• **Break Starts:** <t:{end_unix}:R> (<t:{end_unix}:t>)"
            ),
            color=discord.Color.from_str("#f4c2c2"),
            timestamp=now,
        )
        view = PomodoroActiveView(self, interaction.user.id)
        await interaction.response.send_message(embed=start_embed, view=view)
        status_msg = await interaction.original_response()

        task = asyncio.create_task(self._run_pomodoro_cycle(interaction.user, interaction.channel, work_mins, break_mins))
        self.active_pomodoros[interaction.user.id] = {
            "task": task,
            "start_time": now,
            "end_time": end_time,
            "work_mins": work_mins,
            "break_mins": break_mins,
            "phase": "focus",
            "channel_id": interaction.channel.id,
            "message": status_msg,
        }

    @pomodoro_group.command(name="stop", description="Stop your currently running Pomodoro session.")
    async def pomodoro_stop(self, interaction: discord.Interaction):
        session = self.active_pomodoros.get(interaction.user.id)
        if not session:
            return await interaction.response.send_message("ℹ️ You don't have an active Pomodoro session running right now.", ephemeral=True)

        status_msg = session.get("message")
        embed = self.cancel_user_session(interaction.user)
        if status_msg:
            try:
                disabled_view = PomodoroActiveView(self, interaction.user.id)
                for child in disabled_view.children:
                    child.disabled = True
                await status_msg.edit(view=disabled_view)
            except Exception:
                pass
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="task", description="Personal study task manager (add, list, clear).")
    async def task_cmd(self, interaction: discord.Interaction, action: str, title: Optional[str] = None, due: Optional[str] = None):
        act = action.lower().strip()
        if act == "add":
            if not title:
                return await interaction.response.send_message("❌ Please provide a `title` when adding a task.", ephemeral=True)
            db.add_user_task(interaction.user.id, title, due)
            await interaction.response.send_message(f"✅ Added task: **{title}** (Due: `{due or 'No deadline'}`)", ephemeral=True)
        elif act == "list":
            tasks_rows = db.get_user_tasks(interaction.user.id)
            active = [t for t in tasks_rows if t["completed"] == 0]
            desc = "\n".join([f"`#{t['id']}` • **{t['title']}** *(Due: {t['due_date']})*" for t in active]) or "✨ You have no active tasks!"
            embed = discord.Embed(title=f"📝 {interaction.user.display_name}'s Study Tasks", description=desc, color=discord.Color.blurple())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif act == "clear":
            removed = db.clear_completed_tasks(interaction.user.id)
            await interaction.response.send_message(f"🧹 Cleared `{removed}` completed task(s).", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Invalid action! Use `add`, `list`, or `clear`.", ephemeral=True)


# ==============================================================================
# SECTION 12: HELP COMMAND COG (cogs/help.py)
# ==============================================================================

class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Moderation", emoji="🛡️", value="mod"),
            discord.SelectOption(label="Welcome System", emoji="🌸", value="welcome"),
            discord.SelectOption(label="VC Tracking", emoji="⏱️", value="vctracker"),
            discord.SelectOption(label="Streaks & Audit", emoji="🔥", value="streaks_audit"),
            discord.SelectOption(label="TempVoice", emoji="🎙️", value="tempvoice"),
            discord.SelectOption(label="Study & Tasks", emoji="🍅", value="study"),
            discord.SelectOption(label="Utility & Presence", emoji="⚙️", value="utility"),
        ]
        super().__init__(placeholder="Select category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        embed = discord.Embed(color=discord.Color.blurple())
        if val == "mod":
            embed.title = "🛡️ Moderation"
            embed.description = "• `/warn`, `/mute`, `/ban`, `/modlogs`"
        elif val == "welcome":
            embed.title = "🌸 Welcome System"
            embed.description = "• `/welcome-setup`"
        elif val == "vctracker":
            embed.title = "⏱️ VC Tracking (Exclusive Buckets)"
            embed.description = (
                "• `/stats [member]` — Interactive Today/Weekly/Monthly/All-Time switcher & Cam/SS/Plain buckets\n"
                "• `/leaderboard` — Filter by All VC, Plain VC, Cam Only, SS Only, Both, or Any Cam/SS\n"
                "• `/challenge-stats` — Staff lookup for mutually exclusive hours in an IST date/time window\n"
                "• `/vc-settings` — Untracked VCs, bucket hour adjustments & leaderboard user exclusions"
            )
        elif val == "streaks_audit":
            embed.title = "🔥 Streaks & Audit Logs"
            embed.description = "• `/streak [member]` — View IST daily streak & goal progress\n• `/streak-config` — Set daily minimum study minutes (00:00 IST reset)\n• `/auditlog-setup` — Configure centralized mod & challenge audit channel"
        elif val == "tempvoice":
            embed.title = "🎙️ TempVoice"
            embed.description = "• `/tempvoice-setup` — Interactive room controls (`Name`, `Limit`, `Lock / Unlock`, `Privacy`, `Chat`, `Trust`, `Untrust`, `Kick`, `Region`, `Claim`, `Transfer`, `Delete`)"
        elif val == "study":
            embed.title = "🍅 Study & Tasks"
            embed.description = "• `/pomodoro start`, `/pomodoro stop`, `/task`, `/challenge-vc-setup`"
        elif val == "utility":
            embed.title = "⚙️ Utility, AFK & Presence"
            embed.description = "• `/purge`, `/autorole-setup`, `/afk`, `/set-status`"
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpSelect())


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Displays help directory.")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(title="✨ Bot Command Directory", description="Select a category from the dropdown menu below 👇", color=discord.Color.from_str("#f4c2c2"))
        await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)


# ==============================================================================
# SECTION 13: MAIN BOT INITIALIZATION (main.py)
# ==============================================================================

class ModWelcomeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await self.add_cog(StatusCog(self))
        await self.add_cog(AuditLogsCog(self))
        await self.add_cog(StreaksCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(WelcomeCog(self))
        await self.add_cog(VCTrackerCog(self))
        await self.add_cog(TempVoiceCog(self))
        await self.add_cog(UtilityCog(self))
        await self.add_cog(AutoroleCog(self))
        await self.add_cog(AfkCog(self))
        await self.add_cog(ChallengeVCsCog(self))
        await self.add_cog(PomodoroTasksCog(self))
        await self.add_cog(HelpCog(self))

        self.add_view(TempVoiceControlView())

        self.tree.on_error = self.on_app_command_error
        synced = await self.tree.sync()
        print(f"[Slash Commands] Synced {len(synced)} command(s) globally.")

    async def on_ready(self):
        status_cog: Optional[StatusCog] = self.get_cog("StatusCog")
        if status_cog:
            try:
                await status_cog.apply_saved_or_default_presence()
            except Exception:
                pass

        print("=" * 55)
        print(f"Logged in as: {self.user} (ID: {self.user.id})")
        print(f"Connected to {len(self.guilds)} server(s).")
        print("Status: Online & Ready!")
        print("=" * 55)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = f"⚠️ Command Error: `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("CRITICAL ERROR: 'DISCORD_TOKEN' not found in environment variables!")

    keep_alive()
    bot = ModWelcomeBot()
    bot.run(token)
