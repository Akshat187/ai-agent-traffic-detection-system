"""
Real-Time Threat Stream WebSocket Router for SentinelTrace.
"""

import logging
from typing import Dict, List, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

router = APIRouter(tags=["WebSocket"])
logger = logging.getLogger("sentineltrace.ws")


class ConnectionManager:
    """Manages active WebSocket dashboard connections, optionally scoped by site_id."""

    def __init__(self):
        # Maps site_id ("ALL" or specific site_id) -> list of WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, site_id: str = "ALL") -> None:
        await websocket.accept()
        self.active_connections.setdefault(site_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, site_id: str = "ALL") -> None:
        conns = self.active_connections.get(site_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns and site_id in self.active_connections:
            del self.active_connections[site_id]

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        """Broadcasts a compact session verdict event to matching site_id and ALL subscribers."""
        target_site = payload.get("site_id")
        targets = list(self.active_connections.get("ALL", []))
        if target_site and target_site != "ALL":
            targets.extend(self.active_connections.get(target_site, []))

        stale: List[tuple] = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)

        if stale:
            for sid, conns in list(self.active_connections.items()):
                self.active_connections[sid] = [c for c in conns if c not in stale]
                if not self.active_connections[sid]:
                    del self.active_connections[sid]


ws_manager = ConnectionManager()


@router.websocket("/ws/sessions")
async def websocket_sessions_endpoint(
    websocket: WebSocket,
    site_id: str = Query("ALL"),
):
    """WebSocket stream for real-time session classification alerts."""
    await ws_manager.connect(websocket, site_id=site_id)
    try:
        while True:
            # Keep connection alive; ignore client pings/messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, site_id=site_id)
    except Exception:
        ws_manager.disconnect(websocket, site_id=site_id)
