import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from .logger import log
from .cog import MusicCog


class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states    = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await self.add_cog(MusicCog(self))
        try:
            synced = await self.tree.sync()
            log.info(f"Đã sync {len(synced)} slash command(s).")
        except Exception as e:
            log.error(f"Sync thất bại: {e}")

    async def on_ready(self):
        log.info(f"Bot online: {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/play để phát nhạc",
            )
        )


async def main():
    load_dotenv()
    token = os.getenv("TOKEN")
    if not token:
        raise ValueError("Thiếu TOKEN trong file .env!")
    async with MusicBot() as bot:
        await bot.start(token)


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot dừng (Ctrl+C).")
    except Exception as e:
        log.critical(f"Bot crash: {e}", exc_info=True)