import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv
from enum import Enum
import logging
import logging.handlers

# =================================================================================
# === CẤU HÌNH LOGGING ============================================================
# =================================================================================
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
logging.getLogger('discord.http').setLevel(logging.INFO)

handler = logging.handlers.RotatingFileHandler(
    filename='discord.log',
    encoding='utf-8',
    maxBytes=32 * 1024 * 1024,  # 32 MB
    backupCount=5,
)
dt_fmt = '%Y-%m-%d %H:%M:%S'
formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')
handler.setFormatter(formatter)
logger.addHandler(handler)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
# =================================================================================

# --- CẤU HÌNH BOT ---
# Tùy chọn cho video đơn và tìm kiếm (lấy thông tin chi tiết)
YTDL_SINGLE_SONG_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

# Tùy chọn cho playlist và mix (lấy nhanh danh sách, giới hạn 20 bài)
YTDL_PLAYLIST_OPTIONS = {
    'format': 'bestaudio/best',
    'extract_flat': 'in_playlist',
    'playlistend': 20, # Giới hạn 20 bài hát
    'quiet': True,
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

class LoopState(Enum): OFF = 0; SONG = 1; QUEUE = 2

class Song:
    def __init__(self, data, requester):
        # Dữ liệu từ 'extract_flat' sẽ khác, cần xử lý cả hai trường hợp
        self.webpage_url = data.get('url') if 'url' in data and data.get('ie_key') else data.get('webpage_url')
        self.title = data.get('title', 'Không rõ tên')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader', 'Không rõ')
        self.requester = requester
        self.stream_url = data.get('url') if 'url' in data and not data.get('ie_key') else None # URL để phát

    async def get_stream_url(self):
        # Nếu chưa có stream_url (trường hợp từ playlist flat), lấy nó ngay bây giờ
        if self.stream_url:
            return self.stream_url
        
        try:
            logger.info(f"Đang lấy stream URL cho: {self.title}")
            loop = asyncio.get_event_loop()
            def extract_stream():
                with yt_dlp.YoutubeDL(YTDL_SINGLE_SONG_OPTIONS) as ydl:
                    info = ydl.extract_info(self.webpage_url, download=False)
                    return info.get('url')
            self.stream_url = await loop.run_in_executor(None, extract_stream)
            return self.stream_url
        except Exception as e:
            logger.error(f"Không thể lấy stream URL cho {self.title}: {e}")
            return None

    def format_duration(self):
        if self.duration and self.duration > 0:
            m, s = divmod(self.duration, 60)
            h, m = divmod(m, 60)
            h, m, s = int(h), int(m), int(s)
            return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        return "00:00"

class MusicControlView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice:
            await interaction.response.send_message("Bạn phải ở trong kênh thoại để điều khiển nhạc!", ephemeral=True)
            return False
        if interaction.guild.voice_client and interaction.user.voice.channel != interaction.guild.voice_client.channel:
            await interaction.response.send_message("Bạn phải ở cùng kênh thoại với bot!", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏯️")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Đã tạm dừng.", ephemeral=True)
        elif vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Đã tiếp tục.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="⏭️")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("Đã bỏ qua bài hát.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            await self.cog.cleanup(interaction.guild)
            await interaction.response.send_message("Đã dừng nhạc, dọn dẹp và ngắt kết nối.", ephemeral=True)

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.song_queues = {}
        self.loop_states = {}
        self.player_messages = {}

    async def cleanup(self, guild):
        if guild.voice_client:
            await guild.voice_client.disconnect()
        self.song_queues.pop(guild.id, None)
        self.loop_states.pop(guild.id, None)
        if guild.id in self.player_messages:
            try:
                msg_id, channel_id = self.player_messages[guild.id]
                channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            self.player_messages.pop(guild.id, None)

    async def send_or_edit_player(self, interaction, song, is_first_song=False):
        guild = interaction.guild
        embed = self.create_playing_embed(song)
        view = MusicControlView(self)

        if is_first_song:
            message = await interaction.followup.send(embed=embed, view=view, wait=True)
            self.player_messages[guild.id] = (message.id, message.channel.id)
        else:
            try:
                msg_id, channel_id = self.player_messages[guild.id]
                channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                message = await channel.fetch_message(msg_id)
                await message.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden):
                message = await interaction.channel.send(embed=embed, view=view)
                self.player_messages[guild.id] = (message.id, message.channel.id)

    def create_playing_embed(self, song):
        embed = discord.Embed(title="🎵 Đang phát", color=discord.Color.blue())
        embed.description = f"**[{song.title}]({song.webpage_url})**"
        embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Thời lượng", value=song.format_duration(), inline=True)
        embed.add_field(name="Người đăng", value=song.uploader, inline=True)
        embed.set_footer(text=f"Yêu cầu bởi: {song.requester.display_name}", icon_url=song.requester.display_avatar.url)
        return embed

    async def play_song(self, interaction, song, is_first_song):
        guild = interaction.guild
        vc = guild.voice_client

        stream_url = await song.get_stream_url()
        if not stream_url:
            await interaction.channel.send(f"Rất tiếc, không thể lấy được link để phát bài hát: **{song.title}**.")
            self.bot.loop.create_task(self.play_next(interaction))
            return

        def after_play(error):
            if error:
                logger.error(f'Lỗi trong callback after_play: {error}')
            self.bot.loop.create_task(self.play_next(interaction))

        try:
            player = discord.FFmpegOpusAudio(stream_url, **FFMPEG_OPTIONS)
            vc.play(player, after=after_play)
            await self.send_or_edit_player(interaction, song, is_first_song)
        except Exception as e:
            logger.error(f"Lỗi khi gọi vc.play: {e}")
            await interaction.channel.send(f"Đã xảy ra lỗi khi cố gắng phát nhạc: `{e}`.")

    async def play_next(self, interaction, is_first_song=False):
        guild = interaction.guild
        guild_id = guild.id
        
        if guild_id not in self.song_queues or not guild.voice_client:
            return

        current_song = self.song_queues[guild_id].get('now_playing')
        if current_song:
            loop_state = self.loop_states.get(guild_id, LoopState.OFF)
            if loop_state == LoopState.SONG:
                self.song_queues[guild_id]['queue'].insert(0, current_song)
            elif loop_state == LoopState.QUEUE:
                self.song_queues[guild_id]['queue'].append(current_song)

        if self.song_queues[guild_id]['queue']:
            next_song = self.song_queues[guild_id]['queue'].pop(0)
            self.song_queues[guild_id]['now_playing'] = next_song
            await self.play_song(interaction, next_song, is_first_song)
        else:
            self.song_queues[guild_id]['now_playing'] = None
            await asyncio.sleep(180)
            if guild.voice_client and not guild.voice_client.is_playing():
                await self.cleanup(guild)

    @app_commands.command(name="play", description="Phát nhạc từ YouTube (tên, link, playlist, mix)")
    async def play(self, interaction: discord.Interaction, search: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            await interaction.followup.send("Bạn phải ở trong kênh thoại để dùng lệnh này.")
            return

        voice_channel = interaction.user.voice.channel
        if interaction.guild.voice_client is None:
            await voice_channel.connect()
        elif interaction.guild.voice_client.channel != voice_channel:
            await interaction.guild.voice_client.move_to(voice_channel)

        is_first_song = not interaction.guild.voice_client.is_playing() and (interaction.guild.id not in self.song_queues or not self.song_queues[interaction.guild.id]['queue'])

        if interaction.guild.id not in self.song_queues:
            self.song_queues[interaction.guild.id] = {'now_playing': None, 'queue': []}
        
        try:
            is_playlist = 'list=' in search
            options = YTDL_PLAYLIST_OPTIONS if is_playlist else YTDL_SINGLE_SONG_OPTIONS
            
            loop = asyncio.get_event_loop()
            def do_extract():
                with yt_dlp.YoutubeDL(options) as ydl:
                    return ydl.extract_info(search, download=False)
            info = await loop.run_in_executor(None, do_extract)
            
            songs_to_add = []
            message = ""

            if 'entries' in info:
                # Nếu là playlist/mix hoặc kết quả tìm kiếm (luôn có 'entries')
                songs_to_add = [Song(entry, interaction.user) for entry in info['entries']]
                if is_playlist:
                    message = f"Đã thêm **{len(songs_to_add)}** bài hát từ playlist/mix vào hàng đợi."
                else: # Là kết quả tìm kiếm, chỉ lấy bài đầu
                    songs_to_add = songs_to_add[:1]
                    message = f"Đã thêm **{songs_to_add[0].title}** vào hàng đợi."
            else:
                # Là video đơn
                song = Song(info, interaction.user)
                songs_to_add.append(song)
                message = f"Đã thêm **{song.title}** vào hàng đợi."

            if not songs_to_add:
                await interaction.followup.send("Không tìm thấy kết quả nào.")
                return

            self.song_queues[interaction.guild.id]['queue'].extend(songs_to_add)
            
            if not is_first_song:
                await interaction.followup.send(message)

        except Exception as e:
            logger.error(f"Lỗi khi xử lý tìm kiếm '{search}': {e}")
            await interaction.followup.send(f"Đã xảy ra lỗi khi tìm kiếm. Hãy chắc chắn rằng link của bạn hợp lệ.")
            return

        if is_first_song:
            await self.play_next(interaction, is_first_song=True)

    async def queue_command_logic(self, interaction: discord.Interaction, ephemeral: bool = False):
        guild_id = interaction.guild.id
        q_data = self.song_queues.get(guild_id)

        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        
        if not q_data or (not q_data['now_playing'] and not q_data['queue']):
            await send_method("Hàng đợi đang trống.", ephemeral=True)
            return

        embed = discord.Embed(title="📜 Hàng đợi bài hát", color=discord.Color.purple())
        
        if q_data['now_playing']:
            np_song = q_data['now_playing']
            embed.add_field(name="Đang phát", value=f"**[{np_song.title}]({np_song.webpage_url})** | `{np_song.format_duration()}`", inline=False)

        if q_data['queue']:
            queue_list = ""
            total_duration = 0
            for i, song in enumerate(q_data['queue'][:10]):
                queue_list += f"`{i+1}.` [{song.title}]({song.webpage_url}) | `{song.format_duration()}`\n"
                if song.duration: total_duration += song.duration
            
            embed.description = queue_list
            footer_text = f"Tổng số bài hát trong hàng đợi: {len(q_data['queue'])}"
            if total_duration > 0:
                 footer_text += f" | Tổng thời lượng: {Song({'duration': total_duration}, None).format_duration()}"
            embed.set_footer(text=footer_text)

        await send_method(embed=embed, ephemeral=ephemeral)

    @app_commands.command(name="queue", description="Hiển thị hàng đợi bài hát")
    async def queue(self, interaction: discord.Interaction):
        await self.queue_command_logic(interaction)

    @app_commands.command(name="skip", description="Bỏ qua bài hát hiện tại")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("Đã bỏ qua bài hát.")
        else:
            await interaction.response.send_message("Không có bài hát nào đang phát.", ephemeral=True)

    @app_commands.command(name="stop", description="Dừng nhạc và ngắt kết nối")
    async def stop(self, interaction: discord.Interaction):
        await self.cleanup(interaction.guild)
        await interaction.response.send_message("Đã dừng nhạc và ngắt kết nối.")
        
    @app_commands.command(name="nowplaying", description="Hiển thị bài hát đang phát")
    async def nowplaying(self, interaction: discord.Interaction):
        q_data = self.song_queues.get(interaction.guild.id)
        if q_data and q_data['now_playing']:
             embed = self.create_playing_embed(q_data['now_playing'])
             await interaction.response.send_message(embed=embed)
        else:
             await interaction.response.send_message("Không có bài hát nào đang phát.", ephemeral=True)


# --- SETUP BOT CHÍNH ---
async def main():
    load_dotenv()
    TOKEN = os.getenv('TOKEN')
    
    intents = discord.Intents.default()
    intents.voice_states = True
    intents.message_content = True
    
    bot = commands.Bot(command_prefix="?", intents=intents, help_command=None)

    @bot.event
    async def on_ready():
        print(f'{bot.user} is now online and ready.')
        await bot.add_cog(MusicCog(bot))
        try:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Bot has crashed: {e}", exc_info=True)