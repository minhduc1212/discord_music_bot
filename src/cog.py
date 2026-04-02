import asyncio
import random

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from .logger import log
from .config import YTDL_SINGLE_OPTIONS, YTDL_PLAYLIST_OPTIONS, FFMPEG_OPTIONS
from .models import LoopState, Song
from .views import MusicView


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.song_queues:    dict[int, dict]       = {}
        self.loop_states:    dict[int, LoopState]  = {}
        self.player_messages: dict[int, tuple[int, int]] = {}

    async def cleanup(self, guild: discord.Guild):
        if guild.voice_client:
            guild.voice_client.stop()
            await guild.voice_client.disconnect()
        self.song_queues.pop(guild.id, None)
        self.loop_states.pop(guild.id, None)
        await self._delete_player_msg(guild)

    def _build_embed(self, song: Song, guild: discord.Guild) -> discord.Embed:
        loop  = self.loop_states.get(guild.id, LoopState.OFF)
        q_len = len(self.song_queues.get(guild.id, {}).get("queue", []))

        embed = discord.Embed(
            description=f"### 🎵 [{song.title}]({song.webpage_url})",
            color=0x5865F2,
        )
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)

        embed.add_field(name="⏱ Thời lượng",       value=song.fmt_duration(), inline=True)
        embed.add_field(name="📺 Kênh",             value=song.uploader,       inline=True)
        embed.add_field(name="🎶 Trong queue",      value=f"{q_len} bài",     inline=True)
        embed.add_field(name=f"{loop.emoji()} Loop", value=loop.label(),       inline=True)
        embed.set_footer(
            text=f"Yêu cầu bởi {song.requester.display_name}",
            icon_url=song.requester.display_avatar.url,
        )
        return embed

    async def _send_player(self, channel: discord.abc.Messageable, guild: discord.Guild, song: Song):
        embed = self._build_embed(song, guild)
        view  = MusicView(self)

        if guild.id in self.player_messages:
            msg_id, ch_id = self.player_messages[guild.id]
            try:
                ch  = guild.get_channel(ch_id) or await self.bot.fetch_channel(ch_id)
                msg = await ch.fetch_message(msg_id)
                await msg.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        msg = await channel.send(embed=embed, view=view)
        self.player_messages[guild.id] = (msg.id, msg.channel.id)

    async def _delete_player_msg(self, guild: discord.Guild):
        if guild.id not in self.player_messages:
            return
        msg_id, ch_id = self.player_messages.pop(guild.id)
        try:
            ch  = guild.get_channel(ch_id) or await self.bot.fetch_channel(ch_id)
            msg = await ch.fetch_message(msg_id)
            await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def show_queue(self, interaction: discord.Interaction, ephemeral: bool = False):
        gid    = interaction.guild.id
        q_data = self.song_queues.get(gid)
        send   = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )

        if not q_data or (not q_data.get("now_playing") and not q_data.get("queue")):
            return await send("📭 Hàng đợi đang trống.", ephemeral=True)

        loop  = self.loop_states.get(gid, LoopState.OFF)
        embed = discord.Embed(title="📜 Hàng đợi", color=0x9B59B6)

        np = q_data.get("now_playing")
        if np:
            embed.add_field(
                name="▶️ Đang phát",
                value=f"**[{np.title}]({np.webpage_url})** · `{np.fmt_duration()}`",
                inline=False,
            )

        queue = q_data.get("queue", [])
        if queue:
            lines, total = [], 0
            for i, s in enumerate(queue[:15], 1):
                lines.append(f"`{i}.` {s.title} · `{s.fmt_duration()}`")
                total += s.duration or 0
            embed.description = "\n".join(lines)
            h, r = divmod(total, 3600)
            m, s = divmod(r, 60)
            dur  = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            more = f" (+{len(queue) - 15} bài nữa)" if len(queue) > 15 else ""
            embed.set_footer(
                text=f"{len(queue)} bài{more} · Tổng: {dur} · Loop: {loop.label()}"
            )

        await send(embed=embed, ephemeral=ephemeral)

    async def show_help(self, interaction: discord.Interaction, ephemeral: bool = False):
        send = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        embed = discord.Embed(title="🎵 Danh sách lệnh", color=0x5865F2)
        cmds = [
            ("/play <tên/link>",  "Phát từ YouTube — tên bài, link, playlist"),
            ("/pause",            "Tạm dừng / tiếp tục"),
            ("/skip",             "Bỏ qua bài hiện tại"),
            ("/stop",             "Dừng và rời voice"),
            ("/loop",             "Chuyển loop: Tắt → Bài → Queue"),
            ("/queue",            "Xem hàng đợi"),
            ("/nowplaying",       "Xem bài đang phát"),
            ("/shuffle",          "Xáo trộn queue"),
            ("/remove <số>",      "Xóa bài theo thứ tự"),
            ("/jump <số>",        "Nhảy tới bài thứ N"),
            ("/move <từ> <đến>",  "Di chuyển vị trí bài"),
            ("/clearqueue",       "Xóa toàn bộ queue"),
        ]
        embed.description = "\n".join(f"`{c}` — {d}" for c, d in cmds)
        embed.set_footer(text="Các nút bấm cũng có sẵn trên player message")
        await send(embed=embed, ephemeral=ephemeral)

    async def play_song(self, interaction: discord.Interaction, song: Song, is_first: bool):
        guild = interaction.guild
        vc    = guild.voice_client

        stream_url = await song.get_stream_url()
        if not stream_url:
            await interaction.channel.send(
                f"⚠️ Không lấy được stream cho **{song.title}** — bỏ qua."
            )
            self.bot.loop.create_task(self.play_next(interaction))
            return

        def after_play(error):
            if error:
                log.error(f"FFmpeg error: {error}")
            self.bot.loop.create_task(self.play_next(interaction))

        try:
            player = discord.FFmpegOpusAudio(stream_url, **FFMPEG_OPTIONS)
            vc.play(player, after=after_play)
            log.info(f"▶ Đang phát: {song.title}")
            await self._send_player(interaction.channel, guild, song)
        except Exception as e:
            log.error(f"Lỗi vc.play '{song.title}': {e}")
            await interaction.channel.send(f"❌ Lỗi phát nhạc: `{e}`")

    async def play_next(self, interaction: discord.Interaction, is_first: bool = False):
        guild    = interaction.guild
        guild_id = guild.id

        if guild_id not in self.song_queues or not guild.voice_client:
            return

        q_data  = self.song_queues[guild_id]
        current = q_data.get("now_playing")
        loop    = self.loop_states.get(guild_id, LoopState.OFF)

        if current:
            if loop == LoopState.SONG:
                current.stream_url = None
                q_data["queue"].insert(0, current)
            elif loop == LoopState.QUEUE:
                current.stream_url = None
                q_data["queue"].append(current)

        if q_data["queue"]:
            next_song = q_data["queue"].pop(0)
            q_data["now_playing"] = next_song
            await self.play_song(interaction, next_song, is_first)
        else:
            q_data["now_playing"] = None
            await self._delete_player_msg(guild)
            await asyncio.sleep(180)
            if guild.voice_client and not guild.voice_client.is_playing():
                await self.cleanup(guild)

    @app_commands.command(name="play", description="Phát nhạc từ YouTube (tên, link, playlist)")
    @app_commands.describe(search="Tên bài hát, link YouTube hoặc link playlist")
    async def cmd_play(self, interaction: discord.Interaction, search: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            return await interaction.followup.send("⚠️ Bạn phải ở trong kênh thoại trước.")

        vc_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        try:
            if vc is None:
                await vc_channel.connect(self_deaf=True)
            elif vc.channel != vc_channel:
                await vc.move_to(vc_channel)
        except Exception as e:
            return await interaction.followup.send(f"❌ Không vào được voice: `{e}`")

        gid      = interaction.guild.id
        is_first = (
            not interaction.guild.voice_client.is_playing()
            and (gid not in self.song_queues or not self.song_queues[gid].get("queue"))
        )

        if gid not in self.song_queues:
            self.song_queues[gid] = {"now_playing": None, "queue": []}

        is_playlist = "list=" in search or "/playlist" in search
        opts = YTDL_PLAYLIST_OPTIONS if is_playlist else YTDL_SINGLE_OPTIONS

        try:
            loop = asyncio.get_event_loop()

            def _extract():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(search, download=False)

            info = await loop.run_in_executor(None, _extract)
        except Exception as e:
            log.error(f"Extract lỗi '{search}': {e}")
            return await interaction.followup.send(
                "❌ Không lấy được thông tin. Video private/bị xóa, hoặc link không hợp lệ."
            )

        if not info:
            return await interaction.followup.send("❌ Không tìm thấy kết quả.")

        songs_to_add: list[Song] = []
        if "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            if is_playlist:
                songs_to_add = [Song(e, interaction.user) for e in entries]
            elif entries:
                songs_to_add = [Song(entries[0], interaction.user)]
        else:
            songs_to_add = [Song(info, interaction.user)]

        if not songs_to_add:
            return await interaction.followup.send("❌ Không tìm thấy kết quả.")

        self.song_queues[gid]["queue"].extend(songs_to_add)

        if len(songs_to_add) == 1:
            await interaction.followup.send(f"✅ Đã thêm **{songs_to_add[0].title}** vào hàng đợi.")
        else:
            await interaction.followup.send(f"✅ Đã thêm **{len(songs_to_add)}** bài vào hàng đợi.")

        if is_first:
            await self.play_next(interaction, is_first=True)

    @app_commands.command(name="pause", description="Tạm dừng / tiếp tục")
    async def cmd_pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Bot không trong voice.", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ Đã tạm dừng.")
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Đã tiếp tục.")
        else:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)

    @app_commands.command(name="skip", description="Bỏ qua bài đang phát")
    async def cmd_skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ Đã bỏ qua.")
        else:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)

    @app_commands.command(name="stop", description="Dừng nhạc và ngắt kết nối")
    async def cmd_stop(self, interaction: discord.Interaction):
        await self.cleanup(interaction.guild)
        await interaction.response.send_message("⏹️ Đã dừng và ngắt kết nối.")

    @app_commands.command(name="loop", description="Chuyển chế độ lặp: Tắt → Bài → Queue")
    async def cmd_loop(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        nxt = self.loop_states.get(gid, LoopState.OFF).next()
        self.loop_states[gid] = nxt
        await interaction.response.send_message(f"{nxt.emoji()} Loop: **{nxt.label()}**")

    @app_commands.command(name="queue", description="Xem hàng đợi bài hát")
    async def cmd_queue(self, interaction: discord.Interaction):
        await self.show_queue(interaction)

    @app_commands.command(name="nowplaying", description="Xem bài đang phát")
    async def cmd_np(self, interaction: discord.Interaction):
        gid    = interaction.guild.id
        q_data = self.song_queues.get(gid)
        if not q_data or not q_data.get("now_playing"):
            return await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)
        embed = self._build_embed(q_data["now_playing"], interaction.guild)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shuffle", description="Xáo trộn hàng đợi")
    async def cmd_shuffle(self, interaction: discord.Interaction):
        q = self.song_queues.get(interaction.guild.id, {}).get("queue", [])
        if not q:
            return await interaction.response.send_message("Queue trống.", ephemeral=True)
        random.shuffle(q)
        await interaction.response.send_message(f"🔀 Đã xáo trộn {len(q)} bài.")

    @app_commands.command(name="remove", description="Xóa bài theo số thứ tự trong /queue")
    @app_commands.describe(index="Số thứ tự bắt đầu từ 1")
    async def cmd_remove(self, interaction: discord.Interaction, index: int):
        q = self.song_queues.get(interaction.guild.id, {}).get("queue", [])
        if not q or not 1 <= index <= len(q):
            return await interaction.response.send_message(
                f"Số không hợp lệ. Queue có {len(q)} bài.", ephemeral=True
            )
        removed = q.pop(index - 1)
        await interaction.response.send_message(f"🗑️ Đã xóa **{removed.title}**.")

    @app_commands.command(name="clearqueue", description="Xóa toàn bộ hàng đợi")
    async def cmd_clearqueue(self, interaction: discord.Interaction):
        q_data = self.song_queues.get(interaction.guild.id, {})
        n = len(q_data.get("queue", []))
        q_data["queue"] = []
        await interaction.response.send_message(f"🗑️ Đã xóa {n} bài khỏi queue.")

    @app_commands.command(name="jump", description="Nhảy tới bài thứ N trong queue")
    @app_commands.describe(index="Số thứ tự bài muốn nhảy đến")
    async def cmd_jump(self, interaction: discord.Interaction, index: int):
        q_data = self.song_queues.get(interaction.guild.id, {})
        q      = q_data.get("queue", [])
        if not q or not 1 <= index <= len(q):
            return await interaction.response.send_message(
                f"Số không hợp lệ. Queue có {len(q)} bài.", ephemeral=True
            )
        target = q[index - 1].title
        loop   = self.loop_states.get(interaction.guild.id, LoopState.OFF)
        q_data["queue"] = q[index - 1:] + (q[:index - 1] if loop == LoopState.QUEUE else [])
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
        await interaction.response.send_message(f"⏩ Nhảy đến: **{target}**")

    @app_commands.command(name="move", description="Di chuyển bài trong queue")
    @app_commands.describe(from_index="Vị trí hiện tại", to_index="Vị trí đích")
    async def cmd_move(self, interaction: discord.Interaction, from_index: int, to_index: int):
        q = self.song_queues.get(interaction.guild.id, {}).get("queue", [])
        n = len(q)
        if not n or not (1 <= from_index <= n and 1 <= to_index <= n):
            return await interaction.response.send_message(
                f"Vị trí không hợp lệ. Queue có {n} bài.", ephemeral=True
            )
        song = q.pop(from_index - 1)
        q.insert(to_index - 1, song)
        await interaction.response.send_message(
            f"↕️ Di chuyển **{song.title}** từ #{from_index} → #{to_index}."
        )

    @app_commands.command(name="help", description="Xem tất cả lệnh")
    async def cmd_help(self, interaction: discord.Interaction):
        await self.show_help(interaction, ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.id != self.bot.user.id:
            return
        if before.channel and not after.channel:
            log.info(f"Bot rời voice tại guild {member.guild.id}")
            self.song_queues.pop(member.guild.id, None)
            self.loop_states.pop(member.guild.id, None)
            await self._delete_player_msg(member.guild)