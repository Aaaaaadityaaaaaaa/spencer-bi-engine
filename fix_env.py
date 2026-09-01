import sys

# Read removing nulls
with open('backend/.env', 'rb') as f:
    raw = f.read()

# Replace \x00 with nothing
clean = raw.replace(b'\x00', b'')

with open('backend/.env', 'wb') as f:
    f.write(clean)
print("Cleaned .env")
