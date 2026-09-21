# ---------------------------------------------------------
# EU (usuário autenticado)
# ---------------------------------------------------------

from fastapi import APIRouter, Depends

from App.dependencies import get_current_user
from Router.Usuarios.CriarUsers import User, UserResponse


router = APIRouter()


@router.get("/", response_model=UserResponse)
def eu(
    user: User = Depends(get_current_user),
):
    return user