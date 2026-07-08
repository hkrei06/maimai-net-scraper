import asyncio
import os
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

from scripts import checks

load_dotenv()

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)

# Dev lock: while under heavy development, only this Discord account may run any
# slash command. Replace with your own user ID (enable Developer Mode -> right
# click your name -> Copy User ID). Set to None to allow everyone.



@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    """Project-wide app-command error handler: friendly cooldown notice, log rest."""
    if await checks.notify_cooldown(interaction, error):
        return
    traceback.print_exception(type(error), error, error.__traceback__)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands: {[cmd.name for cmd in synced]}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

async def main():
    async with bot:
        await bot.load_extension("cogs.maimai")
        await bot.load_extension("cogs.friend")
        await bot.load_extension("cogs.b50")
        await bot.load_extension("cogs.score")
        await bot.start(os.getenv("TOKEN"))
asyncio.run(main())