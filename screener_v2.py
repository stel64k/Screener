import json
import requests
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from tqdm import tqdm
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename='trading_bot.log')

# Загрузка конфигурационного файла
with open('config.json', 'r') as file:
    config = json.load(file)

# Инициализация клиента Binance
client = Client(api_key=config['binance_api_key'], api_secret=config['binance_api_secret'])

def send_telegram_message(symbol, message):
    """Функция для отправки уведомлений в Telegram с ссылкой на график."""
    telegram_api_url = f"https://api.telegram.org/bot{config['telegram_bot_token']}/sendMessage"
    
    # Формирование ссылки
    link = f"https://www.coinglass.com/tv/Binance_{symbol}"
    
    # Формирование полного сообщения
    full_message = f"{message}\n\nСсылка на график: {link}"
    
    params = {
        "chat_id": config['telegram_chat_id'],
        "text": full_message
    }
    
    try:
        response = requests.get(telegram_api_url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to send message to Telegram: {response.status_code}")
    except Exception as e:
        logging.error(f"Error sending message to Telegram: {e}")


def fetch_current_price(symbol):
    """Функция для получения текущей цены символа."""
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except BinanceAPIException as e:
        logging.error(f"Error fetching current price for {symbol}: {e}")
        return None

def fetch_futures_data(symbol, intervals):
    """Функция для получения данных открытого интереса и объема по нескольким таймфреймам."""
    try:
        open_interest = client.futures_open_interest(symbol=symbol)
        open_interest_hist = client.futures_open_interest_hist(symbol=symbol, period='5m', limit=2)
        
        # Получение данных по нескольким таймфреймам
        klines = {}
        for interval in intervals:
            klines[interval] = client.futures_klines(symbol=symbol, interval=interval, limit=10)
        
        return open_interest, open_interest_hist, klines
    except BinanceAPIException as e:
        if e.code == -4108:
            logging.info(f"Skipping symbol {symbol} due to API error -4108")
            return None, None, None
        logging.error(f"Error fetching data for {symbol}: {e}")
        return None, None, None

def calculate_cumulative_delta(klines):
    """Функция для расчета кумулятивной дельты объема с использованием торговых данных."""
    cumulative_delta = 0
    total_buy_volume = 0
    total_sell_volume = 0

    for kline in klines:
        open_price = float(kline[1])
        close_price = float(kline[4])
        high_price = float(kline[2])
        low_price = float(kline[3])
        candle_volume = float(kline[5])

        # Избегаем деления на ноль
        price_range = high_price - low_price
        if price_range == 0:
            continue

        buy_volume = (candle_volume / price_range) * (close_price - low_price)
        sell_volume = candle_volume - buy_volume

        total_buy_volume += buy_volume
        total_sell_volume += sell_volume

        cumulative_delta += (buy_volume - sell_volume)

    return cumulative_delta, total_buy_volume, total_sell_volume

def analyze_symbol(symbol):
    """Функция анализа символа."""
    intervals = config['analysis_intervals']  # Предполагаем, что 'analysis_intervals' - это список интервалов
    open_interest, open_interest_hist, klines_by_interval = fetch_futures_data(symbol, intervals)
    
    if open_interest and open_interest_hist and klines_by_interval:
        for interval, klines in klines_by_interval.items():
            cumulative_delta, total_buy_volume, total_sell_volume = calculate_cumulative_delta(klines)

            last_open_interest = float(open_interest['openInterest'])
            prev_open_interest = float(open_interest_hist[-2]['sumOpenInterest'])

            # Настройки процентов из конфигурационного файла
            delta_percentage = config['delta_percentage']
            interest_percentage = config['interest_percentage']

            current_price = fetch_current_price(symbol)

            # Расчет процентного изменения открытого интереса
            interest_increase_percentage = ((last_open_interest - prev_open_interest) / prev_open_interest) * 100

            # Проверка условий для сигнала на покупку
            if (total_buy_volume > total_sell_volume and 
                cumulative_delta > 0 and 
                last_open_interest > prev_open_interest and 
                interest_increase_percentage > interest_percentage and
                cumulative_delta / total_buy_volume * 100 > delta_percentage):
                
                ratio_buy_to_sell = total_buy_volume / total_sell_volume if total_sell_volume != 0 else float('inf')

                message = (
                    f"Пара: {symbol}\n"
                    f"Интервал: {interval}\n"
                    f"Открытый интерес вырос: {prev_open_interest} -> {last_open_interest} ({interest_increase_percentage:.2f}% рост)\n"
                    f"Кумулятивная дельта объема положительная: {cumulative_delta}\n"
                    f"Объем покупок: {total_buy_volume}\n" 
                    f"Oбъем продаж: {total_sell_volume}\n"
                    f"Покупки больше продаж в {ratio_buy_to_sell:.2f} раз\n"
                    f"Текущая цена: {current_price}\n"
                    f"Сигнал на покупку!"
                )
                logging.info(message)
                send_telegram_message(symbol, message)


def analyze_market():
    """Основная функция анализа рынка."""
    try:
        futures_info = client.futures_exchange_info()
        symbols = [item['symbol'] for item in futures_info['symbols'] if item['quoteAsset'] == 'USDT']

        for symbol in tqdm(symbols, desc="Анализ рынка"):
            analyze_symbol(symbol)

    except BinanceAPIException as e:
        logging.error(f"Error in analyze_market: {e}")

def main():
    """Основная функция для запуска бота."""
    while True:
        analyze_market()
        logging.info("Анализ завершен. Ожидание 3 минуты перед следующим запуском...")
        time.sleep(1)

if __name__ == "__main__":
    main()