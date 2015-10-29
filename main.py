#!/usr/bin/python
from flask import Flask, request, redirect
from twilio.rest import TwilioRestClient
from lib.ExpiringCache import ExpiringCache
from threading import Thread
import threading
from time import sleep
import twilio.twiml
import schedule
import requests
import sys
import time

def run_continuously(sh, interval=1):
        cease_continuous_run = threading.Event()
        class ScheduleThread(threading.Thread):
            @classmethod
            def run(cls):
                while not cease_continuous_run.is_set():
                    sh.run_pending()
                    time.sleep(interval)
        continuous_thread = ScheduleThread()
        continuous_thread.start()

class SubscriptionRepo():
    def __init__(self):
        self.storage = {}

    def add_subscription(self, subscriber, stock):
        if stock not in self.storage:
            self.storage[stock] = [ subscriber ]
        else:
            subs = self.storage[stock]
            if subscriber not in subs:
                subs.append(subscriber)

    def remove_subscription(self, subscriber, stock):
        if stock not in self.storage:
            return
        if subscriber in self.storage[stock]:
            self.storage[stock].remove(subscriber)

    def get_storage(self):
        return self.storage

last_message_cache = ExpiringCache()
subscription_repo = SubscriptionRepo()
app = Flask(__name__)



def get_ticker_info(csv_tickers):
    tickers = csv_tickers.split(",")
    buff = ""
    for i, ticker in enumerate(tickers):
        ticker = ticker.strip()
        if i != 0:
            buff += "\n"
        ticker_price = requests.get("http://download.finance.yahoo.com/d/quotes.csv?s=%s&f=nsl1" % ticker).text
        parts = ticker_price.encode('ascii', 'xmlcharrefreplace').split("\",")
        parts = [x.strip().replace("\n", "").replace("\"", "") for x in parts]
        if len(parts) != 3:
            buff += "Unable to get quote on ticker"
            continue
        name = parts[0]
        price = parts[2]
        if name == "N/A" or price == "N/A":
            buff += "Unable to get quote on ticker"
        else:
            buff += "{0}: ${1}".format(name, price)
    return buff

def get_more_info(ticker):
    if "," in ticker:
        return "MORE INFO on multiple tickers isn't allowed."
    ticker_price = requests.get("http://download.finance.yahoo.com/d/quotes.csv?s=%s&f=sl1opj1p2t1" % ticker).text

    parts = ticker_price.encode('ascii', 'xmlcharrefreplace').split(",")
    parts = [x.strip().replace("\n", "").replace("\"", "") for x in parts]
    name = parts[0].upper()
    price = parts[1]
    opening = parts[2]
    closing = parts[3]
    marketcap = parts[4]
    percent_change = parts[5]
    last_trade = parts[6]
    return ("More Information on {0}\nOpening Price: ${1}\nClosing Price: ${2}\nMarket Capitalization"
            ": ${3}\nChange in Percent: {4}\nLast Trade Time: {5}").format(name, opening, closing, marketcap, percent_change, last_trade)
  
def toggle_subscription(ticker, sender, toggle_state):
    if toggle_state:
        subscription_repo.add_subscription(sender, ticker)
        return "You are now subscribed to '%s' updates" % ticker 
    else:
        subscription_repo.remove_subscription(sender, ticker)
        return "You are now unsubscribed from '%s' updates" % ticker 

def evaluate_message(curr, prev, sender):
    curr = curr.upper()
    if curr == "MORE INFO":
        if prev is None:
            return "Please text a ticker first"
        return get_more_info(prev)
    elif curr.startswith("SUB "):
        return toggle_subscription(curr.replace("SUB ", ""), sender, True)
    elif curr.startswith("UNSUB "):
        return toggle_subscription(curr.replace("UNSUB ", ""), sender, False)
    elif curr == "MENU":
        return "Options: <TICKER> to get quote, MORE INFO for more info on previous ticker, SUB\
                <TICKER> to subscribe, UNSUB <TICKER> to unsubscribe."
    else:
        return get_ticker_info(curr)

@app.route("/recv", methods=['GET', 'POST'])
def on_text_received():
    from_number = request.values.get('From', None)
    curr_message = request.values.get("Body", None)
    prev_message = last_message_cache.get(from_number, None)
    
    response = evaluate_message(curr_message, prev_message, from_number)
    last_message_cache.set(from_number, curr_message, timeout=900)

    resp = twilio.twiml.Response()
    resp.message(response)
    return str(resp)

def repl():
    prev = None
    while True:
        curr = raw_input("> ")
        print evaluate_message(curr, prev, "+123123")
        prev = curr

def sub_service():
    sub_repo = subscription_repo.get_storage()
    for key in sub_repo:
        ticker = key
        targets_to_send_to = sub_repo[key]
        if len(targets_to_send_to) == 0:
            continue

        info = get_ticker_info(key)
        for target in targets_to_send_to:
            account = ""
            token = ""
            twilio_number = ""
            client = TwilioRestClient(account, token)
            message = client.sms.messages.create(to=target,
                                                 from_=twilio_number,
                                                 body=info)
            print target,info

 
if __name__ == "__main__":
    sh = schedule.Scheduler()
    sh.every(10).seconds.do(sub_service)
    run_continuously(sh)

    if len(sys.argv) == 2 and sys.argv[1] == 'repl':
        repl()
    app.run(debug=True, port=9000, host="0.0.0.0")
