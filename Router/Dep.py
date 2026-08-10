# from pydantic import BaseModel, ConfigDict, Field
# import uuid
# from datetime import datetime
# from sqlalchemy.orm import Mapped, mapped_column, Session
# from sqlalchemy.dialects.postgresql import ENUM, UUID
# from sqlalchemy import DateTime, ForeignKey, String, select
# from sqlalchemy.sql import func
# from fastapi import Depends, HTTPException, status, APIRouter

# from App.database import Base, get_database
# from App.dependencies import get_current_user
# from Router.Eu import Membership, MembershipRole,  Role
# from Router.Users import User

# router = APIRouter()

# class Department(Base):
#     __tablename__ = "departments"

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         primary_key=True,
#         default=uuid.uuid4,
#     )

#     organization_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("organizations.id"),
#         nullable=False,
#     )

#     parent_id: Mapped[uuid.UUID | None] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("departments.id"),
#         nullable=True,
#     )

#     name: Mapped[str] = mapped_column(
#         String(120),
#         nullable=False,
#     )

#     created_at: Mapped[datetime] = mapped_column(
#         DateTime(timezone=True),
#         server_default=func.now(),
#     )

# class DepartmentCreate(BaseModel):
#     name: str = Field(
#         min_length=2,
#         max_length=120,
#     )

# class DepartmentResponse(BaseModel):
#     id: uuid.UUID
#     organization_id: uuid.UUID
#     name: str
#     created_at: datetime
#     model_config = ConfigDict(from_attributes=True)

# @router.get( "/", response_model=list[DepartmentResponse])
# def listarDep(current_user: User = Depends(get_current_user), database: Session = Depends(get_database)):
#     membership = database.scalar(select(Membership).where(Membership.user_id == current_user.id))
#     if not membership:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Usuário sem organização",
#         )
#     departments = database.scalars(
#         select(Department)
#         .where(Department.organization_id == membership.organization_id)
#         .order_by(Department.name)
#     ).all()
#     return departments


# @router.post( "/departments", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
# def create_department(
#     department_data: DepartmentCreate,
#     current_user: User = Depends(get_current_user),
#     database: Session = Depends(get_database),
# ):
#     membership_data = database.execute(
#         select(
#             Membership,
#             Role.code,
#         )
#         .join(
#             MembershipRole,
#             MembershipRole.membership_id == Membership.id,
#         )
#         .join(
#             Role,
#             Role.id == MembershipRole.role_id,
#         )
#         .where(
#             Membership.user_id == current_user.id,
#         )
#     ).first()

#     if not membership_data:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Usuário sem organização",
#         )

#     membership, role_code = membership_data

#     if role_code != "owner":
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Usuário sem permissão",
#         )

#     existing_department = database.scalar(
#         select(Department).where(
#             Department.organization_id
#             == membership.organization_id,
#             Department.name
#             == department_data.name,
#         )
#     )

#     if existing_department:
#         raise HTTPException(
#             status_code=status.HTTP_409_CONFLICT,
#             detail="Departamento já cadastrado",
#         )

#     department = Department(
#         organization_id=membership.organization_id,
#         name=department_data.name,
#     )

#     database.add(department)
#     database.commit()
#     database.refresh(department)

#     return department