from PIL import Image
from io import BytesIO
from collections import namedtuple
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List

import discord

from player import Player
from poker import best_possible_hand, Card, Deck
from pot import PotManager

Option = namedtuple("Option", ["description", "default"])

GAME_OPTIONS: Dict[str, Option] = {
    "blind":  Option("The current price of the small blind", 5),
    "buy-in": Option("The amount of money all players start out with", 500),
    "raise-delay": Option("The number of minutes before blinds double",  30),
    "starting-blind": Option("The starting price of the small blind", 5)
}
    


# An enumeration that says what stage of the game we've reached
class GameState(Enum):
    # Game hasn't started yet
    NO_GAME = 1
    # A game has started, and we're waiting for players to join
    WAITING = 2
    # Everyone's joined, we're waiting for the hands to be dealt
    NO_HANDS = 3
    # We've dealt hands to everyone, they're making their bets
    HANDS_DEALT = 4
    # We've just dealt the flop
    FLOP_DEALT = 5
    # We just dealt the turn
    TURN_DEALT = 6
    # We just dealt the river
    RIVER_DEALT = 7

# A class that keeps track of all the information having to do with a game
class Game:
    def __init__(self, *, channel: discord.TextChannel):
        self.new_game(channel)
        # Set the game options to the defaults
        self.options = {key: value.default
                        for key, value in GAME_OPTIONS.items()}

    def new_game(self, channel: discord.TextChannel) -> None:
        self.state = GameState.NO_GAME
        # The players participating in the game
        self.players: List[Player] = []
        # The players participating in the current hand
        self.in_hand: List[Player] = []
        # The index of the current dealer
        self.dealer_index = 0
        # The index of the first person to bet in the post-flop rounds
        self.first_bettor = 0
        # The deck that we're dealing from
        self.cur_deck: Deck = None
        # The five cards shared by all players
        self.shared_cards: List[Card] = []
        # Used to keep track of the current value of the pot, and who's in it
        self.pot = PotManager()
        # The index of the player in in_hand whose turn it is
        self.turn_index = -1
        # The last time that the blinds were automatically raised
        self.last_raise: datetime = None
        self.channel = channel
        print(f'created game in {self.channel}')

    # Adds a new player to the game, returning if they weren't already playing
    def add_player(self, user: discord.User) -> bool:
        if self.is_player(user):
            return False
        self.players.append(Player(user))
        return True

    # Returns whether a user is playing in the game
    def is_player(self, user: discord.User) -> bool:
        for player in self.players:
            if player.user == user:
                return True
        return False

    # Removes a player from being able to bet, if they folded or went all in
    def leave_hand(self, to_remove: Player) -> None:
        for i, player in enumerate(self.in_hand):
            if player == to_remove:
                index = i
                break
        else:
            # The player who we're removing isn't in the hand, so just
            # return
            return

        self.in_hand.pop(index)

        # Adjust the index of the first person to bet and the index of the
        # current player, depending on the index of the player who just folded
        if index < self.first_bettor:
            self.first_bettor -= 1
        if self.first_bettor >= len(self.in_hand):
            self.first_bettor = 0
        if self.turn_index >= len(self.in_hand):
            self.turn_index = 0

    # Returns some messages to update the players on the state of the game
    def status_between_rounds(self) -> str:
        message: str = ''
        for player in self.players:
            message = f"{message}{player.user.name} has ${player.balance}.\n"
        message = f"{message}{self.dealer.user.name} is the current dealer. \nMessage /deal to deal when you're ready."
        return message

    # Moves on to the next dealer
    def next_dealer(self) -> None:
        self.dealer_index = (self.dealer_index + 1) % len(self.players)

    # Returns the current dealer
    @property
    def dealer(self) -> Player:
        return self.players[self.dealer_index]

    @property
    def cur_bet(self) -> int:
        return self.pot.cur_bet

    # Returns the player who is next to move
    @property
    def current_player(self) -> Player:
        return self.in_hand[self.turn_index]

    # Starts a new game, returning the messages to tell the channel
    def start(self) -> str:
        self.state = GameState.NO_HANDS
        self.dealer_index = 0
        for player in self.players:
            player.balance = self.options["buy-in"]
        # Reset the blind to be the starting blind value
        self.options["blind"] = self.options["starting-blind"]
        return f"The game has begunf\n{self.status_between_rounds()}"

    # Starts a new round of Hold'em, dealing two cards to each player, and
    # return the messages to tell the channel
    def deal_hands(self) -> str:
        # Shuffles a new deck of cards
        self.cur_deck = Deck()

        # Start out the shared cards as being empty
        self.shared_cards = []

        # Deals hands to each player, setting their initial bets to zero and
        # adding them as being in on the hand
        self.in_hand = []
        for player in self.players:
            player.cards = (self.cur_deck.draw(), self.cur_deck.draw())
            player.cur_bet = 0
            player.placed_bet = False
            self.in_hand.append(player)

        self.state = GameState.HANDS_DEALT
        message = "The hands have been dealt!"

        # Reset the pot for the new hand
        self.pot.new_hand(self.players)

        if self.options["blind"] > 0:
            message = f"{message}\n{self.pay_blinds()}"

        self.turn_index -= 1

        message = f"{message}\n{self.next_turn()}"
        return message

    # Makes the blinds players pay up with their initial bets
    def pay_blinds(self) -> str:
        message: str = ''

        # See if we need to raise the blinds or not
        raise_delay = self.options["raise-delay"]
        if raise_delay == 0:
            # If the raise delay is set to zero, consider it as being turned
            # off, and do nothing for blinds raises
            self.last_raise = None
        elif self.last_raise is None:
            # Start the timer, if it hasn't been started yet
            self.last_raise = datetime.now()
        elif datetime.now() - self.last_raise > timedelta(minutes=raise_delay):
            message = f"**Blinds are being doubled this round!**"
            self.options["blind"] *= 2
            self.last_raise = datetime.now()

        blind = self.options["blind"]

        # Figure out the players that need to pay the blinds
        if len(self.players) > 2:
            small_player = self.players[(self.dealer_index + 1) % len(self.in_hand)]
            big_player = self.players[(self.dealer_index + 2) % len(self.in_hand)]
            # The first player to bet pre-flop is the player to the left of the big blind
            self.turn_index = (self.dealer_index + 3) % len(self.in_hand)
            # The first player to bet post-flop is the first player to the left of the dealer
            self.first_bettor = (self.dealer_index + 1) % len(self.players)
        else:
            # In heads-up games, who plays the blinds is different, with the
            # dealer playing the small blind and the other player paying the big
            small_player = self.players[self.dealer_index]
            big_player = self.players[self.dealer_index - 1]
            # Dealer goes first pre-flop, the other player goes first afterwards
            self.turn_index = self.dealer_index
            self.first_bettor = self.dealer_index - 1

        message = f"{message}\n{small_player.name} has paid the small blind of ${blind}."

        if self.pot.pay_blind(small_player, blind):
            message = f"{message}\n{small_player.name} is all in!"
            self.leave_hand(small_player)

        message = f"{message}\n{big_player.name} has paid the big blind of ${blind * 2}."
        if self.pot.pay_blind(big_player, blind * 2):
            message = f"{message}\n{big_player.name} is all in!"
            self.leave_hand(big_player)

        return message

    # Returns messages telling the current player their options
    def cur_options(self) -> str:
        message = f"It is {self.current_player.name}'s turn.\n{self.current_player.user.name} currently has ${self.current_player.balance}.\nThe pot is currently ${self.pot.value}."
        if self.pot.cur_bet > 0:
            message = f"{message}\nThe current bet to meet is ${self.cur_bet}\nand {self.current_player.name} has ${self.current_player.cur_bet}."
        else:
            message = f"{message}\nThe current bet to meet is ${self.cur_bet}."
        if self.current_player.cur_bet == self.cur_bet:
            message = f"{message}\nMessage /check, /raise or /fold."
        elif self.current_player.max_bet > self.cur_bet:
            message = f"{message}\nMessage /call, /raise or /fold."
        else:
            message = f"{message}\nMessage /all-in or /fold."
        return message

    # Advances to the next round of betting (or to the showdown), returning a
    # list messages to tell the players
    def next_round(self) -> str:
        message: str = ''
        if self.state == GameState.HANDS_DEALT:
            message = "Dealing the flop:"
            self.shared_cards.append(self.cur_deck.draw())
            self.shared_cards.append(self.cur_deck.draw())
            self.shared_cards.append(self.cur_deck.draw())
            self.state = GameState.FLOP_DEALT
        elif self.state == GameState.FLOP_DEALT:
            message = "Dealing the turn:"
            self.shared_cards.append(self.cur_deck.draw())
            self.state = GameState.TURN_DEALT
        elif self.state == GameState.TURN_DEALT:
            message = "Dealing the river:"
            self.shared_cards.append(self.cur_deck.draw())
            self.state = GameState.RIVER_DEALT
        elif self.state == GameState.RIVER_DEALT:
            return self.showdown()
        message = f"{message}\n{'  '.join(str(card) for card in self.shared_cards)}"
        self.pot.next_round()
        self.turn_index = self.first_bettor
        message = f"{message}\n{self.cur_options()}"
        return message

    # Finish a player's turn, advancing to either the next player who needs to
    # bet, the next round of betting, or to the showdown
    def next_turn(self) -> str:
        message: str
        if self.pot.round_over():
            if self.pot.betting_over():
                return self.showdown()
            else:
                return self.next_round()
        else:
            self.turn_index = (self.turn_index + 1) % len(self.in_hand)
            return self.cur_options()

    
    def showdown(self) -> str:
        while len(self.shared_cards) < 5:
            self.shared_cards.append(self.cur_deck.draw())

        message = "We have reached the end of betting.\nAll cards will be revealed."
        #Open card images
        cardnames = []
        for x in range(5):
            print('debug: card processing...')
            cardnames.append('card/' + str(self.shared_cards[x]) + '.png')
            print(cardnames[x])
        images = [Image.open(x) for x in cardnames]
        print(images)
        widths, heights = zip(*(i.size for i in images))
        total_width = sum(widths)
        max_height = max(heights)
        #Create new image to send
        new_im = Image.new('RGB', (total_width, max_height))
        x_offset = 0
        for im in images:
          new_im.paste(im, (x_offset,0))
          x_offset += im.size[0]
        bytes = BytesIO()
        new_im.save(bytes, format="PNG")
        bytes.seek(0)
        print(new_im)
        async def announce(self):
            print('sending')
            await self.channel.send(file = discord.File(bytes, filename='new_im.png'))

        for player in self.pot.in_pot():
            message = f"{message}\n{player.name}'s hand:\n{player.cards[0]}  {player.cards[1]}"
            
        winners = self.pot.get_winners(self.shared_cards)
        for winner, winnings in sorted(winners.items(), key=lambda item: item[1]):
            hand_name = str(best_possible_hand(self.shared_cards, winner.cards))
            message = f"{message}\n{winner.name} wins ${winnings} with a {hand_name}."
            winner.balance += winnings

        # Remove players that went all in and lost
        i = 0
        while i < len(self.players):
            player = self.players[i]
            if player.balance > 0:
                i += 1
            else:
                message = f"{message}\n{player.name} has been knocked out of the game!"
                self.players.pop(i)
                if len(self.players) == 1:
                    # There's only one player, so they win
                    message = f"{message}\n{self.players[0].user.name} wins the game!\nCongratulations!"
                    self.state = GameState.NO_GAME
                    return message
                if i <= self.dealer_index:
                    self.dealer_index -= 1

        # Go on to the next round
        self.state = GameState.NO_HANDS
        self.next_dealer()
        message = f"{message}\n{self.status_between_rounds()}"
        return message

    # Make the current player check, betting no additional money
    def check(self) -> str:
        self.current_player.placed_bet = True
        message = f"{self.current_player.name} checks.\n{self.next_turn()}"
        return message

    # Has the current player raise a certain amount
    def raise_bet(self, amount: int) -> str:
        self.pot.handle_raise(self.current_player, amount)
        message = f"{self.current_player.name} raises by ${amount}."
        if self.current_player.balance == 0:
            message = f"{message}\n{self.current_player.name} is all in!"
            self.leave_hand(self.current_player)
            self.turn_index -= 1
        message = f"{message}\n{self.next_turn()}"
        
        return message

    # Has the current player match the current bet
    def call(self) -> str:
        self.pot.handle_call(self.current_player)
        message = f"{self.current_player.name} calls."
        if self.current_player.balance == 0:
            message = f"{message}\n{self.current_player.name} is all in!"
            self.leave_hand(self.current_player)
            self.turn_index -= 1
        message = f"{message}\n{self.next_turn()}"

        return message

    def all_in(self) -> List[str]:
        if self.pot.cur_bet > self.current_player.max_bet:
            return self.call()
        else:
            return self.raise_bet(self.current_player.max_bet - self.cur_bet)

    # Has the current player fold their hand
    def fold(self) -> str:
        message = f"{self.current_player.name} has folded."
        self.pot.handle_fold(self.current_player)
        self.leave_hand(self.current_player)

        # If only one person is left in the pot, give it to them instantly
        if len(self.pot.in_pot()) == 1:
            winner = list(self.pot.in_pot())[0]
            message = f"{message}\n{winner.name} wins ${self.pot.value}!"
            winner.balance += self.pot.value
            self.state = GameState.NO_HANDS
            self.next_dealer()
            message = f"{message}\n{self.status_between_rounds()}"

        # If there's still betting to do, go on to the next turn
        elif not self.pot.betting_over():
            self.turn_index -= 1
            message = f"{message}\n{self.next_turn()}"

        # Otherwise, have the showdown immediately
        else:
            message = self.showdown()

        return message

    # Send a message to each player, telling them what their hole cards are
    async def tell_hands(self, client: discord.Client):
        for player in self.players:
            
            #Open card images
            images = [Image.open(x) for x in ['card/' + str(player.cards[0]) + '.png', 'card/' + str(player.cards[1]) + '.png']]
            widths, heights = zip(*(i.size for i in images))
        
            total_width = sum(widths)
            max_height = max(heights)
            #Create new image to send
            new_im = Image.new('RGB', (total_width, max_height))
            x_offset = 0
            for im in images:
              new_im.paste(im, (x_offset,0))
              x_offset += im.size[0]
                
            bytes = BytesIO()
            new_im.save(bytes, format="PNG")
            bytes.seek(0)
            await player.user.send(file = discord.File(bytes, filename='new_im.png'))
