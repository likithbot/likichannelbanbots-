# Telegram Voice Chat Participant Monitor

Monitor real-time join/leave events in Telegram Voice Chats (Group Calls) using a Telethon userbot and pytgcalls.

## Features

- ✅ Join Telegram Voice Chats using pytgcalls
- ✅ Listen to real-time `UpdateGroupCallParticipants` raw updates
- ✅ Fetch and print `user_id` of members who join/leave
- ✅ Clean async code structure
- ✅ Compatible with pytgcalls v2.x

## Requirements

- **Python 3.10 or 3.11** (NOT 3.12 for pytgcalls)
- Telegram user account (not bot)
- **Optional**: Admin rights in the target group (only needed if joining VC via pytgcalls)
- API credentials from [my.telegram.org/apps](https://my.telegram.org/apps)

**Note**: You can monitor participants via raw updates **without** admin rights or pytgcalls!

## Installation

### ⚠️ Important: Python Version
- ✅ **Python 3.10** (Recommended)
- ✅ **Python 3.11** (Recommended)
- ❌ **Python 3.12** (Not supported by PyPI pytgcalls)

### Quick Install

1. Clone or download this repository

2. Install Telethon and python-dotenv:
```bash
pip install telethon>=1.34.0 python-dotenv>=1.0.0
```

3. **Optional**: Install pytgcalls from GitHub (for VC joining):
```bash
pip install git+https://github.com/pytgcalls/pytgcalls.git
```

**Note**: pytgcalls is **OPTIONAL**. The script works with raw updates only - you can monitor participants without joining the VC!

### Why Not PyPI pytgcalls?

The PyPI version (`pytgcalls[telethon]`) has critical issues:
- ❌ Deprecated imports (`AudioPiped` path changed)
- ❌ Python 3.12 incompatibility
- ❌ Dependency conflicts (`tgcalls==2.0.0` fails to install)
- ❌ Missing updates and fixes

**Solution**: Use GitHub version or skip pytgcalls entirely (raw updates work without it).

See [INSTALLATION.md](INSTALLATION.md) for detailed explanation.

3. Generate a Telethon string session:
```bash
python generate_session.py
```
This will prompt you for:
- API ID and API Hash (from https://my.telegram.org/apps)
- Your phone number
- Verification code
- 2FA password (if enabled)

4. Create a `.env` file:
```bash
cp .env.example .env
```

5. Edit `.env` and add your credentials:
```env
API_ID=12345678
API_HASH=your_api_hash_here
SESSION_STRING=your_session_string_here
CHAT_ID=-1001234567890
```

## Usage

Run the monitor:
```bash
python vc_participant_monitor.py
```

The bot will:
1. Connect to Telegram using your user account
2. **Listen for participant join/leave events** (via raw updates - works without joining VC)
3. **Optionally join the Voice Chat** (if pytgcalls is installed and you have admin rights)
4. Print user_id and event details to console

Press `Ctrl+C` to stop.

## How It Works

### Architecture

1. **Telethon Client**: Authenticates as a userbot using a string session
2. **Raw Updates Handler**: Listens to `UpdateGroupCallParticipants` events (core functionality)
3. **PyTgCalls (Optional)**: Joins the Voice Chat and maintains connection (optional feature)
4. **Participant Processing**: Extracts `user_id` from participant objects

**Key Point**: Raw updates work **without** pytgcalls! You don't need to join the VC to monitor participants.

### Event Flow

```
User joins/leaves VC
    ↓
Telegram sends UpdateGroupCallParticipants
    ↓
Telethon raw update handler catches it
    ↓
Extract user_id from GroupCallParticipant
    ↓
Print user_id and event details
```

### Key Components

- **`join_voice_chat()`**: Uses pytgcalls to join the VC with a silent audio stream
- **`handle_group_call_participant_update()`**: Processes raw updates and extracts user info
- **`get_user_id_from_participant()`**: Safely extracts user_id from participant object

## Limitations

### Admin Rights
- **For VC Joining**: The userbot account must be an **admin** with "Manage Voice Chats" permission
- **For Raw Updates**: **NOT REQUIRED** - you can monitor participants without admin rights or joining VC
- **Best Practice**: Use raw updates only (no admin needed, no pytgcalls needed)

### Privacy Settings
- **Private Groups**: The userbot must be a member of the group
- **Public Groups**: Can join if public, but still needs admin for VC
- **Channel VCs**: Works with channel voice chats too

### Technical Limitations
- **Real-time Only**: Only receives events while the bot is running and connected
- **No History**: Cannot fetch past participants, only live events
- **Join Detection**: Telegram doesn't explicitly mark "leave" events, so we infer from muted/video_stopped flags
- **Channel Participants**: Channels joining as participants are detected but user_id extraction may fail

### API Limitations
- **Rate Limits**: Telegram API has rate limits (usually not an issue for VC monitoring)
- **Connection Drops**: Network issues may disconnect the bot (auto-reconnect not implemented in this example)
- **VC Must Be Active**: The Voice Chat must be active/started for the bot to join

## Output Example

```
============================================================
🎤 Voice Chat Participant Event
============================================================
User ID: 123456789
Action: JOINED
Group Call ID: -1234567890123456789
Timestamp: 2026-01-01 12:00:00 UTC
Muted: False
Video Stopped: False
Presentation Paused: False
Volume: 100%
Can Self Unmute: True
============================================================
```

## Troubleshooting

### "pytgcalls not available"
- **This is OK!** Raw updates work without pytgcalls
- To install: `pip install git+https://github.com/pytgcalls/pytgcalls.git`
- **DO NOT** use PyPI version (`pytgcalls[telethon]`) - it's broken
- See [INSTALLATION.md](INSTALLATION.md) for details

### "No active group call"
- This only matters if you're trying to join VC via pytgcalls
- **Raw updates work without joining VC** - you'll still receive participant events
- If joining VC: bot must be admin with "Manage Voice Chats" permission

### "Could not join VC"
- Verify admin permissions
- Check if VC is active
- Ensure network connectivity

### "No participant events"
- **You don't need to join VC** - raw updates work independently
- Events only fire when users actually join/leave
- Make sure you're a member of the group (for private groups)
- Check that a Voice Chat is active in the group

## Security Notes

- ⚠️ **Keep your session string SECRET** - anyone with it can access your account
- ⚠️ **Never commit `.env` file** to version control
- ⚠️ **Use a separate Telegram account** for bot development if possible

## License

Free to use and modify.

