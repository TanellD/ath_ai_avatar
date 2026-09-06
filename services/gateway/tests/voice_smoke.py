"""Manual PTT smoke test against the running Compose stack (silence only)."""

import asyncio
import json
import uuid

import httpx
import websockets


async def receive_until(websocket, wanted: str) -> dict:  # noqa: ANN001
    async with asyncio.timeout(15):
        async for raw in websocket:
            event = json.loads(raw)
            print(event["type"], event.get("code", ""))
            if event["type"] == wanted:
                return event
    raise RuntimeError(f"WebSocket closed before {wanted}")


async def main() -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get("http://scenario-service:8050/scenarios")
        scenario_id = response.raise_for_status().json()["items"][0]["id"]
        response = await client.post(
            "http://localhost:8000/sessions", json={"scenario_id": scenario_id}
        )
        session_id = response.raise_for_status().json()["session_id"]

    capture_id = str(uuid.uuid4())
    async with websockets.connect(f"ws://localhost:8000/ws/session/{session_id}") as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "speech_start",
                    "capture_id": capture_id,
                    "interrupts": None,
                    "mode": "ptt",
                    "audio_format": "pcm_s16le",
                    "sample_rate": 16_000,
                    "num_channels": 1,
                }
            )
        )
        await receive_until(websocket, "speech_started")
        await websocket.send(b"\x00\x00" * 3_200)
        await websocket.send(json.dumps({"type": "speech_end", "capture_id": capture_id}))
        final = await receive_until(websocket, "transcript")
        if not final["is_final"]:
            raise RuntimeError("expected final transcript")


if __name__ == "__main__":
    asyncio.run(main())
