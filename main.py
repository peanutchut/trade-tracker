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

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_NAME = "trade-signals"

# Google Sheets setup
gc = gspread.service_account(filename='credentialscopy.json')
sheet = gc.open("Demo Google Sheet").sheet1  # Update if sheet name differs

# Discord client setup
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# FastAPI for health checks
app = FastAPI()

@app.get("/")
async def root():
    return JSONResponse(content={"message": "Bot is running!"})

# ✅ Parse new trade command
def parse_trade(message):
    # Expected format: BUY AMD 11/11 12/20 145C 5 @ 865
    parts = message.strip().upper().split()

    if len(parts) >= 8 and parts[0] in ["BUY", "SELL"] and "@" in parts:
        action = parts[0]
        ticker = parts[1]
        trade_enter = parts[2]
        exp_date = parts[3]
        strike_raw = parts[4]
        strike = strike_raw[:-1]
        cp = strike_raw[-1]
        contracts = int(parts[5])

        try:
            at_index = parts.index("@")
            raw_price = parts[at_index + 1]
        except ValueError:
            return None

        price_float = float(raw_price) / 100
        total_cost = price_float * contracts * 100  # each option = 100 shares

        return {
            "action": action,
            "ticker": ticker,
            "trade_enter": trade_enter,
            "trade_exit": "",
            "exp_date": exp_date,
            "strike": strike,
            "cp": cp,
            "initial_contracts": contracts,
            "contracts": contracts,
            "avg_cost_option": f"${price_float:.2f}",
            "$ avg_cost": f"${total_cost:,.2f}",
            "market_value": f"${total_cost:,.2f}",
            "% gain": "0.00%",
            "$ gain": "$0.00",
            "status": "Open",
            "notes": ""
        }
    return None

# ✅ Parse close trade command
def parse_close(message):
    # Expected: CLOSE AMD 11/15 @ 900
    parts = message.strip().upper().split()
    if len(parts) == 5 and parts[0] == "CLOSE" and parts[3] == "@":
        ticker = parts[1]
        trade_exit = parts[2]
        close_price = float(parts[4]) / 100
        return ticker, trade_exit, close_price
    return None

# ✅ Find the last open trade for a ticker
def find_open_trade(ticker):
    all_rows = sheet.get_all_values()[1:]  # skip header
    for idx, row in enumerate(reversed(all_rows), start=2):  # start at row 2
        if row[0] == ticker and row[13].upper() == "OPEN":
            return len(all_rows) - idx + 2  # return sheet row number
    return None

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.name == CHANNEL_NAME:
        content = message.content.strip()

        # Check for open trade
        trade_data = parse_trade(content)
        if trade_data:
            try:
                all_values = sheet.get_all_values()
                trade_number = len(all_values)  # count existing rows
                row_values = [
                    trade_data["ticker"], trade_data["trade_enter"], trade_data["trade_exit"],
                    trade_data["exp_date"], trade_data["strike"], trade_data["cp"],
                    trade_data["initial_contracts"], trade_data["contracts"],
                    trade_data["avg_cost_option"], trade_data["$ avg_cost"],
                    trade_data["market_value"], trade_data["% gain"], trade_data["$ gain"],
                    trade_data["status"], trade_data["notes"]
                ]
                sheet.append_row(row_values)
                await message.channel.send(
                    f"✅ Trade #{trade_number} recorded: {trade_data['ticker']} {trade_data['strike']}{trade_data['cp']} @ {trade_data['avg_cost_option']}"
                )
            except Exception as e:
                await message.channel.send(f"❌ Error writing to sheet: {e}")
            return

        # Check for close trade
        close_data = parse_close(content)
        if close_data:
            ticker, trade_exit, close_price = close_data
            row_num = find_open_trade(ticker)
            if row_num:
                row = sheet.row_values(row_num)
                open_price = float(row[8].replace("$", ""))
                contracts = int(row[7])
                market_value = close_price * contracts * 100
                initial_cost = open_price * contracts * 100
                gain = market_value - initial_cost
                pct_gain = (gain / initial_cost) * 100 if initial_cost > 0 else 0

                # Update cells in sheet
                sheet.update(f"C{row_num}", trade_exit)
                sheet.update(f"K{row_num}", f"${market_value:,.2f}")
                sheet.update(f"L{row_num}", f"{pct_gain:.2f}%")
                sheet.update(f"M{row_num}", f"${gain:,.2f}")
                sheet.update(f"N{row_num}", "Closed")

                await message.channel.send(
                    f"✅ Trade closed: {ticker} @ ${close_price:.2f} | Gain: {pct_gain:.2f}% (${gain:,.2f})"
                )
            else:
                await message.channel.send(f"⚠ No open trade found for {ticker}.")
            return

        # Invalid format
        await message.channel.send(
            "❌ Invalid format.\nUse:\nOpen: `BUY/SELL TICKER TRADE_ENTER EXP_DATE STRIKE[C/P] CONTRACTS @ PRICE`\nClose: `CLOSE TICKER TRADE_EXIT @ PRICE`"
        )

# ✅ Run both bot and API
async def main():
    config = Config()
    config.bind = ["0.0.0.0:8000"]

    await asyncio.gather(
        client.start(DISCORD_TOKEN),
        serve(app, config)
    )

if __name__ == "__main__":
    asyncio.run(main())
