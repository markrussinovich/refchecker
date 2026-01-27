import sqlite3
conn = sqlite3.connect('backend/refchecker_history.db')
cursor = conn.cursor()
cursor.execute("UPDATE llm_configs SET model = 'claude-sonnet-4-20250514' WHERE id = 1")
conn.commit()
print('Updated model name')
cursor.execute('SELECT id, name, model FROM llm_configs')
for row in cursor.fetchall():
    print(row)
conn.close()
