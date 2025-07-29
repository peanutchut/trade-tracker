import discord
import os
from dotenv import load_dotenv
import gspread
import re
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from hypercorn.asyncio import serve
from hypercorn.config import Config
import asyncio

# ✅ Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_NAME = "trade-signals"

# ✅ Google Sheets setup
gc = gspread.service_account(filename='credentialscopy.json')
sheet = gc.open("Demo Google Sheet").sheet1  # Update if sheet name differs

# ✅ Discord client setup
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ✅ FastAPI for health checks
app = FastAPI()

@app.get("/")
async def root():
    return JSONResponse(content={"message": "Bot is running!"})

# ✅ Parse trade message (BTO or STC)
def parse_trade(message: str):
    """
    Expected format:
    Trade-101#BTO AAPL 08/15 200C@3.5(2 contracts)
    """
    pattern = re.compile(
        r'#(?P<action>BTO|STC)\s+'
        r'(?P<ticker>[A-Z]+)\s+'
        r'(?P<expiry>\d{2}/\d{2}(?:/\d{4})?)\s+'
        r'(?P<strike>\d+)(?P<cp>[CP])@'
        r'(?P<price>[\d.]+)\('
        r'(?P<contracts>\d+)\s+contracts'
    )

    match = pattern.search(message)
    if not match:
        return None

    data = match.groupdict()
    data["strike"] = int(data["strike"])
    data["price"] = float(data["price"])
    data["contracts"] = int(data["contracts"])
    data["trade_enter"] = datetime.now().strftime("%m/%d")
    data["trade_exit"] = ""
    return data

# ✅ Add a new trade (BTO) to Google Sheets
def add_trade(data):
    avg_cost_option = f"${data['price']:.2f}"
    total_cost = data["price"] * data["contracts"] * 100  # Each contract = 100 shares

    row_values = [
        data["ticker"], data["trade_enter"], data["trade_exit"],
        data["expiry"], data["strike"], data["cp"],
        data["contracts"], data["contracts"],  # Initial & current contracts
        avg_cost_option, f"${total_cost:,.2f}", f"${total_cost:,.2f}",
        "0.00%", "$0.00", "Open", ""
    ]
    sheet.append_row(row_values)

# ✅ Close an existing trade (STC) and update Google Sheets
def close_trade(data):
    all_rows = sheet.get_all_values()[1:]  # Skip header row
    for idx, row in enumerate(reversed(all_rows), start=2):
        if row[0] == data["ticker"] and row[13].upper() == "OPEN":
            row_num = len(all_rows) - idx + 2
            open_price = float(row[8].replace("$", ""))
            contracts = int(row[7])
            market_value = data["price"] * contracts * 100
            initial_cost = open_price * contracts * 100
            gain = market_value - initial_cost
            pct_gain = (gain / initial_cost) * 100 if initial_cost > 0 else 0

            # Update cells
            updates = {
                "C": datetime.now().strftime("%m/%d"),  # Trade Exit
                "K": f"${market_value:,.2f}",          # Market Value
                "L": f"{pct_gain:.2f}%",              # % Gain
                "M": f"${gain:,.2f}",                 # $ Gain
                "N": "Closed"                         # Status
            }
            for col, val in updates.items():
                sheet.update(f"{col}{row_num}", val)
            return gain, pct_gain
    return None, None

# ✅ Discord Events
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.name == CHANNEL_NAME:
        trade_data = parse_trade(message.content)
        if trade_data:
            if trade_data["action"] == "BTO":
                add_trade(trade_data)
                await message.channel.send(
                    f"✅ New trade added: {trade_data['ticker']} {trade_data['strike']}{trade_data['cp']} @ ${trade_data['price']:.2f}"
                )
            elif trade_data["action"] == "STC":
                gain, pct_gain = close_trade(trade_data)
                if gain is not None:
                    await message.channel.send(
                        f"✅ Trade closed: {trade_data['ticker']} @ ${trade_data['price']:.2f} | Gain: {pct_gain:.2f}% (${gain:,.2f})"
                    )
                else:
                    await message.channel.send(f"⚠ No matching open trade found for {trade_data['ticker']}.")
        else:
            await message.channel.send(
                "❌ Invalid format.\nUse:\n`Trade-101#BTO AAPL 08/15 200C@3.5(2 contracts)`\nExample Close:\n`Trade-102#STC AAPL 08/15 200C@5(2 contracts)`"
            )

# ✅ Run both bot and FastAPI
async def main():
    config = Config()
    config.bind = ["0.0.0.0:8000"]

    await asyncio.gather(
        client.start(DISCORD_TOKEN),
        serve(app, config)
    )

if __name__ == "__main__":
    asyncio.run(main())
