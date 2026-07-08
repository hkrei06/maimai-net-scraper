import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from scripts import checks, scrap, songdb


class ScoreCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ──────────────────────────────────────────────
    # /scoreimage
    # ──────────────────────────────────────────────
    async def song_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Suggest songs as the user types the ``name`` argument.

        Backed by the same fuzzy search as the command itself. Discord caps this
        at 25 choices and 100 chars per field; ranking need not be perfect as long
        as the intended song appears somewhere in the list.
        """
        if not current.strip():
            return []
        try:
            results = songdb.search(current, limit=25)
        except Exception:
            return []
        return [
            app_commands.Choice(
                name=f"{s['title']} ({s['genre']})"[:100],
                value=s["title"][:100],
            )
            for s in results
        ]

    @app_commands.command(
        name="scoreimage",
        description="Search a song and show your highscores as a Discord embed",
    )
    @checks.user_cooldown()  # 1 use / 17s per user
    @app_commands.describe(name="Song name to search for (fuzzy/semantic)")
    @app_commands.autocomplete(name=song_autocomplete)
    async def scoreimage(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        # 1) Semantic (fuzzy) search over the bundled static data to validate the
        #    typed name and resolve the header info (artist / genre / bpm / jacket).
        song = None if not name.strip() else songdb.best_match(name)
        if song is None:
            await interaction.followup.send("song not found, please try again")
            return

        # 2) Fetch the difficulty data (levels + scores) live from maimaidx-eng.com.
        try:
            detail = await asyncio.to_thread(scrap.fetch_live_detail_by_name, song["title"], True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch scores: {e}")
            return

        if not detail or not detail["difficulties"]:
            await interaction.followup.send("No live data found for this song.")
            return

        # 3) Build the embed straight from the live data (no image render).
        embed = discord.Embed(
            title=song["title"],
            description=song.get("artist", ""),
            color=0x51bcf3,
        )
        for d in detail["difficulties"]:
            level = d.get("level", "?")
            score = d.get("score") or "No play"
            embed.add_field(
                name=d["diff"],
                value=f"Lv.**{level}** • {score}",
                inline=False,
            )

        tags = []
        if song.get("genre"):
            tags.append(song["genre"])
        if song.get("bpm"):
            tags.append(f"BPM {song['bpm']}")
        if tags:
            embed.set_footer(text=" • ".join(tags))

        # 4) Attach the local jacket as the embed thumbnail, if present.
        jacket = songdb.jacket_path(song["image_url"])
        if jacket:
            fname = f"jacket{jacket.suffix or '.png'}"
            file = discord.File(str(jacket), filename=fname)
            embed.set_thumbnail(url=f"attachment://{fname}")
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ScoreCog(bot))
