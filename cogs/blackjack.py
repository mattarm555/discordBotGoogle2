import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, button
import random
import os
from PIL import Image
import io
from utils.economy import (
    get_balance,
    add_currency,
    remove_currency,
    can_claim_daily,
    set_daily_claim,
    get_guild_balances,
    daily_time_until_next,
)
from datetime import datetime

# --- Color Codes ---
RESET = "\033[0m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"

def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

# Manual card mapping - each card maps to a specific PNG file
CARD_IMAGES = {
    'A': ['ace_of_spades.png', 'ace_of_hearts.png', 'ace_of_diamonds.png', 'ace_of_clubs.png'],
    '2': ['2_of_spades.png', '2_of_hearts.png', '2_of_diamonds.png', '2_of_clubs.png'],
    '3': ['3_of_spades.png', '3_of_hearts.png', '3_of_diamonds.png', '3_of_clubs.png'],
    '4': ['4_of_spades.png', '4_of_hearts.png', '4_of_diamonds.png', '4_of_clubs.png'],
    '5': ['5_of_spades.png', '5_of_hearts.png', '5_of_diamonds.png', '5_of_clubs.png'],
    '6': ['6_of_spades.png', '6_of_hearts.png', '6_of_diamonds.png', '6_of_clubs.png'],
    '7': ['7_of_spades.png', '7_of_hearts.png', '7_of_diamonds.png', '7_of_clubs.png'],
    '8': ['8_of_spades.png', '8_of_hearts.png', '8_of_diamonds.png', '8_of_clubs.png'],
    '9': ['9_of_spades.png', '9_of_hearts.png', '9_of_diamonds.png', '9_of_clubs.png'],
    '10': ['10_of_spades.png', '10_of_hearts.png', '10_of_diamonds.png', '10_of_clubs.png'],
    'J': ['jack_of_spades.png', 'jack_of_hearts.png', 'jack_of_diamonds.png', 'jack_of_clubs.png'],
    'Q': ['queen_of_spades.png', 'queen_of_hearts.png', 'queen_of_diamonds.png', 'queen_of_clubs.png'],
    'K': ['king_of_spades.png', 'king_of_hearts.png', 'king_of_diamonds.png', 'king_of_clubs.png']
}

# Create deck with card values (not suits since they don't matter)
DECK = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'] * 16  # 4 of each card * 4 suits
random.shuffle(DECK)
deck_index = 0

def deal_card():
    global deck_index, DECK
    if deck_index >= len(DECK):
        # Reshuffle when deck runs out
        DECK = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'] * 16
        random.shuffle(DECK)
        deck_index = 0
    
    card = DECK[deck_index]
    deck_index += 1
    return card

def get_card_image(card):
    """Get a random image file for the given card value"""
    return random.choice(CARD_IMAGES[card])

def card_value(card):
    if card in ['J', 'Q', 'K']:
        return 10
    elif card == 'A':
        return 11  # initially count as 11
    else:
        return int(card)

def hand_value(hand):
    total = sum(card_value(card) for card in hand)
    aces = sum(1 for card in hand if card == 'A')
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

def format_hand(hand, hide_second=False):
    """Format hand for display"""
    display = []
    for i, card in enumerate(hand):
        if hide_second and i == 1:
            display.append("?")
        else:
            display.append(card)
    return " ".join(display)

def format_hand_with_total(hand, hide_second=False, show_ace_values=True):
    """Format hand with total and optionally show ace values"""
    cards_display = format_hand(hand, hide_second)
    
    if hide_second:
        # Don't show total for hidden hands
        return cards_display
    
    total = hand_value(hand)
    
    if show_ace_values:
        # Show how aces are being counted
        aces = sum(1 for card in hand if card == 'A')
        if aces > 0:
            # Calculate how many aces are used as 1 vs 11
            temp_total = sum(card_value(card) for card in hand)
            aces_as_one = 0
            while temp_total > 21 and aces_as_one < aces:
                temp_total -= 10
                aces_as_one += 1
            
            if aces_as_one > 0:
                ace_info = f" (Aces: {aces - aces_as_one} as 11, {aces_as_one} as 1)"
                return f"{cards_display} - Total: {total}{ace_info}"
    
    return f"{cards_display} - Total: {total}"

def create_hand_image(hand, hide_second=False):
    """Create a composite image of the hand using card PNGs"""
    try:
        card_width = 140
        card_height = 190
        spacing = 10
        
        # Calculate image dimensions
        total_width = len(hand) * card_width + (len(hand) - 1) * spacing
        total_height = card_height
        
        # Create base image with transparent background
        image = Image.new('RGBA', (total_width, total_height), (0, 0, 0, 0))
        
        for i, card in enumerate(hand):
            x_pos = i * (card_width + spacing)
            
            if hide_second and i == 1:
                # Use card back
                card_path = os.path.join('cards', 'back_of_card.png')
            else:
                # Get random image for this card value
                card_filename = get_card_image(card)
                card_path = os.path.join('cards', card_filename)
            
            if os.path.exists(card_path):
                card_img = Image.open(card_path)
                card_img = card_img.resize((card_width, card_height), Image.Resampling.LANCZOS)
                image.paste(card_img, (x_pos, 0))
        
        return image
    except Exception as e:
        print(f"Error creating hand image: {e}")
        return None

def image_to_discord_file(image, filename):
    """Convert PIL image to Discord file"""
    if image is None:
        return None
    
    try:
        img_bytes = io.BytesIO()
        image.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return discord.File(img_bytes, filename=filename)
    except Exception as e:
        print(f"Error converting image to Discord file: {e}")
        return None


class BlackjackView(View):
    def __init__(self, cog: 'Blackjack', interaction: Interaction, wager: int):
        # Increase timeout moderately; we'll also keep a strong reference in the cog
        super().__init__(timeout=900)  # 15 minutes
        self.cog = cog
        self.ctx = interaction  # original Interaction for edits
        self.wager = wager
        self.player_hand = [deal_card(), deal_card()]
        self.dealer_hand = [deal_card(), deal_card()]
        self.finished = False
        self.doubled = False
        self.message_id: int | None = None  # set after initial send
        
        # Initial blackjack detection
        self.player_blackjack = hand_value(self.player_hand) == 21
        self.dealer_blackjack = hand_value(self.dealer_hand) == 21
        if self.dealer_blackjack:
            self.finished = True

    def is_blackjack(self, hand):
        return len(hand) == 2 and hand_value(hand) == 21

    async def update(self, interaction: Interaction):
        player_display = format_hand_with_total(self.player_hand)
        if self.finished:
            dealer_display = format_hand_with_total(self.dealer_hand)
        else:
            dealer_display = format_hand(self.dealer_hand, hide_second=True)
        
        # Create hand images
        player_image = create_hand_image(self.player_hand)
        dealer_image = create_hand_image(self.dealer_hand, hide_second=not self.finished)
        
        embed = discord.Embed(title="🂠 Blackjack", color=discord.Color.blurple())
        embed.add_field(name="👤 Your Hand", value=player_display, inline=False)
        embed.add_field(name="🤖 Dealer's Hand", value=dealer_display, inline=False)
        
        # Attach hand images if available
        files = []
        if player_image:
            embed.set_image(url="attachment://hands.png")
            # Combine both hands into one image
            if dealer_image and self.finished:
                # Stack images vertically when game is finished
                total_height = player_image.height + dealer_image.height + 20
                total_width = max(player_image.width, dealer_image.width)
                combined = Image.new('RGBA', (total_width, total_height), (0, 0, 0, 0))
                combined.paste(player_image, (0, 0))
                combined.paste(dealer_image, (0, player_image.height + 20))
                combined_file = image_to_discord_file(combined, "hands.png")
                if combined_file:
                    files.append(combined_file)
            else:
                # Show only player hand
                player_file = image_to_discord_file(player_image, "hands.png")
                if player_file:
                    files.append(player_file)
        
        embed.set_footer(text=f"Wager: {self.wager}")
        
        # Update button states
        self.update_buttons()
        
        # Simple, reliable interaction handling
        try:
            if files:
                await interaction.response.edit_message(embed=embed, view=self, attachments=files)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            try:
                if files:
                    await interaction.edit_original_response(embed=embed, view=self, attachments=files)
                else:
                    await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass
        except Exception:
            try:
                if files:
                    await interaction.edit_original_response(embed=embed, view=self, attachments=files)
                else:
                    await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass

    def update_buttons(self):
        # Disable buttons based on game state
        for item in self.children:
            if item.label == "Double" and (len(self.player_hand) > 2 or self.doubled):
                item.disabled = True
            elif self.finished:
                item.disabled = True

    @button(label="Hit", style=discord.ButtonStyle.green)
    async def hit(self, interaction: Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.user.id or self.finished:
            await interaction.response.defer()
            return
        
        self.player_hand.append(deal_card())
        if hand_value(self.player_hand) > 21:
            self.finished = True
            await self.update(interaction)
            await self.resolve_game(interaction)
            return
        await self.update(interaction)

    @button(label="Stand", style=discord.ButtonStyle.red)
    async def stand(self, interaction: Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.user.id or self.finished:
            await interaction.response.defer()
            return
        
        # Dealer plays
        while hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(deal_card())
        
        self.finished = True
        await self.update(interaction)
        await self.resolve_game(interaction)

    @button(label="Double", style=discord.ButtonStyle.blurple)
    async def double(self, interaction: Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.user.id or self.finished or len(self.player_hand) > 2:
            await interaction.response.defer()
            return
        
        uid = str(self.ctx.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else None
        current_balance = get_balance(uid, guild_id=guild_id)
        if current_balance < self.wager:
            try:
                await interaction.response.send_message(f"❌ Insufficient funds to double down! You need {self.wager} coins but only have {current_balance} coins.", ephemeral=True)
            except:
                await interaction.followup.send(f"❌ Insufficient funds to double down! You need {self.wager} coins but only have {current_balance} coins.", ephemeral=True)
            return
        
        # Double the wager and remove from balance
        remove_currency(uid, self.wager, guild_id=guild_id)
        self.wager *= 2
        self.doubled = True
        
        # Deal one card and stand
        self.player_hand.append(deal_card())
        
        # Dealer plays
        while hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(deal_card())
        
        self.finished = True
        await self.update(interaction)
        await self.resolve_game(interaction)

    async def resolve_game(self, interaction: Interaction):
        uid = str(self.ctx.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else None
        p_value = hand_value(self.player_hand)
        d_value = hand_value(self.dealer_hand)
        p_blackjack = self.is_blackjack(self.player_hand)
        d_blackjack = self.is_blackjack(self.dealer_hand)
        
        payout = 0
        message = ""
        
        # Handle main game
        if p_value > 21:
            # Player busted
            message += f"You busted! Lost {self.wager} coins."
        elif d_value > 21:
            # Dealer busted, player wins
            if p_blackjack and not self.doubled:
                # Natural blackjack pays 3:2
                payout = int(self.wager * 2.5)
                message += f"Blackjack! You win {payout} coins!"
            else:
                # Regular win pays 1:1
                payout = self.wager * 2
                message += f"Dealer busts! You win {payout} coins!"
        elif p_blackjack and d_blackjack:
            # Both blackjack = push
            payout = self.wager
            message += f"Both have blackjack! Push. {payout} coins returned."
        elif p_blackjack and not d_blackjack:
            # Player blackjack wins 3:2
            payout = int(self.wager * 2.5)
            message += f"Blackjack! You win {payout} coins!"
        elif d_blackjack and not p_blackjack:
            # Dealer blackjack wins
            message += f"Dealer blackjack! You lose {self.wager} coins."
        elif p_value > d_value:
            # Player wins
            payout = self.wager * 2
            message += f"You win! +{payout} coins!"
        elif p_value == d_value:
            # Push
            payout = self.wager
            message += f"Push! {payout} coins returned."
        else:
            # Dealer wins
            message += f"Dealer wins! You lose {self.wager} coins."
        
        if payout > 0:
            add_currency(uid, payout, guild_id=guild_id)
        
        # Send the result message as embed
        if ("you win" in message.lower() or "blackjack!" in message.lower() or 
            "dealer busts!" in message.lower()):
            embed_color = discord.Color.green()
            title = "🎉 You Win!"
        elif "push" in message.lower() or "returned" in message.lower():
            embed_color = discord.Color.blue()
            title = "🤝 Push"
        else:
            embed_color = discord.Color.red()
            title = "💸 You Lose"
        
        result_embed = discord.Embed(title=title, description=message, color=embed_color)
        try:
            await interaction.followup.send(embed=result_embed)
        except:
            # If followup fails, try creating a new message in the channel
            try:
                if hasattr(interaction, 'channel') and interaction.channel:
                    await interaction.channel.send(embed=result_embed)
            except:
                pass
        
        self.stop()
        # Unregister from cog active games
        self.cog.unregister_game(uid)

    async def on_timeout(self):
        """Called when the view times out."""
        for item in self.children:
            item.disabled = True
        
        try:
            embed = discord.Embed(title="Blackjack - Timed Out", description="Game timed out. Your wager has been returned.", color=discord.Color.orange())
            # Return wager to user
            uid = str(self.ctx.user.id)
            guild_id = str(self.ctx.guild.id) if self.ctx.guild else None
            add_currency(uid, self.wager, guild_id=guild_id)
            
            if hasattr(self.ctx, 'edit_original_response'):
                await self.ctx.edit_original_response(embed=embed, view=self)
            elif hasattr(self.ctx, 'message'):
                await self.ctx.message.edit(embed=embed, view=self)
        except Exception:
            pass
        finally:
            # Ensure we unregister so user can start a new game
            self.cog.unregister_game(str(self.ctx.user.id))


class Blackjack(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track active blackjack games to prevent GC + duplicate games
        # key: user_id (str) -> BlackjackView
        self.active_games: dict[str, BlackjackView] = {}

    # ---- Active game management ----
    def register_game(self, user_id: str, view: BlackjackView):
        self.active_games[user_id] = view

    def unregister_game(self, user_id: str):
        self.active_games.pop(user_id, None)

    @app_commands.command(name="daily", description="Claim your daily currency reward (once every 24 hours)")
    async def daily(self, interaction: Interaction):
        debug_command('daily', interaction.user, interaction.guild)
        uid = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else None
        if not can_claim_daily(uid, guild_id=guild_id):
            remaining = daily_time_until_next(uid, guild_id=guild_id)
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            parts = []
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if not hours and not minutes:
                parts.append(f"{seconds}s")
            time_str = " ".join(parts)
            desc = (
                "You already claimed your daily reward in this server.\n"
                f"Next claim available in **{time_str}** (midnight UTC reset)."
            )
            embed = discord.Embed(title="⏳ Daily Already Claimed", description=desc, color=discord.Color.orange())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        reward = random.randint(1, 1000)
        add_currency(uid, reward, guild_id=guild_id)
        set_daily_claim(uid, guild_id=guild_id)
        embed = discord.Embed(
            title="🎁 Daily Reward",
            description=f"You received **{reward}** coins today! Come back after the next reset (midnight UTC).",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="balance", description="Check your current coin balance")
    async def balance(self, interaction: Interaction):
        debug_command('balance', interaction.user, interaction.guild)
        uid = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else None
        bal = get_balance(uid, guild_id=guild_id)
        embed = discord.Embed(title="💰 Balance", description=f"{interaction.user.mention} has **{bal}** coins.", color=discord.Color.gold())
        embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pay", description="Pay another user some of your coins (server balance)")
    @app_commands.describe(user="The user to pay", amount="Amount of coins to send (must be positive)")
    async def pay(self, interaction: Interaction, user: discord.User, amount: app_commands.Range[int, 1, 1_000_000]):
        debug_command('pay', interaction.user, interaction.guild, target=user.id, amount=amount)
        if user.id == interaction.user.id:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Invalid Target", description="You can't pay yourself.", color=discord.Color.red()), ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Invalid Target", description="You can't pay a bot.", color=discord.Color.red()), ephemeral=True)
            return
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Server Only", description="This command must be used in a server.", color=discord.Color.red()), ephemeral=True)
            return
        guild_id = str(guild.id)
        sender_id = str(interaction.user.id)
        receiver_id = str(user.id)
        sender_balance = get_balance(sender_id, guild_id=guild_id)
        if amount > sender_balance:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Insufficient Funds", description=f"You tried to pay {amount} but only have {sender_balance} coins.", color=discord.Color.red()), ephemeral=True)
            return
        # Perform transfer atomically (read -> validate -> write both)
        remove_currency(sender_id, amount, guild_id=guild_id)
        add_currency(receiver_id, amount, guild_id=guild_id)
        sender_after = get_balance(sender_id, guild_id=guild_id)
        receiver_after = get_balance(receiver_id, guild_id=guild_id)
        embed = discord.Embed(
            title="💸 Payment Sent",
            description=f"{interaction.user.mention} paid {user.mention} **{amount}** coins.",
            color=discord.Color.green()
        )
        embed.add_field(name="Your New Balance", value=f"{sender_after} coins", inline=True)
        embed.add_field(name=f"{user.display_name}'s New Balance", value=f"{receiver_after} coins", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="blackjack", description="Play a hand of blackjack. Wager between 1 and 2000.")
    @app_commands.describe(wager="Amount to wager (1-2000)")
    async def blackjack(self, interaction: Interaction, wager: int):
        debug_command('blackjack', interaction.user, interaction.guild, wager=wager)
        uid = str(interaction.user.id)
        # Prevent multiple concurrent games for same user
        existing = self.active_games.get(uid)
        if existing and not existing.finished:
            await interaction.response.send_message(embed=discord.Embed(title="⏳ Game In Progress", description="You already have an active blackjack game. Finish or let it timeout before starting another.", color=discord.Color.orange()), ephemeral=True)
            return
        if wager < 1 or wager > 2000:
            embed = discord.Embed(title="❌ Invalid Wager", description="Wager must be between 1 and 2000.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        guild_id = str(interaction.guild.id) if interaction.guild else None
        bal = get_balance(uid, guild_id=guild_id)
        if bal < wager:
            embed = discord.Embed(title="❌ Insufficient Funds", description=f"You need {wager} coins but only have {bal} coins.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        # remove wager upfront
        if not remove_currency(uid, wager, guild_id=guild_id):
            embed = discord.Embed(title="❌ Wager Failed", description="Failed to place wager (insufficient funds).", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        view = BlackjackView(self, interaction, wager)

        # Create initial hand images
        player_image = create_hand_image(view.player_hand)
        dealer_image = create_hand_image(view.dealer_hand, hide_second=True)

        embed = discord.Embed(title="🂠 Blackjack", color=discord.Color.blurple())
        embed.add_field(name="👤 Your Hand", value=format_hand_with_total(view.player_hand), inline=False)
        embed.add_field(name="🤖 Dealer's Hand", value=format_hand(view.dealer_hand, hide_second=True), inline=False)
        embed.set_footer(text=f"Wager: {wager}")

        # Add combined image if available
        files = []
        if player_image and dealer_image:
            total_height = player_image.height + dealer_image.height + 20
            total_width = max(player_image.width, dealer_image.width)
            combined = Image.new('RGBA', (total_width, total_height), (0, 0, 0, 0))
            combined.paste(player_image, (0, 0))
            combined.paste(dealer_image, (0, player_image.height + 20))
            embed.set_image(url="attachment://hands.png")
            combined_file = image_to_discord_file(combined, "hands.png")
            if combined_file:
                files.append(combined_file)

        if files:
            await interaction.response.send_message(embed=embed, view=view, files=files)
        else:
            await interaction.response.send_message(embed=embed, view=view)
        try:
            original = await interaction.original_response()
            view.message_id = original.id
        except Exception:
            view.message_id = None
        self.register_game(uid, view)

    @app_commands.command(name="balancetop", description="Show the top balances in this server.")
    @app_commands.describe(limit="Number of top users to show (default 10)")
    async def balancetop(self, interaction: Interaction, limit: int = 10):
        debug_command('balancetop', interaction.user, interaction.guild, limit=limit)
        guild = interaction.guild
        if not guild:
            embed = discord.Embed(title="❌ Server Only", description="This command must be used in a server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # gather balances for guild members
        balances = get_guild_balances(str(guild.id))
        members = []
        for member in guild.members:
            bal = int(balances.get(str(member.id), 0))
            if bal > 0:
                members.append((member, bal))

        if not members:
            await interaction.response.send_message(embed=discord.Embed(title="💤 No balances", description="No users with balances found in this server.", color=discord.Color.dark_gray()))
            return

        members.sort(key=lambda x: x[1], reverse=True)
        top = members[:max(1, min(limit, 50))]

        embed = discord.Embed(title="🏆 Balance Leaderboard", color=discord.Color.gold())
        for i, (member, bal) in enumerate(top, start=1):
            embed.add_field(name=f"#{i} {member.display_name}", value=f"{bal} coins", inline=False)

        # put top user's avatar as thumbnail
        top_user = top[0][0]
        embed.set_thumbnail(url=top_user.avatar.url if top_user.avatar else top_user.default_avatar.url)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Blackjack(bot))