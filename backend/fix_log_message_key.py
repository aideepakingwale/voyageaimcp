"""
Fix: KeyError "Attempt to overwrite 'message' in LogRecord"

Python's logging module reserves these keys in extra={} dict:
  message, msg, args, levelname, levelno, pathname, filename,
  module, exc_info, exc_text, stack_info, lineno, funcName,
  created, msecs, relativeCreated, thread, threadName,
  processName, process, name

Any of these passed in extra={} raises KeyError.
This script renames 'message' → 'user_msg' in all Python files.

Run from backend folder: python fix_log_message_key.py
"""
import os, re

BACKEND = os.path.dirname(os.path.abspath(__file__))

RESERVED = {
    "message", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "name",
}

# Safe rename mapping
RENAME = {
    '"message"': '"user_msg"',
    "'message'": "'user_msg'",
}

fixed_files  = []
fixed_count  = 0

for root, dirs, files in os.walk(BACKEND):
    # Skip venv, __pycache__, node_modules
    dirs[:] = [d for d in dirs if d not in ("venv", "__pycache__", ".git", "node_modules")]
    for fname in files:
        if not fname.endswith(".py"):
            continue
        path = os.path.join(root, fname)
        try:
            src = open(path, encoding="utf-8").read()
        except Exception:
            continue

        # Only touch lines that are inside a log.*/logger.* call with extra={}
        # Pattern: finds   "message": value   inside extra={...} blocks
        new_src = src
        n = 0
        for old, new in RENAME.items():
            # Match the key only when it appears inside an extra= dict context
            # (i.e. preceded by { or , on the same or previous line)
            pattern = re.compile(
                r'(extra\s*=\s*\{[^}]*?)' + re.escape(old) + r'(\s*:)',
                re.DOTALL
            )
            result, count = pattern.subn(r'\1' + new + r'\2', new_src)
            if count:
                new_src = result
                n += count

        if new_src != src:
            open(path, "w", encoding="utf-8").write(new_src)
            fixed_files.append(os.path.relpath(path, BACKEND))
            fixed_count += n
            print(f"  Fixed {n} occurrence(s) in {os.path.relpath(path, BACKEND)}")

print()
if fixed_files:
    print(f"Done. Fixed {fixed_count} log key(s) in {len(fixed_files)} file(s).")
else:
    print("No 'message' keys found in extra={} blocks — already clean.")

print()
print("Restart:  python run.py")
