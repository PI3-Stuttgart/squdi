#!/usr/bin/env python
# pylint: disable=unused-argument, wrong-import-position
# This program is dedicated to the public domain under the CC0 license.

"""
First, a few callback functions are defined. Then, those functions are passed to
the Application and registered at their respective places.
Then, the bot is started and runs until we press Ctrl-C on the command line.

Usage:
Example of a bot-user conversation using ConversationHandler.
Send /start to initiate the conversation.
Press Ctrl-C on the command line or send a signal to the process to stop the
bot.
"""

import logging

from telegram import __version__ as TG_VER

try:
    from telegram import __version_info__
except ImportError:
    __version_info__ = (0, 0, 0, 0, 0)  # type: ignore[assignment]

if __version_info__ < (20, 0, 0, "alpha", 5):
    raise RuntimeError(
        f"This example is not compatible with your current PTB version {TG_VER}. To view the "
        f"{TG_VER} version of this example, "
        f"visit https://docs.python-telegram-bot.org/en/v{TG_VER}/examples.html"
    )

TOKEN = '517124256:AAE2dHpeO5KGI9c2G9J593JM6X24wb8JVMk'
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

GENDER, PHOTO, LOCATION, BIO = range(4)


from qtpy import QtCore
import ctypes   # is a foreign function library for Python. It provides C
                # compatible data types, and allows calling functions in DLLs
                # or shared libraries. It can be used to wrap these libraries
                # in pure Python.
from qudi.hardware.wavemeter import high_finesse_api
from qudi.interface.wavemeter_interface import WavemeterInterface
from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import Mutex

import numpy as np


class TelegramBot(Base):
    token = ConfigOption(name='token', missing='error')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        """ Initalize the verdieLaser object.
            
            It will grab the first available I/O serial port, as is
            consistent with the PySerial modules.
        """
        # configure the port
        pass
    
    def on_activate(self):
        """Run the bot."""
        # Create the Application and pass it your bot's token.
        self.application = Application.builder().token(TOKEN).build()

        # Add conversation handler with the states GENDER, PHOTO, LOCATION and BIO
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                GENDER: [MessageHandler(filters.Regex("^(Boy|Girl|Other)$"), self.gender)],
                PHOTO: [MessageHandler(filters.PHOTO, self.photo), CommandHandler("skip", skip_photo)],
                LOCATION: [
                    MessageHandler(filters.LOCATION, self.location),
                    CommandHandler("skip", self.skip_location),
                ],
                BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.bio)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )

        self.application.add_handler(conv_handler)

        # Run the bot until the user presses Ctrl-C
        self.application.run_polling()

    def on_deactivate(self):
        """ Deactivate module.
        """
        self.port.close()


    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation and asks the user about their gender."""
        reply_keyboard = [["Boy", "Girl", "Other"]]

        await update.message.reply_text(
            "Hi! My name is Professor Bot. I will hold a conversation with you. "
            "Send /cancel to stop talking to me.\n\n"
            "Are you a boy or a girl?",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="Boy or Girl?"
            ),
        )

        return GENDER


    async def gender(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Stores the selected gender and asks for a photo."""
        user = update.message.from_user
        logger.info("Gender of %s: %s", user.first_name, update.message.text)
        await update.message.reply_text(
            "I see! Please send me a photo of yourself, "
            "so I know what you look like, or send /skip if you don't want to.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return PHOTO


    async def photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Stores the photo and asks for a location."""
        user = update.message.from_user
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_to_drive("user_photo.jpg")
        logger.info("Photo of %s: %s", user.first_name, "user_photo.jpg")
        await update.message.reply_text(
            "Gorgeous! Now, send me your location please, or send /skip if you don't want to."
        )

        return LOCATION


    async def skip_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Skips the photo and asks for a location."""
        user = update.message.from_user
        logger.info("User %s did not send a photo.", user.first_name)
        await update.message.reply_text(
            "I bet you look great! Now, send me your location please, or send /skip."
        )

        return LOCATION


    async def location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Stores the location and asks for some info about the user."""
        user = update.message.from_user
        user_location = update.message.location
        logger.info(
            "Location of %s: %f / %f", user.first_name, user_location.latitude, user_location.longitude
        )
        await update.message.reply_text(
            "Maybe I can visit you sometime! At last, tell me something about yourself."
        )

        return BIO


    async def skip_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Skips the location and asks for info about the user."""
        user = update.message.from_user
        logger.info("User %s did not send a location.", user.first_name)
        await update.message.reply_text(
            "You seem a bit paranoid! At last, tell me something about yourself."
        )

        return BIO


    async def bio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Stores the info about the user and ends the conversation."""
        user = update.message.from_user
        logger.info("Bio of %s: %s", user.first_name, update.message.text)
        await update.message.reply_text("Thank you! I hope we can talk again some day.")

        return ConversationHandler.END


    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels and ends the conversation."""
        user = update.message.from_user
        logger.info("User %s canceled the conversation.", user.first_name)
        await update.message.reply_text(
            "Bye! I hope we can talk again some day.", reply_markup=ReplyKeyboardRemove()
        )

        return ConversationHandler.END
