// 定数と変数
const RARITY_COLORS = {
    "NONE": "コモン",
    "GREEN": "アンコモン",
    "BLUE": "レア",
    "MAGENTA": "エピック",
    "ORANGE": "レジェンド",
    "RED": "ミシック"
};

let allItemsData = [];
let realms = [];
let categoriesToFetch = [];
let currentRealmCode = "";
let selectedItemName = null;

let currentSort = { column: 'name', asc: true };
let currentDetailsSort = { column: 'level', asc: true };
let currentGroupedArr = [];
let currentEnhArr = [];
let isJpyGlobal = true;

// DOM 要素
const DOM = {
    realmSelect: document.getElementById('realmSelect'),
    reloadBtn: document.getElementById('reloadBtn'),
    lastUpdated: document.getElementById('lastUpdated'),
    currencyRadios: document.getElementsByName('currencyMode'),
    jpyRate: document.getElementById('jpyRate'),
    jpyRateContainer: document.getElementById('jpyRateContainer'),
    mainCatSelect: document.getElementById('mainCatSelect'),
    subCatSelect: document.getElementById('subCatSelect'),
    raritySelect: document.getElementById('raritySelect'),
    
    loadingOverlay: document.getElementById('loadingOverlay'),
    loadingText: document.getElementById('loadingText'),
    progressBar: document.getElementById('progressBar'),
    
    summaryCount: document.getElementById('summaryCount'),
    summaryMin: document.getElementById('summaryMin'),
    summaryMax: document.getElementById('summaryMax'),
    
    mainTableBody: document.getElementById('mainTableBody'),
    detailsTitle: document.getElementById('detailsTitle'),
    detailsPlaceholder: document.getElementById('detailsPlaceholder'),
    detailsContent: document.getElementById('detailsContent'),
    detailsTableBody: document.getElementById('detailsTableBody')
};

// API Fetch Helper
async function fetchApi(url, method = "GET", payload = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7'
        }
    };
    if (payload) {
        options.body = JSON.stringify(payload);
    }
    
    for (let i = 0; i < 3; i++) {
        try {
            const response = await fetch(url, options);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (e) {
            if (i === 2) return null;
            await new Promise(r => setTimeout(r, 500 * Math.pow(2, i))); 
        }
    }
    return null;
}

// 初期化
async function initApp() {
    DOM.loadingOverlay.classList.remove('hidden');
    DOM.loadingText.textContent = "サーバーリストを取得中...";
    
    // イベントリスナーの登録
    DOM.reloadBtn.addEventListener('click', reloadData);
    DOM.currencyRadios.forEach(r => r.addEventListener('change', updateView));
    DOM.jpyRate.addEventListener('input', updateView);
    DOM.mainCatSelect.addEventListener('change', () => {
        updateSubCategoryOptions();
        updateView();
    });
    DOM.subCatSelect.addEventListener('change', updateView);
    DOM.raritySelect.addEventListener('change', updateView);
    
    // ソートイベントの登録
    document.querySelectorAll('#mainTable th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (currentSort.column === col) {
                currentSort.asc = !currentSort.asc;
            } else {
                currentSort.column = col;
                currentSort.asc = true;
            }
            updateSortIcons('mainTable', currentSort.column, currentSort.asc);
            renderMainTable();
        });
    });
    
    document.querySelectorAll('#detailsTable th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (currentDetailsSort.column === col) {
                currentDetailsSort.asc = !currentDetailsSort.asc;
            } else {
                currentDetailsSort.column = col;
                currentDetailsSort.asc = true;
            }
            updateSortIcons('detailsTable', currentDetailsSort.column, currentDetailsSort.asc);
            renderDetailsTable();
        });
    });
    
    // Realm取得
    realms = await fetchApi('https://api.nextmarket.games/l9asia/v1/realm');
    if (!realms || realms.length === 0) {
        alert("サーバーリストの取得に失敗しました。");
        return;
    }
    
    // Realmセレクトボックス構築
    DOM.realmSelect.innerHTML = '';
    let defaultIndex = 0;
    realms.forEach((r, idx) => {
        const option = document.createElement('option');
        option.value = r.code;
        option.textContent = r.name;
        DOM.realmSelect.appendChild(option);
        if (r.name.includes("オリジン")) defaultIndex = idx;
    });
    DOM.realmSelect.selectedIndex = defaultIndex;
    DOM.realmSelect.addEventListener('change', reloadData);
    
    await reloadData();
}

function updateSortIcons(tableId, activeCol, isAsc) {
    document.querySelectorAll(`#${tableId} th.sortable i`).forEach(icon => {
        icon.className = 'fa-solid fa-sort';
    });
    const activeTh = document.querySelector(`#${tableId} th[data-sort="${activeCol}"] i`);
    if (activeTh) {
        activeTh.className = isAsc ? 'fa-solid fa-sort-up' : 'fa-solid fa-sort-down';
    }
}

// データ再取得ロジック
async function reloadData() {
    currentRealmCode = DOM.realmSelect.value;
    DOM.loadingOverlay.classList.remove('hidden');
    DOM.progressBar.style.width = '0%';
    
    try {
        DOM.loadingText.textContent = "カテゴリ情報を取得中...";
        const presets = await fetchApi('https://api.nextmarket.games/l9asia/v1/sale/c2c/preset');
        if (!presets) throw new Error("Preset fetch failed");
        
        categoriesToFetch = [];
        presets.forEach(main => {
            if (main.subPresetList && main.subPresetList.length > 0) {
                main.subPresetList.forEach(sub => {
                    categoriesToFetch.push({ main: main.name, sub: sub.name, id: sub.id });
                });
            } else {
                categoriesToFetch.push({ main: main.name, sub: "すべて", id: main.id });
            }
        });
        
        allItemsData = [];
        const totalCats = categoriesToFetch.length;
        let completed = 0;
        let pageTasks = [];
        
        DOM.loadingText.textContent = "データの超高速取得中... (フェーズ1)";
        
        const fetchFirstPage = async (cat) => {
            const data = await fetchApi(`https://api.nextmarket.games/l9asia/v1/sale/c2c?page=0&size=500`, "POST", {
                realmCode: currentRealmCode, presetId: cat.id
            });
            if (data && data.content) {
                data.content.forEach(item => {
                    item.__main_cat = cat.main;
                    item.__sub_cat = cat.sub;
                });
                allItemsData.push(...data.content);
                
                const totalPages = Math.ceil((data.totalElements || 0) / 500);
                for (let p = 1; p < totalPages; p++) {
                    pageTasks.push({ main: cat.main, sub: cat.sub, id: cat.id, page: p });
                }
            }
            completed++;
            DOM.progressBar.style.width = `${(completed / totalCats) * 50}%`;
        };
        
        for (let i = 0; i < categoriesToFetch.length; i += 15) {
            const chunk = categoriesToFetch.slice(i, i + 15);
            await Promise.all(chunk.map(c => fetchFirstPage(c)));
        }
        
        if (pageTasks.length > 0) {
            DOM.loadingText.textContent = "追加データの取得中... (フェーズ2)";
            let pageCompleted = 0;
            const totalPageTasks = pageTasks.length;
            
            const fetchExtraPage = async (task) => {
                const data = await fetchApi(`https://api.nextmarket.games/l9asia/v1/sale/c2c?page=${task.page}&size=500`, "POST", {
                    realmCode: currentRealmCode, presetId: task.id
                });
                if (data && data.content) {
                    data.content.forEach(item => {
                        item.__main_cat = task.main;
                        item.__sub_cat = task.sub;
                    });
                    allItemsData.push(...data.content);
                }
                pageCompleted++;
                DOM.progressBar.style.width = `${50 + (pageCompleted / totalPageTasks) * 50}%`;
            };
            
            for (let i = 0; i < pageTasks.length; i += 15) {
                const chunk = pageTasks.slice(i, i + 15);
                await Promise.all(chunk.map(t => fetchExtraPage(t)));
            }
        }
        
        processItems();
        updateCategoryOptions();
        updateView();
        
    } catch (e) {
        console.error(e);
        alert("データ取得に失敗しました。");
    } finally {
        DOM.loadingOverlay.classList.add('hidden');
        const now = new Date();
        DOM.lastUpdated.textContent = `最終更新: ${now.toLocaleTimeString('ja-JP')}`;
    }
}

// 取得したアイテムのフォーマット整形
function processItems() {
    allItemsData.forEach(item => {
        const bg_color = item.backgroundColor || 'NONE';
        item.rarity_name = RARITY_COLORS[bg_color] || "不明";
        
        item.jpy_price = item.fiatPriceInfo?.price || 0;
        item.currency_type = item.fiatPriceInfo?.currencyType || 'JPY';
        item.usdt_price = item.cryptoPriceInfo?.price || 0;
        
        item.enhance_lvl = "+0";
        if (item.abilityOptionList) {
            const opt = item.abilityOptionList.find(o => o.code === "Enhance_LVL_NUM");
            if (opt) item.enhance_lvl = `+${parseInt(opt.value)}`;
        }
        item.item_name = item.item?.name || 'Unknown';
    });
}

// カテゴリセレクタの更新
function updateCategoryOptions() {
    const mains = new Set(allItemsData.map(d => d.__main_cat));
    DOM.mainCatSelect.innerHTML = '<option value="すべて">すべて</option>';
    Array.from(mains).sort().forEach(m => {
        if(m) DOM.mainCatSelect.add(new Option(m, m));
    });
    updateSubCategoryOptions();
}

function updateSubCategoryOptions() {
    const mainCat = DOM.mainCatSelect.value;
    DOM.subCatSelect.innerHTML = '<option value="すべて">すべて</option>';
    if (mainCat === "すべて") return;
    
    const subs = new Set(allItemsData.filter(d => d.__main_cat === mainCat).map(d => d.__sub_cat));
    Array.from(subs).sort().forEach(s => {
        if(s) DOM.subCatSelect.add(new Option(s, s));
    });
}

// UI更新処理
function updateView() {
    isJpyGlobal = document.getElementById('currencyJPY').checked;
    DOM.jpyRateContainer.style.display = isJpyGlobal ? 'flex' : 'none';
    const rate = parseFloat(DOM.jpyRate.value) || 157;
    
    const mainCat = DOM.mainCatSelect.value;
    const subCat = DOM.subCatSelect.value;
    const rarity = DOM.raritySelect.value;
    
    let filtered = allItemsData;
    
    if (mainCat !== "すべて") filtered = filtered.filter(d => d.__main_cat === mainCat);
    if (subCat !== "すべて") filtered = filtered.filter(d => d.__sub_cat === subCat);
    if (rarity !== "すべて") filtered = filtered.filter(d => d.rarity_name === rarity);
    
    // 価格の計算
    filtered.forEach(item => {
        if (isJpyGlobal) {
            item.display_price = item.currency_type === 'JPY' ? item.jpy_price : (item.usdt_price * rate);
        } else {
            item.display_price = item.usdt_price;
        }
    });
    
    filtered = filtered.filter(d => d.display_price > 0);
    
    // Summary
    const count = filtered.length;
    DOM.summaryCount.textContent = count.toLocaleString();
    if (count > 0) {
        const prices = filtered.map(d => d.display_price);
        const min = Math.min(...prices);
        const max = Math.max(...prices);
        DOM.summaryMin.textContent = formatPrice(min, isJpyGlobal);
        DOM.summaryMax.textContent = formatPrice(max, isJpyGlobal);
    } else {
        DOM.summaryMin.textContent = formatPrice(0, isJpyGlobal);
        DOM.summaryMax.textContent = formatPrice(0, isJpyGlobal);
    }
    
    // グループ化 (アイテム名 + レアリティ)
    const groupedMap = new Map();
    filtered.forEach(item => {
        const key = item.item_name + "::" + item.rarity_name;
        if (!groupedMap.has(key)) {
            groupedMap.set(key, {
                name: item.item_name, rarity: item.rarity_name, count: 0, min: Infinity, max: -Infinity, items: []
            });
        }
        const g = groupedMap.get(key);
        g.count++;
        if (item.display_price < g.min) g.min = item.display_price;
        if (item.display_price > g.max) g.max = item.display_price;
        g.items.push(item);
    });
    
    currentGroupedArr = Array.from(groupedMap.values());
    renderMainTable();
    
    // 詳細のクリア
    DOM.detailsTitle.textContent = "🔍 強化値内訳";
    DOM.detailsPlaceholder.classList.remove('hidden');
    DOM.detailsContent.classList.add('hidden');
    selectedItemName = null;
}

function renderMainTable() {
    currentGroupedArr.sort((a, b) => {
        let valA = a[currentSort.column];
        let valB = b[currentSort.column];
        
        if (currentSort.column === 'name') {
            return currentSort.asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        } else {
            return currentSort.asc ? (valA - valB) : (valB - valA);
        }
    });

    DOM.mainTableBody.innerHTML = '';
    currentGroupedArr.forEach(g => {
        const tr = document.createElement('tr');
        if (selectedItemName === g.name + "::" + g.rarity) {
            tr.classList.add('active-row');
        }
        tr.onclick = () => showDetails(g, tr);
        
        tr.innerHTML = `
            <td class="rarity-${g.rarity}">${g.name}</td>
            <td>${g.count.toLocaleString()}</td>
            <td>${formatPrice(g.min, isJpyGlobal)}</td>
            <td>${formatPrice(g.max, isJpyGlobal)}</td>
        `;
        DOM.mainTableBody.appendChild(tr);
    });
}

// 詳細ビューの描画
function showDetails(groupData, trElement) {
    selectedItemName = groupData.name + "::" + groupData.rarity;
    
    // アクティブラインのハイライト
    document.querySelectorAll('#mainTableBody tr').forEach(row => row.classList.remove('active-row'));
    if(trElement) trElement.classList.add('active-row');
    
    DOM.detailsTitle.innerHTML = `🔍 「<span class="rarity-${groupData.rarity}">${groupData.name}</span>」 の強化値内訳`;
    DOM.detailsPlaceholder.classList.add('hidden');
    DOM.detailsContent.classList.remove('hidden');
    
    const enhMap = new Map();
    groupData.items.forEach(item => {
        const lvl = item.enhance_lvl;
        if (!enhMap.has(lvl)) {
            enhMap.set(lvl, { level: lvl, count: 0, min: Infinity, max: -Infinity });
        }
        const e = enhMap.get(lvl);
        e.count++;
        if (item.display_price < e.min) e.min = item.display_price;
        if (item.display_price > e.max) e.max = item.display_price;
    });
    
    currentEnhArr = Array.from(enhMap.values());
    renderDetailsTable();
}

function renderDetailsTable() {
    currentEnhArr.sort((a, b) => {
        let valA = a[currentDetailsSort.column];
        let valB = b[currentDetailsSort.column];
        
        if (currentDetailsSort.column === 'level') {
            const numA = parseInt(a.level.replace('+', ''));
            const numB = parseInt(b.level.replace('+', ''));
            return currentDetailsSort.asc ? (numA - numB) : (numB - numA);
        } else {
            return currentDetailsSort.asc ? (valA - valB) : (valB - valA);
        }
    });

    DOM.detailsTableBody.innerHTML = '';
    currentEnhArr.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${e.level}</strong></td>
            <td>${e.count.toLocaleString()}</td>
            <td>${formatPrice(e.min, isJpyGlobal)}</td>
            <td>${formatPrice(e.max, isJpyGlobal)}</td>
        `;
        DOM.detailsTableBody.appendChild(tr);
    });
}

// ユーティリティ
function formatPrice(val, isJpy) {
    if (isJpy) {
        return `¥${Math.floor(val).toLocaleString()}`;
    } else {
        return `USDT ${val.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    }
}

// アプリ起動
initApp();
