import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

# Set style for better aesthetics
plt.style.use('ggplot')
sns.set_theme(style="whitegrid")

# Define file paths
base_dir = '/Users/mac/Downloads/doc'
files = {
    'gacha_card': 'gacha_card.csv',
    'gacha_history': 'gacha_history.csv',
    'inventory': 'user_card_inventory.csv',
    'profile': 'user_profile.csv'
}

# 1. Load Data
dfs = {}

# Special handling for gacha_card.csv (transposed)
try:
    card_path = os.path.join(base_dir, 'gacha_card.csv')
    if os.path.exists(card_path):
        # Read without header initially
        raw_card = pd.read_csv(card_path, header=None)
        # Transpose
        df_card = raw_card.T
        # Set first row as header
        df_card.columns = df_card.iloc[0]
        df_card = df_card[1:]
        # Rename 'Column' if it persisted (it was the name of the first column in original)
        # The first column in original was "Column", "id", "character_id"...
        # After transpose, "Column" is the column name for the index, but let's check.
        # Original:
        # Col 0: [Column, id, character_id, name, tier]
        # Col 1: [Value (1), id_val1, char_val1, name1, tier1]
        #
        # Transposed:
        # Index 0 (Column): [id, character_id, name, tier] -> This is our header
        # Index 1 (Value 1): [id_val1, char_val1, name1, tier1]
        
        # Reset index
        dfs['gacha_card'] = df_card.reset_index(drop=True)
        print(f"Loaded gacha_card.csv (transposed): {dfs['gacha_card'].shape}")
except Exception as e:
    print(f"Error loading gacha_card.csv: {e}")

# Standard loading for others
for key, filename in files.items():
    if key == 'gacha_card': continue 
    
    file_path = os.path.join(base_dir, filename)
    if os.path.exists(file_path):
        try:
            dfs[key] = pd.read_csv(file_path)
            print(f"Loaded {filename}: {dfs[key].shape}")
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            try:
                dfs[key] = pd.read_csv(file_path, on_bad_lines='skip')
                print(f"Loaded {filename} (skipping bad lines): {dfs[key].shape}")
            except Exception as e2:
                print(f"Critical error loading {filename}: {e2}")

# Check if we have necessary data
if not all(k in dfs for k in ['gacha_card', 'gacha_history', 'inventory', 'profile']):
    print("Missing some required files.")
    # Debug info
    print("Loaded keys:", dfs.keys())
    if 'gacha_card' in dfs:
        print("Gacha Card columns:", dfs['gacha_card'].columns)
    exit()

# Clean up gacha_card columns (remove any generic name if exists)
# The first column of the transposed df might be 'Column' in the header row, which is correct.
# Ensure 'id' exists
if 'Column' in dfs['gacha_card'].columns and 'id' not in dfs['gacha_card'].columns:
    # Maybe the first row wasn't correctly identified as header?
    # No, we set `df_card.columns = df_card.iloc[0]`.
    # df.iloc[0] should be ["Column", "Value(1)"...]? No.
    # Raw read: 
    #    0       1         2
    # 0  Column  Value(1)  Value(2)
    # 1  id      ...
    #
    # Transposed:
    #           0       1
    # 0         Column  id
    # 1         Value(1) ...
    #
    # Wait, raw_card.T:
    # Columns will be 0, 1, 2, 3, 4 (indices of original rows)
    # Row 0 of T will be [Column, id, char_id, name, tier]
    # So `df_card.iloc[0]` is indeed the header.
    pass

# 2. Data Preprocessing

# Convert timestamps to datetime
dfs['gacha_history']['created_at'] = pd.to_datetime(dfs['gacha_history']['created_at'])
dfs['profile']['created_at'] = pd.to_datetime(dfs['profile']['created_at'])

# Merge History with Card Info to get Tiers
history_merged = pd.merge(
    dfs['gacha_history'],
    dfs['gacha_card'],
    left_on='card_id',
    right_on='id',
    how='left',
    suffixes=('', '_card')
)

# 3. Visualizations

# Create an output directory for charts
output_dir = os.path.join(base_dir, 'analytics_charts')
os.makedirs(output_dir, exist_ok=True)

# Chart 1: Daily Gacha Pulls (Time Series)
plt.figure(figsize=(12, 6))
daily_pulls = dfs['gacha_history'].set_index('created_at').resample('D').size()
daily_pulls.plot(kind='line', marker='o', color='tab:blue')
plt.title('Daily Gacha Pulls Trend')
plt.xlabel('Date')
plt.ylabel('Number of Pulls')
plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'daily_pulls_trend.png'))
plt.close()

# Chart 2: Pull Distribution by Tier (Pie Chart)
if 'tier' in history_merged.columns:
    plt.figure(figsize=(8, 8))
    tier_counts = history_merged['tier'].value_counts()
    plt.pie(tier_counts, labels=tier_counts.index, autopct='%1.1f%%', startangle=140, colors=sns.color_palette('pastel'))
    plt.title('Distribution of Pulled Card Tiers')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'tier_distribution.png'))
    plt.close()

# Chart 3: Top 10 Users by Total Spins
# Calculate actual spins from history to double check or use profile 'total_spins'
# Let's use profile data for "Total Spins" as it seems to be an aggregate
if 'total_spins' in dfs['profile'].columns:
    plt.figure(figsize=(12, 6))
    top_users = dfs['profile'].nlargest(10, 'total_spins')
    # Use user_id (shortened) as label
    labels = top_users['user_id'].apply(lambda x: str(x)[:8] + '...')
    sns.barplot(x=labels, y=top_users['total_spins'], palette='viridis')
    plt.title('Top 10 Users by Total Spins')
    plt.xlabel('User ID')
    plt.ylabel('Total Spins')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'top_users_spins.png'))
    plt.close()

# Chart 4: Inventory Distribution (Most owned cards)
# Merge Inventory with Card to get names
inventory_merged = pd.merge(
    dfs['inventory'],
    dfs['gacha_card'],
    left_on='card_id',
    right_on='id',
    how='left'
)

if 'name' in inventory_merged.columns:
    plt.figure(figsize=(12, 8))
    # Sum quantity by card name
    card_popularity = inventory_merged.groupby('name')['quantity'].sum().nlargest(15)
    sns.barplot(y=card_popularity.index, x=card_popularity.values, orient='h', palette='magma')
    plt.title('Top 15 Most Owned Cards in Inventory')
    plt.xlabel('Total Quantity')
    plt.ylabel('Card Name')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'top_inventory_cards.png'))
    plt.close()

print(f"Charts generated successfully in {output_dir}")
