"""Keep request-bound work alive only while its caller is connected."""

import asyncio

from fastapi import Request


async def while_connected(request: Request, work):
    async def disconnected():
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return

    operation = asyncio.create_task(work)
    connection = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait({operation, connection}, timeout=3540, return_when=asyncio.FIRST_COMPLETED)
        if operation in done:
            return await operation
        if connection in done:
            raise ConnectionError("Caller disconnected")
        raise TimeoutError
    finally:
        operation.cancel()
        connection.cancel()
        await asyncio.gather(operation, connection, return_exceptions=True)
