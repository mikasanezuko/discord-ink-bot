"""
================================================================================
DISCORD MODERATION & MIMU-STYLE WELCOME BOT (discord.py 2.x + Flask)
================================================================================
Designed for Render / Replit 24/7 hosting with SQLite persistence, interactive
Discord UI Modals, Buttons, Select menus, native timeouts, and Mimu-style welcome
embed customization.

SETUP INSTRUCTIONS:
1. Ensure `discord.py>=2.3.2` and `flask>=3.0.0` are installed.
2. Enable "SERVER MEMBERS INTENT" and "MESSAGE CONTENT INTENT" in Discord Developer Portal.
3. Store your token in environment variables under `DISCORD_TOKEN`.
================================================================================
"""

import os
import re
import json
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
        """Creates required tables for all bot subsystems."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Moderation logs
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
            # Mimu-style welcome configurations
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
            # VC Study Time tracking (IST resets)
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
            # Untracked voice channels
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vc_untracked_channels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )
                """
            )
            # TempVoice per-guild config
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
            # Active temporary voice channels
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
            # Server autoroles
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS server_autoroles (
                    guild_id INTEGER PRIMARY KEY,
                    role_ids TEXT DEFAULT '[]'
                )
                """
            )
            # Challenge VCs
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
            # User personal tasks
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
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
                    guild_id, user_id, moderator_id, action_type,
                    reason, internal_note or "None", duration or "N/A", timestamp,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_user_logs(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
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

    # --- VC Study Time DB Methods ---
    @staticmethod
    def get_ist_period_keys() -> tuple[str, str, str]:
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.datetime.now(ist_tz)
        iso_year, iso_week, _ = now_ist.isocalendar()
        day_key = now_ist.strftime("%Y-%m-%d")
        week_key = f"{iso_year}-W{iso_week:02d}"
        month_key = now_ist.strftime("%Y-%m")
        return day_key, week_key, month_key

    def _sync_period_resets(self, conn: sqlite3.Connection, guild_id: int, user_id: int) -> sqlite3.Row:
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

    def adjust_vc_seconds(self, guild_id: int, user_id: int, metric: str, action: str, seconds: int):
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
            conn.commit()

    def get_user_vc_stats(self, guild_id: int, user_id: int) -> dict:
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
        day_key, week_key, month_key = self.get_ist_period_keys()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM vc_study_stats WHERE guild_id = ?",
                (guild_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

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
                cursor.execute(
                    "INSERT INTO vc_untracked_channels (guild_id, channel_id) VALUES (?, ?)",
                    (guild_id, cid),
                )
            conn.commit()

    # --- TempVoice DB Methods ---
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
                """
                INSERT OR REPLACE INTO tempvoice_channels (
                    channel_id, guild_id, owner_id, privacy_mode, chat_enabled
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (channel_id, guild_id, owner_id, privacy_mode, chat_enabled),
            )
            conn.commit()

    def get_temp_channel(self, channel_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tempvoice_channels WHERE channel_id = ?", (channel_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_temp_channel(self, channel_id: int, **kwargs):
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [channel_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE tempvoice_channels SET {columns} WHERE channel_id = ?", values)
            conn.commit()

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

    # --- Autorole DB Methods ---
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
            cursor.execute(
                "INSERT OR REPLACE INTO server_autoroles (guild_id, role_ids) VALUES (?, ?)",
                (guild_id, json.dumps(list(set(role_ids)))),
            )
            conn.commit()

    # --- Challenge VC DB Methods ---
    def get_challenge_vc(self, channel_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM challenge_vcs WHERE channel_id = ?", (channel_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_challenge_vc(self, channel_id: int, guild_id: int, challenge_type: str, grace_seconds: int):
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM challenge_vcs WHERE channel_id = ?", (channel_id,))
            conn.commit()

    # --- Task DB Methods ---
    def add_user_task(self, user_id: int, title: str, due_date: Optional[str]) -> int:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_tasks WHERE user_id = ? ORDER BY id DESC", (user_id,))
            return cursor.fetchall()

    def update_task_status(self, task_id: int, user_id: int, completed: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_tasks SET completed = ? WHERE id = ? AND user_id = ?",
                (completed, task_id, user_id),
            )
            conn.commit()

    def clear_user_tasks(self, user_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_tasks WHERE user_id = ? AND completed = 1", (user_id,))
            conn.commit()


db = DatabaseManager()


# ==============================================================================
# SECTION 3: MODERATION COG (cogs/moderation.py)
# ==============================================================================

class WarnModal(discord.ui.Modal, title="Issue Warning"):
    reason = discord.ui.TextInput(
        label="Reason for Warning",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., Disregarding channel topic / spamming",
        required=True,
        max_length=500,
    )
    internal_note = discord.ui.TextInput(
        label="Internal Mod Note (Optional)",
        style=discord.TextStyle.short,
        placeholder="e.g., User warned previously in modmail",
        required=False,
        max_length=200,
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.target_member = member

    async def on_submit(self, interaction: discord.Interaction):
        case_id = db.add_mod_log(
            guild_id=interaction.guild.id,
            user_id=self.target_member.id,
            moderator_id=interaction.user.id,
            action_type="WARN",
            reason=self.reason.value,
            internal_note=self.internal_note.value,
        )

        try:
            dm_embed = discord.Embed(
                title=f"⚠️ You received a warning in {interaction.guild.name}",
                description=f"**Reason:** {self.reason.value}",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            dm_embed.set_footer(text=f"Case ID: #{case_id}")
            await self.target_member.send(embed=dm_embed)
        except Exception:
            pass

        embed = discord.Embed(
            title=f"⚠️ Member Warned [Case #{case_id}]",
            description=f"**User:** {self.target_member.mention} (`{self.target_member.id}`)\n**Reason:** {self.reason.value}\n**Moderator:** {interaction.user.mention}",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if self.internal_note.value:
            embed.add_field(name="Internal Note", value=self.internal_note.value, inline=False)
        await interaction.response.send_message(embed=embed)


class MuteModal(discord.ui.Modal, title="Apply Timeout (Mute)"):
    duration_str = discord.ui.TextInput(
        label="Duration (e.g., 10m, 2h, 1d)",
        style=discord.TextStyle.short,
        placeholder="10m",
        required=True,
        max_length=20,
    )
    reason = discord.ui.TextInput(
        label="Reason for Mute",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., Toxic behavior in VC",
        required=True,
        max_length=500,
    )

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
            await interaction.response.send_message(
                "❌ Invalid duration format! Please use numbers followed by `s`, `m`, `h`, or `d` (e.g., `10m`, `2h`).",
                ephemeral=True,
            )
            return

        until = datetime.datetime.now(datetime.timezone.utc) + delta
        case_id = db.add_mod_log(
            guild_id=interaction.guild.id,
            user_id=self.target_member.id,
            moderator_id=interaction.user.id,
            action_type="MUTE",
            reason=self.reason.value,
            duration=self.duration_str.value,
        )

        try:
            await self.target_member.timeout(until, reason=self.reason.value)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to timeout this member.", ephemeral=True)
            return

        try:
            dm_embed = discord.Embed(
                title=f"🔇 You have been muted in {interaction.guild.name}",
                description=f"**Duration:** {self.duration_str.value}\n**Reason:** {self.reason.value}",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self.target_member.send(embed=dm_embed)
        except Exception:
            pass

        embed = discord.Embed(
            title=f"🔇 Member Muted [Case #{case_id}]",
            description=f"**User:** {self.target_member.mention}\n**Duration:** {self.duration_str.value}\n**Reason:** {self.reason.value}",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await interaction.response.send_message(embed=embed)


class BanModal(discord.ui.Modal, title="Ban Member"):
    reason = discord.ui.TextInput(
        label="Reason for Ban",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., Raiding / severe TOS violation",
        required=True,
        max_length=500,
    )
    delete_days = discord.ui.TextInput(
        label="Delete Message History (0-7 days)",
        style=discord.TextStyle.short,
        placeholder="1",
        required=True,
        max_length=1,
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.target_member = member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            del_days = int(self.delete_days.value.strip())
            del_days = max(0, min(7, del_days))
        except ValueError:
            del_days = 0

        case_id = db.add_mod_log(
            guild_id=interaction.guild.id,
            user_id=self.target_member.id,
            moderator_id=interaction.user.id,
            action_type="BAN",
            reason=self.reason.value,
        )

        try:
            await interaction.guild.ban(self.target_member, reason=self.reason.value, delete_message_days=del_days)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to ban this member.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🔨 Member Banned [Case #{case_id}]",
            description=f"**User:** {self.target_member.mention} (`{self.target_member.id}`)\n**Reason:** {self.reason.value}\n**Deleted Messages:** {del_days} day(s)",
            color=discord.Color.dark_red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await interaction.response.send_message(embed=embed)


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Opens a modal to issue a warning to a member.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(member="The member to warn")
    async def warn_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if member.top_role >= interaction.user.top_role and interaction.guild.owner != interaction.user:
            await interaction.response.send_message("❌ You cannot warn a member with an equal or higher role.", ephemeral=True)
            return
        await interaction.response.send_modal(WarnModal(member))

    @app_commands.command(name="mute", description="Opens a modal to timeout (mute) a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to mute")
    async def mute_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if member.top_role >= interaction.user.top_role and interaction.guild.owner != interaction.user:
            await interaction.response.send_message("❌ You cannot mute a member with an equal or higher role.", ephemeral=True)
            return
        await interaction.response.send_modal(MuteModal(member))

    @app_commands.command(name="ban", description="Opens a modal to ban a member.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(member="The member to ban")
    async def ban_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if member.top_role >= interaction.user.top_role and interaction.guild.owner != interaction.user:
            await interaction.response.send_message("❌ You cannot ban a member with an equal or higher role.", ephemeral=True)
            return
        await interaction.response.send_modal(BanModal(member))

    @app_commands.command(name="modlogs", description="Displays past moderation logs for a member.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(member="The member whose logs to view")
    async def modlogs_cmd(self, interaction: discord.Interaction, member: discord.Member):
        logs = db.get_user_logs(interaction.guild.id, member.id)
        if not logs:
            await interaction.response.send_message(f"✨ No moderation records found for {member.mention}.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🛡️ Moderation History for {member} (`{member.id}`)",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        for log in logs[:10]:
            embed.add_field(
                name=f"[{log['action_type']}] Case #{log['id']} • {log['timestamp']}",
                value=f"**Reason:** {log['reason']}\n**Mod ID:** `<@{log['moderator_id']}>` | **Duration:** {log['duration']}",
                inline=False,
            )
        embed.set_footer(text=f"Showing latest {min(len(logs), 10)} of {len(logs)} total records.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==============================================================================
# SECTION 4: WELCOME SYSTEM COG (cogs/welcome.py)
# ==============================================================================

class WelcomeTextModal(discord.ui.Modal, title="Edit Welcome Content & Text"):
    outside_content = discord.ui.TextInput(
        label="Outside Embed Message Content",
        style=discord.TextStyle.short,
        placeholder="Haiii, {user}!",
        required=False,
        max_length=200,
    )
    embed_title = discord.ui.TextInput(
        label="Embed Title",
        style=discord.TextStyle.short,
        placeholder="✨ Welcome to {server}!",
        required=True,
        max_length=256,
    )
    embed_description = discord.ui.TextInput(
        label="Embed Description (Supports multi-line & <#channel_id>)",
        style=discord.TextStyle.paragraph,
        placeholder="We are happy to have you here, {user}!\nYou are member #{member_count} ♡",
        required=True,
        max_length=1500,
    )
    footer_text = discord.ui.TextInput(
        label="Footer Text",
        style=discord.TextStyle.short,
        placeholder="Enjoy your stay • {username}",
        required=False,
        max_length=200,
    )

    def __init__(self, guild_id: int, current_data: dict):
        super().__init__()
        self.guild_id = guild_id
        self.outside_content.default = current_data.get("outside_content", "")
        self.embed_title.default = current_data.get("embed_title", "")
        self.embed_description.default = current_data.get("embed_description", "")
        self.footer_text.default = current_data.get("footer_text", "")

    async def on_submit(self, interaction: discord.Interaction):
        db.update_welcome_config(
            self.guild_id,
            outside_content=self.outside_content.value,
            embed_title=self.embed_title.value,
            embed_description=self.embed_description.value,
            footer_text=self.footer_text.value,
        )
        await interaction.response.send_message("🌸 Welcome text content updated successfully!", ephemeral=True)


class WelcomeVisualsModal(discord.ui.Modal, title="Edit Welcome Visuals & Images"):
    embed_color = discord.ui.TextInput(
        label="Embed Hex Color (e.g. #f4c2c2)",
        style=discord.TextStyle.short,
        placeholder="#f4c2c2",
        required=True,
        max_length=7,
    )
    thumbnail_url = discord.ui.TextInput(
        label="Thumbnail Image URL (or {avatar})",
        style=discord.TextStyle.short,
        placeholder="{avatar}",
        required=False,
        max_length=500,
    )
    banner_url = discord.ui.TextInput(
        label="Large Banner Image URL",
        style=discord.TextStyle.short,
        placeholder="https://...",
        required=False,
        max_length=500,
    )
    footer_icon_url = discord.ui.TextInput(
        label="Footer Icon URL",
        style=discord.TextStyle.short,
        placeholder="https://...",
        required=False,
        max_length=500,
    )
    show_author = discord.ui.TextInput(
        label="Show Author Toggle (1 = Yes, 0 = No)",
        style=discord.TextStyle.short,
        placeholder="1",
        required=True,
        max_length=1,
    )

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
            show_auth = int(self.show_author.value.strip())
            show_auth = 1 if show_auth > 0 else 0
        except ValueError:
            show_auth = 1

        db.update_welcome_config(
            self.guild_id,
            embed_color=self.embed_color.value.strip(),
            thumbnail_url=self.thumbnail_url.value.strip(),
            banner_url=self.banner_url.value.strip(),
            footer_icon_url=self.footer_icon_url.value.strip(),
            show_author=show_auth,
        )
        await interaction.response.send_message("🌸 Welcome visuals and images updated successfully!", ephemeral=True)


class WelcomeDashboardView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Edit Content & Text", style=discord.ButtonStyle.primary, emoji="✍️", row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = db.get_welcome_config(self.guild_id)
        await interaction.response.send_modal(WelcomeTextModal(self.guild_id, config))

    @discord.ui.button(label="Edit Visuals & Images", style=discord.ButtonStyle.secondary, emoji="🎨", row=0)
    async def edit_visuals(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = db.get_welcome_config(self.guild_id)
        await interaction.response.send_modal(WelcomeVisualsModal(self.guild_id, config))

    @discord.ui.button(label="Test Welcome", style=discord.ButtonStyle.success, emoji="🧪", row=0)
    async def test_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("WelcomeCog")
        if cog:
            await cog.trigger_welcome(interaction.member, interaction.channel, test_mode=True)
            await interaction.response.send_message("✨ Test welcome preview sent in this channel!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Welcome cog not loaded.", ephemeral=True)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="welcome-setup", description="Configures the Mimu-style welcome system for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel="The target text channel where welcome messages will be posted")
    async def welcome_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.update_welcome_config(interaction.guild.id, channel_id=channel.id)
        embed = discord.Embed(
            title="🌸 Mimu-Style Welcome Dashboard",
            description=(
                f"Welcome messages are now configured to post in {channel.mention}!\n\n"
                "Use the interactive buttons below to customize your server's welcome cards:"
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        embed.set_footer(text=f"Server ID: {interaction.guild.id}")
        await interaction.response.send_message(embed=embed, view=WelcomeDashboardView(interaction.guild.id), ephemeral=True)

    def format_template(self, template: str, member: discord.Member) -> str:
        if not template:
            return ""
        return (
            template.replace("{user}", member.mention)
            .replace("{username}", member.name)
            .replace("{server}", member.guild.name)
            .replace("{member_count}", str(member.guild.member_count))
            .replace("{avatar}", member.display_avatar.url)
        )

    async def trigger_welcome(self, member: discord.Member, channel: discord.TextChannel, test_mode: bool = False):
        config = db.get_welcome_config(member.guild.id)
        if not config or not config["channel_id"] and not test_mode:
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
# SECTION 5: VC STUDY TRACKER COG (cogs/vctracker.py)
# ==============================================================================

class VcAdjustHoursModal(discord.ui.Modal, title="Adjust User VC/Cam/SS Hours"):
    user_id_input = discord.ui.TextInput(label="Target User ID", style=discord.TextStyle.short, placeholder="123456789...", required=True)
    metric_input = discord.ui.TextInput(label="Metric: vc, cam, or ss", style=discord.TextStyle.short, placeholder="vc", required=True)
    action_input = discord.ui.TextInput(label="Action: add, remove, or set", style=discord.TextStyle.short, placeholder="add", required=True)
    hours_input = discord.ui.TextInput(label="Hours to adjust", style=discord.TextStyle.short, placeholder="2.5", required=True)

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
            metric = self.metric_input.value.strip().lower()
            action = self.action_input.value.strip().lower()
            hrs = float(self.hours_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid numerical input format.", ephemeral=True)
            return

        if metric not in ("vc", "cam", "ss"):
            await interaction.response.send_message("❌ Metric must be `vc`, `cam`, or `ss`.", ephemeral=True)
            return
        if action not in ("add", "remove", "set"):
            await interaction.response.send_message("❌ Action must be `add`, `remove`, or `set`.", ephemeral=True)
            return

        secs = int(hrs * 3600)
        db.adjust_vc_seconds(self.guild_id, uid, metric, action, secs)
        await interaction.response.send_message(f"✅ Successfully adjusted `{metric}` by `{hrs}h` (`{action}`) for user ID `<@{uid}>`.", ephemeral=True)


class UntrackedChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select voice channels to exclude from tracking...",
            min_values=0,
            max_values=10,
            channel_types=[discord.ChannelType.voice],
        )

    async def callback(self, interaction: discord.Interaction):
        selected_ids = [ch.id for ch in self.values]
        db.set_untracked_channels(interaction.guild.id, selected_ids)
        await interaction.response.send_message(f"✅ Updated untracked voice channels ({len(selected_ids)} channel(s) excluded).", ephemeral=True)


class VcSettingsView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.add_item(UntrackedChannelSelect())

    @discord.ui.button(label="View Untracked Channels", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def view_untracked(self, interaction: discord.Interaction, button: discord.ui.Button):
        untracked = db.get_untracked_channels(self.guild_id)
        if not untracked:
            await interaction.response.send_message("✨ No voice channels are currently marked as untracked in this server.", ephemeral=True)
            return
        mentions = [f"<#{cid}>" for cid in untracked]
        await interaction.response.send_message(f"📋 **Untracked Voice Channels:**\n" + ", ".join(mentions), ephemeral=True)

    @discord.ui.button(label="Adjust User Hours", style=discord.ButtonStyle.primary, emoji="⏱️", row=1)
    async def adjust_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VcAdjustHoursModal(self.guild_id))


class LeaderboardView(discord.ui.View):
    def __init__(self, guild: discord.Guild, rows: list[dict], timeframe: str = "all_time", category: str = "vc"):
        super().__init__(timeout=180)
        self.guild = guild
        self.rows = rows
        self.timeframe = timeframe
        self.category = category
        self.page = 0
        self.per_page = 10
        self.update_buttons()

    def update_buttons(self):
        # Timeframe button styles
        self.btn_daily.style = discord.ButtonStyle.success if self.timeframe == "daily" else discord.ButtonStyle.secondary
        self.btn_weekly.style = discord.ButtonStyle.success if self.timeframe == "weekly" else discord.ButtonStyle.secondary
        self.btn_monthly.style = discord.ButtonStyle.success if self.timeframe == "monthly" else discord.ButtonStyle.secondary
        self.btn_all.style = discord.ButtonStyle.success if self.timeframe == "all_time" else discord.ButtonStyle.secondary

    def sort_rows(self) -> list[dict]:
        col_map = {
            "vc": f"{self.timeframe}_seconds",
            "combined": f"{self.timeframe}_cam_ss_seconds",
            "cam": f"{self.timeframe}_cam_seconds",
            "ss": f"{self.timeframe}_ss_seconds",
        }
        key_col = col_map.get(self.category, f"{self.timeframe}_seconds")
        return sorted(self.rows, key=lambda x: x.get(key_col, 0), reverse=True)

    def build_embed(self) -> discord.Embed:
        sorted_data = self.sort_rows()
        max_pages = max(1, (len(sorted_data) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, max_pages - 1))

        chunk = sorted_data[self.page * self.per_page : (self.page + 1) * self.per_page]

        cat_names = {
            "vc": "Total VC Hours",
            "combined": "Cam + SS Combined Hours",
            "cam": "Camera Only Hours",
            "ss": "Screen Share Only Hours",
        }
        embed = discord.Embed(
            title=f"🏆 Voice Study Leaderboard • {self.timeframe.replace('_', ' ').title()}",
            description=f"**Category:** {cat_names.get(self.category, 'Total VC')}\nShowing top studiers (IST Resets Active).",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        col_map = {
            "vc": f"{self.timeframe}_seconds",
            "combined": f"{self.timeframe}_cam_ss_seconds",
            "cam": f"{self.timeframe}_cam_seconds",
            "ss": f"{self.timeframe}_ss_seconds",
        }
        key_col = col_map.get(self.category, f"{self.timeframe}_seconds")

        if not chunk:
            embed.add_field(name="No Data", value="No voice study records found for this timeframe yet!", inline=False)
        else:
            lines = []
            for idx, r in enumerate(chunk, start=self.page * self.per_page + 1):
                uid = r["user_id"]
                val_secs = r.get(key_col, 0)
                hrs, rem = divmod(val_secs, 3600)
                mins = rem // 60
                time_str = f"{hrs}h {mins}m"

                cam_secs = r.get(f"{self.timeframe}_cam_seconds", 0)
                ss_secs = r.get(f"{self.timeframe}_ss_seconds", 0)
                c_hrs, c_rem = divmod(cam_secs, 3600)
                s_hrs, s_rem = divmod(ss_secs, 3600)
                cam_str = f"{c_hrs}h {c_rem//60}m"
                ss_str = f"{s_hrs}h {s_rem//60}m"

                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`#{idx}`"
                extra = f" (Cam: {cam_str} | SS: {ss_str})" if self.category == "combined" else ""
                lines.append(f"{medal} <@{uid}> — **{time_str}**{extra}")

            embed.add_field(name="Rankings", value="\n".join(lines), inline=False)

        embed.set_footer(text=f"Page {self.page + 1}/{max_pages} • Use category dropdown & timeframe buttons below")
        return embed

    @discord.ui.button(label="Daily", style=discord.ButtonStyle.secondary, row=0)
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "daily"
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "weekly"
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Monthly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "monthly"
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="All-Time", style=discord.ButtonStyle.success, row=0)
    async def btn_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "all_time"
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.primary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=1)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="Switch leaderboard category...",
        row=2,
        options=[
            discord.SelectOption(label="Total VC Hours", value="vc", emoji="⏱️"),
            discord.SelectOption(label="Cam + SS Combined Hours", value="combined", emoji="🔥"),
            discord.SelectOption(label="Camera Only Hours", value="cam", emoji="📹"),
            discord.SelectOption(label="Screen Share Only Hours", value="ss", emoji="🖥️"),
        ],
    )
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.category = select.values[0]
        self.page = 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class VCTrackerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Active sessions dict: (guild_id, user_id) -> { 'join_time': datetime, 'vc_id': int, 'cam_start': datetime|None, 'ss_start': datetime|None, 'cam_secs': int, 'ss_secs': int, 'comb_start': datetime|None, 'comb_secs': int }
        self.active_sessions = {}
        self.flush_vc_sessions.start()

    def cog_unload(self):
        self.flush_vc_sessions.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """Recovers active voice members upon bot restart."""
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
                    self.active_sessions[(guild.id, member.id)] = {
                        "join_time": now,
                        "vc_id": vc.id,
                        "cam_start": now if has_cam else None,
                        "ss_start": now if has_ss else None,
                        "cam_secs": 0,
                        "ss_secs": 0,
                        "comb_start": now if (has_cam or has_ss) else None,
                        "comb_secs": 0,
                    }

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        guild = member.guild
        untracked = db.get_untracked_channels(guild.id)
        now = datetime.datetime.now(datetime.timezone.utc)
        key = (guild.id, member.id)

        before_tracked = before.channel and before.channel.id not in untracked
        after_tracked = after.channel and after.channel.id not in untracked

        # Case 1: Left tracked VC or moved to untracked channel
        if before_tracked and (not after_tracked or before.channel.id != after.channel.id):
            session = self.active_sessions.pop(key, None)
            if session:
                elapsed = int((now - session["join_time"]).total_seconds())
                cam_tot = session["cam_secs"] + (int((now - session["cam_start"]).total_seconds()) if session["cam_start"] else 0)
                ss_tot = session["ss_secs"] + (int((now - session["ss_start"]).total_seconds()) if session["ss_start"] else 0)
                comb_tot = session["comb_secs"] + (int((now - session["comb_start"]).total_seconds()) if session["comb_start"] else 0)
                db.add_vc_metrics(guild.id, member.id, vc_seconds=elapsed, cam_seconds=cam_tot, ss_seconds=ss_tot, cam_ss_seconds=comb_tot)

        # Case 2: Joined tracked VC or switched between tracked VCs
        if after_tracked:
            if not before_tracked or (before.channel and before.channel.id != after.channel.id):
                has_cam = bool(after.self_video)
                has_ss = bool(after.self_stream)
                self.active_sessions[key] = {
                    "join_time": now,
                    "vc_id": after.channel.id,
                    "cam_start": now if has_cam else None,
                    "ss_start": now if has_ss else None,
                    "cam_secs": 0,
                    "ss_secs": 0,
                    "comb_start": now if (has_cam or has_ss) else None,
                    "comb_secs": 0,
                }
            else:
                # Same tracked VC, handle camera or screen share state toggles
                session = self.active_sessions.get(key)
                if session:
                    # Camera toggle
                    if not before.self_video and after.self_video:
                        session["cam_start"] = now
                        if not session["ss_start"] and not session["comb_start"]:
                            session["comb_start"] = now
                    elif before.self_video and not after.self_video:
                        if session["cam_start"]:
                            session["cam_secs"] += int((now - session["cam_start"]).total_seconds())
                            session["cam_start"] = None
                        if not session["ss_start"] and session["comb_start"]:
                            session["comb_secs"] += int((now - session["comb_start"]).total_seconds())
                            session["comb_start"] = None

                    # Screen Share toggle
                    if not before.self_stream and after.self_stream:
                        session["ss_start"] = now
                        if not session["cam_start"] and not session["comb_start"]:
                            session["comb_start"] = now
                    elif before.self_stream and not after.self_stream:
                        if session["ss_start"]:
                            session["ss_secs"] += int((now - session["ss_start"]).total_seconds())
                            session["ss_start"] = None
                        if not session["cam_start"] and session["comb_start"]:
                            session["comb_secs"] += int((now - session["comb_start"]).total_seconds())
                            session["comb_start"] = None

    @tasks.loop(minutes=5)
    async def flush_vc_sessions(self):
        """Background task flushing active VC metrics to SQLite every 5 minutes."""
        now = datetime.datetime.now(datetime.timezone.utc)
        for key, session in list(self.active_sessions.items()):
            guild_id, user_id = key
            elapsed = int((now - session["join_time"]).total_seconds())
            cam_tot = session["cam_secs"] + (int((now - session["cam_start"]).total_seconds()) if session["cam_start"] else 0)
            ss_tot = session["ss_secs"] + (int((now - session["ss_start"]).total_seconds()) if session["ss_start"] else 0)
            comb_tot = session["comb_secs"] + (int((now - session["comb_start"]).total_seconds()) if session["comb_start"] else 0)

            if elapsed > 0 or cam_tot > 0 or ss_tot > 0:
                db.add_vc_metrics(guild_id, user_id, vc_seconds=elapsed, cam_seconds=cam_tot, ss_seconds=ss_tot, cam_ss_seconds=comb_tot)
                # Reset timers for next interval chunk
                session["join_time"] = now
                session["cam_secs"] = 0
                session["ss_secs"] = 0
                session["comb_secs"] = 0
                if session["cam_start"]:
                    session["cam_start"] = now
                if session["ss_start"]:
                    session["ss_start"] = now
                if session["comb_start"]:
                    session["comb_start"] = now

    @flush_vc_sessions.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="stats", description="Displays tracked voice study time stats and current rank.")
    @app_commands.describe(member="The member whose stats to view (defaults to yourself)")
    async def stats_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        stats = db.get_user_vc_stats(interaction.guild.id, target.id)

        live_session = self.active_sessions.get((interaction.guild.id, target.id))
        is_live = bool(live_session)
        live_cam = False
        live_ss = False
        if is_live and target.voice:
            live_cam = bool(target.voice.self_video)
            live_ss = bool(target.voice.self_stream)

        def fmt(secs: int) -> str:
            h, r = divmod(secs, 3600)
            return f"{h}h {r//60}m"

        embed = discord.Embed(
            title=f"⏱️ Voice Study Stats • {target.display_name}",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        status_badge = "🔴 Offline / Not in VC"
        if is_live:
            status_badge = "🟢 In VC"
            if live_cam:
                status_badge += " | 📹 Cam ON"
            if live_ss:
                status_badge += " | 🖥️ Screen Sharing"

        embed.add_field(name="Current Status", value=status_badge, inline=False)
        embed.add_field(name="Server Rank", value=f"`#{stats['rank']}` All-Time", inline=True)
        embed.add_field(name="All-Time VC Hours", value=fmt(stats["all_time_seconds"]), inline=True)

        embed.add_field(
            name="📊 Time Breakdown",
            value=(
                f"• **Today:** {fmt(stats['daily_seconds'])} (Cam: {fmt(stats['daily_cam_seconds'])} | SS: {fmt(stats['daily_ss_seconds'])})\n"
                f"• **This Week:** {fmt(stats['weekly_seconds'])} (Cam: {fmt(stats['weekly_cam_seconds'])} | SS: {fmt(stats['weekly_ss_seconds'])})\n"
                f"• **This Month:** {fmt(stats['monthly_seconds'])} (Cam: {fmt(stats['monthly_cam_seconds'])} | SS: {fmt(stats['monthly_ss_seconds'])})\n"
                f"• **Combined Cam/SS:** {fmt(stats['all_time_cam_ss_seconds'])}"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="leaderboard", description="Displays the top voice study leaderboard.")
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        rows = db.get_vc_leaderboard_all_rows(interaction.guild.id)
        if not rows:
            await interaction.response.send_message("✨ No voice study data recorded in this server yet.", ephemeral=True)
            return
        view = LeaderboardView(interaction.guild, rows, timeframe="all_time", category="vc")
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="vc-settings", description="Configures untracked voice channels and admin adjustments.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def vc_settings_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ VC Tracker Admin Configuration",
            description=(
                "Use the channel selector below to designate voice channels as **untracked** (excluded from study tracking).\n"
                "Use the buttons below to view untracked rooms or adjust user study hours."
            ),
            color=discord.Color.from_str("#f4c2c2"),
        )
        await interaction.response.send_message(embed=embed, view=VcSettingsView(interaction.guild.id), ephemeral=True)


# ==============================================================================
# SECTION 6: TEMPVOICE COG (cogs/tempvoice.py)
# ==============================================================================

class TempVoiceNameModal(discord.ui.Modal, title="Rename Temporary Voice Channel"):
    new_name = discord.ui.TextInput(label="New Channel Name", style=discord.TextStyle.short, placeholder="🌿・Study Room", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ You are not the owner of this temporary voice channel.", ephemeral=True)
            return

        try:
            await vc.edit(name=self.new_name.value.strip())
            await interaction.response.send_message(f"✅ Successfully renamed channel to **{self.new_name.value.strip()}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to rename this channel.", ephemeral=True)


class TempVoiceLimitModal(discord.ui.Modal, title="Set User Limit"):
    limit_val = discord.ui.TextInput(label="User Limit (0 for unlimited, 1-99)", style=discord.TextStyle.short, placeholder="5", required=True, max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ You are not the owner of this temporary voice channel.", ephemeral=True)
            return

        try:
            lim = int(self.limit_val.value.strip())
            lim = max(0, min(99, lim))
        except ValueError:
            lim = 0

        try:
            await vc.edit(user_limit=lim)
            await interaction.response.send_message(f"✅ Voice channel user limit set to **{lim if lim > 0 else 'Unlimited'}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to set user limits.", ephemeral=True)


class TempVoiceTrustSelect(discord.ui.UserSelect):
    def __init__(self, action: str):
        self.action = action
        super().__init__(placeholder=f"Select member to {action}...", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ You are not the owner of this temporary voice channel.", ephemeral=True)
            return

        target = self.values[0]
        try:
            if self.action == "trust":
                await vc.set_permissions(target, connect=True, view_channel=True, send_messages=True)
                await interaction.response.send_message(f"✅ Trusted {target.mention} in your room.", ephemeral=True)
            elif self.action == "untrust":
                await vc.set_permissions(target, overwrite=None)
                await interaction.response.send_message(f"✅ Removed trusted permissions for {target.mention}.", ephemeral=True)
            elif self.action == "transfer":
                if target.voice and target.voice.channel and target.voice.channel.id == vc.id:
                    db.update_temp_channel(vc.id, owner_id=target.id)
                    await vc.set_permissions(target, manage_channels=True, move_members=True, connect=True)
                    await interaction.response.send_message(f"👑 Transferred ownership of the room to {target.mention}!", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Target user must be inside your voice channel.", ephemeral=True)
            elif self.action == "kick":
                if target.voice and target.voice.channel and target.voice.channel.id == vc.id:
                    await target.move_to(None)
                    await interaction.response.send_message(f"👢 Disconnected {target.mention} from your room.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Target user is not in your channel.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to modify channel overrides.", ephemeral=True)


class TempVoiceTrustView(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=60)
        self.add_item(TempVoiceTrustSelect(action))


class TempVoiceRegionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Automatic", value="None", emoji="🌐"),
            discord.SelectOption(label="India", value="india", emoji="🇮🇳"),
            discord.SelectOption(label="Singapore", value="singapore", emoji="🇸🇬"),
            discord.SelectOption(label="US East", value="us-east", emoji="🇺🇸"),
            discord.SelectOption(label="Europe", value="europe", emoji="🇪🇺"),
        ]
        super().__init__(placeholder="Select voice channel region...", options=options)

    async def callback(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ You are not the owner of this temporary voice channel.", ephemeral=True)
            return

        reg = None if self.values[0] == "None" else self.values[0]
        try:
            await vc.edit(rtc_region=reg)
            await interaction.response.send_message(f"✅ Voice region updated to **{self.values[0]}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to change voice regions.", ephemeral=True)


class TempVoiceRegionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(TempVoiceRegionSelect())


class TempVoiceControlView(discord.ui.View):
    """Persistent 3-row interactive control panel for temporary voice channels."""
    def __init__(self):
        super().__init__(timeout=None)

    # Row 1
    @discord.ui.button(label="Name", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="temp_vc_name", row=0)
    async def btn_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempVoiceNameModal())

    @discord.ui.button(label="Limit", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="temp_vc_limit", row=0)
    async def btn_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempVoiceLimitModal())

    @discord.ui.button(label="Privacy", style=discord.ButtonStyle.primary, emoji="🔒", custom_id="temp_vc_privacy", row=0)
    async def btn_privacy(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ You are not the owner of this temporary voice channel.", ephemeral=True)
            return

        modes = ["open", "locked", "hidden"]
        current = meta["privacy_mode"]
        next_mode = modes[(modes.index(current) + 1) % len(modes)]
        db.update_temp_channel(vc.id, privacy_mode=next_mode)

        try:
            if next_mode == "open":
                await vc.set_permissions(interaction.guild.default_role, connect=True, view_channel=True)
                msg = "🔓 Room is now **Public / Open**."
            elif next_mode == "locked":
                await vc.set_permissions(interaction.guild.default_role, connect=False, view_channel=True)
                msg = "🔒 Room is now **Locked** (`@everyone` cannot connect)."
            elif next_mode == "hidden":
                await vc.set_permissions(interaction.guild.default_role, connect=False, view_channel=False)
                msg = "👻 Room is now **Hidden / Invisible**."
            await interaction.response.send_message(msg, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to modify channel overrides.", ephemeral=True)

    @discord.ui.button(label="Chat", style=discord.ButtonStyle.secondary, emoji="💬", custom_id="temp_vc_chat", row=0)
    async def btn_chat(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ You are not the owner of this temporary voice channel.", ephemeral=True)
            return

        new_chat = 0 if meta["chat_enabled"] == 1 else 1
        db.update_temp_channel(vc.id, chat_enabled=new_chat)
        try:
            await vc.set_permissions(interaction.guild.default_role, send_messages=bool(new_chat))
            await interaction.response.send_message(f"💬 Text-in-voice is now **{'Enabled' if new_chat else 'Disabled'}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions.", ephemeral=True)

    # Row 2
    @discord.ui.button(label="Trust", style=discord.ButtonStyle.success, emoji="✅", custom_id="temp_vc_trust", row=1)
    async def btn_trust(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select a member to trust:", view=TempVoiceTrustView("trust"), ephemeral=True)

    @discord.ui.button(label="Untrust", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="temp_vc_untrust", row=1)
    async def btn_untrust(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select a member to untrust:", view=TempVoiceTrustView("untrust"), ephemeral=True)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢", custom_id="temp_vc_kick", row=1)
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select a member to kick from your room:", view=TempVoiceTrustView("kick"), ephemeral=True)

    @discord.ui.button(label="Region", style=discord.ButtonStyle.secondary, emoji="🌐", custom_id="temp_vc_region", row=1)
    async def btn_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select voice region:", view=TempVoiceRegionView(), ephemeral=True)

    # Row 3
    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="👑", custom_id="temp_vc_claim", row=2)
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta:
            await interaction.response.send_message("❌ This is not a temporary voice channel.", ephemeral=True)
            return

        owner_member = interaction.guild.get_member(meta["owner_id"])
        if owner_member and owner_member.voice and owner_member.voice.channel and owner_member.voice.channel.id == vc.id:
            await interaction.response.send_message("❌ The original owner is still in the room!", ephemeral=True)
            return

        db.update_temp_channel(vc.id, owner_id=interaction.user.id)
        await vc.set_permissions(interaction.user, manage_channels=True, move_members=True, connect=True)
        await interaction.response.send_message("👑 You have successfully claimed ownership of this temporary voice channel!", ephemeral=True)

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="temp_vc_transfer", row=2)
    async def btn_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select a member to transfer ownership to:", view=TempVoiceTrustView("transfer"), ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="temp_vc_delete", row=2)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return
        meta = db.get_temp_channel(vc.id)
        if not meta or meta["owner_id"] != interaction.user.id:
            await interaction.response.send_message("❌ You are not the owner of this temporary voice channel.", ephemeral=True)
            return

        db.delete_temp_channel(vc.id)
        try:
            await vc.delete(reason="Owner deleted room via TempVoice panel")
            await interaction.response.send_message("🗑️ Temporary voice channel deleted.", ephemeral=True)
        except Exception:
            pass


class TempVoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Sweeps empty leftover temp VCs on startup."""
        for guild in self.bot.guilds:
            temp_rows = db.get_all_temp_channels(guild.id)
            for row in temp_rows:
                ch = guild.get_channel(row["channel_id"])
                if not ch or len(ch.members) == 0:
                    if ch:
                        try:
                            await ch.delete(reason="Startup cleanup of empty temp voice channel")
                        except Exception:
                            pass
                    db.delete_temp_channel(row["channel_id"])

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        config = db.get_tempvoice_config(guild.id)
        hub_id = config.get("hub_channel_id")

        # 1. Spawn new temp VC if joined Hub
        if hub_id and after.channel and after.channel.id == hub_id:
            cat = guild.get_channel(config["category_id"]) or after.channel.category
            fmt = config.get("name_format", "🌿・{username}'s study room")
            room_name = fmt.replace("{username}", member.name).replace("{user}", member.display_name)

            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
                    member: discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True, view_channel=True),
                }
                new_vc = await guild.create_voice_channel(name=room_name, category=cat, overwrites=overwrites)
                db.register_temp_channel(new_vc.id, guild.id, member.id)
                await member.move_to(new_vc)
            except discord.Forbidden:
                pass

        # 2. Cleanup empty temp VCs
        if before.channel:
            meta = db.get_temp_channel(before.channel.id)
            if meta and len(before.channel.members) == 0:
                db.delete_temp_channel(before.channel.id)
                try:
                    await before.channel.delete(reason="Empty temporary voice channel cleanup")
                except Exception:
                    pass

    @app_commands.command(name="tempvoice-setup", description="Configures the Join-to-Create TempVoice hub and persistent control panel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        hub_channel="The voice channel users join to spawn rooms",
        interface_channel="The text channel where the persistent control panel will be posted",
        category="Optional target category for new rooms",
    )
    async def tempvoice_setup(
        self,
        interaction: discord.Interaction,
        hub_channel: discord.VoiceChannel,
        interface_channel: discord.TextChannel,
        category: Optional.CategoryChannel = None,
    ):
        cat_id = category.id if category else (hub_channel.category.id if hub_channel.category else None)
        db.update_tempvoice_config(
            interaction.guild.id,
            hub_channel_id=hub_channel.id,
            category_id=cat_id,
            interface_channel_id=interface_channel.id,
        )

        embed = discord.Embed(
            title="🎙️ TempVoice Control Center",
            description=(
                "Manage your personal study room using the interactive buttons below!\n\n"
                "• **Row 1:** `Name`, `Limit`, `Privacy`, `Chat`\n"
                "• **Row 2:** `Trust`, `Untrust`, `Kick`, `Region`\n"
                "• **Row 3:** `Claim`, `Transfer`, `Delete`"
            ),
            color=discord.Color.blurple(),
        )
        msg = await interface_channel.send(embed=embed, view=TempVoiceControlView())
        db.update_tempvoice_config(interaction.guild.id, interface_message_id=msg.id)

        await interaction.response.send_message(
            f"✅ TempVoice successfully configured! Hub: {hub_channel.mention} | Control Panel posted in {interface_channel.mention}.",
            ephemeral=True,
        )


# ==============================================================================
# SECTION 7: UTILITY & AUTOROLE COGS (cogs/utility.py & cogs/autorole.py)
# ==============================================================================

class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="purge", description="Deletes 1-100 messages instantly (optionally filtered by member).")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(amount="Number of messages to delete (1-100)", member="Optional member whose messages to purge")
    async def purge_cmd(self, interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Purge amount must be between 1 and 100.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        def check(m: discord.Message):
            if member and m.author.id != member.id:
                return False
            return True

        try:
            deleted = await interaction.channel.purge(limit=amount, check=check, bulk=True)
            await interaction.followup.send(f"🧹 Successfully deleted `{len(deleted)}` message(s).", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ I lack 'Manage Messages' permissions.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"⚠️ Error purging messages (messages older than 14 days cannot be bulk deleted): `{e}`", ephemeral=True)


class AutoroleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select default roles assigned on join...",
            min_values=1,
            max_values=5,
        )

    async def callback(self, interaction: discord.Interaction):
        role_ids = [r.id for r in self.values]
        db.set_autoroles(interaction.guild.id, role_ids)
        mentions = [r.mention for r in self.values]
        await interaction.response.send_message(f"⚙️ Autoroles updated successfully: " + ", ".join(mentions), ephemeral=True)


class AutoroleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(AutoroleSelect())


class AutoroleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="autorole-setup", description="Configures default roles automatically granted to new members.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ Server Autorole Setup",
            description="Select up to 5 default roles from the dropdown menu below that will be automatically assigned when new members join.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=AutoroleView(), ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        role_ids = db.get_autoroles(member.guild.id)
        if not role_ids:
            return
        roles_to_add = [member.guild.get_role(rid) for rid in role_ids if member.guild.get_role(rid)]
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Automatic Server Autorole")
            except discord.Forbidden:
                pass


# ==============================================================================
# SECTION 8: CHALLENGE VCS & POMODORO TASKS (cogs/challenge_vcs.py & cogs/pomodoro_tasks.py)
# ==============================================================================

class ChallengeVCsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track pending grace tasks: (guild_id, user_id) -> asyncio.Task
        self.grace_tasks = {}

    @app_commands.command(name="challenge-vc-setup", description="Designates a voice channel as Cam-Only or SS-Only with automatic grace period disconnects.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel="The voice channel", challenge_type="cam or ss", grace_seconds="Grace period in seconds (default 30)")
    async def challenge_vc_setup(self, interaction: discord.Interaction, channel: discord.VoiceChannel, challenge_type: str, grace_seconds: int = 30):
        ctype = challenge_type.strip().lower()
        if ctype not in ("cam", "ss"):
            await interaction.response.send_message("❌ Challenge type must be either `cam` or `ss`.", ephemeral=True)
            return

        db.set_challenge_vc(channel.id, interaction.guild.id, ctype, grace_seconds)
        await interaction.response.send_message(f"✅ Configured {channel.mention} as **{ctype.upper()}-Only** challenge room with a `{grace_seconds}s` grace period.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        key = (member.guild.id, member.id)

        # Cancel existing grace task if user switched channels
        if before.channel and before.channel.id != (after.channel.id if after.channel else None):
            task = self.grace_tasks.pop(key, None)
            if task and not task.done():
                task.cancel()

        # Joined challenge VC
        if after.channel:
            conf = db.get_challenge_vc(after.channel.id)
            if conf:
                ctype = conf["challenge_type"]
                grace = conf["grace_seconds"]
                has_req = (after.self_video if ctype == "cam" else after.self_stream)

                if not has_req and key not in self.grace_tasks:
                    # Start grace period countdown
                    async def grace_countdown():
                        import asyncio
                        await asyncio.sleep(grace)
                        # Recheck voice state
                        if member.voice and member.voice.channel and member.voice.channel.id == after.channel.id:
                            cur_req = (member.voice.self_video if ctype == "cam" else member.voice.self_stream)
                            if not cur_req:
                                try:
                                    await member.move_to(None, reason=f"Failed {ctype.upper()}-Only challenge grace period")
                                    await member.send(f"⚠️ You were disconnected from **{after.channel.name}** because you failed to enable your **{'Camera' if ctype == 'cam' else 'Screen Share'}** within {grace} seconds.")
                                except Exception:
                                    pass
                        self.grace_tasks.pop(key, None)

                    self.grace_tasks[key] = self.bot.loop.create_task(grace_countdown())
                elif has_req and key in self.grace_tasks:
                    t = self.grace_tasks.pop(key, None)
                    if t:
                        t.cancel()

        # Toggled cam/ss mid-session inside challenge VC
        if after.channel and before.channel and after.channel.id == before.channel.id:
            conf = db.get_challenge_vc(after.channel.id)
            if conf:
                ctype = conf["challenge_type"]
                has_req = (after.self_video if ctype == "cam" else after.self_stream)
                if has_req and key in self.grace_tasks:
                    t = self.grace_tasks.pop(key, None)
                    if t:
                        t.cancel()


class TaskCompleteView(discord.ui.View):
    def __init__(self, task_id: int, user_id: int):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.user_id = user_id

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.success, emoji="✅")
    async def complete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your task.", ephemeral=True)
            return
        db.update_task_status(self.task_id, self.user_id, 1)
        await interaction.response.send_message("✅ Task marked as completed!", ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your task.", ephemeral=True)
            return
        db.update_task_status(self.task_id, self.user_id, 1)
        await interaction.response.send_message("🗑️ Task deleted.", ephemeral=True)


class PomodoroTasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="task", description="Manages your personal to-do tasks.")
    @app_commands.describe(action="add, list, or clear", title="Task title (required for add)", due="Optional due date")
    async def task_cmd(self, interaction: discord.Interaction, action: str, title: Optional[str] = None, due: Optional[str] = None):
        act = action.strip().lower()
        if act == "add":
            if not title:
                await interaction.response.send_message("❌ Please provide a task title.", ephemeral=True)
                return
            db.add_user_task(interaction.user.id, title, due)
            await interaction.response.send_message(f"✅ Added task: **{title}** (Due: {due or 'No deadline'})", ephemeral=True)
        elif act == "list":
            tasks = db.get_user_tasks(interaction.user.id)
            active = [t for t in tasks if t["completed"] == 0]
            if not active:
                await interaction.response.send_message("✨ You have no active tasks!", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"📝 To-Do Tasks • {interaction.user.display_name}",
                color=discord.Color.blurple(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            for t in active[:10]:
                embed.add_field(
                    name=f"#{t['id']} • {t['title']}",
                    value=f"**Due:** {t['due_date']} | **Created:** {t['created_at']}",
                    inline=False,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif act == "clear":
            db.clear_user_tasks(interaction.user.id)
            await interaction.response.send_message("🧹 Cleared all completed tasks.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Action must be `add`, `list`, or `clear`.", ephemeral=True)

    @app_commands.command(name="pomodoro", description="Launches a guided Pomodoro study session timer.")
    @app_commands.describe(work_mins="Work focus minutes (default 50)", break_mins="Break minutes (default 10)")
    async def pomodoro_cmd(self, interaction: discord.Interaction, work_mins: int = 50, break_mins: int = 10):
        import asyncio
        embed = discord.Embed(
            title="🍅 Pomodoro Focus Session Started!",
            description=f"**Focus Block:** `{work_mins} minutes`\n**Break Block:** `{break_mins} minutes`\n\nLet's get to work, {interaction.user.mention}! ✨",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await interaction.response.send_message(embed=embed)

        await asyncio.sleep(work_mins * 60)
        try:
            await interaction.followup.send(f"🔔 {interaction.user.mention}, **Work session complete!** Time for a `{break_mins}` minute break! 🎉")
        except Exception:
            pass

        await asyncio.sleep(break_mins * 60)
        try:
            await interaction.followup.send(f"🔔 {interaction.user.mention}, **Break is over!** Time to lock back in! 🚀")
        except Exception:
            pass


# ==============================================================================
# SECTION 9: HELP COMMAND COG (cogs/help.py)
# ==============================================================================

class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Moderation & Modals", description="Warn, Mute, Ban, and ModLogs commands", emoji="🛡️", value="mod"),
            discord.SelectOption(label="Welcome System", description="Mimu-style welcome setup and embed customization", emoji="🌸", value="welcome"),
            discord.SelectOption(label="VC Tracking & Stats", description="Voice Study Time tracking, Cam/SS metrics & Leaderboards", emoji="⏱️", value="vctracker"),
            discord.SelectOption(label="TempVoice (Join-to-Create)", description="Personal voice room creation and interactive controls", emoji="🎙️", value="tempvoice"),
            discord.SelectOption(label="Study, Tasks & Challenge VCs", description="Pomodoro timers, To-Do list, and Cam/SS Challenge VCs", emoji="🍅", value="study"),
            discord.SelectOption(label="Utility & Autoroles", description="Message purging and automated new member roles", emoji="⚙️", value="utility"),
        ]
        super().__init__(placeholder="Select a command category to browse...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        embed = discord.Embed(color=discord.Color.blurple(), timestamp=datetime.datetime.now(datetime.timezone.utc))

        if val == "mod":
            embed.title = "🛡️ Moderation & Modal Commands"
            embed.description = (
                "Interactive UI Modal-based moderation suite:\n\n"
                "• `/warn <member>` — Warns a member.\n"
                "• `/mute <member>` — Timeouts a member.\n"
                "• `/ban <member>` — Bans a member.\n"
                "• `/modlogs <member>` — Displays past mod records."
            )
        elif val == "welcome":
            embed.title = "🌸 Mimu-Style Welcome Embed Builder"
            embed.description = (
                "Automated welcome system supporting dynamic placeholders (`{user}`, `{username}`, `{server}`, `{member_count}`, `{avatar}`):\n\n"
                "• `/welcome-setup <channel>` — Sets welcome channel and opens interactive setup dashboard."
            )
        elif val == "vctracker":
            embed.title = "⏱️ Voice Tracking & Leaderboards"
            embed.description = (
                "IST study time tracking for Total VC, Cam, SS, and Combined hours:\n\n"
                "• `/stats [member]` — Live session status, rank, and breakdowns.\n"
                "• `/leaderboard` — Paginated top studiers with timeframe and category filters.\n"
                "• `/vc-settings` — Admin panel for untracked VCs & hour adjustments."
            )
        elif val == "tempvoice":
            embed.title = "🎙️ TempVoice (Join-to-Create VCs)"
            embed.description = (
                "Personal voice channel spawning system with persistent 3-row button controls:\n\n"
                "• `/tempvoice-setup` — Configures Hub VC, category, name format, and control panel."
            )
        elif val == "study":
            embed.title = "🍅 Study Suite, Tasks & Challenge VCs"
            embed.description = (
                "• `/task [add/list/clear]` — Personal to-do manager.\n"
                "• `/pomodoro [work] [break]` — Guided focus timer.\n"
                "• `/challenge-vc-setup` — Cam-Only / SS-Only VCs with auto-disconnects."
            )
        elif val == "utility":
            embed.title = "⚙️ Utility & Autorole System"
            embed.description = (
                "• `/purge <amount> [member]` — Instantly deletes 1-100 messages.\n"
                "• `/autorole-setup` — Configures default roles assigned on join."
            )

        embed.set_footer(text="Use the dropdown menu below to switch categories • Bot v2.x")
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HelpSelect())


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Displays the comprehensive categorized help command directory.")
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
        await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)


# ==============================================================================
# SECTION 10: MAIN BOT INITIALIZATION (main.py)
# ==============================================================================

class ModWelcomeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        await self.add_cog(ModerationCog(self))
        await self.add_cog(WelcomeCog(self))
        await self.add_cog(VCTrackerCog(self))
        await self.add_cog(TempVoiceCog(self))
        await self.add_cog(UtilityCog(self))
        await self.add_cog(AutoroleCog(self))
        await self.add_cog(ChallengeVCsCog(self))
        await self.add_cog(PomodoroTasksCog(self))
        await self.add_cog(HelpCog(self))

        self.add_view(TempVoiceControlView())
        self.add_view(HelpView())

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

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
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

    keep_alive()

    bot = ModWelcomeBot()
    bot.run(token)