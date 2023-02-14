from collections import namedtuple
import os
from typing import Dict, List

import discord
from discord import app_commands

from game import Game, GAME_OPTIONS, GameState

MY_GUILD = discord.Object(id=714226545119461469)

class MyClient(discord.Client):
    def __init__(self, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)


intents = discord.Intents.default()
intents.members = True
client = MyClient(intents)




games: Dict[discord.TextChannel, Game] = {}

@client.tree.command()
async def new_game(interaction: discord.Interaction):
    game = Game(channel=interaction.channel)
    games[interaction.channel] = game
    message: str = ''
    if game.state == GameState.NO_GAME:
        game.add_player(interaction.user)
        game.state = GameState.WAITING
        message = f"A new game has been started by {interaction.user.name}!\nMessage /join to join the game."
    else:
        message = "There is already a game in progress,\nyou can't start a new game."
        if game.state == GameState.WAITING:
            message = f"{message}\nIt still hasn't started yet, so you can still message /join to join that game."
        
    await interaction.response.send_message(message)

# Has a user try to join a game about to begin, giving an error if they've
# already joined or the game can't be joined. Returns the list of messages the
# bot should say
@client.tree.command(name='join')
async def join_game(interaction: discord.Interaction):
    game = games.get(interaction.channel)
    message: str = ''
    if game.state == GameState.NO_GAME:
        message = f"No game has been started yet for you to join.\nMessage /newgame to start a new game."
    elif game.state != GameState.WAITING:
        message = f"The game is already in progress, {interaction.user.name}.\nYou're not allowed to join right now."
    elif game.add_player(interaction.user):
        message = f"{interaction.user.name} has joined the game!\nMessage /join to join the game, \nor /start to start the game."
    else:
        message = f"You've already joined the game {interaction.user.name}!"

    await interaction.response.send_message(message)

# Starts a game, so long as one hasn't already started, and there are enough
# players joined to play. Returns the messages the bot should say.
@client.tree.command(name='start')
async def start_game(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    print(game.state)
    if game.state == GameState.NO_GAME:
        message = "Message /newgame if you would like to start a new game."
    elif game.state != GameState.WAITING:
        message = f"The game has already started, {interaction.user.name}.\nIt can't be started twice."
    elif not game.is_player(interaction.user):
        message = f"You are not a part of that game yet, {interaction.user.name}.\nPlease message /join if you are interested in playing."
    elif len(game.players) < 0:
        message = "The game must have at least two players before\nit can be started."
    else:
        message = game.start()

    await interaction.response.send_message(message)

# Deals the hands to the players, saying an error message if the hands have
# already been dealt, or the game hasn't started. Returns the messages the bot
# should say
@client.tree.command(name='deal')
async def deal_hand(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if game.state == GameState.NO_GAME:
        message = f"No game has been started for you to deal.\nMessage /newgame to start one."
    elif game.state == GameState.WAITING:
        message = f"You can't deal because the game hasn't started yet."
    elif game.state != GameState.NO_HANDS:
        message = f"The cards have already been dealt."
    elif game.dealer.user != interaction.user:
        message = f"You aren't the dealer, {interaction.user.name}.\nPlease wait for {game.dealer.user.name} to /deal."
    else:
        message = game.deal_hands()
        await game.tell_hands(client)

    await interaction.response.send_message(message)

# Handles a player calling a bet, giving an appropriate error message if the
# user is not the current player or betting hadn't started. Returns the list of
# messages the bot should say.
@client.tree.command(name='call')
async def call_bet(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if game.state == GameState.NO_GAME:
        message = "No game has been started yet. Message /newgame to start one."
    elif game.state == GameState.WAITING:
        message = "You can't call any bets because the game hasn't started yet."
    elif not game.is_player(interaction.user):
        message = f"You can't call, because you're not playing, {interaction.user.name}."
    elif game.state == GameState.NO_HANDS:
        message = "You can't call any bets because the hands haven't been dealt yet."
    elif game.current_player.user != interaction.user:
        message = f"You can't call {interaction.user.name}, because it's\n{game.current_player.user.name}'s turn."
    else:
        message = game.call()

    await interaction.response.send_message(message)

# Has a player check, giving an error message if the player cannot check.
# Returns the list of messages the bot should say.
@client.tree.command()
async def check(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if game.state == GameState.NO_GAME:
        message = "No game has been started yet. Message /newgame to start one."
    elif game.state == GameState.WAITING:
        message = "You can't check because the game hasn't started yet."
    elif not game.is_player(interaction.user):
        message = f"You can't check, because you're not playing, {interaction.user.name}."
    elif game.state == GameState.NO_HANDS:
        message = "You can't check because the hands haven't been dealt yet."
    elif game.current_player.user != interaction.user:
        message = f"You can't check, {interaction.user.name}, because it's\n{game.current_player.user.name}'s turn."
    elif game.current_player.cur_bet != game.cur_bet:
        message = f"You can't check, {interaction.user.name} because you need to\nput in ${game.cur_bet - game.current_player.cur_bet} to call."
    else:
        message = game.check()

    await interaction.response.send_message(message)

# Has a player raise a bet, giving an error message if they made an invalid
# raise, or if they cannot raise. Returns the list of messages the bot will say
@client.tree.command(name='raise')
async def raise_bet(interaction: discord.Interaction, amount: int):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if game.state == GameState.NO_GAME:
        message = "No game has been started yet. Message /newgame to start one."
    elif game.state == GameState.WAITING:
        message = "You can't raise because the game hasn't started yet."
    elif not game.is_player(interaction.user):
        message = f"You can't raise, because you're not playing, {interaction.user.name}."
    elif game.state == GameState.NO_HANDS:
        message = "You can't raise because the hands haven't been dealt yet."
    elif game.current_player.user != interaction.user:
        message = f"You can't raise, {interaction.user.name}, because it's\n{game.current_player.name}'s turn."

    if game.cur_bet >= game.current_player.max_bet:
        message = f"You don't have enough money to raise the current bet of ${game.cur_bet}."
    elif game.cur_bet + amount > game.current_player.max_bet:
        message = f"You don't have enough money to raise by ${amount}.\nThe most you can raise it by is ${game.current_player.max_bet - game.cur_bet}."
    else: 
        message = game.raise_bet(amount)

    await interaction.response.send_message(message)

# Has a player fold their hand, giving an error message if they cannot fold
# for some reason. Returns the list of messages the bot should say
@client.tree.command(name='fold')
async def fold_hand(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if game.state == GameState.NO_GAME:
        message = "No game has been started yet.\nMessage /newgame to start one."
    elif game.state == GameState.WAITING:
        message = "You can't fold yet because the game hasn't started yet."
    elif not game.is_player(interaction.user):
        message = f"You can't fold, because you're not playing, {interaction.user.name}."
    elif game.state == GameState.NO_HANDS:
        message = "You can't fold yet because the hands haven't been dealt yet."
    elif game.current_player.user != interaction.user:
        message = f"You can't fold {interaction.user.name}, because it's\n{game.current_player.name}'s turn."
    else:
        message = game.fold()

    await interaction.response.send_message(message)

# Returns a list of messages that the bot should say in order to tell the
# players the list of available commands.
@client.tree.command(name='help')
async def show_help(interaction: discord.Interaction):
    message: str = ''
    commands: List[app_commands.AppCommand] = client.tree.get_commands(guild=MY_GUILD)
    longest_command = 12
    for command in commands:
        spacing = ' ' * (longest_command - len(command.name) + 2)
        message = f"{message}{command.name}{spacing}{command.description}\n"
    
    message = f"```{message}```"
    await interaction.response.send_message(message)

# Returns a list of messages that the bot should say in order to tell the
# players the list of settable options.
@client.tree.command(name='options')
async def show_options(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    longest_option = len(max(game.options, key=len))
    longest_value = max([len(str(val)) for key, val in game.options.items()])
    option_lines = []
    for option in GAME_OPTIONS:
        name_spaces = ' ' * (longest_option - len(option) + 2)
        val_spaces = ' ' * (longest_value - len(str(game.options[option])) + 2)
        message = f"{message}{option}{name_spaces}{str(game.options[option])}{val_spaces}{GAME_OPTIONS[option].description}\n"
    
    message = f"```{message}```"
    await interaction.response.send_message(message)

# Sets an option to player-specified value. Says an error message if the player
# tries to set a nonexistent option or if the option is set to an invalid value
# Returns the list of messages the bot should say.
@client.tree.command(name='set')
async def set_option(interaction: discord.Interaction, option: str, value: int):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if option not in GAME_OPTIONS:
        message = f"'{option}' is not an option. Message /options to see\nthe list of options."

    if value < 0:
        message = f"Cannot set {option} to a negative value!"
    else:
        game.options[option] = value
        message = f"The {option} is now set to {value}."

    await interaction.response.send_message(message)

# Returns a list of messages that the bot should say to tell the players of
# the current chip standings.
@client.tree.command(name='count')
async def chip_count(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if game.state in (GameState.NO_GAME, GameState.WAITING):
        message = "You can't request a chip count because the game\nhasn't started yet."
    else:
        message = ''
        for player in game.players:
            message = f"{message}{player.user.name} has ${player.balance}.\n"

    await interaction.response.send_message(message)

# Handles a player going all-in, returning an error message if the player
# cannot go all-in for some reason. Returns the list of messages for the bot
# to say.
@client.tree.command()
async def all_in(interaction: discord.Interaction):
    game: Game = games.get(interaction.channel)
    message: str = ''
    if game.state == GameState.NO_GAME:
        message = "No game has been started yet. Message /newgame to start one."
    elif game.state == GameState.WAITING:
        message = "You can't go all in because the game hasn't started yet."
    elif not game.is_player(interaction.user):
        message = f"You can't go all in, because you're not playing, {interaction.user.name}."
    elif game.state == GameState.NO_HANDS:
        message = "You can't go all in because the hands haven't been dealt yet."
    elif game.current_player.user != interaction.user:
        message = f"You can't go all in, {interaction.user.name}, because\nit's {game.current_player.user.name}'s turn."
    else:
        message = game.all_in()

    await interaction.response.send_message(message)


@client.event
async def on_ready():
    print("Poker bot ready!")
    print(f"Logged in as {client.user.name} ({client.user.id})")


client.run(os.getenv("BOT_TOKEN"))
