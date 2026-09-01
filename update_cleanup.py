import sys
import re

with open('backend/services/cleanup_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the DROP TABLE logic with close_and_delete_session
old_sweep_logic = """        # AP-8: `entry` (untrusted dir name) is NEVER put in SQL. We derive its
        # identifier prefixes and filter the catalog snapshot in Python; only
        # catalog-sourced, quote-escaped names reach DROP.
        uuid_ = entry.replace("-", "_")
        prefixes = (f"t_{uuid_}_", f"backup_{uuid_}_")
        victims = [name for name in catalog_names if name.startswith(prefixes)]
        for name in victims:
            await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {_quote_ident(name)}")
            result["tables_dropped"] += 1
            reclaimed_any = True

        # Estimate reclaimed bytes before removing the dir.
        result["bytes_estimated"] += _dir_size(dir_path)
        shutil.rmtree(dir_path, ignore_errors=True)
        result["dirs_removed"] += 1
        reclaimed_any = True

        redis_manager.purge_session(entry)
        result["sessions_reaped"] += 1

    if reclaimed_any:
        # Reclaim freed space for reuse *within* spencer.db (the file may not
        # shrink on disk depending on the OS, but internal blocks are freed).
        await db_manager.run_readwrite("CHECKPOINT")"""

new_sweep_logic = """        # Remove session DB file and any open connections
        db_manager.close_and_delete_session(entry)
        
        # Estimate reclaimed bytes before removing the dir.
        result["bytes_estimated"] += _dir_size(dir_path)
        shutil.rmtree(dir_path, ignore_errors=True)
        result["dirs_removed"] += 1
        result["tables_dropped"] += 1 # Metric compatibility
        reclaimed_any = True

        redis_manager.purge_session(entry)
        result["sessions_reaped"] += 1

    if reclaimed_any:
        # Global DB checkpoint just in case
        await db_manager.run_readwrite("CHECKPOINT")"""

content = content.replace(old_sweep_logic, new_sweep_logic)

with open('backend/services/cleanup_service.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated cleanup_service.py to use per-session file deletion")
