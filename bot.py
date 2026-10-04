import asyncio
import logging
import os

import aiohttp
import discord


API_URL = "https://rebootradio.uk/v3/api/stats"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("presenter-watcher")


class PresenterWatcher(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.none())
        self.channel_id = int(CHANNEL_ID) if CHANNEL_ID else None
        self.http_session: aiohttp.ClientSession | None = None
        self.poll_task: asyncio.Task | None = None
        self.presenter_name: str | None = None

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "RebootPresenterWatcher/1.0"},
        )

    async def on_ready(self) -> None:
        logger.info("Connected to Discord as %s", self.user)
        if self.channel_id is None:
            logger.error("DISCORD_CHANNEL_ID is not configured")
            await self.close()
            return
        if self.poll_task is None or self.poll_task.done():
            self.poll_task = asyncio.create_task(self.watch_presenter())

    async def fetch_presenter(self) -> str:
        if self.http_session is None:
            raise RuntimeError("HTTP session is not initialized")
        async with self.http_session.get(API_URL) as response:
            response.raise_for_status()
            payload = await response.json()
        name = payload.get("presenter", {}).get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("API response does not contain a presenter name")
        return name.strip()

    async def watch_presenter(self) -> None:
        # Establish a baseline on startup; only subsequent changes are announced.
        while not self.is_closed():
            try:
                current_name = await self.fetch_presenter()
                if self.presenter_name is None:
                    self.presenter_name = current_name
                    logger.info("Initial presenter: %s", current_name)
                elif current_name != self.presenter_name:
                    channel = self.get_channel(self.channel_id)
                    if channel is None:
                        channel = await self.fetch_channel(self.channel_id)
                    await channel.send(f"Presenter Changed: {current_name}")
                    logger.info("Presenter changed: %s -> %s", self.presenter_name, current_name)
                    self.presenter_name = current_name
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, discord.HTTPException) as exc:
                logger.warning("Presenter check failed: %s", exc)
            except Exception:
                logger.exception("Unexpected error while checking presenter")

            await asyncio.sleep(POLL_INTERVAL)

    async def close(self) -> None:
        if self.poll_task is not None:
            self.poll_task.cancel()
        if self.http_session is not None and not self.http_session.closed:
            await self.http_session.close()
        await super().close()


def main() -> None:
    if not DISCORD_TOKEN:
        raise SystemExit("Set DISCORD_TOKEN in the environment.")
    if not CHANNEL_ID:
        raise SystemExit("Set DISCORD_CHANNEL_ID in the environment.")
    if POLL_INTERVAL < 5:
        raise SystemExit("POLL_INTERVAL_SECONDS must be at least 5.")
    PresenterWatcher().run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
