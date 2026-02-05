import sqlite3
import os
db_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'refchecker', 'refchecker_history.db')
print(f"Database path: {db_path}")
print(f"Exists: {os.path.exists(db_path)}")
conn = sqlite3.connect(db_path)
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", [r[0] for r in cur.fetchall()])
try:
    cur = conn.execute("SELECT key, length(value_encrypted) FROM app_settings")
    print("App settings:", cur.fetchall())
except Exception as e:
    print("App settings error:", e)
