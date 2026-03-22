from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Director(Base):
    __tablename__ = "directors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(5), default="uk")
    currency: Mapped[str] = mapped_column(String(3), default="PLN")
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Warsaw")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    brigades: Mapped[list["Brigade"]] = relationship(back_populates="director")
    workers: Mapped[list["Worker"]] = relationship(back_populates="director")
    projects: Mapped[list["Project"]] = relationship(back_populates="director")
    work_types: Mapped[list["WorkType"]] = relationship(back_populates="director")
    invite_codes: Mapped[list["InviteCode"]] = relationship(back_populates="director")


class Brigade(Base):
    __tablename__ = "brigades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    director_id: Mapped[int] = mapped_column(ForeignKey("directors.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    director: Mapped["Director"] = relationship(back_populates="brigades")
    members: Mapped[list["BrigadeMember"]] = relationship(back_populates="brigade")
    invite_codes: Mapped[list["InviteCode"]] = relationship(back_populates="brigade")


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    director_id: Mapped[int] = mapped_column(ForeignKey("directors.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(5), default="uk")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    director: Mapped["Director"] = relationship(back_populates="workers")
    memberships: Mapped[list["BrigadeMember"]] = relationship(back_populates="worker")
    work_entries: Mapped[list["WorkEntry"]] = relationship(back_populates="worker")


class BrigadeMember(Base):
    __tablename__ = "brigade_members"
    __table_args__ = (UniqueConstraint("brigade_id", "worker_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brigade_id: Mapped[int] = mapped_column(ForeignKey("brigades.id"), nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="worker")  # 'brigadier' | 'worker'
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    brigade: Mapped["Brigade"] = relationship(back_populates="members")
    worker: Mapped["Worker"] = relationship(back_populates="memberships")


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    director_id: Mapped[int] = mapped_column(ForeignKey("directors.id"), nullable=False)
    brigade_id: Mapped[int] = mapped_column(ForeignKey("brigades.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="worker")  # 'brigadier' | 'worker'
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'director' | 'brigadier'
    created_by_id: Mapped[int] = mapped_column(Integer, nullable=False)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("workers.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    director: Mapped["Director"] = relationship(back_populates="invite_codes")
    brigade: Mapped["Brigade"] = relationship(back_populates="invite_codes")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    director_id: Mapped[int] = mapped_column(ForeignKey("directors.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    director: Mapped["Director"] = relationship(back_populates="projects")
    buildings: Mapped[list["Building"]] = relationship(back_populates="project")
    project_rates: Mapped[list["ProjectRate"]] = relationship(back_populates="project")


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    project: Mapped["Project"] = relationship(back_populates="buildings")
    elements: Mapped[list["Element"]] = relationship(back_populates="building")


class Element(Base):
    __tablename__ = "elements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    element_type: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    building: Mapped["Building"] = relationship(back_populates="elements")
    work_entries: Mapped[list["WorkEntry"]] = relationship(back_populates="element")


class WorkType(Base):
    __tablename__ = "work_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    director_id: Mapped[int] = mapped_column(ForeignKey("directors.id"), nullable=False)
    name_uk: Mapped[str] = mapped_column(String(255), nullable=False)
    name_pl: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)  # 'm2' | 'mp' | 'h'
    default_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    director: Mapped["Director"] = relationship(back_populates="work_types")
    project_rates: Mapped[list["ProjectRate"]] = relationship(back_populates="work_type")

    def get_name(self, lang: str) -> str:
        return getattr(self, f"name_{lang}", self.name_uk)


class ProjectRate(Base):
    __tablename__ = "project_rates"
    __table_args__ = (UniqueConstraint("project_id", "work_type_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    work_type_id: Mapped[int] = mapped_column(ForeignKey("work_types.id"), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="project_rates")
    work_type: Mapped["WorkType"] = relationship(back_populates="project_rates")


class WorkEntry(Base):
    __tablename__ = "work_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), nullable=False)
    element_id: Mapped[int] = mapped_column(ForeignKey("elements.id"), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    worker: Mapped["Worker"] = relationship(back_populates="work_entries")
    element: Mapped["Element"] = relationship(back_populates="work_entries")
    items: Mapped[list["WorkEntryItem"]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class WorkEntryItem(Base):
    __tablename__ = "work_entry_items"
    __table_args__ = (UniqueConstraint("entry_id", "work_type_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("work_entries.id", ondelete="CASCADE"), nullable=False)
    work_type_id: Mapped[int] = mapped_column(ForeignKey("work_types.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    rate_applied: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    entry: Mapped["WorkEntry"] = relationship(back_populates="items")
    work_type: Mapped["WorkType"] = relationship()
