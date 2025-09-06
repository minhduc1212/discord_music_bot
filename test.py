import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import yt_dlp
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

# --- KHÔNG CÓ THAY ĐỔI Ở ĐÂY ---
class MusicControlView(discord.ui.View):
    # Lớp View này đã khá tốt, nhưng để nó hoạt động tốt hơn với slash commands,
    # chúng ta nên sửa lại cách nó gọi các hàm. Tuy nhiên, để đơn giản, ta tạm giữ nguyên.
    # Lưu ý: Các button này sẽ gửi message dạng prefix command, không phải là slash command.
    def __init__(self, voice_client, play_next_song_func, guild, text_channel):
        super().__init__(timeout=None)
        self.voice_client = voice_client
        self.play_next_song_func = play_next_song_func
        self.guild = guild
        self.text_channel = text_channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Đảm bảo chỉ người trong voice channel mới có thể dùng button
        if interaction.user.voice and interaction.user.voice.channel == self.voice_client.channel:
            return True
        else:
            await interaction.response.send_message("Bạn phải ở trong kênh thoại để điều khiển nhạc!", ephemeral=True)
            return False

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.voice_client.is_playing():
            self.voice_client.pause()
            await interaction.response.send_message("Đã tạm dừng.", ephemeral=True)
        else:
            await interaction.response.send_message("Không có gì để tạm dừng.", ephemeral=True)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success, emoji="▶️")
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.voice_client.is_paused():
            self.voice_client.resume()
            await interaction.response.send_message("Đã tiếp tục.", ephemeral=True)
        else:
            await interaction.response.send_message("Không có gì để tiếp tục.", ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, emoji="⏭️")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.voice_client.is_playing():
            self.voice_client.stop()
            # Bot sẽ tự động chơi bài tiếp theo nhờ vào hàm 'after' trong lúc play
            await interaction.response.send_message("Đã bỏ qua bài hát.", ephemeral=True)
        else:
            await interaction.response.send_message("Không có gì để bỏ qua.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        global song_queue
        if self.voice_client:
            song_queue[self.guild.id] = [] # Xóa hàng đợi của server này
            self.voice_client.stop()
            await self.voice_client.disconnect()
            await interaction.response.send_message("Đã dừng nhạc và ngắt kết nối.", ephemeral=True)


def run_bot():
    load_dotenv()
    TOKEN = os.getenv('TOKEN')
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True # Cần intent này cho voice
    bot = commands.Bot(command_prefix="?", intents=intents)

    # --- THAY ĐỔI CẤU TRÚC DỮ LIỆU ---
    # Quản lý hàng đợi và voice client theo từng server (guild)
    song_queue = {}
    voice_clients = {}
    
    yt_dl_options = {"format": "bestaudio/best", "noplaylist": True, "quiet": True}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)

    ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5','options': '-vn -filter:a "volume=0.5"'}

    # --- HÀM LÕI ĐÃ ĐƯỢC SỬA LẠI ---
    async def play_next_song(guild, text_channel):
        if guild.id in song_queue and song_queue[guild.id]:
            url = song_queue[guild.id].pop(0)
            await play_song(guild, text_channel, url)
        else:
            # Nếu hàng đợi trống, ngắt kết nối sau 1 lúc
            await asyncio.sleep(120) # Chờ 2 phút
            if guild.id in voice_clients and not voice_clients[guild.id].is_playing():
                 await voice_clients[guild.id].disconnect()
                 del voice_clients[guild.id]


    async def play_song(guild, text_channel, url):
        try:
            voice_client = voice_clients[guild.id]
            loop = asyncio.get_event_loop()
            
            # Sử dụng ytdl để lấy thông tin, bao gồm URL trực tiếp và tiêu đề
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
            
            song_url = data['url']
            title = data.get('title', 'Không rõ tên')
            duration = data.get('duration_string', 'N/A')
            
            player = discord.FFmpegOpusAudio(song_url, **ffmpeg_options)
            
            # Hàm `after` sẽ được gọi khi bài hát kết thúc
            voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(guild, text_channel), loop))

            # Tạo view và gửi tin nhắn
            view = MusicControlView(voice_client, play_next_song, guild, text_channel)
            embed = discord.Embed(title="🎵 Đang phát", description=f"**{title}**\n`Thời lượng: {duration}`", color=discord.Color.blue())
            await text_channel.send(embed=embed, view=view)

        except Exception as e:
            print(f"Lỗi khi phát nhạc: {e}")
            await text_channel.send(f"Đã xảy ra lỗi khi phát bài hát. Thử lại sau nhé.")
            await play_next_song(guild, text_channel)

    # --- THÊM MỚI: SỰ KIỆN ON_READY ĐỂ SYNC COMMAND ---
    @bot.event
    async def on_ready():
        print(f'{bot.user} is now active')
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    # --- KHỐI SLASH COMMANDS ---
    @bot.tree.command(name="play", description="Phát một bài hát hoặc thêm vào hàng đợi")
    @app_commands.describe(song="Nhập tên bài hát hoặc dán link YouTube")
    async def slash_play(interaction: discord.Interaction, song: str):
        if not interaction.user.voice:
            await interaction.response.send_message("Bạn phải ở trong một kênh thoại để dùng lệnh này!", ephemeral=True)
            return

        await interaction.response.defer() # Báo cho Discord biết bot đang xử lý

        guild = interaction.guild
        voice_channel = interaction.user.voice.channel
        
        # Kết nối vào voice channel nếu chưa có
        if guild.id not in voice_clients:
            try:
                voice_clients[guild.id] = await voice_channel.connect()
            except Exception as e:
                await interaction.followup.send(f"Không thể kết nối vào kênh thoại: {e}")
                return
        
        vc = voice_clients[guild.id]
        
        if guild.id not in song_queue:
            song_queue[guild.id] = []
        
        song_queue[guild.id].append(song)
        await interaction.followup.send(f"Đã thêm `{song}` vào hàng đợi!")

        if not vc.is_playing():
            await play_next_song(guild, interaction.channel)

    @bot.tree.command(name="skip", description="Bỏ qua bài hát hiện tại")
    async def slash_skip(interaction: discord.Interaction):
        guild = interaction.guild
        if guild.id in voice_clients and voice_clients[guild.id].is_playing():
            voice_clients[guild.id].stop()
            await interaction.response.send_message("Đã bỏ qua bài hát!")
            # Hàm `after` sẽ tự động gọi bài tiếp theo
        else:
            await interaction.response.send_message("Không có bài hát nào đang phát.", ephemeral=True)

    @bot.tree.command(name="stop", description="Dừng phát nhạc và ngắt kết nối bot")
    async def slash_stop(interaction: discord.Interaction):
        guild = interaction.guild
        if guild.id in voice_clients:
            song_queue[guild.id] = [] # Xóa hàng đợi
            voice_clients[guild.id].stop()
            await voice_clients[guild.id].disconnect()
            del voice_clients[guild.id]
            await interaction.response.send_message("Đã dừng nhạc và dọn dẹp hàng đợi.")
        else:
            await interaction.response.send_message("Bot không ở trong kênh thoại nào.", ephemeral=True)
            
    @bot.tree.command(name="queue", description="Hiển thị hàng đợi bài hát")
    async def slash_queue(interaction: discord.Interaction):
        guild = interaction.guild
        if guild.id in song_queue and song_queue[guild.id]:
            queue_list = "\n".join(f"{i+1}. {song}" for i, song in enumerate(song_queue[guild.id][:10]))
            embed = discord.Embed(title="📜 Hàng đợi bài hát", description=queue_list, color=discord.Color.purple())
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Hàng đợi đang trống.", ephemeral=True)

    # --- KHỐI PREFIX COMMANDS (VẪN GIỮ LẠI VÀ SỬA ĐỔI) ---
    @bot.command(name="play")
    async def prefix_play(ctx: commands.Context, *, url: str):
        if not ctx.author.voice:
            await ctx.send("Bạn phải ở trong một kênh thoại để dùng lệnh này!")
            return

        guild = ctx.guild
        voice_channel = ctx.author.voice.channel

        if guild.id not in voice_clients:
            try:
                voice_clients[guild.id] = await voice_channel.connect()
            except Exception as e:
                await ctx.send(f"Không thể kết nối vào kênh thoại: {e}")
                return

        vc = voice_clients[guild.id]

        if guild.id not in song_queue:
            song_queue[guild.id] = []

        song_queue[guild.id].append(url)
        await ctx.send(f"Đã thêm `{url}` vào hàng đợi!")

        if not vc.is_playing():
            await play_next_song(guild, ctx.channel)
    
    # Bạn có thể thêm các prefix command khác tương tự nếu muốn
    
    bot.run(TOKEN)

