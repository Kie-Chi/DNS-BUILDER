from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..wsm import manager

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # just echo the message back to the client
            await websocket.send_text(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)