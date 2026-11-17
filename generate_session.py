"""
Generate Telethon String Session for Userbot

Run this script to generate a string session for your user account.
This session will be used to authenticate as a userbot (not bot).

Copyright © 2026
Author: TASLIM A (taslim19)

This software is licensed under a proprietary license agreement.
See LICENSE file for full terms and conditions.
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

async def generate_session():
    """Generate and print a Telethon string session."""
    print("=" * 60)
    print("Telethon String Session Generator")
    print("=" * 60)
    print()
    print("You need to get your API credentials from:")
    print("https://my.telegram.org/apps")
    print()
    
    # Get API credentials
    api_id = input("Enter your API ID: ").strip()
    api_hash = input("Enter your API Hash: ").strip()
    
    if not api_id or not api_hash:
        print("Error: API ID and API Hash are required")
        return
    
    try:
        api_id = int(api_id)
    except ValueError:
        print("Error: API ID must be a number")
        return
    
    # Create a new session
    session = StringSession()
    client = TelegramClient(session, api_id, api_hash)
    
    print()
    print("Connecting to Telegram...")
    print("You will need to authorize this session:")
    print("1. Enter your phone number (with country code, e.g., +1234567890)")
    print("2. Enter the verification code sent to your Telegram")
    print("3. If you have 2FA enabled, enter your password")
    print()
    
    try:
        await client.start()
        
        # Get the string session
        session_string = client.session.save()
        
        print()
        print("=" * 60)
        print("✅ Session generated successfully!")
        print("=" * 60)
        print()
        print("Add this to your .env file as SESSION_STRING:")
        print()
        print(f"SESSION_STRING={session_string}")
        print()
        print("=" * 60)
        print()
        print("⚠️  Keep this session string SECRET!")
        print("   Anyone with this string can access your account.")
        print()
        
    except Exception as e:
        print(f"Error generating session: {e}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(generate_session())

