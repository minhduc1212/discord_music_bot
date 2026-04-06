import random
from typing import TYPE_CHECKING

import discord

from .models import LoopState

if TYPE_CHECKING:
    from .cog import MusicCog


class MusicView(discord.ui.View):
    def __init__(self, cog: "MusicCog"):
        super().__init__(timeout=None)
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice:
            await interaction.response.send_message(
                "❌ Bạn phải ở trong kênh thoại!", ephemeral=True
            )
            return False
        vc = interaction.guild.voice_client
        if vc and interaction.user.voice.channel != vc.channel:
            await interaction.response.send_message(
                "❌ Bạn phải ở cùng kênh với bot!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="mb:prev", row=0)
    async def btn_prev(self, interaction: discord.Interaction, _: discord.ui.Button):
        vc     = interaction.guild.voice_client
        gid    = interaction.guild.id
        q_data = self.cog.song_queues.get(gid)
        if not vc or not q_data or not q_data.get("now_playing"):
            return await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)
        current = q_data["now_playing"]
        current.stream_url = None
        q_data["queue"].insert(0, current)
        vc.stop()
        await interaction.response.send_message("🔄 Đã yêu cầu phát lại.", ephemeral=True)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="mb:pause", row=0)
    async def btn_pause(self, interaction: discord.Interaction, _: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Bot không trong voice.", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ Đã tạm dừng.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Đã tiếp tục.", ephemeral=True)
        else:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.primary, custom_id="mb:skip", row=0)
    async def btn_skip(self, interaction: discord.Interaction, _: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏩ Đã bỏ qua.", ephemeral=True)
        else:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)

    @discord.ui.button(emoji="🛑", style=discord.ButtonStyle.danger, custom_id="mb:stop", row=0)
    async def btn_stop(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.cleanup(interaction.guild)
        await interaction.response.send_message("🛑 Đã dừng và ngắt kết nối.", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="mb:shuffle", row=1)
    async def btn_shuffle(self, interaction: discord.Interaction, _: discord.ui.Button):
        q = self.cog.song_queues.get(interaction.guild.id, {}).get("queue", [])
        if not q:
            return await interaction.response.send_message("Queue trống.", ephemeral=True)
        random.shuffle(q)
        await interaction.response.send_message(f"🔀 Đã xáo trộn {len(q)} bài.", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="mb:loop", row=1)
    async def btn_loop(self, interaction: discord.Interaction, _: discord.ui.Button):
        gid = interaction.guild.id
        nxt = self.cog.loop_states.get(gid, LoopState.OFF).next()
        self.cog.loop_states[gid] = nxt
        await interaction.response.send_message(
            f"{nxt.emoji()} Loop: **{nxt.label()}**", ephemeral=True
        )

    @discord.ui.button(emoji="📜", label="Queue", style=discord.ButtonStyle.secondary, custom_id="mb:queue", row=1)
    async def btn_queue(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.show_queue(interaction, ephemeral=True)

    @discord.ui.button(emoji="ℹ️", label="Help", style=discord.ButtonStyle.secondary, custom_id="mb:help", row=1)
    async def btn_help(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.show_help(interaction, ephemeral=True)