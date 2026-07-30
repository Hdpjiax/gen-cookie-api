import asyncio
import sys

# Forzar el motor correcto en Windows antes de que Uvicorn arranque
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=8000, reload=False, loop="none")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
