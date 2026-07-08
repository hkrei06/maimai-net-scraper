"""
Reusable app-command checks / helpers shared across the cogs.

Keeps the cooldown policy (and its user-facing message) in one place so every
command can opt in with a single decorator and the whole project stays
consistent.
"""

from __future__ import annotations

import discord
from discord import app_commands


def user_cooldown(per: float = 30.0, rate: int = 1):
    """Per-user app-command cooldown decorator.

    ``rate`` uses allowed per ``per`` seconds, bucketed by Discord user id, so a
    future multi-account setup gives each user their own window. Reuse anywhere:

        @app_commands.command(...)
        @checks.user_cooldown()          # 1 use / 30s per user
        async def some_command(self, interaction, ...):
    """
    return app_commands.checks.cooldown(rate, per, key=lambda i: i.user.id)


async def notify_cooldown(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> bool:
    """Send a friendly ephemeral notice for a cooldown hit.

    Returns ``True`` if it handled the error (it was a cooldown), else ``False``
    so the caller can fall through to its normal error handling. Wire once on the
    command tree (see bot.py) and every ``user_cooldown`` command is covered.
    """
    if not isinstance(error, app_commands.CommandOnCooldown):
        return False
    msg = f"⏳ On cooldown — try again in {error.retry_after:.0f}s."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
    return True