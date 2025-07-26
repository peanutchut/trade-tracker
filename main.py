import discord
import os
from dotenv import load_dotenv
import gspread
from datetime import datetime

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_NAME = "trade-signals"

gc = gspread.service_account(filename='/Users/evanarumbaka/Desktop/DISCORD_BOT/credentialscopy.json')
sheet = gc.open("Trade Tracker Test").sheet1

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def parse_trade(message): # NEED TO TALK TO SHANI MAMA ABOUT THIS AND MAKE CHANGES
    parts = message.strip().split()
    if len(parts) == 5 and parts[0] in ["BUY", "SELL"] and "@" in parts:
        action = parts[0]
        ticker = parts[1]
        strike = parts[2]
        price = parts[4]
        return [str(datetime.now()), action, ticker, strike, price]
    return None #CURRENTLY ITS BAREBONES, this is the format [(BUY/SELL) + (TICKER) + (##C (call)) + @ + (##PRICE)]

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
            await message.channel.send(f" Nice Trade recorded: {trade[1]} {trade[2]} {trade[3]} @ {trade[4]}") # when input reqs are met
        else:
            await message.channel.send(" Invalid format. Use: [BUY/ SELL] + [TICKER] + [##C (call)] + @ + [##PRICE]]") # when input reqs arent met

client.run(DISCORD_TOKEN)
