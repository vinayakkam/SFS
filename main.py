import discord
from discord.ext import commands, tasks
import aiohttp
from keep_alive import keep_alive
keep_alive()
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
load_dotenv()
# Configuration

DISCORD_TOKEN =os.getenv('DISCORD_TOKEN')
CHANNEL_ID = 1443636093433155776  # Replace with your channel ID
CHECK_INTERVAL = 5  # Check every 5 minutes
LAUNCH_URL = 'https://superheavybooster.github.io/Booster-16-Space-Exploration-Technologies-Corporation/#launches'
# Manual launch time configuration (IN UTC!)
# Format: "November 28, 2025 13:00:00" in UTC
MANUAL_LAUNCH_TIMES = {
    "When Elephants Fly": "November 29, 2025 13:00:00"  # UTC time!
}

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store active launch messages for live updates
active_launches = {}


async def update_countdown_embeds():
    """Update all active countdown embeds"""
    for launch_id, launch_data in list(active_launches.items()):
        try:
            channel = bot.get_channel(launch_data['channel_id'])
            if not channel:
                continue

            message = await channel.fetch_message(launch_data['message_id'])
            launch_date = parse_launch_date(launch_data['date'], launch_data.get('exact_time'), launch_data['title'])

            if not launch_date:
                continue

            # Ensure launch_date is timezone-aware
            if launch_date.tzinfo is None:
                launch_date = launch_date.replace(tzinfo=timezone.utc)

            # Check if launch is ongoing (countdown hit zero)
            countdown = get_countdown_string(launch_date)
            now_utc = datetime.now(timezone.utc)
            is_ongoing = launch_date and now_utc >= launch_date

            # If launch has been ongoing for more than 30 minutes, stop tracking
            if is_ongoing and launch_date:
                time_since_launch = (now_utc - launch_date).total_seconds()
                if time_since_launch > 1800:  # 30 minutes
                    print(f"🚀 Launch {launch_data['title']} completed, removing from tracking")
                    del active_launches[launch_id]
                    continue

            # Change color to red if ongoing
            embed_color = 0xFF0000 if is_ongoing else 0x7c7cff

            # Recreate embed with updated countdown
            embed = discord.Embed(
                title=f"🚀 {launch_data['title']}",
                url=LAUNCH_URL,
                color=embed_color,
                description=f"**Mission Overview**\n{launch_data['description']}\n\n{'━' * 40}",
                timestamp=now_utc
            )

            author_text = "🔴 LAUNCH ONGOING" if is_ongoing else "🔔 UPCOMING LAUNCH"
            embed.set_author(name=author_text,
                             icon_url="https://em-content.zobj.net/thumbs/120/twitter/348/rocket_1f680.png")
            embed.add_field(name="📅 Launch Date", value=f"```{launch_data['date']}```", inline=True)
            embed.add_field(name="📍 Launch Site", value=f"```{launch_data['location']}```", inline=True)
            embed.add_field(name="⏱️ T-Minus", value=countdown, inline=False)

            links_text = f"🌐 [Mission Details]({LAUNCH_URL})"
            if launch_data.get('watch_link'):
                links_text += f" • 📺 [Watch Live]({launch_data['watch_link']})"
            embed.add_field(name="🔗 Links", value=links_text, inline=False)

            embed.set_footer(text="StaticFire Launch Services • Live Countdown (Updates Every Second)",
                             icon_url="https://em-content.zobj.net/thumbs/120/twitter/348/satellite_1f6f0-fe0f.png")

            await message.edit(embed=embed)
        except Exception as e:
            print(f"Error updating countdown for {launch_id}: {e}")
            import traceback
            traceback.print_exc()


@tasks.loop(seconds=1)
async def update_countdowns():
    """Update countdowns every second"""
    await update_countdown_embeds()


async def fetch_launch_data():
    """Fetch and parse launch data from the website"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LAUNCH_URL) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    launches = []

                    # Find all script tags to extract countdown target times
                    scripts = soup.find_all('script')
                    countdown_targets = {}

                    for script in scripts:
                        if script.string and 'countdown' in script.string.lower():
                            # Extract target date from JavaScript
                            import re
                            # Look for patterns like: new Date("November 28, 2025 14:30:00")
                            matches = re.findall(r'new Date\(["\']([^"\']+)["\']\)', script.string)
                            if matches:
                                for match in matches:
                                    countdown_targets[match] = match

                    # Find all elements containing mission information
                    all_text = soup.get_text()

                    # Split by common month names to find launch entries
                    months = ['January', 'February', 'March', 'April', 'May', 'June',
                              'July', 'August', 'September', 'October', 'November', 'December']

                    lines = all_text.split('\n')

                    i = 0
                    while i < len(lines):
                        line = lines[i].strip()

                        # Check if line contains a date pattern (Month Day, Year • Location)
                        if '•' in line and any(month in line for month in months):
                            parts = line.split('•')
                            if len(parts) == 2:
                                date_text = parts[0].strip()
                                location = parts[1].strip()

                                # Look ahead for title (usually right after T-minus or before date)
                                title = None
                                description_parts = []
                                has_tminus = False
                                watch_link = None
                                exact_launch_time = None

                                # Look backwards for title
                                for j in range(max(0, i - 5), i):
                                    prev_line = lines[j].strip()
                                    if prev_line and len(prev_line) > 3 and prev_line not in ['Upcoming', 'T-minus',
                                                                                              'DAYS', 'HOURS',
                                                                                              'MINUTES', 'SECONDS']:
                                        if not any(month in prev_line for month in months):
                                            title = prev_line
                                            break

                                # Look forward for description and check for T-minus
                                for j in range(i + 1, min(len(lines), i + 20)):
                                    next_line = lines[j].strip()
                                    if 'T-minus' in next_line or 'T-MINUS' in next_line:
                                        has_tminus = True
                                    elif 'twitch.tv' in next_line.lower() or 'youtube.com' in next_line.lower():
                                        # Extract the watch link from surrounding lines
                                        if j > 0:
                                            watch_link = lines[j - 1].strip()
                                    elif next_line and len(next_line) > 30 and '•' not in next_line:
                                        if not any(keyword in next_line.lower() for keyword in
                                                   ['where you can watch', 'on our', 'twitch', 'youtube']):
                                            description_parts.append(next_line)

                                    # Stop if we hit another date
                                    if '•' in next_line and any(month in next_line for month in months):
                                        break

                                description = ' '.join(description_parts[:3])  # First 3 relevant lines

                                # Try to find exact countdown target from JavaScript
                                for target_str in countdown_targets.keys():
                                    if date_text in target_str:
                                        exact_launch_time = target_str
                                        break

                                # Only add if it has T-minus (indicating upcoming launch)
                                if has_tminus and title:
                                    # Find the actual watch link from the HTML
                                    watch_url = None
                                    for link in soup.find_all('a'):
                                        href = link.get('href', '')
                                        if 'twitch.tv' in href or 'youtube.com' in href:
                                            # Check if this link is near our date in the HTML
                                            link_text = link.parent.get_text() if link.parent else ''
                                            if date_text in link_text or title in link_text:
                                                watch_url = href
                                                break

                                    # If no watch link found in context, use the default Twitch
                                    if not watch_url:
                                        watch_url = 'https://www.twitch.tv/superheavybooster'

                                    launches.append({
                                        'id': f"{title}-{date_text}",
                                        'title': title,
                                        'date': date_text,
                                        'exact_time': exact_launch_time,
                                        'location': location,
                                        'description': description[
                                            :1024] if description else 'No description available',
                                        'countdown': has_tminus,
                                        'watch_link': watch_url
                                    })

                        i += 1

                    print(f"Found {len(launches)} upcoming launches")
                    return launches
                else:
                    print(f"Error fetching page: Status {response.status}")
                    return []
    except Exception as e:
        print(f"Error fetching launch data: {e}")
        import traceback
        traceback.print_exc()
        return []


def parse_launch_date(date_string, exact_time=None, title=None):
    """Parse date string and return datetime object in UTC"""
    try:
        # Check if there's a manual override for this launch
        if title and title in MANUAL_LAUNCH_TIMES:
            print(f"Using manual launch time for {title}: {MANUAL_LAUNCH_TIMES[title]} UTC")
            # Parse as UTC time
            dt = datetime.strptime(MANUAL_LAUNCH_TIMES[title], "%B %d, %Y %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)

        # If exact time is provided from JavaScript, use it
        if exact_time:
            dt = datetime.strptime(exact_time, "%B %d, %Y %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)

        # Otherwise parse just the date (defaults to midnight UTC)
        dt = datetime.strptime(date_string, "%B %d, %Y")
        return dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"Error parsing date: {e}")
        return None


def get_countdown_string(launch_date):
    """Calculate countdown from now to launch date"""
    if not launch_date:
        return "TBD"

    # Use UTC for current time
    now = datetime.now(timezone.utc)
    delta = launch_date - now

    # If countdown reaches zero or is negative, show "ONGOING"
    if delta.total_seconds() <= 0:
        return "🔴 **LAUNCH ONGOING!**"

    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    seconds = delta.seconds % 60

    return f"**{days:02d}** days **{hours:02d}** hours **{minutes:02d}** minutes **{seconds:02d}** seconds"


async def send_launch_notification(channel, launch):
    """Send launch notification embed to Discord channel with live countdown"""
    launch_date = parse_launch_date(launch['date'], launch.get('exact_time'), launch['title'])

    if not launch_date:
        print(f"❌ Could not parse launch date for {launch['title']}")
        return None

    # Ensure launch_date is timezone-aware
    if launch_date.tzinfo is None:
        launch_date = launch_date.replace(tzinfo=timezone.utc)

    countdown = get_countdown_string(launch_date)

    print(f"Launch date parsed as: {launch_date} UTC")
    print(f"Current UTC time: {datetime.now(timezone.utc)}")
    print(f"Current countdown: {countdown}")

    # Create beautiful embed
    embed = discord.Embed(
        title=f"🚀 {launch['title']}",
        url=LAUNCH_URL,
        color=0x7c7cff,
        description=f"**Mission Overview**\n{launch['description']}\n\n{'━' * 40}",
        timestamp=datetime.now(timezone.utc)
    )

    # Add thumbnail (rocket emoji as placeholder)
    embed.set_author(name="🔔 NEW UPCOMING LAUNCH",
                     icon_url="https://em-content.zobj.net/thumbs/120/twitter/348/rocket_1f680.png")

    # Launch details
    embed.add_field(name="📅 Launch Date", value=f"```{launch['date']}```", inline=True)
    embed.add_field(name="📍 Launch Site", value=f"```{launch['location']}```", inline=True)
    embed.add_field(name="⏱️ T-Minus", value=countdown, inline=False)

    # Links section
    links_text = f"🌐 [Mission Details]({LAUNCH_URL})"
    if launch.get('watch_link'):
        links_text += f" • 📺 [Watch Live]({launch['watch_link']})"
    embed.add_field(name="🔗 Links", value=links_text, inline=False)

    embed.set_footer(text="StaticFire Launch Services • Updates every second",
                     icon_url="https://em-content.zobj.net/thumbs/120/twitter/348/satellite_1f6f0-fe0f.png")

    try:
        message = await channel.send("@everyone", embed=embed)
        print(f"✅ Sent notification for: {launch['title']}")

        # Store message for live updates
        if 'message_id' not in launch:
            launch['message_id'] = message.id
            launch['channel_id'] = channel.id

        return message
    except Exception as e:
        print(f"❌ Error sending notification: {e}")
        return None


@tasks.loop(minutes=CHECK_INTERVAL)
async def check_for_new_launches():
    """Periodically check for new launches"""
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("❌ Channel not found!")
        return

    launches = await fetch_launch_data()
    print(f"🔍 Checking launches... Found {len(launches)} upcoming")

    for launch in launches:
        print(f"  - Launch ID: {launch['id']}")
        if launch['id'] not in active_launches:
            print(f"  ✨ NEW LAUNCH DETECTED: {launch['title']}")
            message = await send_launch_notification(channel, launch)
            if message:
                active_launches[launch['id']] = {
                    'message_id': message.id,
                    'channel_id': channel.id,
                    'title': launch['title'],
                    'date': launch['date'],
                    'exact_time': launch.get('exact_time'),
                    'location': launch['location'],
                    'description': launch['description'],
                    'watch_link': launch.get('watch_link')
                }
            await asyncio.sleep(1)  # Avoid rate limiting
        else:
            print(f"  ✓ Already tracked: {launch['title']}")


@bot.event
async def on_ready():
    """Bot startup event"""
    print(f"✅ Bot logged in as {bot.user}")
    print(f"📡 Monitoring launches from: {LAUNCH_URL}")

    # DON'T populate tracked launches on startup - let the first check send notifications
    print(f"🚀 Bot is ready! Waiting for first check in {CHECK_INTERVAL} minutes...")
    print(f"💡 Use !check command to manually check for launches now")

    # Start the background tasks
    check_for_new_launches.start()
    update_countdowns.start()


@bot.command(name='check')
async def manual_check(ctx):
    """Manually check for new launches"""
    await ctx.send("🔍 Checking for new launches...")
    await check_for_new_launches()


@bot.command(name='status')
async def status(ctx):
    """Check bot status"""
    embed = discord.Embed(
        title="🤖 Launch Bot Status",
        color=0x7c7cff,
        description="Live launch tracking system operational"
    )
    embed.add_field(name="📊 Active Launches", value=f"{len(active_launches)} tracked", inline=True)
    embed.add_field(name="⏰ Check Interval", value=f"{CHECK_INTERVAL} minutes", inline=True)
    embed.add_field(name="🔄 Countdown Updates", value="Every second", inline=True)
    embed.add_field(name="🌐 Source", value=f"[Launch Site]({LAUNCH_URL})", inline=False)

    if active_launches:
        launches_text = "\n".join([f"🚀 {data['title']}" for data in active_launches.values()])
        embed.add_field(name="Current Missions", value=launches_text, inline=False)

    embed.set_footer(text="StaticFire Launch Services")
    await ctx.send(embed=embed)


@bot.command(name='setlaunch')
async def set_launch(ctx, *, args):
    """
    Manually set a launch countdown
    Usage: !setlaunch "Launch Title" "November 28, 2025 13:00:00" "Cape Canaveral" "Mission description"
    """
    try:
        # Parse arguments - expecting quoted strings
        import shlex
        parsed_args = shlex.split(args)

        if len(parsed_args) < 4:
            await ctx.send(
                "❌ Invalid format! Use: `!setlaunch \"Title\" \"Date Time\" \"Location\" \"Description\"`\nExample: `!setlaunch \"Test Mission\" \"November 30, 2025 14:00:00\" \"Cape Canaveral\" \"Test flight\"`")
            return

        title = parsed_args[0]
        datetime_str = parsed_args[1]
        location = parsed_args[2]
        description = " ".join(parsed_args[3:]) if len(parsed_args) > 3 else parsed_args[3]

        # Validate datetime format
        try:
            launch_dt = datetime.strptime(datetime_str, "%B %d, %Y %H:%M:%S")
            launch_dt = launch_dt.replace(tzinfo=timezone.utc)
        except:
            await ctx.send("❌ Invalid date format! Use: `November 28, 2025 13:00:00`")
            return

        # Add to manual launch times
        MANUAL_LAUNCH_TIMES[title] = datetime_str

        # Create launch data
        launch = {
            'id': f"{title}-{datetime_str}",
            'title': title,
            'date': datetime_str.split()[0:3],  # Extract just date part
            'date': " ".join(datetime_str.split()[0:3]),
            'exact_time': datetime_str,
            'location': location,
            'description': description,
            'countdown': True,
            'watch_link': 'https://www.twitch.tv/superheavybooster'
        }

        # Send notification
        message = await send_launch_notification(ctx.channel, launch)

        if message:
            # Add to active launches
            active_launches[launch['id']] = {
                'message_id': message.id,
                'channel_id': ctx.channel.id,
                'title': title,
                'date': launch['date'],
                'exact_time': datetime_str,
                'location': location,
                'description': description,
                'watch_link': 'https://www.twitch.tv/superheavybooster'
            }

            await ctx.send(f"✅ Launch `{title}` has been set and is now tracking!")

    except Exception as e:
        await ctx.send(
            f"❌ Error: {e}\nUse: `!setlaunch \"Title\" \"November 28, 2025 13:00:00\" \"Location\" \"Description\"`")


@bot.command(name='removelaunch')
async def remove_launch(ctx, *, title):
    """
    Remove a launch from tracking
    Usage: !removelaunch Launch Title
    """
    removed = False
    for launch_id, launch_data in list(active_launches.items()):
        if launch_data['title'].lower() == title.lower():
            del active_launches[launch_id]
            if title in MANUAL_LAUNCH_TIMES:
                del MANUAL_LAUNCH_TIMES[title]
            removed = True
            await ctx.send(f"✅ Removed `{launch_data['title']}` from tracking")
            break

    if not removed:
        await ctx.send(f"❌ Launch `{title}` not found in active launches")


@bot.command(name='listlaunches')
async def list_launches(ctx):
    """List all active launches"""
    if not active_launches:
        await ctx.send("📭 No active launches being tracked")
        return

    embed = discord.Embed(
        title="🚀 Active Launch Tracking",
        color=0x7c7cff,
        description="Currently tracked launches"
    )

    for launch_data in active_launches.values():
        launch_date = parse_launch_date(launch_data['date'], launch_data.get('exact_time'), launch_data['title'])
        countdown = get_countdown_string(launch_date)

        embed.add_field(
            name=f"🚀 {launch_data['title']}",
            value=f"📅 {launch_data['date']}\n📍 {launch_data['location']}\n⏱️ {countdown}",
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name='bhelp')
async def help_command(ctx):
    """Show all bot commands"""
    embed = discord.Embed(
        title="🤖 Launch Bot Commands",
        color=0x7c7cff,
        description="Available commands for managing launch tracking"
    )

    embed.add_field(
        name="!check",
        value="Manually check for new launches from the website",
        inline=False
    )

    embed.add_field(
        name="!status",
        value="View bot status and tracking information",
        inline=False
    )

    embed.add_field(
        name="!setlaunch",
        value='Set a manual launch countdown\nUsage: `!setlaunch "Title" "November 28, 2025 13:00:00" "Location" "Description"`',
        inline=False
    )

    embed.add_field(
        name="!removelaunch",
        value="Remove a launch from tracking\nUsage: `!removelaunch Launch Title`",
        inline=False
    )

    embed.add_field(
        name="!listlaunches",
        value="List all currently tracked launches with countdowns",
        inline=False
    )

    embed.set_footer(text="StaticFire Launch Services • All times in UTC")
    await ctx.send(embed=embed)


# Run the bot
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)