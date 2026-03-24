import asyncio
import urllib3
from contextlib import asynccontextmanager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.logger import sse_endpoint
from infrastructure.database import init_db
from infrastructure.udp_listener import start_aria_udp
from infrastructure.session_poller import start_session_poller
from presentation.api.aria_router import router as aria_router
from presentation.api.avi_policy_router import router as avi_policy_router
from presentation.api.nsx_policy_router import router as nsx_policy_router
from presentation.api.connections_router import router as connections_router
from presentation.api.demo_router import router as demo_router
from presentation.api.idsp_router import router as idsp_router
from presentation.api.jit_router import router as jit_router
from presentation.api.sessions_router import router as sessions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    udp_task = asyncio.create_task(start_aria_udp())
    poller_task = asyncio.create_task(start_session_poller())
    yield
    poller_task.cancel()
    udp_task.cancel()
    for task in (poller_task, udp_task):
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="VMware Zero Trust Mock", version="1.0.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="presentation/static"), name="static")
templates = Jinja2Templates(directory="presentation/templates")

app.include_router(idsp_router)
app.include_router(aria_router)
app.include_router(jit_router)
app.include_router(connections_router)
app.include_router(demo_router)
app.include_router(sessions_router)
app.include_router(avi_policy_router)
app.include_router(nsx_policy_router)


@app.get("/client-ip")
async def client_ip(request: Request) -> dict:
    """Return the caller's IP address — used to seed form fields."""
    host = request.client.host if request.client else "127.0.0.1"
    return {"ip": host}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/events")
async def sse_events(request: Request):
    return await sse_endpoint(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
