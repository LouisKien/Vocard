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
import io
import os
import json
import contextlib
import textwrap
import traceback
import voicelink

from typing import Optional
from discord.ext import commands

from .utils import BaseModal
from ..config import Config
from ..utils import format_ms, format_bytes
from ..language import LangHandler


class CogsDropdown(discord.ui.Select):
    def __init__(self, bot: commands.Bot, lang: str):
        self.bot: commands.Bot = bot
        self.lang: str = lang
        texts = LangHandler._get_lang(lang, "debug.cogs.selectPlaceholder", "debug.cogs.all", "debug.cogs.allDescription")

        super().__init__(
            placeholder=texts[0],
            options=[discord.SelectOption(label=texts[1], value="all", description=texts[2])] +
            [
                discord.SelectOption(
                    label=name.capitalize(),
                    description=LangHandler._get_lang(lang, f"help.categoryDescriptions.{name.lower()}")[:50]
                    if LangHandler._get_lang(lang, f"help.categoryDescriptions.{name.lower()}") != "Not found!"
                    else cog.description[:50],
                )
                for name, cog in bot.cogs.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0].lower()
        try:
            if selected == "all":
                for name in self.bot.cogs.copy().keys():
                    await self.bot.reload_extension(f"cogs.{name.lower()}")
            else:
                await self.bot.reload_extension(f"cogs.{selected}")
        except Exception as e:
            text = LangHandler._get_lang(self.lang, "debug.errors.reloadFailed")
            return await interaction.response.send_message(text.format(selected, e), ephemeral=True)

        await interaction.response.send_message(LangHandler._get_lang(self.lang, "debug.cogs.reloadSuccess").format(selected), ephemeral=True)

class NodesDropdown(discord.ui.Select):
    def __init__(self, bot: commands.Bot, lang: str):
        self.bot: commands.Bot = bot
        self.view: NodesPanel
        self.lang: str = lang
    
        super().__init__(
            placeholder=LangHandler._get_lang(lang, "debug.nodes.selectPlaceholder"),
            options=self.get_nodes()
        )
    
    def get_nodes(self) -> list[discord.SelectOption]:
        nodes = [
            discord.SelectOption(
                label=name,
                description=("🟢 " + LangHandler._get_lang(self.lang, "debug.nodes.connected") if node._available else "🔴 " + LangHandler._get_lang(self.lang, "debug.nodes.disconnected")) + f" - {LangHandler._get_lang(self.lang, 'debug.metrics.players')}: {node.player_count} ({node.latency if node._available else 0:.2f}ms)")
            for name, node in voicelink.NodePool._nodes.items()
        ]
        
        if not nodes:
            nodes = [discord.SelectOption(label=LangHandler._get_lang(self.lang, "debug.errors.nodeNotFound"))]
            
        return nodes
    
    def update(self) -> None:
        self.options = self.get_nodes()
        
    async def callback(self, interaction: discord.Interaction) -> None:
        selected_node = self.values[0]
        node = voicelink.NodePool._nodes.get(selected_node, None)
        if not node:
            return await interaction.response.send_message(LangHandler._get_lang(self.lang, "debug.errors.nodeNotFound"), ephemeral=True)
        
        self.view.selected_node = node
        await interaction.response.defer()
        await self.view.message.edit(embed=self.view.build_embed(), view=self.view)
        
class ExecutePanel(discord.ui.View):
    def __init__(self, bot, lang: str, *, timeout = 180):
        self.bot: commands.Bot = bot
        self.lang: str = lang

        self.message: discord.WebhookMessage = None
        self.code: str = None
        self._error: Exception = None

        super().__init__(timeout=timeout)

    def toggle_button(self, name: str, status: bool):
        child: discord.ui.Button
        for child in self.children:
            if child.custom_id == name:
                child.disabled = status
                break

    def clear_code(self, content: str):
        """Automatically removes code blocks from the code."""
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        return content.strip('` \n')
    
    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(view=self)

    async def execute(self, interaction: discord.Interaction):
        modal = BaseModal(
            title=LangHandler._get_lang(self.lang, "debug.execute.title"),
            custom_id="execute_code_modal",
            items=[discord.ui.TextInput(
                label=LangHandler._get_lang(self.lang, "debug.execute.label"),
                placeholder=LangHandler._get_lang(self.lang, "debug.execute.placeholder"),
                style=discord.TextStyle.long,
                custom_id="code_runner",
                default=self.code
            )]
        )
        await interaction.response.send_modal(modal)
        await modal.wait()

        if not (code := modal.values.get("code_runner")):
            return
        
        self._error = None
        text = ""

        local_variables = {
            "discord": discord,
            "bot": self.bot,
            "interaction": interaction,
            "input": None
        }

        self.code = self.clear_code(code)
        str_obj = io.StringIO() #Retrieves a stream of data
        try:
            with contextlib.redirect_stdout(str_obj):
                exec(f"async def func():\n{textwrap.indent(self.code, '  ')}", local_variables)
                obj = await local_variables["func"]()
                result = f"{str_obj.getvalue()}\n-- {obj}\n"
        except Exception as e:
            text = f"{e.__class__.__name__}: {e}"
            self._error = e

        if not self._error:
            text = "\n".join([f"{'%03d' % index} | {i}" for index, i in enumerate(result.split("\n"), start=1)])

        self.toggle_button("Error", True if self._error is None else False)

        if not self.message:
            self.message = await interaction.followup.send(f"```{text}```", view=self, ephemeral=True)
        else:
            await self.message.edit(content=f"```{text}```", view=self)

    @discord.ui.button(label=" ", emoji="🗑️", custom_id="end")
    async def end(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.message:
            await self.message.delete()
        self.stop()

    @discord.ui.button(label=" ", emoji="🔄", custom_id="rerun")
    async def rerun(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.execute(interaction)

    @discord.ui.button(label=" ", emoji="👾", custom_id="Error")
    async def error(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = ''.join(traceback.format_exception(self._error, self._error, self._error.__traceback__))
        await self.message.edit(content=f"```py\n{result}```")

class NodesPanel(discord.ui.View):
    def __init__(self, bot, lang: str, *, timeout: float | None = 180):
        super().__init__(timeout=timeout)
        self.message: Optional[discord.Message] = None
        self.selected_node: Optional[voicelink.Node] = None
        self.lang: str = lang
        
        self.add_item(NodesDropdown(bot, lang))
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        texts = LangHandler._get_lang(
            self.lang,
            "debug.buttons.add",
            "debug.buttons.remove",
            "debug.buttons.reconnect",
            "debug.buttons.connect",
            "debug.buttons.disconnect",
        )
        mapping = {"add": texts[0], "remove": texts[1], "reconnect": texts[2], "connect": texts[3], "disconnect": texts[4]}
        for child in self.children:
            if child.custom_id in mapping:
                child.label = mapping[child.custom_id]
    
    def update_btn_status(self) -> None:
        for child in self._children:
            if isinstance(child, discord.ui.Button) and child.custom_id != "add":
                child.disabled = self.selected_node is None
            
            if isinstance(child, discord.ui.Select):
                child.update()
        
    def build_embed(self) -> discord.Embed:
        self.update_btn_status()
        panel_texts = LangHandler._get_lang(
            self.lang,
            "debug.panel.nodesTitle",
            "debug.panel.noNodesConnected",
            "debug.panel.noExtraData",
            "debug.nodes.connected",
            "debug.nodes.disconnected",
            "debug.metrics.address",
            "debug.metrics.players",
            "debug.metrics.cpu",
            "debug.metrics.ram",
            "debug.metrics.latency",
            "debug.metrics.uptime",
        )
        embed = discord.Embed(title=panel_texts[0], color=Config().embed_color)
        
        if not voicelink.NodePool._nodes:
            embed.description = f"```{panel_texts[1]}```"
        
        else:
            for name, node in voicelink.NodePool._nodes.items():
                if self.selected_node and self.selected_node._identifier != node._identifier:
                    continue
                
                if node._available and node.stats:
                    total_memory = node.stats.used + node.stats.free
                    embed.add_field(
                        name=f"{name} Node - 🟢 {panel_texts[3]}",
                        value=f"```• {panel_texts[5]}: {node._host}:{node._port}\n" \
                            f"• {panel_texts[6]}: {len(node._players)}\n" \
                            f"• {panel_texts[7]}:     {node.stats.cpu_process_load:.1f}%\n" \
                            f"• {panel_texts[8]}:     {format_bytes(node.stats.free)}/{format_bytes(total_memory, True)} ({(node.stats.free/total_memory) * 100:.1f}%)\n"
                            f"• {panel_texts[9]}: {node.latency:.2f}ms\n" \
                            f"• {panel_texts[10]}:  {format_ms(node.stats.uptime)}```"
                    )
                else:
                    embed.add_field(
                        name=f"{name} Node - 🔴 {panel_texts[4]}",
                        value=f"```• {panel_texts[5]}: {node._host}:{node._port}\n" \
                            f"• {panel_texts[6]}: {len(node._players)}\n{panel_texts[2]}```",
                    )
                    
        return embed
    
    async def on_error(self, interaction: discord.Interaction, error, item) -> None:
        return await interaction.followup.send(error, ephemeral=True)
    
    @discord.ui.button(label=" ", custom_id="add", emoji="➕", style=discord.ButtonStyle.green)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        texts = LangHandler._get_lang(
            self.lang,
            "debug.modals.createNodeTitle",
            "debug.modals.hostLabel",
            "debug.modals.hostPlaceholder",
            "debug.modals.portLabel",
            "debug.modals.portPlaceholder",
            "debug.modals.passwordLabel",
            "debug.modals.passwordPlaceholder",
            "debug.modals.secureLabel",
            "debug.modals.securePlaceholder",
            "debug.modals.identifierLabel",
            "debug.modals.identifierPlaceholder",
        )
        modal = BaseModal(
            title=texts[0],
            custom_id="add_node_modal",
            items=[
                discord.ui.TextInput(
                    label=texts[1],
                    placeholder=texts[2],
                    custom_id="host"
                ),
                discord.ui.TextInput(
                    label=texts[3],
                    placeholder=texts[4],
                    custom_id="port"
                ),
                discord.ui.TextInput(
                    label=texts[5],
                    placeholder=texts[6],
                    custom_id="password"
                ),
                discord.ui.TextInput(
                    label=texts[7],
                    placeholder=texts[8],
                    custom_id="secure",
                    default="false"
                ),
                discord.ui.TextInput(
                    label=texts[9],
                    placeholder=texts[10],
                    custom_id="identifier"
                )
            ]
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        
        v = modal.values
        try:
            config = {
                "host": v["host"],
                "port": int(v["port"]),
                "password": v["password"],
                "secure": v["secure"].startswith("t"),
                "identifier": v["identifier"]
            }
        except Exception:
            return await interaction.response.send_message(LangHandler._get_lang(self.lang, "debug.errors.invalidNodeInput"), ephemeral=True)
        
        try:
            await voicelink.NodePool.create_node(bot=interaction.client, **config)
            await interaction.followup.send(LangHandler._get_lang(self.lang, "debug.nodes.connectedMessage").format(v["identifier"]), ephemeral=True)
            await self.message.edit(embed=self.build_embed(), view=self)
            
        except Exception as e:
            return await interaction.followup.send(e, ephemeral=True)
        
    @discord.ui.button(label=" ", custom_id="remove", emoji="➖", style=discord.ButtonStyle.red, disabled=True)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_node:
            return await interaction.response.send_message(LangHandler._get_lang(self.lang, "debug.errors.selectNodeFirst"), ephemeral=True)

        identifier = self.selected_node._identifier
        await self.selected_node.disconnect(remove_from_pool=True)
        
        self.selected_node = None
        
        await self.message.edit(embed=self.build_embed(), view=self)
        await interaction.response.send_message(LangHandler._get_lang(self.lang, "debug.nodes.removed").format(identifier), ephemeral=True)
        
    @discord.ui.button(label=" ", custom_id="reconnect", disabled=True, row=1)
    async def reconnect(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.selected_node.is_connected:
            await self.selected_node.disconnect()
            await self.selected_node.connect()
            await self.message.edit(embed=self.build_embed(), view=self)
    
    @discord.ui.button(label=" ", custom_id="connect", disabled=True, row=1)
    async def connect(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not self.selected_node.is_connected:
            await self.selected_node.connect()
            await self.message.edit(embed=self.build_embed(), view=self)
        
    @discord.ui.button(label=" ", custom_id="disconnect", style=discord.ButtonStyle.red, disabled=True, row=1)
    async def disconnect(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.selected_node.is_connected:
            await self.selected_node.disconnect()
            
            await self.message.edit(embed=self.build_embed(), view=self)
        
class CogsView(discord.ui.View):
    def __init__(self, bot, lang: str, *, timeout: float | None = 180):
        super().__init__(timeout=timeout)

        self.add_item(CogsDropdown(bot, lang))
   
class DebugView(discord.ui.View):
    def __init__(self, bot, lang: str, *, timeout: float | None = 180):
        self.bot: commands.Bot = bot
        self.lang: str = lang
        self.panel: ExecutePanel = ExecutePanel(bot, lang)

        super().__init__(timeout=timeout)
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        texts = LangHandler._get_lang(
            self.lang,
            "debug.buttons.command",
            "debug.buttons.cogs",
            "debug.buttons.resync",
            "debug.buttons.nodes",
            "debug.buttons.stopBot",
        )
        mapping = {"run_command": texts[0], "reload_cog": texts[1], "sync": texts[2], "nodes": texts[3], "stop": texts[4]}
        for child in self.children:
            if child.custom_id in mapping:
                child.label = mapping[child.custom_id]
        end_texts = LangHandler._get_lang(self.lang, "debug.buttons.end", "debug.buttons.rerun", "debug.buttons.error")
        end_mapping = {"end": end_texts[0], "rerun": end_texts[1], "Error": end_texts[2]}
        for child in self.panel.children:
            if child.custom_id in end_mapping:
                child.label = end_mapping[child.custom_id]

    @discord.ui.button(label=' ', custom_id="run_command", emoji="▶️", style=discord.ButtonStyle.green)
    async def run_command(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.panel.execute(interaction)
    
    @discord.ui.button(label=' ', custom_id="reload_cog", emoji="⚙️")
    async def reload_cog(self, interaction: discord.Interaction, button: discord.ui.Button):
        return await interaction.response.send_message(LangHandler._get_lang(self.lang, "debug.cogs.open"), view=CogsView(self.bot, self.lang), ephemeral=True)
    
    @discord.ui.button(label=" ", custom_id="sync", emoji="🔄")
    async def sync(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 " + LangHandler._get_lang(self.lang, "debug.sync.start"), ephemeral=True)
        await self.bot.tree.sync()
        await interaction.edit_original_response(content="✅ " + LangHandler._get_lang(self.lang, "debug.sync.done"))
    
    @discord.ui.button(label=" ", custom_id="nodes", emoji="📡")
    async def nodes(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = NodesPanel(self.bot, self.lang)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()
    
    @discord.ui.button(label=" ", custom_id="stop", emoji="🔴")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        for name in self.bot.cogs.copy().keys():
            try:
                await self.bot.unload_extension(name)
            except Exception:
                pass

        player_data = []
        for identifier, node in voicelink.NodePool._nodes.items():
            for guild_id, player in node._players.copy().items():
                if player.guild.me is None or player.guild.me.voice or not player.current:
                    continue

                player_data.append(player.data)
                try:
                    await player.teardown()
                except Exception:
                    pass

        if os.path.exists(Config.LAST_SESSION_FILE_DIR):
            os.remove(Config.LAST_SESSION_FILE_DIR)    

        with open(Config.LAST_SESSION_FILE_DIR, "w", encoding="utf8") as f:
            json.dump(player_data, f, ensure_ascii=False, indent=4)
        await interaction.client.close()
