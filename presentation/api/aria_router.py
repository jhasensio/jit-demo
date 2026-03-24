from fastapi import APIRouter

router = APIRouter(prefix="/aria", tags=["VCF Operations"])


@router.get("/status")
async def aria_status() -> dict:
    return {"status": "listening", "port": 5140, "protocol": "UDP"}
