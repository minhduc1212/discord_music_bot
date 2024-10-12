import discord
import os
import asyncio
import yt_dlp
from yt_dlp import YoutubeDL
from dotenv import load_dotenv
from discord.ext import commands

class MusicControlView(discord.ui.View):
    def __init__(self, voice_client, play_next_song, voice_clients):
        super().__init__(timeout=None)
        self.voice_client = voice_client
        self.play_next_song = play_next_song
        self.voice_clients = voice_clients

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("?pause", ephemeral=True)
        if self.voice_client.is_playing():
            self.voice_client.pause()
            await interaction.channel.send("Paused the current song.")
        else:
            await interaction.channel.send("No song is currently playing.")

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("?resume", ephemeral=True)
        if self.voice_client.is_paused():
            self.voice_client.resume()
            await interaction.channel.send("Resumed the current song.")
        else:
            await interaction.channel.send("No song is currently paused.")

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("?skip", ephemeral=True)
        try:
            if interaction.guild.id in self.voice_clients and self.voice_clients[interaction.guild.id].is_playing():
                self.voice_clients[interaction.guild.id].stop()
                await self.play_next_song()
                await interaction.channel.send("Skipped to the next song. Use the buttons below to control the music:", view=self)
            else:
                await interaction.channel.send("No song is currently playing.")
        except Exception as e:
            print(e)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("?stop", ephemeral=True)
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
            await self.voice_client.disconnect()
            await interaction.channel.send("Stopped the current song and disconnected.")
        else:
            await interaction.channel.send("No song is currently playing.")

def run_bot():
    load_dotenv()
    TOKEN = os.getenv('TOKEN')
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="?", intents=intents)

    song_queue = []
    voice_clients = {}
    
    ydl_opts = {'extract_flat': 'in_playlist', 'playlistend': 20}
    yt_dl_options = {"format": "bestaudio/best"}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)
    global is_playing
    is_playing = False  

    ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5','options': '-vn -filter:a "volume=0.5"'}

    async def play_next_song(ctx):
        global is_playing
        if song_queue:
            url = song_queue.pop(0)
            await play_song(ctx, url)
        else:
            is_playing = False

    async def play_song(ctx, url):
        global is_playing
        try:
            voice_client = voice_clients[ctx.guild.id]
            if 'list' in url:
                await ctx.send("Wait a moment while I get the playlist...")
                with YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                    if 'entries' in info_dict:
                        for i, entry in enumerate(info_dict['entries']):
                            song_queue.insert(i,entry['url'])
                        await ctx.send(f"Added {len(info_dict['entries'])} songs to the queue")
                    if not is_playing:
                        play_next_song(ctx)
                return
            else:
                await ctx.send(f"Playing {url}", view=MusicControlView(voice_client, play_next_song, voice_clients))
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
                song = data['url']
                player = discord.FFmpegOpusAudio(song, **ffmpeg_options)
                voice_clients[ctx.guild.id].play(player, after=lambda _: asyncio.run_coroutine_threadsafe(play_next_song(ctx), loop))
                is_playing = True
        except Exception as e:
            print(f"Error playing {url}: {e}")
            await play_next_song(ctx)

    @bot.event
    async def on_ready():
        print(f'{bot.user} is now active')

    @bot.command()
    async def play(ctx, url: str):
        global is_playing
        try:
            voice_client = await ctx.author.voice.channel.connect()
            voice_clients[voice_client.guild.id] = voice_client
        except Exception as e:
            print(e)

        if 'list' not in url:
            if not is_playing:
                song_queue.append(url)
                await play_next_song(ctx)
            else:
                song_queue.append(url)
                await ctx.send("Added to queue")
        elif 'list' in url:
            await ctx.send("Wait a moment while I get the playlist...")
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                if 'entries' in info_dict:
                    for entry in info_dict['entries']:
                        song_queue.append(entry['url'])
                    await ctx.send(f"Added {len(info_dict['entries'])} songs to the queue")
                if not is_playing:
                    await play_next_song(ctx)

    @bot.command()
    async def pause(ctx):
        try:
            voice_clients[ctx.guild.id].pause()
            view = MusicControlView(voice_clients[ctx.guild.id], play_next_song, voice_clients)
            await ctx.send("Paused the current song. Use the buttons below to control the music:", view=view)
        except Exception as e:
            print(e)

    @bot.command()
    async def resume(ctx):
        try:
            voice_clients[ctx.guild.id].resume()
            view = MusicControlView(voice_clients[ctx.guild.id], play_next_song, voice_clients)
            await ctx.send("Resumed the current song. Use the buttons below to control the music:", view=view)
        except Exception as e:
            print(e)

    @bot.command()
    async def stop(ctx):
        global is_playing
        try:
            voice_clients[ctx.guild.id].stop()
            await voice_clients[ctx.guild.id].disconnect()
            is_playing = False
            view = MusicControlView(voice_clients[ctx.guild.id], play_next_song, voice_clients)
            await ctx.send("Stopped the current song and disconnected. Use the buttons below to control the music:", view=view)
        except Exception as e:
            print(e)

    @bot.command()
    async def add(ctx, *urls: str):
        try:
            if urls:
                song_queue.extend(urls)  # Add all URLs to the song queue
                await ctx.send(f"Added {len(urls)} songs to the list")
            else:
                await ctx.send("Please provide at least one URL.")
        except Exception as e:
            print(e)

    @bot.command()
    async def list(ctx):
        try:
            await ctx.send(song_queue)
        except Exception as e:
            print(e)
    
    @bot.command(name="help_command")
    async def help_command(ctx):
        try:
            await ctx.send("List of commands:\n?play [url] - Play a song\n?pause - Pause the current song\n?resume - Resume the current song\n?stop - Stop the current song\n?add [url] - Add a song to the list\n?list - Show the list of songs\n?help_command - Show this message")
        except Exception as e:
            print(e)

    @bot.command()
    async def skip(ctx):
        try:
            if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
                voice_clients[ctx.guild.id].stop()
                await play_next_song(ctx)
                view = MusicControlView(voice_clients[ctx.guild.id], play_next_song, voice_clients)
                await ctx.send("Skipped to the next song. Use the buttons below to control the music:", view=view)
            else:
                await ctx.send("No song is currently playing.")
        except Exception as e:
            print(e)

    @bot.event
    async def on_voice_state_update(member, before, after):
        global is_playing
        if member == bot.user and before.channel is not None and after.channel is None:
            # Bot was disconnected from the voice channel
            song_queue.clear()
            is_playing = False
            # Send a message to the system channel or another appropriate channel
            if before.channel.guild.system_channel:
                await before.channel.guild.system_channel.send("Bot was disconected, playlist ended.")

    bot.run(TOKEN)
