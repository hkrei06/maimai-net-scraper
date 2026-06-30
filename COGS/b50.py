import asyncio
import io

import discord
from discord import app_commands
from discord.ext import commands

from scripts import b50, render, scrap


class B50Cog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_unload(self):
        await render.close()

    # ──────────────────────────────────────────────
    # /top
    # ──────────────────────────────────────────────
    @staticmethod
    def _build_payload() -> tuple[dict, list[str]]:
        """Fetch + parse + enrich the ratingTargetMusic page (blocking).

        Mirrors b50.main()'s pipeline (reusing its scraping/enrichment) but
        returns the render payload instead of writing an image to disk.
        """
        html = scrap.fetch_html(b50.RATING_URL, referer=f"{scrap.MOBILE}/home/")
        new, old = b50.parse_rating_target(html)
        index = b50._build_index()
        unmatched: list[str] = []
        b50.enrich(new, index, unmatched)
        b50.enrich(old, index, unmatched)
        total_rating = sum(c["rating"] for c in new) + sum(c["rating"] for c in old)
        payload = {"total_rating": total_rating, "new_charts": new, "old_charts": old}
        return payload, unmatched

    @app_commands.command(name="top", description="Render your maimai best-50 as an image")
    async def top(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not scrap.CLAL:
            await interaction.followup.send("❌ Bot is missing MAIMAI_CLAL.")
            return

        try:
            payload, _ = await asyncio.to_thread(self._build_payload)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch b50 data: {e}")
            return

        try:
            png = await render.render_b50_card(payload)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to render b50 image: {e}")
            return

        file = discord.File(io.BytesIO(png), filename="b50.png")
        content = f"🎵 **Best 50** • Rating **{payload['total_rating']}**"
        await interaction.followup.send(content=content, file=file)


async def setup(bot):
    await bot.add_cog(B50Cog(bot))
