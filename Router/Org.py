# from fastapi import Depends, HTTPException, status, APIRouter
# from sqlalchemy import select
# from sqlalchemy.orm import Session
# import uuid, re, unicodedata
# from datetime import datetime
# from pydantic import BaseModel, Field

# from App.database import get_database
# from App.dependencies import get_current_user
# from Router.Eu import Membership, MembershipRole, Organization, Role
# from Router.Users import User

# router = APIRouter()

# class OrganizationCreate(BaseModel):
#     name: str = Field(
#         min_length=3,
#         max_length=150,
#     )

# class OrganizationResponse(BaseModel):
#     id: uuid.UUID
#     name: str
#     slug: str
#     owner_role: str
#     created_at: datetime

# def create_slug(name: str) -> str:
#     normalized_name = unicodedata.normalize( "NFKD", name )
#     normalized_name = normalized_name.encode("ascii", "ignore").decode("ascii")
#     return re.sub( r"[^a-z0-9]+", "-", normalized_name.lower() ).strip("-")

# @router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
# def criarOrganizacao(organization_data: OrganizationCreate, current_user: User = Depends(get_current_user), database: Session = Depends(get_database)):
#     existing_membership = database.scalar(select(Membership).where( Membership.user_id == current_user.id ))
#     if existing_membership:
#         raise HTTPException(
#             status_code=status.HTTP_409_CONFLICT,
#             detail="Usuário já vinculado a uma organização",
#         )
#     slug = create_slug(organization_data.name)
#     existing_organization = database.scalar(select(Organization).where( Organization.slug == slug ))
#     if existing_organization:
#         raise HTTPException(
#             status_code=status.HTTP_409_CONFLICT,
#             detail="Organização já cadastrada",
#         )
#     organization = Organization( name=organization_data.name, slug=slug)
#     database.add(organization)
#     database.flush()
#     membership = Membership(
#         organization_id=organization.id,
#         user_id=current_user.id,
#         job_title="Proprietário",
#     )
#     database.add(membership)
#     database.flush()
#     owner_role = Role(
#         organization_id=organization.id,
#         name="Proprietário",
#         code="owner",
#     )
#     database.add(owner_role)
#     database.flush()
#     membership_role = MembershipRole(
#         membership_id=membership.id,
#         role_id=owner_role.id,
#     )
#     database.add(membership_role)
#     database.commit()
#     database.refresh(organization)
#     return {
#         "id": organization.id,
#         "name": organization.name,
#         "slug": organization.slug,
#         "owner_role": owner_role.code,
#         "created_at": organization.created_at,
#     }