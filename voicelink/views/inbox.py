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
import time

from typing import Any

from ..config import Config
from ..language import LangHandler
from ..mongodb import MongoDBHandler

class Select_message(discord.ui.Select):
    def __init__(self, inbox, lang: str):
        self.view: InboxView
        options = [
            discord.SelectOption(
                label=f"{index}. {mail['title'][:50]}",
                description=self._format_mail_type(lang, mail["type"]),
                emoji='✉️' if mail['type'] == 'invite' else '📢',
            )
            for index, mail in enumerate(inbox, start=1)
        ]

        super().__init__(
            placeholder=LangHandler._get_lang(lang, "inbox.selectPlaceholder"),
            options=options, custom_id='select'
        )

    @staticmethod
    def _format_mail_type(lang: str, mail_type: str) -> str:
        key = "inbox.types.invite" if mail_type == "invite" else "inbox.types.notification"
        return LangHandler._get_lang(lang, key)

    async def callback(self, interaction: discord.Interaction):
        self.view.current = self.view.inbox[int(self.values[0].split(". ")[0]) - 1]
        await self.view.button_change(interaction)

class InboxView(discord.ui.View):
    def __init__(self, author: discord.Member, inbox: list[dict[str, Any]]):
        super().__init__(timeout=60)
        self.inbox: list[dict[str, Any]] = inbox
        self.new_playlist = []

        self.author: discord.Member = author
        self.response: discord.Message = None
        self.current = None
        self.lang: str = MongoDBHandler.get_cached_settings(author.guild.id).get("lang", LangHandler._default_lang)

        self.add_item(Select_message(inbox, self.lang))
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        texts = LangHandler._get_lang(
            self.lang,
            "inbox.buttons.accept",
            "inbox.buttons.dismiss",
            "inbox.buttons.save",
        )
        mapping = {"accept": texts[0], "dismiss": texts[1], "save": texts[2]}
        for child in self.children:
            if child.custom_id in mapping:
                child.label = mapping[child.custom_id]

    async def interaction_check(self, interaction: discord.Interaction):
        return interaction.user == self.author

    def build_embed(self) -> discord.Embed:
        texts = LangHandler._get_lang(
            self.lang,
            "inbox.title",
            "inbox.maxMessages",
            "inbox.headers",
            "inbox.messageInfo",
            "inbox.senderId",
            "inbox.playlistId",
            "inbox.inviteTime",
        )
        headers = texts[2].split(",")
        embed=discord.Embed(
            title=texts[0].format(self.author.display_name),
            description=texts[1].format(len(self.inbox)) + '```%0s %2s %20s\n' % ("   ", headers[0], headers[1]) + '\n'.join('%0s %2s. %35s'% ('✉️' if mail['type'] == 'invite' else '📢', index, mail['title'][:35] + "...") for index, mail in enumerate(self.inbox, start=1)) + '```',
            color=Config().embed_color
        )

        if self.current:
            embed.add_field(name=texts[3], value=f"```{self.current['description']}\n{texts[4]}: {self.current['sender']}\n{texts[5]}: {self.current['referId']}\n{texts[6]}: {time.strftime('%d-%m %H:%M:%S', time.gmtime(int(self.current['time'])))}```")
        return embed
    
    async def button_change(self, interaction: discord.Interaction):
        for child in self.children:
            if child.custom_id in ['accept', 'dismiss']:
                child.disabled = True if self.current is None else False
            elif child.custom_id == "select":
                child.options = [
                    discord.SelectOption(
                        label=f"{index}. {mail['title'][:50]}",
                        description=Select_message._format_mail_type(self.lang, mail["type"]),
                        emoji='✉️' if mail['type'] == 'invite' else '📢',
                    )
                    for index, mail in enumerate(self.inbox, start=1)
                ]

        if not self.inbox:
            await interaction.response.edit_message(embed=self.build_embed(), view=None)
            return self.stop()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.response.edit(view=self)
        except discord.HTTPException:
            pass
        
    @discord.ui.button(label=' ', style=discord.ButtonStyle.green, custom_id="accept", disabled=True)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.new_playlist.append(self.current)
        self.inbox.remove(self.current)
        self.current = None
        await self.button_change(interaction)
    
    @discord.ui.button(label=' ', style=discord.ButtonStyle.red, custom_id="dismiss", disabled=True)
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.inbox.remove(self.current)
        self.current = None
        await self.button_change(interaction)
    
    @discord.ui.button(label=' ', custom_id="save", style=discord.ButtonStyle.blurple)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.response.edit(view=None) 
        self.stop()
