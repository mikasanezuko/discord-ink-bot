"""
================================================================================
DISCORD MODERATION & MIMU-STYLE WELCOME BOT (discord.py 2.x + Flask)
================================================================================
Designed for Render / Replit 24/7 hosting with SQLite persistence, interactive
Discord UI Modals, Buttons, Select menus, native timeouts, AFK system, and more.
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

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = (
            "<h2>Bot is online and running!</h2>"
            "<p>Discord Moderation, VC Tracking, TempVoice, AFK & Study Suite are active.</p>"
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

DB_FILE = "bot_database.db"


class DatabaseManager:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
        cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                """
                INSERT INTO vc_study_stats (
                    guild_id, user_id, daily_seconds, weekly_seconds, monthly_seconds, all_time_seconds,
                    daily_cam_seconds, weekly_cam_seconds, monthly_cam_seconds, all_time_cam_seconds,
                    daily_ss_seconds, weekly_ss_seconds, monthly_ss_seconds, all_time_ss_seconds,
                    daily_cam_ss_seconds, weekly_cam_ss_seconds, monthly_cam_ss_seconds, all_time_cam_ss_seconds,
                    last_day_key, last_week_key, last_month_key
                ) VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?, ?, ?)
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
                    day_key, week_key, month_key, guild_id, user_id,
                ),
            )
            conn.commit()
            cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            return cursor.fetchone()
        return row

    def add_vc_metrics(self, guild_id: int, user_id: int, vc_seconds: int = 0, cam_seconds: int = 0, ss_seconds: int = 0, cam_ss_seconds: int = 0):
        if vc_seconds <= 0 and cam_seconds <= 0 and ss_seconds <= 0 and cam_ss_seconds <= 0:
            return
        with self._get_connection() as conn:
            self._sync_period_resets(conn, guild_id, user_id)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE vc_study_stats
                SET daily_seconds = daily_seconds + ?, weekly_seconds = weekly_seconds + ?, monthly_seconds = monthly_seconds + ?, all_time_seconds = all_time_seconds + ?,
                    daily_cam_seconds = daily_cam_seconds + ?, weekly_cam_seconds = weekly_cam_seconds + ?, monthly_cam_seconds = monthly_cam_seconds + ?, all_time_cam_seconds = all_time_cam_seconds + ?,
                    daily_ss_seconds = daily_ss_seconds + ?, weekly_ss_seconds = weekly_ss_seconds + ?, monthly_ss_seconds = monthly_ss_seconds + ?, all_time_ss_seconds = all_time_ss_seconds + ?,
                    daily_cam_ss_seconds = daily_cam_ss_seconds + ?, weekly_cam_ss_seconds = weekly_cam_ss_seconds + ?, monthly_cam_ss_seconds = monthly_cam_ss_seconds + ?, all_time_cam_ss_seconds = all_time_cam_ss_seconds + ?
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
            cursor.execute(f"UPDATE vc_study_stats SET {cols[0]} = ?, {cols[1]} = ?, {cols[2]} = ?, {cols[3]} = ? WHERE guild_id = ? AND user_id = ?", (*new_vals, guild_id, user_id))
            conn.commit()

    def get_user_vc_stats(self, guild_id: int, user_id: int) -> dict:
        with self._get_connection() as conn:
            row = self._sync_period_resets(conn, guild_id, user_id)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) + 1 AS rank FROM vc_study_stats WHERE guild_id = ? AND all_time_seconds > ?", (guild_id, row["all_time_seconds"]))
            rank_row = cursor.fetchone()
            data = dict(row)
            data["rank"] = rank_row["rank"] if rank_row else 1
            return data

    def get_vc_leaderboard_all_rows(self, guild_id: int) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vc_study_stats WHERE guild_id = ?", (guild_id,))
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
                cursor.execute("INSERT INTO vc_untracked_channels (guild_id, channel_id) VALUES (?, ?)", (guild_id, cid))
            conn.commit()

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


db = DatabaseManager()


# ==============================================================================
# SECTION 3: MODERATION COG (cogs/moderation.py)
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
# SECTION 4: WELCOME SYSTEM COG (cogs/welcome.py)
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
    user_id_input = discord.ui.TextInput(label="Target User ID", style=discord.TextStyle.short, required=True)
    metric_input = discord.ui.TextInput(label="Metric: vc, cam, or ss", style=discord.TextStyle.short, required=True)
    action_input = discord.ui.TextInput(label="Action: add, remove, set", style=discord.TextStyle.short, required=True)
    hours_input = discord.ui.TextInput(label="Hours", style=discord.TextStyle.short, required=True)

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
            await interaction.response.send_message("❌ Invalid numerical input.", ephemeral=True)
            return
        if metric not in ("vc", "cam", "ss") or action not in ("add", "remove", "set"):
            await interaction.response.send_message("❌ Invalid metric or action.", ephemeral=True)
            return
        db.adjust_vc_seconds(self.guild_id, uid, metric, action, int(hrs * 3600))
        await interaction.response.send_message(f"✅ Adjusted `{metric}` by `{hrs}h` for <@{uid}>.", ephemeral=True)


class UntrackedChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="Select voice channels to exclude...", min_values=0, max_values=10, channel_types=[discord.ChannelType.voice])

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
        await interaction.response.send_message("📋 **Untracked VCs:** " + ", ".join([f"<@{cid}>" for cid in untracked]), ephemeral=True)

    @discord.ui.button(label="Adjust Hours", style=discord.ButtonStyle.primary, emoji="⏱️", row=1)
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

    def sort_rows(self) -> list[dict]:
        col_map = {
            "vc": f"{self.timeframe}_seconds",
            "combined": f"{self.timeframe}_cam_ss_seconds",
            "cam": f"{self.timeframe}_cam_seconds",
            "ss": f"{self.timeframe}_ss_seconds",
        }
        return sorted(self.rows, key=lambda x: x.get(col_map.get(self.category, f"{self.timeframe}_seconds"), 0), reverse=True)

    def build_embed(self) -> discord.Embed:
        sorted_data = self.sort_rows()
        max_pages = max(1, (len(sorted_data) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, max_pages - 1))
        chunk = sorted_data[self.page * self.per_page : (self.page + 1) * self.per_page]

        embed = discord.Embed(title=f"🏆 Leaderboard • {self.timeframe.title()}", color=discord.Color.gold(), timestamp=datetime.datetime.now(datetime.timezone.utc))
        col_map = {
            "vc": f"{self.timeframe}_seconds",
            "combined": f"{self.timeframe}_cam_ss_seconds",
            "cam": f"{self.timeframe}_cam_seconds",
            "ss": f"{self.timeframe}_ss_seconds",
        }
        key_col = col_map.get(self.category, f"{self.timeframe}_seconds")

        if not chunk:
            embed.add_field(name="No Data", value="No records found!", inline=False)
        else:
            lines = []
            for idx, r in enumerate(chunk, start=self.page * self.per_page + 1):
                val = r.get(key_col, 0)
                hrs, rem = divmod(val, 3600)
                lines.append(f"`#{idx}` <@{r['user_id']}> — **{hrs}h {rem//60}m**")
            embed.add_field(name="Rankings", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Page {self.page + 1}/{max_pages}")
        return embed

    @discord.ui.button(label="Daily", style=discord.ButtonStyle.secondary, row=0)
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "daily", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "weekly", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Monthly", style=discord.ButtonStyle.secondary, row=0)
    async def btn_monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "monthly", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="All-Time", style=discord.ButtonStyle.success, row=0)
    async def btn_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe, self.page = "all_time", 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.primary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=1)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class VCTrackerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_sessions = {}
        self.flush_vc_sessions.start()

    def cog_unload(self):
        self.flush_vc_sessions.cancel()

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
                    self.active_sessions[(guild.id, member.id)] = {
                        "join_time": now, "vc_id": vc.id,
                        "cam_start": now if has_cam else None, "ss_start": now if has_ss else None,
                        "cam_secs": 0, "ss_secs": 0,
                        "comb_start": now if (has_cam or has_ss) else None, "comb_secs": 0,
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

        if before_tracked and (not after_tracked or before.channel.id != after.channel.id):
            session = self.active_sessions.pop(key, None)
            if session:
                elapsed = int((now - session["join_time"]).total_seconds())
                cam_tot = session["cam_secs"] + (int((now - session["cam_start"]).total_seconds()) if session["cam_start"] else 0)
                ss_tot = session["ss_secs"] + (int((now - session["ss_start"]).total_seconds()) if session["ss_start"] else 0)
                comb_tot = session["comb_secs"] + (int((now - session["comb_start"]).total_seconds()) if session["comb_start"] else 0)
                db.add_vc_metrics(guild.id, member.id, vc_seconds=elapsed, cam_seconds=cam_tot, ss_seconds=ss_tot, cam_ss_seconds=comb_tot)

        if after_tracked:
            if not before_tracked or (before.channel and before.channel.id != after.channel.id):
                has_cam = bool(after.self_video)
                has_ss = bool(after.self_stream)
                self.active_sessions[key] = {
                    "join_time": now, "vc_id": after.channel.id,
                    "cam_start": now if has_cam else None, "ss_start": now if has_ss else None,
                    "cam_secs": 0, "ss_secs": 0,
                    "comb_start": now if (has_cam or has_ss) else None, "comb_secs": 0,
                }
            else:
                session = self.active_sessions.get(key)
                if session:
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
        now = datetime.datetime.now(datetime.timezone.utc)
        for key, session in list(self.active_sessions.items()):
            guild_id, user_id = key
            elapsed = int((now - session["join_time"]).total_seconds())
            cam_tot = session["cam_secs"] + (int((now - session["cam_start"]).total_seconds()) if session["cam_start"] else 0)
            ss_tot = session["ss_secs"] + (int((now - session["ss_start"]).total_seconds()) if session["ss_start"] else 0)
            comb_tot = session["comb_secs"] + (int((now - session["comb_start"]).total_seconds()) if session["comb_start"] else 0)

            if elapsed > 0 or cam_tot > 0 or ss_tot > 0:
                db.add_vc_metrics(guild_id, user_id, vc_seconds=elapsed, cam_seconds=cam_tot, ss_seconds=ss_tot, cam_ss_seconds=comb_tot)
                session["join_time"] = now
                session["cam_secs"], session["ss_secs"], session["comb_secs"] = 0, 0, 0
                if session["cam_start"]: session["cam_start"] = now
                if session["ss_start"]: session["ss_start"] = now
                if session["comb_start"]: session["comb_start"] = now

    @flush_vc_sessions.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="stats", description="Displays tracked voice study stats.")
    async def stats_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        stats = db.get_user_vc_stats(interaction.guild.id, target.id)
        def fmt(s): return f"{s//3600}h {(s%3600)//60}m"
        embed = discord.Embed(title=f"⏱️ Voice Study Stats • {target.display_name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Server Rank", value=f"`#{stats['rank']}`", inline=True)
        embed.add_field(name="All-Time VC", value=fmt(stats["all_time_seconds"]), inline=True)
        embed.add_field(name="Breakdown", value=f"• **Today:** {fmt(stats['daily_seconds'])}\n• **This Week:** {fmt(stats['weekly_seconds'])}\n• **This Month:** {fmt(stats['monthly_seconds'])}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Displays leaderboard.")
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        rows = db.get_vc_leaderboard_all_rows(interaction.guild.id)
        if not rows:
            await interaction.response.send_message("✨ No records found.", ephemeral=True)
            return
        view = LeaderboardView(interaction.guild, rows)
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="vc-settings", description="Configures untracked voice channels and hours.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def vc_settings_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚙️ VC Tracker Admin Configuration", description="Use the selector below to exclude channels.", color=discord.Color.from_str("#f4c2c2"))
        await interaction.response.send_message(embed=embed, view=VcSettingsView(interaction.guild.id), ephemeral=True)


# ==============================================================================
# SECTION 6: TEMPVOICE COG (cogs/tempvoice.py)
# ==============================================================================

class TempVoiceNameModal(discord.ui.Modal, title="Rename Channel"):
    new_name = discord.ui.TextInput(label="New Name", style=discord.TextStyle.short, required=True, max_length=100)
    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc: return await interaction.response.send_message("❌ Not in a VC.", ephemeral=True)
        await vc.edit(name=self.new_name.value.strip())
        await interaction.response.send_message("✅ Renamed room!", ephemeral=True)


class TempVoiceLimitModal(discord.ui.Modal, title="Set Limit"):
    limit_val = discord.ui.TextInput(label="Limit (0-99)", style=discord.TextStyle.short, required=True, max_length=2)
    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc: return await interaction.response.send_message("❌ Not in a VC.", ephemeral=True)
        await vc.edit(user_limit=max(0, min(99, int(self.limit_val.value.strip()))))
        await interaction.response.send_message("✅ User limit updated!", ephemeral=True)


class TempVoiceTrustSelect(discord.ui.UserSelect):
    def __init__(self, action: str):
        self.action = action
        super().__init__(placeholder=f"Select member to {action}...", min_values=1, max_values=1)
    async def callback(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc: return await interaction.response.send_message("❌ Not in a VC.", ephemeral=True)
        target = self.values[0]
        if self.action == "trust":
            await vc.set_permissions(target, connect=True, view_channel=True)
            await interaction.response.send_message(f"✅ Trusted {target.mention}.", ephemeral=True)
        elif self.action == "kick":
            await target.move_to(None)
            await interaction.response.send_message(f"👢 Kicked {target.mention}.", ephemeral=True)


class TempVoiceTrustView(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=60)
        self.add_item(TempVoiceTrustSelect(action))


class TempVoiceControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Name", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="tv_name", row=0)
    async def btn_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempVoiceNameModal())

    @discord.ui.button(label="Limit", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="tv_limit", row=0)
    async def btn_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempVoiceLimitModal())

    @discord.ui.button(label="Trust", style=discord.ButtonStyle.success, emoji="✅", custom_id="tv_trust", row=1)
    async def btn_trust(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select member:", view=TempVoiceTrustView("trust"), ephemeral=True)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢", custom_id="tv_kick", row=1)
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select member:", view=TempVoiceTrustView("kick"), ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="tv_delete", row=2)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc: return await interaction.response.send_message("❌ Not in a VC.", ephemeral=True)
        db.delete_temp_channel(vc.id)
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
                    if ch: await ch.delete()
                    db.delete_temp_channel(row["channel_id"])

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        config = db.get_tempvoice_config(guild.id)
        if config.get("hub_channel_id") and after.channel and after.channel.id == config["hub_channel_id"]:
            cat = guild.get_channel(config["category_id"]) or after.channel.category
            new_vc = await guild.create_voice_channel(name=f"{member.name}'s room", category=cat)
            db.register_temp_channel(new_vc.id, guild.id, member.id)
            await member.move_to(new_vc)
        if before.channel:
            meta = db.get_temp_channel(before.channel.id)
            if meta and len(before.channel.members) == 0:
                db.delete_temp_channel(before.channel.id)
                await before.channel.delete()

    @app_commands.command(name="tempvoice-setup", description="Configures TempVoice hub.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tempvoice_setup(self, interaction: discord.Interaction, hub_channel: discord.VoiceChannel, interface_channel: discord.TextChannel, category: Optional[discord.CategoryChannel] = None):
        db.update_tempvoice_config(interaction.guild.id, hub_channel_id=hub_channel.id, category_id=category.id if category else None, interface_channel_id=interface_channel.id)
        msg = await interface_channel.send(embed=discord.Embed(title="🎙️ TempVoice Panel", description="Use buttons below to control your room!"), view=TempVoiceControlView())
        db.update_tempvoice_config(interaction.guild.id, interface_message_id=msg.id)
        await interaction.response.send_message("✅ TempVoice configured!", ephemeral=True)


# ==============================================================================
# SECTION 7: UTILITY, AUTOROLE & AFK COGS
# ==============================================================================

class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="purge", description="Purges messages.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_cmd(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted `{len(deleted)}` messages.", ephemeral=True)


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
            await member.add_roles(*roles)


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

        # Check if author was AFK
        afk_data = db.get_afk(message.guild.id, message.author.id)
        if afk_data:
            db.remove_afk(message.guild.id, message.author.id)
            try:
                await message.channel.send(f"Welcome back {message.author.mention}! I've removed your AFK status.", delete_after=10)
            except Exception:
                pass

        # Check if author pinged someone who is AFK
        for mentioned in message.mentions:
            target_afk = db.get_afk(message.guild.id, mentioned.id)
            if target_afk:
                embed = discord.Embed(title=f"💤 {mentioned.display_name} is AFK", description=f"**Reason:** {target_afk['reason']}\n*Since {target_afk['timestamp']}*", color=discord.Color.orange())
                await message.channel.send(embed=embed, delete_after=15)


# ==============================================================================
# SECTION 8: CHALLENGE VCS & POMODORO TASKS
# ==============================================================================

class ChallengeVCsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="challenge-vc-setup", description="Designates Cam/SS challenge VCs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def challenge_vc_setup(self, interaction: discord.Interaction, channel: discord.VoiceChannel, challenge_type: str, grace_seconds: int = 30):
        db.set_challenge_vc(channel.id, interaction.guild.id, challenge_type.lower(), grace_seconds)
        await interaction.response.send_message(f"✅ Configured {channel.mention} as {challenge_type.upper()}-Only.", ephemeral=True)


class PomodoroTasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="task", description="Task manager.")
    async def task_cmd(self, interaction: discord.Interaction, action: str, title: Optional[str] = None, due: Optional[str] = None):
        if action.lower() == "add":
            db.add_user_task(interaction.user.id, title or "Task", due)
            await interaction.response.send_message(f"✅ Added task: **{title}**", ephemeral=True)
        elif action.lower() == "list":
            tasks = db.get_user_tasks(interaction.user.id)
            embed = discord.Embed(title="📝 Your Tasks", description="\n".join([f"• {t['title']}" for t in tasks if t["completed"] == 0]) or "No active tasks!", color=discord.Color.blurple())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pomodoro", description="Pomodoro timer.")
    async def pomodoro_cmd(self, interaction: discord.Interaction, work_mins: int = 50, break_mins: int = 10):
        import asyncio
        await interaction.response.send_message(f"🍅 Pomodoro started! Focus for {work_mins}m.")
        await asyncio.sleep(work_mins * 60)
        await interaction.followup.send(f"🔔 {interaction.user.mention}, break time!")


# ==============================================================================
# SECTION 9: HELP COMMAND COG
# ==============================================================================

class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Moderation", emoji="🛡️", value="mod"),
            discord.SelectOption(label="Welcome System", emoji="🌸", value="welcome"),
            discord.SelectOption(label="VC Tracking", emoji="⏱️", value="vctracker"),
            discord.SelectOption(label="TempVoice", emoji="🎙️", value="tempvoice"),
            discord.SelectOption(label="Study & Tasks", emoji="🍅", value="study"),
            discord.SelectOption(label="Utility & AFK", emoji="⚙️", value="utility"),
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
            embed.title = "⏱️ VC Tracking"
            embed.description = "• `/stats`, `/leaderboard`, `/vc-settings`"
        elif val == "tempvoice":
            embed.title = "🎙️ TempVoice"
            embed.description = "• `/tempvoice-setup`"
        elif val == "study":
            embed.title = "🍅 Study & Tasks"
            embed.description = "• `/task`, `/pomodoro`, `/challenge-vc-setup`"
        elif val == "utility":
            embed.title = "⚙️ Utility & AFK"
            embed.description = "• `/purge`, `/autorole-setup`, `/afk`"
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
# SECTION 10: MAIN BOT INITIALIZATION (main.py)
# ==============================================================================

class ModWelcomeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
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
