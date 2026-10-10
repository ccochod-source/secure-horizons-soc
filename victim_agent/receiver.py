"""A real local sink: only authenticated lab payloads, no GitHub calls."""
from pathlib import Path
import sqlite3
import threading
from .storage import now


class DemoReceiver:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent_id TEXT NOT NULL, content TEXT NOT NULL, received_at TEXT NOT NULL)")
        self.db.commit()

    def receive(self, payload):
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO receipts VALUES (?, ?, ?, ?, ?)",
                            (str(payload.attempt_id), str(payload.run_id), payload.agent_id, payload.content, now()))
            self.db.commit()
        return {"received": True, "receipt_id": str(payload.attempt_id)}

    def list_receipts(self):
        with self.lock:
            # Payloads remain local; API returns no raw secret values.
            rows = self.db.execute("SELECT id, run_id, agent_id, received_at, length(CAST(content AS BLOB)) FROM receipts ORDER BY received_at DESC LIMIT 100").fetchall()
        return [{"receipt_id": r[0], "run_id": r[1], "agent_id": r[2], "received_at": r[3], "bytes": r[4]} for r in rows]

    def close(self):
        self.db.close()
