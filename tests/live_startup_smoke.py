"""Explicit local startup smoke; briefly binds configured SIP/RTP ports."""
import asyncio
import contextlib
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import PhoneChat, load_config


async def main():
    config_file = ROOT / 'config.json'
    app = PhoneChat(load_config(config_file), config_file)
    task = asyncio.create_task(app.run())
    try:
        async with asyncio.timeout(180):
            while app.phone is None:
                if task.done():
                    await task
                await asyncio.sleep(.1)
            await asyncio.sleep(2)
            if task.done():
                await task
            assert app.phone.process.returncode is None
            assert app.tts.process.returncode is None
            assert not app.call, 'A real call arrived during the startup smoke'
            print('LIVE_STARTUP_OK', flush=True)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert app.phone.process.returncode is not None
    assert app.tts.process.returncode is not None
    print('CLEAN_SHUTDOWN_OK', flush=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    asyncio.run(main())
