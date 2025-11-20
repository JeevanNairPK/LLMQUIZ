import mimetypes
try:
    import magic as _magic_lib
except Exception:
    _magic_lib = None

def detect_mime(path_or_bytes, filename=None):
    # If python-magic available, use it
    if _magic_lib:
        if isinstance(path_or_bytes, (str,)):
            return _magic_lib.from_file(path_or_bytes, mime=True)
        else:
            # bytes: use from_buffer
            return _magic_lib.from_buffer(path_or_bytes, mime=True)
    # Fallback: use filename extension
    if filename:
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"
    return "application/octet-stream"
