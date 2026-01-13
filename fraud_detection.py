"""
Gacha Fraud Detection & Data Audit Module
==========================================
Phát hiện gian lận và kiểm tra dữ liệu không khớp trong hệ thống Gacha.

Business Rules (Confirmed):
- Daily Free Spins: 10 lượt/ngày
- Merge: 3R giống -> 1 SR ngẫu nhiên, 3SR giống -> 1 SSR ngẫu nhiên
- Pity: Mỗi 40 spins -> thưởng 1 SSR (KHÔNG PHẢI UR)
- Collection: Hoàn thành 3R + 2SR + 1SSR của 1 nhân vật -> 1 UR giới hạn
- UR CHỈ NHẬN ĐƯỢC TỪ COLLECTION REWARD
- Rates: R(60%), SR(30%), SSR(7%), UR(3%)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any
from collections import defaultdict

# ============================================================================
# DATA LOADING
# ============================================================================

def load_data(base_dir: str = '/Users/mac/Downloads/doc') -> Dict[str, pd.DataFrame]:
    """Load all CSV data files"""
    dfs = {}
    
    # Load gacha_card.csv (transposed format)
    try:
        raw_card = pd.read_csv(f'{base_dir}/gacha_card.csv', header=None)
        df_card = raw_card.T
        df_card.columns = df_card.iloc[0]
        df_card = df_card[1:].reset_index(drop=True)
        dfs['gacha_card'] = df_card
    except Exception as e:
        print(f"Error loading gacha_card: {e}")
    
    # Load other files
    for key, filename in [
        ('gacha_history', 'gacha_history.csv'),
        ('inventory', 'user_card_inventory.csv'),
        ('profile', 'user_profile.csv')
    ]:
        try:
            dfs[key] = pd.read_csv(f'{base_dir}/{filename}', on_bad_lines='skip')
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    
    # Parse timestamps
    if 'gacha_history' in dfs:
        dfs['gacha_history']['created_at'] = pd.to_datetime(dfs['gacha_history']['created_at'])
    if 'inventory' in dfs:
        dfs['inventory']['created_at'] = pd.to_datetime(dfs['inventory']['created_at'])
        dfs['inventory']['updated_at'] = pd.to_datetime(dfs['inventory']['updated_at'])
    if 'profile' in dfs:
        if 'updated_at' in dfs['profile'].columns:
            dfs['profile']['updated_at'] = pd.to_datetime(dfs['profile']['updated_at'])
    
    return dfs

# ============================================================================
# FRAUD DETECTION CHECKS
# ============================================================================

class FraudDetector:
    def __init__(self, dfs: Dict[str, pd.DataFrame]):
        self.dfs = dfs
        self.card_info = self._build_card_info()
        self.suspicious_users = []
        
    def _build_card_info(self) -> Dict[str, Dict]:
        """Build card ID to info mapping"""
        card_info = {}
        if 'gacha_card' in self.dfs:
            for _, row in self.dfs['gacha_card'].iterrows():
                card_info[row['id']] = {
                    'name': row['name'],
                    'tier': row['tier'],
                    'character_id': row['character_id']
                }
        return card_info
    
    def check_inventory_history_mismatch(self) -> List[Dict]:
        """
        Check 1: Inventory vs History Mismatch
        
        Logic:
        - Count cards from history (draws) + estimated merge results
        - Compare with current inventory
        - Flag significant discrepancies
        """
        results = []
        history = self.dfs.get('gacha_history', pd.DataFrame())
        inventory = self.dfs.get('inventory', pd.DataFrame())
        
        if history.empty or inventory.empty:
            return results
        
        # Get all unique users
        all_users = set(history['user_id'].unique()) | set(inventory['user_id'].unique())
        
        for user_id in all_users:
            user_history = history[history['user_id'] == user_id]
            user_inventory = inventory[inventory['user_id'] == user_id]
            
            # Count cards from history (excluding merged ones - they were consumed)
            history_cards = user_history[user_history['is_merged'] != True]
            history_total = len(history_cards)
            
            # Count current inventory
            inventory_total = user_inventory['quantity'].sum() if not user_inventory.empty else 0
            
            # Calculate difference
            # Cards can be consumed via merge (3:1) so inventory should be <= history
            # But inventory can't be MORE than history total cards received
            
            if inventory_total > history_total + 10:  # Allow small buffer for edge cases
                diff = inventory_total - history_total
                results.append({
                    'user_id': user_id,
                    'flag': 'INV_HISTORY_MISMATCH',
                    'severity': 'HIGH',
                    'detail': f'Inventory ({int(inventory_total)}) > History ({history_total}). Diff: +{int(diff)} thẻ không có nguồn gốc',
                    'history_total': history_total,
                    'inventory_total': int(inventory_total),
                    'diff': int(diff)
                })
        
        return results
    
    def check_ur_without_collection(self) -> List[Dict]:
        """
        Check 2: UR Cards Without Valid Collection
        
        Logic:
        - UR can ONLY be obtained from collection reward
        - Check if user has UR but never completed a collection
        - Cross-check with collection completion logic
        """
        results = []
        inventory = self.dfs.get('inventory', pd.DataFrame())
        history = self.dfs.get('gacha_history', pd.DataFrame())
        cards = self.dfs.get('gacha_card', pd.DataFrame())
        
        if inventory.empty or cards.empty:
            return results
        
        # Get UR card IDs
        ur_card_ids = set(cards[cards['tier'] == 'UR']['id'].tolist())
        
        # Get users with UR in inventory
        inventory_merged = inventory.merge(cards[['id', 'tier', 'character_id']], 
                                           left_on='card_id', right_on='id', how='left')
        users_with_ur = inventory_merged[inventory_merged['tier'] == 'UR']['user_id'].unique()
        
        # Get character requirements for collection (3R + 2SR + 1SSR per character)
        char_requirements = {}
        for char_id in cards['character_id'].unique():
            char_cards = cards[cards['character_id'] == char_id]
            char_requirements[char_id] = {
                'R': len(char_cards[char_cards['tier'] == 'R']),
                'SR': len(char_cards[char_cards['tier'] == 'SR']),
                'SSR': len(char_cards[char_cards['tier'] == 'SSR']),
                'UR_id': char_cards[char_cards['tier'] == 'UR']['id'].tolist()
            }
        
        for user_id in users_with_ur:
            user_inv = inventory_merged[inventory_merged['user_id'] == user_id]
            user_ur_cards = user_inv[user_inv['tier'] == 'UR']
            
            for _, ur_row in user_ur_cards.iterrows():
                ur_char_id = ur_row['character_id']
                ur_card_id = ur_row['card_id']
                ur_qty = ur_row['quantity']
                
                if pd.isna(ur_char_id):
                    continue
                
                # Check if user has/had enough cards for collection of this character
                user_char_inv = user_inv[user_inv['character_id'] == ur_char_id]
                
                # Count cards by tier for this character
                tier_counts = user_char_inv.groupby('tier')['quantity'].sum()
                r_count = tier_counts.get('R', 0)
                sr_count = tier_counts.get('SR', 0)
                ssr_count = tier_counts.get('SSR', 0)
                
                # Get required unique cards for collection
                req = char_requirements.get(ur_char_id, {})
                required_r = req.get('R', 3)
                required_sr = req.get('SR', 2)
                required_ssr = req.get('SSR', 1)
                
                # Check history for this character to see if user ever had enough cards
                user_hist = history[history['user_id'] == user_id]
                user_hist_merged = user_hist.merge(cards[['id', 'tier', 'character_id']], 
                                                   left_on='card_id', right_on='id', how='left')
                user_char_hist = user_hist_merged[user_hist_merged['character_id'] == ur_char_id]
                
                # Count unique cards ever obtained for this character
                unique_r = user_char_hist[user_char_hist['tier'] == 'R']['card_id'].nunique()
                unique_sr = user_char_hist[user_char_hist['tier'] == 'SR']['card_id'].nunique()
                unique_ssr = user_char_hist[user_char_hist['tier'] == 'SSR']['card_id'].nunique()
                
                # Check if user ever qualified for collection
                has_collection = (unique_r >= required_r and 
                                  unique_sr >= required_sr and 
                                  unique_ssr >= required_ssr)
                
                # Also check pity_reward = True in history for this UR
                ur_from_history = history[(history['user_id'] == user_id) & 
                                          (history['card_id'] == ur_card_id) &
                                          (history['is_pity_reward'] == True)]
                has_ur_history = len(ur_from_history) > 0
                
                if not has_collection and not has_ur_history:
                    results.append({
                        'user_id': user_id,
                        'flag': 'UR_WITHOUT_COLLECTION',
                        'severity': 'HIGH',
                        'detail': f'Có UR "{self.card_info.get(ur_card_id, {}).get("name", ur_card_id)}" nhưng chưa đủ bộ sưu tập. Unique cards: R={unique_r}/{required_r}, SR={unique_sr}/{required_sr}, SSR={unique_ssr}/{required_ssr}',
                        'ur_card_id': ur_card_id,
                        'ur_quantity': int(ur_qty),
                        'character_id': ur_char_id,
                        'unique_r': unique_r,
                        'unique_sr': unique_sr,
                        'unique_ssr': unique_ssr
                    })
        
        return results
    
    def check_excessive_ur_rate(self) -> List[Dict]:
        """
        Check 3: Excessive UR Rate
        
        Logic:
        - UR requires completing collection
        - If user has many URs but low total spins, suspicious
        - Also check total cards ratio
        """
        results = []
        inventory = self.dfs.get('inventory', pd.DataFrame())
        profile = self.dfs.get('profile', pd.DataFrame())
        cards = self.dfs.get('gacha_card', pd.DataFrame())
        
        if inventory.empty or profile.empty or cards.empty:
            return results
        
        # Get UR card IDs
        ur_card_ids = set(cards[cards['tier'] == 'UR']['id'].tolist())
        
        for _, user_row in profile.iterrows():
            user_id = user_row['user_id']
            total_spins = user_row.get('total_spins', 0)
            
            if total_spins == 0:
                continue
            
            user_inv = inventory[inventory['user_id'] == user_id]
            user_inv_with_tier = user_inv.merge(cards[['id', 'tier']], 
                                                 left_on='card_id', right_on='id', how='left')
            
            ur_count = user_inv_with_tier[user_inv_with_tier['tier'] == 'UR']['quantity'].sum()
            total_cards = user_inv_with_tier['quantity'].sum()
            
            if total_cards == 0:
                continue
            
            ur_rate = ur_count / total_cards * 100
            
            # UR rate > 15% is very suspicious (should be hard to achieve)
            # Also check: having many URs with few total spins
            if ur_rate > 15 and ur_count >= 3:
                results.append({
                    'user_id': user_id,
                    'flag': 'EXCESSIVE_UR_RATE',
                    'severity': 'MEDIUM',
                    'detail': f'UR rate: {ur_rate:.1f}% ({int(ur_count)} UR / {int(total_cards)} cards). Total spins: {total_spins}',
                    'ur_count': int(ur_count),
                    'total_cards': int(total_cards),
                    'ur_rate': round(ur_rate, 2),
                    'total_spins': total_spins
                })
        
        return results
    
    def check_missing_history(self) -> List[Dict]:
        """
        Check 4: Cards in Inventory Without History
        
        Logic:
        - Every card in inventory should have at least one history record
        - Exception: Merge results (but should still be logged with is_merged=False in history)
        """
        results = []
        inventory = self.dfs.get('inventory', pd.DataFrame())
        history = self.dfs.get('gacha_history', pd.DataFrame())
        
        if inventory.empty:
            return results
        
        # Get all card IDs ever in history per user
        history_by_user = history.groupby('user_id')['card_id'].apply(set).to_dict()
        
        for user_id in inventory['user_id'].unique():
            user_inv = inventory[inventory['user_id'] == user_id]
            user_hist_cards = history_by_user.get(user_id, set())
            
            missing_cards = []
            for _, inv_row in user_inv.iterrows():
                card_id = inv_row['card_id']
                quantity = inv_row['quantity']
                
                if quantity > 0 and card_id not in user_hist_cards:
                    card_name = self.card_info.get(card_id, {}).get('name', card_id)
                    missing_cards.append(f"{card_name} (x{int(quantity)})")
            
            if missing_cards:
                results.append({
                    'user_id': user_id,
                    'flag': 'MISSING_HISTORY',
                    'severity': 'MEDIUM',
                    'detail': f'Có {len(missing_cards)} loại thẻ trong kho không có history: {", ".join(missing_cards[:5])}{"..." if len(missing_cards) > 5 else ""}',
                    'missing_count': len(missing_cards),
                    'missing_cards': missing_cards[:10]
                })
        
        return results
    
    def check_negative_inventory(self) -> List[Dict]:
        """
        Check 5: Negative Inventory Quantities
        
        Logic:
        - Quantity should never be negative
        - Indicates bug or manipulation
        """
        results = []
        inventory = self.dfs.get('inventory', pd.DataFrame())
        
        if inventory.empty:
            return results
        
        negative = inventory[inventory['quantity'] < 0]
        
        for _, row in negative.iterrows():
            card_name = self.card_info.get(row['card_id'], {}).get('name', row['card_id'])
            results.append({
                'user_id': row['user_id'],
                'flag': 'NEGATIVE_INVENTORY',
                'severity': 'HIGH',
                'detail': f'Số lượng âm: {card_name} = {int(row["quantity"])}',
                'card_id': row['card_id'],
                'quantity': int(row['quantity'])
            })
        
        return results
    
    def check_burst_activity(self, threshold: int = 100) -> List[Dict]:
        """
        Check 6: Burst Activity Detection
        
        Logic:
        - Detect users with too many actions in short timeframes
        - Could indicate bot/script usage
        """
        results = []
        history = self.dfs.get('gacha_history', pd.DataFrame())
        
        if history.empty:
            return results
        
        # Group by user and check activity density
        for user_id in history['user_id'].unique():
            user_hist = history[history['user_id'] == user_id].sort_values('created_at')
            
            if len(user_hist) < threshold:
                continue
            
            # Check for bursts in 1-minute windows
            user_hist['minute'] = user_hist['created_at'].dt.floor('min')
            minute_counts = user_hist.groupby('minute').size()
            
            max_per_minute = minute_counts.max()
            if max_per_minute > threshold:
                peak_time = minute_counts.idxmax()
                results.append({
                    'user_id': user_id,
                    'flag': 'BURST_ACTIVITY',
                    'severity': 'LOW',
                    'detail': f'{max_per_minute} actions trong 1 phút (peak: {peak_time})',
                    'max_per_minute': int(max_per_minute),
                    'peak_time': str(peak_time)
                })
        
        return results
    
    def check_impossible_merge(self) -> List[Dict]:
        """
        Check 7: Impossible Merge Detection
        
        Logic:
        - User has SR/SSR but never had enough R/SR cards to merge
        - Merge: 3R -> 1SR, 3SR -> 1SSR
        """
        results = []
        inventory = self.dfs.get('inventory', pd.DataFrame())
        history = self.dfs.get('gacha_history', pd.DataFrame())
        cards = self.dfs.get('gacha_card', pd.DataFrame())
        
        if inventory.empty or history.empty or cards.empty:
            return results
        
        for user_id in inventory['user_id'].unique():
            user_hist = history[history['user_id'] == user_id]
            user_inv = inventory[inventory['user_id'] == user_id]
            
            # Merge history with cards to get tier info
            hist_with_tier = user_hist.merge(cards[['id', 'tier']], 
                                              left_on='card_id', right_on='id', how='left')
            inv_with_tier = user_inv.merge(cards[['id', 'tier']], 
                                            left_on='card_id', right_on='id', how='left')
            
            # Count cards received from history by tier (total ever received)
            hist_tier_counts = hist_with_tier.groupby('tier').size()
            r_received = hist_tier_counts.get('R', 0)
            sr_received = hist_tier_counts.get('SR', 0)
            ssr_received = hist_tier_counts.get('SSR', 0)
            
            # Count current inventory by tier
            inv_tier_qty = inv_with_tier.groupby('tier')['quantity'].sum()
            sr_in_inv = inv_tier_qty.get('SR', 0)
            ssr_in_inv = inv_tier_qty.get('SSR', 0)
            
            # Count merged cards (used for merge)
            merged_count = len(user_hist[user_hist['is_merged'] == True])
            
            # Calculate max possible SR from R merge (3:1)
            max_sr_from_merge = (r_received - merged_count) // 3
            
            # If SR in inventory > SR received directly + possible merge results, suspicious
            # Note: This is rough estimation, may have false positives
            sr_from_gacha = len(hist_with_tier[hist_with_tier['tier'] == 'SR'])
            total_possible_sr = sr_from_gacha + max_sr_from_merge
            
            # If user has more SR than possible, flag it
            if sr_in_inv > total_possible_sr + 5:  # Buffer for edge cases
                results.append({
                    'user_id': user_id,
                    'flag': 'IMPOSSIBLE_MERGE',
                    'severity': 'MEDIUM',
                    'detail': f'SR trong kho ({int(sr_in_inv)}) > SR có thể có ({total_possible_sr}). Gacha: {sr_from_gacha}, Max merge: {max_sr_from_merge}',
                    'sr_in_inv': int(sr_in_inv),
                    'sr_from_gacha': sr_from_gacha,
                    'max_sr_from_merge': max_sr_from_merge
                })
        
        return results
    
    def run_all_checks(self) -> pd.DataFrame:
        """Run all fraud detection checks and return consolidated results"""
        print("🔍 Running fraud detection checks...")
        
        all_results = []
        
        print("  [1/7] Checking inventory vs history mismatch...")
        all_results.extend(self.check_inventory_history_mismatch())
        
        print("  [2/7] Checking UR without collection...")
        all_results.extend(self.check_ur_without_collection())
        
        print("  [3/7] Checking excessive UR rate...")
        all_results.extend(self.check_excessive_ur_rate())
        
        print("  [4/7] Checking missing history...")
        all_results.extend(self.check_missing_history())
        
        print("  [5/7] Checking negative inventory...")
        all_results.extend(self.check_negative_inventory())
        
        print("  [6/7] Checking burst activity...")
        all_results.extend(self.check_burst_activity())
        
        print("  [7/7] Checking impossible merge...")
        all_results.extend(self.check_impossible_merge())
        
        print(f"\n✅ Done! Found {len(all_results)} suspicious records.")
        
        if not all_results:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_results)
        
        # Calculate risk score per user
        severity_scores = {'HIGH': 10, 'MEDIUM': 5, 'LOW': 1}
        df['score'] = df['severity'].map(severity_scores)
        
        return df
    
    def get_user_summary(self, results_df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate results by user with risk score"""
        if results_df.empty:
            return pd.DataFrame()
        
        summary = results_df.groupby('user_id').agg({
            'flag': lambda x: ', '.join(sorted(set(x))),
            'score': 'sum',
            'severity': lambda x: 'HIGH' if 'HIGH' in x.values else ('MEDIUM' if 'MEDIUM' in x.values else 'LOW')
        }).reset_index()
        
        summary.columns = ['user_id', 'flags', 'risk_score', 'max_severity']
        summary = summary.sort_values('risk_score', ascending=False)
        
        return summary


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("🎰 GACHA FRAUD DETECTION MODULE")
    print("=" * 60)
    
    # Load data
    print("\n📂 Loading data...")
    dfs = load_data()
    
    print(f"  - gacha_card: {len(dfs.get('gacha_card', []))} cards")
    print(f"  - gacha_history: {len(dfs.get('gacha_history', []))} records")
    print(f"  - inventory: {len(dfs.get('inventory', []))} records")
    print(f"  - profile: {len(dfs.get('profile', []))} users")
    
    # Run detection
    detector = FraudDetector(dfs)
    results = detector.run_all_checks()
    
    if not results.empty:
        # Get user summary
        summary = detector.get_user_summary(results)
        
        print("\n" + "=" * 60)
        print("📊 TOP 20 SUSPICIOUS USERS")
        print("=" * 60)
        print(summary.head(20).to_string(index=False))
        
        # Save results
        results.to_csv('/Users/mac/Downloads/doc/fraud_detection_results.csv', index=False)
        summary.to_csv('/Users/mac/Downloads/doc/fraud_user_summary.csv', index=False)
        
        print("\n💾 Results saved to:")
        print("  - fraud_detection_results.csv (detailed)")
        print("  - fraud_user_summary.csv (by user)")
        
        # Print summary stats
        print("\n" + "=" * 60)
        print("📈 SUMMARY STATISTICS")
        print("=" * 60)
        print(f"Total suspicious records: {len(results)}")
        print(f"Unique suspicious users: {results['user_id'].nunique()}")
        print("\nBy Flag Type:")
        print(results['flag'].value_counts().to_string())
        print("\nBy Severity:")
        print(results['severity'].value_counts().to_string())
    else:
        print("\n✅ No suspicious activity detected!")
