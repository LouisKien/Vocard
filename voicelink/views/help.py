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
from discord.ext import commands

from ..config import Config
from ..language import LangHandler
from ..mongodb import MongoDBHandler


def _resolve_lang(author: discord.Member) -> str:
    guild = getattr(author, "guild", None)
    if guild:
        return MongoDBHandler.get_cached_settings(guild.id).get("lang", LangHandler._default_lang)
    return LangHandler._default_lang

class HelpDropdown(discord.ui.Select):
    def __init__(self, categories: list[tuple[str, str]], lang: str) -> None:
        self.view: HelpView
        texts = LangHandler._get_lang(
            lang,
            "help.menu.selectPlaceholder",
            "help.menu.news",
            "help.menu.news",
            "help.menu.tutorial",
            "help.menu.tutorial",
        )
        news_label, tutorial_label = texts[1], texts[3]

        super().__init__(
            placeholder=texts[0],
            min_values=1, max_values=1,
            options=[
                discord.SelectOption(emoji="🆕", label=news_label, value="news", description=self._category_description(lang, "news")),
                discord.SelectOption(emoji="🕹️", label=tutorial_label, value="tutorial", description=self._category_description(lang, "tutorial")),
            ] + [
                discord.SelectOption(
                    emoji=emoji,
                    label=category_label,
                    value=category_key,
                    description=self._category_description(lang, category_key),
                )
                for (category_key, category_label), emoji in zip(categories, ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"])
            ],
            custom_id="select"
        )

    @staticmethod
    def _category_description(lang: str, category_key: str) -> str:
        return LangHandler._get_lang(lang, f"help.categoryDescriptions.{category_key.lower()}")
    
    async def callback(self, interaction: discord.Interaction) -> None:
        embed = self.view.build_embed(self.values[0])
        await interaction.response.edit_message(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author: discord.Member) -> None:
        super().__init__(timeout=60)

        self.author: discord.Member = author
        self.bot: commands.Bot = bot
        self.response: discord.Message = None
        self.lang: str = _resolve_lang(author)
        self.category_keys: list[str] = [name.lower() for name, cog in bot.cogs.items() if len([c for c in cog.walk_commands()])]
        self.categories: list[tuple[str, str]] = [(key, self._display_category(key)) for key in self.category_keys]
        button_texts = LangHandler._get_lang(
            self.lang,
            "help.buttons.website",
            "help.buttons.documentation",
            "help.buttons.github",
            "help.buttons.donate",
        )

        self.add_item(discord.ui.Button(label=button_texts[0], emoji='🌎', url='https://vocard.xyz'))
        self.add_item(discord.ui.Button(label=button_texts[1], emoji=':support:915152950471581696', url='https://docs.vocard.xyz'))
        self.add_item(discord.ui.Button(label=button_texts[2], emoji=':github:1098265017268322406', url='https://github.com/LouisKien/Vocard'))
        self.add_item(discord.ui.Button(label=button_texts[3], emoji=':patreon:913397909024800878', url='https://www.patreon.com/Vocard'))
        self.add_item(HelpDropdown(self.categories, self.lang))

    async def on_timeout(self) -> None:
        for child in self.children:
            if child.custom_id == "select":
                child.disabled = True
        try:
            await self.response.edit(view=self)
        except discord.HTTPException:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> None:
        return interaction.user == self.author

    def _display_category(self, category: str) -> str:
        localized = LangHandler._get_lang(self.lang, f"help.categoryLabels.{category.lower()}")
        return localized if localized != "Not found!" else category.capitalize()

    def _category_description(self, category: str, fallback: str = "") -> str:
        localized = LangHandler._get_lang(self.lang, f"help.categoryDescriptions.{category.lower()}")
        return localized if localized != "Not found!" else fallback

    def build_embed(self, category: str) -> discord.Embed:
        category = category.lower()
        display_categories = [("news", LangHandler._get_lang(self.lang, "help.menu.news")), ("tutorial", LangHandler._get_lang(self.lang, "help.menu.tutorial"))] + self.categories
        if category == "news":
            bot_name = Config().bot_name
            texts = LangHandler._get_lang(
                self.lang,
                "help.menu.title",
                "help.menu.availableCategories",
                "help.menu.informationTitle",
                "help.menu.informationBody",
                "help.menu.getStartedTitle",
                "help.menu.getStartedBody",
            )
            embed = discord.Embed(title=texts[0].format(bot_name), url="https://discord.com/channels/811542332678996008/811909963718459392/1069971173116481636", color=Config().embed_color)
            embed.add_field(
                name=texts[1].format(len(display_categories)),
                value="```py\n" + "\n".join(
                    ("👉 " if idx == 1 else f"{idx}. ") + label
                    for idx, (_, label) in enumerate(display_categories, start=1)
                ) + "\n```",
                inline=True
            )

            embed.add_field(name=texts[2], value=texts[3].format(bot_name), inline=True)
            embed.add_field(name=texts[4], value=f"```{texts[5].format(bot_name)}```", inline=False)
            
            return embed

        texts = LangHandler._get_lang(self.lang, "help.menu.categoryTitle", "help.menu.availableCategories", "help.menu.commandsTitle", "help.menu.tutorialBody")
        embed = discord.Embed(title=texts[0].format(self._display_category(category)), color=Config().embed_color)
        embed.add_field(
            name=texts[1].format(len(display_categories)),
            value="```py\n" + "\n".join(
                ("👉 " if key == category else f"{i}. ") + label
                for i, (key, label) in enumerate(display_categories, start=1)
            ) + "\n```",
            inline=True,
        )

        if category == 'tutorial':
            embed.description = texts[3]
            embed.set_image(url="https://cdn.discordapp.com/attachments/674788144931012638/917656288899514388/final_61aef3aa7836890135c6010c_669380.gif")
        else:
            cog = [c for _, c in self.bot.cogs.items() if _.lower() == category][0]

            commands = [command for command in cog.walk_commands()]
            embed.description = self._category_description(category, cog.description)
            embed.add_field(
                name=texts[2].format(self._display_category(category), len(commands)),
                value="```{}```".format("".join(f"/{command.qualified_name}\n" for command in commands if not command.qualified_name == cog.qualified_name))
            )

        return embed
