import sys
import os
from dotenv import load_dotenv
load_dotenv('.env')

sys.path.insert(0, os.getcwd())
from database import Database

db = Database()
logs = db.get_recent_logs(50)
for log in logs:
    print(f"{log['timestamp']} | {log['event_type']} | {log['message']} | {log.get('data_json')}")
