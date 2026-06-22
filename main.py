from fastapi import FastAPI

from extractor.controller import router as course_router

app = FastAPI(title="Course Extractor API")

app.include_router(course_router)


@app.get("/")
async def root():
    return {"message": "Course Extractor API"}