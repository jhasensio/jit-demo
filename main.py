import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.logger import sse_endpoint
from infrastructure.udp_listener import start_aria_udp
from presentation.api.aria_router import router as aria_router
from presentation.api.connections_router import router as connections_router
from presentation.api.idsp_router import router as idsp_router
from presentation.api.jit_router import router as jit_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(start_aria_udp())
    yield
    task.cancel()
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/events")
async def sse_events(request: Request):
    return await sse_endpoint(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
