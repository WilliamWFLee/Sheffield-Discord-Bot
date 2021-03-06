#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Cog for organising polls

Author: William Lee
"""

import asyncio
import datetime
import re
import time
import traceback

import discord
from discord.ext import commands, tasks

import database as db
import utils as ut

# Regex from extracting time from format 00h00m00s
DURATION_REGEX = re.compile(
    r"((?P<days>\d+?)d)?((?P<hours>\d+?)h)?"
    r"((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?")


class PollsCog(commands.Cog, name="Polls"):
    """Class for polls cog"""

    def __init__(self, bot):
        """Save our bot argument that is passed in to the class."""
        self.bot = bot
        self.poll_daemon.start()

    async def parse_time_as_delta(self, time: str):
        """
        Uses a regex to extract a duration in the format 00h00m00s
        to a `datetime.timedelta`
        """

        # Duration string is converted to lowercase
        # so 10h30m5 is equivalent to 10H30M5S
        match = DURATION_REGEX.match(time.lower())
        if match:
            values_dict = match.groupdict()
            for key in values_dict:
                # If no value for a time unit is found
                # then it is assumed to be 0
                if values_dict[key] is None:
                    values_dict[key] = 0
                values_dict[key] = int(values_dict[key])

            return datetime.timedelta(**values_dict)

    async def check_add_new_choice(self, poll, message, response):
        # Checks an edited message against a given message
        def get_message_edit_check(message):
            def check(_, m):
                return m.id == message.id

            return check

        # Splits the message into emoji and text
        values = response.content.split(maxsplit=1)

        error_msg = None

        # Expect split be into 2 parts exactly
        if len(values) != 2:
            error_msg = "New choice wasn't given in the correct format."

        if error_msg is None:
            reaction, text = values
            if reaction in ('➕', '✖️', '🛑'):
                error_msg = f"You can't use {reaction} as a choice."
            elif await db.get_poll_choice(poll['ID'], reaction):
                error_msg = f"Choice already exists for {reaction}."
            else:
                try:
                    await message.add_reaction(reaction)
                except discord.errors.HTTPException:
                    error_msg = f"'{reaction}' is an unknown emoji."

        if error_msg is not None:
            error_prompt = await message.channel.send(
                f"{error_msg} You may edit your original message.")

            check = get_message_edit_check(response)

            try:
                _, new_response = await self.bot.wait_for(
                    'message_edit', check=check, timeout=30.0)
            except asyncio.TimeoutError:
                await response.delete()
                await error_prompt.delete()
            else:
                await error_prompt.delete()
                await self.check_add_new_choice(poll, message, new_response)
        else:
            await response.delete()
            await db.add_poll_choice(int(poll['ID']), reaction, text)

    async def get_new_choice_from_user(self, poll, message, user):

        # Checks that the author of the message
        # is the one that wants to add a new choice
        def author_check(m):
            return m.author == user

        prompt_msg = await message.channel.send(
            "Send a message for the choice in the format `<emoji> <text>`, "
            "e.g. :heart: Red Heart")

        try:
            response = await self.bot.wait_for('message', check=author_check,
                                               timeout=30.0)
        except asyncio.TimeoutError:
            pass
        else:
            await self.check_add_new_choice(poll, message, response)
        finally:
            await prompt_msg.delete()

    async def user_delete_poll(self, poll, message, user):
        poll_creator_id = poll['creator']
        current_user_id = int(await db.get_user_id(user.id))

        # Only the creator of the poll or admins can delete it
        if (poll_creator_id != current_user_id
                and not await ut.is_admin(user)):
            return

        # Awaits confirmation of the deletion
        result, reason = await ut.get_confirmation(
            message.channel, user, self.bot,
            "Are you sure you want to delete the poll? "
            "All responses and choices will be deleted")

        if result:
            # The message containing the poll is deleted
            await message.delete()
            # Poll is also ended
            await self.end_poll(poll)

        return result

    async def toggle_poll_response(self, poll, user_id, reaction, message):

        has_response = await db.user_has_response(
            user_id, poll['ID'], reaction)

        if has_response is None:
            return

        if has_response:
            result, reason = await db.user_remove_response(
                user_id, poll['ID'], reaction)
        else:
            result, reason = await db.user_add_response(
                user_id, poll['ID'], reaction)

        return result

    async def end_poll(self, poll):
        poll_id = int(poll['ID'])
        channel = self.bot.get_channel(int(poll['channelID']))

        await db.end_poll(poll_id)

        # If the message has been deleted
        try:
            message = await channel.fetch_message(int(poll['messageID']))
        except discord.errors.NotFound:
            return

        # Removes all reactions but the delete poll reaction
        for reaction in message.reactions:
            if str(reaction.emoji) == '✖️':
                continue
            await message.remove_reaction(reaction.emoji, self.bot.user)

        embed = message.embeds[0]
        embed.description = ("Poll has now ended\n"
                             "React with ✖️ to delete the poll")

        await message.edit(embed=embed)

    async def user_end_poll(self, poll, message, user):
        poll_creator_id = poll['creator']
        current_user_id = int(await db.get_user_id(user.id))

        # Only the creator of the poll can end the poll
        if (poll_creator_id != current_user_id
                and not await ut.is_admin(user)):
            return

        result, reason = await ut.get_confirmation(
            message.channel, user, self.bot,
            "Are you sure you want to end the poll now?")

        # Brings forward the end date for the poll to current time
        #
        # The poll will end the poll on its next iteration
        if result:
            await db.change_poll_end_date(
                poll['ID'], int((await ut.get_utc_time()).timestamp()))

    async def update_response_counts(self, poll):

        def key(choice):
            try:
                # Returns the index of the choice's emoji
                # in the list of emojis in the message reactions
                return emojis.index(choice['reaction'])
            except ValueError:
                # If emoji isn't found, then return the length
                # of the choices list
                #
                # This guarantees that the choice are displayed at the end
                # of the list (along with the others that are not found)
                return len(choices)

        channel = self.bot.get_channel(int(poll['channelID']))

        # If the message is deleted, then ignore and return
        try:
            message = await channel.fetch_message(int(poll['messageID']))
        except discord.errors.NotFound:
            return

        choices = await db.get_poll_choices(poll['ID'])

        # Choices are sorted in the order of appearance
        # of the emoji in the message - also the order in
        # which they are added
        emojis = [reaction.emoji for reaction in message.reactions]
        choices.sort(key=key)

        embed = message.embeds[0]
        embed.clear_fields()

        user_limit = 3

        for choice in choices:
            reaction = choice['reaction']

            users = await db.get_discord_user_ids_for_choice(choice['ID'])
            count = len(users)

            users = ', '.join([
                f"<@{int(user['discordID'])}>" for user in users[:user_limit]])
            if count > user_limit:
                users += f" and {count-user_limit} more"

            field_value = choice['text'] + (f" - {users}" if users else "")

            embed.add_field(name=f"{reaction} {count}",
                            value=field_value, inline=False)

        # Indicates that results are being updated
        footer_text = (await ut.get_uk_time()).strftime(
            "Results last updated: %d/%m/%Y %H:%M:%S %Z\n"
            f"Poll ID: {int(poll['ID'])}")
        embed.set_footer(text=footer_text)

        # Again, if the message is deleted
        try:
            await message.edit(embed=embed)
        except discord.errors.NotFound:
            return

    @tasks.loop(seconds=1.0)
    async def poll_daemon(self):
        """
        Task loop that update response counts
        and ends polls that need to be ended
        """

        # try-except can be replaced with a coroutine
        # wrapped with discord.ext.tasks.Loop.error on release of 1.4
        try:
            ongoing_polls = await db.get_all_ongoing_polls()
            for poll in ongoing_polls:
                end_date = poll['endDate']
                if (await ut.get_utc_time()).timestamp() >= end_date:
                    await self.end_poll(poll)

                await self.update_response_counts(poll)
        except Exception:
            traceback.print_exc()

    @poll_daemon.before_loop
    async def before_poll_daemon_start(self):
        # Waits until the bot is ready
        # before starting the task loop
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """
        Listens for reactions to poll messages
        """

        # Ignores if any bots reacts
        emoji = payload.emoji
        if payload.member.bot:
            return

        # Ignores react if the message doesn't correspond to a poll
        message_id = payload.message_id
        poll = await db.get_poll_by_message_id(message_id)
        if not poll:
            return

        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(message_id)
        user = payload.member

        if emoji.name == '✖️':
            deleted = await self.user_delete_poll(poll, message, user)
            if not deleted:
                await message.remove_reaction(emoji, user)
            return

        # New responses after the poll has ended are not accepted
        end_date = int(poll['endDate'])
        if (await ut.get_utc_time()).timestamp() >= end_date or poll['ended']:
            await message.remove_reaction(emoji, user)
            return

        if emoji.name == '➕':
            await self.get_new_choice_from_user(poll, message, user)
        elif emoji.name == '🛑':
            await self.user_end_poll(poll, message, user)
        else:
            await self.toggle_poll_response(poll, user.id, str(emoji), message)

        await message.remove_reaction(emoji, user)

    @commands.command(
        name="createpoll",
        help="Creates a poll. You can add choices to it later")
    @commands.has_role("Member")
    async def create_poll(self, ctx, duration, *, title):
        """
        Allows a user to create a poll.
        """

        duration = await self.parse_time_as_delta(duration)

        if not duration:
            await ctx.send("Poll must have a valid duration "
                           "that is greater than zero")
            return

        end_date = await ut.get_utc_time() + duration
        description = (await ut.get_uk_time(end_date)).strftime(
            "Poll ends: %d/%m/%Y %H:%M:%S %Z\n"
            "React with ➕ to add a choice\n"
            "React with ✖️ to delete the poll\n"
            "React with 🛑 to end the poll, and finalise the results\n"
            "React with the emojis shown below to vote for that option")
        embed = discord.Embed(title=title, description=description,
                              color=0x009fe3)
        message = await ctx.send(embed=embed)

        # Adds control emojis
        await message.add_reaction('➕')
        await message.add_reaction('✖️')
        await message.add_reaction('🛑')

        # Deletes the original command message
        await ctx.message.delete()

        await db.user_create_poll(
            ctx.author.id, message.id, message.channel.id,
            ctx.guild.id, title, int(end_date.timestamp()))

    @commands.command(
        name="summonpoll",
        help="Moves an existing poll to the bottom of the channel")
    async def summon_poll(self, ctx, poll_id: int):
        """
        Allows a user to bring forward a poll in the conversation,
        for the benefit of longer-duration polls
        """

        poll = await db.get_poll_by_id(poll_id)
        if not poll:
            await ctx.send(f"Poll with ID {poll_id} could not found.")
            return

        old_message = await ctx.fetch_message(int(poll['messageID']))
        embed = old_message.embeds[0]
        reactions = old_message.reactions

        await old_message.delete()

        new_message = await ctx.send(embed=embed)
        for reaction in reactions:
            await new_message.add_reaction(reaction.emoji)

        await ctx.message.delete()

        await db.update_poll_message_id(poll_id, new_message.id)


def setup(bot):
    """
    Add the cog we have made to our bot.

    This function is necessary for every cog file, multiple classes in the
    same file all need adding and each file must have their own setup function.
    """
    bot.add_cog(PollsCog(bot))
