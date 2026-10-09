"""Dashboard, board pages, checkout and return."""

from fastapi import APIRouter, Request

from app.auth import CurrentUser
from app.templating import render

router = APIRouter()


@router.get("/", name="dashboard")
def dashboard(request: Request, user: CurrentUser):
    return render(request, "dashboard.html", boards=[])


@router.get("/me", name="my_boards")
def my_boards(request: Request, user: CurrentUser):
    return render(request, "dashboard.html", boards=[])
