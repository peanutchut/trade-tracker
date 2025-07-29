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
sheet = gc.open("Demo Google Sheet").sheet1

# Setup Discord client
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Setup FastAPI app
app = FastAPI()


@app.get("/")
async def root():
    return JSONResponse(content={"message": "Bot is running!"})


# ✅ Parse trade message into structured format
def parse_trade(message):
    # Expected format: BUY AMD 11/11 12/20 145C 5 @ 865
    parts = message.strip().split()

    if len(parts) >= 8 and parts[0].upper() in ["BUY", "SELL"]:
        action = parts[0].upper()  # BUY or SELL
        ticker = parts[1].upper()  # e.g., AMD
        trade_enter = parts[2]  # e.g., 11/11
        exp_date = parts[3]  # e.g., 12/20
        strike_raw = parts[4]  # e.g., 145C
        strike = strike_raw[:-1]
        cp = strike_raw[-1].upper()  # C or P
        initial_contracts = parts[5]  # e.g., 5

        # ✅ Handle "@ price" safely
        try:
            at_index = parts.index("@")
            price = parts[at_index + 1]
        except ValueError:
            price = parts[-1]  # fallback if @ missing

        price_float = float(price) / 100  # convert to dollars
        total_cost = price_float * int(initial_contracts) * 100  # Option contracts are 100 shares each

        return {
            "action": action,
            "ticker": ticker,
            "trade_enter": trade_enter,
            "trade_exit": "",  # Initially blank
            "exp_date": exp_date,
            "strike": strike,
            "cp": cp,
            "initial_contracts": initial_contracts,
            "contracts": initial_contracts,
            "avg_cost_option": f"${price_float:.2f}",
            "$ avg_cost": f"${total_cost:,.2f}",
            "market_value": f"${total_cost:,.2f}",
            "% gain": "0.00%",
            "$ gain": "$0.00",
            "status": "Open",
            "notes": ""
        }
    return None


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.name == CHANNEL_NAME:
        trade_data = parse_trade(message.content)
        if trade_data:
            # ✅ Dynamically calculate trade number
            all_values = sheet.get_all_values()
            trade_number = len(all_values)  # first row = header
            row_values = [
                trade_number,
                trade_data["ticker"],
                trade_data["trade_enter"],
                trade_data["trade_exit"],
                trade_data["exp_date"],
                trade_data["strike"],
                trade_data["cp"],
                trade_data["initial_contracts"],
                trade_data["contracts"],
                trade_data["avg_cost_option"],
                trade_data["$ avg_cost"],
                trade_data["market_value"],
                trade_data["% gain"],
                trade_data["$ gain"],
                trade_data["status"],
                trade_data["notes"]
            ]

            try:
                sheet.append_row(row_values)
                await message.channel.send(
                    f"✅ Trade #{trade_number} recorded: {trade_data['ticker']} {trade_data['strike']}{trade_data['cp']} @ {trade_data['avg_cost_option']}"
                )
            except Exception as e:
                await message.channel.send(f"❌ Error writing to sheet: {e}")
        else:
            await message.channel.send("Invalid format. Use: BUY/SELL TICKER TRADE_ENTER EXP_DATE STRIKE[C/P] CONTRACTS @ PRICE")


# ✅ Correct bot + API run logic
async def main():
    config = Config()
    config.bind = ["0.0.0.0:8000"]

    await asyncio.gather(
        client.start(DISCORD_TOKEN),  # ✅ Use start(), not login/connect
        serve(app, config)
    )


if __name__ == "__main__":
    asyncio.run(main())
