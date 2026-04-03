import discord
from discord import app_commands
from discord.ext import commands
from scrapv2 import fetch_friend_list

class FriendsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ──────────────────────────────────────────────
    # /friend
    # ──────────────────────────────────────────────
    @app_commands.command(name="friend", description="Show your maimai friend list with ratings")
    async def friend(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            friends = await fetch_friend_list()
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch friend list: {e}")
            return

        if not friends:
            await interaction.followup.send("No friends found.")
            return

        embed = discord.Embed(
            title="👥 Friend List",
            color=0x51bcf3
        )

        for i, friend in enumerate(friends, 1):
            embed.add_field(
                name=f"{i}. {friend['name']}",
                value=f"Rating: `{friend['rating']}`",
                inline=True
            )

        embed.set_footer(text=f"{len(friends)} friends total")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(FriendsCog(bot))