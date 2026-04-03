import discord
from discord import app_commands
from discord.ext import commands
from scrapv2 import fetch_recent_scores, fetch_song_by_name, fetch_song_detail

class MaimaiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ──────────────────────────────────────────────
    # /recent
    # ──────────────────────────────────────────────
    @app_commands.command(name="recent", description="Show your 20 most recent maimai plays")
    async def recent(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            plays = await fetch_recent_scores(20)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch recent scores: {e}")
            return

        if not plays:
            await interaction.followup.send("No recent plays found.")
            return

        embed = discord.Embed(
            title="🎵 Recent Plays",
            color=0x51bcf3
        )

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
                inline=False
            )

        embed.set_footer(text=f"Showing {len(plays)} recent plays")
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────────
    # /score
    # ──────────────────────────────────────────────
    @app_commands.command(name="score", description="Look up your score for a specific song")
    @app_commands.describe(name="Song name to search for")
    async def score(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        try:
            results = await fetch_song_by_name(name)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to search songs: {e}")
            return

        if not results:
            await interaction.followup.send(f"No songs found matching `{name}`.")
            return

        try:
            detail = await fetch_song_detail(results[0]["idx"])
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch song detail: {e}")
            return

        embed = discord.Embed(
            title=detail["title"],
            color=0x51bcf3
        )
        embed.add_field(name="Artist", value=detail["artist"], inline=True)
        embed.add_field(name="Genre",  value=detail["genre"],  inline=True)
        embed.add_field(name="\u200b", value="\u200b",         inline=False)  # spacer

        for diff in detail["difficulties"]:
            score_val = diff.get("score") or "No score"
            embed.add_field(
                name=f"{diff['diff']} Lv.{diff['level']}",
                value=f"`{score_val}`",
                inline=True
            )

        embed.set_footer(text=f"Search: {name}")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(MaimaiCog(bot))