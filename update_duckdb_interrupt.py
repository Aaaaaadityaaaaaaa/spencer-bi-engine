import sys
import re

with open('backend/services/duckdb_manager.py', 'r', encoding='utf-8') as f:
    content = f.read()

interrupt_method = """    def interrupt_session(self, session_id: str):
        \"\"\"Instantly interrupts any running query on this session's connection.\"\"\"
        if session_id in self._conns:
            self._conns[session_id].interrupt()
            logger.info(f"Interrupted running query on session: {session_id}")

    def close_and_delete_session"""

content = content.replace("    def close_and_delete_session", interrupt_method)

with open('backend/services/duckdb_manager.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Added interrupt_session to duckdb_manager")
