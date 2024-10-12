import discord
import os
import asyncio
import yt_dlp
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

def run_bot():
    load_dotenv()
    TOKEN = os.getenv('TOKEN')
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    song_queue = []
    voice_clients = {}
    
    ydl_opts = {'extract_flat': 'in_playlist', 'playlistend': 20}
    yt_dl_options = {"format": "bestaudio/best"}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)
    global is_playing
    is_playing = False  

    ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5','options': '-vn -filter:a "volume=0.5"'}

    @client.event
    async def on_ready():
        print(f'{client.user} is now active')

    @client.event
    async def on_message(message):
        global is_playing
        if message.content.startswith("?play"):
            try:
                voice_client = await message.author.voice.channel.connect()
                voice_clients[voice_client.guild.id] = voice_client
            except Exception as e:
                print(e)
            
            async def play_next_song():
                global is_playing
                if song_queue:
                    url = song_queue.pop(0)
                    await play_song(url)
                else:
                    is_playing = False

            async def play_song(url):
                global is_playing
                try:
                    if 'list' in url:
                        await message.channel.send("Wait a moment while I get the playlist...")
                        with YoutubeDL(ydl_opts) as ydl:
                            info_dict = ydl.extract_info(url, download=False)
                            if 'entries' in info_dict:  # Is a playlist
                                for i, entry in enumerate(info_dict['entries']):
                                    song_queue.insert(i, entry['url'])
                                await message.channel.send(f"Added {len(info_dict['entries'])} songs to the queue")
                            if not is_playing:
                                await play_next_song()
                        return
                    else:
                        await message.channel.send(f"Playing {url}")
                        loop = asyncio.get_event_loop()
                        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
                        song = data['url']
                        player = discord.FFmpegOpusAudio(song, **ffmpeg_options)
                        voice_clients[message.guild.id].play(player, after=lambda _: asyncio.run_coroutine_threadsafe(play_next_song(), loop))
                        is_playing = True
                except Exception as e:
                    print(f"Error playing {url}: {e}")
                    await play_next_song()

            try:
                content = message.content.split()
                
                if len(content) == 2:                   
                    url = content[1]
                    if 'list' not in url:
                        if not is_playing:
                            song_queue.append(url)
                            await play_next_song()
                        else:
                            song_queue.append(url)
                            await message.channel.send("Added to queue")
                    elif 'list' in url:
                        await message.channel.send("Wait a moment while I fetch the playlist...")
                        with YoutubeDL(ydl_opts) as ydl:
                            info_dict = ydl.extract_info(url, download=False)
                            if 'entries' in info_dict:
                                for entry in info_dict['entries']:
                                    song_queue.append(entry['url'])
                                await message.channel.send(f"Added {len(info_dict['entries'])} songs to the queue")
                            if not is_playing:
                                await play_next_song()
                elif len(content) > 2:
                    urls = content[1:]
                    if not is_playing:
                        song_queue.extend(urls)
                        await play_next_song()
                    else:
                        song_queue.extend(urls)
                        await message.channel.send(f"Added {len(urls)} songs to the queue")
                else:
                    await message.channel.send("Please provide a URL.")
            except Exception as e:
                print(e)

        if message.content.startswith("?pause"):
            try:
                voice_clients[message.guild.id].pause()
            except Exception as e:
                print(e)

        if message.content.startswith("?resume"):
            try:
                voice_clients[message.guild.id].resume()
            except Exception as e:
                print(e)

        if message.content.startswith("?stop"):
            try:
                voice_clients[message.guild.id].stop()
                await voice_clients[message.guild.id].disconnect()
                is_playing = False
            except Exception as e:
                print(e)

        if message.content.startswith("?add"):
            try:
                content = message.content.split()
                if len(content) > 1:
                    urls = content[1:]  # Get all URLs after the command
                    song_queue.extend(urls)  # Add all URLs to the song queue
                    await message.channel.send(f"Added {len(urls)} songs to the list")
                else:
                    await message.channel.send("Please provide at least one URL.")
            except Exception as e:
                print(e)

        if message.content.startswith("?list"):
            try:
                await message.channel.send(song_queue)
            except Exception as e:
                print(e)
        
        if message.content.startswith("?help"):
            try:
                await message.channel.send("List of commands:\n?play [url] - Play a song\n?pause - Pause the current song\n?resume - Resume the current song\n?stop - Stop the current song\n?add [url] - Add a song to the list\n?list - Show the list of songs\n?help - Show this message")
            except Exception as e:
                print(e)

        if message.content.startswith("?skip"):
            try:
                if message.guild.id in voice_clients and voice_clients[message.guild.id].is_playing():
                    voice_clients[message.guild.id].stop()
                    await play_next_song()
                    await message.channel.send("Skipped to the next song.")
                else:
                    await message.channel.send("No song is currently playing.")
            except Exception as e:
                print(e)

    @client.event
    async def on_voice_state_update(member, before, after):
        global is_playing
        # Bot was disconnected from the voice channel
        if member == client.user and before.channel is not None and after.channel is None:
            song_queue.clear()
            is_playing = False
            # Send a message to the system channel or another appropriate channel
            if before.channel.guild.system_channel:
                await before.channel.guild.system_channel.send("Bot bị đuổi, playlist ended.")

    client.run(TOKEN)

# Ensure the bot is started
if __name__ == "__main__":
    run_bot()