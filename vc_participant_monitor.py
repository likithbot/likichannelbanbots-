"""
Telegram Voice Chat Participant Monitor (Userbot)

Monitors real-time join/leave events in Telegram Voice Chats (Group Calls).
Uses Telethon userbot + pytgcalls to join VC and listen to UpdateGroupCallParticipants.
Automatically bans users who join as channels and actual channels.

Copyright © 2026
Author: TASLIM A (taslim19)

This software is licensed under a proprietary license agreement.
See LICENSE file for full terms and conditions.

Requirements:
- User account (not bot) with API credentials
- Admin rights in the target group (to join VC and ban users)
- pytgcalls v2.x installed
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from telethon import TelegramClient, events, functions
from telethon.tl.types import (
    UpdateGroupCallParticipants,
    GroupCallParticipant,
    PeerUser,
    PeerChannel,
    Channel,
    InputGroupCall,
    InputPeerUser,
    InputPeerChannel,
    ChatBannedRights
)
from telethon.errors import ChatAdminRequiredError, UserNotParticipantError
import json
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# pytgcalls imports (GitHub version)
# Note: PyPI version has compatibility issues with Python 3.10+ and deprecated imports
# Use GitHub version: pip install git+https://github.com/pytgcalls/pytgcalls.git
PYTGCALLS_AVAILABLE = False
PyTgCalls = None
AudioPiped = None

try:
    from pytgcalls import PyTgCalls
    # Try different import paths for AudioPiped (GitHub version may have different structure)
    try:
        from pytgcalls.types.input_stream import AudioPiped
    except ImportError:
        try:
            from pytgcalls.types import AudioPiped
        except ImportError:
            # AudioPiped might not be needed if we're only listening to raw updates
            AudioPiped = None
            logger.warning("AudioPiped not available - VC joining will be disabled")
    PYTGCALLS_AVAILABLE = True
    logger.info("✅ pytgcalls imported successfully (GitHub version)")
except ImportError as e:
    PYTGCALLS_AVAILABLE = False
    logger.warning(f"pytgcalls not available: {e}")
    logger.warning("VC joining will be disabled, but raw update monitoring will still work")
    logger.warning("Install GitHub version: pip install git+https://github.com/pytgcalls/pytgcalls.git")


class VoiceChatParticipantMonitor:
    """
    Monitors Telegram Voice Chat participants using Telethon userbot + pytgcalls.
    """
    
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_string: str,
        chat_id: int
    ):
        """
        Initialize the monitor.
        
        Args:
            api_id: Telegram API ID (from https://my.telegram.org/apps)
            api_hash: Telegram API Hash
            session_string: Telethon string session (userbot account)
            chat_id: Target group chat ID where VC is located
        """
        if not api_id or not api_hash:
            raise ValueError("api_id and api_hash are required")
        if not session_string:
            raise ValueError("session_string is required (userbot account)")
        if not chat_id:
            raise ValueError("chat_id is required")
        
        # Initialize Telethon client with string session
        from telethon.sessions import StringSession
        session = StringSession(session_string)
        self.client = TelegramClient(
            session,
            api_id,
            api_hash
        )
        
        self.chat_id = chat_id
        self.pytgcalls = None
        self.vc_connected = False
        
        # New features
        self.start_time = datetime.now(timezone.utc)
        self.authed_chats = {chat_id}
        self.heartbeat_task = None
        self.auth_file = "authed_chats.json"
        
        # Load extra authed chats if file exists
        self._load_authed_chats()
        
        logger.info(f"Initialized monitor for chat_id: {chat_id}")
        logger.info(f"Total authed chats: {self.authed_chats}")
    
    async def start(self):
        """Start the userbot and connect to voice chat."""
        # Connect Telethon client
        await self.client.start()
        logger.info("✅ Telethon client connected")
        
        # Register raw update handler
        self.client.add_event_handler(
            self.handle_group_call_participant_update,
            events.Raw(types=UpdateGroupCallParticipants)
        )
        logger.info("✅ Registered UpdateGroupCallParticipants handler")
        
        # Register command handlers
        self.client.add_event_handler(
            self.handle_commands,
            events.NewMessage(pattern=r"^\.(ping|auth|listauth)", outgoing=True)
        )
        logger.info("✅ Registered command handlers (.ping, .auth, .listauth)")
        
        # Start heartbeat loop
        self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        logger.info("✅ Started heartbeat polling loop (10s interval)")
        
        # Initialize pytgcalls (optional - for joining VC)
        if PYTGCALLS_AVAILABLE:
            try:
                self.pytgcalls = PyTgCalls(self.client)
                await self.pytgcalls.start()
                logger.info("✅ PyTgCalls client started")
                
                # Optionally join the voice chat (requires AudioPiped)
                await self.join_voice_chat()
            except Exception as e:
                logger.warning(f"Failed to initialize pytgcalls: {e}")
                logger.warning("Continuing without VC connection - raw updates will still work")
                self.pytgcalls = None
        else:
            logger.info("ℹ️  pytgcalls not available - monitoring via raw updates only")
            logger.info("   (You can still receive participant events without joining VC)")
        
        logger.info("🚀 Monitor is running. Listening for VC participants...")
        logger.info("Press Ctrl+C to stop")
        
        # Keep running
        await self.client.run_until_disconnected()
    
    async def join_voice_chat(self) -> bool:
        """
        Join the group Voice Chat using pytgcalls.
        
        Returns:
            True if joined successfully, False otherwise
        """
        if not PYTGCALLS_AVAILABLE or not self.pytgcalls:
            logger.error("pytgcalls not available - cannot join VC")
            return False
        
        try:
            # Get the group call info
            full_chat = await self.client.get_entity(self.chat_id)
            if not hasattr(full_chat, 'full_chat'):
                logger.warning(f"Chat {self.chat_id} is not a full chat")
                return False
            
            full_chat_obj = full_chat.full_chat
            if not hasattr(full_chat_obj, 'call') or not full_chat_obj.call:
                logger.warning(f"No active group call in chat {self.chat_id}")
                return False
            
            group_call = full_chat_obj.call
            group_call_id = getattr(group_call, 'id', None)
            group_call_access_hash = getattr(group_call, 'access_hash', None)
            
            if not group_call_id:
                logger.warning("Group call ID not found")
                return False
            
            # Join the group call using pytgcalls
            # Using a silent audio stream to stay connected (if AudioPiped is available)
            if AudioPiped is None:
                logger.warning("AudioPiped not available - cannot join VC with audio stream")
                logger.info("Raw update monitoring will still work without joining VC")
                return False
            
            await self.pytgcalls.join_group_call(
                self.chat_id,
                AudioPiped("http://docs.evostream.com/sample_content/assets/sintel1m720p.mp4")
            )
            
            self.vc_connected = True
            logger.info(
                f"✅ Joined Voice Chat in chat {self.chat_id} "
                f"(Group Call ID: {group_call_id})"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to join Voice Chat: {e}")
            self.vc_connected = False
            return False
    
    async def get_user_id_from_participant(
        self,
        participant: GroupCallParticipant
    ) -> Optional[int]:
        """
        Extract user_id from a GroupCallParticipant.
        
        Args:
            participant: GroupCallParticipant object
            
        Returns:
            user_id if found, None otherwise
        """
        try:
            # Check participant.peer (the actual participant)
            if hasattr(participant, 'peer') and participant.peer:
                if isinstance(participant.peer, PeerUser):
                    return participant.peer.user_id
                elif isinstance(participant.peer, PeerChannel):
                    # This is a channel, not a user
                    logger.debug(f"Participant is a channel: {participant.peer.channel_id}")
                    return None
            
            # Check participant.join_as (what they joined as)
            if hasattr(participant, 'join_as') and participant.join_as:
                if isinstance(participant.join_as, PeerUser):
                    return participant.join_as.user_id
                elif isinstance(participant.join_as, PeerChannel):
                    # User joined AS a channel
                    logger.debug(f"User joined as channel: {participant.join_as.channel_id}")
                    # Try to get the actual user from participant.peer
                    if hasattr(participant, 'peer') and isinstance(participant.peer, PeerUser):
                        return participant.peer.user_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting user_id: {e}")
            return None
    
    async def ban_user_from_voice_chat(
        self,
        user_id: int,
        group_call_id: int,
        group_call_access_hash: int,
        channel_id: Optional[int] = None,
        participant: Optional[GroupCallParticipant] = None
    ) -> bool:
        """
        Ban/remove a user from the voice chat.
        Optimized to avoid expensive entity resolution that causes flood waits.
        
        Args:
            user_id: The user ID to ban
            group_call_id: Group call ID
            group_call_access_hash: Group call access hash
            channel_id: Channel ID if user joined as channel (for logging)
            participant: GroupCallParticipant object (optional, for extracting access_hash)
            
        Returns:
            True if ban was successful, False otherwise
        """
        try:
            # Extract access_hash from participant if available (avoids entity lookup)
            user_access_hash = None
            if participant:
                try:
                    # Try to extract from participant.peer if it's a PeerUser with access_hash
                    peer = getattr(participant, 'peer', None)
                    if isinstance(peer, PeerUser) and hasattr(peer, 'access_hash'):
                        user_access_hash = peer.access_hash
                        logger.debug(f"Extracted access_hash {user_access_hash} from participant peer")
                except Exception:
                    pass
            
            # Method 1: Try EditBannedRequest with PeerUser directly FIRST (no entity resolution needed)
            # This is fastest and avoids flood waits from entity resolution
            try:
                banned_rights = ChatBannedRights(
                    until_date=None,  # Permanent ban
                    view_messages=True,  # Ban from viewing messages (removes from VC)
                    send_messages=True,
                    send_media=True,
                    send_stickers=True,
                    send_gifs=True,
                    send_games=True,
                    send_inline=True,
                    embed_links=True,
                    send_polls=True,
                    change_info=True,
                    invite_users=True,
                    pin_messages=True,
                )
                await self.client(functions.channels.EditBannedRequest(
                    channel=self.chat_id,
                    participant=PeerUser(user_id=user_id),
                    banned_rights=banned_rights
                ))
                logger.info(f"✅ Banned user {user_id} using EditBannedRequest with PeerUser (direct)")
                return True
            except Exception as e1:
                logger.debug(f"EditBannedRequest with PeerUser failed: {e1}")
            
            # Method 2: Try EditGroupCallParticipantRequest to remove from VC (might need access_hash)
            # This can remove them from the VC even if we can't ban them from the group
            if user_access_hash:  # Only try if we have access_hash
                try:
                    result = await self.client(functions.phone.EditGroupCallParticipantRequest(
                        call=InputGroupCall(
                            id=group_call_id,
                            access_hash=group_call_access_hash
                        ),
                        participant=InputPeerUser(
                            user_id=user_id,
                            access_hash=user_access_hash
                        ),
                        muted=True,
                        video_stopped=None,  # video_stopped=True causes VIDEO_STOP_FORBIDDEN
                        presentation_paused=None
                    ))
                    logger.warning(f"⚠️  Muted user {user_id} in VC (may not fully remove - EditBannedRequest preferred)")
                    # Return False because muting alone doesn't fully remove them
                    return False
                except Exception as e2:
                    logger.debug(f"EditGroupCallParticipantRequest failed: {e2}")
            
            # Method 3: Try entity resolution only if direct methods failed (avoid flood waits)
            try:
                user_entity = await self.client.get_entity(PeerUser(user_id=user_id))
                await self.client.edit_permissions(
                    self.chat_id,
                    user_entity,
                    view_messages=False,  # This effectively bans them
                    send_messages=False,
                    send_media=False,
                    send_stickers=False,
                    send_gifs=False,
                    send_games=False,
                    send_inline=False,
                    embed_links=False,
                    send_polls=False,
                    change_info=False,
                    invite_users=False,
                    pin_messages=False,
                )
                logger.info(f"✅ Restricted user {user_id} using edit_permissions")
                return True
            except ChatAdminRequiredError:
                logger.error(f"Bot needs admin permissions in chat {self.chat_id} to ban users")
                return False
            except UserNotParticipantError:
                logger.warning(f"User {user_id} is not a participant in chat {self.chat_id}")
                return False
            except Exception as e3:
                logger.debug(f"edit_permissions failed: {e3}")
            
            logger.warning(f"⚠️  All ban methods failed for user {user_id}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in ban_user_from_voice_chat: {e}")
            return False
    
    async def ban_channel_from_voice_chat(
        self,
        channel_id: int,
        group_call_id: int,
        group_call_access_hash: int,
        channel_access_hash: Optional[int] = None,
        participant: Optional[GroupCallParticipant] = None
    ) -> bool:
        """
        Ban/remove a channel from the voice chat.
        Optimized to avoid expensive entity resolution that causes flood waits.
        
        Args:
            channel_id: The channel ID to ban
            group_call_id: Group call ID
            group_call_access_hash: Group call access hash
            channel_access_hash: Channel access hash (optional, extracted from participant if available)
            participant: GroupCallParticipant object (optional, for extracting access_hash)
            
        Returns:
            True if ban was successful, False otherwise
        """
        try:
            # Extract access_hash from participant if available (avoids entity lookup)
            if channel_access_hash is None and participant:
                try:
                    # Try to extract from participant.peer if it's a PeerChannel with access_hash
                    peer = getattr(participant, 'peer', None)
                    if isinstance(peer, PeerChannel) and hasattr(peer, 'access_hash'):
                        channel_access_hash = peer.access_hash
                        logger.debug(f"Extracted access_hash {channel_access_hash} from participant peer")
                except Exception:
                    pass
            
            # Method 1: Try EditBannedRequest with PeerChannel directly FIRST (no entity resolution needed)
            # This is fastest and avoids flood waits from entity resolution
            try:
                banned_rights = ChatBannedRights(
                    until_date=None,  # Permanent ban
                    view_messages=True,  # Ban from viewing messages (removes from VC)
                    send_messages=True,
                    send_media=True,
                    send_stickers=True,
                    send_gifs=True,
                    send_games=True,
                    send_inline=True,
                    embed_links=True,
                    send_polls=True,
                    change_info=True,
                    invite_users=True,
                    pin_messages=True,
                )
                await self.client(functions.channels.EditBannedRequest(
                    channel=self.chat_id,
                    participant=PeerChannel(channel_id=channel_id),
                    banned_rights=banned_rights
                ))
                logger.info(f"✅ Banned channel {channel_id} using EditBannedRequest with PeerChannel (direct)")
                return True
            except Exception as e1:
                logger.debug(f"EditBannedRequest with PeerChannel failed: {e1}")
            
            # Method 2: Try EditGroupCallParticipantRequest to mute in VC (might need access_hash)
            # Note: This only mutes, doesn't fully remove, but it's better than nothing
            try:
                result = await self.client(functions.phone.EditGroupCallParticipantRequest(
                    call=InputGroupCall(
                        id=group_call_id,
                        access_hash=group_call_access_hash
                    ),
                    participant=InputPeerChannel(
                        channel_id=channel_id,
                        access_hash=channel_access_hash if channel_access_hash else 0
                    ),
                    muted=True,
                    video_stopped=None,  # video_stopped=True causes VIDEO_STOP_FORBIDDEN
                    presentation_paused=None
                ))
                logger.warning(f"⚠️  Muted channel {channel_id} in VC (may not fully remove - EditBannedRequest preferred)")
                # Return False because muting alone doesn't fully remove them
                return False
            except Exception as e2:
                logger.debug(f"EditGroupCallParticipantRequest failed: {e2}")
            
            # Method 3: Try entity resolution only if direct methods failed (avoid flood waits)
            # Only try quick entity lookups, skip iter_participants (causes floods)
            channel_entity = None
            
            # Try 1: Direct entity lookup (quick, but may fail)
            try:
                channel_entity = await self.client.get_entity(PeerChannel(channel_id=channel_id))
                logger.debug(f"Got channel entity via direct lookup")
            except Exception as e3:
                logger.debug(f"Direct entity lookup failed: {e3}")
            
            # Try 2: GetFullChannelRequest (skip iter_participants - causes flood waits)
            if not channel_entity:
                try:
                    full_channel = await self.client(functions.channels.GetFullChannelRequest(
                        channel=PeerChannel(channel_id=channel_id)
                    ))
                    if hasattr(full_channel, 'chats') and full_channel.chats:
                        channel_entity = full_channel.chats[0]
                        logger.debug(f"Got channel entity via GetFullChannelRequest")
                except Exception as e4:
                    logger.debug(f"GetFullChannelRequest failed: {e4}")
            
            # If we got entity, try edit_permissions
            if channel_entity:
                try:
                    await self.client.edit_permissions(
                        self.chat_id,
                        channel_entity,
                        view_messages=False,  # This effectively bans them
                        send_messages=False,
                        send_media=False,
                        send_stickers=False,
                        send_gifs=False,
                        send_games=False,
                        send_inline=False,
                        embed_links=False,
                        send_polls=False,
                        change_info=False,
                        invite_users=False,
                        pin_messages=False,
                    )
                    logger.info(f"✅ Restricted channel {channel_id} using edit_permissions")
                    return True
                except Exception as e5:
                    logger.debug(f"edit_permissions failed: {e5}")
            
            logger.warning(f"⚠️  All ban methods failed for channel {channel_id}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in ban_channel_from_voice_chat: {e}")
            return False

    def _load_authed_chats(self):
        """Load authed chats from JSON file."""
        if os.path.exists(self.auth_file):
            try:
                with open(self.auth_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.authed_chats.update(data)
            except Exception as e:
                logger.error(f"Error loading authed_chats: {e}")

    def _save_authed_chats(self):
        """Save authed chats to JSON file."""
        try:
            with open(self.auth_file, "w") as f:
                json.dump(list(self.authed_chats), f)
        except Exception as e:
            logger.error(f"Error saving authed_chats: {e}")

    async def _reply(self, event, text):
        """Helper to reply to a command. Edits if outgoing, responds otherwise."""
        try:
            if event.out:
                await event.edit(text)
            else:
                await event.respond(text)
        except Exception:
            await event.respond(text)

    async def handle_commands(self, event):
        """Handle userbot commands (.ping, .auth, .listauth)."""
        if not event.is_private and event.chat_id not in self.authed_chats:
            # Allow .auth anywhere to add new groups.
            pass

        cmd = event.pattern_match.group(1).lower()
        
        if cmd == "ping":
            uptime = datetime.now(timezone.utc) - self.start_time
            days = uptime.days
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
            
            await self._reply(event, f"**🏓 Pong!**\n**Uptime:** `{uptime_str}`\n**Status:** `Monitoring {len(self.authed_chats)} chats`")
            
        elif cmd == "auth":
            chat_id = event.chat_id
            if chat_id not in self.authed_chats:
                self.authed_chats.add(chat_id)
                self._save_authed_chats()
                await self._reply(event, f"**✅ Group Authorized!**\nNow monitoring Voice Chat in this group (`{chat_id}`).")
                logger.info(f"Authorized new group: {chat_id}")
            else:
                await self._reply(event, f"**ℹ️ This group is already authorized.**")

        elif cmd == "listauth":
            text = "**📜 Authorized Groups:**\n\n"
            for c_id in list(self.authed_chats):
                try:
                    entity = await self.client.get_entity(c_id)
                    title = getattr(entity, 'title', 'Unknown Chat')
                    text += f"• **{title}**: `{c_id}`\n"
                except Exception:
                    text += f"• **Unknown**: `{c_id}`\n"
            
            await self._reply(event, text)

    async def heartbeat_loop(self):
        """
        Background loop to poll participants every 10 seconds.
        This provides a fallback for delayed push updates.
        """
        while True:
            try:
                # Iterate over all authed chats
                for chat_id in list(self.authed_chats):
                    try:
                        # Get full chat to find the call
                        full_chat = await self.client(functions.channels.GetFullChannelRequest(channel=chat_id))
                        full_chat_obj = full_chat.full_chat
                        
                        if hasattr(full_chat_obj, 'call') and full_chat_obj.call:
                            call = full_chat_obj.call
                            
                            # Resiliently find the correct GetGroupParticipantsRequest
                            GetParticipants = getattr(functions.phone, 'GetGroupParticipantsRequest', 
                                              getattr(functions.phone, 'GetGroupCallParticipantsRequest', None))
                            
                            if GetParticipants:
                                try:
                                    participants_res = await self.client(GetParticipants(
                                        call=call,
                                        ids=[],
                                        sources=[],
                                        offset='',
                                        limit=100
                                    ))
                                    
                                    if participants_res and hasattr(participants_res, 'participants'):
                                        logger.debug(f"Heartbeat: Polling {len(participants_res.participants)} participants in {chat_id}")
                                        await self.process_participants(
                                            participants=participants_res.participants,
                                            group_call_id=call.id,
                                            group_call_access_hash=call.access_hash
                                        )
                                except Exception as poll_err:
                                    logger.debug(f"Heartbeat: Polling error in {chat_id}: {poll_err}")
                            else:
                                logger.error("Heartbeat: API function to get participants not found in Telethon")
                    except Exception as e:
                        logger.debug(f"Heartbeat: Error polling chat {chat_id}: {e}")
                
                # Sleep for 10 seconds
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat_loop: {e}")
                await asyncio.sleep(30) # Sleep longer on error

    async def handle_group_call_participant_update(self, event: events.Raw):
        """Handle UpdateGroupCallParticipants raw update."""
        try:
            update = event
            if not isinstance(update, UpdateGroupCallParticipants):
                return
            
            group_call = update.call
            if not group_call:
                return
            
            group_call_id = getattr(group_call, 'id', None)
            group_call_access_hash = getattr(group_call, 'access_hash', None)
            if not group_call_id:
                return
            
            participants = update.participants or []
            if not participants:
                return
            
            await self.process_participants(participants, group_call_id, group_call_access_hash)
            
        except Exception as e:
            logger.error(f"Error handling group call update: {e}")

    async def process_participants(
        self, 
        participants: list[GroupCallParticipant], 
        group_call_id: int, 
        group_call_access_hash: int
    ):
        """Shared logic to process and ban participants."""
        for participant in participants:
            try:
                participant_peer = getattr(participant, 'peer', None)
                participant_join_as = getattr(participant, 'join_as', None)

                # 1. Screen/Camera Sharing Detection (Mute instead of Ban)
                has_presentation = getattr(participant, 'presentation', None)
                has_video = getattr(participant, 'video', None)

                if has_presentation or has_video:
                    if participant_peer:
                        share_type = "Screen share" if has_presentation else "Camera share"
                        logger.warning(f"📢 {share_type} detected from {participant_peer}! Muting...")
                        try:
                            # Convert peer to InputPeer for the API call
                            input_peer = None
                            if isinstance(participant_peer, PeerUser):
                                try:
                                    entity = await self.client.get_entity(participant_peer.user_id)
                                    input_peer = await self.client.get_input_entity(entity)
                                except Exception:
                                    input_peer = InputPeerUser(user_id=participant_peer.user_id, access_hash=0)
                            elif isinstance(participant_peer, PeerChannel):
                                try:
                                    entity = await self.client.get_entity(participant_peer.channel_id)
                                    input_peer = await self.client.get_input_entity(entity)
                                except Exception:
                                    input_peer = InputPeerChannel(channel_id=participant_peer.channel_id, access_hash=0)
                            
                            if input_peer:
                                # Strategy 1: Mute + stop video/pause presentation
                                try:
                                    await self.client(functions.phone.EditGroupCallParticipantRequest(
                                        call=InputGroupCall(
                                            id=group_call_id,
                                            access_hash=group_call_access_hash
                                        ),
                                        participant=input_peer,
                                        muted=True,
                                        video_stopped=True if has_video else None,
                                        presentation_paused=True if has_presentation else None
                                    ))
                                    res_msg = "paused presentation" if has_presentation else "stopped video"
                                    logger.info(f"✅ Muted and {res_msg} for {participant_peer}")
                                except Exception as e1:
                                    logger.warning(f"Strategy 1 (mute+video/presentation) failed: {e1}")
                                    # Strategy 2: Just mute
                                    try:
                                        await self.client(functions.phone.EditGroupCallParticipantRequest(
                                            call=InputGroupCall(
                                                id=group_call_id,
                                                access_hash=group_call_access_hash
                                            ),
                                            participant=input_peer,
                                            muted=True,
                                            video_stopped=None,
                                            presentation_paused=None
                                        ))
                                        logger.info(f"✅ Muted (without pause/stop) for {participant_peer}")
                                    except Exception as e2:
                                        logger.warning(f"Strategy 2 (mute only) also failed: {e2}")
                        except Exception as e:
                            logger.warning(f"Failed to mute share: {e}")

                # 2. Existing Channel Banning Logic
                is_user_joining_as_channel = (
                    participant_peer and isinstance(participant_peer, PeerUser) and
                    participant_join_as and isinstance(participant_join_as, PeerChannel)
                )
                is_actual_channel = (
                    participant_peer and isinstance(participant_peer, PeerChannel)
                )
                
                if not is_user_joining_as_channel and not is_actual_channel:
                    continue

                # Extract IDs
                channel_id = None
                if is_user_joining_as_channel:
                    channel_id = participant_join_as.channel_id
                elif is_actual_channel:
                    channel_id = participant_peer.channel_id
                
                user_id = await self.get_user_id_from_participant(participant)
                
                should_ban = False
                ban_target_id = None
                ban_target_type = None
                
                if is_user_joining_as_channel and user_id and channel_id:
                    should_ban = True
                    ban_target_id = user_id
                    ban_target_type = "user_joined_as_channel"
                elif is_actual_channel and channel_id:
                    should_ban = True
                    ban_target_id = channel_id
                    ban_target_type = "actual_channel"
                
                if should_ban and group_call_access_hash:
                    # Proceed with banning
                    if ban_target_type == "user_joined_as_channel":
                        logger.warning(f"🚫 BANNING user {ban_target_id} (joined as channel {channel_id})")
                        await self.ban_user_from_voice_chat(
                            user_id=ban_target_id,
                            group_call_id=group_call_id,
                            group_call_access_hash=group_call_access_hash,
                            channel_id=channel_id,
                            participant=participant
                        )
                    elif ban_target_type == "actual_channel":
                        logger.warning(f"🚫 BANNING channel {ban_target_id}")
                        await self.ban_channel_from_voice_chat(
                            channel_id=ban_target_id,
                            group_call_id=group_call_id,
                            group_call_access_hash=group_call_access_hash,
                            participant=participant
                        )
                
                # Print info for banned ones
                timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                print(f"\n{'='*60}")
                print(f"🚫 BANNED: {ban_target_type.upper()}")
                print(f"Target ID: {ban_target_id}")
                if channel_id: print(f"Channel ID: {channel_id}")
                print(f"Timestamp: {timestamp}")
                print(f"{'='*60}\n")

            except Exception as e:
                logger.error(f"Error processing participant: {e}")
    
    async def stop(self):
        """Stop the monitor and disconnect."""
        try:
            # Cancel heartbeat task
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    logger.info("Heartbeat loop cancelled.")

            # Leave VC if connected
            if self.pytgcalls and self.vc_connected:
                try:
                    await self.pytgcalls.leave_group_call(self.chat_id)
                    logger.info("Left voice chat")
                except Exception as e:
                    logger.debug(f"Error leaving group call: {e}")
            
            # Stop pytgcalls (if method exists - GitHub version may not have it)
            if self.pytgcalls:
                try:
                    if hasattr(self.pytgcalls, 'stop'):
                        await self.pytgcalls.stop()
                        logger.info("Stopped PyTgCalls")
                    else:
                        logger.debug("PyTgCalls stop() method not available (GitHub version)")
                except Exception as e:
                    logger.debug(f"Error stopping PyTgCalls: {e}")
            
            # Disconnect Telethon client
            await self.client.disconnect()
            logger.info("Disconnected Telethon client")
            
        except Exception as e:
            logger.error(f"Error stopping monitor: {e}")


async def main():
    """
    Main entry point.
    Configure your credentials here or load from environment variables.
    """
    import os
    from dotenv import load_dotenv
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Configuration
    API_ID = os.getenv('API_ID')
    API_HASH = os.getenv('API_HASH')
    SESSION_STRING = os.getenv('SESSION_STRING')
    CHAT_ID = os.getenv('CHAT_ID') or os.getenv('CHANNEL_ID')
    
    # Validate configuration
    if not API_ID or not API_HASH:
        logger.error(
            "Please set API_ID, API_HASH, and CHAT_ID (or CHANNEL_ID) as environment variables.\n"
            "Local: Add to .env file | Heroku: heroku config:set API_ID=... API_HASH=... CHAT_ID=...\n"
            "Get them from https://my.telegram.org/apps"
        )
        return
    
    if not SESSION_STRING:
        logger.error(
            "Please set SESSION_STRING as environment variable.\n"
            "Local: Add to .env file | Heroku: heroku config:set SESSION_STRING=...\n"
            "Generate a Telethon string session using generate_session.py"
        )
        return
    
    if not CHAT_ID:
        logger.error(
            "Please set CHAT_ID as environment variable.\n"
            "Local: Add to .env file | Heroku: heroku config:set CHAT_ID=...\n"
            "This is the group chat ID where the Voice Chat is located."
        )
        return
    
    try:
        API_ID = int(API_ID)
        CHAT_ID = int(CHAT_ID)
    except ValueError:
        logger.error("API_ID and CHAT_ID must be numbers")
        return
    
    logger.info("Starting Voice Chat Participant Monitor...")
    logger.info(f"Target chat ID: {CHAT_ID}")
    
    # Initialize and start the monitor
    monitor = VoiceChatParticipantMonitor(
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
        chat_id=CHAT_ID
    )
    
    try:
        await monitor.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())

