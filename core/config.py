from pathlib import Path

# Directory where uploaded archives are stored.
UPLOAD_DIR = Path("uploads")

# Read uploads in chunks so large archives don't get loaded fully into memory.
CHUNK_SIZE = 1024 * 1024  # 1 MiB

# Allowed file extension for uploads.
ALLOWED_EXTENSION = ".tar"
