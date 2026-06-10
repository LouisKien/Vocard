"""MIT License

Copyright (c) 2023 - present Vocard Development

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import re
import aiohttp
import discord
import voicelink

from contextlib import suppress
from io import StringIO
from validators import url
from discord import app_commands
from discord.ext import commands
from function import (
    cooldown_check,
    get_aliases,
    logger
)

from voicelink import MongoDBHandler, LangHandler, Config
from voicelink.song_resolver import resolve_song, search_songs
from voicelink.views import SearchView, QueueView, LinkView, LyricsView, HelpView
from voicelink.utils import format_ms, format_to_ms, truncate_string, dispatch_message, send_localized_message

SPOTIFY_PLAYLIST_URL_REGEX = re.compile(
    r"^https?://open\.spotify\.com/playlist/[A-Za-z0-9]+(?:\?.*)?$",
    re.IGNORECASE,
)
AUTOCOMPLETE_MIN_QUERY_LENGTH = 2
AUTOCOMPLETE_LOOKUP_TIMEOUT_SECONDS = 2.0
AUTOCOMPLETE_MAX_CHOICES = 5
RESOLVER_FALLBACK_RESULT_LIMIT = 10

async def nowplay(ctx: commands.Context, player: voicelink.Player):
    track = player.current
    if not track:
        return await send_localized_message(ctx, 'player.errors.noTrackPlaying', ephemeral=True)

    texts = await LangHandler.get_lang(ctx.guild.id, "player.playback.nowplayingDesc", "player.playback.nowplayingField", "player.playback.nowplayingLink")
    upnext = "\n".join(f"`{index}.` `[{track.formatted_length}]` [{truncate_string(track.title)}]({track.uri})" for index, track in enumerate(player.queue.tracks()[:2], start=2))
    
    embed = discord.Embed(description=texts[0].format(track.title), color=Config().embed_color)
    embed.set_author(
        name=track.requester.display_name,
        icon_url=track.requester.display_avatar.url
    )
    embed.set_thumbnail(url=track.thumbnail)

    if upnext:
        embed.add_field(name=texts[1], value=upnext)

    pbar = "".join(":radio_button:" if i == round(player.position // round(track.length // 15)) else "▬" for i in range(15))
    icon = ":red_circle:" if track.is_stream else (":pause_button:" if player.is_paused else ":arrow_forward:")
    embed.add_field(name="\u2800", value=f"{icon} {pbar} **[{format_ms(player.position)}/{track.formatted_length}]**", inline=False)

    return await dispatch_message(ctx, embed, view=LinkView(texts[2].format(track.source.title()), track.emoji, track.uri))

class Basic(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.description = "This category is available to anyone on this server. Voting is required in certain commands."
        self.ctx_menu = app_commands.ContextMenu(
            name="play",
            callback=self._play
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @staticmethod
    def _is_spotify_playlist_query(query: str) -> bool:
        return bool(SPOTIFY_PLAYLIST_URL_REGEX.match(query.strip()))

    @staticmethod
    async def _dismiss_temporary_message(message: discord.Message | None) -> None:
        if not message or not hasattr(message, "delete"):
            return

        with suppress(discord.HTTPException, discord.NotFound, AttributeError):
            await message.delete()

    @staticmethod
    def _should_attempt_resolver_fallback(query: str) -> bool:
        normalized_query = query.strip()
        return bool(normalized_query) and not voicelink.pool.URL_REGEX.match(normalized_query)

    @staticmethod
    def _resolution_identifiers(resolved_track: object) -> list[str]:
        canonical_url = str(getattr(resolved_track, "canonical_url", "") or "").strip()
        search_query = str(getattr(resolved_track, "search_query", "") or "").strip()
        source = str(getattr(resolved_track, "source", "") or "").strip().lower()
        resolved_by = str(getattr(resolved_track, "resolved_by", "") or "").strip().lower()

        identifiers: list[str] = []
        if search_query and source == "youtube" and resolved_by == "direct":
            identifiers.append(search_query)
        if canonical_url:
            identifiers.append(canonical_url)
        if search_query and search_query not in identifiers:
            identifiers.append(search_query)
        return identifiers

    async def _hydrate_resolved_tracks(
        self,
        player: voicelink.Player,
        *,
        resolved_tracks: list[object],
        requester: discord.Member | discord.User,
        search_type: voicelink.SearchType | None = None,
    ) -> list[voicelink.Track]:
        tracks: list[voicelink.Track] = []
        seen_identifiers: set[str] = set()

        for resolved_track in resolved_tracks:
            for identifier in self._resolution_identifiers(resolved_track):
                if not identifier or identifier in seen_identifiers:
                    continue

                seen_identifiers.add(identifier)

                try:
                    loaded_tracks = await player.get_tracks(
                        identifier,
                        requester=requester,
                        search_type=search_type,
                    )
                except (asyncio.TimeoutError, aiohttp.ClientError, voicelink.NodeException, voicelink.TrackLoadError):
                    continue

                if isinstance(loaded_tracks, voicelink.Playlist):
                    candidate_tracks = loaded_tracks.tracks
                else:
                    candidate_tracks = loaded_tracks or []

                if candidate_tracks:
                    tracks.append(candidate_tracks[0])
                    break

        return tracks

    async def _resolve_tracks_from_keyword(
        self,
        player: voicelink.Player,
        *,
        query: str,
        requester: discord.Member | discord.User,
        search_type: voicelink.SearchType | None = None,
    ):
        normalized_query = query.strip()
        if not self._should_attempt_resolver_fallback(normalized_query):
            return None

        try:
            if search_type is None:
                resolved_track = await resolve_song(normalized_query)
                resolved_tracks = [resolved_track]
            else:
                resolved_tracks = await search_songs(
                    normalized_query,
                    search_type=search_type.name,
                    limit=RESOLVER_FALLBACK_RESULT_LIMIT,
                )
        except Exception:
            return None

        hydrated_tracks = await self._hydrate_resolved_tracks(
            player,
            resolved_tracks=resolved_tracks,
            requester=requester,
            search_type=search_type,
        )
        return hydrated_tracks or None

    async def _get_tracks_with_loading_notice(
        self,
        ctx: commands.Context | discord.Interaction,
        player: voicelink.Player,
        *,
        query: str,
        requester: discord.Member | discord.User,
        settings: dict,
        search_type: voicelink.SearchType | None = None,
    ):
        loading_message = None
        if self._is_spotify_playlist_query(query):
            loading_message = await send_localized_message(
                ctx,
                "player.playback.spotifyPlaylistLoading",
                settings=settings,
                delete_after=None,
            )

        try:
            tracks = await player.get_tracks(query, requester=requester, search_type=search_type)
        except voicelink.TrackLoadError as error:
            if self._should_attempt_resolver_fallback(query):
                fallback_tracks = await self._resolve_tracks_from_keyword(
                    player,
                    query=query,
                    requester=requester,
                    search_type=search_type,
                )
                if fallback_tracks:
                    return fallback_tracks
                return None
            if self._is_spotify_playlist_query(query):
                message = player.get_msg("player.errors.spotifyPlaylistLookupFailed")
                if message == "Not found!":
                    message = "Spotify playlist này đang tải quá lâu hoặc tạm thời lỗi. Vui lòng thử lại sau."
                raise voicelink.TrackLoadError(message) from error
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, voicelink.NodeException) as error:
            if self._is_spotify_playlist_query(query):
                message = player.get_msg("player.errors.spotifyPlaylistLookupFailed")
                if message == "Not found!":
                    message = "Spotify playlist này đang tải quá lâu hoặc tạm thời lỗi. Vui lòng thử lại sau."
            else:
                message = player.get_msg("player.errors.trackLookupFailed")
                if message == "Not found!":
                    message = "Không thể tải dữ liệu bài hát lúc này. Vui lòng thử lại sau."
            raise voicelink.TrackLoadError(message) from error
        finally:
            await self._dismiss_temporary_message(loading_message)

        if tracks:
            return tracks

        return await self._resolve_tracks_from_keyword(
            player,
            query=query,
            requester=requester,
            search_type=search_type,
        )

    @staticmethod
    async def _refresh_controller_after_queue_add(
        player: voicelink.Player,
        ctx: commands.Context | discord.Interaction,
    ) -> None:
        await player.refresh_controller_after_queue_update(ctx)

    @staticmethod
    async def _refresh_controller_after_state_change(
        player: voicelink.Player,
        ctx: commands.Context | discord.Interaction,
    ) -> None:
        await player.refresh_controller_for_state_change(ctx)

    async def help_autocomplete(self, interaction: discord.Interaction, current: str) -> list:
        return [app_commands.Choice(name=c.capitalize(), value=c) for c in self.bot.cogs if c not in ["Nodes", "Task"] and current in c]

    async def play_autocomplete(self, interaction: discord.Interaction, current: str) -> list:
        current = current.strip()
        if voicelink.pool.URL_REGEX.match(current):
            return []

        if current:
            if len(current) < AUTOCOMPLETE_MIN_QUERY_LENGTH:
                return []
            try:
                tracks = await search_songs(current, limit=AUTOCOMPLETE_MAX_CHOICES)
            except Exception:
                return []
            if not tracks:
                return []

            return [
                app_commands.Choice(
                    name=truncate_string(f"🎵 [{format_ms(track.duration_ms or 0)}] {track.author} - {track.title}", 100),
                    value=track.canonical_url,
                )
                for track in tracks[:AUTOCOMPLETE_MAX_CHOICES]
            ]
        
        history_source = MongoDBHandler.get_cached_user(interaction.user.id, d_type="history")
        if not history_source:
            history_source = await MongoDBHandler.get_user(interaction.user.id, d_type="history")

        history = {track["identifier"]: track for track_id in reversed(history_source) if (track := voicelink.Track.decode(track_id))["uri"]}
        return [app_commands.Choice(name=truncate_string(f"🕒 [{format_ms(track['length'])}] {track['author']} - {track['title']}", 100), value=track['uri']) for track in history.values() if len(track['uri']) <= 100][:25]
            
    @commands.hybrid_command(name="connect", aliases=get_aliases("connect"))
    @app_commands.describe(channel="Provide a channel to connect.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def connect(self, ctx: commands.Context, channel: discord.VoiceChannel = None) -> None:
        "Connect to a voice channel."
        try:
            player = await voicelink.connect_channel(ctx, channel)
        except discord.errors.ClientException:
            return await send_localized_message(ctx, "voice.connection.alreadyConnected")

        await send_localized_message(ctx, "voice.connection.connect", player.channel)
                
    @commands.hybrid_command(name="play", aliases=get_aliases("play"))
    @app_commands.describe(
        query="Input a query or a searchable link.",
        start="Specify a time you would like to start, e.g. 1:00",
        end="Specify a time you would like to end, e.g. 4:00"
    )
    @app_commands.autocomplete(query=play_autocomplete)
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def play(self, ctx: commands.Context, *, query: str, start: str = "0", end: str = "0") -> None:
        "Loads your input into the queue."
        if isinstance(ctx, discord.Interaction) and not ctx.interaction.response.is_done():
            await ctx.defer()
            
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)
        settings = player.settings
        player.bind_controller_context(ctx)

        tracks = await self._get_tracks_with_loading_notice(
            ctx,
            player,
            query=query,
            requester=ctx.author,
            settings=settings,
        )
        if not tracks:
            return await send_localized_message(ctx, "player.errors.noTrackFound", settings=settings)

        was_playing = player.is_playing
        if isinstance(tracks, voicelink.Playlist):
            index = await player.add_track(tracks.tracks, start_time=format_to_ms(start), end_time=format_to_ms(end))
            if not was_playing:
                await player.do_next()
            await send_localized_message(ctx, "player.playback.playlistLoad", tracks.name, index, settings=settings)
            await self._refresh_controller_after_queue_add(player, ctx)
        else:
            position = await player.add_track(tracks[0], start_time=format_to_ms(start), end_time=format_to_ms(end))
            if not was_playing:
                await player.do_next()
            texts = player.get_msg("common.status.live", "player.playback.trackLoadPos", "player.playback.trackLoad")
            stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""
            additional_content = texts[1] if position >= 1 and was_playing else texts[2]

            await dispatch_message(
                ctx,
                stream_content + additional_content,
                tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                position if position >= 1 and was_playing else None,
                settings=settings,
            )
            await self._refresh_controller_after_queue_add(player, ctx)
    
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def _play(self, interaction: discord.Interaction, message: discord.Message):
        query = ""

        if message.content:
            url = re.findall(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+", message.content)
            if url:
                query = url[0]

        elif message.attachments:
            query = message.attachments[0].url

        if not query:
            return await send_localized_message(interaction, "player.errors.noPlaySource", ephemeral=True)

        player: voicelink.Player = interaction.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(interaction)

        if not player.is_user_join(interaction.user):
            return await send_localized_message(interaction, "voice.connection.notInChannel", interaction.user.mention, player.channel.mention, ephemeral=True)

        await interaction.response.defer()
        settings = player.settings
        player.bind_controller_context(interaction)
        tracks = await self._get_tracks_with_loading_notice(
            interaction,
            player,
            query=query,
            requester=interaction.user,
            settings=settings,
        )
        if not tracks:
            return await send_localized_message(interaction, "player.errors.noTrackFound", settings=settings)

        was_playing = player.is_playing
        if isinstance(tracks, voicelink.Playlist):
            index = await player.add_track(tracks.tracks)
            if not was_playing:
                await player.do_next()
            await send_localized_message(interaction, "player.playback.playlistLoad", tracks.name, index, settings=settings)
            await self._refresh_controller_after_queue_add(player, interaction)
        else:
            position = await player.add_track(tracks[0])
            if not was_playing:
                await player.do_next()
            texts = player.get_msg("common.status.live", "player.playback.trackLoadPos", "player.playback.trackLoad")

            stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""
            additional_content = texts[1] if position >= 1 and was_playing else texts[2]

            await dispatch_message(
                interaction,
                stream_content + additional_content,
                tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                position if position >= 1 and was_playing else None,
                settings=settings,
            )
            await self._refresh_controller_after_queue_add(player, interaction)

    @commands.hybrid_command(name="search", aliases=get_aliases("search"))
    @app_commands.describe(
        query="Input the name of the song.",
        platform="Select the platform you want to search."
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name=search_type.display_name, value=search_type.name)
        for search_type in voicelink.SearchType
    ])
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def search(self, ctx: commands.Context, *, query: str, platform: str = Config().search_platform.name):
        "Searches your query and displays the results."
        if isinstance(ctx, discord.Interaction) and not ctx.interaction.response.is_done():
            await ctx.defer()
            
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)
        settings = player.settings
        player.bind_controller_context(ctx)

        if url(query):
            return await send_localized_message(ctx, "search.noLinkSupport", ephemeral=True, settings=settings)
        
        search_type: voicelink.SearchType = voicelink.SearchType.from_platform(platform) or Config().search_platform
        tracks = await self._get_tracks_with_loading_notice(
            ctx,
            player,
            query=query,
            requester=ctx.author,
            settings=settings,
            search_type=search_type,
        )
        if not tracks:
            return await send_localized_message(ctx, "player.errors.noTrackFound", settings=settings)

        texts = await LangHandler.get_lang(
            ctx.guild.id,
            "search.title",
            "search.desc",
            "common.status.live",
            "player.playback.trackLoadPos",
            "player.playback.trackLoad",
            "search.wait",
            "search.success",
            settings=settings,
        )
        query_track = "\n".join(f"`{index}.` `[{track.formatted_length}]` **{track.title[:35]}**" for index, track in enumerate(tracks[0:10], start=1))
        embed = discord.Embed(title=texts[0].format(query), description=texts[1].format(Config().get_source_config(search_type.display_name, "emoji"), search_type.display_name, len(tracks[0:10]), query_track), color=Config().embed_color)
        view = SearchView(tracks=tracks[0:10], texts=[texts[5], texts[6]])
        view.response = await dispatch_message(ctx, embed, view=view, ephemeral=True, settings=settings)

        await view.wait()
        if view.values is not None:
            was_playing = player.is_playing
            msg = ""
            for value in view.values:
                track = tracks[int(value.split(". ")[0]) - 1]
                position = await player.add_track(track)
                msg += (f"`{texts[2]}`" if track.is_stream else "") + (texts[3].format(track.title, track.uri, track.author, track.formatted_length, position) if position >= 1 else texts[4].format(track.title, track.uri, track.author, track.formatted_length))
            if not was_playing:
                await player.do_next()
            await dispatch_message(ctx, msg, settings=settings)
            await self._refresh_controller_after_queue_add(player, ctx)

    @commands.hybrid_command(name="playtop", aliases=get_aliases("playtop"))
    @app_commands.describe(
        query="Input a query or a searchable link.",
        start="Specify a time you would like to start, e.g. 1:00",
        end="Specify a time you would like to end, e.g. 4:00"
    )
    @app_commands.autocomplete(query=play_autocomplete)
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def playtop(self, ctx: commands.Context, *, query: str, start: str = "0", end: str = "0"):
        "Adds a song with the given url or query on the top of the queue."
        if isinstance(ctx, discord.Interaction) and not ctx.interaction.response.is_done():
            await ctx.defer()
        
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)
        settings = player.settings
        player.bind_controller_context(ctx)

        tracks = await self._get_tracks_with_loading_notice(
            ctx,
            player,
            query=query,
            requester=ctx.author,
            settings=settings,
        )
        if not tracks:
            return await send_localized_message(ctx, "player.errors.noTrackFound", settings=settings)

        was_playing = player.is_playing
        if isinstance(tracks, voicelink.Playlist):
            index = await player.add_track(tracks.tracks, start_time=format_to_ms(start), end_time=format_to_ms(end), at_front=True)
            if not was_playing:
                await player.do_next()
            await send_localized_message(ctx, "player.playback.playlistLoad", tracks.name, index, settings=settings)
            await self._refresh_controller_after_queue_add(player, ctx)
        else:
            position = await player.add_track(tracks[0], start_time=format_to_ms(start), end_time=format_to_ms(end), at_front=True)
            if not was_playing:
                await player.do_next()
            texts = player.get_msg("common.status.live", "player.playback.trackLoadPos", "player.playback.trackLoad")

            stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""
            additional_content = texts[1] if position >= 1 and was_playing else texts[2]

            await dispatch_message(
                ctx,
                stream_content + additional_content,
                tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                position if position >= 1 and was_playing else None,
                settings=settings,
            )
            await self._refresh_controller_after_queue_add(player, ctx)

    @commands.hybrid_command(name="forceplay", aliases=get_aliases("forceplay"))
    @app_commands.describe(
        query="Input a query or a searchable link.",
        start="Specify a time you would like to start, e.g. 1:00",
        end="Specify a time you would like to end, e.g. 4:00"
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def forceplay(self, ctx: commands.Context, *, query: str, start: str = "0", end: str = "0"):
        "Enforce playback using the given URL or query."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingFunction", ephemeral=True)
        
        if ctx.interaction:
            await ctx.interaction.response.defer()
        settings = player.settings
        player.bind_controller_context(ctx)

        tracks = await self._get_tracks_with_loading_notice(
            ctx,
            player,
            query=query,
            requester=ctx.author,
            settings=settings,
        )
        if not tracks:
            return await send_localized_message(ctx, "player.errors.noTrackFound", settings=settings)

        if isinstance(tracks, voicelink.Playlist):
            index = await player.add_track(tracks.tracks, start_time=format_to_ms(start), end_time=format_to_ms(end), at_front=True)
        else:
            await player.add_track(tracks[0], start_time=format_to_ms(start), end_time=format_to_ms(end), at_front=True)

        if player.queue._repeat.mode == voicelink.LoopType.TRACK:
            await player.set_repeat(voicelink.LoopType.OFF)

        await player.stop() if player.is_playing else await player.do_next()

        if isinstance(tracks, voicelink.Playlist):
            await send_localized_message(ctx, "player.playback.playlistLoad", tracks.name, index, settings=settings)
            await self._refresh_controller_after_queue_add(player, ctx)
        else:
            texts = player.get_msg("common.status.live", "player.playback.trackLoad")
            stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""

            await dispatch_message(
                ctx,
                stream_content + texts[1],
                tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                settings=settings,
            )
            await self._refresh_controller_after_queue_add(player, ctx)

    @commands.hybrid_command(name="pause", aliases=get_aliases("pause"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def pause(self, ctx: commands.Context):
        "Pause the music."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)
        settings = player.settings

        if player.is_paused:
            return await send_localized_message(ctx, "player.controls.pause.error", ephemeral=True, settings=settings)

        if not player.is_privileged(ctx.author):
            if ctx.author in player.pause_votes:
                return await send_localized_message(ctx, "voting.voted", ephemeral=True, settings=settings)
            
            player.pause_votes.add(ctx.author)
            if len(player.pause_votes) < (required := player.required()):
                return await send_localized_message(ctx, "player.controls.pause.vote", ctx.author, len(player.pause_votes), required, settings=settings)

        await player.set_pause(True, ctx.author)
        await send_localized_message(ctx, "player.controls.pause.success", ctx.author, settings=settings)
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="resume", aliases=get_aliases("resume"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def resume(self, ctx: commands.Context):
        "Resume the music."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)
        settings = player.settings

        if not player.is_paused:
            return await send_localized_message(ctx, "player.controls.resume.error", settings=settings)

        if not player.is_privileged(ctx.author):
            if ctx.author in player.resume_votes:
                return await send_localized_message(ctx, "voting.voted", ephemeral=True, settings=settings)
            
            player.resume_votes.add(ctx.author)
            if len(player.resume_votes) < (required := player.required()):
                return await send_localized_message(ctx, "player.controls.resume.vote", ctx.author, len(player.resume_votes), required, settings=settings)

        await player.set_pause(False, ctx.author)
        await send_localized_message(ctx, "player.controls.resume.success", ctx.author, settings=settings)
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="skip", aliases=get_aliases("skip"))
    @app_commands.describe(index="Enter a index that you want to skip to.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def skip(self, ctx: commands.Context, index: int = 0):
        "Skips to the next song or skips to the specified song."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)
        settings = player.settings

        if not player.node._available:
            return await send_localized_message(ctx, "player.errors.nodeReconnect", settings=settings)
        
        if not player.is_playing:
            return await send_localized_message(ctx, "player.controls.skip.error", ephemeral=True, settings=settings)

        if not player.is_privileged(ctx.author):
            if ctx.author == player.current.requester:
                pass
            elif ctx.author in player.skip_votes:
                return await send_localized_message(ctx, "voting.voted", ephemeral=True)
            else:
                player.skip_votes.add(ctx.author)
                if len(player.skip_votes) < (required := player.required()):
                    return await send_localized_message(ctx, "player.controls.skip.vote", ctx.author, len(player.skip_votes), required, settings=settings)

        if index:
            player.queue.skipto(index)
        player.bind_controller_context(ctx)

        if player.queue._repeat.mode == voicelink.LoopType.TRACK:
            await player.set_repeat(voicelink.LoopType.OFF)
            
        await player.stop()
        await send_localized_message(ctx, "player.controls.skip.success", ctx.author, settings=settings)

    @commands.hybrid_command(name="back", aliases=get_aliases("back"))
    @app_commands.describe(index="Enter a index that you want to skip back to.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def back(self, ctx: commands.Context, index: int = 1):
        "Skips back to the previous song or skips to the specified previous song."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)
        settings = player.settings

        if not player.node._available:
            return await send_localized_message(ctx, "player.errors.nodeReconnectode", settings=settings)
        
        if not player.is_privileged(ctx.author):
            if ctx.author in player.previous_votes:
                return await send_localized_message(ctx, "voting.voted", ephemeral=True)
            
            player.previous_votes.add(ctx.author)
            if len(player.previous_votes) < (required := player.required()):
                return await send_localized_message(ctx, "player.controls.back.vote", ctx.author, len(player.previous_votes), required, settings=settings)

        if not player.is_playing:
            player.queue.backto(index)
            player.bind_controller_context(ctx)
            await player.do_next()
        else:
            player.queue.backto(index + 1)
            if player.queue._repeat.mode == voicelink.LoopType.TRACK:
                await player.set_repeat(voicelink.LoopType.OFF)
            player.bind_controller_context(ctx)
            await player.stop()

        await send_localized_message(ctx, "player.controls.back.success", ctx.author, settings=settings)

    @commands.hybrid_command(name="seek", aliases=get_aliases("seek"))
    @app_commands.describe(position="Input position. Exmaple: 1:20.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def seek(self, ctx: commands.Context, position: str):
        "Change the player position."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingPosition", ephemeral=True)

        if not player.current or player.position == 0:
            return await send_localized_message(ctx, "player.errors.noTrackPlaying", ephemeral=True)

        if not (num := format_to_ms(position)):
            return await send_localized_message(ctx, "time.formatError", ephemeral=True)

        await player.seek(num, ctx.author)
        await send_localized_message(ctx, "player.controls.seek", position)

    @commands.hybrid_group(
        name="queue", 
        aliases=get_aliases("queue"),
        fallback="list",
        invoke_without_command=True
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def queue(self, ctx: commands.Context):
        "Display the players queue songs in your queue."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if player.queue.is_empty:
            return await nowplay(ctx, player)
        view = QueueView(player=player, author=ctx.author)
        view.response = await dispatch_message(ctx, await view.build_embed(), view=view)

    @queue.command(name="export", aliases=get_aliases("export"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def export(self, ctx: commands.Context):
        "Exports the entire queue to a text file"
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)
        
        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)
        
        if player.queue.is_empty and not player.current:
            return await send_localized_message(ctx, "player.errors.noTrackPlaying", ephemeral=True)

        await ctx.defer()

        tracks = player.queue.tracks(True)
        temp = ""
        raw = "----------->Raw Info<-----------\n"

        total_length = 0
        for index, track in enumerate(tracks, start=1):
            temp += f"{index}. {track.title} [{format_ms(track.length)}]\n"
            raw += track.track_id
            if index != len(tracks):
                raw += ","
            total_length += track.length

        temp = "!Remember do not change this file!\n------------->Info<-------------\nGuild: {} ({})\nRequester: {} ({})\nTracks: {} - {}\n------------>Tracks<------------\n".format(
            ctx.guild.name, ctx.guild.id,
            ctx.author.display_name, ctx.author.id,
            len(tracks), format_ms(total_length)
        ) + temp
        temp += raw

        await ctx.reply(content="", file=discord.File(StringIO(temp), filename=f"{ctx.guild.id}_Full_Queue.txt"))

    @queue.command(name="import", aliases=get_aliases("import"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def _import(self, ctx: commands.Context, attachment: discord.Attachment):
        "Imports the text file and adds the track to the current queue."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)
        settings = player.settings

        try:
            bytes = await attachment.read()
            track_ids = bytes.split(b"\n")[-1]
            track_ids = track_ids.decode().split(",")
            
            tracks = [voicelink.Track(track_id=track_id, info=voicelink.Track.decode(track_id), requester=ctx.author) for track_id in track_ids]
            if not tracks:
                return await send_localized_message(ctx, "player.errors.noTrackFound", settings=settings)

            was_playing = player.is_playing
            player.bind_controller_context(ctx)
            index = await player.add_track(tracks)
            if not was_playing:
                await player.do_next()
            await send_localized_message(ctx, "player.playback.playlistLoad", attachment.filename, index, settings=settings)
            await self._refresh_controller_after_queue_add(player, ctx)
        except Exception as e:
            logger.error("error", exc_info=e)
            raise e

    @commands.hybrid_command(name="history", aliases=get_aliases("history"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def history(self, ctx: commands.Context):
        "Display the players queue songs in your history queue."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if not player.queue.history():
            return await nowplay(ctx, player)

        view = QueueView(player=player, author=ctx.author, is_queue=False)
        view.response = await dispatch_message(ctx, await view.build_embed(), view=view)

    @commands.hybrid_command(name="leave", aliases=get_aliases("leave"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def leave(self, ctx: commands.Context):
        "Disconnects the bot from your voice channel and chears the queue."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)
        settings = player.settings

        if not player.is_privileged(ctx.author):
            if ctx.author in player.stop_votes:
                return await send_localized_message(ctx, "voting.voted", ephemeral=True, settings=settings)
            else:
                player.stop_votes.add(ctx.author)
                if len(player.stop_votes) >= (required := player.required(leave=True)):
                    pass
                else:
                    return await send_localized_message(ctx, "player.controls.leave.vote", ctx.author, len(player.stop_votes), required, settings=settings)

        await player.teardown()
        await send_localized_message(ctx, "player.controls.leave.success", ctx.author, settings=settings)

    @commands.hybrid_command(name="nowplaying", aliases=get_aliases("nowplaying"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def nowplaying(self, ctx: commands.Context):
        "Shows details of the current track."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        await nowplay(ctx, player)

    @commands.hybrid_command(name="loop", aliases=get_aliases("loop"))
    @app_commands.describe(mode="Choose a looping mode.")
    @app_commands.choices(mode=[
        app_commands.Choice(name=loop_type.name.title(), value=loop_type.name)
        for loop_type in voicelink.LoopType
    ])
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def loop(self, ctx: commands.Context, mode: str):
        "Changes Loop mode."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingMode", ephemeral=True)

        await player.set_repeat(voicelink.LoopType[mode] if mode in voicelink.LoopType.__members__ else voicelink.LoopType.OFF, ctx.author)
        await send_localized_message(ctx, "player.controls.repeat", mode.capitalize())
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="clear", aliases=get_aliases("clear"))
    @app_commands.describe(queue="Choose a queue that you want to clear.")
    @app_commands.choices(queue=[
        app_commands.Choice(name='Queue', value='queue'),
        app_commands.Choice(name='History', value='history')
    ])
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def clear(self, ctx: commands.Context, queue: str = "queue"):
        "Remove all the tracks in your queue or history queue."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingQueue", ephemeral=True)

        await player.clear_queue(queue, ctx.author)
        await send_localized_message(ctx, "queue.management.cleared", queue.capitalize())
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="remove", aliases=get_aliases("remove"))
    @app_commands.describe(
        position1="Input a position from the queue to be removed.",
        position2="Set the range of the queue to be removed.",
        member="Remove tracks requested by a specific member."
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def remove(self, ctx: commands.Context, position1: int, position2: int = None, member: discord.Member = None):
        "Removes specified track or a range of tracks from the queue."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingQueue", ephemeral=True)

        removed_tracks = await player.remove_track(position1, position2, remove_target=member, requester=ctx.author)
        await send_localized_message(ctx, "queue.management.removed", len(removed_tracks.keys()))
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="forward", aliases=get_aliases("forward"))
    @app_commands.describe(position="Input an amount that you to forward to. Exmaple: 1:20")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def forward(self, ctx: commands.Context, position: str = "10"):
        "Forwards by a certain amount of time in the current track. The default is 10 seconds."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingPosition", ephemeral=True)

        if not player.current:
            return await send_localized_message(ctx, "player.errors.noTrackPlaying", ephemeral=True)

        if not (num := format_to_ms(position)):
            return await send_localized_message(ctx, "time.formatError", ephemeral=True)

        await player.seek(int(player.position + num))
        await send_localized_message(ctx, "player.controls.forward", format_ms(player.position + num))
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="rewind", aliases=get_aliases("rewind"))
    @app_commands.describe(position="Input an amount that you to rewind to. Exmaple: 1:20")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def rewind(self, ctx: commands.Context, position: str = "10"):
        "Rewind by a certain amount of time in the current track. The default is 10 seconds."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingPosition", ephemeral=True)

        if not player.current:
            return await send_localized_message(ctx, "player.errors.noTrackPlaying", ephemeral=True)
        
        if not (num := format_to_ms(position)):
            return await send_localized_message(ctx, "time.formatError", ephemeral=True)

        await player.seek(int(player.position - num))
        await send_localized_message(ctx, "player.controls.rewind", format_ms(player.position - num))
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="replay", aliases=get_aliases("replay"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def replay(self, ctx: commands.Context):
        "Reset the progress of the current song."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingPosition", ephemeral=True)

        if not player.current:
            return await send_localized_message(ctx, "player.errors.noTrackPlaying", ephemeral=True)
        
        await player.seek(0)
        await send_localized_message(ctx, "player.controls.replay")
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="shuffle", aliases=get_aliases("shuffle"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def shuffle(self, ctx: commands.Context):
        "Randomizes the tracks in the queue."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            if ctx.author in player.shuffle_votes:
                return await send_localized_message(ctx, "voting.voted", ephemeral=True)
            
            player.shuffle_votes.add(ctx.author)
            if len(player.shuffle_votes) < (required := player.required()):
                return await send_localized_message(ctx, "player.controls.shuffle.vote", ctx.author, len(player.shuffle_votes), required)
        
        await player.shuffle("queue", ctx.author)
        await send_localized_message(ctx, "player.controls.shuffle.success")
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="swap", aliases=get_aliases("swap"))
    @app_commands.describe(
        position1="The track to swap. Example: 2",
        position2="The track to swap with position1. Exmaple: 1"
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def swap(self, ctx: commands.Context, position1: int, position2: int):
        "Swaps the specified song to the specified song."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingPosition", ephemeral=True)

        track1, track2 = await player.swap_track(position1, position2, ctx.author)        
        await send_localized_message(ctx, "queue.management.swapped", track1.title, track2.title)
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="move", aliases=get_aliases("move"))
    @app_commands.describe(
        target="The track to move. Example: 2",
        to="The new position to move the track to. Exmaple: 1"
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def move(self, ctx: commands.Context, target: int, to: int):
        "Moves the specified song to the specified position."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)
        
        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingPosition", ephemeral=True)

        moved_track = await player.move_track(target, to, ctx.author)
        await send_localized_message(ctx, "queue.management.moved", moved_track, to)
        await self._refresh_controller_after_state_change(player, ctx)

    @commands.hybrid_command(name="lyrics", aliases=get_aliases("lyrics"))
    @app_commands.describe(title="Searches for your query and displays the reutned lyrics.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def lyrics(self, ctx: commands.Context, *, title: str = "", artist: str = ""):
        "Displays lyrics for the playing track."
        if not title:
            player: voicelink.Player = ctx.guild.voice_client
            if not player or not player.is_playing:
                return await send_localized_message(ctx, "player.errors.noTrackPlaying", ephemeral=True)
            
            title = player.current.title
            artist = player.current.author
        
        await ctx.defer()
        try:
            lyrics = await voicelink.fetch_lyrics(title, artist)
        except Exception as error:
            logger.warning("Lyrics lookup failed for title=%r artist=%r", title, artist, exc_info=error)
            lyrics = None
        if not lyrics:
            return await send_localized_message(ctx, "lyrics.notFound", ephemeral=True)

        view = LyricsView(name=title, source={_: re.findall(r'.*\n(?:.*\n){,22}', v or "") for _, v in lyrics.items()}, author=ctx.author)
        view.response = await dispatch_message(ctx, await view.build_embed(), view=view)

    @commands.hybrid_command(name="swapdj", aliases=get_aliases("swapdj"))
    @app_commands.describe(member="Choose a member to transfer the dj role.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def swapdj(self, ctx: commands.Context, member: discord.Member):
        "Transfer dj to another."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send_localized_message(ctx, "voice.connection.notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if player.dj.id != ctx.author.id or player.settings.get('dj', False):
            return await send_localized_message(ctx, "permissions.notDj", f"<@&{player.settings['dj']}>" if player.settings.get('dj') else player.dj.mention, ephemeral=True)

        if player.dj.id == member.id or member.bot:
            return await send_localized_message(ctx, "permissions.djToSelf", ephemeral=True)

        if member not in player.channel.members:
            return await send_localized_message(ctx, "permissions.djNotInChannel", member, ephemeral=True)

        player.dj = member
        await send_localized_message(ctx, "permissions.djSwapped", member)

    @commands.hybrid_command(name="autoplay", aliases=get_aliases("autoplay"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def autoplay(self, ctx: commands.Context):
        "Toggles autoplay mode, it will automatically queue the best songs to play."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send_localized_message(ctx, "player.errors.noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send_localized_message(ctx, "permissions.missingAutoPlay", ephemeral=True)

        check = not player.settings.get("autoplay", False)
        player.settings['autoplay'] = check
        await send_localized_message(ctx, "player.controls.autoplay", await LangHandler.get_lang(ctx.guild.id, "common.status.enabled" if check else "common.status.disabled"))

        if not player.is_playing:
            await player.do_next()
        await self._refresh_controller_after_state_change(player, ctx)
        
        if player.is_ipc_connected:
            await player.send_ws({"op": "toggleAutoplay", "status": check})

    @commands.hybrid_command(name="help", aliases=get_aliases("help"))
    @app_commands.autocomplete(category=help_autocomplete)
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def help(self, ctx: commands.Context, category: str = "News") -> None:
        "Lists all the bot commands."
        if category not in self.bot.cogs:
            category = "News"
        view = HelpView(self.bot, ctx.author)
        embed = view.build_embed(category)
        view.response = await dispatch_message(ctx, embed, view=view)

    @commands.hybrid_command(name="ping", aliases=get_aliases("ping"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def ping(self, ctx: commands.Context):
        "Test if the bot is alive, and see the delay between your commands and my response."
        player: voicelink.Player = ctx.guild.voice_client

        value = await LangHandler.get_lang(ctx.guild.id, "ping.title1", "ping.field1", "ping.title2", "ping.field2")
        
        embed = discord.Embed(color=Config().embed_color)
        embed.add_field(
            name=value[0],
            value=value[1].format(
                "0", "0", self.bot.latency, '😭' if self.bot.latency > 5 else ('😨' if self.bot.latency > 1 else '👌'), "St Louis, MO, United States"
        ))

        if player:
            embed.add_field(
                name=value[2],
                value=value[3].format(
                    player.node._identifier, player.ping, player.node.player_count, player.channel.rtc_region),
                    inline=False
            )

        await dispatch_message(ctx, embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Basic(bot))
