import json
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, agent TEXT, level TEXT,
  symbol TEXT, msg TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS equity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, equity REAL, cash REAL, note TEXT);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT, chain TEXT, token TEXT, pair TEXT,
  symbol TEXT, url TEXT,
  opened_at REAL, entry_mid REAL, entry_price REAL, qty REAL, size_usd REAL,
  entry_slip_bps REAL, entry_fee REAL, entry_liq REAL, entry_reason TEXT, rug_summary TEXT,
  size_reason TEXT, peak_price REAL, last_price REAL, last_liq REAL, missing INTEGER DEFAULT 0,
  closed_at REAL, exit_mid REAL, exit_price REAL, exit_slip_bps REAL, exit_fee REAL,
  proceeds REAL, pnl_usd REAL, pnl_pct REAL, exit_reason TEXT);
"""


class Store:
    """SQLite 저장소. 엔진 스레드와 웹 스레드가 같이 쓰므로 락으로 보호한다."""

    def __init__(self, path):
        if path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ── 공통 ──
    def _exec(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # ── kv ──
    def get(self, key, default=None):
        rows = self._rows('SELECT value FROM kv WHERE key=?', (key,))
        return json.loads(rows[0]['value']) if rows else default

    def set(self, key, value):
        self._exec('INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key, json.dumps(value)))

    # ── 이벤트(활동 피드) ──
    def add_event(self, ts, agent, level, symbol, msg, data=None):
        self._exec('INSERT INTO events(ts,agent,level,symbol,msg,data) VALUES(?,?,?,?,?,?)',
                   (ts, agent, level, symbol, msg, json.dumps(data or {}, ensure_ascii=False)))

    def events(self, limit=80):
        return self._rows('SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))

    def count_events(self):
        return self._rows('SELECT COUNT(*) AS n FROM events')[0]['n']

    # ── 수익 곡선 ──
    def add_equity(self, ts, equity, cash, note):
        self._exec('INSERT INTO equity(ts,equity,cash,note) VALUES(?,?,?,?)', (ts, equity, cash, note))

    def equity_points(self, limit=2000):
        rows = self._rows('SELECT * FROM equity ORDER BY id DESC LIMIT ?', (limit,))
        return rows[::-1]

    # ── 거래 ──
    def insert_trade(self, row):
        cols = ','.join(row)
        cur = self._exec(f'INSERT INTO trades({cols}) VALUES({",".join("?" * len(row))})', tuple(row.values()))
        return cur.lastrowid

    def update_trade(self, trade_id, **fields):
        sets = ','.join(f'{k}=?' for k in fields)
        self._exec(f'UPDATE trades SET {sets} WHERE id=?', (*fields.values(), trade_id))

    def open_trades(self):
        return self._rows("SELECT * FROM trades WHERE status='open' ORDER BY id")

    def closed_trades(self, limit=100):
        return self._rows("SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC, id DESC LIMIT ?", (limit,))

    def last_trade(self):
        rows = self._rows('SELECT * FROM trades ORDER BY MAX(opened_at, COALESCE(closed_at, 0)) DESC, id DESC LIMIT 1')
        return rows[0] if rows else None

    def all_closed(self):
        return self._rows("SELECT pnl_usd, entry_fee, exit_fee FROM trades WHERE status='closed' ORDER BY id")

    def reset(self):
        with self.lock:
            for t in ('kv', 'events', 'equity', 'trades'):
                self.db.execute(f'DELETE FROM {t}')
            self.db.commit()
