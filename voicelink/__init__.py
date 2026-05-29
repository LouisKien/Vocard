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

__version__ = "1.5"
__author__ = 'Vocard Development, ChocoMeow'
__license__ = "MIT"
__copyright__ = "Copyright 2023 - present (c) Vocard Development, ChocoMeow"

from .config import Config as Config
from .enums import SearchType as SearchType, LoopType as LoopType, TrackRecType as TrackRecType
from .events import *  # noqa: F403
from .exceptions import *  # noqa: F403
from .filters import *  # noqa: F403
from .objects import *  # noqa: F403
from .pool import *  # noqa: F403
from .queue import *  # noqa: F403
from .player import Player as Player, connect_channel as connect_channel
from .placeholders import PlayerPlaceholder as PlayerPlaceholder, BotPlaceholder as BotPlaceholder
from .mongodb import MongoDBHandler as MongoDBHandler
from .language import LangHandler as LangHandler
from .lyrics import LYRICS_PLATFORMS as LYRICS_PLATFORMS
from .ipc import IPCClient as IPCClient
