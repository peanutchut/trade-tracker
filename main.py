import discord
import os
from dotenv import load_dotenv
import gspread
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from hypercorn.asyncio import serve
from hypercorn.config import Config
import asyncio

# Load env variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_NAME = "trade-signals"

# Setup Google Sheets
gc = gspread.service_account(filename='credentialscopy.json')
sheet = gc.open("Trade Tracker Test").sheet1

# Setup Discord client
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Setup FastAPI app
app = FastAPI()

@app.get("/")
async def root():
    return JSONResponse(content={"message": "Bot is running!"})

# Parse trade message
def parse_trade(message):
    parts = message.strip().split()
    if len(parts) == 5 and parts[0] in ["BUY", "SELL"] and "@" in parts:
        action = parts[0]
        ticker = parts[1]
        strike = parts[2]
        price = parts[4]
        return [str(datetime.now()), action, ticker, strike, price]
    return None

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    print(f"Received message: {message.content} in channel: {message.channel.name}")
    if message.author == client.user:
        return

    if message.channel.name == CHANNEL_NAME:
        trade = parse_trade(message.content)
        if trade:
            sheet.append_row(trade)
            await message.channel.send(f"Nice Trade recorded: {trade[1]} {trade[2]} {trade[3]} @ {trade[4]}")
        else:
            await message.channel.send("Invalid format. Use: [BUY/SELL] + [TICKER] + [##C] + @ + [PRICE]")

# Run bot + server
async def main():
    config = Config()
    config.bind = ["0.0.0.0:8000"]

    await client.login(DISCORD_TOKEN)
    await asyncio.gather(
        client.connect(),
        serve(app, config)
    )

if __name__ == "__main__":
    asyncio.run(main())
