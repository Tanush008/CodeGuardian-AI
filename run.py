import sys
import asyncio
import uvicorn

# This is a crucial fix for Windows to allow subprocesses (like the MCP server) to run properly
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    # We run uvicorn programmatically so that our event loop policy takes effect
    # before uvicorn initializes the server.
    uvicorn.run("app.core.webhook:app", host="127.0.0.1", port=8000)
