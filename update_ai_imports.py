import sys
import re

with open('backend/routers/ai.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("from fastapi import APIRouter, HTTPException", "from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect")

with open('backend/routers/ai.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated ai.py imports")
