from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


class AccountStateStore:
    def __init__(self, db_path: Path, backup_dir: Path) -> None:
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS instances (
                    instance_number INTEGER PRIMARY KEY,
                    credentials TEXT NOT NULL DEFAULT '',
                    instance_name TEXT NOT NULL DEFAULT '',
                    profile_name TEXT NOT NULL DEFAULT '',
                    preview_updated_at TEXT NOT NULL DEFAULT '',
                    run_state TEXT NOT NULL DEFAULT '',
                    backend_profile_id TEXT NOT NULL DEFAULT '',
                    photo_upload_path TEXT NOT NULL DEFAULT '',
                    cover_upload_path TEXT NOT NULL DEFAULT '',
                    photo_upload_description TEXT NOT NULL DEFAULT '',
                    report_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_state(self, data: dict[str, Any]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        active_instances = {int(value) for value in data.get("active_instances", [])}
        deleted_instances = {int(value) for value in data.get("deleted_instances", [])}
        instance_ids = set(active_instances) | set(deleted_instances)

        keyed_fields = (
            "credentials",
            "instance_names",
            "profile_names",
            "preview_updated_at",
            "run_states",
            "instance_reports",
            "backend_profile_ids",
            "photo_upload_paths",
            "cover_upload_paths",
            "photo_upload_descriptions",
        )
        for field_name in keyed_fields:
            values = data.get(field_name, {})
            if isinstance(values, dict):
                instance_ids.update(int(key) for key in values.keys())

        with self._connect() as conn:
            conn.execute("DELETE FROM instances")
            for instance_number in sorted(instance_ids):
                report = data.get("instance_reports", {}).get(instance_number, {})
                if not report:
                    report = data.get("instance_reports", {}).get(str(instance_number), {})
                conn.execute(
                    """
                    INSERT INTO instances (
                        instance_number,
                        credentials,
                        instance_name,
                        profile_name,
                        preview_updated_at,
                        run_state,
                        backend_profile_id,
                        photo_upload_path,
                        cover_upload_path,
                        photo_upload_description,
                        report_json,
                        active,
                        deleted,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        instance_number,
                        self._keyed_value(data, "credentials", instance_number),
                        self._keyed_value(data, "instance_names", instance_number),
                        self._keyed_value(data, "profile_names", instance_number),
                        self._keyed_value(data, "preview_updated_at", instance_number),
                        self._keyed_value(data, "run_states", instance_number),
                        self._keyed_value(data, "backend_profile_ids", instance_number),
                        self._keyed_value(data, "photo_upload_paths", instance_number),
                        self._keyed_value(data, "cover_upload_paths", instance_number),
                        self._keyed_value(data, "photo_upload_descriptions", instance_number),
                        json.dumps(report if isinstance(report, dict) else {}),
                        1 if instance_number in active_instances else 0,
                        1 if instance_number in deleted_instances else 0,
                        now,
                    ),
                )

            settings = {
                "browser_mode": str(data.get("browser_mode") or "pc"),
                "platform_mode": str(data.get("platform_mode") or "facebook"),
                "thread_count": str(data.get("thread_count") or "3"),
                "platform_states": json.dumps(data.get("platform_states", {})),
                "last_saved_at": now,
            }
            for key, value in settings.items():
                conn.execute(
                    """
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )

    def load_state(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM instances ORDER BY instance_number").fetchall()
            settings = {
                row["key"]: row["value"]
                for row in conn.execute("SELECT key, value FROM settings").fetchall()
            }

        if not rows and not settings:
            return None

        data: dict[str, Any] = {
            "credentials": {},
            "instance_names": {},
            "profile_names": {},
            "preview_updated_at": {},
            "run_states": {},
            "instance_reports": {},
            "backend_profile_ids": {},
            "photo_upload_paths": {},
            "cover_upload_paths": {},
            "photo_upload_descriptions": {},
            "browser_mode": settings.get("browser_mode", "pc"),
            "platform_mode": settings.get("platform_mode", "facebook"),
            "thread_count": settings.get("thread_count", "3"),
            "platform_states": {},
            "deleted_instances": [],
            "active_instances": [],
        }
        try:
            platform_states = json.loads(settings.get("platform_states", "{}"))
        except json.JSONDecodeError:
            platform_states = {}
        if isinstance(platform_states, dict):
            data["platform_states"] = platform_states

        for row in rows:
            instance_number = int(row["instance_number"])
            key = str(instance_number)
            self._put_if_value(data["credentials"], key, row["credentials"])
            self._put_if_value(data["instance_names"], key, row["instance_name"])
            self._put_if_value(data["profile_names"], key, row["profile_name"])
            self._put_if_value(data["preview_updated_at"], key, row["preview_updated_at"])
            self._put_if_value(data["run_states"], key, row["run_state"])
            self._put_if_value(data["backend_profile_ids"], key, row["backend_profile_id"])
            self._put_if_value(data["photo_upload_paths"], key, row["photo_upload_path"])
            self._put_if_value(data["cover_upload_paths"], key, row["cover_upload_path"])
            self._put_if_value(
                data["photo_upload_descriptions"],
                key,
                row["photo_upload_description"],
                keep_empty=True,
            )

            try:
                report = json.loads(row["report_json"] or "{}")
            except json.JSONDecodeError:
                report = {}
            if isinstance(report, dict) and report:
                data["instance_reports"][key] = report

            if int(row["deleted"] or 0):
                data["deleted_instances"].append(instance_number)
            if int(row["active"] or 0) and not int(row["deleted"] or 0):
                data["active_instances"].append(instance_number)

        return data

    def write_backup(self, data: dict[str, Any] | None = None) -> Path:
        if data is None:
            data = self.load_state() or {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"fbv1_accounts_{timestamp}.json"
        with backup_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        return backup_path

    def _keyed_value(self, data: dict[str, Any], field_name: str, instance_number: int) -> str:
        values = data.get(field_name, {})
        if not isinstance(values, dict):
            return ""
        value = values.get(instance_number, values.get(str(instance_number), ""))
        return str(value or "")

    def _put_if_value(self, target: dict[str, Any], key: str, value: Any, keep_empty: bool = False) -> None:
        text = str(value or "")
        if text or keep_empty:
            target[key] = text
