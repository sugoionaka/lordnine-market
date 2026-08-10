import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import math
import time
import datetime
import concurrent.futures
import pandas as pd
import os

# 高速化のためのセッションとコネクションプール設定
session = requests.Session()
retry = Retry(
    total=5,
    read=5,
    connect=5,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=100, pool_maxsize=100)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({
    'Content-Type': 'application/json',
    'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7'
})

def fetch_api(url, method="GET", payload=None):
    try:
        if method == "GET":
            response = session.get(url, timeout=10)
        else:
            response = session.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return None

def get_realms():
    data = fetch_api('https://api.nextmarket.games/l9asia/v1/realm')
    return data if data else []

def get_presets():
    data = fetch_api('https://api.nextmarket.games/l9asia/v1/sale/c2c/preset')
    return data if data else []

def fetch_page(realm_code, preset_id, page, size=500):
    payload = {"realmCode": realm_code, "presetId": preset_id}
    url = f'https://api.nextmarket.games/l9asia/v1/sale/c2c?page={page}&size={size}'
    return fetch_api(url, method="POST", payload=payload)

def fetch_all_marketplace_data(realm_code, presets):
    categories_to_fetch = []
    for main_cat in presets:
        sub_cats = main_cat.get('subPresetList', [])
        if sub_cats:
            for sub_cat in sub_cats:
                categories_to_fetch.append({
                    'main': main_cat['name'],
                    'sub': sub_cat['name'],
                    'id': sub_cat['id']
                })
        else:
            categories_to_fetch.append({
                'main': main_cat['name'],
                'sub': "すべて",
                'id': main_cat['id']
            })

    page_tasks = []
    all_items = []
    
    def fetch_initial(cat):
        return cat, fetch_page(realm_code, cat['id'], 0, size=500)
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        future_to_cat = {executor.submit(fetch_initial, cat): cat for cat in categories_to_fetch}
        for future in concurrent.futures.as_completed(future_to_cat):
            cat, first_page = future.result()
            if first_page and 'content' in first_page:
                content = first_page['content']
                for item in content:
                    item['__main_cat'] = cat['main']
                    item['__sub_cat'] = cat['sub']
                all_items.extend(content)
                
                total_elements = first_page.get('totalElements', 0)
                total_pages = math.ceil(total_elements / 500)
                if total_pages > 1:
                    for p in range(1, total_pages):
                        page_tasks.append((cat['id'], p, cat['main'], cat['sub']))
            
    if page_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            future_to_info = {
                executor.submit(fetch_page, realm_code, task[0], task[1], 500): task 
                for task in page_tasks
            }
            for future in concurrent.futures.as_completed(future_to_info):
                task_info = future_to_info[future]
                page_data = future.result()
                if page_data and 'content' in page_data:
                    content = page_data['content']
                    for item in content:
                        item['__main_cat'] = task_info[2]
                        item['__sub_cat'] = task_info[3]
                    all_items.extend(content)
    
    processed_data = []
    for item in all_items:
        jpy_price = 0
        currency_type = "JPY"
        if 'fiatPriceInfo' in item:
            jpy_price = item['fiatPriceInfo'].get('price', 0)
            currency_type = item['fiatPriceInfo'].get('currencyType', 'JPY')
            
        usdt_price = 0
        if 'cryptoPriceInfo' in item:
            usdt_price = item['cryptoPriceInfo'].get('price', 0)
            
        enhance_lvl = "+0"
        if 'abilityOptionList' in item:
            for option in item['abilityOptionList']:
                if option.get('code') == "Enhance_LVL_NUM":
                    val = int(option.get('value', 0))
                    enhance_lvl = f"+{val}"
                    break
        
        name = item.get('item', {}).get('name', 'Unknown')
        
        appraisal = "なし"
        if "(鑑定)" in name or "(Appraised)" in name:
            appraisal = "鑑定"
        elif "(未鑑定)" in name or "(Not Appraised)" in name:
            appraisal = "未鑑定"
            
        processed_data.append({
            "name": name,
            "appraisal": appraisal,
            "enhance_lvl": enhance_lvl,
            "jpy_price": jpy_price,
            "currency_type": currency_type,
            "usdt_price": usdt_price
        })
        
    return pd.DataFrame(processed_data)

def main():
    print("Starting daily market history scrape...")
    realms = get_realms()
    presets = get_presets()
    
    if not realms or not presets:
        print("Failed to fetch realms or presets.")
        return
        
    all_summaries = []
    jst = datetime.timezone(datetime.timedelta(hours=9))
    current_date = datetime.datetime.now(jst).strftime("%Y-%m-%d")
    
    for r in realms:
        realm_code = r['code']
        realm_name = r['name']
        print(f"Fetching data for {realm_name} ({realm_code})...")
        
        df = fetch_all_marketplace_data(realm_code, presets)
        if df.empty:
            continue
            
        # サーバーが海外で USD 等を返した場合、強制的に日本円を計算する（ここでは固定レート157円を使用するか、USDTのみ保持するか）
        # 簡単のため、jpy_priceがない（0の場合）はusdt_price * 157を代入
        df['jpy_price'] = df.apply(
            lambda x: x['jpy_price'] if x['currency_type'] == 'JPY' else x['usdt_price'] * 157, 
            axis=1
        )
        
        # 0円のものは除外
        df = df[df['jpy_price'] > 0]
        
        if df.empty:
            continue
            
        # アイテムごとに最安値を計算
        summary = df.groupby(['name', 'enhance_lvl', 'appraisal']).agg(
            min_price=('jpy_price', 'min')
        ).reset_index()
        
        summary['realm'] = realm_code
        summary['date'] = current_date
        all_summaries.append(summary)
        
    if not all_summaries:
        print("No data collected.")
        return
        
    final_df = pd.concat(all_summaries, ignore_index=True)
    
    history_file = 'history.csv'
    
    # 既存の履歴があれば読み込んで結合
    if os.path.exists(history_file):
        try:
            old_df = pd.read_csv(history_file)
            # 同じ日付のデータがあれば上書き（削除して追加）
            old_df = old_df[old_df['date'] != current_date]
            final_df = pd.concat([old_df, final_df], ignore_index=True)
        except Exception as e:
            print(f"Error reading {history_file}: {e}")
            
    final_df.to_csv(history_file, index=False)
    print(f"Successfully saved {len(final_df)} rows to {history_file}.")

if __name__ == "__main__":
    main()
