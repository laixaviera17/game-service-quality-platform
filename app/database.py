from __future__ import annotations

import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "game_quality.db"


def database_path() -> Path:
    path = Path(os.getenv("GAME_QA_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT PRIMARY KEY,
                nickname TEXT NOT NULL,
                gem_balance INTEGER NOT NULL DEFAULT 0 CHECK (gem_balance >= 0)
            );

            CREATE TABLE IF NOT EXISTS activities (
                activity_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                reward_gems INTEGER NOT NULL CHECK (reward_gems > 0),
                stock INTEGER NOT NULL CHECK (stock >= 0),
                status TEXT NOT NULL CHECK (status IN ('active', 'inactive'))
            );

            CREATE TABLE IF NOT EXISTS reward_grants (
                grant_id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                reward_gems INTEGER NOT NULL CHECK (reward_gems > 0),
                status TEXT NOT NULL CHECK (status IN ('success', 'rejected')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (player_id) REFERENCES players(player_id),
                FOREIGN KEY (activity_id) REFERENCES activities(activity_id)
            );
            """
        )
