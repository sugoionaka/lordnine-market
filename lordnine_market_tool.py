import streamlit as st
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import math
import time
import datetime
import concurrent.futures
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode, ColumnsAutoSizeMode

st.set_page_config(page_title="LORDNINE Market Analyzer", layout="wide")

# カスタムCSSでサイドバーの空白を極力詰める
st.markdown("""
<style>
    /* サイドバー内の要素の上下の余白を詰める */
    [data-testid="stSidebar"] .stRadio, 
    [data-testid="stSidebar"] .stPills, 
    [data-testid="stSidebar"] .stSelectbox {
        margin-bottom: -15px;
    }
    /* st.pillsのボタン間の隙間を少し詰める */
    div[data-testid="stPills"] button {
        padding-top: 0.2rem;
        padding-bottom: 0.2rem;
        padding-left: 0.6rem;
        padding-right: 0.6rem;
        min-height: 2rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚔️ LORDNINE NEXT Market 分析ツール")

RARITY_COLORS = {
    "NONE": "コモン",
    "GREEN": "アンコモン",
    "BLUE": "レア",
    "MAGENTA": "エピック",
    "ORANGE": "レジェンド",
    "RED": "ミシック"
}

RARITY_TEXT_COLORS = {
    "コモン": "#E0E0E0",
    "アンコモン": "#4CAF50",
    "レア": "#2196F3",
    "エピック": "#9C27B0",
    "レジェンド": "#FF9800",
    "ミシック": "#F44336"
}

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

@st.cache_data(ttl=3600)
def get_realms():
    data = fetch_api('https://api.nextmarket.games/l9asia/v1/realm')
    return data if data else []

@st.cache_data(ttl=3600)
def get_presets():
    data = fetch_api('https://api.nextmarket.games/l9asia/v1/sale/c2c/preset')
    return data if data else []

def fetch_page(realm_code, preset_id, page, size=500):
    payload = {"realmCode": realm_code, "presetId": preset_id}
    url = f'https://api.nextmarket.games/l9asia/v1/sale/c2c?page={page}&size={size}'
    return fetch_api(url, method="POST", payload=payload)

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_all_marketplace_data(realm_code):
    presets = get_presets()
    if not presets:
        return pd.DataFrame()

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
    
    progress_text = "データの超高速取得中..."
    bar = st.progress(0, text=progress_text)
    
    total_cats = len(categories_to_fetch)
    completed = 0
    
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
            completed += 1
            bar.progress(completed / total_cats, text=f"{progress_text} ({completed}/{total_cats})")
            
    if page_tasks:
        completed_tasks = 0
        total_tasks = len(page_tasks)
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
                completed_tasks += 1
                bar.progress(completed_tasks / total_tasks, text=f"追加データの取得中... ({completed_tasks}/{total_tasks})")
    
    bar.empty()
    
    processed_data = []
    for item in all_items:
        bg_color = item.get('backgroundColor', 'NONE')
        rarity_name = RARITY_COLORS.get(bg_color, "不明")
        
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
        
        processed_data.append({
            "id": item.get('id'),
            "main_cat": item.get('__main_cat'),
            "sub_cat": item.get('__sub_cat'),
            "name": item.get('item', {}).get('name', 'Unknown'),
            "rarity": rarity_name,
            "jpy_price": jpy_price,
            "currency_type": currency_type,
            "usdt_price": usdt_price,
            "enhance_lvl": enhance_lvl
        })
        
    return pd.DataFrame(processed_data)

# --- App Logic ---
realms = get_realms()
realm_options = {r['name']: r['code'] for r in realms} if realms else {"OLD_REALM": "OLD_REALM"}

default_realm_index = 0
realm_names = list(realm_options.keys())
for i, name in enumerate(realm_names):
    if "オリジン" in name:
        default_realm_index = i
        break

# --- SIDEBAR: 設定 ---
st.sidebar.markdown("### ⚙️ 設定")

selected_realm_name = st.sidebar.pills(
    "サーバー (Realm)", 
    options=realm_names, 
    default=realm_names[default_realm_index] if realm_names else None,
    selection_mode="single"
)
if selected_realm_name is None:
    selected_realm_name = realm_names[default_realm_index] if realm_names else "OLD_REALM"

realm_code = realm_options.get(selected_realm_name, "OLD_REALM")

if st.sidebar.button("🔄 最新データを取得 (リロード)"):
    fetch_all_marketplace_data.clear()

jst = datetime.timezone(datetime.timedelta(hours=9))
last_updated = datetime.datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S")
st.sidebar.markdown(f"<div style='text-align:center; font-size: 0.8rem; color: gray;'>最終更新: {last_updated} (JST)</div>", unsafe_allow_html=True)

st.sidebar.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

currency_mode = st.sidebar.radio("価格表示 (通貨)", ["JPY (日本円)", "USDT"])
is_jpy = "JPY" in currency_mode
price_col = 'jpy_price' if is_jpy else 'usdt_price'

jpy_rate = 157
if is_jpy:
    jpy_rate = st.sidebar.number_input("USDT換算レート (円)", min_value=100, max_value=200, value=157, step=1, help="クラウドサーバー経由のためAPIが日本円を返さない場合、USDTから自動換算します。")

st.sidebar.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

with st.spinner(f"サーバー「{selected_realm_name}」のデータを取得中..."):
    df_all = fetch_all_marketplace_data(realm_code)

if not df_all.empty and is_jpy:
    # サーバーが海外で USD 等を返した場合、USDT価格 × 設定レート で強制的に日本円を計算する
    df_all['jpy_price'] = df_all.apply(
        lambda x: x['jpy_price'] if x['currency_type'] == 'JPY' else x['usdt_price'] * jpy_rate, 
        axis=1
    )

if df_all.empty:
    st.error("データの取得に失敗したか、出品アイテムがありません。")
    st.stop()

# --- カテゴリ設定 (Pills化) ---
main_cats_available = ["すべて"] + list(df_all['main_cat'].unique())
selected_main_cat = st.sidebar.pills(
    "メインカテゴリ", 
    options=main_cats_available, 
    default="すべて",
    selection_mode="single"
)
if selected_main_cat is None:
    selected_main_cat = "すべて"

sub_cats_available = ["すべて"]
if selected_main_cat != "すべて":
    sub_cats_available += list(df_all[df_all['main_cat'] == selected_main_cat]['sub_cat'].unique())

selected_sub_cat = st.sidebar.pills(
    "サブカテゴリ", 
    options=sub_cats_available, 
    default="すべて",
    selection_mode="single"
)
if selected_sub_cat is None:
    selected_sub_cat = "すべて"

st.sidebar.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

rarity_options = ["すべて"] + list(RARITY_COLORS.values())
selected_rarity = st.sidebar.pills(
    "表示するレアリティ", 
    options=rarity_options, 
    default="すべて", 
    selection_mode="single"
)
if selected_rarity is None:
    selected_rarity = "すべて"

# --- MAIN AREA ---
filtered_df = df_all.copy()

if selected_main_cat != "すべて":
    filtered_df = filtered_df[filtered_df['main_cat'] == selected_main_cat]
    if selected_sub_cat != "すべて":
        filtered_df = filtered_df[filtered_df['sub_cat'] == selected_sub_cat]

if selected_rarity != "すべて" and selected_rarity is not None:
    filtered_df = filtered_df[filtered_df['rarity'] == selected_rarity]
elif selected_rarity is None:
    filtered_df = pd.DataFrame(columns=df_all.columns)

filtered_df = filtered_df[filtered_df[price_col] > 0]

if filtered_df.empty:
    st.info("選択された条件に一致するアイテムが見つかりませんでした。")
else:
    currency_symbol = "¥" if is_jpy else "USDT "
    
    min_val = filtered_df[price_col].min()
    max_val = filtered_df[price_col].max()
    min_str = f"{currency_symbol}{min_val:,.2f}" if not is_jpy else f"{currency_symbol}{int(min_val):,}"
    max_str = f"{currency_symbol}{max_val:,.2f}" if not is_jpy else f"{currency_symbol}{int(max_val):,}"
    
    st.markdown(
        f"**📊 検索結果サマリー** &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"該当アイテム数: **{len(filtered_df):,}** 件 &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"最安値: **{min_str}** &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"最高値: **{max_str}**"
    )
    
    st.markdown("---")
    
    col_list, col_details = st.columns([1.3, 1])
    
    with col_list:
        st.markdown("### ⭐ 相場一覧 (行クリックで右に詳細表示)")
        
        summary_df = filtered_df.groupby(['name', 'rarity']).agg(
            出品数=('id', 'count'),
            最安値=(price_col, 'min'),
            最高値=(price_col, 'max')
        ).reset_index()
        
        summary_df = summary_df.sort_values('name')
        
        display_df = summary_df[['name', 'rarity', '出品数', '最安値', '最高値']].rename(columns={
            'name': 'アイテム名',
            'rarity': 'レアリティ'
        })
        
        gb = GridOptionsBuilder.from_dataframe(display_df)
        gb.configure_selection('single', use_checkbox=False)
        gb.configure_column("レアリティ", hide=True)
        
        formatter_jscode = JsCode("function(params) { return params.value ? '¥' + Math.floor(params.value).toLocaleString() : ''; }") if is_jpy else JsCode("function(params) { return params.value ? 'USDT ' + params.value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : ''; }")
        gb.configure_column("最安値", type=["numericColumn", "numberColumnFilter"], valueFormatter=formatter_jscode)
        gb.configure_column("最高値", type=["numericColumn", "numberColumnFilter"], valueFormatter=formatter_jscode)
        
        
        color_jscode = JsCode("""
        function(params) {
            var rarity = params.data.レアリティ;
            if (rarity === 'コモン') return {'color': '#E0E0E0', 'fontWeight': 'bold'};
            if (rarity === 'アンコモン') return {'color': '#4CAF50', 'fontWeight': 'bold'};
            if (rarity === 'レア') return {'color': '#2196F3', 'fontWeight': 'bold'};
            if (rarity === 'エピック') return {'color': '#9C27B0', 'fontWeight': 'bold'};
            if (rarity === 'レジェンド') return {'color': '#FF9800', 'fontWeight': 'bold'};
            if (rarity === 'ミシック') return {'color': '#F44336', 'fontWeight': 'bold'};
            return {'color': 'white', 'fontWeight': 'bold'};
        }
        """)
        gb.configure_column("アイテム名", cellStyle=color_jscode)
        gb.configure_grid_options(domLayout='autoHeight')
        
        go = gb.build()
        
        response = AgGrid(
            display_df,
            gridOptions=go,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            theme='streamlit',
            columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS
        )
    
    with col_details:
        selected = response.get('selected_rows')
        if selected is not None and len(selected) > 0:
            if isinstance(selected, pd.DataFrame):
                selected_item_name = selected.iloc[0]['アイテム名']
            else:
                selected_item_name = selected[0]['アイテム名']
                
            st.markdown(f"#### 🔍 「{selected_item_name}」 の強化値内訳")
            
            detail_df = filtered_df[filtered_df['name'] == selected_item_name]
            
            detail_grouped = detail_df.groupby('enhance_lvl').agg(
                出品数=('id', 'count'),
                最安値=(price_col, 'min'),
                最高値=(price_col, 'max')
            ).reset_index()
            
            detail_grouped['sort_key'] = detail_grouped['enhance_lvl'].apply(lambda x: int(x.replace('+', '')))
            detail_grouped = detail_grouped.sort_values('sort_key').drop('sort_key', axis=1)
            
            detail_grouped.rename(columns={'enhance_lvl': '強化値'}, inplace=True)
            
            st.dataframe(
                detail_grouped, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "最安値": st.column_config.NumberColumn(
                        "最安値",
                        format="¥%d" if is_jpy else "USDT %.2f"
                    ),
                    "最高値": st.column_config.NumberColumn(
                        "最高値",
                        format="¥%d" if is_jpy else "USDT %.2f"
                    )
                }
            )
        else:
            st.info("👈 左の表からアイテムをクリックすると、ここに強化値ごとの内訳が表示されます。")
