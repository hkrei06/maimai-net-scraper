import asyncio
import io

import discord
from discord import app_commands
from discord.ext import commands

from scripts import render, scrap, songdb


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
    @app_commands.describe(name="Song name to search for (fuzzy/semantic)")
    @app_commands.autocomplete(name=song_autocomplete)
    async def score(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        # 1) Semantic (fuzzy) search over the bundled static data.
        song = None if not name.strip() else songdb.best_match(name)
        if song is None:
            await interaction.followup.send("song not found, please try again")
            return

        # 2) Start from the static difficulty data (level + constant + designer).
        difficulties = [dict(d) for d in song["difficulties"]]
        by_diff = {d["diff"]: d for d in difficulties}
        for d in difficulties:
            d.setdefault("score", None)
            d.setdefault("playcount", None)

        # 3) Overlay the user's live scores from maimaidx-eng.com. The song-list
        #    idx are cached and reused across commands; fetch_live_detail_by_name
        #    transparently refreshes them if they've expired.
        score_note = ""
        try:
            detail = await asyncio.to_thread(scrap.fetch_live_detail_by_name, song["title"], True)
            if detail:
                for live in detail["difficulties"]:
                    target = by_diff.get(live["diff"])
                    if target:
                        target["score"] = live.get("score")
                        target["playcount"] = live.get("playcount")
            else:
                score_note = " (no live scores found for this title)"
        except Exception as e:
            # Live scrape is best-effort; still render the static card.
            score_note = f" (live scores unavailable: {e})"

        # 4) Render the card image. The player profile header is best-effort.
        render_song = dict(song)
        render_song["jacket"] = songdb.jacket_data_uri(song["image_url"])
        try:
            profile = await asyncio.to_thread(scrap.get_profile)
        except Exception:
            profile = None
        try:
            png = await render.render_score_card(render_song, difficulties, name, profile)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to render score card: {e}")
            return

        file = discord.File(io.BytesIO(png), filename="score.png")
        content = f"🎵 **{song['title']}**{score_note}"
        await interaction.followup.send(content=content, file=file)


async def setup(bot):
    await bot.add_cog(MaimaiCog(bot))
