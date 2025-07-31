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
import yfinance as yf

# ✅ Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_NAME = "trade-signals"

# ✅ Google Sheets setup
gc = gspread.service_account(filename='credentialscopy.json')
sheet = gc.open("Demo Google Sheet").sheet1  # Ensure this matches your sheet

# ✅ Discord setup
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ✅ FastAPI health check
app = FastAPI()

@app.get("/")
async def root():
    return JSONResponse(content={"message": "Bot is running!"})

# ✅ Parse trade message
def parse_trade(message):
    pattern = re.compile(
    r'Trade-(?P<trade_num>\d+)#(?P<action>BTO|STC)\s+'
    r'(?P<ticker>[A-Z]+)\s+'
    r'(?P<expiry>\d{2}/\d{2})\s+'
    r'(?P<strike>\d+)(?P<cp>[CP])@'
    r'(?P<price>[\d.]+)\('
    r'(?P<contracts>\d+)\s+contract[s]?\s*\)', re.IGNORECASE
    )
    match = pattern.search(message)
    if not match:
        return None

    data = match.groupdict()
    data["trade_num"] = int(data["trade_num"])
    data["strike"] = int(data["strike"])
    data["price"] = float(data["price"])
    data["contracts"] = int(data["contracts"])
    data["expiry"] = format_expiry(data["expiry"])
    data["trade_enter"] = datetime.now().strftime("%m/%d")
    data["trade_exit"] = ""
    return data

def format_expiry(raw_date):
    year = datetime.now().year
    month, day = map(int, raw_date.split("/"))
    if month < datetime.now().month:  # If date has passed, assume next year
        year += 1
    return f"{year}-{month:02d}-{day:02d}"

# ✅ Fetch live market price
def get_market_price(ticker, expiry, strike, cp):
    try:
        stock = yf.Ticker(ticker)
        chain = stock.option_chain(expiry)
        options = chain.calls if cp.upper() == "C" else chain.puts
        row = options[options['strike'] == float(strike)]
        if not row.empty:
            bid, ask = float(row['bid'].iloc[0]), float(row['ask'].iloc[0])
            midpoint = (bid + ask) / 2 if bid and ask else bid or ask
            return round(midpoint, 2)
    except Exception as e:
        print(f"⚠ Error fetching market price: {e}")
    return None

# ✅ Add trade to sheet
def add_trade(data):
    avg_cost = f"${data['price']:.2f}"
    total_cost = data['price'] * data['contracts'] * 100
    row = [
        data["trade_num"], data["ticker"], data["trade_enter"], "",
        data["expiry"], data["strike"], data["cp"],
        data["contracts"], data["contracts"],
        avg_cost, f"${total_cost:,.2f}", f"${total_cost:,.2f}",
        "0.00%", "$0.00", "Open", ""
    ]
    sheet.append_row(row)

# ✅ Close trade (STC)
def close_trade(data):
    rows = sheet.get_all_values()[6:]  # Skip headers
    for idx, row in enumerate(rows, start=7):
        if str(row[0]) == str(data["trade_num"]) and row[14].upper() == "OPEN":
            open_price = float(row[9].replace("$", ""))
            contracts = int(row[8])
            live_price = get_market_price(data["ticker"], data["expiry"], data["strike"], data["cp"]) or data["price"]

            market_value = live_price * contracts * 100
            initial_cost = open_price * contracts * 100
            gain = market_value - initial_cost
            pct_gain = (gain / initial_cost) * 100 if initial_cost else 0

            updates = {
                "D": datetime.now().strftime("%m/%d"),
                "L": f"${market_value:,.2f}",
                "M": f"{pct_gain:.2f}%",
                "N": f"${gain:,.2f}",
                "O": "Closed"
            }
            for col, val in updates.items():
                sheet.update(f"{col}{idx}", val)
            return gain, pct_gain, live_price
    return None, None, None

# ✅ Auto-update open trades every 15 mins
async def auto_update_open_trades():
    while True:
        rows = sheet.get_all_values()[6:]
        for idx, row in enumerate(rows, start=7):
            if row[14].upper() == "OPEN":
                ticker, expiry, strike, cp, contracts, open_price = row[1], row[4], row[5], row[6], int(row[8]), float(row[9].replace("$", ""))
                live_price = get_market_price(ticker, expiry, strike, cp)
                if live_price:
                    market_value = live_price * contracts * 100
                    initial_cost = open_price * contracts * 100
                    gain = market_value - initial_cost
                    pct_gain = (gain / initial_cost) * 100 if initial_cost else 0

                    sheet.update(f"L{idx}", f"${market_value:,.2f}")
                    sheet.update(f"M{idx}", f"{pct_gain:.2f}%")
                    sheet.update(f"N{idx}", f"${gain:,.2f}")
        await asyncio.sleep(900)  # 15 minutes

# ✅ Discord Events
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    asyncio.create_task(auto_update_open_trades())

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.name == CHANNEL_NAME:
        trade_data = parse_trade(message.content)
        if trade_data:
            if trade_data["action"].upper() == "BTO":
                add_trade(trade_data)
                await message.channel.send(f"✅ Added: {trade_data['ticker']} {trade_data['strike']}{trade_data['cp']} @ ${trade_data['price']:.2f}")
            elif trade_data["action"].upper() == "STC":
                gain, pct_gain, used_price = close_trade(trade_data)
                if gain is not None:
                    await message.channel.send(f"✅ Closed: {trade_data['ticker']} @ ${used_price:.2f} | Gain: {pct_gain:.2f}% (${gain:,.2f})")
                else:
                    await message.channel.send(f"⚠ No open trade found for #{trade_data['trade_num']}")
        else:
            await message.channel.send("❌ Invalid format. Example: `Trade-101#BTO AAPL 08/15 200C@3.5(2 contracts)`")

# ✅ Run bot + FastAPI
async def main():
    config = Config()
    config.bind = ["0.0.0.0:8000"]
    await asyncio.gather(client.start(DISCORD_TOKEN), serve(app, config))

if __name__ == "__main__":
    asyncio.run(main())
