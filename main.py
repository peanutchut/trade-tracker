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
CHANNEL_NAME = "trade-signals"  # Update to your actual channel name

# ✅ Google Sheets setup
gc = gspread.service_account(filename='credentialscopy.json')
sheet = gc.open("Demo Google Sheet").sheet1  # Replace with your sheet name

# ✅ Discord setup
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ✅ FastAPI for health check
app = FastAPI()

@app.get("/")
async def root():
    return JSONResponse(content={"message": "Bot is running!"})

# ✅ Regex for trade parsing
pattern = re.compile(
    r'Trade-(?P<trade_num>\d+)#(?P<action>BTO|STC)\s+'
    r'(?P<ticker>[A-Z]+)\s+'
    r'(?P<expiry>\d{2}/\d{2})\s+'
    r'(?P<strike>\d+)(?P<cp>[CP])@'
    r'(?P<price>[\d.]+)\('
    r'(?P<contracts>\d+)\s+contract[s]?\s*\)'
    r'(?:\s+(?P<notes>.*))?',  # ✅ Capture extra text as Notes
    re.IGNORECASE
)

# ✅ Parse trade message
def parse_trade(message):
    match = pattern.search(message)
    if not match:
        return None
    data = match.groupdict()
    data["trade_num"] = int(data["trade_num"])
    data["strike"] = float(data["strike"])
    data["price"] = float(data["price"])
    data["contracts"] = int(data["contracts"])
    data["expiry"] = format_expiry(data["expiry"])
    data["cp"] = data["cp"].upper()
    data["trade_enter"] = datetime.now().strftime("%m/%d")
    data["notes"] = data.get("notes") if data.get("notes") else ""
    return data

def format_expiry(raw_date):
    year = datetime.now().year
    month, day = map(int, raw_date.split("/"))
    if month < datetime.now().month:
        year += 1
    return f"{year}-{month:02d}-{day:02d}"

# ✅ Fetch live option price
def get_market_price(ticker, expiry, strike, cp):
    try:
        stock = yf.Ticker(ticker)
        chain = stock.option_chain(expiry)
        options = chain.calls if cp == "C" else chain.puts
        row = options[options['strike'] == strike]
        if not row.empty:
            bid, ask = float(row['bid'].iloc[0]), float(row['ask'].iloc[0])
            return round((bid + ask) / 2, 2) if (bid and ask) else bid or ask
    except Exception as e:
        print(f"⚠ Error fetching market price: {e}")
    return None

# ✅ Add or update trade (BTO)
def add_or_update_trade(data):
    rows = sheet.get_all_values()[1:]
    matching_rows = [idx for idx, row in enumerate(rows, start=2) if str(row[0]) == str(data["trade_num"]) and row[14].upper() == "OPEN"]

    if matching_rows:
        row_idx = matching_rows[0]
        current_contracts = int(sheet.cell(row_idx, 9).value)
        avg_cost_old = float(sheet.cell(row_idx, 10).value.replace("$", ""))

        new_total_contracts = current_contracts + data["contracts"]
        new_avg_cost = ((avg_cost_old * current_contracts) + (data["price"] * data["contracts"])) / new_total_contracts
        total_cost_basis = new_avg_cost * new_total_contracts * 100

        live_price = get_market_price(data["ticker"], data["expiry"], data["strike"], data["cp"]) or new_avg_cost
        market_value = live_price * new_total_contracts * 100

        sheet.update(f"I{row_idx}", new_total_contracts)
        sheet.update(f"J{row_idx}", f"${new_avg_cost:.2f}")
        sheet.update(f"K{row_idx}", f"${total_cost_basis:,.2f}")
        sheet.update(f"L{row_idx}", f"${market_value:,.2f}")
        if data["notes"]:
            sheet.update(f"P{row_idx}", data["notes"])
    else:
        avg_cost_total = data["price"] * data["contracts"] * 100
        live_price = get_market_price(data["ticker"], data["expiry"], data["strike"], data["cp"]) or data["price"]
        market_value = live_price * data["contracts"] * 100
        row = [
            data["trade_num"], data["ticker"], data["trade_enter"], "",
            data["expiry"], data["strike"], data["cp"],
            data["contracts"], data["contracts"],
            f"${data['price']:.2f}", f"${avg_cost_total:,.2f}",
            f"${market_value:,.2f}", "0.00%", "$0.00", "Open", data["notes"]
        ]
        sheet.append_row(row)

# ✅ Close trade (STC)
def close_trade(data):
    rows = sheet.get_all_values()[1:]
    for idx, row in enumerate(rows, start=2):
        if str(row[0]) == str(data["trade_num"]) and row[14].upper() == "OPEN":
            open_price = float(row[9].replace("$", ""))
            contracts = int(row[8])
            remaining = contracts - data["contracts"]

            live_price = get_market_price(data["ticker"], data["expiry"], data["strike"], data["cp"]) or data["price"]
            market_value = live_price * remaining * 100
            gain = (data["price"] - open_price) * data["contracts"] * 100
            pct_gain = (gain / (open_price * data["contracts"] * 100)) * 100

            sheet.update(f"D{idx}", datetime.now().strftime("%m/%d"))
            sheet.update(f"I{idx}", remaining)
            sheet.update(f"L{idx}", f"${market_value:,.2f}")
            sheet.update(f"M{idx}", f"{pct_gain:.2f}%")
            sheet.update(f"N{idx}", f"${gain:,.2f}")
            if data["notes"]:
                sheet.update(f"P{idx}", data["notes"])

            if remaining == 0:
                sheet.update(f"O{idx}", "Closed")
                sheet.format(f"A{idx}:P{idx}", {"textFormat": {"strikethrough": True}})
                return gain, pct_gain, live_price, True
            return gain, pct_gain, live_price, False
    return None, None, None, False

# ✅ Auto-update open trades every 15 mins
async def auto_update_open_trades():
    while True:
        rows = sheet.get_all_values()[1:]
        for idx, row in enumerate(rows, start=2):
            if row[14].upper() == "OPEN":
                ticker, expiry, strike, cp = row[1], row[4], float(row[5]), row[6]
                contracts = int(row[8])
                open_price = float(row[9].replace("$", ""))

                live_price = get_market_price(ticker, expiry, strike, cp)
                if live_price:
                    market_value = live_price * contracts * 100
                    cost_basis = open_price * contracts * 100
                    gain = market_value - cost_basis
                    pct_gain = (gain / cost_basis) * 100 if cost_basis else 0

                    sheet.update(f"L{idx}", f"${market_value:,.2f}")
                    sheet.update(f"M{idx}", f"{pct_gain:.2f}%")
                    sheet.update(f"N{idx}", f"${gain:,.2f}")
        await asyncio.sleep(900)

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
                add_or_update_trade(trade_data)
                await message.channel.send(f"✅ Added/Updated: {trade_data['ticker']} {trade_data['strike']}{trade_data['cp']} @ ${trade_data['price']:.2f}")
            elif trade_data["action"].upper() == "STC":
                gain, pct_gain, used_price, fully_closed = close_trade(trade_data)
                if gain is not None:
                    if fully_closed:
                        await message.channel.send(f"✅ Trade #{trade_data['trade_num']} CLOSED! {trade_data['ticker']} @ ${used_price:.2f} | Gain: {pct_gain:.2f}% (${gain:,.2f})")
                    else:
                        await message.channel.send(f"✅ Partially closed: {trade_data['ticker']} @ ${used_price:.2f} | Gain: {pct_gain:.2f}% (${gain:,.2f})")
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
