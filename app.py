import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="NBA BPM Dashboard", layout="wide")
st.title("🏀 NBA BPM Impact Dashboard")
st.markdown("---")

# Constants
TOTAL_TEAM_MINUTES = 240  # 5 players × 48 minutes
IMPACT_MULTIPLIER = 2.083

# Function to load data
@st.cache_data(ttl=86400)
def load_nba_data():
    try:
        url = "https://www.basketball-reference.com/leagues/NBA_2026_advanced.html"
        tables = pd.read_html(url)
        df = tables[0]
        
        df = df[df['Rk'] != 'Rk'].copy()
        df.columns = df.columns.str.strip()
        
        # Find BPM column
        bpm_column = None
        for col in df.columns:
            if 'BPM' in col:
                bpm_column = col
                break
        
        if bpm_column is None:
            st.error("Could not find BPM column!")
            return None
        
        df = df[['Player', 'Team', 'G', 'MP', bpm_column]].copy()
        df = df.rename(columns={bpm_column: 'BPM', 'Team': 'Team'})
        
        df['G'] = pd.to_numeric(df['G'], errors='coerce')
        df['MP'] = pd.to_numeric(df['MP'], errors='coerce')
        df['BPM'] = pd.to_numeric(df['BPM'], errors='coerce')
        df = df.dropna()
        
        # Calculate MPG and Impact
        df['MPG'] = df['MP'] / df['G']
        df['Impact'] = (df['BPM'] / 100) * df['MPG'] * IMPACT_MULTIPLIER
        
        df['MPG'] = df['MPG'].round(1)
        df['Impact'] = df['Impact'].round(3)
        
        return df
        
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None

# Function to redistribute minutes when players are removed
def redistribute_minutes_after_removal(data, removed_players, team):
    """
    Remove injured players and redistribute their minutes to remaining players
    proportionally based on current MPG.
    """
    # Get all players from the team
    team_data = data[data['Team'] == team].copy()
    
    if len(team_data) == 0:
        return data
    
    # Remove injured players
    healthy_players = team_data[~team_data['Player'].isin(removed_players)].copy()
    
    if len(healthy_players) == 0:
        # All players are injured - return empty
        return data
    
    if len(removed_players) == 0:
        # No injuries on this team
        return data
    
    # Calculate total minutes to redistribute from removed players
    removed_minutes = team_data[team_data['Player'].isin(removed_players)]['MPG'].sum()
    
    # Calculate redistribution factors based on current MPG
    # Players with more minutes get more of the redistributed minutes
    total_healthy_mpg = healthy_players['MPG'].sum()
    
    if total_healthy_mpg > 0 and removed_minutes > 0:
        redistribution_factors = healthy_players['MPG'] / total_healthy_mpg
        minutes_to_add = redistribution_factors * removed_minutes
        
        # Update MPG for healthy players
        for idx, player in healthy_players.iterrows():
            player_name = player['Player']
            original_mpg = player['MPG']
            additional_minutes = minutes_to_add.loc[idx]
            new_mpg = original_mpg + additional_minutes
            
            # Update the data
            data.loc[(data['Player'] == player_name) & (data['Team'] == team), 'MPG'] = new_mpg
            data.loc[(data['Player'] == player_name) & (data['Team'] == team), 'Impact'] = (
                (data.loc[(data['Player'] == player_name) & (data['Team'] == team), 'BPM'].values[0] / 100) 
                * new_mpg 
                * IMPACT_MULTIPLIER
            )
    
    # Remove injured players from the dataset entirely
    for player in removed_players:
        data = data[~((data['Player'] == player) & (data['Team'] == team))]
    
    return data

# Load the data
with st.spinner('Loading NBA data from Basketball-Reference...'):
    nba_data = load_nba_data()

if nba_data is None:
    st.stop()

# Sidebar for controls
st.sidebar.header("📊 Dashboard Controls")

# Team selection FIRST (needed for injury selection)
st.sidebar.subheader("🏀 Matchup Selection")
all_teams = sorted(nba_data['Team'].unique())

col1, col2 = st.sidebar.columns(2)
with col1:
    team1 = st.selectbox("Team 1", all_teams, index=0 if 'LAL' in all_teams else 0)
with col2:
    team2_default = 'BOS' if 'BOS' in all_teams else all_teams[1] if len(all_teams) > 1 else all_teams[0]
    team2 = st.selectbox("Team 2", all_teams, index=all_teams.index(team2_default) if team2_default in all_teams else 0)

# Injury management - show only players from selected teams
st.sidebar.subheader("🚫 Remove Injured Players")

# Get players from both teams for injury selection
team1_players = nba_data[nba_data['Team'] == team1]['Player'].tolist()
team2_players = nba_data[nba_data['Team'] == team2]['Player'].tolist()
all_matchup_players = team1_players + team2_players

# Multi-select for injuries with team grouping
removed_players = st.sidebar.multiselect(
    "Select injured players to remove:",
    options=all_matchup_players,
    help="Selected players will be removed entirely and their minutes redistributed"
)

# Show team breakdown of injuries
if removed_players:
    team1_removed = [p for p in removed_players if p in team1_players]
    team2_removed = [p for p in removed_players if p in team2_players]
    
    if team1_removed:
        minutes_removed_team1 = nba_data[(nba_data['Player'].isin(team1_removed)) & 
                                        (nba_data['Team'] == team1)]['MPG'].sum()
        st.sidebar.info(f"**{team1} removed:** {len(team1_removed)} players ({minutes_removed_team1:.1f} MPG)")
    
    if team2_removed:
        minutes_removed_team2 = nba_data[(nba_data['Player'].isin(team2_removed)) & 
                                        (nba_data['Team'] == team2)]['MPG'].sum()
        st.sidebar.info(f"**{team2} removed:** {len(team2_removed)} players ({minutes_removed_team2:.1f} MPG)")

# Filter options
st.sidebar.subheader("🔍 Filters")
min_games = st.sidebar.slider("Minimum games played:", 1, 82, 20)
filtered_data = nba_data[nba_data['G'] >= min_games].copy()

# Apply injury removal and redistribution
working_data = filtered_data.copy()

if removed_players:
    # Separate removed players by team
    team1_removed = [p for p in removed_players if p in team1_players]
    team2_removed = [p for p in removed_players if p in team2_players]
    
    # Apply removal and redistribution for each team
    if team1_removed:
        working_data = redistribute_minutes_after_removal(working_data, team1_removed, team1)
    
    if team2_removed:
        working_data = redistribute_minutes_after_removal(working_data, team2_removed, team2)

# Main content area
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.subheader(f"📈 {team1} vs {team2} Matchup")
    
    # Get team data after removal
    team1_data = working_data[working_data['Team'] == team1].copy()
    team2_data = working_data[working_data['Team'] == team2].copy()
    
    # Calculate team totals
    team1_impact = team1_data['Impact'].sum()
    team2_impact = team2_data['Impact'].sum()
    advantage = team1_impact - team2_impact
    
    # Calculate total team minutes
    team1_total_mpg = team1_data['MPG'].sum()
    team2_total_mpg = team2_data['MPG'].sum()
    
    # Original totals for comparison
    original_team1_data = filtered_data[filtered_data['Team'] == team1]
    original_team2_data = filtered_data[filtered_data['Team'] == team2]
    original_team1_impact = original_team1_data['Impact'].sum()
    original_team2_impact = original_team2_data['Impact'].sum()
    
    # Display matchup metrics
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    with metric_col1:
        impact_change = team1_impact - original_team1_impact
        delta_sign = "+" if impact_change > 0 else ""
        delta_color = "normal" if impact_change >= 0 else "inverse"
        st.metric(f"{team1} Total Impact", 
                 f"{team1_impact:.2f}", 
                 delta=f"{delta_sign}{impact_change:.2f}",
                 delta_color=delta_color)
    
    with metric_col2:
        impact_change = team2_impact - original_team2_impact
        delta_sign = "+" if impact_change > 0 else ""
        delta_color = "normal" if impact_change >= 0 else "inverse"
        st.metric(f"{team2} Total Impact", 
                 f"{team2_impact:.2f}",
                 delta=f"{delta_sign}{impact_change:.2f}",
                 delta_color=delta_color)
    
    with metric_col3:
        original_advantage = original_team1_impact - original_team2_impact
        advantage_change = advantage - original_advantage
        st.metric("Projected Advantage", 
                 f"{advantage:.2f}",
                 delta=f"{team1} by {abs(advantage):.2f}" if advantage > 0 else f"{team2} by {abs(advantage):.2f}",
                 delta_color="normal" if advantage > 0 else "inverse")

with col2:
    st.subheader("📊 Team Impact Comparison")
    
    # Create comparison data
    impact_data = pd.DataFrame({
        'Situation': ['With Injuries', 'Full Strength'],
        team1: [team1_impact, original_team1_impact],
        team2: [team2_impact, original_team2_impact]
    })
    
    # Melt for plotting
    plot_data = impact_data.melt(id_vars=['Situation'], 
                                 value_vars=[team1, team2],
                                 var_name='Team', 
                                 value_name='Impact')
    
    # Create grouped bar chart
    chart = st.bar_chart(plot_data, 
                        x='Team', 
                        y='Impact', 
                        color='Situation',
                        use_container_width=True)

with col3:
    st.subheader("🎯 Prediction")
    
    if advantage > 1:
        st.success(f"**{team1} favored** by {advantage:.2f} points")
        if removed_players:
            original_spread = original_team1_impact - original_team2_impact
            spread_change = advantage - original_spread
            if spread_change != 0:
                st.caption(f"Spread changed by {spread_change:+.2f} due to injuries")
    elif advantage < -1:
        st.error(f"**{team2} favored** by {abs(advantage):.2f} points")
        if removed_players:
            original_spread = original_team1_impact - original_team2_impact
            spread_change = advantage - original_spread
            if spread_change != 0:
                st.caption(f"Spread changed by {spread_change:+.2f} due to injuries")
    else:
        st.info("**Close matchup** - within 1 point")

# Show team rosters with changes
st.markdown("---")
st.subheader("👥 Team Rosters After Injury Adjustments")

col1, col2 = st.columns(2)

with col1:
    st.write(f"### {team1} Roster ({len(team1_data)} players)")
    
    if team1_removed:
        st.warning(f"**Removed:** {', '.join(team1_removed)}")
        st.write(f"**Total MPG:** {team1_total_mpg:.1f} (was {original_team1_data['MPG'].sum():.1f})")
    
    # Display team 1 players sorted by Impact
    team1_display = team1_data.sort_values('Impact', ascending=False)[['Player', 'MPG', 'BPM', 'Impact']].copy()
    
    # Add indicators for players who gained minutes
    if team1_removed:
        for idx, row in team1_display.iterrows():
            player = row['Player']
            original_mpg = original_team1_data[original_team1_data['Player'] == player]['MPG'].values
            if len(original_mpg) > 0:
                mpg_change = row['MPG'] - original_mpg[0]
                if mpg_change > 0:
                    team1_display.at[idx, 'MPG'] = f"{row['MPG']:.1f} (+{mpg_change:.1f})"
                else:
                    team1_display.at[idx, 'MPG'] = f"{row['MPG']:.1f}"
    
    st.dataframe(team1_display, use_container_width=True)

with col2:
    st.write(f"### {team2} Roster ({len(team2_data)} players)")
    
    if team2_removed:
        st.warning(f"**Removed:** {', '.join(team2_removed)}")
        st.write(f"**Total MPG:** {team2_total_mpg:.1f} (was {original_team2_data['MPG'].sum():.1f})")
    
    # Display team 2 players sorted by Impact
    team2_display = team2_data.sort_values('Impact', ascending=False)[['Player', 'MPG', 'BPM', 'Impact']].copy()
    
    # Add indicators for players who gained minutes
    if team2_removed:
        for idx, row in team2_display.iterrows():
            player = row['Player']
            original_mpg = original_team2_data[original_team2_data['Player'] == player]['MPG'].values
            if len(original_mpg) > 0:
                mpg_change = row['MPG'] - original_mpg[0]
                if mpg_change > 0:
                    team2_display.at[idx, 'MPG'] = f"{row['MPG']:.1f} (+{mpg_change:.1f})"
                else:
                    team2_display.at[idx, 'MPG'] = f"{row['MPG']:.1f}"
    
    st.dataframe(team2_display, use_container_width=True)

# Show removed players summary
if removed_players:
    st.markdown("---")
    st.subheader("🚫 Removed Players Summary")
    
    summary_data = []
    
    # Get removed player details
    for player in removed_players:
        player_data = filtered_data[filtered_data['Player'] == player]
        if not player_data.empty:
            team = player_data['Team'].values[0]
            mpg = player_data['MPG'].values[0]
            bpm = player_data['BPM'].values[0]
            impact = player_data['Impact'].values[0]
            summary_data.append({
                'Player': player,
                'Team': team,
                'MPG': mpg,
                'BPM': bpm,
                'Impact': impact
            })
    
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        st.write(f"**Total players removed:** {len(summary_data)}")
        st.dataframe(summary_df.sort_values(['Team', 'Impact'], ascending=[True, False]), 
                    use_container_width=True)

# Sorting and filtering for combined view
st.markdown("---")
st.subheader("🔍 Combined Player View")

sort_col1, sort_col2 = st.columns([1, 2])
with sort_col1:
    sort_by = st.selectbox(
        "Sort all players by:",
        ['Team', 'Player', 'Impact', 'BPM', 'MPG', 'G']
    )
with sort_col2:
    sort_order = st.radio(
        "Sort order:",
        ['Descending', 'Ascending'],
        horizontal=True,
        key='combined_sort'
    )

# Combine data for display
combined_data = pd.concat([team1_data, team2_data])

# Apply sorting
sorted_data = combined_data.sort_values(
    by=sort_by,
    ascending=(sort_order == 'Ascending')
)

# Display the table
display_columns = ['Team', 'Player', 'G', 'MPG', 'BPM', 'Impact']
st.dataframe(
    sorted_data[display_columns].reset_index(drop=True),
    use_container_width=True,
    column_config={
        "Team": st.column_config.TextColumn("Team", width="small"),
        "Player": st.column_config.TextColumn("Player", width="medium"),
        "G": st.column_config.NumberColumn("Games", format="%d"),
        "MPG": st.column_config.NumberColumn("MPG", format="%.1f"),
        "BPM": st.column_config.NumberColumn("BPM", format="%.1f"),
        "Impact": st.column_config.NumberColumn("Impact", format="%.3f")
    }
)

# Summary stats
st.markdown("---")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Active Players", len(combined_data))
with col2:
    st.metric("Removed Players", len(removed_players))
with col3:
    st.metric(f"{team1} Active", len(team1_data))
with col4:
    st.metric(f"{team2} Active", len(team2_data))

# Data source and explanation
st.markdown("---")
st.caption("📊 **Data sourced from Basketball-Reference.com**")
st.caption("📈 **Impact Formula:** (BPM/100) × MPG × 2.083")
st.caption("🔄 **Injury Logic:** Removed players' minutes are redistributed proportionally to remaining teammates")
st.caption("🎯 **Total Team MPG:** ~240 minutes (5 players × 48 minutes) distributed across roster")
