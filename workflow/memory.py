import sqlite3
import json
import os

DB_PATH = "cycling_memory.db"

def init_memory_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id TEXT PRIMARY KEY,
            data TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user_profile(user_id: str, profile_dict: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_profile (user_id, data) VALUES (?, ?)", 
                   (user_id, json.dumps(profile_dict)))
    conn.commit()
    conn.close()

def load_user_profile(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM user_profile WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return {"avg_speed": 22, "heart_rate_limit": 160, "pref": "asphalt"}

# Init on import
if not os.path.exists(DB_PATH):
    init_memory_db()
