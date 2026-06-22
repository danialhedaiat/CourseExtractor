from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_name: Mapped[str] = mapped_column(String, nullable=False)
    zip_file_path: Mapped[str] = mapped_column(String, nullable=False)
