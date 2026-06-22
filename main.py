from fastapi import FastAPI

from controllers.course_controller import CourseController

app = FastAPI(title="Course Extractor API")

app.include_router(CourseController().router)


@app.get("/")
async def root():
    return {"message": "Course Extractor API"}
