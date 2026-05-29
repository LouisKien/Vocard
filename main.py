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

import discord
import sys
import os
import aiohttp
import update
import logging
import function as func

from discord.ext import commands
from logging.handlers import TimedRotatingFileHandler
from voicelink import Config, LangHandler, MongoDBHandler, IPCClient, VoicelinkException
from voicelink.utils import dispatch_message

class Translator(discord.app_commands.Translator):
    MISSING_TRANSLATOR: dict[str, list[str]] = {}
    MESSAGE_TO_DISCORD_LOCALE = {"VN": "VI"}

    async def load(self):
        func.logger.info("Loaded Translator")
        
    async def unload(self):
        func.logger.info("Unload Translator")
        
    async def translate(
        self,
        string: discord.app_commands.locale_str,
        locale: discord.Locale,
        context: discord.app_commands.TranslationContext
    ) -> str | None:
        locale_key = str(locale).upper()
        local_translations = LangHandler._local_langs.get(locale_key)
        if not local_translations:
            return None

        translated_text = local_translations.get(string.message)
        if translated_text is not None:
            return translated_text

        expected_locale = self.MESSAGE_TO_DISCORD_LOCALE.get(LangHandler._default_lang, LangHandler._default_lang)
        if locale_key != expected_locale:
            return None

        missing = self.MISSING_TRANSLATOR.setdefault(locale_key, [])
        if string.message not in missing:
            missing.append(string.message)

        return None

class Vocard(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.ipc_client: IPCClient

    def is_allowed_guild(self, guild_id: int | None) -> bool:
        return bot_config.is_allowed_guild(guild_id)

    async def leave_unauthorized_guilds(self) -> None:
        if not bot_config.server_id:
            return

        for guild in list(self.guilds):
            if self.is_allowed_guild(guild.id):
                continue
            func.logger.warning(
                "Leaving unauthorized guild %s (%s); expected guild %s.",
                guild.name,
                guild.id,
                bot_config.server_id
            )
            await guild.leave()

    async def on_message(self, message: discord.Message, /) -> None:
        # Ignore messages from bots or DMs
        if message.author.bot or not message.guild:
            return False

        if not self.is_allowed_guild(message.guild.id):
            return False

        # Check if the bot is directly mentioned
        if message.content.strip() == self.user.mention and not message.mention_everyone:
            prefix = await self.command_prefix(self, message)
            if not prefix:
                return await message.channel.send("I don't have a bot prefix set.")
            return await message.channel.send(f"My prefix is `{prefix}`")

        # Fetch guild settings and check if the mesage is in the music request channel
        settings = MongoDBHandler.get_cached_settings(message.guild.id)
        if not settings:
            settings = await MongoDBHandler.get_settings(message.guild.id)
        if settings and (request_channel := settings.get("music_request_channel")):
            if message.channel.id == request_channel.get("text_channel_id"):
                ctx = await self.get_context(message)    
                try:
                    if not ctx.prefix:
                        cmd = self.get_command("play")
                        if message.content:
                            await cmd(ctx, query=message.content)

                        elif message.attachments:
                            for attachment in message.attachments:
                                await cmd(ctx, query=attachment.url)

                except Exception as e:
                    await dispatch_message(ctx, str(e), ephemeral=True)

                finally:
                    await message.delete()

        await self.process_commands(message)

    async def setup_hook(self) -> None:
        # Connecting to MongoDB
        await MongoDBHandler.init(bot_config.mongodb_url, bot_config.mongodb_name)

        # Set translator
        await self.tree.set_translator(Translator())

        # Loading all the module in `cogs` folder
        for module in os.listdir(func.ROOT_DIR / "cogs"):
            if module.endswith('.py'):
                try:
                    await self.load_extension(f"cogs.{module[:-3]}")
                    func.logger.info(f"Loaded {module[:-3]}")
                except Exception as e:
                    func.logger.error(f"Something went wrong while loading {module[:-3]} cog.", exc_info=e)

        self.ipc_client: IPCClient = IPCClient(self, **bot_config.ipc_client)
        if bot_config.ipc_client.get("enable", False):
            try:
                await self.ipc_client.connect()
            except Exception as e:
                func.logger.error(f"Cannot connected to dashboard! - Reason: {e}")

        if bot_config.server_id:
            guild = discord.Object(id=bot_config.server_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        elif not bot_config.version or bot_config.version != update.__version__:
            await self.tree.sync()

        if func.settings_override_exists() and (not bot_config.version or bot_config.version != update.__version__):
            func.update_json("settings.json", new_data={"version": update.__version__})

        for locale_key, values in self.tree.translator.MISSING_TRANSLATOR.items():
            func.logger.warning(f'Missing translation for "{", ".join(values)}" in "{locale_key}"')
        self.tree.translator.MISSING_TRANSLATOR.clear()

    async def on_ready(self):
        func.logger.info("------------------")
        func.logger.info(f"Logging As {self.user}")
        func.logger.info(f"Bot ID: {self.user.id}")
        func.logger.info("------------------")
        func.logger.info(f"{bot_config.bot_name} Version: {update.__version__}")
        func.logger.info(f"Discord Version: {discord.__version__}")
        func.logger.info(f"Python Version: {sys.version}")
        func.logger.info("------------------")

        bot_config.client_id = self.user.id
        LangHandler._local_langs.clear()
        await self.leave_unauthorized_guilds()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if self.is_allowed_guild(guild.id):
            return

        func.logger.warning(
            "Joined unauthorized guild %s (%s); leaving because SERVER_ID is %s.",
            guild.name,
            guild.id,
            bot_config.server_id
        )
        await guild.leave()

    async def on_command_error(self, ctx: commands.Context, exception, /) -> None:
        error = getattr(exception, 'original', exception)
        if ctx.interaction:
            error = getattr(error, 'original', error)

        if isinstance(error, (commands.CommandNotFound, aiohttp.client_exceptions.ClientOSError, discord.errors.NotFound)):
            return

        elif isinstance(error, (commands.CommandOnCooldown, commands.MissingPermissions, commands.RangeError, commands.BadArgument)):
            pass

        elif isinstance(error, (commands.MissingRequiredArgument, commands.MissingRequiredAttachment)):
            command = f"{ctx.prefix}" + (f"{ctx.command.parent.qualified_name} " if ctx.command.parent else "") + f"{ctx.command.name} {ctx.command.signature}"
            position = command.find(f"<{ctx.current_parameter.name}>") + 1
            description = f"**Correct Usage:**\n```{command}\n" + " " * position + "^" * len(ctx.current_parameter.name) + "```\n"
            if ctx.command.aliases:
                description += f"**Aliases:**\n`{', '.join([f'{ctx.prefix}{alias}' for alias in ctx.command.aliases])}`\n\n"
            description += f"**Description:**\n{ctx.command.help}\n\u200b"

            embed = discord.Embed(description=description, color=bot_config.embed_color)
            embed.set_footer(icon_url=ctx.me.display_avatar.url, text=f"More Help: {bot_config.invite_link}")
            return await ctx.reply(embed=embed)

        elif not issubclass(error.__class__, VoicelinkException):
            error = await Lang_handler.get_lang(ctx.guild.id, "common.errors.unknown") + bot_config.invite_link
            func.logger.error(f"An unexpected error occurred in the {ctx.command.name} command on the {ctx.guild.name}({ctx.guild.id}).", exc_info=exception)

        try:
            return await ctx.reply(error, ephemeral=True)
        except discord.HTTPException:
            pass

class CommandCheck(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        if interaction.type == discord.InteractionType.application_command:
            if not interaction.guild:
                await interaction.response.send_message("This command can only be used in guilds!")
                return False

            if not bot_config.is_allowed_guild(interaction.guild_id):
                await interaction.response.send_message("This bot is locked to a different server.", ephemeral=True)
                return False

            channel_perm = interaction.channel.permissions_for(interaction.guild.me)
            if not channel_perm.read_messages or not channel_perm.send_messages:
                await interaction.response.send_message("I don't have permission to read or send messages in this channel.", ephemeral=True)
                return False
            
        return True

async def get_prefix(bot: commands.Bot, message: discord.Message) -> str:
    if not bot_config.is_allowed_guild(message.guild.id):
        return ""
    settings = MongoDBHandler.get_cached_settings(message.guild.id)
    if not settings:
        settings = await MongoDBHandler.get_settings(message.guild.id)
    prefix = settings.get("prefix", bot_config.bot_prefix)
    return prefix if prefix is not None else ""

# Loading settings and logger
bot_config = Config(func.load_settings())
Lang_handler = LangHandler.init()

def _has_value(value) -> bool:
    return value not in (None, "", 0, "0")

def _env_enabled(*names: str, default: bool = True) -> bool:
    for name in names:
        value = os.getenv(name)
        if value in (None, ""):
            continue
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default

def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return None

def validate_runtime_config(config: Config) -> None:
    missing: list[str] = []

    if not _has_value(config.token):
        missing.append("DISCORD_TOKEN (or legacy BOT_TOKEN/TOKEN)")
    if not _has_value(config.server_id):
        missing.append("SERVER_ID (or legacy DISCORD_GUILD_ID)")
    if not _has_value(config.mongodb_url):
        missing.append("MONGODB_URL")
    if not _has_value(config.mongodb_name):
        missing.append("MONGODB_NAME")

    node = config.nodes.get("DEFAULT", {})
    if not _has_value(node.get("host")):
        missing.append("LAVALINK_HOST")
    if not _has_value(node.get("port")):
        missing.append("LAVALINK_PORT")
    if not _has_value(node.get("password")):
        missing.append("LAVALINK_PASSWORD")

    if _env_enabled("LAVASRC_SPOTIFY_ENABLED", "SPOTIFY_ENABLED", default=True):
        if not _first_env("LAVASRC_SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_ID"):
            missing.append("LAVASRC_SPOTIFY_CLIENT_ID")
        if not _first_env("LAVASRC_SPOTIFY_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET"):
            missing.append("LAVASRC_SPOTIFY_CLIENT_SECRET")

    if missing:
        raise RuntimeError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Copy .env.example to .env, fill the required values, then run docker compose up -d --build."
        )

LOG_SETTINGS = bot_config.logging
if (LOG_FILE := LOG_SETTINGS.get("file", {})).get("enable", True):
    log_path = os.path.abspath(LOG_FILE.get("path", "./logs"))
    if not os.path.exists(log_path):
        os.makedirs(log_path)

    file_handler = TimedRotatingFileHandler(filename=f'{log_path}/vocard.log', encoding="utf-8", backupCount=LOG_SETTINGS.get("max_history", 30), when="d")
    file_handler.namer = lambda name: name.replace(".log", "") + ".log"
    file_handler.setFormatter(logging.Formatter('{asctime} [{levelname:<8}] {name}: {message}', '%Y-%m-%d %H:%M:%S', style='{'))
    logging.getLogger().addHandler(file_handler)

for log_name, log_level in LOG_SETTINGS.get("level", {}).items():
    _logger = logging.getLogger(log_name)
    _logger.setLevel(log_level)

# Setup the bot object
intents = discord.Intents.default()
intents.message_content = False if bot_config.bot_prefix is None else True
intents.members = bot_config.ipc_client.get("enable", False)
intents.voice_states = True
intents.presences = False

bot = Vocard(
    command_prefix=get_prefix,
    help_command=None,
    tree_cls=CommandCheck,
    chunk_guilds_at_startup=False,
    activity=discord.Activity(type=discord.ActivityType.listening, name="Starting..."),
    case_insensitive=True,
    intents=intents
)

if __name__ == "__main__":
    validate_runtime_config(bot_config)
    if bot_config.check_upstream_updates:
        update.check_version(with_msg=True)
    bot.run(bot_config.token, root_logger=True)
