"""Single source of truth for the generated-code security gate.

Both the code-generator's sanitizer and the validator's AST preflight import
THESE constants. They used to hold two hand-copied, divergent lists (the
sanitizer knew about vars/getattr/setattr/delattr; the live validator gate did
not) — code could pass one gate and fail the other, and a gap in either was
invisible. One set, imported twice, cannot drift.
"""

# Module roots that generated Manim code may never import.
FORBIDDEN_MODULES = frozenset({
    "os", "subprocess", "socket", "sys", "importlib", "shutil",
    "pathlib", "ctypes", "multiprocessing", "threading", "pty",
    "signal", "resource", "fcntl", "tempfile", "http", "urllib",
    "ftplib", "smtplib", "telnetlib", "xmlrpc",
})

# Builtins that generated Manim code may never reference. Union of the two
# previously divergent lists (sanitizer ∪ validator).
FORBIDDEN_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "breakpoint",
    "memoryview", "vars", "globals", "locals",
    "getattr", "setattr", "delattr",
})
