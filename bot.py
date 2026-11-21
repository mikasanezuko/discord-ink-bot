"""
================================================================================
DISCORD MODERATION, STUDY, ECONOMY & DIARIES SUITE BOT (discord.py 2.x)
================================================================================
Designed for 24/7 hosting on Render / Replit with Cloud PostgreSQL (`asyncpg` via
`DATABASE_URL`) persistence—plus graceful local SQLite fallback if `DATABASE_URL`
is omitted—so no data is ever wiped on container restarts or redeploys.
================================================================================
"""

import os
import re
import json
import random
import asyncio
import sqlite3
import datetime
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

try:
    import asyncpg
except ImportError:
    asyncpg = None


# ==============================================================================
# SECTION 1: RENDER & UPTIMEROBOT KEEP-ALIVE WEB SERVER (keep_alive.py)
# ==============================================================================

class KeepAliveHandler(BaseHTTPRequestHandler):
    """HTTP request handler supporting both GET and HEAD pings for Render & UptimeRobot."""

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        db_mode = "PostgreSQL Cloud (DATABASE_URL)" if os.environ.get("DATABASE_URL") else "Local SQLite Fallback"
        html = (
            "<h2>Bot is online and running!</h2>"
            f"<p>Storage Backend: <strong>{db_mode}</strong></p>"
            "<p>Discord Moderation, VC Tracking, TempVoice, Economy Shop, Focus Diaries & Streaks are active.</p>"
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
# SECTION 2: ASYNC CLOUD POSTGRESQL + SAFE FALLBACK DATABASE MANAGER (db_manager.py)
# ==============================================================================

os.makedirs("data", exist_ok=True)
LOCAL_SQLITE_FILE = os.path.join("data", "bot_data.db")
IST_TZ = ZoneInfo("Asia/Kolkata")


class CloudDatabaseManager:
    """
    Async-safe database manager supporting Cloud PostgreSQL (`DATABASE_URL` via `asyncpg`)
    with automatic pool reconnection and seamless SQLite fallback if `DATABASE_URL` is unset.
    """

    def __init__(self):
        self.database_url: Optional[str] = os.environ.get("DATABASE_URL", "").strip() or None
        self.pool: Optional["asyncpg.Pool"] = None
        self.use_postgres: bool = bool(self.database_url and asyncpg is not None)

        if self.database_url and asyncpg is None:
            print("[DB WARNING] DATABASE_URL is set, but `asyncpg` is not installed! Falling back to local SQLite.")

        if not self.use_postgres:
            self._init_sqlite_sync()

    async def connect(self):
        """Connects to PostgreSQL Cloud pool on startup and initializes schema."""
        if not self.use_postgres:
            print("[DB] Running in local SQLite fallback mode (set DATABASE_URL for Cloud PostgreSQL).")
            return

        try:
            dsn = self.database_url
            if dsn.startswith("postgres://"):
                dsn = "postgresql://" + dsn[len("postgres://"):]
            self.pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=10,
                command_timeout=30,
                max_inactive_connection_lifetime=300,
            )
            await self._init_postgres_schema()
            print("[DB] Connected to Cloud PostgreSQL and verified all tables.")
        except Exception as exc:
            print(f"[DB ERROR] Failed to connect to Cloud PostgreSQL ({exc}). Falling back to SQLite.")
            self.use_postgres = False
            self._init_sqlite_sync()

    async def close(self):
        if self.pool:
            try:
                await self.pool.close()
            except Exception:
                pass

    async def _ensure_pg_pool(self) -> bool:
        if not self.use_postgres:
            return False
        if self.pool is None or getattr(self.pool, "_closed", False):
            try:
                await self.connect()
            except Exception:
                return False
        return self.pool is not None

    async def _init_postgres_schema(self):
        if not self.pool:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mod_logs (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    moderator_id BIGINT NOT NULL,
                    action_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    internal_note TEXT,
                    duration TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_settings (
                    guild_id BIGINT PRIMARY KEY,
                    channel_id BIGINT,
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
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_study_stats (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    daily_seconds BIGINT DEFAULT 0,
                    weekly_seconds BIGINT DEFAULT 0,
                    monthly_seconds BIGINT DEFAULT 0,
                    all_time_seconds BIGINT DEFAULT 0,
                    daily_cam_only_seconds BIGINT DEFAULT 0,
                    weekly_cam_only_seconds BIGINT DEFAULT 0,
                    monthly_cam_only_seconds BIGINT DEFAULT 0,
                    all_time_cam_only_seconds BIGINT DEFAULT 0,
                    daily_ss_only_seconds BIGINT DEFAULT 0,
                    weekly_ss_only_seconds BIGINT DEFAULT 0,
                    monthly_ss_only_seconds BIGINT DEFAULT 0,
                    all_time_ss_only_seconds BIGINT DEFAULT 0,
                    daily_both_seconds BIGINT DEFAULT 0,
                    weekly_both_seconds BIGINT DEFAULT 0,
                    monthly_both_seconds BIGINT DEFAULT 0,
                    all_time_both_seconds BIGINT DEFAULT 0,
                    daily_plain_seconds BIGINT DEFAULT 0,
                    weekly_plain_seconds BIGINT DEFAULT 0,
                    monthly_plain_seconds BIGINT DEFAULT 0,
                    all_time_plain_seconds BIGINT DEFAULT 0,
                    last_day_key TEXT NOT NULL,
                    last_week_key TEXT NOT NULL,
                    last_month_key TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_interval_logs (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    bucket TEXT NOT NULL,
                    start_utc DOUBLE PRECISION NOT NULL,
                    end_utc DOUBLE PRECISION NOT NULL,
                    duration_seconds BIGINT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vc_interval_lookup
                ON vc_interval_logs (guild_id, start_utc, end_utc)
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_untracked_channels (
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_excluded_users (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_active_sessions (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    vc_id BIGINT NOT NULL,
                    bucket TEXT NOT NULL,
                    bucket_start_utc DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tempvoice_settings (
                    guild_id BIGINT PRIMARY KEY,
                    hub_channel_id BIGINT,
                    category_id BIGINT,
                    name_format TEXT DEFAULT '🌿・{username}''s study room',
                    interface_channel_id BIGINT,
                    interface_message_id BIGINT
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tempvoice_channels (
                    channel_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    owner_id BIGINT NOT NULL,
                    privacy_mode TEXT DEFAULT 'open',
                    chat_enabled INTEGER DEFAULT 1
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS server_autoroles (
                    guild_id BIGINT PRIMARY KEY,
                    role_ids TEXT DEFAULT '[]'
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS challenge_vcs (
                    channel_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    challenge_type TEXT NOT NULL,
                    grace_seconds INTEGER DEFAULT 30
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_tasks (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    title TEXT NOT NULL,
                    due_date TEXT,
                    completed INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_afk (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS streak_config (
                    guild_id BIGINT PRIMARY KEY,
                    min_daily_seconds INTEGER DEFAULT 1800
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_streaks (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    last_qualified_day TEXT,
                    last_evaluated_day TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log_settings (
                    guild_id BIGINT PRIMARY KEY,
                    channel_id BIGINT
                )
                """
            )
            await conn.execute(
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
            await conn.execute(
                """
                INSERT INTO bot_presence_config (id, custom_override, activity_type, activity_name, online_status)
                VALUES (1, 0, 'watching', '🌛 The Study Hall', 'online')
                ON CONFLICT (id) DO NOTHING
                """
            )
            # Economy & Rental Shop Tables
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_wallets (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    balance BIGINT DEFAULT 0,
                    last_daily_key TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shop_role_items (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    role_id BIGINT NOT NULL,
                    price BIGINT NOT NULL,
                    description TEXT DEFAULT '',
                    duration_seconds BIGINT DEFAULT 0,
                    UNIQUE (guild_id, role_id)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS active_rental_roles (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    role_id BIGINT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (guild_id, user_id, role_id)
                )
                """
            )
            # Focus Diaries Forum Reminder & Quick-Journaling Tables
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS diary_guild_config (
                    guild_id BIGINT PRIMARY KEY,
                    forum_channel_id BIGINT,
                    default_reminder_time TEXT DEFAULT '22:00',
                    coin_reward INTEGER DEFAULT 25
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS diary_threads (
                    thread_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    owner_id BIGINT NOT NULL,
                    reminders_enabled INTEGER DEFAULT 1,
                    reminder_time_ist TEXT DEFAULT '22:00',
                    unanswered_pings INTEGER DEFAULT 0,
                    last_entry_date TEXT,
                    last_ping_date TEXT,
                    last_reward_date TEXT,
                    journal_streak INTEGER DEFAULT 0,
                    best_journal_streak INTEGER DEFAULT 0
                )
                """
            )

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(LOCAL_SQLITE_FILE)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite_sync(self):
        with self._get_sqlite_conn() as conn:
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
            cursor.execute("CREATE TABLE IF NOT EXISTS vc_untracked_channels (guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, PRIMARY KEY (guild_id, channel_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS vc_excluded_users (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, PRIMARY KEY (guild_id, user_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS vc_active_sessions (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, vc_id INTEGER NOT NULL, bucket TEXT NOT NULL, bucket_start_utc REAL NOT NULL, PRIMARY KEY (guild_id, user_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS tempvoice_settings (guild_id INTEGER PRIMARY KEY, hub_channel_id INTEGER, category_id INTEGER, name_format TEXT DEFAULT '🌿・{username}''s study room', interface_channel_id INTEGER, interface_message_id INTEGER)")
            cursor.execute("CREATE TABLE IF NOT EXISTS tempvoice_channels (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, privacy_mode TEXT DEFAULT 'open', chat_enabled INTEGER DEFAULT 1)")
            cursor.execute("CREATE TABLE IF NOT EXISTS server_autoroles (guild_id INTEGER PRIMARY KEY, role_ids TEXT DEFAULT '[]')")
            cursor.execute("CREATE TABLE IF NOT EXISTS challenge_vcs (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, challenge_type TEXT NOT NULL, grace_seconds INTEGER DEFAULT 30)")
            cursor.execute("CREATE TABLE IF NOT EXISTS user_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL, due_date TEXT, completed INTEGER DEFAULT 0, created_at TEXT NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS user_afk (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT NOT NULL, timestamp TEXT NOT NULL, PRIMARY KEY (guild_id, user_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS streak_config (guild_id INTEGER PRIMARY KEY, min_daily_seconds INTEGER DEFAULT 1800)")
            cursor.execute("CREATE TABLE IF NOT EXISTS user_streaks (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, current_streak INTEGER DEFAULT 0, best_streak INTEGER DEFAULT 0, last_qualified_day TEXT, last_evaluated_day TEXT, PRIMARY KEY (guild_id, user_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS audit_log_settings (guild_id INTEGER PRIMARY KEY, channel_id INTEGER)")
            cursor.execute("CREATE TABLE IF NOT EXISTS bot_presence_config (id INTEGER PRIMARY KEY CHECK (id = 1), custom_override INTEGER DEFAULT 0, activity_type TEXT DEFAULT 'watching', activity_name TEXT DEFAULT '🌛 The Study Hall', online_status TEXT DEFAULT 'online')")
            cursor.execute("INSERT OR IGNORE INTO bot_presence_config (id, custom_override, activity_type, activity_name, online_status) VALUES (1, 0, 'watching', '🌛 The Study Hall', 'online')")
            cursor.execute("CREATE TABLE IF NOT EXISTS economy_wallets (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, balance INTEGER DEFAULT 0, last_daily_key TEXT, PRIMARY KEY (guild_id, user_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS shop_role_items (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL, price INTEGER NOT NULL, description TEXT DEFAULT '', duration_seconds INTEGER DEFAULT 0, UNIQUE (guild_id, role_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS active_rental_roles (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, role_id INTEGER NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY (guild_id, user_id, role_id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS diary_guild_config (guild_id INTEGER PRIMARY KEY, forum_channel_id INTEGER, default_reminder_time TEXT DEFAULT '22:00', coin_reward INTEGER DEFAULT 25)")
            cursor.execute("CREATE TABLE IF NOT EXISTS diary_threads (thread_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, reminders_enabled INTEGER DEFAULT 1, reminder_time_ist TEXT DEFAULT '22:00', unanswered_pings INTEGER DEFAULT 0, last_entry_date TEXT, last_ping_date TEXT, last_reward_date TEXT, journal_streak INTEGER DEFAULT 0, best_journal_streak INTEGER DEFAULT 0)")
            conn.commit()

    @staticmethod
    def get_ist_now() -> datetime.datetime:
        return datetime.datetime.now(IST_TZ)

    @classmethod
    def get_ist_period_keys(cls, now_ist: Optional[datetime.datetime] = None) -> tuple[str, str, str]:
        if now_ist is None:
            now_ist = cls.get_ist_now()
        else:
            now_ist = now_ist.astimezone(IST_TZ)
        iso_year, iso_week, _ = now_ist.isocalendar()
        return now_ist.strftime("%Y-%m-%d"), f"{iso_year}-W{iso_week:02d}", now_ist.strftime("%Y-%m")

    @classmethod
    def normalize_row_for_current_ist_periods(cls, row_dict: dict, now_ist: Optional[datetime.datetime] = None) -> dict:
        day_key, week_key, month_key = cls.get_ist_period_keys(now_ist)
        out = dict(row_dict)
        same_day = out.get("last_day_key") == day_key
        same_week = out.get("last_week_key") == week_key
        same_month = out.get("last_month_key") == month_key

        if not same_day:
            for col in ("daily_seconds", "daily_cam_only_seconds", "daily_ss_only_seconds", "daily_both_seconds", "daily_plain_seconds"):
                out[col] = 0
            out["last_day_key"] = day_key
        if not same_week:
            for col in ("weekly_seconds", "weekly_cam_only_seconds", "weekly_ss_only_seconds", "weekly_both_seconds", "weekly_plain_seconds"):
                out[col] = 0
            out["last_week_key"] = week_key
        if not same_month:
            for col in ("monthly_seconds", "monthly_cam_only_seconds", "monthly_ss_only_seconds", "monthly_both_seconds", "monthly_plain_seconds"):
                out[col] = 0
            out["last_month_key"] = month_key
        return out

    # ---------------- PRESENCE CONFIG ----------------
    async def get_presence_config(self) -> dict:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM bot_presence_config WHERE id = 1")
                    if row:
                        return dict(row)
            except Exception as e:
                print(f"[DB ERROR] get_presence_config: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM bot_presence_config WHERE id = 1").fetchone()
            return dict(row) if row else {"custom_override": 0, "activity_type": "watching", "activity_name": "🌛 The Study Hall", "online_status": "online"}

    async def set_presence_config(self, custom_override: int, activity_type: str, activity_name: str, online_status: str):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO bot_presence_config (id, custom_override, activity_type, activity_name, online_status)
                        VALUES (1, $1, $2, $3, $4)
                        ON CONFLICT (id) DO UPDATE SET custom_override = $1, activity_type = $2, activity_name = $3, online_status = $4
                        """,
                        custom_override, activity_type, activity_name, online_status,
                    )
                    return
            except Exception as e:
                print(f"[DB ERROR] set_presence_config: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("UPDATE bot_presence_config SET custom_override = ?, activity_type = ?, activity_name = ?, online_status = ? WHERE id = 1", (custom_override, activity_type, activity_name, online_status))
            conn.commit()

    # ---------------- MODERATION LOGS ----------------
    async def add_mod_log(self, guild_id: int, user_id: int, moderator_id: int, action_type: str, reason: str, internal_note: Optional[str] = None, duration: Optional[str] = None) -> int:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO mod_logs (guild_id, user_id, moderator_id, action_type, reason, internal_note, duration, timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        RETURNING id
                        """,
                        guild_id, user_id, moderator_id, action_type, reason, internal_note or "None", duration or "N/A", timestamp,
                    )
                    return row["id"] if row else 0
            except Exception as e:
                print(f"[DB ERROR] add_mod_log: {e}")
        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mod_logs (guild_id, user_id, moderator_id, action_type, reason, internal_note, duration, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, moderator_id, action_type, reason, internal_note or "None", duration or "N/A", timestamp),
            )
            conn.commit()
            return cur.lastrowid

    async def get_user_logs(self, guild_id: int, user_id: int) -> list[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM mod_logs WHERE guild_id = $1 AND user_id = $2 ORDER BY id DESC", guild_id, user_id)
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_user_logs: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT * FROM mod_logs WHERE guild_id = ? AND user_id = ? ORDER BY id DESC", (guild_id, user_id)).fetchall()
            return [dict(r) for r in rows]

    # ---------------- WELCOME SETTINGS ----------------
    async def get_welcome_config(self, guild_id: int) -> dict:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO welcome_settings (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING", guild_id)
                    row = await conn.fetchrow("SELECT * FROM welcome_settings WHERE guild_id = $1", guild_id)
                    return dict(row)
            except Exception as e:
                print(f"[DB ERROR] get_welcome_config: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO welcome_settings (guild_id) VALUES (?)", (guild_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,)).fetchone()
            return dict(row)

    async def update_welcome_config(self, guild_id: int, **kwargs):
        await self.get_welcome_config(guild_id)
        if not kwargs:
            return
        if await self._ensure_pg_pool():
            try:
                keys = list(kwargs.keys())
                set_clause = ", ".join(f"{k} = ${idx+1}" for idx, k in enumerate(keys))
                vals = list(kwargs.values()) + [guild_id]
                async with self.pool.acquire() as conn:
                    await conn.execute(f"UPDATE welcome_settings SET {set_clause} WHERE guild_id = ${len(vals)}", *vals)
                return
            except Exception as e:
                print(f"[DB ERROR] update_welcome_config: {e}")
        columns = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]
        with self._get_sqlite_conn() as conn:
            conn.execute(f"UPDATE welcome_settings SET {columns} WHERE guild_id = ?", values)
            conn.commit()

    # ---------------- VC STUDY BUCKETS & PERIOD RESETS ----------------
    async def _sync_pg_period_resets(self, conn: "asyncpg.Connection", guild_id: int, user_id: int) -> dict:
        day_key, week_key, month_key = self.get_ist_period_keys()
        row = await conn.fetchrow("SELECT * FROM vc_study_stats WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
        if not row:
            await conn.execute(
                """
                INSERT INTO vc_study_stats (
                    guild_id, user_id,
                    daily_seconds, weekly_seconds, monthly_seconds, all_time_seconds,
                    daily_cam_only_seconds, weekly_cam_only_seconds, monthly_cam_only_seconds, all_time_cam_only_seconds,
                    daily_ss_only_seconds, weekly_ss_only_seconds, monthly_ss_only_seconds, all_time_ss_only_seconds,
                    daily_both_seconds, weekly_both_seconds, monthly_both_seconds, all_time_both_seconds,
                    daily_plain_seconds, weekly_plain_seconds, monthly_plain_seconds, all_time_plain_seconds,
                    last_day_key, last_week_key, last_month_key
                ) VALUES ($1, $2, 0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0, $3, $4, $5)
                """,
                guild_id, user_id, day_key, week_key, month_key,
            )
            row = await conn.fetchrow("SELECT * FROM vc_study_stats WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
            return dict(row)

        same_day = row["last_day_key"] == day_key
        same_week = row["last_week_key"] == week_key
        same_month = row["last_month_key"] == month_key
        if not (same_day and same_week and same_month):
            def pick(col: str, keep: bool) -> int:
                return row[col] if keep else 0
            await conn.execute(
                """
                UPDATE vc_study_stats
                SET daily_seconds = $1, weekly_seconds = $2, monthly_seconds = $3,
                    daily_cam_only_seconds = $4, weekly_cam_only_seconds = $5, monthly_cam_only_seconds = $6,
                    daily_ss_only_seconds = $7, weekly_ss_only_seconds = $8, monthly_ss_only_seconds = $9,
                    daily_both_seconds = $10, weekly_both_seconds = $11, monthly_both_seconds = $12,
                    daily_plain_seconds = $13, weekly_plain_seconds = $14, monthly_plain_seconds = $15,
                    last_day_key = $16, last_week_key = $17, last_month_key = $18
                WHERE guild_id = $19 AND user_id = $20
                """,
                pick("daily_seconds", same_day), pick("weekly_seconds", same_week), pick("monthly_seconds", same_month),
                pick("daily_cam_only_seconds", same_day), pick("weekly_cam_only_seconds", same_week), pick("monthly_cam_only_seconds", same_month),
                pick("daily_ss_only_seconds", same_day), pick("weekly_ss_only_seconds", same_week), pick("monthly_ss_only_seconds", same_month),
                pick("daily_both_seconds", same_day), pick("weekly_both_seconds", same_week), pick("monthly_both_seconds", same_month),
                pick("daily_plain_seconds", same_day), pick("weekly_plain_seconds", same_week), pick("monthly_plain_seconds", same_month),
                day_key, week_key, month_key, guild_id, user_id,
            )
            row = await conn.fetchrow("SELECT * FROM vc_study_stats WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
        return dict(row)

    def _sync_sqlite_period_resets(self, conn: sqlite3.Connection, guild_id: int, user_id: int) -> dict:
        day_key, week_key, month_key = self.get_ist_period_keys()
        row = conn.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO vc_study_stats (
                    guild_id, user_id,
                    daily_seconds, weekly_seconds, monthly_seconds, all_time_seconds,
                    daily_cam_only_seconds, weekly_cam_only_seconds, monthly_cam_only_seconds, all_time_cam_only_seconds,
                    daily_ss_only_seconds, weekly_ss_only_seconds, monthly_ss_only_seconds, all_time_ss_only_seconds,
                    daily_both_seconds, weekly_both_seconds, monthly_both_seconds, all_time_both_seconds,
                    daily_plain_seconds, weekly_plain_seconds, monthly_plain_seconds, all_time_plain_seconds,
                    last_day_key, last_week_key, last_month_key
                ) VALUES (?, ?, 0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0, ?, ?, ?)
                """,
                (guild_id, user_id, day_key, week_key, month_key),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone())

        same_day = row["last_day_key"] == day_key
        same_week = row["last_week_key"] == week_key
        same_month = row["last_month_key"] == month_key
        if not (same_day and same_week and same_month):
            def pick(col: str, keep: bool) -> int:
                return row[col] if keep else 0
            conn.execute(
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
            row = conn.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
        return dict(row)

    async def save_active_session_checkpoint(self, guild_id: int, user_id: int, vc_id: int, bucket: str, bucket_start_ts: float):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO vc_active_sessions (guild_id, user_id, vc_id, bucket, bucket_start_utc)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (guild_id, user_id) DO UPDATE SET vc_id = $3, bucket = $4, bucket_start_utc = $5
                        """,
                        guild_id, user_id, vc_id, bucket, bucket_start_ts,
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] save_active_session_checkpoint: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO vc_active_sessions (guild_id, user_id, vc_id, bucket, bucket_start_utc) VALUES (?, ?, ?, ?, ?)", (guild_id, user_id, vc_id, bucket, bucket_start_ts))
            conn.commit()

    async def remove_active_session_checkpoint(self, guild_id: int, user_id: int):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("DELETE FROM vc_active_sessions WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                return
            except Exception as e:
                print(f"[DB ERROR] remove_active_session_checkpoint: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("DELETE FROM vc_active_sessions WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            conn.commit()

    async def pop_all_active_session_checkpoints(self) -> list[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("DELETE FROM vc_active_sessions RETURNING *")
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] pop_all_active_session_checkpoints: {e}")
        with self._get_sqlite_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM vc_active_sessions").fetchall()]
            conn.execute("DELETE FROM vc_active_sessions")
            conn.commit()
            return rows

    async def record_interval_log(self, guild_id: int, user_id: int, channel_id: int, bucket: str, start_ts: float, end_ts: float):
        secs = int(end_ts - start_ts)
        if secs <= 0:
            return
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO vc_interval_logs (guild_id, user_id, channel_id, bucket, start_utc, end_utc, duration_seconds) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        guild_id, user_id, channel_id, bucket, start_ts, end_ts, secs,
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] record_interval_log: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT INTO vc_interval_logs (guild_id, user_id, channel_id, bucket, start_utc, end_utc, duration_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)", (guild_id, user_id, channel_id, bucket, start_ts, end_ts, secs))
            conn.commit()

    async def query_challenge_window(
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
        rows = []
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    if target_user_id is not None:
                        pg_rows = await conn.fetch(
                            "SELECT user_id, channel_id, bucket, start_utc, end_utc FROM vc_interval_logs WHERE guild_id = $1 AND user_id = $2 AND end_utc > $3 AND start_utc < $4",
                            guild_id, target_user_id, start_ts, end_ts,
                        )
                    else:
                        pg_rows = await conn.fetch(
                            "SELECT user_id, channel_id, bucket, start_utc, end_utc FROM vc_interval_logs WHERE guild_id = $1 AND end_utc > $2 AND start_utc < $3",
                            guild_id, start_ts, end_ts,
                        )
                    rows = [dict(r) for r in pg_rows]
            except Exception as e:
                print(f"[DB ERROR] query_challenge_window: {e}")
        else:
            with self._get_sqlite_conn() as conn:
                if target_user_id is not None:
                    sq_rows = conn.execute("SELECT user_id, channel_id, bucket, start_utc, end_utc FROM vc_interval_logs WHERE guild_id = ? AND user_id = ? AND end_utc > ? AND start_utc < ?", (guild_id, target_user_id, start_ts, end_ts)).fetchall()
                else:
                    sq_rows = conn.execute("SELECT user_id, channel_id, bucket, start_utc, end_utc FROM vc_interval_logs WHERE guild_id = ? AND end_utc > ? AND start_utc < ?", (guild_id, start_ts, end_ts)).fetchall()
                rows = [dict(r) for r in sq_rows]

        per_user: dict[int, dict[str, int]] = {}
        for r in rows:
            if r["channel_id"] in untracked_channels:
                continue
            uid = r["user_id"]
            if target_user_id is None and uid in excluded_users:
                continue
            overlap_secs = max(0, int(min(end_ts, float(r["end_utc"])) - max(start_ts, float(r["start_utc"]))))
            if overlap_secs <= 0:
                continue
            b = r["bucket"] if r["bucket"] in ("cam_only", "ss_only", "both", "plain") else "plain"
            if uid not in per_user:
                per_user[uid] = {"cam_only": 0, "ss_only": 0, "both": 0, "plain": 0}
            per_user[uid][b] += overlap_secs

        results = []
        for uid, b_map in per_user.items():
            total_vc = b_map["cam_only"] + b_map["ss_only"] + b_map["both"] + b_map["plain"]
            any_cam_ss = b_map["cam_only"] + b_map["ss_only"] + b_map["both"]
            results.append({"user_id": uid, **b_map, "any_cam_ss": any_cam_ss, "total_vc": total_vc})
        results.sort(key=lambda item: item["total_vc"], reverse=True)
        return results

    async def add_exclusive_vc_buckets(self, guild_id: int, user_id: int, cam_only_seconds: int = 0, ss_only_seconds: int = 0, both_seconds: int = 0, plain_seconds: int = 0):
        cam_only_seconds = max(0, int(cam_only_seconds))
        ss_only_seconds = max(0, int(ss_only_seconds))
        both_seconds = max(0, int(both_seconds))
        plain_seconds = max(0, int(plain_seconds))
        total_vc = cam_only_seconds + ss_only_seconds + both_seconds + plain_seconds
        if total_vc <= 0:
            return

        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await self._sync_pg_period_resets(conn, guild_id, user_id)
                    await conn.execute(
                        """
                        UPDATE vc_study_stats
                        SET daily_seconds = daily_seconds + $1, weekly_seconds = weekly_seconds + $1, monthly_seconds = monthly_seconds + $1, all_time_seconds = all_time_seconds + $1,
                            daily_cam_only_seconds = daily_cam_only_seconds + $2, weekly_cam_only_seconds = weekly_cam_only_seconds + $2, monthly_cam_only_seconds = monthly_cam_only_seconds + $2, all_time_cam_only_seconds = all_time_cam_only_seconds + $2,
                            daily_ss_only_seconds = daily_ss_only_seconds + $3, weekly_ss_only_seconds = weekly_ss_only_seconds + $3, monthly_ss_only_seconds = monthly_ss_only_seconds + $3, all_time_ss_only_seconds = all_time_ss_only_seconds + $3,
                            daily_both_seconds = daily_both_seconds + $4, weekly_both_seconds = weekly_both_seconds + $4, monthly_both_seconds = monthly_both_seconds + $4, all_time_both_seconds = all_time_both_seconds + $4,
                            daily_plain_seconds = daily_plain_seconds + $5, weekly_plain_seconds = weekly_plain_seconds + $5, monthly_plain_seconds = monthly_plain_seconds + $5, all_time_plain_seconds = all_time_plain_seconds + $5
                        WHERE guild_id = $6 AND user_id = $7
                        """,
                        total_vc, cam_only_seconds, ss_only_seconds, both_seconds, plain_seconds, guild_id, user_id,
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] add_exclusive_vc_buckets: {e}")

        with self._get_sqlite_conn() as conn:
            self._sync_sqlite_period_resets(conn, guild_id, user_id)
            conn.execute(
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

    async def adjust_vc_bucket_seconds(self, guild_id: int, user_id: int, bucket: str, action: str, seconds: int):
        bucket_map = {
            "vc": ("daily_seconds", "weekly_seconds", "monthly_seconds", "all_time_seconds"),
            "plain": ("daily_plain_seconds", "weekly_plain_seconds", "monthly_plain_seconds", "all_time_plain_seconds"),
            "cam_only": ("daily_cam_only_seconds", "weekly_cam_only_seconds", "monthly_cam_only_seconds", "all_time_cam_only_seconds"),
            "ss_only": ("daily_ss_only_seconds", "weekly_ss_only_seconds", "monthly_ss_only_seconds", "all_time_ss_only_seconds"),
            "both": ("daily_both_seconds", "weekly_both_seconds", "monthly_both_seconds", "all_time_both_seconds"),
        }
        cols = bucket_map.get(bucket, bucket_map["vc"])

        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await self._sync_pg_period_resets(conn, guild_id, user_id)
                    new_vals = []
                    for col in cols:
                        cur = row[col] or 0
                        if action == "add":
                            new_vals.append(cur + seconds)
                        elif action == "remove":
                            new_vals.append(max(0, cur - seconds))
                        else:
                            new_vals.append(max(0, seconds))
                    await conn.execute(
                        f"UPDATE vc_study_stats SET {cols[0]} = $1, {cols[1]} = $2, {cols[2]} = $3, {cols[3]} = $4 WHERE guild_id = $5 AND user_id = $6",
                        *new_vals, guild_id, user_id,
                    )
                    if bucket in ("plain", "cam_only", "ss_only", "both"):
                        updated = await conn.fetchrow("SELECT * FROM vc_study_stats WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                        for p in ("daily", "weekly", "monthly", "all_time"):
                            recomputed = (updated[f"{p}_cam_only_seconds"] or 0) + (updated[f"{p}_ss_only_seconds"] or 0) + (updated[f"{p}_both_seconds"] or 0) + (updated[f"{p}_plain_seconds"] or 0)
                            tot_col = "all_time_seconds" if p == "all_time" else f"{p}_seconds"
                            await conn.execute(f"UPDATE vc_study_stats SET {tot_col} = $1 WHERE guild_id = $2 AND user_id = $3", recomputed, guild_id, user_id)
                return
            except Exception as e:
                print(f"[DB ERROR] adjust_vc_bucket_seconds: {e}")

        with self._get_sqlite_conn() as conn:
            row = self._sync_sqlite_period_resets(conn, guild_id, user_id)
            new_vals = []
            for col in cols:
                cur = row[col] or 0
                if action == "add":
                    new_vals.append(cur + seconds)
                elif action == "remove":
                    new_vals.append(max(0, cur - seconds))
                else:
                    new_vals.append(max(0, seconds))
            conn.execute(f"UPDATE vc_study_stats SET {cols[0]} = ?, {cols[1]} = ?, {cols[2]} = ?, {cols[3]} = ? WHERE guild_id = ? AND user_id = ?", (*new_vals, guild_id, user_id))
            if bucket in ("plain", "cam_only", "ss_only", "both"):
                updated = conn.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
                for p in ("daily", "weekly", "monthly", "all_time"):
                    recomputed = (updated[f"{p}_cam_only_seconds"] or 0) + (updated[f"{p}_ss_only_seconds"] or 0) + (updated[f"{p}_both_seconds"] or 0) + (updated[f"{p}_plain_seconds"] or 0)
                    tot_col = "all_time_seconds" if p == "all_time" else f"{p}_seconds"
                    conn.execute(f"UPDATE vc_study_stats SET {tot_col} = ? WHERE guild_id = ? AND user_id = ?", (recomputed, guild_id, user_id))
            conn.commit()

    @classmethod
    def enrich_row_with_derived_metrics(cls, row_dict: dict) -> dict:
        out = cls.normalize_row_for_current_ist_periods(row_dict)
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
            out[f"{prefix}_cam_only_seconds"] = cam_only
            out[f"{prefix}_ss_only_seconds"] = ss_only
            out[f"{prefix}_both_seconds"] = both
            out[f"{prefix}_plain_seconds"] = plain
            out[total_key] = total_vc
            out[f"{prefix}_any_cam_ss_seconds"] = cam_only + ss_only + both
            out[f"{prefix}_total_cam_seconds"] = cam_only + both
            out[f"{prefix}_total_ss_seconds"] = ss_only + both
        return out

    async def get_user_vc_stats(self, guild_id: int, user_id: int) -> dict:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await self._sync_pg_period_resets(conn, guild_id, user_id)
                    rank_val = await conn.fetchval("SELECT COUNT(*) + 1 FROM vc_study_stats WHERE guild_id = $1 AND all_time_seconds > $2", guild_id, row["all_time_seconds"])
                    data = self.enrich_row_with_derived_metrics(row)
                    data["rank"] = int(rank_val or 1)
                    return data
            except Exception as e:
                print(f"[DB ERROR] get_user_vc_stats: {e}")

        with self._get_sqlite_conn() as conn:
            row = self._sync_sqlite_period_resets(conn, guild_id, user_id)
            rank_row = conn.execute("SELECT COUNT(*) + 1 AS rank FROM vc_study_stats WHERE guild_id = ? AND all_time_seconds > ?", (guild_id, row["all_time_seconds"])).fetchone()
            data = self.enrich_row_with_derived_metrics(row)
            data["rank"] = rank_row["rank"] if rank_row else 1
            return data

    async def get_vc_leaderboard_all_rows(self, guild_id: int, excluded_users: Optional[set[int]] = None) -> list[dict]:
        excluded_users = excluded_users or set()
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM vc_study_stats WHERE guild_id = $1", guild_id)
                    return [self.enrich_row_with_derived_metrics(dict(r)) for r in rows if r["user_id"] not in excluded_users]
            except Exception as e:
                print(f"[DB ERROR] get_vc_leaderboard_all_rows: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT * FROM vc_study_stats WHERE guild_id = ?", (guild_id,)).fetchall()
            return [self.enrich_row_with_derived_metrics(dict(r)) for r in rows if r["user_id"] not in excluded_users]

    async def get_all_tracked_user_pairs(self) -> list[tuple[int, int]]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT DISTINCT guild_id, user_id FROM vc_study_stats")
                    return [(r["guild_id"], r["user_id"]) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_all_tracked_user_pairs: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT DISTINCT guild_id, user_id FROM vc_study_stats").fetchall()
            return [(r["guild_id"], r["user_id"]) for r in rows]

    async def get_untracked_channels(self, guild_id: int) -> set[int]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT channel_id FROM vc_untracked_channels WHERE guild_id = $1", guild_id)
                    return {r["channel_id"] for r in rows}
            except Exception as e:
                print(f"[DB ERROR] get_untracked_channels: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT channel_id FROM vc_untracked_channels WHERE guild_id = ?", (guild_id,)).fetchall()
            return {r["channel_id"] for r in rows}

    async def set_untracked_channels(self, guild_id: int, channel_ids: list[int]):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("DELETE FROM vc_untracked_channels WHERE guild_id = $1", guild_id)
                    for cid in set(channel_ids):
                        await conn.execute("INSERT INTO vc_untracked_channels (guild_id, channel_id) VALUES ($1, $2)", guild_id, cid)
                return
            except Exception as e:
                print(f"[DB ERROR] set_untracked_channels: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("DELETE FROM vc_untracked_channels WHERE guild_id = ?", (guild_id,))
            for cid in set(channel_ids):
                conn.execute("INSERT INTO vc_untracked_channels (guild_id, channel_id) VALUES (?, ?)", (guild_id, cid))
            conn.commit()

    async def get_excluded_leaderboard_users(self, guild_id: int) -> set[int]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT user_id FROM vc_excluded_users WHERE guild_id = $1", guild_id)
                    return {r["user_id"] for r in rows}
            except Exception as e:
                print(f"[DB ERROR] get_excluded_leaderboard_users: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT user_id FROM vc_excluded_users WHERE guild_id = ?", (guild_id,)).fetchall()
            return {r["user_id"] for r in rows}

    async def add_excluded_leaderboard_user(self, guild_id: int, user_id: int):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO vc_excluded_users (guild_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", guild_id, user_id)
                return
            except Exception as e:
                print(f"[DB ERROR] add_excluded_leaderboard_user: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO vc_excluded_users (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
            conn.commit()

    async def remove_excluded_leaderboard_user(self, guild_id: int, user_id: int) -> bool:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    res = await conn.execute("DELETE FROM vc_excluded_users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                    return not res.endswith("0")
            except Exception as e:
                print(f"[DB ERROR] remove_excluded_leaderboard_user: {e}")
        with self._get_sqlite_conn() as conn:
            cur = conn.execute("DELETE FROM vc_excluded_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            conn.commit()
            return cur.rowcount > 0

    # ---------------- TEMPVOICE ----------------
    async def get_tempvoice_config(self, guild_id: int) -> dict:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO tempvoice_settings (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING", guild_id)
                    row = await conn.fetchrow("SELECT * FROM tempvoice_settings WHERE guild_id = $1", guild_id)
                    return dict(row)
            except Exception as e:
                print(f"[DB ERROR] get_tempvoice_config: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO tempvoice_settings (guild_id) VALUES (?)", (guild_id,))
            conn.commit()
            return dict(conn.execute("SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,)).fetchone())

    async def update_tempvoice_config(self, guild_id: int, **kwargs):
        await self.get_tempvoice_config(guild_id)
        if not kwargs:
            return
        if await self._ensure_pg_pool():
            try:
                keys = list(kwargs.keys())
                set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(keys))
                vals = list(kwargs.values()) + [guild_id]
                async with self.pool.acquire() as conn:
                    await conn.execute(f"UPDATE tempvoice_settings SET {set_clause} WHERE guild_id = ${len(vals)}", *vals)
                return
            except Exception as e:
                print(f"[DB ERROR] update_tempvoice_config: {e}")
        columns = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]
        with self._get_sqlite_conn() as conn:
            conn.execute(f"UPDATE tempvoice_settings SET {columns} WHERE guild_id = ?", values)
            conn.commit()

    async def register_temp_channel(self, channel_id: int, guild_id: int, owner_id: int, privacy_mode: str = "open", chat_enabled: int = 1):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO tempvoice_channels (channel_id, guild_id, owner_id, privacy_mode, chat_enabled)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (channel_id) DO UPDATE SET guild_id = $2, owner_id = $3, privacy_mode = $4, chat_enabled = $5
                        """,
                        channel_id, guild_id, owner_id, privacy_mode, chat_enabled,
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] register_temp_channel: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO tempvoice_channels (channel_id, guild_id, owner_id, privacy_mode, chat_enabled) VALUES (?, ?, ?, ?, ?)", (channel_id, guild_id, owner_id, privacy_mode, chat_enabled))
            conn.commit()

    async def update_temp_channel(self, channel_id: int, **kwargs):
        if not kwargs:
            return
        if await self._ensure_pg_pool():
            try:
                keys = list(kwargs.keys())
                set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(keys))
                vals = list(kwargs.values()) + [channel_id]
                async with self.pool.acquire() as conn:
                    await conn.execute(f"UPDATE tempvoice_channels SET {set_clause} WHERE channel_id = ${len(vals)}", *vals)
                return
            except Exception as e:
                print(f"[DB ERROR] update_temp_channel: {e}")
        columns = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [channel_id]
        with self._get_sqlite_conn() as conn:
            conn.execute(f"UPDATE tempvoice_channels SET {columns} WHERE channel_id = ?", values)
            conn.commit()

    async def get_temp_channel(self, channel_id: int) -> Optional[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM tempvoice_channels WHERE channel_id = $1", channel_id)
                    return dict(row) if row else None
            except Exception as e:
                print(f"[DB ERROR] get_temp_channel: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM tempvoice_channels WHERE channel_id = ?", (channel_id,)).fetchone()
            return dict(row) if row else None

    async def delete_temp_channel(self, channel_id: int):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("DELETE FROM tempvoice_channels WHERE channel_id = $1", channel_id)
                return
            except Exception as e:
                print(f"[DB ERROR] delete_temp_channel: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("DELETE FROM tempvoice_channels WHERE channel_id = ?", (channel_id,))
            conn.commit()

    async def get_all_temp_channels(self, guild_id: Optional[int] = None) -> list[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM tempvoice_channels WHERE guild_id = $1", guild_id) if guild_id is not None else await conn.fetch("SELECT * FROM tempvoice_channels")
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_all_temp_channels: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT * FROM tempvoice_channels WHERE guild_id = ?", (guild_id,)).fetchall() if guild_id is not None else conn.execute("SELECT * FROM tempvoice_channels").fetchall()
            return [dict(r) for r in rows]

    # ---------------- AUTOROLES, CHALLENGE VCS, TASKS & AFK ----------------
    async def get_autoroles(self, guild_id: int) -> list[int]:
        raw = "[]"
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    val = await conn.fetchval("SELECT role_ids FROM server_autoroles WHERE guild_id = $1", guild_id)
                    raw = val or "[]"
            except Exception as e:
                print(f"[DB ERROR] get_autoroles: {e}")
        else:
            with self._get_sqlite_conn() as conn:
                row = conn.execute("SELECT role_ids FROM server_autoroles WHERE guild_id = ?", (guild_id,)).fetchone()
                raw = row["role_ids"] if row and row["role_ids"] else "[]"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []

    async def set_autoroles(self, guild_id: int, role_ids: list[int]):
        payload = json.dumps(list(set(role_ids)))
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO server_autoroles (guild_id, role_ids) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET role_ids = $2", guild_id, payload)
                return
            except Exception as e:
                print(f"[DB ERROR] set_autoroles: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO server_autoroles (guild_id, role_ids) VALUES (?, ?)", (guild_id, payload))
            conn.commit()

    async def get_challenge_vc(self, channel_id: int) -> Optional[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM challenge_vcs WHERE channel_id = $1", channel_id)
                    return dict(row) if row else None
            except Exception as e:
                print(f"[DB ERROR] get_challenge_vc: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM challenge_vcs WHERE channel_id = ?", (channel_id,)).fetchone()
            return dict(row) if row else None

    async def set_challenge_vc(self, channel_id: int, guild_id: int, challenge_type: str, grace_seconds: int):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO challenge_vcs (channel_id, guild_id, challenge_type, grace_seconds) VALUES ($1, $2, $3, $4) ON CONFLICT (channel_id) DO UPDATE SET guild_id = $2, challenge_type = $3, grace_seconds = $4",
                        channel_id, guild_id, challenge_type, grace_seconds,
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] set_challenge_vc: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO challenge_vcs (channel_id, guild_id, challenge_type, grace_seconds) VALUES (?, ?, ?, ?)", (channel_id, guild_id, challenge_type, grace_seconds))
            conn.commit()

    async def add_user_task(self, user_id: int, title: str, due_date: Optional[str]) -> int:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("INSERT INTO user_tasks (user_id, title, due_date, completed, created_at) VALUES ($1, $2, $3, 0, $4) RETURNING id", user_id, title, due_date or "No deadline", ts)
                    return row["id"] if row else 0
            except Exception as e:
                print(f"[DB ERROR] add_user_task: {e}")
        with self._get_sqlite_conn() as conn:
            cur = conn.execute("INSERT INTO user_tasks (user_id, title, due_date, completed, created_at) VALUES (?, ?, ?, 0, ?)", (user_id, title, due_date or "No deadline", ts))
            conn.commit()
            return cur.lastrowid

    async def get_user_tasks(self, user_id: int) -> list[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM user_tasks WHERE user_id = $1 ORDER BY completed ASC, id ASC", user_id)
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_user_tasks: {e}")
        with self._get_sqlite_conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM user_tasks WHERE user_id = ? ORDER BY completed ASC, id ASC", (user_id,)).fetchall()]

    async def complete_user_task(self, user_id: int, task_id: int) -> bool:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    res = await conn.execute("UPDATE user_tasks SET completed = 1 WHERE user_id = $1 AND id = $2 AND completed = 0", user_id, task_id)
                    return not res.endswith("0")
            except Exception as e:
                print(f"[DB ERROR] complete_user_task: {e}")
        with self._get_sqlite_conn() as conn:
            cur = conn.execute("UPDATE user_tasks SET completed = 1 WHERE user_id = ? AND id = ? AND completed = 0", (user_id, task_id))
            conn.commit()
            return cur.rowcount > 0

    async def delete_user_task(self, user_id: int, task_id: int) -> bool:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    res = await conn.execute("DELETE FROM user_tasks WHERE user_id = $1 AND id = $2", user_id, task_id)
                    return not res.endswith("0")
            except Exception as e:
                print(f"[DB ERROR] delete_user_task: {e}")
        with self._get_sqlite_conn() as conn:
            cur = conn.execute("DELETE FROM user_tasks WHERE user_id = ? AND id = ?", (user_id, task_id))
            conn.commit()
            return cur.rowcount > 0

    async def clear_completed_tasks(self, user_id: int) -> int:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    res = await conn.execute("DELETE FROM user_tasks WHERE user_id = $1 AND completed = 1", user_id)
                    return int(res.split()[-1]) if res else 0
            except Exception as e:
                print(f"[DB ERROR] clear_completed_tasks: {e}")
        with self._get_sqlite_conn() as conn:
            cur = conn.execute("DELETE FROM user_tasks WHERE user_id = ? AND completed = 1", (user_id,))
            conn.commit()
            return cur.rowcount

    async def set_afk(self, guild_id: int, user_id: int, reason: str):
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO user_afk (guild_id, user_id, reason, timestamp) VALUES ($1, $2, $3, $4) ON CONFLICT (guild_id, user_id) DO UPDATE SET reason = $3, timestamp = $4", guild_id, user_id, reason, ts)
                return
            except Exception as e:
                print(f"[DB ERROR] set_afk: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO user_afk (guild_id, user_id, reason, timestamp) VALUES (?, ?, ?, ?)", (guild_id, user_id, reason, ts))
            conn.commit()

    async def get_afk(self, guild_id: int, user_id: int) -> Optional[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM user_afk WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                    return dict(row) if row else None
            except Exception as e:
                print(f"[DB ERROR] get_afk: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM user_afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
            return dict(row) if row else None

    async def remove_afk(self, guild_id: int, user_id: int):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("DELETE FROM user_afk WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                return
            except Exception as e:
                print(f"[DB ERROR] remove_afk: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("DELETE FROM user_afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            conn.commit()

    # ---------------- STREAKS & AUDIT LOG SETTINGS ----------------
    async def get_streak_threshold_seconds(self, guild_id: int) -> int:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    val = await conn.fetchval("SELECT min_daily_seconds FROM streak_config WHERE guild_id = $1", guild_id)
                    return int(val) if val is not None else 1800
            except Exception as e:
                print(f"[DB ERROR] get_streak_threshold_seconds: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT min_daily_seconds FROM streak_config WHERE guild_id = ?", (guild_id,)).fetchone()
            return row["min_daily_seconds"] if row else 1800

    async def set_streak_threshold_seconds(self, guild_id: int, seconds: int):
        seconds = max(60, int(seconds))
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO streak_config (guild_id, min_daily_seconds) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET min_daily_seconds = $2", guild_id, seconds)
                return
            except Exception as e:
                print(f"[DB ERROR] set_streak_threshold_seconds: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO streak_config (guild_id, min_daily_seconds) VALUES (?, ?)", (guild_id, seconds))
            conn.commit()

    async def get_user_streak_record(self, guild_id: int, user_id: int) -> dict:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO user_streaks (guild_id, user_id, current_streak, best_streak, last_qualified_day, last_evaluated_day) VALUES ($1, $2, 0, 0, NULL, NULL) ON CONFLICT (guild_id, user_id) DO NOTHING",
                        guild_id, user_id,
                    )
                    row = await conn.fetchrow("SELECT * FROM user_streaks WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                    return dict(row)
            except Exception as e:
                print(f"[DB ERROR] get_user_streak_record: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO user_streaks (guild_id, user_id, current_streak, best_streak, last_qualified_day, last_evaluated_day) VALUES (?, ?, 0, 0, NULL, NULL)", (guild_id, user_id))
            conn.commit()
            return dict(conn.execute("SELECT * FROM user_streaks WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone())

    async def update_user_streak_record(self, guild_id: int, user_id: int, **kwargs):
        await self.get_user_streak_record(guild_id, user_id)
        if not kwargs:
            return
        if await self._ensure_pg_pool():
            try:
                keys = list(kwargs.keys())
                set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(keys))
                vals = list(kwargs.values()) + [guild_id, user_id]
                async with self.pool.acquire() as conn:
                    await conn.execute(f"UPDATE user_streaks SET {set_clause} WHERE guild_id = ${len(vals)-1} AND user_id = ${len(vals)}", *vals)
                return
            except Exception as e:
                print(f"[DB ERROR] update_user_streak_record: {e}")
        columns = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [guild_id, user_id]
        with self._get_sqlite_conn() as conn:
            conn.execute(f"UPDATE user_streaks SET {columns} WHERE guild_id = ? AND user_id = ?", values)
            conn.commit()

    async def get_audit_log_channel_id(self, guild_id: int) -> Optional[int]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    return await conn.fetchval("SELECT channel_id FROM audit_log_settings WHERE guild_id = $1", guild_id)
            except Exception as e:
                print(f"[DB ERROR] get_audit_log_channel_id: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT channel_id FROM audit_log_settings WHERE guild_id = ?", (guild_id,)).fetchone()
            return row["channel_id"] if row else None

    async def set_audit_log_channel_id(self, guild_id: int, channel_id: int):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO audit_log_settings (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2", guild_id, channel_id)
                return
            except Exception as e:
                print(f"[DB ERROR] set_audit_log_channel_id: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO audit_log_settings (guild_id, channel_id) VALUES (?, ?)", (guild_id, channel_id))
            conn.commit()

    # ---------------- ECONOMY & RENTAL ROLE SHOP ----------------
    async def get_wallet(self, guild_id: int, user_id: int) -> dict:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO economy_wallets (guild_id, user_id, balance, last_daily_key) VALUES ($1, $2, 0, NULL) ON CONFLICT (guild_id, user_id) DO NOTHING",
                        guild_id, user_id,
                    )
                    row = await conn.fetchrow("SELECT * FROM economy_wallets WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                    return dict(row)
            except Exception as e:
                print(f"[DB ERROR] get_wallet: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO economy_wallets (guild_id, user_id, balance, last_daily_key) VALUES (?, ?, 0, NULL)", (guild_id, user_id))
            conn.commit()
            return dict(conn.execute("SELECT * FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone())

    async def add_coins(self, guild_id: int, user_id: int, amount: int) -> int:
        await self.get_wallet(guild_id, user_id)
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    new_bal = await conn.fetchval(
                        "UPDATE economy_wallets SET balance = GREATEST(0, balance + $1) WHERE guild_id = $2 AND user_id = $3 RETURNING balance",
                        int(amount), guild_id, user_id,
                    )
                    return int(new_bal or 0)
            except Exception as e:
                print(f"[DB ERROR] add_coins: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("UPDATE economy_wallets SET balance = MAX(0, balance + ?) WHERE guild_id = ? AND user_id = ?", (int(amount), guild_id, user_id))
            conn.commit()
            row = conn.execute("SELECT balance FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
            return int(row["balance"] if row else 0)

    async def claim_daily_coins(self, guild_id: int, user_id: int, reward: int = 100) -> tuple[bool, int]:
        day_key, _, _ = self.get_ist_period_keys()
        wallet = await self.get_wallet(guild_id, user_id)
        if wallet.get("last_daily_key") == day_key:
            return False, int(wallet.get("balance", 0))

        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    async with conn.transaction():
                        row = await conn.fetchrow("SELECT balance, last_daily_key FROM economy_wallets WHERE guild_id = $1 AND user_id = $2 FOR UPDATE", guild_id, user_id)
                        if row and row["last_daily_key"] == day_key:
                            return False, int(row["balance"] or 0)
                        new_bal = await conn.fetchval(
                            "UPDATE economy_wallets SET balance = balance + $1, last_daily_key = $2 WHERE guild_id = $3 AND user_id = $4 RETURNING balance",
                            int(reward), day_key, guild_id, user_id,
                        )
                        return True, int(new_bal or 0)
            except Exception as e:
                print(f"[DB ERROR] claim_daily_coins: {e}")

        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT balance, last_daily_key FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
            if row and row["last_daily_key"] == day_key:
                return False, int(row["balance"] or 0)
            conn.execute("UPDATE economy_wallets SET balance = balance + ?, last_daily_key = ? WHERE guild_id = ? AND user_id = ?", (int(reward), day_key, guild_id, user_id))
            conn.commit()
            updated = conn.execute("SELECT balance FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
            return True, int(updated["balance"] if updated else 0)

    async def transfer_coins_atomic(self, guild_id: int, sender_id: int, recipient_id: int, amount: int) -> tuple[bool, str, int, int]:
        """Atomically deducts `amount` from sender and credits `amount` to recipient."""
        amount = int(amount)
        if amount <= 0:
            return False, "Amount must be greater than `0`.", 0, 0
        await self.get_wallet(guild_id, sender_id)
        await self.get_wallet(guild_id, recipient_id)

        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    async with conn.transaction():
                        first_id, second_id = sorted([sender_id, recipient_id])
                        await conn.fetch("SELECT user_id FROM economy_wallets WHERE guild_id = $1 AND user_id IN ($2, $3) FOR UPDATE", guild_id, first_id, second_id)
                        s_bal = await conn.fetchval("SELECT balance FROM economy_wallets WHERE guild_id = $1 AND user_id = $2", guild_id, sender_id)
                        if (s_bal or 0) < amount:
                            return False, f"Insufficient coins! Your current balance is **{s_bal or 0:,}** coins.", int(s_bal or 0), 0
                        new_s_bal = await conn.fetchval(
                            "UPDATE economy_wallets SET balance = balance - $1 WHERE guild_id = $2 AND user_id = $3 RETURNING balance",
                            amount, guild_id, sender_id,
                        )
                        new_r_bal = await conn.fetchval(
                            "UPDATE economy_wallets SET balance = balance + $1 WHERE guild_id = $2 AND user_id = $3 RETURNING balance",
                            amount, guild_id, recipient_id,
                        )
                        return True, "OK", int(new_s_bal or 0), int(new_r_bal or 0)
            except Exception as e:
                print(f"[DB ERROR] transfer_coins_atomic: {e}")
                return False, f"Database error during transfer: `{e}`", 0, 0

        with self._get_sqlite_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            s_row = conn.execute("SELECT balance FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, sender_id)).fetchone()
            s_bal = int(s_row["balance"] if s_row else 0)
            if s_bal < amount:
                conn.rollback()
                return False, f"Insufficient coins! Your current balance is **{s_bal:,}** coins.", s_bal, 0
            conn.execute("UPDATE economy_wallets SET balance = balance - ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, sender_id))
            conn.execute("UPDATE economy_wallets SET balance = balance + ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, recipient_id))
            conn.commit()
            new_s = int(conn.execute("SELECT balance FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, sender_id)).fetchone()["balance"])
            new_r = int(conn.execute("SELECT balance FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, recipient_id)).fetchone()["balance"])
            return True, "OK", new_s, new_r

    async def upsert_shop_role_item(self, guild_id: int, role_id: int, price: int, description: str, duration_seconds: int):
        price = max(0, int(price))
        duration_seconds = max(0, int(duration_seconds))
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO shop_role_items (guild_id, role_id, price, description, duration_seconds)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (guild_id, role_id) DO UPDATE SET price = $3, description = $4, duration_seconds = $5
                        """,
                        guild_id, role_id, price, description, duration_seconds,
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] upsert_shop_role_item: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO shop_role_items (guild_id, role_id, price, description, duration_seconds) VALUES (?, ?, ?, ?, ?)",
                (guild_id, role_id, price, description, duration_seconds),
            )
            conn.commit()

    async def remove_shop_role_item(self, guild_id: int, role_id: int) -> bool:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    res = await conn.execute("DELETE FROM shop_role_items WHERE guild_id = $1 AND role_id = $2", guild_id, role_id)
                    return not res.endswith("0")
            except Exception as e:
                print(f"[DB ERROR] remove_shop_role_item: {e}")
        with self._get_sqlite_conn() as conn:
            cur = conn.execute("DELETE FROM shop_role_items WHERE guild_id = ? AND role_id = ?", (guild_id, role_id))
            conn.commit()
            return cur.rowcount > 0

    async def get_shop_items(self, guild_id: int) -> list[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM shop_role_items WHERE guild_id = $1 ORDER BY price ASC, id ASC", guild_id)
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_shop_items: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT * FROM shop_role_items WHERE guild_id = ? ORDER BY price ASC, id ASC", (guild_id,)).fetchall()
            return [dict(r) for r in rows]

    async def get_shop_item_by_role(self, guild_id: int, role_id: int) -> Optional[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM shop_role_items WHERE guild_id = $1 AND role_id = $2", guild_id, role_id)
                    return dict(row) if row else None
            except Exception as e:
                print(f"[DB ERROR] get_shop_item_by_role: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM shop_role_items WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)).fetchone()
            return dict(row) if row else None

    async def purchase_shop_role_atomic(self, guild_id: int, user_id: int, role_id: int) -> tuple[bool, str, int, Optional[float]]:
        """
        Atomically deducts coins and records/extends a rental role if `duration_seconds > 0`.
        Returns `(success, message, new_balance, new_expires_at_utc_or_None)`.
        """
        item = await self.get_shop_item_by_role(guild_id, role_id)
        if not item:
            return False, "That role is not available in the shop.", 0, None

        price = int(item["price"])
        duration_seconds = int(item.get("duration_seconds") or 0)
        await self.get_wallet(guild_id, user_id)
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()

        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    async with conn.transaction():
                        bal = await conn.fetchval("SELECT balance FROM economy_wallets WHERE guild_id = $1 AND user_id = $2 FOR UPDATE", guild_id, user_id)
                        bal = int(bal or 0)
                        if bal < price:
                            return False, f"You need **{price:,}** coins, but you only have **{bal:,}** coins.", bal, None

                        new_bal = await conn.fetchval(
                            "UPDATE economy_wallets SET balance = balance - $1 WHERE guild_id = $2 AND user_id = $3 RETURNING balance",
                            price, guild_id, user_id,
                        )
                        new_expires: Optional[float] = None
                        if duration_seconds > 0:
                            existing_exp = await conn.fetchval(
                                "SELECT expires_at FROM active_rental_roles WHERE guild_id = $1 AND user_id = $2 AND role_id = $3 FOR UPDATE",
                                guild_id, user_id, role_id,
                            )
                            base_ts = max(now_ts, float(existing_exp)) if existing_exp else now_ts
                            new_expires = base_ts + duration_seconds
                            await conn.execute(
                                """
                                INSERT INTO active_rental_roles (guild_id, user_id, role_id, expires_at)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (guild_id, user_id, role_id) DO UPDATE SET expires_at = $4
                                """,
                                guild_id, user_id, role_id, new_expires,
                            )
                        return True, "OK", int(new_bal or 0), new_expires
            except Exception as e:
                print(f"[DB ERROR] purchase_shop_role_atomic: {e}")
                return False, f"Purchase error: `{e}`", 0, None

        with self._get_sqlite_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            bal_row = conn.execute("SELECT balance FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
            bal = int(bal_row["balance"] if bal_row else 0)
            if bal < price:
                conn.rollback()
                return False, f"You need **{price:,}** coins, but you only have **{bal:,}** coins.", bal, None

            conn.execute("UPDATE economy_wallets SET balance = balance - ? WHERE guild_id = ? AND user_id = ?", (price, guild_id, user_id))
            new_expires: Optional[float] = None
            if duration_seconds > 0:
                exp_row = conn.execute(
                    "SELECT expires_at FROM active_rental_roles WHERE guild_id = ? AND user_id = ? AND role_id = ?",
                    (guild_id, user_id, role_id),
                ).fetchone()
                base_ts = max(now_ts, float(exp_row["expires_at"])) if exp_row else now_ts
                new_expires = base_ts + duration_seconds
                conn.execute(
                    "INSERT OR REPLACE INTO active_rental_roles (guild_id, user_id, role_id, expires_at) VALUES (?, ?, ?, ?)",
                    (guild_id, user_id, role_id, new_expires),
                )
            conn.commit()
            new_bal = int(conn.execute("SELECT balance FROM economy_wallets WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()["balance"])
            return True, "OK", new_bal, new_expires

    async def get_user_active_rentals(self, guild_id: int, user_id: int) -> list[dict]:
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT * FROM active_rental_roles WHERE guild_id = $1 AND user_id = $2 AND expires_at > $3 ORDER BY expires_at ASC",
                        guild_id, user_id, now_ts,
                    )
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_user_active_rentals: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM active_rental_roles WHERE guild_id = ? AND user_id = ? AND expires_at > ? ORDER BY expires_at ASC",
                (guild_id, user_id, now_ts),
            ).fetchall()
            return [dict(r) for r in rows]

    async def get_expired_rental_roles(self, now_ts: Optional[float] = None) -> list[dict]:
        if now_ts is None:
            now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM active_rental_roles WHERE expires_at <= $1", now_ts)
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_expired_rental_roles: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT * FROM active_rental_roles WHERE expires_at <= ?", (now_ts,)).fetchall()
            return [dict(r) for r in rows]

    async def delete_rental_role_record(self, guild_id: int, user_id: int, role_id: int):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM active_rental_roles WHERE guild_id = $1 AND user_id = $2 AND role_id = $3",
                        guild_id, user_id, role_id,
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] delete_rental_role_record: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute("DELETE FROM active_rental_roles WHERE guild_id = ? AND user_id = ? AND role_id = ?", (guild_id, user_id, role_id))
            conn.commit()

    # ---------------- FOCUS DIARIES & REMINDERS ----------------
    async def get_diary_guild_config(self, guild_id: int) -> Optional[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM diary_guild_config WHERE guild_id = $1", guild_id)
                    return dict(row) if row else None
            except Exception as e:
                print(f"[DB ERROR] get_diary_guild_config: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM diary_guild_config WHERE guild_id = ?", (guild_id,)).fetchone()
            return dict(row) if row else None

    async def set_diary_guild_config(self, guild_id: int, forum_channel_id: int, default_reminder_time: str = "22:00", coin_reward: int = 25):
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO diary_guild_config (guild_id, forum_channel_id, default_reminder_time, coin_reward)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (guild_id) DO UPDATE SET forum_channel_id = $2, default_reminder_time = $3, coin_reward = $4
                        """,
                        guild_id, forum_channel_id, default_reminder_time, int(coin_reward),
                    )
                return
            except Exception as e:
                print(f"[DB ERROR] set_diary_guild_config: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO diary_guild_config (guild_id, forum_channel_id, default_reminder_time, coin_reward) VALUES (?, ?, ?, ?)",
                (guild_id, forum_channel_id, default_reminder_time, int(coin_reward)),
            )
            conn.commit()

    async def upsert_diary_thread(self, thread_id: int, guild_id: int, owner_id: int, reminders_enabled: int = 1, reminder_time_ist: str = "22:00") -> dict:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO diary_threads (thread_id, guild_id, owner_id, reminders_enabled, reminder_time_ist, unanswered_pings, journal_streak, best_journal_streak)
                        VALUES ($1, $2, $3, $4, $5, 0, 0, 0)
                        ON CONFLICT (thread_id) DO UPDATE SET owner_id = $3
                        """,
                        thread_id, guild_id, owner_id, reminders_enabled, reminder_time_ist,
                    )
                    row = await conn.fetchrow("SELECT * FROM diary_threads WHERE thread_id = $1", thread_id)
                    return dict(row)
            except Exception as e:
                print(f"[DB ERROR] upsert_diary_thread: {e}")
        with self._get_sqlite_conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO diary_threads (thread_id, guild_id, owner_id, reminders_enabled, reminder_time_ist, unanswered_pings, journal_streak, best_journal_streak)
                VALUES (?, ?, ?, ?, ?, 0, 0, 0)
                """,
                (thread_id, guild_id, owner_id, reminders_enabled, reminder_time_ist),
            )
            conn.execute("UPDATE diary_threads SET owner_id = ? WHERE thread_id = ?", (owner_id, thread_id))
            conn.commit()
            return dict(conn.execute("SELECT * FROM diary_threads WHERE thread_id = ?", (thread_id,)).fetchone())

    async def get_diary_thread(self, thread_id: int) -> Optional[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM diary_threads WHERE thread_id = $1", thread_id)
                    return dict(row) if row else None
            except Exception as e:
                print(f"[DB ERROR] get_diary_thread: {e}")
        with self._get_sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM diary_threads WHERE thread_id = ?", (thread_id,)).fetchone()
            return dict(row) if row else None

    async def update_diary_thread(self, thread_id: int, **kwargs):
        if not kwargs:
            return
        if await self._ensure_pg_pool():
            try:
                keys = list(kwargs.keys())
                set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(keys))
                vals = list(kwargs.values()) + [thread_id]
                async with self.pool.acquire() as conn:
                    await conn.execute(f"UPDATE diary_threads SET {set_clause} WHERE thread_id = ${len(vals)}", *vals)
                return
            except Exception as e:
                print(f"[DB ERROR] update_diary_thread: {e}")
        columns = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [thread_id]
        with self._get_sqlite_conn() as conn:
            conn.execute(f"UPDATE diary_threads SET {columns} WHERE thread_id = ?", values)
            conn.commit()

    async def get_all_enabled_diary_threads(self) -> list[dict]:
        if await self._ensure_pg_pool():
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM diary_threads WHERE reminders_enabled = 1")
                    return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DB ERROR] get_all_enabled_diary_threads: {e}")
        with self._get_sqlite_conn() as conn:
            rows = conn.execute("SELECT * FROM diary_threads WHERE reminders_enabled = 1").fetchall()
            return [dict(r) for r in rows]


db = CloudDatabaseManager()


def format_duration_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hrs, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs}h {mins}m"
    return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"


def format_rental_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds <= 0:
        return "Permanent"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if mins > 0 and days == 0:
        parts.append(f"{mins}m")
    return " ".join(parts) if parts else f"{seconds}s"


def parse_rental_duration_input(raw: str) -> Optional[int]:
    """Parses `permanent`, `0`, `24h`, `7d`, `30d`, `12h`, `30m` into seconds (`0` = permanent)."""
    val = (raw or "").strip().lower()
    if val in ("", "0", "perm", "permanent", "forever", "none"):
        return 0
    if val.isdigit():
        return int(val)
    match = re.match(r"^(\d+)([mhdw])$", val)
    if not match:
        return None
    num, unit = int(match.group(1)), match.group(2)
    if num == 0:
        return 0
    multipliers = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    return num * multipliers[unit]


def parse_ist_datetime(date_str: str) -> Optional[datetime.datetime]:
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

        await db.set_presence_config(
            custom_override=1,
            activity_type=normalized_type,
            activity_name=clean_name,
            online_status=normalized_status,
        )
        await self.status_cog.apply_presence(act_type, clean_name, status_obj)

        embed = discord.Embed(
            title="✨ Bot Presence Updated & Saved to Cloud",
            description=(
                f"**Activity:** `{normalized_type.title()}` **{clean_name}**\n"
                f"**Status:** `{normalized_status.upper()}`\n"
                f"*Saved persistently — will automatically reapply after restarts.*"
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class StatusCog(commands.Cog):
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
        cfg = await db.get_presence_config()
        act_type = parse_activity_type(cfg.get("activity_type", "watching")) or discord.ActivityType.watching
        status_obj = parse_online_status(cfg.get("online_status", "online")) or discord.Status.online
        name = cfg.get("activity_name") or DEFAULT_ROTATING_ACTIVITIES[0]
        await self.apply_presence(act_type, name, status_obj)

    @tasks.loop(minutes=7)
    async def rotate_presence_task(self):
        cfg = await db.get_presence_config()
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
        current_cfg = await db.get_presence_config()
        await interaction.response.send_modal(SetStatusModal(self, current_cfg))


# ==============================================================================
# SECTION 4: CENTRALIZED AUDIT LOGS COG (cogs/auditlogs.py)
# ==============================================================================

class AuditLogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_audit_embed(self, guild: Optional[discord.Guild], embed: discord.Embed):
        if not guild:
            return
        try:
            channel_id = await db.get_audit_log_channel_id(guild.id)
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

    async def log_tracker_adjustment(self, guild: discord.Guild, admin: discord.abc.User, target_user_id: int, bucket: str, action: str, hours: float):
        embed = discord.Embed(
            title="⏱️ Audit Log • Manual Tracker Adjustment",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Admin", value=f"{admin.mention} (`{admin.id}`)", inline=True)
        embed.add_field(name="Target User", value=f"<@{target_user_id}> (`{target_user_id}`)", inline=True)
        embed.add_field(name="Bucket & Action", value=f"`{bucket}` • `{action.upper()}` (`{hours}h`)", inline=True)
        await self.send_audit_embed(guild, embed)

    async def log_challenge_disconnect(self, guild: discord.Guild, member: discord.Member, channel: discord.VoiceChannel, challenge_type: str, reason: str):
        embed = discord.Embed(
            title="🚨 Audit Log • Challenge VC Disconnect",
            color=discord.Color.from_str("#ff5555"),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Challenge VC", value=f"{channel.mention} (`{challenge_type.upper()}`)", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await self.send_audit_embed(guild, embed)

    async def log_coin_transfer(self, guild: discord.Guild, sender: discord.abc.User, recipient: discord.abc.User, amount: int, sender_bal: int, recipient_bal: int):
        embed = discord.Embed(
            title="🪙 Audit Log • Coin Transfer (/pay)",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Sender", value=f"{sender.mention} (`{sender.id}`)\nNew Bal: `{sender_bal:,}`", inline=True)
        embed.add_field(name="Recipient", value=f"{recipient.mention} (`{recipient.id}`)\nNew Bal: `{recipient_bal:,}`", inline=True)
        embed.add_field(name="Amount Sent", value=f"**{amount:,} coins**", inline=True)
        await self.send_audit_embed(guild, embed)

    @app_commands.command(name="auditlog-setup", description="Sets the centralized moderation, economy & challenge audit log channel.")
    @app_commands.describe(channel="Text channel where audit embeds will be sent")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def auditlog_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await db.set_audit_log_channel_id(interaction.guild.id, channel.id)
        embed = discord.Embed(
            title="📜 Centralized Audit Log Configured",
            description=f"All moderation, coin transfer, manual tracker edit, and challenge VC disconnect events will be logged in {channel.mention}.",
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
        case_id = await db.add_mod_log(interaction.guild.id, self.target_member.id, interaction.user.id, "WARN", self.reason.value, self.internal_note.value)
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
        case_id = await db.add_mod_log(interaction.guild.id, self.target_member.id, interaction.user.id, "MUTE", self.reason.value, duration=self.duration_str.value)
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
        case_id = await db.add_mod_log(interaction.guild.id, self.target_member.id, interaction.user.id, "BAN", self.reason.value)
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
        logs = await db.get_user_logs(interaction.guild.id, member.id)
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
        await db.update_welcome_config(
            self.guild_id,
            outside_content=self.outside_content.value,
            embed_title=self.embed_title.value,
            embed_description=self.embed_description.value,
            footer_text=self.footer_text.value,
        )
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
        await db.update_welcome_config(
            self.guild_id,
            embed_color=self.embed_color.value.strip(),
            thumbnail_url=self.thumbnail_url.value.strip(),
            banner_url=self.banner_url.value.strip(),
            footer_icon_url=self.footer_icon_url.value.strip(),
            show_author=show_auth,
        )
        await interaction.response.send_message("🌸 Welcome visuals updated!", ephemeral=True)


class WelcomeDashboardView(discord.ui.View):
    def __init__(self, guild_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    def _resolve_guild_id(self, interaction: discord.Interaction) -> Optional[int]:
        return self.guild_id or (interaction.guild.id if interaction.guild else None)

    @discord.ui.button(label="Edit Content", style=discord.ButtonStyle.primary, emoji="✍️", custom_id="welcome_edit_content")
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = self._resolve_guild_id(interaction)
        if not gid:
            return await interaction.response.send_message("❌ Server context not found.", ephemeral=True)
        config = await db.get_welcome_config(gid)
        await interaction.response.send_modal(WelcomeTextModal(gid, config))

    @discord.ui.button(label="Edit Visuals", style=discord.ButtonStyle.secondary, emoji="🎨", custom_id="welcome_edit_visuals")
    async def edit_visuals(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = self._resolve_guild_id(interaction)
        if not gid:
            return await interaction.response.send_message("❌ Server context not found.", ephemeral=True)
        config = await db.get_welcome_config(gid)
        await interaction.response.send_modal(WelcomeVisualsModal(gid, config))

    @discord.ui.button(label="Test Welcome", style=discord.ButtonStyle.success, emoji="🧪", custom_id="welcome_test_preview")
    async def test_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            if not interaction.guild:
                return await interaction.followup.send("❌ This button can only be used inside a server.", ephemeral=True)

            cog: Optional["WelcomeCog"] = interaction.client.get_cog("WelcomeCog")
            if not cog:
                return await interaction.followup.send("❌ Welcome module is not loaded.", ephemeral=True)

            member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(interaction.user.id)
                except discord.HTTPException:
                    member = None
            target_user = member or interaction.user

            sent_msg, target_ch = await cog.send_welcome_message(
                target_user,
                guild=interaction.guild,
                fallback_channel=interaction.channel,
            )
            if sent_msg and target_ch:
                await interaction.followup.send(f"✨ Test welcome preview sent to {target_ch.mention}!", ephemeral=True)
            else:
                await interaction.followup.send(
                    "⚠️ Could not send test welcome — please verify a welcome channel is configured and I have **Send Messages** & **Embed Links** permissions there.",
                    ephemeral=True,
                )
        except Exception as exc:
            await interaction.followup.send(f"❌ Test Welcome failed: `{exc}`", ephemeral=True)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="welcome-setup", description="Configures Mimu-style welcome system.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await db.update_welcome_config(interaction.guild.id, channel_id=channel.id)
        embed = discord.Embed(
            title="🌸 Welcome Dashboard",
            description=f"Welcome messages configured in {channel.mention}!\nUse the buttons below to customize text, visuals, or send a live test preview.",
            color=discord.Color.from_str("#f4c2c2"),
        )
        await interaction.response.send_message(embed=embed, view=WelcomeDashboardView(interaction.guild.id), ephemeral=True)

    @staticmethod
    def _is_valid_http_url(url: str) -> bool:
        val = (url or "").strip()
        return val.startswith("http://") or val.startswith("https://")

    def format_template(self, template: Optional[str], user: discord.abc.User, guild: discord.Guild) -> str:
        if not template:
            return ""
        avatar_url = user.display_avatar.url if user.display_avatar else ""
        member_count = str(guild.member_count or len(guild.members) or 1)
        return (
            template.replace("{user}", user.mention)
            .replace("{username}", user.name)
            .replace("{display_name}", getattr(user, "display_name", user.name))
            .replace("{server}", guild.name)
            .replace("{member_count}", member_count)
            .replace("{avatar}", avatar_url)
        )

    def build_welcome_payload(self, config: dict, member: discord.abc.User, guild: discord.Guild) -> tuple[Optional[str], Optional[discord.Embed]]:
        outside_txt = self.format_template(config.get("outside_content"), member, guild).strip()
        title = self.format_template(config.get("embed_title"), member, guild).strip()
        desc = self.format_template(config.get("embed_description"), member, guild).strip()
        footer = self.format_template(config.get("footer_text"), member, guild).strip()
        thumb = self.format_template(config.get("thumbnail_url"), member, guild).strip()
        banner = self.format_template(config.get("banner_url"), member, guild).strip()
        footer_icon = self.format_template(config.get("footer_icon_url"), member, guild).strip()

        raw_color = (config.get("embed_color") or "#f4c2c2").strip()
        if raw_color and not raw_color.startswith("#"):
            raw_color = f"#{raw_color}"
        try:
            color = discord.Color.from_str(raw_color)
        except Exception:
            color = discord.Color.from_str("#f4c2c2")

        embed = discord.Embed(
            title=title or None,
            description=desc or None,
            color=color,
        )
        if self._is_valid_http_url(thumb):
            embed.set_thumbnail(url=thumb)
        if self._is_valid_http_url(banner):
            embed.set_image(url=banner)
        if footer:
            embed.set_footer(
                text=footer,
                icon_url=footer_icon if self._is_valid_http_url(footer_icon) else None,
            )
        if config.get("show_author", 1) == 1:
            avatar_url = member.display_avatar.url if member.display_avatar else None
            embed.set_author(name=str(member), icon_url=avatar_url)

        has_embed_content = bool(embed.title or embed.description or embed.thumbnail or embed.image or embed.footer or embed.author)
        if not outside_txt and not has_embed_content:
            embed.description = f"Welcome to **{guild.name}**, {member.mention}!"
            has_embed_content = True

        return (outside_txt if outside_txt else None), (embed if has_embed_content else None)

    async def send_welcome_message(
        self,
        member: discord.abc.User,
        guild: Optional[discord.Guild] = None,
        fallback_channel: Optional[discord.abc.Messageable] = None,
    ) -> tuple[Optional[discord.Message], Optional[discord.abc.Messageable]]:
        target_guild = guild or getattr(member, "guild", None)
        if not target_guild:
            return None, None

        config = await db.get_welcome_config(target_guild.id)
        if not config:
            return None, None

        target_channel: Optional[discord.abc.Messageable] = None
        channel_id = config.get("channel_id")
        if channel_id:
            target_channel = target_guild.get_channel(channel_id)
            if target_channel is None:
                try:
                    target_channel = await target_guild.fetch_channel(channel_id)
                except Exception:
                    target_channel = None

        if target_channel is None:
            target_channel = fallback_channel

        if target_channel is None:
            return None, None

        content, embed = self.build_welcome_payload(config, member, target_guild)
        sent = await target_channel.send(content=content, embed=embed)
        return sent, target_channel

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            await self.send_welcome_message(member, guild=member.guild)
        except Exception as exc:
            print(f"[WELCOME ERROR] on_member_join ({member.guild.id}): {exc}")


# ==============================================================================
# SECTION 7: DAILY STUDY STREAKS IN IST COG (cogs/streaks.py)
# ==============================================================================

class StreaksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_streak_rollover.start()

    def cog_unload(self):
        self.daily_streak_rollover.cancel()

    @staticmethod
    def _previous_ist_day_key(day_key: str) -> str:
        dt = datetime.datetime.strptime(day_key, "%Y-%m-%d")
        return (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    async def evaluate_user_streak(self, guild_id: int, user_id: int, now_ist: Optional[datetime.datetime] = None) -> dict:
        if now_ist is None:
            now_ist = db.get_ist_now()
        today_key, _, _ = db.get_ist_period_keys(now_ist)
        yesterday_key = self._previous_ist_day_key(today_key)

        threshold = await db.get_streak_threshold_seconds(guild_id)
        vc_stats = await db.get_user_vc_stats(guild_id, user_id)
        today_seconds = vc_stats.get("daily_seconds", 0) or 0

        rec = await db.get_user_streak_record(guild_id, user_id)
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

        await db.update_user_streak_record(
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

        pairs = await db.get_all_tracked_user_pairs()
        for gid, uid in pairs:
            try:
                await self.evaluate_user_streak(gid, uid, now_ist=now_ist)
            except Exception:
                pass

    @daily_streak_rollover.before_loop
    async def before_rollover(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="streak-config", description="Sets the minimum daily study time required to maintain an IST streak.")
    @app_commands.describe(minutes="Minimum daily minutes in tracked VCs (e.g., 30)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def streak_config_cmd(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 720]):
        await db.set_streak_threshold_seconds(interaction.guild.id, minutes * 60)
        embed = discord.Embed(
            title="🔥 Daily Streak Goal Updated",
            description=f"Members must now study for at least **{minutes} minutes** (`{minutes}m`) per IST day (00:00 IST reset) to build/keep their daily streak.",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="streak", description="Displays a member's IST daily study streak and today's goal progress.")
    async def streak_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        info = await self.evaluate_user_streak(interaction.guild.id, target.id)
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
        embed.set_footer(text="Resets daily at 00:00 IST (Asia/Kolkata)")
        await interaction.response.send_message(embed=embed)


# ==============================================================================
# SECTION 8: VC STUDY TRACKER COG — BUCKETS, CHALLENGE WINDOW & EXCLUSIONS
# ==============================================================================

class VcAdjustBucketModal(discord.ui.Modal, title="Adjust User VC Bucket Hours"):
    user_id_input = discord.ui.TextInput(label="Target User ID", style=discord.TextStyle.short, required=True)
    bucket_input = discord.ui.TextInput(label="Bucket: plain, cam_only, ss_only, both, vc", style=discord.TextStyle.short, placeholder="cam_only", required=True)
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

        await db.adjust_vc_bucket_seconds(self.guild_id, uid, bucket, action, int(hrs * 3600))
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
            await db.add_excluded_leaderboard_user(self.guild_id, uid)
            await interaction.response.send_message(
                f"🚫 Added <@{uid}> (`{uid}`) to leaderboard/challenge top exclusions. Their personal `/stats` and tracking still work normally.",
                ephemeral=True,
            )
        elif mode == "remove":
            removed = await db.remove_excluded_leaderboard_user(self.guild_id, uid)
            msg = f"✅ Removed <@{uid}> (`{uid}`) from leaderboard exclusions." if removed else f"ℹ️ `{uid}` was not in the exclusion list."
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Action must be `add` or `remove`.", ephemeral=True)


class UntrackedChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="Select voice channels to exclude from tracking...", min_values=0, max_values=10, channel_types=[discord.ChannelType.voice])

    async def callback(self, interaction: discord.Interaction):
        selected_ids = [ch.id for ch in self.values]
        await db.set_untracked_channels(interaction.guild.id, selected_ids)
        await interaction.response.send_message(f"✅ Updated untracked voice channels ({len(selected_ids)} excluded).", ephemeral=True)


class VcSettingsView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.add_item(UntrackedChannelSelect())

    @discord.ui.button(label="View Untracked", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def view_untracked(self, interaction: discord.Interaction, button: discord.ui.Button):
        untracked = await db.get_untracked_channels(self.guild_id)
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
        excluded = sorted(await db.get_excluded_leaderboard_users(self.guild_id))
        if not excluded:
            return await interaction.response.send_message("✨ No users are currently excluded from leaderboards.", ephemeral=True)
        formatted = ", ".join([f"<@{uid}> (`{uid}`)" for uid in excluded])
        await interaction.response.send_message(f"🙈 **Excluded from Leaderboard/Challenge Top:**\n{formatted}", ephemeral=True)


class StatsTimeframeView(discord.ui.View):
    def __init__(self, cog: "VCTrackerCog", guild: discord.Guild, member: discord.Member, timeframe: str = "daily"):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.member = member
        self.timeframe = timeframe

    async def build_embed(self) -> discord.Embed:
        return await self.cog.build_stats_embed(self.guild, self.member, self.timeframe)

    @discord.ui.button(label="Today", style=discord.ButtonStyle.secondary, row=0)
    async def btn_today(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "daily"
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "weekly"
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Monthly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "monthly"
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="All-Time", style=discord.ButtonStyle.success, row=0)
    async def btn_all_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "all_time"
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)


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
        await interaction.response.edit_message(embed=await self.parent_view.build_embed(), view=self.parent_view)


class LeaderboardView(discord.ui.View):
    def __init__(self, cog: "VCTrackerCog", guild: discord.Guild, timeframe: str = "all_time", mode: str = "total"):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
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

    async def build_embed(self) -> discord.Embed:
        rows = await self.cog.get_live_merged_leaderboard_rows(self.guild)
        key = self._metric_key()
        sorted_data = sorted(rows, key=lambda x: x.get(key, 0) or 0, reverse=True)

        max_pages = max(1, (len(sorted_data) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, max_pages - 1))
        chunk = sorted_data[self.page * self.per_page : (self.page + 1) * self.per_page]

        tf_title = "Today" if self.timeframe == "daily" else self.timeframe.replace("_", " ").title()
        embed = discord.Embed(
            title=f"🏆 Challenge Leaderboard • {self._mode_label()} ({tf_title})",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

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

        embed.set_footer(text=f"Page {self.page + 1}/{max_pages} • Calendar IST Resets (00:00 Asia/Kolkata)")
        return embed

    @discord.ui.button(label="Daily", style=discord.ButtonStyle.secondary, row=1)
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "daily", 0
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=1)
    async def btn_weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "weekly", 0
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Monthly", style=discord.ButtonStyle.secondary, row=1)
    async def btn_monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "monthly", 0
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="All-Time", style=discord.ButtonStyle.success, row=1)
    async def btn_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "all_time", 0
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.primary, row=2)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=2)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)


class VCTrackerCog(commands.Cog):
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

    def _verify_live_member_in_tracked_vc(self, guild: Optional[discord.Guild], user_id: int, untracked: set[int]) -> Optional[tuple[discord.Member, discord.VoiceChannel]]:
        if not guild:
            return None
        member = guild.get_member(user_id)
        if not member or member.bot or not member.voice or not member.voice.channel:
            return None
        vc = member.voice.channel
        if not isinstance(vc, discord.VoiceChannel) or vc.id in untracked:
            return None
        if member not in vc.members:
            return None
        return member, vc

    async def reconcile_guild_sessions(self, guild: discord.Guild):
        now = datetime.datetime.now(datetime.timezone.utc)
        untracked = await db.get_untracked_channels(guild.id)

        for key, session in list(self.active_sessions.items()):
            gid, uid = key
            if gid != guild.id:
                continue
            verified = self._verify_live_member_in_tracked_vc(guild, uid, untracked)
            if not verified:
                self.active_sessions.pop(key, None)
                await db.remove_active_session_checkpoint(gid, uid)
                await self._commit_and_reset_live_buckets(gid, uid, session, now)
            else:
                member, vc = verified
                if vc.id != session["vc_id"]:
                    await self._commit_and_reset_live_buckets(gid, uid, session, now)
                    session["vc_id"] = vc.id
                    session["bucket"] = self._classify_state(bool(member.voice.self_video), bool(member.voice.self_stream))
                    session["bucket_start"] = now
                    await db.save_active_session_checkpoint(gid, uid, vc.id, session["bucket"], now.timestamp())

        for vc in guild.voice_channels:
            if vc.id in untracked:
                continue
            for member in vc.members:
                if member.bot or not member.voice or member.voice.channel != vc:
                    continue
                key = (guild.id, member.id)
                if key not in self.active_sessions:
                    sess = self._new_session_dict(vc.id, bool(member.voice.self_video), bool(member.voice.self_stream), now)
                    self.active_sessions[key] = sess
                    await db.save_active_session_checkpoint(guild.id, member.id, vc.id, sess["bucket"], now.timestamp())

    async def _roll_current_bucket_into_live(self, guild_id: int, user_id: int, session: dict, now: datetime.datetime):
        cur_bucket = session["bucket"]
        start_dt = session["bucket_start"]
        elapsed = max(0, int((now - start_dt).total_seconds()))
        if elapsed > 0:
            await db.record_interval_log(guild_id, user_id, session["vc_id"], cur_bucket, start_dt.timestamp(), now.timestamp())
            session["live_buckets"][cur_bucket] = session["live_buckets"].get(cur_bucket, 0) + elapsed
        session["bucket_start"] = now

    async def _commit_and_reset_live_buckets(self, guild_id: int, user_id: int, session: dict, now: datetime.datetime):
        await self._roll_current_bucket_into_live(guild_id, user_id, session, now)
        lb = session["live_buckets"]
        await db.add_exclusive_vc_buckets(
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

        checkpoints = await db.pop_all_active_session_checkpoints()
        for cp in checkpoints:
            gid, uid, vc_id = cp["guild_id"], cp["user_id"], cp["vc_id"]
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            untracked = await db.get_untracked_channels(gid)
            verified = self._verify_live_member_in_tracked_vc(guild, uid, untracked)
            if not verified or verified[1].id != vc_id:
                continue
            bucket = cp["bucket"] if cp["bucket"] in ("cam_only", "ss_only", "both", "plain") else "plain"
            start_ts = float(cp["bucket_start_utc"])
            elapsed = max(0, int(now.timestamp() - start_ts))
            if 0 < elapsed <= 21600:
                await db.record_interval_log(gid, uid, vc_id, bucket, start_ts, now.timestamp())
                kwargs = {f"{bucket}_seconds": elapsed}
                await db.add_exclusive_vc_buckets(gid, uid, **kwargs)

        for guild in self.bot.guilds:
            await self.reconcile_guild_sessions(guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        guild = member.guild
        untracked = await db.get_untracked_channels(guild.id)
        now = datetime.datetime.now(datetime.timezone.utc)
        key = (guild.id, member.id)

        before_tracked = bool(before.channel and isinstance(before.channel, discord.VoiceChannel) and before.channel.id not in untracked)
        after_tracked = bool(after.channel and isinstance(after.channel, discord.VoiceChannel) and after.channel.id not in untracked)

        if before_tracked and (not after_tracked or before.channel.id != after.channel.id):
            session = self.active_sessions.pop(key, None)
            await db.remove_active_session_checkpoint(guild.id, member.id)
            if session:
                await self._commit_and_reset_live_buckets(guild.id, member.id, session, now)
                streaks_cog: Optional[StreaksCog] = self.bot.get_cog("StreaksCog")
                if streaks_cog:
                    await streaks_cog.evaluate_user_streak(guild.id, member.id)

        if after_tracked:
            if not before_tracked or (before.channel and before.channel.id != after.channel.id):
                sess = self._new_session_dict(after.channel.id, bool(after.self_video), bool(after.self_stream), now)
                self.active_sessions[key] = sess
                await db.save_active_session_checkpoint(guild.id, member.id, after.channel.id, sess["bucket"], now.timestamp())
            else:
                session = self.active_sessions.get(key)
                if not session:
                    sess = self._new_session_dict(after.channel.id, bool(after.self_video), bool(after.self_stream), now)
                    self.active_sessions[key] = sess
                    await db.save_active_session_checkpoint(guild.id, member.id, after.channel.id, sess["bucket"], now.timestamp())
                else:
                    new_bucket = self._classify_state(bool(after.self_video), bool(after.self_stream))
                    if new_bucket != session["bucket"]:
                        await self._roll_current_bucket_into_live(guild.id, member.id, session, now)
                        session["bucket"] = new_bucket
                        session["bucket_start"] = now
                        await db.save_active_session_checkpoint(guild.id, member.id, after.channel.id, new_bucket, now.timestamp())
        else:
            stale = self.active_sessions.pop(key, None)
            if stale:
                await db.remove_active_session_checkpoint(guild.id, member.id)
                await self._commit_and_reset_live_buckets(guild.id, member.id, stale, now)

    @tasks.loop(minutes=5)
    async def flush_vc_sessions(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for guild in self.bot.guilds:
            await self.reconcile_guild_sessions(guild)

        for key, session in list(self.active_sessions.items()):
            guild_id, user_id = key
            guild = self.bot.get_guild(guild_id)
            untracked = await db.get_untracked_channels(guild_id) if guild else set()
            if not self._verify_live_member_in_tracked_vc(guild, user_id, untracked):
                self.active_sessions.pop(key, None)
                await db.remove_active_session_checkpoint(guild_id, user_id)
                await self._commit_and_reset_live_buckets(guild_id, user_id, session, now)
                continue

            await self._commit_and_reset_live_buckets(guild_id, user_id, session, now)
            await db.save_active_session_checkpoint(guild_id, user_id, session["vc_id"], session["bucket"], now.timestamp())
            streaks_cog: Optional[StreaksCog] = self.bot.get_cog("StreaksCog")
            if streaks_cog:
                await streaks_cog.evaluate_user_streak(guild_id, user_id)

    @flush_vc_sessions.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    async def get_live_merged_leaderboard_rows(self, guild: discord.Guild) -> list[dict]:
        await self.reconcile_guild_sessions(guild)
        excluded = await db.get_excluded_leaderboard_users(guild.id)
        rows = await db.get_vc_leaderboard_all_rows(guild.id, excluded_users=excluded)
        row_by_uid = {r["user_id"]: r for r in rows}

        now = datetime.datetime.now(datetime.timezone.utc)
        untracked = await db.get_untracked_channels(guild.id)

        for (gid, uid), session in list(self.active_sessions.items()):
            if gid != guild.id or uid in excluded:
                continue
            if not self._verify_live_member_in_tracked_vc(guild, uid, untracked):
                continue
            cur_b = session["bucket"]
            pending = max(0, int((now - session["bucket_start"]).total_seconds()))
            live_add = {
                b_key: session["live_buckets"].get(b_key, 0) + (pending if b_key == cur_b else 0)
                for b_key in ("cam_only", "ss_only", "both", "plain")
            }
            add_total = sum(live_add.values())
            if add_total <= 0:
                continue

            if uid not in row_by_uid:
                d_key, w_key, m_key = db.get_ist_period_keys()
                row_by_uid[uid] = db.enrich_row_with_derived_metrics(
                    {
                        "guild_id": guild.id,
                        "user_id": uid,
                        "daily_seconds": 0,
                        "weekly_seconds": 0,
                        "monthly_seconds": 0,
                        "all_time_seconds": 0,
                        "daily_cam_only_seconds": 0,
                        "weekly_cam_only_seconds": 0,
                        "monthly_cam_only_seconds": 0,
                        "all_time_cam_only_seconds": 0,
                        "daily_ss_only_seconds": 0,
                        "weekly_ss_only_seconds": 0,
                        "monthly_ss_only_seconds": 0,
                        "all_time_ss_only_seconds": 0,
                        "daily_both_seconds": 0,
                        "weekly_both_seconds": 0,
                        "monthly_both_seconds": 0,
                        "all_time_both_seconds": 0,
                        "daily_plain_seconds": 0,
                        "weekly_plain_seconds": 0,
                        "monthly_plain_seconds": 0,
                        "all_time_plain_seconds": 0,
                        "last_day_key": d_key,
                        "last_week_key": w_key,
                        "last_month_key": m_key,
                    }
                )

            target = row_by_uid[uid]
            for prefix, tot_col in [("daily", "daily_seconds"), ("weekly", "weekly_seconds"), ("monthly", "monthly_seconds"), ("all_time", "all_time_seconds")]:
                target[f"{prefix}_cam_only_seconds"] += live_add["cam_only"]
                target[f"{prefix}_ss_only_seconds"] += live_add["ss_only"]
                target[f"{prefix}_both_seconds"] += live_add["both"]
                target[f"{prefix}_plain_seconds"] += live_add["plain"]
                target[tot_col] += add_total
                target[f"{prefix}_any_cam_ss_seconds"] += live_add["cam_only"] + live_add["ss_only"] + live_add["both"]
                target[f"{prefix}_total_cam_seconds"] += live_add["cam_only"] + live_add["both"]
                target[f"{prefix}_total_ss_seconds"] += live_add["ss_only"] + live_add["both"]

        return list(row_by_uid.values())

    async def build_stats_embed(self, guild: discord.Guild, member: discord.Member, timeframe: str = "daily") -> discord.Embed:
        await self.reconcile_guild_sessions(guild)
        stats = await db.get_user_vc_stats(guild.id, member.id)
        now = datetime.datetime.now(datetime.timezone.utc)
        untracked = await db.get_untracked_channels(guild.id)
        verified = self._verify_live_member_in_tracked_vc(guild, member.id, untracked)
        session = self.active_sessions.get((guild.id, member.id)) if verified else None

        live_add = {"cam_only": 0, "ss_only": 0, "both": 0, "plain": 0}
        status_badges = []
        if session and verified:
            cur_b = session["bucket"]
            pending = max(0, int((now - session["bucket_start"]).total_seconds()))
            for b_key in live_add:
                live_add[b_key] = session["live_buckets"].get(b_key, 0) + (pending if b_key == cur_b else 0)

            vc_obj = verified[1]
            status_badges.append(f"🟢 **In VC:** {vc_obj.mention}")
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
            st = await streaks_cog.evaluate_user_streak(guild.id, member.id)
            embed.add_field(
                name="🔥 Daily Streak (IST)",
                value=f"**Current:** `{st['current_streak']}d` • **Best:** `{st['best_streak']}d` • **Goal:** `{st['percent']}%` {st['progress_bar']}",
                inline=False,
            )

        embed.set_footer(text="Resets: Daily 00:00 IST • Weekly Mon 00:00 IST • Monthly 1st 00:00 IST")
        return embed

    @app_commands.command(name="stats", description="Displays detailed tracked VC stats with mutually exclusive Cam/SS/Plain buckets.")
    async def stats_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        view = StatsTimeframeView(self, interaction.guild, target, timeframe="daily")
        await interaction.response.send_message(embed=await view.build_embed(), view=view)

    @app_commands.command(name="leaderboard", description="Displays challenge leaderboard by accountability mode and IST timeframe.")
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        view = LeaderboardView(self, interaction.guild)
        embed = await view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

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

        await self.reconcile_guild_sessions(interaction.guild)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        for key, session in list(self.active_sessions.items()):
            if key[0] == interaction.guild.id:
                await self._commit_and_reset_live_buckets(key[0], key[1], session, now_utc)
                await db.save_active_session_checkpoint(key[0], key[1], session["vc_id"], session["bucket"], now_utc.timestamp())

        untracked = await db.get_untracked_channels(interaction.guild.id)
        excluded_users = await db.get_excluded_leaderboard_users(interaction.guild.id)
        window_rows = await db.query_challenge_window(
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
    meta = await db.get_temp_channel(vc.id)
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
        meta = await db.get_temp_channel(self.vc.id)
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
        meta = await db.get_temp_channel(self.vc.id)
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
        meta = await db.get_temp_channel(self.vc.id)
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
            await db.update_temp_channel(self.vc.id, owner_id=target.id)
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
        meta = await db.get_temp_channel(self.vc.id)
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
            await db.update_temp_channel(vc.id, privacy_mode="locked")
            await interaction.response.send_message("🔒 **Room Locked!** `@everyone` cannot join; trusted/current members keep access.", ephemeral=True)
        else:
            overwrite.connect = None
            await vc.set_permissions(everyone, overwrite=overwrite)
            await db.update_temp_channel(vc.id, privacy_mode="open")
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
            await db.update_temp_channel(vc.id, privacy_mode="hidden")
            await interaction.response.send_message("🙈 **Room Hidden!**", ephemeral=True)
        else:
            overwrite.view_channel = None
            overwrite.connect = None
            await vc.set_permissions(everyone, overwrite=overwrite)
            await db.update_temp_channel(vc.id, privacy_mode="open")
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
        await db.update_temp_channel(vc.id, chat_enabled=new_chat)
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
        await db.update_temp_channel(vc.id, owner_id=interaction.user.id)
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
        await db.delete_temp_channel(vc.id)
        await interaction.response.send_message("🗑️ Deleting room...", ephemeral=True)
        await vc.delete()


class TempVoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            for row in await db.get_all_temp_channels(guild.id):
                ch = guild.get_channel(row["channel_id"])
                if not ch or len(ch.members) == 0:
                    if ch:
                        try:
                            await ch.delete()
                        except Exception:
                            pass
                    await db.delete_temp_channel(row["channel_id"])

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        config = await db.get_tempvoice_config(guild.id)

        if config.get("hub_channel_id") and after.channel and after.channel.id == config["hub_channel_id"]:
            cat = guild.get_channel(config["category_id"]) if config.get("category_id") else after.channel.category
            fmt = config.get("name_format") or "🌿・{username}'s study room"
            room_name = fmt.replace("{username}", member.display_name)
            overwrites = {
                member: discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True, view_channel=True),
            }
            new_vc = await guild.create_voice_channel(name=room_name, category=cat, overwrites=overwrites)
            await db.register_temp_channel(new_vc.id, guild.id, member.id)
            try:
                await member.move_to(new_vc)
            except Exception:
                pass

        if before.channel:
            meta = await db.get_temp_channel(before.channel.id)
            if meta and len(before.channel.members) == 0:
                await db.delete_temp_channel(before.channel.id)
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
        await db.update_tempvoice_config(
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
        await db.update_tempvoice_config(interaction.guild.id, interface_message_id=msg.id)
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
        await db.set_autoroles(interaction.guild.id, [r.id for r in self.values])
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
        try:
            guild = member.guild
            if not guild or not guild.me or not guild.me.guild_permissions.manage_roles:
                return
            role_ids = await db.get_autoroles(guild.id)
            if not role_ids:
                return
            bot_top_role = guild.me.top_role
            assignable_roles = []
            for rid in role_ids:
                role = guild.get_role(rid)
                if role and not role.is_default() and not role.managed and bot_top_role > role:
                    assignable_roles.append(role)
            if assignable_roles:
                try:
                    await member.add_roles(*assignable_roles, reason="Server Autorole on Join")
                except discord.Forbidden:
                    pass
                except Exception as exc:
                    print(f"[AUTOROLE ERROR] add_roles ({guild.id}): {exc}")
        except Exception as exc:
            print(f"[AUTOROLE ERROR] on_member_join: {exc}")


class AfkCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="afk", description="Sets your AFK status.")
    async def afk_cmd(self, interaction: discord.Interaction, *, reason: str = "AFK"):
        await db.set_afk(interaction.guild.id, interaction.user.id, reason)
        await interaction.response.send_message(f"💤 {interaction.user.mention}, you are now AFK: **{reason}**", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        afk_data = await db.get_afk(message.guild.id, message.author.id)
        if afk_data:
            await db.remove_afk(message.guild.id, message.author.id)
            try:
                await message.channel.send(f"Welcome back {message.author.mention}! I've removed your AFK status.", delete_after=10)
            except Exception:
                pass

        for mentioned in message.mentions:
            target_afk = await db.get_afk(message.guild.id, mentioned.id)
            if target_afk:
                embed = discord.Embed(title=f"💤 {mentioned.display_name} is AFK", description=f"**Reason:** {target_afk['reason']}\n*Since {target_afk['timestamp']}*", color=discord.Color.orange())
                await message.channel.send(embed=embed, delete_after=15)


# ==============================================================================
# SECTION 11: CHALLENGE VCS & POMODORO TASKS (PERSISTENT PUBLIC TASK LIST)
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

        cfg = await db.get_challenge_vc(after.channel.id)
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
        await db.set_challenge_vc(channel.id, interaction.guild.id, ctype, grace_seconds)
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


class TaskActionModal(discord.ui.Modal):
    task_id_input = discord.ui.TextInput(label="Task ID (or leave blank for #1)", style=discord.TextStyle.short, placeholder="e.g., 1", required=False, max_length=10)

    def __init__(self, action: str, owner_id: int, source_message: discord.Message, page: int = 0):
        title_map = {"complete": "Complete a Task", "delete": "Delete a Task"}
        super().__init__(title=title_map.get(action, "Manage Task"))
        self.action = action
        self.owner_id = owner_id
        self.source_message = source_message
        self.page = page

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Only the owner of this task board can edit these tasks!", ephemeral=True)

        tasks_rows = await db.get_user_tasks(self.owner_id)
        if not tasks_rows:
            return await interaction.response.send_message("✨ You don't have any tasks in your list.", ephemeral=True)

        raw = self.task_id_input.value.strip().lstrip("#")
        target_db_id: Optional[int] = None

        if not raw:
            if self.action == "complete":
                pending = [t for t in tasks_rows if t["completed"] == 0]
                target_db_id = pending[0]["id"] if pending else tasks_rows[0]["id"]
            else:
                target_db_id = tasks_rows[0]["id"]
        else:
            try:
                num = int(raw)
            except ValueError:
                return await interaction.response.send_message("❌ Please enter a valid numeric Task ID.", ephemeral=True)

            if 1 <= num <= len(tasks_rows):
                target_db_id = tasks_rows[num - 1]["id"]
            else:
                for t in tasks_rows:
                    if t["id"] == num:
                        target_db_id = t["id"]
                        break

        if target_db_id is None:
            return await interaction.response.send_message(f"❌ Task `#{raw}` was not found.", ephemeral=True)

        if self.action == "complete":
            ok = await db.complete_user_task(self.owner_id, target_db_id)
            feedback = "✅ Task marked as **Completed**!" if ok else "ℹ️ That task is already completed."
        else:
            ok = await db.delete_user_task(self.owner_id, target_db_id)
            feedback = "🗑️ Task **Deleted**!" if ok else "❌ Could not delete that task."

        embed, clamped_page = await TaskListView.build_task_embed(interaction.user, self.owner_id, self.page)
        try:
            await self.source_message.edit(embed=embed, view=TaskListView(owner_id=self.owner_id, page=clamped_page))
        except Exception:
            pass
        await interaction.response.send_message(feedback, ephemeral=True)


class TaskListView(discord.ui.View):
    PER_PAGE = 8

    def __init__(self, owner_id: Optional[int] = None, page: int = 0):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.page = page

    @staticmethod
    def _extract_meta_from_message(message: Optional[discord.Message], fallback_owner: Optional[int], fallback_page: int) -> tuple[Optional[int], int]:
        if message and message.embeds:
            footer_txt = message.embeds[0].footer.text or ""
            m_owner = re.search(r"Owner:\s*(\d+)", footer_txt)
            m_page = re.search(r"Page\s*(\d+)/(\d+)", footer_txt)
            owner = int(m_owner.group(1)) if m_owner else fallback_owner
            page = (int(m_page.group(1)) - 1) if m_page else fallback_page
            return owner, max(0, page)
        return fallback_owner, max(0, fallback_page)

    @classmethod
    async def build_task_embed(cls, user: discord.abc.User, owner_id: int, page: int = 0) -> tuple[discord.Embed, int]:
        tasks_rows = await db.get_user_tasks(owner_id)
        total = len(tasks_rows)
        completed_cnt = sum(1 for t in tasks_rows if t["completed"] == 1)
        pending_cnt = total - completed_cnt

        max_pages = max(1, (total + cls.PER_PAGE - 1) // cls.PER_PAGE)
        page = max(0, min(page, max_pages - 1))
        chunk = tasks_rows[page * cls.PER_PAGE : (page + 1) * cls.PER_PAGE]

        if not chunk:
            desc = "✨ **No tasks yet!** Use `/task add` to add your study goals."
        else:
            lines = []
            for idx, t in enumerate(chunk, start=page * cls.PER_PAGE + 1):
                is_done = t["completed"] == 1
                icon = "✅" if is_done else "⬜"
                title_fmt = f"~~{t['title']}~~" if is_done else f"**{t['title']}**"
                lines.append(f"{icon} `#{idx}` • {title_fmt} *(Due: {t['due_date']})*")
            desc = "\n".join(lines)

        embed = discord.Embed(
            title=f"📝 Study Task Board • {user.display_name}",
            description=desc,
            color=discord.Color.from_str("#f4c2c2"),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(
            name="Progress Summary",
            value=f"• **Pending:** `{pending_cnt}`  |  • **Completed:** `{completed_cnt}`  |  • **Total:** `{total}`",
            inline=False,
        )
        embed.set_footer(text=f"Page {page + 1}/{max_pages} • Owner: {owner_id}")
        return embed, page

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.success, emoji="✅", custom_id="taskboard_complete", row=0)
    async def btn_complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, page = self._extract_meta_from_message(interaction.message, self.owner_id, self.page)
        if not owner_id or interaction.user.id != owner_id:
            return await interaction.response.send_message("❌ Only the owner of this task board can complete tasks on it!", ephemeral=True)
        await interaction.response.send_modal(TaskActionModal("complete", owner_id, interaction.message, page))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="taskboard_delete", row=0)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, page = self._extract_meta_from_message(interaction.message, self.owner_id, self.page)
        if not owner_id or interaction.user.id != owner_id:
            return await interaction.response.send_message("❌ Only the owner of this task board can delete tasks on it!", ephemeral=True)
        await interaction.response.send_modal(TaskActionModal("delete", owner_id, interaction.message, page))

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="taskboard_refresh", row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, page = self._extract_meta_from_message(interaction.message, self.owner_id, self.page)
        if not owner_id:
            return await interaction.response.send_message("❌ Could not identify task board owner.", ephemeral=True)
        target_user = (interaction.guild.get_member(owner_id) if interaction.guild else None) or interaction.user
        embed, clamped_page = await self.build_task_embed(target_user, owner_id, page)
        await interaction.response.edit_message(embed=embed, view=TaskListView(owner_id=owner_id, page=clamped_page))

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="taskboard_prev", row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, page = self._extract_meta_from_message(interaction.message, self.owner_id, self.page)
        if not owner_id:
            return await interaction.response.send_message("❌ Could not identify task board owner.", ephemeral=True)
        target_user = (interaction.guild.get_member(owner_id) if interaction.guild else None) or interaction.user
        embed, clamped_page = await self.build_task_embed(target_user, owner_id, max(0, page - 1))
        await interaction.response.edit_message(embed=embed, view=TaskListView(owner_id=owner_id, page=clamped_page))

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="taskboard_next", row=1)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, page = self._extract_meta_from_message(interaction.message, self.owner_id, self.page)
        if not owner_id:
            return await interaction.response.send_message("❌ Could not identify task board owner.", ephemeral=True)
        target_user = (interaction.guild.get_member(owner_id) if interaction.guild else None) or interaction.user
        embed, clamped_page = await self.build_task_embed(target_user, owner_id, page + 1)
        await interaction.response.edit_message(embed=embed, view=TaskListView(owner_id=owner_id, page=clamped_page))


class PomodoroTasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_pomodoros: dict[int, dict] = {}
        self.latest_task_boards: dict[int, discord.Message] = {}

    def cog_unload(self):
        for uid, session in list(self.active_pomodoros.items()):
            task: asyncio.Task = session.get("task")
            if task and not task.done():
                task.cancel()
        self.active_pomodoros.clear()

    async def _sync_latest_task_board(self, user: discord.abc.User):
        msg = self.latest_task_boards.get(user.id)
        if not msg:
            return
        try:
            _, cur_page = TaskListView._extract_meta_from_message(msg, user.id, 0)
            embed, clamped_page = await TaskListView.build_task_embed(user, user.id, cur_page)
            await msg.edit(embed=embed, view=TaskListView(owner_id=user.id, page=clamped_page))
        except Exception:
            self.latest_task_boards.pop(user.id, None)

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
    @app_commands.describe(action="Action: add, list, or clear", title="Task title (for add)", due="Optional due date/note (for add)")
    async def task_cmd(self, interaction: discord.Interaction, action: str, title: Optional[str] = None, due: Optional[str] = None):
        act = action.lower().strip()
        if act == "add":
            if not title:
                return await interaction.response.send_message("❌ Please provide a `title` when adding a task.", ephemeral=True)
            await db.add_user_task(interaction.user.id, title, due)
            await self._sync_latest_task_board(interaction.user)
            await interaction.response.send_message(f"✅ Added task: **{title}** (Due: `{due or 'No deadline'}`)", ephemeral=True)
        elif act == "list":
            embed, clamped_page = await TaskListView.build_task_embed(interaction.user, interaction.user.id, page=0)
            view = TaskListView(owner_id=interaction.user.id, page=clamped_page)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
            self.latest_task_boards[interaction.user.id] = await interaction.original_response()
        elif act == "clear":
            removed = await db.clear_completed_tasks(interaction.user.id)
            await self._sync_latest_task_board(interaction.user)
            await interaction.response.send_message(f"🧹 Cleared `{removed}` completed task(s).", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Invalid action! Use `add`, `list`, or `clear`.", ephemeral=True)


# ==============================================================================
# SECTION 12: COINS ECONOMY & TEMPORARY/RENTAL ROLE SHOP COG (cogs/economy_shop.py)
# ==============================================================================

class ShopPurchaseSelect(discord.ui.Select):
    def __init__(self, guild: Optional[discord.Guild] = None, items: Optional[list[dict]] = None):
        options = []
        if guild and items:
            for it in items[:25]:
                role = guild.get_role(it["role_id"])
                role_name = role.name if role else f"Role ({it['role_id']})"
                dur_sec = int(it.get("duration_seconds") or 0)
                dur_badge = f"Rental: {format_rental_duration(dur_sec)}" if dur_sec > 0 else "Permanent"
                desc = f"{it['price']:,} coins • {dur_badge}"
                if it.get("description"):
                    desc = f"{desc} — {it['description'][:45]}"
                options.append(
                    discord.SelectOption(
                        label=role_name[:100],
                        value=str(it["role_id"]),
                        description=desc[:100],
                        emoji="⏳" if dur_sec > 0 else "👑",
                    )
                )
        if not options:
            options = [
                discord.SelectOption(
                    label="No items available",
                    value="none",
                    description="Use /shop to refresh available roles",
                )
            ]
        super().__init__(
            placeholder="Select a role to buy / rent...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_role_purchase_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            val = self.values[0]
            if val == "none":
                return await interaction.followup.send("ℹ️ No roles are listed in the shop right now.", ephemeral=True)

            cog: Optional["EconomyShopCog"] = interaction.client.get_cog("EconomyShopCog")
            if not cog:
                return await interaction.followup.send("❌ Economy module is currently unavailable.", ephemeral=True)

            await cog.handle_role_purchase(interaction, int(val), already_deferred=True)
        except Exception as exc:
            await interaction.followup.send(f"❌ Purchase failed unexpectedly: `{exc}`", ephemeral=True)


class ShopBrowseView(discord.ui.View):
    def __init__(self, guild: Optional[discord.Guild] = None, items: Optional[list[dict]] = None):
        super().__init__(timeout=None)
        self.add_item(ShopPurchaseSelect(guild, items))


class EconomyShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rental_expiry_loop.start()

    def cog_unload(self):
        self.rental_expiry_loop.cancel()

    async def cleanup_expired_rentals(self):
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        expired_rows = await db.get_expired_rental_roles(now_ts)
        for rec in expired_rows:
            gid = rec["guild_id"]
            uid = rec["user_id"]
            rid = rec["role_id"]
            guild = self.bot.get_guild(gid)
            if guild:
                member = guild.get_member(uid)
                role = guild.get_role(rid)
                if member and role and role in member.roles:
                    try:
                        if guild.me and guild.me.guild_permissions.manage_roles and guild.me.top_role > role:
                            await member.remove_roles(role, reason="Temporary rental role expired")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
            await db.delete_rental_role_record(gid, uid, rid)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.cleanup_expired_rentals()

    @tasks.loop(minutes=2)
    async def rental_expiry_loop(self):
        await self.cleanup_expired_rentals()

    @rental_expiry_loop.before_loop
    async def before_rental_loop(self):
        await self.bot.wait_until_ready()

    @staticmethod
    def build_shop_embed(guild: discord.Guild, items: list[dict], wallet_balance: int) -> discord.Embed:
        embed = discord.Embed(
            title=f"🛍️ {guild.name} • Role Shop",
            description=f"**Your Wallet:** `{wallet_balance:,}` coins\nSelect a role from the dropdown below to buy or rent it!",
            color=discord.Color.from_str("#f4c2c2"),
        )
        if not items:
            embed.add_field(name="Shop Empty", value="Admins can add items using `/shop-add`.", inline=False)
            return embed

        lines = []
        for it in items:
            dur_sec = int(it.get("duration_seconds") or 0)
            dur_tag = f"⏳ Rental (`{format_rental_duration(dur_sec)}`)" if dur_sec > 0 else "👑 Permanent"
            desc_line = f"\n└ *{it['description']}*" if it.get("description") else ""
            lines.append(f"<@&{it['role_id']}> — **{it['price']:,} coins** • {dur_tag}{desc_line}")

        embed.add_field(name="Available Roles", value="\n".join(lines[:20]), inline=False)
        return embed

    async def handle_role_purchase(self, interaction: discord.Interaction, role_id: int, already_deferred: bool = False):
        if not already_deferred and not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        try:
            guild = interaction.guild
            if not guild:
                return await interaction.followup.send("❌ This action can only be used inside a server.", ephemeral=True)

            member: Optional[discord.Member] = interaction.user if isinstance(interaction.user, discord.Member) else guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.HTTPException:
                    member = None

            if member is None:
                return await interaction.followup.send("❌ Could not resolve your server member profile. Please try again.", ephemeral=True)

            role = guild.get_role(int(role_id))
            if not role:
                return await interaction.followup.send(
                    "❌ That role no longer exists in this server. No coins were deducted.",
                    ephemeral=True,
                )

            item = await db.get_shop_item_by_role(guild.id, role.id)
            if not item:
                return await interaction.followup.send(
                    "❌ That role is no longer listed in the shop. No coins were deducted.",
                    ephemeral=True,
                )

            bot_member = guild.me or guild.get_member(self.bot.user.id)
            if not bot_member or not bot_member.guild_permissions.manage_roles:
                return await interaction.followup.send(
                    "❌ I don't have the **Manage Roles** permission! Ask an admin to grant me **Manage Roles** first. No coins were deducted.",
                    ephemeral=True,
                )

            if role.is_default() or role.managed or bot_member.top_role <= role:
                return await interaction.followup.send(
                    f"❌ I cannot assign {role.mention} because my highest role (**{bot_member.top_role.name}**) is below or equal to **{role.name}**!\n"
                    f"👉 Ask an admin to go to **Server Settings → Roles** and drag my role **above** {role.mention}. No coins were deducted.",
                    ephemeral=True,
                )

            duration_seconds = int(item.get("duration_seconds") or 0)
            if duration_seconds == 0 and role in member.roles:
                return await interaction.followup.send(
                    f"ℹ️ You already own the permanent role {role.mention}! No coins were deducted.",
                    ephemeral=True,
                )

            price = int(item["price"])
            wallet = await db.get_wallet(guild.id, member.id)
            current_bal = int(wallet.get("balance", 0))
            if current_bal < price:
                return await interaction.followup.send(
                    f"❌ Insufficient coins! You need **{price:,}** coins for {role.mention}, but you currently have **{current_bal:,}** coins.",
                    ephemeral=True,
                )

            # Assign the Discord role FIRST before deducting any coins
            if role not in member.roles:
                try:
                    await member.add_roles(role, reason="Role Shop Purchase")
                except discord.Forbidden:
                    return await interaction.followup.send(
                        f"❌ Discord rejected assigning {role.mention} due to role hierarchy/permissions. No coins were deducted.",
                        ephemeral=True,
                    )
                except discord.HTTPException as http_err:
                    return await interaction.followup.send(
                        f"❌ Discord API error while assigning {role.mention}: `{http_err}`. No coins were deducted.",
                        ephemeral=True,
                    )

            # Role assignment succeeded -> now atomically deduct coins & save rental timer
            ok, msg, new_bal, expires_at = await db.purchase_shop_role_atomic(guild.id, member.id, role.id)
            if not ok:
                return await interaction.followup.send(f"❌ {msg}", ephemeral=True)

            # Refresh the shop message's displayed wallet balance cleanly if triggered from /shop dropdown
            if interaction.message:
                try:
                    refreshed_items = await db.get_shop_items(guild.id)
                    refreshed_embed = self.build_shop_embed(guild, refreshed_items, new_bal)
                    await interaction.message.edit(embed=refreshed_embed, view=ShopBrowseView(guild, refreshed_items))
                except Exception:
                    pass

            if expires_at:
                exp_unix = int(expires_at)
                duration_info = f"⏳ **Rental Active Until:** <t:{exp_unix}:f> (<t:{exp_unix}:R>)\n*(Buying again before expiry extends your timer!)*"
            else:
                duration_info = "👑 **Ownership:** Permanent"

            embed = discord.Embed(
                title="🛍️ Role Purchased!",
                description=(
                    f"You unlocked {role.mention}!\n\n"
                    f"• {duration_info}\n"
                    f"• **Remaining Balance:** `{new_bal:,}` coins"
                ),
                color=discord.Color.gold(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"❌ Something went wrong during purchase: `{exc}`", ephemeral=True)

    @app_commands.command(name="balance", description="Check your coin wallet and active rental roles.")
    async def balance_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        wallet = await db.get_wallet(interaction.guild.id, target.id)
        rentals = await db.get_user_active_rentals(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"🪙 Wallet & Rentals • {target.display_name}",
            description=f"**Current Balance:** `{int(wallet.get('balance', 0)):,}` coins",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if rentals:
            lines = []
            for r in rentals:
                exp_unix = int(r["expires_at"])
                lines.append(f"• <@&{r['role_id']}> — expires <t:{exp_unix}:R> (<t:{exp_unix}:t>)")
            embed.add_field(name="⏳ Active Rental Roles", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="⏳ Active Rental Roles", value="No active timed rental roles.", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily coin reward (resets at 00:00 IST).")
    async def daily_cmd(self, interaction: discord.Interaction):
        claimed, bal = await db.claim_daily_coins(interaction.guild.id, interaction.user.id, reward=100)
        if not claimed:
            return await interaction.response.send_message(
                f"⏳ You already claimed today's daily coins! Come back after **00:00 IST**.\n**Current Balance:** `{bal:,}` coins",
                ephemeral=True,
            )
        embed = discord.Embed(
            title="🎁 Daily Coins Claimed!",
            description=f"You received **+100 coins**!\n**New Balance:** `{bal:,}` coins",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pay", description="Send coins from your wallet to another server member.")
    @app_commands.describe(member="Member to send coins to", amount="Positive number of coins to transfer")
    async def pay_cmd(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 100_000_000]):
        if member.bot:
            return await interaction.response.send_message("❌ You cannot send coins to a bot.", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("❌ You cannot pay yourself!", ephemeral=True)

        ok, msg, new_sender_bal, new_recipient_bal = await db.transfer_coins_atomic(
            interaction.guild.id,
            interaction.user.id,
            member.id,
            amount,
        )
        if not ok:
            return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

        embed = discord.Embed(
            title="💸 Coin Transfer Complete",
            description=(
                f"{interaction.user.mention} sent **{amount:,} coins** to {member.mention}!\n\n"
                f"• **Your New Balance:** `{new_sender_bal:,}` coins\n"
                f"• **{member.display_name}'s Balance:** `{new_recipient_bal:,}` coins"
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await interaction.response.send_message(embed=embed)

        audit_cog: Optional[AuditLogsCog] = interaction.client.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_coin_transfer(interaction.guild, interaction.user, member, amount, new_sender_bal, new_recipient_bal)

    @app_commands.command(name="shop", description="Browse and purchase permanent or temporary/rental roles with coins.")
    async def shop_cmd(self, interaction: discord.Interaction):
        items = await db.get_shop_items(interaction.guild.id)
        wallet = await db.get_wallet(interaction.guild.id, interaction.user.id)
        bal = int(wallet.get("balance", 0))

        embed = self.build_shop_embed(interaction.guild, items, bal)
        if not items:
            return await interaction.response.send_message(embed=embed)

        await interaction.response.send_message(embed=embed, view=ShopBrowseView(interaction.guild, items))

    @app_commands.command(name="buy", description="Purchase or rent a role directly from the server shop.")
    @app_commands.describe(role="The shop role you want to buy or rent")
    async def buy_cmd(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        await self.handle_role_purchase(interaction, role.id, already_deferred=True)

    @app_commands.command(name="shop-add", description="Admin: Add or update a permanent or rental role in the shop.")
    @app_commands.describe(
        role="Role to sell or rent",
        price="Price in coins",
        duration="Duration e.g. 'permanent', '24h', '7d', '30d' (default: permanent)",
        description="Optional short description",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def shop_add_cmd(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        price: app_commands.Range[int, 0, 100_000_000],
        duration: str = "permanent",
        description: str = "",
    ):
        if role.is_default() or role.managed:
            return await interaction.response.send_message("❌ You cannot add `@everyone` or an integration-managed role.", ephemeral=True)
        dur_seconds = parse_rental_duration_input(duration)
        if dur_seconds is None:
            return await interaction.response.send_message(
                "❌ Invalid duration! Use `permanent`, `0`, `12h`, `24h`, `7d`, `30d`, etc.",
                ephemeral=True,
            )

        await db.upsert_shop_role_item(interaction.guild.id, role.id, price, description.strip(), dur_seconds)
        dur_label = "Permanent" if dur_seconds == 0 else f"Rental ({format_rental_duration(dur_seconds)})"
        await interaction.response.send_message(
            f"✅ Listed {role.mention} in `/shop` for **{price:,} coins** • **{dur_label}**.",
            ephemeral=True,
        )

    @app_commands.command(name="shop-remove", description="Admin: Remove a role from the shop.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def shop_remove_cmd(self, interaction: discord.Interaction, role: discord.Role):
        removed = await db.remove_shop_role_item(interaction.guild.id, role.id)
        if removed:
            await interaction.response.send_message(f"🗑️ Removed {role.mention} from the shop.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ That role was not listed in the shop.", ephemeral=True)

    @app_commands.command(name="eco-grant", description="Admin: Grant or deduct coins for a member.")
    @app_commands.describe(member="Target member", amount="Coins to add (or negative to deduct)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_grant_cmd(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        new_bal = await db.add_coins(interaction.guild.id, member.id, amount)
        verb = "Granted" if amount >= 0 else "Deducted"
        await interaction.response.send_message(
            f"🪙 {verb} **{abs(amount):,} coins** for {member.mention}. New balance: `{new_bal:,}` coins.",
            ephemeral=True,
        )


# ==============================================================================
# SECTION 13: FOCUS DIARIES FORUM REMINDER & QUICK-JOURNALING COG
# ==============================================================================

DIARY_PROMPTS = [
    "What is one study milestone you are proud of today, and what is your #1 priority tomorrow?",
    "Rate your focus today from 1–10. What helped you lock in, and what distracted you?",
    "Summarize the most important concept you learned or revised today in 2 sentences.",
    "How was your energy and study environment today? Note one small adjustment for tomorrow.",
    "Write a quick check-in for your future self: what went well today, and what will you tackle first next session?",
]

REMINDER_TIME_CHOICES = [
    ("20:00 IST", "8:00 PM IST — Evening wind-down check-in"),
    ("21:00 IST", "9:00 PM IST — Night study review"),
    ("22:00 IST", "10:00 PM IST — Late-evening journal prompt"),
    ("23:00 IST", "11:00 PM IST — End-of-day reflection before midnight"),
]


class DiaryQuickEntryModal(discord.ui.Modal, title="✍️ Quick Focus Diary Entry"):
    accomplishments = discord.ui.TextInput(
        label="What did you accomplish / study today?",
        style=discord.TextStyle.paragraph,
        placeholder="Completed 3 Pomodoro blocks on Organic Chemistry & revised flashcards...",
        required=True,
        max_length=1000,
    )
    tomorrow_plan = discord.ui.TextInput(
        label="Top priority for tomorrow & mood (1-10)",
        style=discord.TextStyle.paragraph,
        placeholder="Mood: 8/10 • Tomorrow: Solve 25 practice problems first thing.",
        required=True,
        max_length=500,
    )

    def __init__(self, thread_id: int, owner_id: int):
        super().__init__()
        self.thread_id = thread_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Only the owner of this diary thread can post entries here!", ephemeral=True)

        cog: Optional["FocusDiariesCog"] = interaction.client.get_cog("FocusDiariesCog")
        if not cog:
            return await interaction.response.send_message("❌ Focus Diaries module unavailable.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        thread = interaction.guild.get_thread(self.thread_id)
        if not thread:
            try:
                fetched = await interaction.guild.fetch_channel(self.thread_id)
                if isinstance(fetched, discord.Thread):
                    thread = fetched
            except Exception:
                thread = None

        if not thread:
            return await interaction.followup.send("❌ Could not locate your diary thread.", ephemeral=True)

        now_ist = db.get_ist_now()
        entry_embed = discord.Embed(
            title=f"📔 Daily Reflection • {now_ist.strftime('%d %b %Y')} (IST)",
            color=discord.Color.from_str("#f4c2c2"),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        entry_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        entry_embed.add_field(name="✅ Today's Progress", value=self.accomplishments.value.strip(), inline=False)
        entry_embed.add_field(name="🎯 Tomorrow's Focus & Mood", value=self.tomorrow_plan.value.strip(), inline=False)

        await thread.send(embed=entry_embed)
        reward_msg = await cog.record_diary_activity(interaction.guild, thread, interaction.user)
        await interaction.followup.send(f"✨ Journal entry posted! {reward_msg}", ephemeral=True)


class DiaryReminderTimeSelect(discord.ui.Select):
    def __init__(self, thread_id: int, owner_id: int, current_time: str = "22:00"):
        self.thread_id = thread_id
        self.owner_id = owner_id
        options = []
        for label_val, desc in REMINDER_TIME_CHOICES:
            raw_hhmm = label_val.split()[0]
            options.append(
                discord.SelectOption(
                    label=label_val,
                    value=raw_hhmm,
                    description=desc,
                    emoji="⏰",
                    default=(raw_hhmm == current_time),
                )
            )
        super().__init__(
            placeholder="⏰ Reminder Time (IST)...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="diary_reminder_time_select",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        meta = await db.get_diary_thread(self.thread_id)
        if not meta or meta["owner_id"] != interaction.user.id:
            return await interaction.response.send_message("❌ Only the owner of this diary thread can change its reminder time!", ephemeral=True)

        chosen_hhmm = self.values[0]
        await db.update_diary_thread(self.thread_id, reminder_time_ist=chosen_hhmm, reminders_enabled=1, unanswered_pings=0)
        await interaction.response.send_message(
            f"⏰ Daily Focus Diary reminder updated to **{chosen_hhmm} IST** (and reminders are **ON**)!",
            ephemeral=True,
        )


class DiaryControlView(discord.ui.View):
    """
    Persistent interactive controls attached to Focus Diary welcome cards & reminder pings:
    - Row 0: [Write Entry] • [Toggle Reminders]
    - Row 1: [Reminder Time] select menu (`20:00 IST`, `21:00 IST`, `22:00 IST`, `23:00 IST`)
    """

    def __init__(self, thread_id: int = 0, owner_id: int = 0, current_time: str = "22:00"):
        super().__init__(timeout=None)
        self.thread_id = thread_id
        self.owner_id = owner_id
        self.add_item(DiaryReminderTimeSelect(thread_id, owner_id, current_time))

    async def _resolve_thread_and_meta(self, interaction: discord.Interaction) -> Optional[tuple[discord.Thread, dict]]:
        tid = self.thread_id or (interaction.channel.id if isinstance(interaction.channel, discord.Thread) else 0)
        if not tid and interaction.message and interaction.message.embeds:
            footer_txt = interaction.message.embeds[0].footer.text or ""
            m_tid = re.search(r"Thread:\s*(\d+)", footer_txt)
            if m_tid:
                tid = int(m_tid.group(1))
        if not tid:
            await interaction.response.send_message("❌ Could not identify this diary thread.", ephemeral=True)
            return None
        meta = await db.get_diary_thread(tid)
        if not meta:
            await interaction.response.send_message("❌ This thread is not registered as a Focus Diary.", ephemeral=True)
            return None
        if meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ Only the owner of this Focus Diary thread can use these controls!", ephemeral=True)
            return None
        thread = interaction.guild.get_thread(tid) if interaction.guild else None
        if not thread and isinstance(interaction.channel, discord.Thread):
            thread = interaction.channel
        if not thread:
            await interaction.response.send_message("❌ Diary thread could not be accessed.", ephemeral=True)
            return None
        return thread, meta

    @discord.ui.button(label="Write Entry", style=discord.ButtonStyle.primary, emoji="✍️", custom_id="diary_write_entry_btn", row=0)
    async def btn_write_entry(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await self._resolve_thread_and_meta(interaction)
        if not res:
            return
        thread, meta = res
        await interaction.response.send_modal(DiaryQuickEntryModal(thread.id, meta["owner_id"]))

    @discord.ui.button(label="Toggle Reminders", style=discord.ButtonStyle.secondary, emoji="🔔", custom_id="diary_toggle_reminders_btn", row=0)
    async def btn_toggle_reminders(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await self._resolve_thread_and_meta(interaction)
        if not res:
            return
        thread, meta = res
        new_state = 0 if meta.get("reminders_enabled", 1) == 1 else 1
        await db.update_diary_thread(thread.id, reminders_enabled=new_state, unanswered_pings=0)
        status_label = f"**ON** (`{meta.get('reminder_time_ist', '22:00')} IST`)" if new_state == 1 else "**OFF** (Paused)"
        await interaction.response.send_message(f"🔔 Daily Focus Diary reminders are now {status_label}.", ephemeral=True)


class FocusDiariesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.diary_reminder_loop.start()

    def cog_unload(self):
        self.diary_reminder_loop.cancel()

    @staticmethod
    def _previous_ist_day_key(day_key: str) -> str:
        dt = datetime.datetime.strptime(day_key, "%Y-%m-%d")
        return (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    async def record_diary_activity(self, guild: discord.Guild, thread: discord.Thread, user: discord.abc.User) -> str:
        """
        Updates journal streak, resets unanswered reminder pings, and awards daily
        journaling coins once per IST day.
        """
        cfg = await db.get_diary_guild_config(guild.id)
        default_time = cfg["default_reminder_time"] if cfg else "22:00"
        coin_reward = int(cfg["coin_reward"]) if cfg else 25

        meta = await db.get_diary_thread(thread.id)
        if not meta:
            meta = await db.upsert_diary_thread(thread.id, guild.id, user.id, 1, default_time)

        today_key, _, _ = db.get_ist_period_keys()
        yesterday_key = self._previous_ist_day_key(today_key)

        last_entry = meta.get("last_entry_date")
        cur_streak = int(meta.get("journal_streak") or 0)
        best_streak = int(meta.get("best_journal_streak") or 0)

        if last_entry != today_key:
            if last_entry == yesterday_key:
                cur_streak += 1
            else:
                cur_streak = 1
            if cur_streak > best_streak:
                best_streak = cur_streak

        reward_note = f"Journal streak: **{cur_streak}d**!"
        last_reward = meta.get("last_reward_date")
        if last_reward != today_key and coin_reward > 0:
            new_bal = await db.add_coins(guild.id, user.id, coin_reward)
            reward_note = f"+**{coin_reward} coins** earned (Balance: `{new_bal:,}`) • Journal streak: **{cur_streak}d**!"
            last_reward = today_key

        await db.update_diary_thread(
            thread.id,
            last_entry_date=today_key,
            unanswered_pings=0,
            journal_streak=cur_streak,
            best_journal_streak=best_streak,
            last_reward_date=last_reward,
        )
        return reward_note

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        try:
            if not thread.guild or not isinstance(thread.parent, discord.ForumChannel):
                return
            cfg = await db.get_diary_guild_config(thread.guild.id)
            if not cfg or cfg.get("forum_channel_id") != thread.parent.id:
                return

            owner_id = thread.owner_id
            if not owner_id:
                return
            owner = thread.guild.get_member(owner_id)
            if owner and owner.bot:
                return

            default_time = cfg.get("default_reminder_time") or "22:00"
            coin_reward = int(cfg.get("coin_reward") or 25)
            await db.upsert_diary_thread(thread.id, thread.guild.id, owner_id, 1, default_time)

            await asyncio.sleep(1.5)
            welcome_embed = discord.Embed(
                title="📔 Welcome to Your Focus Diary!",
                description=(
                    f"Hey <@{owner_id}>! Your personal study journal is active.\n\n"
                    f"• **Daily Reminder:** `{default_time} IST` (adjust anytime below)\n"
                    f"• **Daily Journaling Bonus:** `+{coin_reward} coins` on your first entry each IST day\n"
                    f"• **Smart Auto-Pause:** Pauses automatically after 3 unanswered reminders so you're never spammed.\n\n"
                    f"Click **Write Entry** below or simply post a message in this thread anytime!"
                ),
                color=discord.Color.from_str("#f4c2c2"),
            )
            welcome_embed.set_footer(text=f"Thread: {thread.id} • Owner: {owner_id}")
            view = DiaryControlView(thread_id=thread.id, owner_id=owner_id, current_time=default_time)
            await thread.send(content=f"<@{owner_id}>", embed=welcome_embed, view=view)
        except Exception as exc:
            print(f"[DIARY ERROR] on_thread_create: {exc}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.channel, discord.Thread):
            return

        thread = message.channel
        if not isinstance(thread.parent, discord.ForumChannel):
            return

        cfg = await db.get_diary_guild_config(message.guild.id)
        if not cfg or cfg.get("forum_channel_id") != thread.parent.id:
            return

        meta = await db.get_diary_thread(thread.id)
        if not meta:
            if thread.owner_id == message.author.id:
                meta = await db.upsert_diary_thread(thread.id, message.guild.id, message.author.id, 1, cfg.get("default_reminder_time") or "22:00")
            else:
                return

        if message.author.id != meta["owner_id"]:
            return

        reward_msg = await self.record_diary_activity(message.guild, thread, message.author)
        try:
            await message.add_reaction("📔")
        except Exception:
            pass
        if "+**" in reward_msg:
            try:
                await thread.send(f"✨ {message.author.mention} {reward_msg}", delete_after=15)
            except Exception:
                pass

    @tasks.loop(minutes=1)
    async def diary_reminder_loop(self):
        now_ist = db.get_ist_now()
        current_hhmm = now_ist.strftime("%H:%M")
        today_key, _, _ = db.get_ist_period_keys(now_ist)

        threads = await db.get_all_enabled_diary_threads()
        for t_rec in threads:
            try:
                if (t_rec.get("reminder_time_ist") or "22:00") != current_hhmm:
                    continue
                if t_rec.get("last_entry_date") == today_key:
                    continue
                if t_rec.get("last_ping_date") == today_key:
                    continue

                guild = self.bot.get_guild(t_rec["guild_id"])
                if not guild:
                    continue
                thread = guild.get_thread(t_rec["thread_id"])
                if not thread:
                    try:
                        fetched = await guild.fetch_channel(t_rec["thread_id"])
                        if isinstance(fetched, discord.Thread):
                            thread = fetched
                    except Exception:
                        thread = None

                if not thread:
                    await db.update_diary_thread(t_rec["thread_id"], reminders_enabled=0)
                    continue

                if thread.archived:
                    try:
                        await thread.edit(archived=False)
                    except Exception:
                        pass

                unanswered = int(t_rec.get("unanswered_pings") or 0) + 1
                owner_id = t_rec["owner_id"]
                prompt = random.choice(DIARY_PROMPTS)

                if unanswered >= 3:
                    await db.update_diary_thread(
                        thread.id,
                        reminders_enabled=0,
                        unanswered_pings=unanswered,
                        last_ping_date=today_key,
                    )
                    pause_embed = discord.Embed(
                        title="💤 Focus Diary Reminders Auto-Paused",
                        description=(
                            f"<@{owner_id}>, you haven't posted in your Focus Diary for the last 3 reminders, so daily pings have been **paused** to avoid clutter.\n\n"
                            f"Whenever you're ready to resume, click **Write Entry** or **Toggle Reminders** below!"
                        ),
                        color=discord.Color.orange(),
                    )
                    pause_embed.set_footer(text=f"Thread: {thread.id} • Owner: {owner_id}")
                    view = DiaryControlView(thread_id=thread.id, owner_id=owner_id, current_time=t_rec.get("reminder_time_ist") or "22:00")
                    await thread.send(content=f"<@{owner_id}>", embed=pause_embed, view=view)
                else:
                    await db.update_diary_thread(
                        thread.id,
                        unanswered_pings=unanswered,
                        last_ping_date=today_key,
                    )
                    rem_embed = discord.Embed(
                        title=f"🌙 Daily Focus Diary Check-In ({current_hhmm} IST)",
                        description=(
                            f"Time to log today's progress, <@{owner_id}>!\n\n"
                            f"**Today's Prompt:** *{prompt}*\n\n"
                            f"Click **Write Entry** below for a quick structured log (or just reply directly in this thread)."
                        ),
                        color=discord.Color.from_str("#f4c2c2"),
                    )
                    rem_embed.set_footer(text=f"Thread: {thread.id} • Owner: {owner_id} • Ping {unanswered}/3")
                    view = DiaryControlView(thread_id=thread.id, owner_id=owner_id, current_time=t_rec.get("reminder_time_ist") or "22:00")
                    await thread.send(content=f"<@{owner_id}>", embed=rem_embed, view=view)
            except Exception as exc:
                print(f"[DIARY LOOP ERROR] thread {t_rec.get('thread_id')}: {exc}")

    @diary_reminder_loop.before_loop
    async def before_diary_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="diary-setup", description="Admin: Configure the Focus Diaries Forum channel, default IST reminder time & coin reward.")
    @app_commands.describe(
        forum_channel="Forum channel where members create their Focus Diary threads",
        default_time="Default IST reminder time (20:00, 21:00, 22:00, or 23:00)",
        coin_reward="Coins awarded once per IST day for journaling (default: 25)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def diary_setup_cmd(
        self,
        interaction: discord.Interaction,
        forum_channel: discord.ForumChannel,
        default_time: str = "22:00",
        coin_reward: app_commands.Range[int, 0, 10000] = 25,
    ):
        clean_time = default_time.strip().split()[0]
        if clean_time not in ("20:00", "21:00", "22:00", "23:00"):
            return await interaction.response.send_message(
                "❌ `default_time` must be one of `20:00`, `21:00`, `22:00`, or `23:00` (IST).",
                ephemeral=True,
            )

        await db.set_diary_guild_config(interaction.guild.id, forum_channel.id, clean_time, coin_reward)
        embed = discord.Embed(
            title="📔 Focus Diaries Configured!",
            description=(
                f"• **Forum Channel:** {forum_channel.mention}\n"
                f"• **Default Reminder Time:** `{clean_time} IST`\n"
                f"• **Daily Journaling Reward:** `+{coin_reward} coins`\n\n"
                f"New threads created in {forum_channel.mention} will automatically receive the interactive journal card with **Write Entry**, **Toggle Reminders**, and the **Reminder Time** selector!"
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="diary", description="Open your Focus Diary controls inside your diary thread (or register an existing thread).")
    async def diary_cmd(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread) or not isinstance(interaction.channel.parent, discord.ForumChannel):
            cfg = await db.get_diary_guild_config(interaction.guild.id)
            forum_hint = f"<#{cfg['forum_channel_id']}>" if cfg and cfg.get("forum_channel_id") else "the configured Focus Diaries forum"
            return await interaction.response.send_message(
                f"ℹ️ Run `/diary` inside your thread in {forum_hint} to open your journal controls!",
                ephemeral=True,
            )

        cfg = await db.get_diary_guild_config(interaction.guild.id)
        if not cfg or cfg.get("forum_channel_id") != interaction.channel.parent.id:
            return await interaction.response.send_message("❌ This forum channel is not configured as the Focus Diaries forum.", ephemeral=True)

        meta = await db.get_diary_thread(interaction.channel.id)
        if not meta:
            owner_id = interaction.channel.owner_id or interaction.user.id
            meta = await db.upsert_diary_thread(
                interaction.channel.id,
                interaction.guild.id,
                owner_id,
                1,
                cfg.get("default_reminder_time") or "22:00",
            )

        if meta["owner_id"] != interaction.user.id:
            return await interaction.response.send_message("❌ Only the owner of this Focus Diary thread can manage its settings.", ephemeral=True)

        rem_status = "ON" if meta.get("reminders_enabled", 1) == 1 else "OFF (Paused)"
        cur_time = meta.get("reminder_time_ist") or "22:00"
        embed = discord.Embed(
            title="📔 Focus Diary Control Panel",
            description=(
                f"• **Reminders:** `{rem_status}` at `{cur_time} IST`\n"
                f"• **Current Journal Streak:** `{meta.get('journal_streak', 0)}d` (Best: `{meta.get('best_journal_streak', 0)}d`)\n"
                f"• **Last Entry Date (IST):** `{meta.get('last_entry_date') or 'None yet'}`"
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        embed.set_footer(text=f"Thread: {interaction.channel.id} • Owner: {interaction.user.id}")
        view = DiaryControlView(thread_id=interaction.channel.id, owner_id=interaction.user.id, current_time=cur_time)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ==============================================================================
# SECTION 14: HELP COMMAND COG (cogs/help.py)
# ==============================================================================

class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Moderation", emoji="🛡️", value="mod"),
            discord.SelectOption(label="Welcome & Autorole", emoji="🌸", value="welcome"),
            discord.SelectOption(label="VC Tracking", emoji="⏱️", value="vctracker"),
            discord.SelectOption(label="Economy & Role Shop", emoji="🪙", value="economy"),
            discord.SelectOption(label="Focus Diaries", emoji="📔", value="diaries"),
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
            embed.title = "🌸 Welcome & Autorole"
            embed.description = "• `/welcome-setup` — Customize welcome embeds & test preview\n• `/autorole-setup` — Automatically assign roles on member join"
        elif val == "vctracker":
            embed.title = "⏱️ VC Tracking (Exclusive Buckets)"
            embed.description = (
                "• `/stats [member]` — Interactive Today/Weekly/Monthly/All-Time switcher & Cam/SS/Plain buckets\n"
                "• `/leaderboard` — Filter by All VC, Plain VC, Cam Only, SS Only, Both, or Any Cam/SS\n"
                "• `/challenge-stats` — Staff lookup for mutually exclusive hours in an IST date/time window\n"
                "• `/vc-settings` — Untracked VCs, bucket hour adjustments & leaderboard user exclusions"
            )
        elif val == "economy":
            embed.title = "🪙 Coins Economy & Rental Role Shop"
            embed.description = (
                "• `/balance [member]` — View coin wallet & active timed rental roles\n"
                "• `/daily` — Claim daily coins (resets 00:00 IST)\n"
                "• `/pay @member amount` — Send coins to another member\n"
                "• `/shop` — Buy permanent or temporary/rental roles\n"
                "• `/shop-add`, `/shop-remove`, `/eco-grant` — Admin shop & coin controls"
            )
        elif val == "diaries":
            embed.title = "📔 Focus Diaries & Quick-Journaling"
            embed.description = (
                "• `/diary-setup` — Admin: Set Forum channel, default IST reminder time & coin reward\n"
                "• `/diary` — Open interactive **Write Entry**, **Toggle Reminders**, & **Reminder Time** (`20:00`–`23:00 IST`) controls"
            )
        elif val == "streaks_audit":
            embed.title = "🔥 Streaks & Audit Logs"
            embed.description = "• `/streak [member]` — View IST daily streak & goal progress\n• `/streak-config` — Set daily minimum study minutes (00:00 IST reset)\n• `/auditlog-setup` — Configure centralized mod, economy & challenge audit channel"
        elif val == "tempvoice":
            embed.title = "🎙️ TempVoice"
            embed.description = "• `/tempvoice-setup` — Interactive room controls (`Name`, `Limit`, `Lock / Unlock`, `Privacy`, `Chat`, `Trust`, `Untrust`, `Kick`, `Region`, `Claim`, `Transfer`, `Delete`)"
        elif val == "study":
            embed.title = "🍅 Study & Tasks"
            embed.description = "• `/pomodoro start`, `/pomodoro stop`, `/task`, `/challenge-vc-setup`"
        elif val == "utility":
            embed.title = "⚙️ Utility, AFK & Presence"
            embed.description = "• `/purge`, `/afk`, `/set-status`"
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
# SECTION 15: MAIN BOT INITIALIZATION (main.py)
# ==============================================================================

class ModWelcomeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await db.connect()

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
        await self.add_cog(EconomyShopCog(self))
        await self.add_cog(FocusDiariesCog(self))
        await self.add_cog(HelpCog(self))

        self.add_view(TempVoiceControlView())
        self.add_view(WelcomeDashboardView())
        self.add_view(TaskListView())
        self.add_view(DiaryControlView())
        self.add_view(ShopBrowseView())

        self.tree.on_error = self.on_app_command_error
        synced = await self.tree.sync()
        print(f"[Slash Commands] Synced {len(synced)} command(s) globally.")

    async def close(self):
        await db.close()
        await super().close()

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
        print(f"Storage Backend: {'Cloud PostgreSQL' if db.use_postgres else 'Local SQLite Fallback'}")
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
