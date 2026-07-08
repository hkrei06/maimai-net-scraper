import asyncio
import io

import discord
from discord import app_commands
from discord.ext import commands

from scripts import checks, render, scrap, songdb


class MaimaiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_unload(self):
        await render.close()

    # ──────────────────────────────────────────────
    # /recent
    # ──────────────────────────────────────────────
    @app_commands.command(name="recent", description="Show your 20 most recent maimai plays")
    async def recent(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            plays = await asyncio.to_thread(scrap.fetch_recent_scores, 20)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch recent scores: {e}")
            return

        if not plays:
            await interaction.followup.send("No recent plays found.")
            return

        embed = discord.Embed(title="🎵 Recent Plays", color=0x51bcf3)
        for play in plays:
            title      = play.get("title", "Unknown")
            diff       = play.get("difficulty", "?")
            ach        = play.get("achievement", "?")
            date       = play.get("date", "?")
            level      = play.get("level", "?")
            new_record = "🆕 " if play.get("is_new_record") else ""
            embed.add_field(
                name=f"{new_record}{title}",
                value=f"`{diff}` Lv.**{level}** • {ach} • {date}",
                inline=False,
            )

        embed.set_footer(text=f"Showing {len(plays)} recent plays")
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────────
    # /score
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
        name="score",
        description="Search a song and show your highscores as an image card",
    )
    @checks.user_cooldown()  # 1 use / 17s per user
    @app_commands.describe(name="Song name to search for (fuzzy/semantic)")
    @app_commands.autocomplete(name=song_autocomplete)
    async def score(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        # 1) Semantic (fuzzy) search over the bundled static data to validate the
        #    typed name and resolve the header info (artist / genre / bpm / jacket).
        song = None if not name.strip() else songdb.best_match(name)
        if song is None:
            await interaction.followup.send("song not found, please try again")
            return

        # 2) Fetch the difficulty data (levels + scores) live from maimaidx-eng.com,
        #    and run the local prep — Chromium warm-up and the static jacket
        #    encoding — concurrently so they overlap the network round-trip. The
        #    browser is a shared singleton, so warm() is a no-op once launched.
        detail_task = asyncio.to_thread(scrap.fetch_live_detail_by_name, song["title"], True)
        jacket_task = asyncio.to_thread(songdb.jacket_data_uri, song["image_url"])
        warm_task = asyncio.create_task(render.warm())
        try:
            detail, jacket, _ = await asyncio.gather(detail_task, jacket_task, warm_task)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch scores: {e}")
            return

        if not detail or not detail["difficulties"]:
            await interaction.followup.send("No live data found for this song.")
            return

        # 3) Build the difficulty rows straight from the live data.
        css_by_diff = {name: css for _prefix, name, css in songdb.DIFFICULTIES}
        difficulties = [
            {
                "diff":      d["diff"],
                "css":       css_by_diff.get(d["diff"], ""),
                "level":     d.get("level", "?"),
                "score":     d.get("score"),
                "constant":  "",
                "playcount": None,
            }
            for d in detail["difficulties"]
        ]

        # 4) Render the card image.
        render_song = dict(song)
        render_song["jacket"] = jacket
        try:
            png = await render.render_score_card(render_song, difficulties, name)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to render score card: {e}")
            return

        file = discord.File(io.BytesIO(png), filename="score.png")
        content = f"🎵 **{song['title']}**"
        await interaction.followup.send(content=content, file=file)


async def setup(bot):
    await bot.add_cog(MaimaiCog(bot))
