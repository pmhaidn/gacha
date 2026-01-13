import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

# --- Cấu hình Trang ---
st.set_page_config(
    page_title="Hệ thống Phân tích Gacha",
    page_icon="📊",
    layout="wide"
)

# --- Tải Dữ liệu ---
@st.cache_data
def load_data(base_dir):
    dfs = {}
    files = {
        'gacha_card': 'gacha_card.csv',
        'gacha_history': 'gacha_history.csv',
        'inventory': 'user_card_inventory.csv',
        'profile': 'user_profile.csv'
    }
    
    # Xử lý file gacha_card.csv (file bị xoay)
    try:
        card_path = os.path.join(base_dir, 'gacha_card.csv')
        if os.path.exists(card_path):
            raw_card = pd.read_csv(card_path, header=None)
            df_card = raw_card.T
            df_card.columns = df_card.iloc[0]
            df_card = df_card[1:]
            dfs['gacha_card'] = df_card.reset_index(drop=True)
    except Exception as e:
        st.error(f"Lỗi tải gacha_card: {e}")

    # Tải các file còn lại
    for key, filename in files.items():
        if key == 'gacha_card':
            continue
        path = os.path.join(base_dir, filename)
        if os.path.exists(path):
            try:
                dfs[key] = pd.read_csv(path)
            except:
                try: 
                    dfs[key] = pd.read_csv(path, on_bad_lines='skip')
                except Exception as e:
                    st.error(f"Lỗi tải {filename}: {e}")
    
    # Tiền xử lý dữ liệu & Chuyển đổi múi giờ (UTC -> UTC+7)
    def to_vn_time(series):
        if series.dt.tz is None:
            series = series.dt.tz_localize('UTC')
        return series.dt.tz_convert('Asia/Ho_Chi_Minh')

    if 'gacha_history' in dfs:
        dfs['gacha_history']['created_at'] = pd.to_datetime(dfs['gacha_history']['created_at'])
        dfs['gacha_history']['created_at'] = to_vn_time(dfs['gacha_history']['created_at'])
        
    if 'inventory' in dfs:
        dfs['inventory']['created_at'] = pd.to_datetime(dfs['inventory']['created_at'])
        dfs['inventory']['updated_at'] = pd.to_datetime(dfs['inventory']['updated_at'])
        dfs['inventory']['created_at'] = to_vn_time(dfs['inventory']['created_at'])
        dfs['inventory']['updated_at'] = to_vn_time(dfs['inventory']['updated_at'])
        
    if 'profile' in dfs:
         if 'updated_at' in dfs['profile'].columns:
            dfs['profile']['updated_at'] = pd.to_datetime(dfs['profile']['updated_at'])
            dfs['profile']['updated_at'] = to_vn_time(dfs['profile']['updated_at'])

    return dfs

base_dir = '.'
dfs = load_data(base_dir)

if not all(k in dfs for k in ['gacha_card', 'gacha_history', 'inventory', 'profile']):
    st.error("Thiếu các file dữ liệu cần thiết.")
    st.stop()

# --- Gộp dữ liệu ---
# Lịch sử + Thông tin thẻ
history_merged = pd.merge(
    dfs['gacha_history'],
    dfs['gacha_card'],
    left_on='card_id',
    right_on='id',
    how='left',
    suffixes=('', '_card')
)

# Kho đồ + Thông tin thẻ
inventory_merged = pd.merge(
    dfs['inventory'],
    dfs['gacha_card'],
    left_on='card_id',
    right_on='id',
    how='left',
    suffixes=('', '_card')
)

# --- Sidebar: Điều hướng & Bộ lọc ---
st.sidebar.header("🛠️ Công cụ")

# Chế độ xem
view_mode = st.sidebar.radio("Chọn chế độ xem:", ["👤 Tra cứu User", "🏆 Thống kê Server", "🚨 Fraud Detection"])

# --- Lọc User có UR (Chuẩn bị dữ liệu) ---
# Xác định danh sách User có UR
inventory_ur = inventory_merged[inventory_merged['tier'] == 'UR']
users_with_ur = inventory_ur['user_id'].unique().tolist()

if view_mode == "👤 Tra cứu User":
    st.sidebar.markdown("---")
    st.sidebar.subheader("Bộ Lọc User")
    
    filter_ur_only = st.sidebar.checkbox("💎 Chỉ hiện User có thẻ UR")
    
    # Logic lọc danh sách User
    all_users = dfs['profile']['user_id'].unique().tolist()
    
    if filter_ur_only:
        # Chỉ lấy user có trong danh sách users_with_ur
        available_users = [u for u in all_users if u in users_with_ur]
        if not available_users:
            st.sidebar.warning("Không có User nào sở hữu thẻ UR.")
    else:
        available_users = all_users

    # Tìm kiếm
    user_search = st.sidebar.text_input("🔍 Tìm User ID hoặc SĐT")
    
    selected_user_id = None
    if user_search:
        # Tìm trong dataframe gốc để lấy thông tin map
        mask_id = dfs['profile']['user_id'].astype(str).str.contains(user_search, case=False)
        mask_phone = dfs['profile']['phone'].astype(str).str.contains(user_search, case=False)
        
        found_df = dfs['profile'][mask_id | mask_phone]
        
        # Lọc lại theo filter UR nếu cần
        if filter_ur_only:
            found_ids = found_df['user_id'].tolist()
            valid_ids = [uid for uid in found_ids if uid in users_with_ur]
            if valid_ids:
                selected_user_id = st.sidebar.selectbox("Kết quả tìm kiếm", valid_ids)
            else:
                st.sidebar.warning("Tìm thấy User nhưng họ không có thẻ UR.")
        else:
            if not found_df.empty:
                selected_user_id = st.sidebar.selectbox("Kết quả tìm kiếm", found_df['user_id'].tolist())
            else:
                st.sidebar.warning("Không tìm thấy user.")
    else:
        # Dropdown mặc định
        if available_users:
            # Ưu tiên hiển thị user có nhiều spins nhất trong danh sách đã lọc
            # Tạo map spin count
            spin_map = dfs['profile'].set_index('user_id')['total_spins'].to_dict()
            # Sort available_users by spins desc
            available_users.sort(key=lambda x: spin_map.get(x, 0), reverse=True)
            
            selected_user_id = st.sidebar.selectbox("Chọn User", available_users)
        else:
            st.warning("Danh sách User trống theo bộ lọc hiện tại.")

    # --- Dashboard Cá nhân (Code cũ được giữ lại và thụt lề) ---
    if selected_user_id:
        user_profile = dfs['profile'][dfs['profile']['user_id'] == selected_user_id].iloc[0]
        st.markdown(f"### 👤 Hồ sơ User: `{selected_user_id}`")
        
        # Header Info
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📱 SĐT", str(user_profile.get('phone', 'N/A')))
        c2.metric("🎲 Lượt quay", user_profile.get('total_spins', 0))
        c3.metric("⚠️ Pity", user_profile.get('pity_count', 0))
        c4.metric("🕒 Update (VN)", str(user_profile.get('updated_at', 'N/A'))[:19])

        # NEW TABS STRUCTURE
        tab_overview, tab_inv, tab_hist = st.tabs([
            "📊 Thống kê Tổng quan", 
            "📦 Kho thẻ (Hiện tại)", 
            "📜 Gacha History (Full)"
        ])

        # --- TAB 1: TỔNG QUAN ---
        with tab_overview:
            st.subheader("Báo cáo Tổng hợp")
            
            # 1. Thống kê số lượng thẻ theo hạng
            user_inv = inventory_merged[inventory_merged['user_id'] == selected_user_id]
            
            # Count by Tier
            tier_counts = user_inv.groupby('tier')['quantity'].sum()
            t_r = tier_counts.get('R', 0)
            t_sr = tier_counts.get('SR', 0)
            t_ssr = tier_counts.get('SSR', 0)
            t_ur = tier_counts.get('UR', 0)
            
            col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
            col_stat1.metric("Thẻ R", int(t_r))
            col_stat2.metric("Thẻ SR", int(t_sr))
            col_stat3.metric("Thẻ SSR", int(t_ssr))
            col_stat4.metric("Thẻ UR (Đã nhận)", int(t_ur))
            
            st.divider()
            
            # 2. Thống kê Bộ sưu tập (Logic cũ)
            all_cards = dfs['gacha_card']
            total_collections_owned = 0
            
            if 'character_id' in all_cards.columns:
                grouped = all_cards.groupby('character_id')
                for char_id, group in grouped:
                    required_cards = group[group['tier'] != 'UR']
                    if required_cards.empty: continue
                    required_ids = set(required_cards['id'])
                    # Check kho
                    owned_in_group = user_inv[user_inv['card_id'].isin(required_ids)]
                    owned_ids = set(owned_in_group['card_id'])
                    if required_ids.issubset(owned_ids):
                        total_collections_owned += 1
            
            c_coll1, c_coll2 = st.columns([1, 3])
            c_coll1.metric("🏆 Số Bộ sưu tập hoàn thành", total_collections_owned, 
                         help="Số lượng nhân vật mà user sở hữu đủ tất cả thẻ R, SR, SSR.")
            
            with c_coll2:
                st.info("💡 **Ghi chú**: Số lượng thẻ UR thực tế nhận được thường liên quan mật thiết đến số bộ sưu tập đã hoàn thành (nếu có cơ chế đổi thưởng).")

        # --- TAB 2: KHO THẺ HIỆN TẠI (Theo Nhân vật) ---
        with tab_inv:
            st.subheader("📦 Kho thẻ theo Nhân vật")
            st.info("💡 Click vào từng nhân vật để xem chi tiết các thẻ đang sở hữu.")
            
            if not user_inv.empty and 'character_id' in user_inv.columns:
                try:
                    # Chuẩn bị dữ liệu thẻ hệ thống với character_id
                    all_cards_sys = dfs['gacha_card'].copy()
                    
                    # Tạo mapping character_id -> tên nhân vật (lấy từ thẻ UR hoặc thẻ đầu tiên)
                    def get_char_display_name(char_id, cards_df):
                        char_cards = cards_df[cards_df['character_id'] == char_id]
                        if char_cards.empty:
                            return "Unknown"
                        # Ưu tiên lấy từ thẻ UR (có tên đầy đủ)
                        ur_cards = char_cards[char_cards['tier'] == 'UR']
                        if not ur_cards.empty:
                            name = str(ur_cards.iloc[0]['name'])
                            # Bỏ phần "UR01" ở cuối
                            return name.replace(' UR01', '').replace(' UR', '').strip()
                        # Fallback: lấy từ thẻ đầu tiên
                        name = str(char_cards.iloc[0]['name'])
                        return name.split()[0] if name else "Unknown"
                    
                    # Tạo bảng thống kê theo character_id
                    char_stats = user_inv.groupby(['character_id', 'tier'])['quantity'].sum().unstack(fill_value=0)
                    char_stats['Tổng thẻ'] = char_stats.sum(axis=1)
                    
                    # Sắp xếp cột
                    desired_cols = ['R', 'SR', 'SSR', 'UR', 'Tổng thẻ']
                    for c in desired_cols:
                        if c not in char_stats.columns:
                            char_stats[c] = 0
                    
                    char_stats = char_stats[desired_cols].sort_values('Tổng thẻ', ascending=False)
                    
                    # Render expander cho từng nhân vật (theo character_id)
                    for char_id in char_stats.index:
                        row = char_stats.loc[char_id]
                        
                        # Lấy tên hiển thị của nhân vật
                        char_display_name = get_char_display_name(char_id, all_cards_sys)
                        
                        # Tạo summary cho expander title
                        tier_summary = f"R:{int(row['R'])} | SR:{int(row['SR'])} | SSR:{int(row['SSR'])} | UR:{int(row['UR'])}"
                        total = int(row['Tổng thẻ'])
                        
                        # Lấy thẻ của nhân vật trong hệ thống (theo character_id)
                        char_universe = all_cards_sys[all_cards_sys['character_id'] == char_id]
                        user_owned_ids = set(user_inv[user_inv['character_id'] == char_id]['card_id'].tolist())
                        
                        # Đếm owned/missing
                        owned_count = len(char_universe[char_universe['id'].isin(user_owned_ids)])
                        missing_count = len(char_universe[~char_universe['id'].isin(user_owned_ids)])
                        
                        # Icon dựa trên trạng thái
                        if missing_count == 0:
                            icon = "🏆"  # Hoàn thành bộ sưu tập
                        elif owned_count > 0:
                            icon = "📦"  # Đang sưu tập
                        else:
                            icon = "❓"  # Chưa có gì
                        
                        expander_title = f"{icon} **{char_display_name}** — {tier_summary} — Tổng: {total} thẻ"
                        
                        with st.expander(expander_title):
                            # Lấy chi tiết thẻ đang có của nhân vật này từ inventory của user
                            char_inventory = user_inv[user_inv['character_id'] == char_id].copy()
                            
                            if not char_inventory.empty:
                                # Hiển thị các thẻ đang sở hữu với đầy đủ thông tin
                                display_cols = ['name', 'tier', 'quantity', 'serial_number', 'created_at', 'updated_at']
                                valid_cols = [c for c in display_cols if c in char_inventory.columns]
                                
                                char_inventory = char_inventory[valid_cols].sort_values('tier', ascending=True)
                                
                                st.dataframe(
                                    char_inventory,
                                    column_config={
                                        "name": "Tên thẻ",
                                        "tier": "Hạng",
                                        "quantity": "Số lượng",
                                        "serial_number": "Serial",
                                        "created_at": st.column_config.DatetimeColumn("Thời gian tạo", format="YYYY-MM-DD HH:mm:ss"),
                                        "updated_at": st.column_config.DatetimeColumn("Cập nhật", format="YYYY-MM-DD HH:mm:ss")
                                    },
                                    hide_index=True,
                                    width="stretch"
                                )
                            else:
                                st.info("Chưa sở hữu thẻ nào của nhân vật này.")
                                
                except Exception as e:
                    st.error(f"Lỗi xử lý kho thẻ: {e}")
            else:
                st.warning("Kho thẻ trống hoặc thiếu dữ liệu character_id.")

        # --- TAB 3: GACHA HISTORY (FULL) ---
        # --- TAB 3: GACHA HISTORY (FULL) ---
        with tab_hist:
            st.subheader("Lịch sử Gacha")
            
            user_hist = history_merged[history_merged['user_id'] == selected_user_id].copy()
            
            if not user_hist.empty:
                # Sort descending
                user_hist = user_hist.sort_values('created_at', ascending=False)
                
                # Checkbox Gom nhóm
                col_opt, _ = st.columns([1, 2])
                with col_opt:
                    use_grouping = st.checkbox("📂 Gom nhóm theo thời gian (Group by Time)", value=True)
                
                if use_grouping:
                    # Lấy danh sách thời gian duy nhất
                    unique_timestamps = user_hist['created_at'].unique()
                    # Mặc dù đã sort df, unique() có thể không giữ thứ tự, nên sort lại cho chắc
                    # unique_timestamps là numpy array of Timestamps
                    unique_timestamps = sorted(unique_timestamps, reverse=True)
                    
                    # Pagination / Limit
                    batch_limit = 50
                    if len(unique_timestamps) > batch_limit:
                        st.warning(f"⚠️ Đang hiển thị {batch_limit} phiên gần nhất (Tổng: {len(unique_timestamps)} phiên). Tắt chế độ gom nhóm để xem toàn bộ.")
                        display_timestamps = unique_timestamps[:batch_limit]
                    else:
                        display_timestamps = unique_timestamps
                    
                    # Loop render expanders
                    for ts in display_timestamps:
                        # Filter batch
                        batch_df = user_hist[user_hist['created_at'] == ts]
                        
                        # Info for Title
                        count = len(batch_df)
                        tier_counts = batch_df['tier'].value_counts()
                        # Format: "UR: 1, SSR: 2..."
                        tier_summary = ", ".join([f"{t}: {c}" for t, c in tier_counts.items()])
                        
                        time_str = ts.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Determine if this batch has Pity or Merge
                        has_pity = batch_df['is_pity_reward'].any()
                        has_merge = batch_df['is_merged'].any()
                        
                        icon = "🎰" # Slot machine for gacha
                        if has_merge: icon = "🔄"
                        if has_pity: icon = "🎁"
                        
                        expander_title = f"{icon} {time_str} | {count} Thẻ | {tier_summary}"
                        
                        with st.expander(expander_title):
                            cols_mini = ['name', 'tier', 'is_merged', 'is_pity_reward', 'banner_id']
                            valid_cols_mini = [c for c in cols_mini if c in batch_df.columns]
                            
                            st.dataframe(
                                batch_df[valid_cols_mini],
                                column_config={
                                    "name": "Tên thẻ",
                                    "tier": "Hạng",
                                    "is_merged": st.column_config.CheckboxColumn("Merge?", default=False),
                                    "is_pity_reward": st.column_config.CheckboxColumn("Pity?", default=False),
                                },
                                width="stretch",
                                hide_index=True
                            )
                            
                            # --- COLLECTION SNAPSHOT AT THIS TIMESTAMP (Show for ALL expanders) ---
                            st.markdown("---")
                            st.markdown("### 📦 Thống kê Bộ sưu tập (tại thời điểm này)")
                            
                            # Get all history UP TO AND INCLUDING this timestamp
                            history_until_now = user_hist[user_hist['created_at'] <= ts]
                            
                            # Merge with card info to get tier and character_id
                            if not history_until_now.empty:
                                hist_with_cards = history_until_now.merge(
                                    dfs['gacha_card'][['id', 'tier', 'character_id', 'name']].rename(columns={'id': 'card_id', 'name': 'card_name'}),
                                    on='card_id',
                                    how='left',
                                    suffixes=('', '_card')
                                )
                            else:
                                hist_with_cards = pd.DataFrame()
                            
                            # Build collection summary for all characters
                            all_char_ids = dfs['gacha_card']['character_id'].unique()
                            collection_data = []
                            
                            total_r_qty = 0
                            total_sr_qty = 0
                            completed_count = 0
                            
                            for char_id in all_char_ids:
                                # Get all cards for this character (excluding UR)
                                char_cards = dfs['gacha_card'][
                                    (dfs['gacha_card']['character_id'] == char_id) & 
                                    (dfs['gacha_card']['tier'] != 'UR')
                                ]
                                
                                if char_cards.empty:
                                    continue
                                
                                # Get character name
                                ur_card = dfs['gacha_card'][
                                    (dfs['gacha_card']['character_id'] == char_id) & 
                                    (dfs['gacha_card']['tier'] == 'UR')
                                ]
                                if not ur_card.empty:
                                    char_name = ur_card.iloc[0]['name'].replace(' UR01', '').replace(' UR', '').strip()
                                else:
                                    char_name = char_cards.iloc[0]['name'].split()[0]
                                
                                # Filter history for this character
                                if not hist_with_cards.empty:
                                    char_hist = hist_with_cards[hist_with_cards['character_id'] == char_id]
                                else:
                                    char_hist = pd.DataFrame()
                                
                                # Count cards by tier
                                r_cards = char_cards[char_cards['tier'] == 'R']
                                sr_cards = char_cards[char_cards['tier'] == 'SR']
                                ssr_cards = char_cards[char_cards['tier'] == 'SSR']
                                
                                # Count quantities and track missing cards
                                r_qty = 0
                                sr_qty = 0
                                ssr_qty = 0
                                r_unique = 0
                                sr_unique = 0
                                ssr_unique = 0
                                missing_r = []
                                missing_sr = []
                                missing_ssr = []
                                
                                for _, card in r_cards.iterrows():
                                    if not char_hist.empty:
                                        qty = len(char_hist[char_hist['card_id'] == card['id']])
                                        r_qty += qty
                                        if qty >= 1:
                                            r_unique += 1
                                        else:
                                            missing_r.append(card['name'])
                                    else:
                                        missing_r.append(card['name'])
                                
                                for _, card in sr_cards.iterrows():
                                    if not char_hist.empty:
                                        qty = len(char_hist[char_hist['card_id'] == card['id']])
                                        sr_qty += qty
                                        if qty >= 1:
                                            sr_unique += 1
                                        else:
                                            missing_sr.append(card['name'])
                                    else:
                                        missing_sr.append(card['name'])
                                
                                for _, card in ssr_cards.iterrows():
                                    if not char_hist.empty:
                                        qty = len(char_hist[char_hist['card_id'] == card['id']])
                                        ssr_qty += qty
                                        if qty >= 1:
                                            ssr_unique += 1
                                        else:
                                            missing_ssr.append(card['name'])
                                    else:
                                        missing_ssr.append(card['name'])
                                
                                total_r_qty += r_qty
                                total_sr_qty += sr_qty
                                
                                r_total = len(r_cards)
                                sr_total = len(sr_cards)
                                ssr_total = len(ssr_cards)
                                
                                is_complete = (r_unique >= r_total and sr_unique >= sr_total and ssr_unique >= ssr_total)
                                if is_complete:
                                    completed_count += 1
                                
                                # Build missing cards string
                                missing_list = []
                                if missing_r:
                                    missing_list.extend(missing_r)
                                if missing_sr:
                                    missing_list.extend(missing_sr)
                                if missing_ssr:
                                    missing_list.extend(missing_ssr)
                                missing_str = ', '.join(missing_list) if missing_list else '✅ Đủ'
                                
                                collection_data.append({
                                    'Nhân vật': char_name,
                                    'R': f"{r_unique}/{r_total}",
                                    'SR': f"{sr_unique}/{sr_total}",
                                    'SSR': f"{ssr_unique}/{ssr_total}",
                                    'Thiếu': missing_str,
                                    'Hoàn thành': '✅' if is_complete else '❌',
                                    'r_qty': r_qty,
                                    'sr_qty': sr_qty,
                                    'r_unique': r_unique,
                                    'sr_unique': sr_unique,
                                    'ssr_unique': ssr_unique,
                                    'r_total': r_total,
                                    'sr_total': sr_total,
                                    'ssr_total': ssr_total,
                                    'is_complete': is_complete
                                })
                            
                            # Summary row
                            potential_sr = total_r_qty // 3
                            potential_ssr = total_sr_qty // 3
                            
                            sum_col1, sum_col2, sum_col3 = st.columns(3)
                            with sum_col1:
                                st.metric("Bộ sưu tập hoàn thành", f"{completed_count}/{len(collection_data)}")
                            with sum_col2:
                                st.metric("Tổng R", f"{total_r_qty}", delta=f"→ {potential_sr} SR")
                            with sum_col3:
                                st.metric("Tổng SR", f"{total_sr_qty}", delta=f"→ {potential_ssr} SSR")
                            
                            # Show compact table with missing cards
                            display_df = pd.DataFrame(collection_data)[['Nhân vật', 'R', 'SR', 'SSR', 'Thiếu', 'Hoàn thành']]
                            st.dataframe(
                                display_df, 
                                hide_index=True, 
                                width="stretch",
                                column_config={
                                    "Thiếu": st.column_config.TextColumn("Thẻ thiếu", width="large")
                                }
                            )
                            
                            # Show detailed card breakdown (expandable)
                            with st.expander("📋 Chi tiết từng thẻ (xem số lượng để merge)"):
                                st.caption("💡 Merge: Cần 3 thẻ giống nhau. Thẻ có ≥3 có thể merge.")
                                
                                # Build detailed card list
                                detailed_cards = []
                                for char_id in all_char_ids:
                                    char_cards_all = dfs['gacha_card'][
                                        (dfs['gacha_card']['character_id'] == char_id) & 
                                        (dfs['gacha_card']['tier'] != 'UR')
                                    ]
                                    
                                    if char_cards_all.empty:
                                        continue
                                    
                                    # Get character name
                                    ur_card = dfs['gacha_card'][
                                        (dfs['gacha_card']['character_id'] == char_id) & 
                                        (dfs['gacha_card']['tier'] == 'UR')
                                    ]
                                    if not ur_card.empty:
                                        char_name = ur_card.iloc[0]['name'].replace(' UR01', '').replace(' UR', '').strip()
                                    else:
                                        char_name = char_cards_all.iloc[0]['name'].split()[0]
                                    
                                    # Filter history for this character
                                    if not hist_with_cards.empty:
                                        char_hist_detail = hist_with_cards[hist_with_cards['character_id'] == char_id]
                                    else:
                                        char_hist_detail = pd.DataFrame()
                                    
                                    for _, card in char_cards_all.iterrows():
                                        if not char_hist_detail.empty:
                                            qty = len(char_hist_detail[char_hist_detail['card_id'] == card['id']])
                                        else:
                                            qty = 0
                                        
                                        can_merge = qty // 3
                                        merge_status = f"✅ Merge được {can_merge}" if can_merge > 0 else ("⚠️ Thiếu" if qty == 0 else "")
                                        
                                        detailed_cards.append({
                                            'Nhân vật': char_name,
                                            'Tên thẻ': card['name'],
                                            'Tier': card['tier'],
                                            'Số lượng': qty,
                                            'Merge': merge_status
                                        })
                                
                                detailed_df = pd.DataFrame(detailed_cards)
                                
                                # Filter options
                                filter_col1, filter_col2 = st.columns(2)
                                with filter_col1:
                                    filter_tier = st.multiselect("Lọc Tier:", ['R', 'SR', 'SSR'], default=['R', 'SR', 'SSR'], key=f"tier_filter_{ts}")
                                with filter_col2:
                                    filter_mergeable = st.checkbox("Chỉ hiện thẻ merge được (≥3)", value=True, key=f"merge_filter_{ts}")
                                
                                filtered_df = detailed_df[detailed_df['Tier'].isin(filter_tier)]
                                if filter_mergeable:
                                    filtered_df = filtered_df[filtered_df['Số lượng'] >= 3]
                                
                                st.dataframe(
                                    filtered_df,
                                    column_config={
                                        "Nhân vật": st.column_config.TextColumn("Nhân vật", width="small"),
                                        "Tên thẻ": st.column_config.TextColumn("Tên thẻ", width="medium"),
                                        "Tier": st.column_config.TextColumn("Tier", width="small"),
                                        "Số lượng": st.column_config.NumberColumn("SL", format="%d", width="small"),
                                        "Merge": st.column_config.TextColumn("Merge", width="medium")
                                    },
                                    hide_index=True,
                                    width="stretch"
                                )
                                
                                # Summary of mergeable cards
                                mergeable_r = detailed_df[(detailed_df['Tier'] == 'R') & (detailed_df['Số lượng'] >= 3)]
                                mergeable_sr = detailed_df[(detailed_df['Tier'] == 'SR') & (detailed_df['Số lượng'] >= 3)]
                                
                                if not mergeable_r.empty or not mergeable_sr.empty:
                                    st.markdown("**🔄 Thẻ có thể Merge:**")
                                    if not mergeable_r.empty:
                                        r_list = [f"{row['Tên thẻ']} (x{row['Số lượng']}→{row['Số lượng']//3} SR)" for _, row in mergeable_r.iterrows()]
                                        st.markdown(f"  - **R→SR**: {', '.join(r_list)}")
                                    if not mergeable_sr.empty:
                                        sr_list = [f"{row['Tên thẻ']} (x{row['Số lượng']}→{row['Số lượng']//3} SSR)" for _, row in mergeable_sr.iterrows()]
                                        st.markdown(f"  - **SR→SSR**: {', '.join(sr_list)}")
                else:
                    # View dạng bảng phẳng (Cũ)
                    cols_to_show = ['created_at', 'name', 'tier', 'is_merged', 'is_pity_reward', 'banner_id', 'card_id']
                    valid_cols = [c for c in cols_to_show if c in user_hist.columns]
                    
                    st.dataframe(
                        user_hist[valid_cols],
                        column_config={
                            "created_at": st.column_config.DatetimeColumn("Thời gian (UTC+7)", format="YYYY-MM-DD HH:mm:ss"),
                            "name": "Tên thẻ",
                            "tier": "Hạng",
                            "is_merged": st.column_config.CheckboxColumn("Là Merge?", default=False),
                            "is_pity_reward": st.column_config.CheckboxColumn("Là Pity?", default=False),
                        },
                        width="stretch",
                        height=600
                    )
                    st.caption(f"Tổng số bản ghi: {len(user_hist)}. Dữ liệu bao gồm cả quay thường và merge.")
            else:
                st.info("Không có lịch sử.")

elif view_mode == "🏆 Thống kê Server":
    st.title("🏆 Bảng Xếp Hạng & Thống Kê UR")
    
    tab_ur_rank, tab_first_ur = st.tabs(["💎 Top User Sở Hữu UR", "dt 150 UR Đầu Tiên"])
    
    # Feature 1: Top User by UR Count
    with tab_ur_rank:
        st.subheader("Bảng Xếp Hạng: Ai đang giữ nhiều UR nhất?")
        if not inventory_ur.empty:
            ur_counts = inventory_ur.groupby('user_id')['quantity'].sum().reset_index()
            ur_counts.columns = ['User ID', 'Tổng số UR']
            
            # Merge with profile to get phone/spins info
            ur_leaderboard = pd.merge(ur_counts, dfs['profile'], left_on='User ID', right_on='user_id', how='left')
            ur_leaderboard = ur_leaderboard[['User ID', 'Tổng số UR', 'phone', 'total_spins']]
            ur_leaderboard = ur_leaderboard.sort_values('Tổng số UR', ascending=False).reset_index(drop=True)
            ur_leaderboard.index += 1 # 1-based index
            
            st.dataframe(ur_leaderboard, width="stretch")
        else:
            st.info("Chưa có thẻ UR nào được sở hữu trên server.")

    # Feature 2: First 150 URs History
    with tab_first_ur:
        st.subheader("Lịch sử 150 Thẻ UR xuất hiện đầu tiên")
        st.caption("Danh sách này giúp Audit xem ai là những người may mắn (hoặc đáng ngờ) sở hữu UR sớm nhất.")
        
        # Filter history for URs
        # Note: History excludes current inventory quantity, it's just drops.
        ur_history = history_merged[history_merged['tier'] == 'UR'].sort_values('created_at', ascending=True)
        
        if not ur_history.empty:
            first_150 = ur_history.head(150).reset_index(drop=True)
            first_150.index += 1
            
            display_cols = ['created_at', 'user_id', 'name', 'is_pity_reward', 'is_merged']
            st.dataframe(
                first_150[display_cols],
                column_config={
                    "created_at": st.column_config.DatetimeColumn("Thời gian (UTC+7)", format="YYYY-MM-DD HH:mm:ss"),
                    "user_id": "Người sở hữu",
                    "name": "Tên thẻ UR",
                    "is_pity_reward": "Từ Pity?",
                    "is_merged": "Từ Merge?"
                },
                width="stretch",
                height=600
            )
        else:
            st.info("Chưa có thẻ UR nào xuất hiện trong lịch sử.")

elif view_mode == "🚨 Fraud Detection":
    st.title("🚨 Hệ thống Phát hiện Gian lận & Kiểm tra Dữ liệu")
    
    st.info("""
    💡 **Business Rules đã xác nhận:**
    - **Merge**: 3R giống → 1 SR, 3SR giống → 1 SSR
    - **Pity**: Mỗi 40 spins → thưởng 1 SSR
    - **Collection**: Hoàn thành 3R + 2SR + 1SSR của 1 nhân vật → 1 UR giới hạn
    - **UR CHỈ NHẬN ĐƯỢC TỪ COLLECTION REWARD**
    """)
    
    # Load fraud detection results if available
    fraud_results_path = '/Users/mac/Downloads/doc/fraud_detection_results.csv'
    fraud_summary_path = '/Users/mac/Downloads/doc/fraud_user_summary.csv'
    
    try:
        fraud_results = pd.read_csv(fraud_results_path)
        fraud_summary = pd.read_csv(fraud_summary_path)
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            high_count = len(fraud_results[fraud_results['severity'] == 'HIGH'])
            st.metric("🔴 HIGH Risk", high_count)
        with col2:
            medium_count = len(fraud_results[fraud_results['severity'] == 'MEDIUM'])
            st.metric("🟠 MEDIUM Risk", medium_count)
        with col3:
            low_count = len(fraud_results[fraud_results['severity'] == 'LOW'])
            st.metric("🟡 LOW Risk", low_count)
        with col4:
            total_users = fraud_summary['user_id'].nunique()
            st.metric("👥 Tổng User nghi ngờ", total_users)
        
        st.divider()
        
        # Tabs for different views
        tab_summary, tab_detail, tab_by_flag = st.tabs([
            "📊 Tổng quan theo User", 
            "📋 Chi tiết tất cả", 
            "🏷️ Theo loại Flag"
        ])
        
        with tab_summary:
            st.subheader("Top User có Risk Score cao nhất")
            
            # Filter options
            col_filter1, col_filter2 = st.columns(2)
            with col_filter1:
                severity_filter = st.multiselect(
                    "Lọc theo Severity",
                    ['HIGH', 'MEDIUM', 'LOW'],
                    default=['HIGH', 'MEDIUM']
                )
            with col_filter2:
                min_score = st.number_input("Risk Score tối thiểu", min_value=0, value=5)
            
            filtered_summary = fraud_summary[
                (fraud_summary['max_severity'].isin(severity_filter)) &
                (fraud_summary['risk_score'] >= min_score)
            ]
            
            if not filtered_summary.empty:
                # Add phone info from profile
                summary_with_phone = pd.merge(
                    filtered_summary,
                    dfs['profile'][['user_id', 'phone', 'total_spins']],
                    on='user_id',
                    how='left'
                )
                
                st.dataframe(
                    summary_with_phone[['user_id', 'phone', 'total_spins', 'flags', 'risk_score', 'max_severity']],
                    column_config={
                        "user_id": "User ID",
                        "phone": "SĐT",
                        "total_spins": "Total Spins",
                        "flags": "Flags",
                        "risk_score": st.column_config.ProgressColumn("Risk Score", max_value=50),
                        "max_severity": "Severity"
                    },
                    width="stretch",
                    height=500
                )
                
                st.caption(f"Hiển thị {len(summary_with_phone)} users")
            else:
                st.success("✅ Không có user nào khớp với bộ lọc!")
        
        with tab_detail:
            st.subheader("Chi tiết tất cả các bản ghi nghi ngờ")
            
            # Search by user ID
            search_user = st.text_input("🔍 Tìm theo User ID")
            
            detail_df = fraud_results.copy()
            if search_user:
                detail_df = detail_df[detail_df['user_id'].str.contains(search_user, case=False)]
            
            # Display
            display_cols = ['user_id', 'flag', 'severity', 'detail']
            if 'history_total' in detail_df.columns:
                display_cols.extend(['history_total', 'inventory_total', 'diff'])
            
            valid_cols = [c for c in display_cols if c in detail_df.columns]
            
            st.dataframe(
                detail_df[valid_cols].sort_values('severity', ascending=True),
                column_config={
                    "user_id": "User ID",
                    "flag": "Flag",
                    "severity": "Severity",
                    "detail": st.column_config.TextColumn("Chi tiết", width="large"),
                    "history_total": "History Total",
                    "inventory_total": "Inventory Total",
                    "diff": "Chênh lệch"
                },
                width="stretch",
                height=600
            )
        
        with tab_by_flag:
            st.subheader("Phân tích theo loại Flag")
            
            # Flag distribution
            flag_counts = fraud_results['flag'].value_counts().reset_index()
            flag_counts.columns = ['Flag', 'Count']
            
            import plotly.express as px
            fig = px.pie(flag_counts, values='Count', names='Flag', 
                        title='Phân bố các loại Flag')
            st.plotly_chart(fig, use_container_width=True)
            
            # Flag descriptions
            flag_descriptions = {
                'INV_HISTORY_MISMATCH': '🔴 Số thẻ trong kho > số thẻ từ lịch sử - Có thẻ không rõ nguồn gốc',
                'UR_WITHOUT_COLLECTION': '🔴 Có UR nhưng chưa hoàn thành bộ sưu tập - UR chỉ nhận được từ collection',
                'EXCESSIVE_UR_RATE': '🟠 Tỷ lệ UR quá cao so với bình thường',
                'MISSING_HISTORY': '🟠 Có thẻ trong kho nhưng không có lịch sử - Có thể từ merge hoặc bug',
                'NEGATIVE_INVENTORY': '🔴 Số lượng thẻ âm - Bug hoặc manipulation',
                'BURST_ACTIVITY': '🟡 Hoạt động bất thường trong thời gian ngắn',
                'IMPOSSIBLE_MERGE': '🟠 Có SR/SSR nhiều hơn số có thể merge được'
            }
            
            st.markdown("### 📖 Giải thích các Flag:")
            for flag, desc in flag_descriptions.items():
                if flag in fraud_results['flag'].values:
                    count = len(fraud_results[fraud_results['flag'] == flag])
                    st.markdown(f"- **{flag}** ({count} records): {desc}")
            
            # Select flag to view details
            st.divider()
            selected_flag = st.selectbox("Xem chi tiết theo Flag:", fraud_results['flag'].unique())
            
            flag_detail = fraud_results[fraud_results['flag'] == selected_flag]
            
            st.dataframe(
                flag_detail[['user_id', 'severity', 'detail']],
                column_config={
                    "user_id": "User ID",
                    "severity": "Severity",
                    "detail": st.column_config.TextColumn("Chi tiết", width="large")
                },
                width="stretch",
                height=400
            )
        
    except FileNotFoundError:
        st.warning("⚠️ Chưa có kết quả phát hiện gian lận. Vui lòng chạy script `fraud_detection.py` trước.")
        
        st.code("""
# Chạy lệnh này trong terminal:
./venv/bin/python fraud_detection.py
        """, language="bash")
        
        if st.button("🔄 Chạy Fraud Detection ngay"):
            import subprocess
            with st.spinner("Đang phân tích dữ liệu..."):
                result = subprocess.run(
                    ['./venv/bin/python', 'fraud_detection.py'],
                    cwd='/Users/mac/Downloads/doc',
                    capture_output=True,
                    text=True
                )
                st.code(result.stdout)
                if result.returncode == 0:
                    st.success("✅ Hoàn thành! Refresh trang để xem kết quả.")
                    st.rerun()
                else:
                    st.error(f"Lỗi: {result.stderr}")

