import sqlite3
conn = sqlite3.connect("backend/refchecker_history.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print("Tables:", tables)

if 'verification_cache' in tables:
    cursor.execute("SELECT COUNT(*) FROM verification_cache")
    print("Cache entries:", cursor.fetchone()[0])
    cursor.execute("DELETE FROM verification_cache")
    conn.commit()
    print("Cache cleared!")
else:
    print("No verification_cache table found")
conn.close()
