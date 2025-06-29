# SPDX-FileCopyrightText: 2019 Scott Shawcroft for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
`adafruit_display_notification`
================================================================================

Very basic notification widgets.

"""

import displayio
import terminalio
from adafruit_display_text import label

try:
    from typing import List
except ImportError:
    pass

__version__ = "1.0.4"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_Display_Notification.git"

TEXT_FONT = terminalio.FONT


class NotificationFree(displayio.Group):
    """Widget to show when no notifications are active."""

    def __init__(self, width: int, height: int, *, dark_mode: bool = True):
        super().__init__()

        if dark_mode:
            text_color = 0xFFFFFF
        else:
            text_color = 0x000000

        # Create the text label
        self.title = label.Label(TEXT_FONT, text="None!", y=height // 2, color=text_color)
        self.append(self.title)


class PlainNotification(displayio.Group):
    """Plain text widget with a title and message."""

    def __init__(
        self, title: str, message: str, width: int, height: int, *, dark_mode: bool = True
    ):
        super().__init__()

        # Set text, font, and color
        if dark_mode:
            text_color = 0xFFFFFF
        else:
            text_color = 0x000000

        # Create the text label
        self.title = label.Label(TEXT_FONT, text=title, color=text_color, y=8)
        self.append(self.title)

        # TODO: Move this into Label or a TextBox.
        lines = PlainNotification._wrap_nicely(message, width // 7)
        max_lines = height // 20
        message = "\n".join(lines[:max_lines])

        self.message = label.Label(
            terminalio.FONT, text=message, color=text_color, x=2, y=height // 2 + 8
        )
        self.append(self.message)

    # cribbed from pyportal
    @staticmethod
    def _wrap_nicely(string: str, max_chars: int) -> List[str]:
        """A helper that will return a list of lines with word-break wrapping.
        :param str string: The text to be wrapped.
        :param int max_chars: The maximum number of characters on a line before wrapping.
        """
        string = string.replace("\n", "").replace("\r", "")  # strip confusing newlines
        words = string.split(" ")
        the_lines = []
        the_line = ""
        for w in words:
            if len(the_line + " " + w) <= max_chars:
                the_line += " " + w
            else:
                the_lines.append(the_line)
                the_line = "" + w
        if the_line:  # last line remaining
            the_lines.append(the_line)
        # remove first space from first line:
        the_lines[0] = the_lines[0][1:]
        return the_lines
