import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, button
import random
import os
from PIL import Image
import io
import asyncio
from utils.economy import (
    get_balance,
    add_currency,
    remove_currency,
    can_claim_daily,
    set_daily_claim,
    get_guild_balances,
    daily_time_until_next,
    delete_balance,
)
from datetime import datetime
import json
from datetime import timedelta
from utils.botadmin import is_bot_admin
import re

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
        # Make view persistent; we'll explicitly close/disable when done
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = interaction  # original Interaction for edits
        self.wager = wager
        self.player_hand = [deal_card(), deal_card()]
        self.dealer_hand = [deal_card(), deal_card()]
        self.finished = False
        self.doubled = False
        self.message_id: int | None = None  # set after initial send
        # Fail-safe tracking
        self.failure_time: datetime | None = None
        self.refunded: bool = False
        self.refund_task: asyncio.Task | None = None
        
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
        success = False
        try:
            if interaction.response.is_done():
                # Already responded elsewhere
                if files:
                    await interaction.edit_original_response(embed=embed, view=self, attachments=files)
                else:
                    await interaction.edit_original_response(embed=embed, view=self)
            else:
                if files:
                    await interaction.response.edit_message(embed=embed, view=self, attachments=files)
                else:
                    await interaction.response.edit_message(embed=embed, view=self)
            success = True
        except Exception:
            # Final fallback attempt
            try:
                if files:
                    await interaction.edit_original_response(embed=embed, view=self, attachments=files)
                else:
                    await interaction.edit_original_response(embed=embed, view=self)
                success = True
            except Exception:
                success = False

        if not success:
            # Mark interaction failure and schedule refund if not already
            self.mark_failure()

    def update_buttons(self):
        # Disable buttons based on game state
        for item in self.children:
            if item.label == "Double" and (len(self.player_hand) > 2 or self.doubled):
                item.disabled = True
            elif self.finished:
                item.disabled = True

    def mark_failure(self):
        if self.failure_time is None:
            self.failure_time = datetime.utcnow()
            # Schedule a one-off refund in 60s
            if self.refund_task is None:
                self.refund_task = asyncio.create_task(self._refund_after_delay())

    async def _refund_after_delay(self):
        try:
            await asyncio.sleep(60)
            # Hard safety: refund even if there was no explicit interaction failure,
            # as long as the game hasn't finished and wasn't refunded.
            if (not self.finished) and (not self.refunded):
                await self.refund_wager(reason="interaction failure")
        except Exception:
            pass

    async def refund_wager(self, reason: str):
        if self.refunded:
            return
        self.refunded = True
        self.finished = True
        uid = str(self.ctx.user.id)
        guild_id = str(self.ctx.guild.id) if self.ctx.guild else None
        add_currency(uid, self.wager, guild_id=guild_id)
        # Attempt to notify user if possible
        try:
            embed = discord.Embed(title="Blackjack Closed", description=f"Game closed due to {reason}. Wager refunded ({self.wager}).", color=discord.Color.orange())
            if self.ctx.channel:
                await self.ctx.channel.send(content=self.ctx.user.mention, embed=embed)
        except Exception:
            pass
        # Disable buttons and try to update message
        for item in self.children:
            item.disabled = True
        try:
            await self.ctx.edit_original_response(view=self)
        except Exception:
            pass
        # Cancel any pending refund task
        try:
            if self.refund_task and not self.refund_task.done():
                self.refund_task.cancel()
        except Exception:
            pass
        # Unregister game
        self.cog.unregister_game(uid)
        self.stop()

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
        # Disable buttons and try to update the original message
        for item in self.children:
            item.disabled = True
        try:
            await self.ctx.edit_original_response(view=self)
        except Exception:
            pass

        # Cancel any pending refund task
        try:
            if self.refund_task and not self.refund_task.done():
                self.refund_task.cancel()
        except Exception:
            pass

        self.stop()
        # Unregister from cog active games
        self.cog.unregister_game(uid)

    async def on_timeout(self):
        """Called when the view times out."""
        for item in self.children:
            item.disabled = True
        
        try:
            await self.refund_wager("inactivity timeout")
        except Exception:
            pass


class Blackjack(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track active blackjack games to prevent GC + duplicate games
        # key: user_id (str) -> BlackjackView
        self.active_games: dict[str, BlackjackView] = {}
        # Per-user cooldown tracking for starting new hands
        self._last_hand_at: dict[str, datetime] = {}
        # Blackjack persistent stats
        self.stats_file = "blackjackstats.json"
        self.stats = self._load_stats()
        self.SESSION_TIMEOUT = timedelta(minutes=30)
        # Shared casino config file (used by slots too)
        self._cfg_file = "casino_config.json"

    # ---- Blackjack Stats Persistence ----
    def _load_stats(self):
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {"guilds": {}}
        return {"guilds": {}}

    def _save_stats(self):
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=4)
        except Exception:
            pass

    # ---- Config helpers (shared with slots) ----
    def _load_cfg(self):
        if os.path.exists(self._cfg_file):
            try:
                with open(self._cfg_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {"guilds": {}}
        return {"guilds": {}}

    def _save_cfg(self, data):
        try:
            with open(self._cfg_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def _get_guild_cfg(self, guild_id: str) -> dict:
        data = self._load_cfg()
        return data.setdefault("guilds", {}).setdefault(str(guild_id), {})

    def _set_guild_cfg(self, guild_id: str, cfg: dict):
        data = self._load_cfg()
        data.setdefault("guilds", {})[str(guild_id)] = cfg
        self._save_cfg(data)

    def _parse_duration_to_seconds(self, text: str) -> int:
        if not text:
            return 0
        s = str(text).strip().lower()
        if s.isdigit():
            return int(s)
        m = re.match(r"^(\d+)\s*([smh])$", s)
        if m:
            val = int(m.group(1))
            unit = m.group(2)
            if unit == 's':
                return val
            if unit == 'm':
                return val * 60
            if unit == 'h':
                return val * 3600
        return 0

    def get_blackjack_cooldown_seconds(self, guild_id: str | None) -> int:
        try:
            if not guild_id:
                return 15
            cfg = self._get_guild_cfg(guild_id)
            sec = int(cfg.get("blackjack_cooldown", 15))
            return max(10, sec)
        except Exception:
            return 15

    def _bj_cooldown_remaining(self, uid: str, cooldown_sec: int) -> int:
        last = self._last_hand_at.get(uid)
        if not last:
            return 0
        try:
            elapsed = (datetime.utcnow() - last).total_seconds()
            rem = cooldown_sec - elapsed
            if rem <= 0:
                return 0
            return int(rem) if float(rem).is_integer() else int(rem) + 1
        except Exception:
            return 0

    def _ensure_user(self, guild_id: str, user_id: str):
        g = self.stats.setdefault("guilds", {}).setdefault(str(guild_id), {})
        u = g.setdefault(user_id, {
            "hands": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "blackjacks": 0,
            "doubles": 0,
            "bet_total": 0,
            "win_total": 0,
            "net": 0,
            "biggest_win": 0,
            "biggest_wager": 0,
            "last_play": None,
            "session_baseline": None,
        })
        return u

    def _maybe_reset_session(self, u: dict):
        last_play = u.get("last_play")
        if not last_play:
            return
        try:
            last_dt = datetime.fromisoformat(last_play)
        except Exception:
            return
        if datetime.utcnow() - last_dt > self.SESSION_TIMEOUT:
            # Reset the session baseline to current totals
            u["session_baseline"] = {
                "hands": u.get("hands", 0),
                "bet_total": u.get("bet_total", 0),
                "win_total": u.get("win_total", 0),
                "net": u.get("net", 0),
            }

    def _ensure_baseline(self, u: dict):
        if u.get("session_baseline") is None:
            u["session_baseline"] = {
                "hands": u.get("hands", 0),
                "bet_total": u.get("bet_total", 0),
                "win_total": u.get("win_total", 0),
                "net": u.get("net", 0),
            }

    def record_hand(self, guild_id: str | None, user_id: str, wager: int, payout: int, result: str, player_blackjack: bool, doubled: bool):
        if not guild_id:
            return  # only track per guild
        u = self._ensure_user(guild_id, user_id)
        # Possibly reset session
        self._maybe_reset_session(u)
        self._ensure_baseline(u)
        u["hands"] += 1
        u["bet_total"] += wager
        u["win_total"] += payout
        net = payout - wager
        u["net"] += net
        if wager > u.get("biggest_wager", 0):
            u["biggest_wager"] = wager
        if payout - wager > u.get("biggest_win", 0):  # biggest positive profit from a hand
            u["biggest_win"] = payout - wager
        if result == "win":
            u["wins"] += 1
        elif result == "loss":
            u["losses"] += 1
        elif result == "push":
            u["pushes"] += 1
        if player_blackjack:
            u["blackjacks"] += 1
        if doubled:
            u["doubles"] += 1
        u["last_play"] = datetime.utcnow().isoformat()
        self._save_stats()

    def get_user_stats(self, guild_id: str, user_id: str):
        return self.stats.get("guilds", {}).get(str(guild_id), {}).get(user_id)

    # ---- Active game management ----
    def register_game(self, user_id: str, view: BlackjackView):
        self.active_games[user_id] = view

    def unregister_game(self, user_id: str):
        self.active_games.pop(user_id, None)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Remove the user's guild-scoped balance when they leave to avoid clogging
        try:
            delete_balance(str(member.id), guild_id=str(member.guild.id))
        except Exception:
            pass

    
    @app_commands.command(name="balance", description="Check your or another user's coin balance")
    @app_commands.describe(user="User to check (optional)")
    async def balance(self, interaction: Interaction, user: discord.User | None = None):
        debug_command('balance', interaction.user, interaction.guild, target=(user.id if user else None))
        target = user or interaction.user
        uid = str(target.id)
        guild_id = str(interaction.guild.id) if interaction.guild else None
        bal = get_balance(uid, guild_id=guild_id)
        embed = discord.Embed(title="💰 Balance", description=f"{target.mention} has **{bal}** coins.", color=discord.Color.gold())
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
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

    @app_commands.command(name="add", description="Add coins to a user's server balance (bot-admin only)")
    @app_commands.describe(user="User to receive coins", amount="Amount of coins to add (1-1,000,000)")
    async def add(self, interaction: Interaction, user: discord.User, amount: app_commands.Range[int, 1, 1_000_000]):
        debug_command('add', interaction.user, interaction.guild, target=user.id, amount=amount)
        if not isinstance(interaction.user, discord.Member) or not is_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Server Only", description="This command must be used in a server.", color=discord.Color.red()), ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Invalid Target", description="You can't add coins to a bot.", color=discord.Color.red()), ephemeral=True)
            return
        guild_id = str(guild.id)
        receiver_id = str(user.id)
        add_currency(receiver_id, int(amount), guild_id=guild_id)
        receiver_after = get_balance(receiver_id, guild_id=guild_id)
        embed = discord.Embed(title="✅ Coins Added", description=f"{user.mention} received **{amount}** coins.", color=discord.Color.green())
        embed.add_field(name=f"{user.display_name}'s New Balance", value=f"{receiver_after} coins", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="blackjack", description="Play a hand of blackjack. Wager between 1 and 50000.")
    @app_commands.describe(wager="Amount to wager (1-50000)")
    async def blackjack(self, interaction: Interaction, wager: int):
        debug_command('blackjack', interaction.user, interaction.guild, wager=wager)
        uid = str(interaction.user.id)
        # Prevent multiple concurrent games for same user
        existing = self.active_games.get(uid)
        if existing and not existing.finished:
            await interaction.response.send_message(embed=discord.Embed(title="⏳ Game In Progress", description="You already have an active blackjack game. Finish or let it timeout before starting another.", color=discord.Color.orange()), ephemeral=True)
            return
        # Cooldown: per-guild configurable, minimum 10 seconds
        try:
            guild_id = str(interaction.guild.id) if interaction.guild else None
            cd = self.get_blackjack_cooldown_seconds(guild_id)
            remaining = self._bj_cooldown_remaining(uid, cd)
            if remaining > 0:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="⏳ Slow Down",
                        description=f"Please wait **{remaining}s** before starting another hand of blackjack.",
                        color=discord.Color.orange()
                    ),
                    ephemeral=True
                )
                return
        except Exception:
            # Fail-open on any unexpected error to avoid blocking users
            pass
        if wager < 1 or wager > 50000:
            embed = discord.Embed(title="❌ Invalid Wager", description="Wager must be between 1 and 50000.", color=discord.Color.red())
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
        # Record cooldown start only after a wager is successfully placed
        self._last_hand_at[uid] = datetime.utcnow()
        
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

        # Send initial embed without the view to avoid early interaction/view init races
        if files:
            await interaction.response.send_message(embed=embed, files=files)
        else:
            await interaction.response.send_message(embed=embed)

        # Staggered setup: wait briefly, then attach the persistent view (ticket-style)
        await asyncio.sleep(1.0)

        # Start a hard 60s refund safety timer similar to tickets' persistent button behavior
        try:
            if view.refund_task is None:
                view.refund_task = asyncio.create_task(view._refund_after_delay())
        except Exception:
            pass

        try:
            # Attach the view without disturbing the embed/attachments
            await interaction.edit_original_response(view=view)
            original = await interaction.original_response()
            view.message_id = original.id
        except Exception:
            view.message_id = None
        # Register game after message is live
        self.register_game(uid, view)

    # Store wager on view for stats usage later (already exists as self.wager)

    @app_commands.command(name="balancetop", description="Show the top balances in this server (10 per page).")
    @app_commands.describe(page="Page number to view (default 1)")
    async def balancetop(self, interaction: Interaction, page: int = 1):
        debug_command('balancetop', interaction.user, interaction.guild, page=page)
        guild = interaction.guild
        if not guild:
            embed = discord.Embed(title="❌ Server Only", description="This command must be used in a server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        balances = get_guild_balances(str(guild.id))  # user_id -> balance
        # Build a list of (user_id, balance) including users not cached if present in balances
        items = [(uid, int(bal)) for uid, bal in balances.items() if int(bal) > 0]
        if not items:
            await interaction.response.send_message(embed=discord.Embed(title="💤 No balances", description="No users with balances found in this server.", color=discord.Color.dark_gray()))
            return

        # Sort by balance desc
        items.sort(key=lambda x: x[1], reverse=True)
        page_size = 10
        total = len(items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        if page < 1:
            page = 1
        if page > total_pages:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Page Out of Range",
                description=f"There are only **{total_pages}** page(s) (total **{total}** users). Try a smaller page number.",
                color=discord.Color.red()
            ), ephemeral=True)
            return

        view = BalanceLeaderboardView(guild, items, page_size=page_size, page=page)
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    # ---- Admin: set blackjack cooldown ----
    @app_commands.command(name="blackjack_set_cooldown", description="Admin: Set per-user cooldown between blackjack hands (min 10s). Accepts 10, 10s, 2m, 1h.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(duration="Cooldown duration (e.g., 10s, 15s, 1m)")
    async def blackjack_set_cooldown(self, interaction: Interaction, duration: str):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Use this in a server.", ephemeral=True)
            return
        seconds = self._parse_duration_to_seconds(duration)
        if seconds < 10:
            await interaction.response.send_message("❌ Minimum cooldown is 10 seconds.", ephemeral=True)
            return
        cfg = self._get_guild_cfg(str(guild.id))
        cfg["blackjack_cooldown"] = int(seconds)
        self._set_guild_cfg(str(guild.id), cfg)
        await interaction.response.send_message(embed=discord.Embed(title="✅ Blackjack Cooldown Set", description=f"Blackjack hand cooldown set to {seconds}s.", color=discord.Color.green()), ephemeral=True)


class BalanceLeaderboardView(View):
    def __init__(self, guild: discord.Guild, items: list[tuple[str, int]], page_size: int = 10, page: int = 1, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.guild = guild
        self.items = items  # list of (user_id, balance)
        self.page_size = page_size
        self.total = len(items)
        self.total_pages = max(1, (self.total + page_size - 1) // page_size)
        self.page = max(1, min(page, self.total_pages))
        self._update_buttons()

    def _slice(self):
        start = (self.page - 1) * self.page_size
        end = min(start + self.page_size, self.total)
        return start, end, self.items[start:end]

    def make_embed(self) -> discord.Embed:
        start, end, page_items = self._slice()
        embed = discord.Embed(title=f"🏆 Balance Leaderboard — Page {self.page}/{self.total_pages}", color=discord.Color.gold())
        first_member = None
        for idx, (uid, bal) in enumerate(page_items, start=start + 1):
            member = self.guild.get_member(int(uid))
            display_name = member.display_name if member else f"<@{uid}>"
            if member and first_member is None:
                first_member = member
            embed.add_field(name=f"#{idx} {display_name}", value=f"{bal} coins", inline=False)
        if first_member:
            embed.set_thumbnail(url=first_member.avatar.url if first_member.avatar else first_member.default_avatar.url)
        return embed

    def _update_buttons(self):
        # Ensure buttons reflect current page bounds
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == 'bal_prev':
                    child.disabled = self.page <= 1
                elif child.custom_id == 'bal_next':
                    child.disabled = self.page >= self.total_pages
                elif child.custom_id == 'bal_back5':
                    child.disabled = self.page <= 1
                elif child.custom_id == 'bal_fwd5':
                    child.disabled = self.page >= self.total_pages

    @button(label="⏮ -5", style=discord.ButtonStyle.gray, custom_id='bal_back5')
    async def back5(self, interaction: Interaction, button: discord.ui.Button):
        old = self.page
        self.page = max(1, self.page - 5)
        if self.page == old:
            await interaction.response.defer()
            return
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @button(label="⬅️ Prev", style=discord.ButtonStyle.blurple, custom_id='bal_prev')
    async def prev(self, interaction: Interaction, button: discord.ui.Button):
        if self.page <= 1:
            await interaction.response.defer()
            return
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @button(label="Next ➡️", style=discord.ButtonStyle.blurple, custom_id='bal_next')
    async def next(self, interaction: Interaction, button: discord.ui.Button):
        if self.page >= self.total_pages:
            await interaction.response.defer()
            return
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @button(label="+5 ⏭", style=discord.ButtonStyle.gray, custom_id='bal_fwd5')
    async def fwd5(self, interaction: Interaction, button: discord.ui.Button):
        old = self.page
        self.page = min(self.total_pages, self.page + 5)
        if self.page == old:
            await interaction.response.defer()
            return
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(Blackjack(bot))