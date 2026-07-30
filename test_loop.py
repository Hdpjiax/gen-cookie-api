import asyncio
import sys
import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def main():
    print(f"Loop is: {type(asyncio.get_running_loop())}")
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=8001, loop="asyncio")
    server = uvicorn.Server(config)
    
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(2)
    server.should_exit = True
    await task

if __name__ == "__main__":
    asyncio.run(main())
