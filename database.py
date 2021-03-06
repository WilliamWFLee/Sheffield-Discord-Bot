#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Class to handle all database connections."""

import os
import mysql.connector as sql
from time import time

import utils as ut

# Load env if we're just running this file.
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
SQL_USER = os.getenv("SQL_USER")
SQL_PASS = os.getenv("SQL_PASS")
SQL_DB = os.getenv("SQL_DB")

if SQL_USER is None or SQL_PASS is None or SQL_DB is None:
    raise Exception("Cannot find required database login information")


class Database:

    def __enter__(self, *args, **kwargs):
        # Connect to the database

        self.db_config = {
            'host': '209.97.130.228',
            'port': 3306,
            'database': SQL_DB,
            'user': SQL_USER,
            'password': SQL_PASS,
            'charset': 'utf8',
            'use_unicode': True,
            'get_warnings': True,
            'autocommit': True,
            'raise_on_warnings': False
        }

        self.connection = sql.Connect(**self.db_config)

        self.cursor = self.connection.cursor(dictionary=True)

        return self

    def __exit__(self, exception_type, value, traceback):
        self.connection.close()


async def create_tables():
    with Database() as db:
        query_list = (
            """
            CREATE TABLE IF NOT EXISTS
            USERS (
                ID INT NOT NULL AUTO_INCREMENT,
                name VARCHAR(255) NOT NULL,
                discordID VARCHAR(255) UNIQUE NOT NULL,
                jamming INT,
                PRIMARY KEY (ID)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            JAM_TEAM (
                ID INT NOT NULL AUTO_INCREMENT,
                teamName VARCHAR(255) NOT NULL UNIQUE,
                gitLink VARCHAR(255) NOT NULL UNIQUE,
                PRIMARY KEY (ID)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            JAM_TEAM_MEMBER (
                ID INT NOT NULL AUTO_INCREMENT,
                teamID INT NOT NULL,
                userID INT NOT NULL UNIQUE,
                creator INT NOT NULL DEFAULT 0,
                PRIMARY KEY (ID)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            EVENTS (
                ID INT PRIMARY KEY AUTO_INCREMENT,
                title VARCHAR(255) NOT NULL,
                description VARCHAR(1024) NOT NULL,
                date DATETIME NOT NULL,
                creator INT NOT NULL,
                FOREIGN KEY (creator)
                    REFERENCES USERS(ID)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            GUILDS (
                ID INT PRIMARY KEY AUTO_INCREMENT,
                guildID VARCHAR(255) NOT NULL UNIQUE,
                registeringID VARCHAR(255) UNIQUE,
                memberID VARCHAR(255) UNIQUE,
                welcomeMessageID VARCHAR(255) UNIQUE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            CHANNELS (
                ID INT PRIMARY KEY AUTO_INCREMENT,
                channelID VARCHAR(255) NOT NULL UNIQUE,
                voice INT NOT NULL,
                owner INT NOT NULL UNIQUE,
                createdDate INT NOT NULL,

                FOREIGN KEY (owner)
                    REFERENCES USERS(ID)
            )""",
            """
            CREATE TABLE IF NOT EXISTS
            POLLS (
                ID INT PRIMARY KEY AUTO_INCREMENT,
                messageID VARCHAR(255) NOT NULL,
                channelID VARCHAR(255) NOT NULL,
                guild INT NOT NULL,
                creator INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                endDate INT NOT NULL,
                ended BOOLEAN NOT NULL DEFAULT FALSE,

                FOREIGN KEY(creator)
                    REFERENCES USERS(ID),
                FOREIGN KEY(guild)
                    REFERENCES GUILDS(ID)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            POLL_CHOICES (
                ID INT PRIMARY KEY AUTO_INCREMENT,
                poll INT NOT NULL,
                reaction VARCHAR(255) NOT NULL,
                text VARCHAR(255) NOT NULL,

                UNIQUE KEY (poll, reaction),
                FOREIGN KEY (poll)
                    REFERENCES POLLS(ID)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            POLL_RESPONSES (
                ID INT PRIMARY KEY AUTO_INCREMENT,
                user INT NOT NULL,
                choice INT NOT NULL,

                UNIQUE KEY (user, choice),
                FOREIGN KEY (user)
                    REFERENCES USERS(ID),
                FOREIGN KEY (choice)
                    REFERENCES POLL_CHOICES(ID)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS
            MESSAGE_LOG (
                ID INT PRIMARY KEY AUTO_INCREMENT,
                authorID INT NOT NULL,
                messageID VARCHAR(255) NOT NULL,
                content VARCHAR(4096),
                dateSent INT NOT NULL,
                FOREIGN KEY (authorID)
                    REFERENCES USERS(ID)
            )
            """
        )

        for query in query_list:
            try:
                db.cursor.execute(query)
            except sql.errors.ProgrammingError:
                ut.log_error(f"Query \n'{query}'\n raised an error, ensure that the "
                             "syntax is correct.")


async def add_user(discord_id, bot, name):
    with Database() as db:
        if bot:
            return
        try:
            db.cursor.execute(f"""
                INSERT INTO USERS (
                    name, discordID
                )
                VALUES (
                    %s,
                    %s
                )
            """, (name, discord_id))

            db.connection.commit()
            return db.cursor.lastrowid
        except sql.errors.IntegrityError:
            return False


async def get_user_id(discord_id):
    with Database() as db:
        db.cursor.execute(f"""
            SELECT ID FROM USERS
            WHERE discordID = %s
        """, (discord_id, ))

        result = db.cursor.fetchone()
        if result:
            return result['ID']

        result = await add_user(discord_id, False, "Unknown")
        return result


async def add_guild(guild_id, registering_id, member_id):
    with Database() as db:
        try:
            db.cursor.execute(f"""
                INSERT INTO GUILDS (
                    guildID, registeringID, memberID
                )
                VALUES (
                    %s,
                    %s,
                    %s
                )
            """, (guild_id, registering_id, member_id))

            db.connection.commit()
        except sql.errors.IntegrityError:
            pass


async def get_guild_info(guild_id, field="*"):
    # We use string formatting for field since it is only created internally
    # and if we used the same method as guild_id, it would be escaped.
    with Database() as db:
        db.cursor.execute(f"""
            SELECT {field} FROM GUILDS
            WHERE guildID = %s
        """, (guild_id,))

        result = db.cursor.fetchone()

        if field != "*" and result[field]:
            return int(result[field])
        if result:
            return result
        return False


async def set_guild_info(guild_id, field, new_value):
    # We use string formatting for field since it is only created internally
    # and if we used the same method as guild_id, it would be escaped.
    with Database() as db:
        try:
            db.cursor.execute(f"""
                UPDATE GUILDS
                SET {field} = %s
                WHERE guildID = %s
            """, (new_value, guild_id))

            db.connection.commit()
        except sql.errors.IntegrityError:
            return False


async def set_jamming(user_id, new_value):
    with Database() as db:
        db.cursor.execute(f"""
            UPDATE USERS
            SET jamming = %s
            WHERE discordID = %s
        """, (new_value, user_id))

        db.connection.commit()
        return True


async def get_user_jam_team(discord_id):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        db.cursor.execute(f"""
            SELECT teamID FROM JAM_TEAM_MEMBER
            WHERE userID = %s
        """, (user_id,))

        result = db.cursor.fetchone()

        if result:
            return result['teamID']
        return False


async def add_user_jam_team(user_id, jam_team, creator="0"):
    with Database() as db:
        try:
            db.cursor.execute(f"""
                INSERT INTO JAM_TEAM_MEMBER
                (teamID, userID, creator)
                VALUES
                (%s, %s, %s)
            """, (jam_team, user_id, creator))

            db.connection.commit()
            return True
        except sql.errors.IntegrityError:
            return False


async def create_jam_team(discord_id, team_name, git_link):
    jam_team_id = await get_user_jam_team(discord_id)
    if jam_team_id:
        return False, "User is already a member of a team."
    with Database() as db:
        try:
            db.cursor.execute(f"""
                INSERT INTO JAM_TEAM
                (teamName, gitLink)
                VALUES
                (%s, %s)
            """, (team_name, git_link))

            jam_team = db.cursor.lastrowid
            user_id = await get_user_id(discord_id)
            await add_user_jam_team(user_id, jam_team, creator="1")
            db.connection.commit()
        except sql.errors.IntegrityError:
            return False, "Team name or git link already in use."


async def user_create_channel(discord_id, channel_id, is_voice):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        try:
            db.cursor.execute(f"""
                INSERT INTO CHANNELS
                (channelID, voice, owner, createdDate)
                VALUES
                (%s, %s, %s, %s)
            """, (channel_id, is_voice, user_id, int(time())))
            db.connection.commit()
        except sql.errors.IntegrityError:
            return False, "UNIQUE constraint failed..."


async def user_delete_channel(discord_id):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        try:
            db.cursor.execute(f"""
                DELETE FROM CHANNELS
                WHERE owner = %s
            """, (user_id,))
            db.connection.commit()
        except sql.errors.IntegrityError:
            return False, "UNIQUE constraint failed..."


async def user_has_channel(discord_id):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        db.cursor.execute(f"""
            SELECT channelID FROM CHANNELS
            WHERE owner = %s
        """, (user_id,))

        result = db.cursor.fetchone()
        if result:
            return result['channelID']
        return False


async def get_poll_by_id(poll_id, field="*"):
    with Database() as db:
        db.cursor.execute(f"""
            SELECT {field} FROM POLLS
            WHERE ID = %s
        """, (poll_id, ))

        return db.cursor.fetchone()


async def get_poll_by_message_id(message_id, field="*"):
    with Database() as db:
        db.cursor.execute(f"""
            SELECT {field} FROM POLLS
            WHERE messageID = %s
        """, (message_id, ))

        return db.cursor.fetchone()


async def user_create_poll(discord_id, message_id, channel_id,
                           discord_guild_id, poll_title, end_date: int):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        guild_id = await get_guild_info(discord_guild_id, field="ID")
        try:
            db.cursor.execute("""
                INSERT INTO POLLS
                (creator, messageID, channelID, guild, title, endDate)
                VALUES
                (%s, %s, %s, %s, %s, %s)
            """, (user_id, message_id, channel_id,
                  guild_id, poll_title, end_date))
            db.connection.commit()
        except sql.errors.IntegrityError:
            return False, "UNIQUE constraint failed"


async def update_poll_message_id(poll_id, message_id):
    with Database() as db:
        try:
            db.cursor.execute("""
                UPDATE POLLS SET messageID = %s
                WHERE ID = %s
            """, (message_id, poll_id))
            db.connection.commit()
        except sql.errors.IntegrityError:
            return False, "Integrity error"


async def get_all_ongoing_polls(field="*"):
    with Database() as db:
        db.cursor.execute(f"""
            SELECT {field} FROM POLLS
            WHERE ended = FALSE
        """)

        return db.cursor.fetchall()


async def change_poll_end_date(poll_id, end_date):
    with Database() as db:
        db.cursor.execute("""
            UPDATE POLLS SET endDate = %s
            WHERE ID = %s
        """, (end_date, poll_id))


async def end_poll(poll_id):
    with Database() as db:
        db.cursor.execute("""
            UPDATE POLLS SET ended = TRUE
            WHERE ID = %s
        """, (poll_id, ))

        return db.cursor.rowcount > 0


async def delete_poll(poll_id):
    with Database() as db:
        db.cursor.execute("""
            DELETE FROM POLLS
            WHERE ID = %s
        """, (poll_id, ))
        db.connection.commit()


async def get_poll_choice(poll_id, reaction, field="*"):
    with Database() as db:
        db.cursor.execute(f"""
            SELECT {field} FROM POLL_CHOICES
            WHERE poll = %s AND reaction = %s
        """, (poll_id, reaction.encode('unicode-escape')))

        result = db.cursor.fetchone()
        if result:
            for key in result:
                if key in ('reaction', 'text'):
                    result[key] = result[key].decode('unicode-escape')
        
        return result


async def add_poll_choice(poll_id, reaction, text):
    with Database() as db:
        try:
            db.cursor.execute("""
                INSERT INTO POLL_CHOICES
                (poll, reaction, text)
                VALUES
                (%s, %s, %s)
            """, (poll_id, reaction.encode('unicode-escape'), 
                  text.encode('unicode-escape')))
        except sql.errors.IntegrityError:
            return False, "UNIQUE constraint failed"


async def user_has_response(discord_id, poll_id, reaction):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        choice = await get_poll_choice(poll_id, reaction, field="ID")
        if choice is None:
            return

        choice_id = choice['ID']
        
        db.cursor.execute("""
            SELECT ID FROM POLL_RESPONSES
            WHERE POLL_RESPONSES.user = %s AND POLL_RESPONSES.choice = %s
        """, (user_id, choice_id))

        return db.cursor.fetchone() is not None


async def user_add_response(discord_id, poll_id, reaction):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        choice = await get_poll_choice(poll_id, reaction, field="ID")
        choice_id = choice['ID']
        try:
            db.cursor.execute("""
                INSERT INTO POLL_RESPONSES
                (choice, user)
                VALUES
                (%s, %s)
            """, (choice_id, user_id))
            return True, None
        except sql.errors.IntegrityError:
            return False, "UNIQUE constraint failed"


async def user_remove_response(discord_id, poll_id, reaction):
    with Database() as db:
        user_id = await get_user_id(discord_id)
        choice = await get_poll_choice(poll_id, reaction, field="ID")
        choice_id = choice['ID']

        db.cursor.execute("""
            DELETE FROM POLL_RESPONSES
            WHERE choice = %s AND user = %s
        """, (choice_id, user_id))

        if db.cursor.rowcount > 0:
            return True, None
        return False, "Response did not exist"


async def get_poll_choices(poll_id):
    with Database() as db:
        db.cursor.execute("""
            SELECT ID, reaction, text
            FROM POLL_CHOICES
            WHERE POLL_CHOICES.poll = %s
        """, (poll_id, ))

        results = db.cursor.fetchall()
        if results:
            for result in results:
                for k in result:
                    if k in ('reaction', 'text'):
                        result[k] = result[k].decode('unicode-escape')

        return results


async def get_discord_user_ids_for_choice(choice_id):
    with Database() as db:
        db.cursor.execute("""
            SELECT USERS.discordID
            FROM USERS, POLL_RESPONSES
            WHERE USERS.ID = POLL_RESPONSES.user AND POLL_RESPONSES.choice = %s 
        """, (choice_id, ))

        return db.cursor.fetchall()


async def log_message(discord_id, message_id, message, date_sent):
    with Database() as db:
        try:
            user_id = await get_user_id(discord_id)
            db.cursor.execute(f"""
                INSERT INTO MESSAGE_LOG
                (authorID, messageID, content, dateSent)
                VALUES
                (%s, %s, %s, %s)
            """, (user_id, message_id, message, date_sent))

            db.connection.commit()
            return True
        except sql.errors.IntegrityError:
            return False


async def test_function():
    print(await user_has_channel(247428233086238720))


if __name__ == "__main__":
    import asyncio

    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_function())
    loop.close()
