import tarfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from core import config

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Hello World"}


@router.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@router.post("/upload")
async def upload_tar(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(config.ALLOWED_EXTENSION):
        raise HTTPException(
            status_code=400,
            detail=f"A {config.ALLOWED_EXTENSION} file is required",
        )

    config.UPLOAD_DIR.mkdir(exist_ok=True)
    dest = config.UPLOAD_DIR / Path(file.filename).name  # strip any path components

    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(config.CHUNK_SIZE):
                size += len(chunk)
                out.write(chunk)
    finally:
        await file.close()

    # Reject anything that isn't actually a valid tar archive.
    if not tarfile.is_tarfile(dest):
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid tar archive")

    return {"filename": dest.name, "size": size}
