"""
Politician Agenda Analyzer - Comprehensive Dashboard
A multi-tab analytics platform combining quantitative metrics and semantic RAG analysis
"""

import streamlit as st
import os
from dotenv import load_dotenv
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import List, Dict, Any, Tuple, Optional
import json
from datetime import datetime

# Load environment variables
load_dotenv()

# Import cloud services
try:
    from google.cloud import bigquery
    from pinecone import Pinecone
    from openai import OpenAI
except ImportError as e:
    st.error(f"Missing required package: {e}. Please install all dependencies.")
    st.stop()


# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="Politician Agenda Analyzer",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================================
# SERVICE INITIALIZATION
# ============================================================================

@st.cache_resource
def get_services() -> Tuple[Any, Any, Any]:
    """Initialize and cache connections to BigQuery, Pinecone, and OpenAI."""
    try:
        bq_client = bigquery.Client(project="starlit-verve-376800")
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        pinecone_index = pc.Index("bills-index")
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return bq_client, pinecone_index, openai_client
    except Exception as e:
        st.error(f"❌ Service Connection Error: {str(e)}")
        st.stop()


# ============================================================================
# DATA FETCHING FUNCTIONS
# ============================================================================

@st.cache_data(ttl=3600)
def get_politician_list(_bq_client) -> pd.DataFrame:
    """Get list of all politicians for dropdown selection."""
    query = """
    SELECT 
        politician_id,
        CONCAT(first_name, ' ', last_name) AS name,
        party,
        state,
        chamber
    FROM `starlit-verve-376800.politician_analytics.politicians`
    WHERE is_active = TRUE
    ORDER BY last_name, first_name
    """
    return _bq_client.query(query).to_dataframe()


@st.cache_data(ttl=3600)
def get_committee_list(_bq_client) -> pd.DataFrame:
    """Get list of all committees."""
    query = """
    SELECT DISTINCT
        string_field_0 as committee_id,
        string_field_1 as committee_name,
        string_field_2 as chamber
    FROM `starlit-verve-376800.politician_analytics.committees`
    ORDER BY string_field_1
    """
    return _bq_client.query(query).to_dataframe()


def build_filter_conditions(filters: Dict) -> Tuple[str, str]:
    """Build SQL WHERE conditions based on selected filters."""
    conditions = []
    
    if filters['level'] == 'politician' and filters['politician_id']:
        conditions.append(f"politicians.politician_id = {filters['politician_id']}")
    elif filters['level'] == 'party' and filters['party']:
        conditions.append(f"politicians.party = '{filters['party']}'")
    elif filters['level'] == 'chamber' and filters['chamber'] != 'Both':
        conditions.append(f"politicians.chamber = '{filters['chamber']}'")
    elif filters['level'] == 'committee' and filters['committee_id']:
        conditions.append(f"""politicians.politician_id IN (
            SELECT politician_id FROM `starlit-verve-376800.politician_analytics.committee_assignments`
            WHERE committee_id = {filters['committee_id']}
        )""")
    
    if filters['congress'] != 'Both':
        congress_condition = f"congress = {filters['congress']}"
    else:
        congress_condition = "congress IN (118, 119)"
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    return congress_condition, where_clause


@st.cache_data(ttl=600)
def get_financial_metrics(_bq_client, filters_json: str) -> Dict:
    """Get comprehensive donation metrics."""
    filters = json.loads(filters_json)
    congress_condition, where_clause = build_filter_conditions(filters)
    
    # Total donations
    total_query = f"""
    SELECT COALESCE(SUM(donations.amount), 0) as total
    FROM `starlit-verve-376800.politician_analytics.donations` AS donations
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON donations.politician_id = politicians.politician_id
    WHERE {where_clause}
    """
    total_result = _bq_client.query(total_query).to_dataframe()
    total_donations = float(total_result['total'].iloc[0]) if not total_result.empty else 0
    
    # Donations by type
    by_type_query = f"""
    SELECT 
        COALESCE(donors.donor_type, 'Unknown') as donor_type,
        SUM(donations.amount) as total,
        COUNT(DISTINCT donations.donation_id) as count
    FROM `starlit-verve-376800.politician_analytics.donations` AS donations
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON donations.politician_id = politicians.politician_id
    JOIN `starlit-verve-376800.politician_analytics.donors` AS donors
        ON donations.donor_id = donors.donor_id
    WHERE {where_clause}
    GROUP BY donor_type
    ORDER BY total DESC
    """
    by_type_df = _bq_client.query(by_type_query).to_dataframe()
    
    # Top donors
    top_donors_query = f"""
    SELECT 
        donors.name,
        COALESCE(donors.donor_type, 'Unknown') as donor_type,
        SUM(donations.amount) as total_donated,
        COUNT(donations.donation_id) as num_donations
    FROM `starlit-verve-376800.politician_analytics.donations` AS donations
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON donations.politician_id = politicians.politician_id
    JOIN `starlit-verve-376800.politician_analytics.donors` AS donors
        ON donations.donor_id = donors.donor_id
    WHERE {where_clause}
    GROUP BY donors.name, donor_type
    ORDER BY total_donated DESC
    LIMIT 10
    """
    top_donors_df = _bq_client.query(top_donors_query).to_dataframe()
    
    # Donations timeline (by month)
    timeline_query = f"""
    SELECT 
        DATE_TRUNC(donations.date, MONTH) as month,
        COALESCE(donors.donor_type, 'Unknown') as donor_type,
        SUM(donations.amount) as total
    FROM `starlit-verve-376800.politician_analytics.donations` AS donations
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON donations.politician_id = politicians.politician_id
    JOIN `starlit-verve-376800.politician_analytics.donors` AS donors
        ON donations.donor_id = donors.donor_id
    WHERE {where_clause}
    GROUP BY month, donor_type
    ORDER BY month
    """
    timeline_df = _bq_client.query(timeline_query).to_dataframe()
    
    return {
        'total': total_donations,
        'by_type': by_type_df,
        'top_donors': top_donors_df,
        'timeline': timeline_df
    }


@st.cache_data(ttl=600)
def get_legislative_metrics(_bq_client, filters_json: str) -> Dict:
    """Get bills sponsored and cosponsored metrics."""
    filters = json.loads(filters_json)
    congress_condition, where_clause = build_filter_conditions(filters)
    
    # Bills sponsored
    sponsored_query = f"""
    SELECT COUNT(*) as count
    FROM `starlit-verve-376800.politician_analytics.bills` AS bills
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON bills.sponsor_id = politicians.politician_id
    WHERE {where_clause} AND {congress_condition}
    """
    sponsored_result = _bq_client.query(sponsored_query).to_dataframe()
    bills_sponsored = int(sponsored_result['count'].iloc[0]) if not sponsored_result.empty else 0
    
    # Cosponsorship stats
    cosponsor_query = f"""
    SELECT 
        bc.is_original_cosponsor,
        COUNT(*) as count
    FROM `starlit-verve-376800.politician_analytics.bill_cosponsors` AS bc
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON bc.politician_id = politicians.politician_id
    JOIN `starlit-verve-376800.politician_analytics.bills` AS bills
        ON bc.bill_id = bills.bill_id
    WHERE {where_clause} AND {congress_condition}
    GROUP BY bc.is_original_cosponsor
    """
    cosponsor_df = _bq_client.query(cosponsor_query).to_dataframe()
    
    original_cosponsor = 0
    later_cosponsor = 0
    for _, row in cosponsor_df.iterrows():
        if row['is_original_cosponsor']:
            original_cosponsor = int(row['count'])
        else:
            later_cosponsor = int(row['count'])
    
    # Recent bills
    recent_bills_query = f"""
    SELECT 
        bills.official_bill_number,
        bills.title,
        bills.date_introduced,
        CONCAT(politicians.first_name, ' ', politicians.last_name) as sponsor_name
    FROM `starlit-verve-376800.politician_analytics.bills` AS bills
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON bills.sponsor_id = politicians.politician_id
    WHERE {where_clause} AND {congress_condition}
    ORDER BY bills.date_introduced DESC
    LIMIT 10
    """
    recent_bills_df = _bq_client.query(recent_bills_query).to_dataframe()
    
    return {
        'sponsored': bills_sponsored,
        'cosponsored_original': original_cosponsor,
        'cosponsored_later': later_cosponsor,
        'total_cosponsored': original_cosponsor + later_cosponsor,
        'recent_bills': recent_bills_df
    }


@st.cache_data(ttl=600)
def get_voting_metrics(_bq_client, filters_json: str) -> Dict:
    """Get comprehensive voting record metrics."""
    filters = json.loads(filters_json)
    congress_condition, where_clause = build_filter_conditions(filters)
    
    # Vote breakdown
    vote_breakdown_query = f"""
    SELECT 
        COALESCE(votes.vote_position, 'Unknown') as vote_position,
        COUNT(*) as count
    FROM `starlit-verve-376800.politician_analytics.votes` AS votes
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON votes.politician_id = politicians.politician_id
    JOIN `starlit-verve-376800.politician_analytics.bills` AS bills
        ON votes.bill_id = bills.bill_id
    WHERE {where_clause} AND {congress_condition}
    GROUP BY vote_position
    """
    vote_df = _bq_client.query(vote_breakdown_query).to_dataframe()
    
    total_votes = int(vote_df['count'].sum()) if not vote_df.empty else 0
    
    # Recent votes
    recent_votes_query = f"""
    SELECT 
        votes.date,
        votes.vote_position,
        votes.vote_category,
        bills.official_bill_number
    FROM `starlit-verve-376800.politician_analytics.votes` AS votes
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON votes.politician_id = politicians.politician_id
    JOIN `starlit-verve-376800.politician_analytics.bills` AS bills
        ON votes.bill_id = bills.bill_id
    WHERE {where_clause} AND {congress_condition}
    ORDER BY votes.date DESC
    LIMIT 20
    """
    recent_votes_df = _bq_client.query(recent_votes_query).to_dataframe()
    
    return {
        'total': total_votes,
        'breakdown': vote_df,
        'recent_votes': recent_votes_df
    }


@st.cache_data(ttl=600)
def get_committee_assignments(_bq_client, filters_json: str) -> pd.DataFrame:
    """Get committee assignments for filtered politicians."""
    filters = json.loads(filters_json)
    _, where_clause = build_filter_conditions(filters)
    
    query = f"""
    SELECT 
        committees.string_field_1 as committee_name,
        committees.string_field_2 as chamber,
        COUNT(DISTINCT ca.politician_id) as member_count
    FROM `starlit-verve-376800.politician_analytics.committee_assignments` AS ca
    JOIN `starlit-verve-376800.politician_analytics.committees` AS committees
        ON ca.committee_id = committees.string_field_0
    JOIN `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON ca.politician_id = politicians.politician_id
    WHERE {where_clause}
    GROUP BY committees.string_field_1, committees.string_field_2
    ORDER BY member_count DESC
    """
    return _bq_client.query(query).to_dataframe()


# ============================================================================
# SEMANTIC SEARCH (PINECONE)
# ============================================================================

def search_bills_semantic(query: str, openai_client: Any, pinecone_index: Any, k: int = 10) -> List[Dict]:
    """Search bills using semantic similarity."""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query
        )
        query_embedding = response.data[0].embedding
        
        results = pinecone_index.query(
            vector=query_embedding,
            top_k=k,
            include_metadata=True
        )
        
        bills = []
        for match in results.matches:
            bills.append({
                'bill_number': match.metadata.get('bill_number', 'Unknown'),
                'title': match.metadata.get('title', 'No title available'),
                'summary': match.metadata.get('summary', 'No summary available'),
                'score': match.score,
                'sponsor': match.metadata.get('sponsor_name', 'Unknown'),
                'congress': match.metadata.get('congress', 'Unknown')
            })
        
        return bills
    except Exception as e:
        st.error(f"Error searching bills: {str(e)}")
        return []


# ============================================================================
# ENHANCED SYNTHESIS ENGINE
# ============================================================================

def extract_keywords_for_synthesis(user_question: str, openai_client: Any) -> Dict:
    """Extract keywords for targeted semantic search."""
    try:
        prompt = f"""
Extract key topics and themes from this question for bill search:
"{user_question}"

Return JSON with:
{{
    "search_terms": ["term1", "term2"],
    "focus_areas": ["area1", "area2"]
}}
"""
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a keyword extraction assistant. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        return json.loads(response.choices[0].message.content)
    except:
        return {"search_terms": [user_question], "focus_areas": []}


def synthesize_comprehensive_agenda(
    user_question: str,
    filters: Dict,
    bills_context: List[Dict],
    financial_metrics: Dict,
    legislative_metrics: Dict,
    voting_metrics: Dict,
    committee_assignments: pd.DataFrame,
    openai_client: Any
) -> str:
    """Enhanced synthesis using ALL available metrics + semantic bill content."""
    try:
        # Format bills context
        bills_text = "\n\n".join([
            f"**{b['bill_number']}**: {b['title']}\nSummary: {b['summary'][:400]}...\nSponsor: {b['sponsor']}"
            for b in bills_context[:8]
        ]) if bills_context else "No relevant bills found in semantic search."
        
        # Financial context
        total_donations = financial_metrics.get('total', 0)
        donation_types = financial_metrics.get('by_type', pd.DataFrame())
        top_donors = financial_metrics.get('top_donors', pd.DataFrame())
        
        financial_text = f"**Total Donations:** ${total_donations:,.2f}\n\n"
        if not donation_types.empty:
            financial_text += "**Breakdown by Donor Type:**\n"
            for _, row in donation_types.iterrows():
                pct = (row['total'] / total_donations * 100) if total_donations > 0 else 0
                financial_text += f"- {row['donor_type']}: ${row['total']:,.2f} ({pct:.1f}%)\n"
        
        if not top_donors.empty:
            financial_text += "\n**Top 5 Donors:**\n"
            for _, row in top_donors.head(5).iterrows():
                financial_text += f"- {row['name']} ({row['donor_type']}): ${row['total_donated']:,.2f}\n"
        
        # Legislative context
        legislative_text = f"""**Bills Sponsored:** {legislative_metrics['sponsored']}
**Bills Cosponsored:** {legislative_metrics['total_cosponsored']}
  - Original Cosponsor: {legislative_metrics['cosponsored_original']}
  - Later Cosponsor: {legislative_metrics['cosponsored_later']}
"""
        
        # Voting context
        total_votes = voting_metrics.get('total', 0)
        vote_breakdown = voting_metrics.get('breakdown', pd.DataFrame())
        
        voting_text = f"**Total Votes Cast:** {total_votes}\n\n"
        if not vote_breakdown.empty:
            voting_text += "**Vote Breakdown:**\n"
            for _, row in vote_breakdown.iterrows():
                pct = (row['count'] / total_votes * 100) if total_votes > 0 else 0
                voting_text += f"- {row['vote_result']}: {row['count']} ({pct:.1f}%)\n"
        
        # Committee context
        committee_text = "Not assigned to any committees."
        if not committee_assignments.empty:
            committee_text = "**Committee Memberships:**\n"
            for _, row in committee_assignments.head(5).iterrows():
                committee_text += f"- {row['committee_name']} ({row['chamber']})\n"
        
        # Scope context
        scope_text = f"**Analysis Scope:** {filters['level'].title()}"
        if filters['level'] == 'politician':
            scope_text += f" - {filters.get('politician_name', 'Unknown')}"
        elif filters['level'] == 'party':
            scope_text += f" - {filters['party']} Party"
        elif filters['level'] == 'chamber':
            scope_text += f" - {filters['chamber']}"
        scope_text += f" | Congress: {filters['congress']}"
        
        # Create synthesis prompt
        prompt = f"""
You are a non-partisan political analyst. Answer the user's question using ONLY the provided data.
Be factual, cite specific bills and numbers, and maintain neutrality.

{scope_text}

User Question: "{user_question}"

=== LEGISLATIVE CONTEXT (Semantic Search of Bill Content) ===
{bills_text}

=== FINANCIAL METRICS (FEC Donation Data) ===
{financial_text}

=== LEGISLATIVE ACTIVITY METRICS ===
{legislative_text}

=== VOTING RECORD METRICS ===
{voting_text}

=== COMMITTEE ASSIGNMENTS ===
{committee_text}

Instructions:
- Synthesize a comprehensive answer using ALL the data provided
- Cite specific bill numbers, dollar amounts, and vote counts
- Connect financial patterns to legislative priorities
- Note committee influence on policy focus
- If data is insufficient for certain aspects, state what's missing
- Maintain non-partisan, analytical tone
- Format clearly with sections or bullet points as appropriate
"""
        
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a comprehensive political analyst providing factual agenda analysis based on quantitative metrics and semantic bill content."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            max_tokens=2000
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        st.error(f"Error synthesizing answer: {str(e)}")
        return "Unable to generate comprehensive analysis due to an error."


# ============================================================================
# VISUALIZATION FUNCTIONS
# ============================================================================

def create_donation_type_chart(by_type_df: pd.DataFrame) -> go.Figure:
    """Create donut chart for donation types."""
    if by_type_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No donation data available", showarrow=False, font=dict(size=14))
        return fig
    
    fig = px.pie(
        by_type_df,
        values='total',
        names='donor_type',
        title='Donations by Donor Type',
        hole=0.4
    )
    fig.update_traces(textposition='inside', textinfo='percent+label')
    return fig


def create_top_donors_chart(top_donors_df: pd.DataFrame) -> go.Figure:
    """Create horizontal bar chart for top donors."""
    if top_donors_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No donor data available", showarrow=False, font=dict(size=14))
        return fig
    
    fig = px.bar(
        top_donors_df.head(10),
        x='total_donated',
        y='name',
        orientation='h',
        title='Top 10 Donors',
        labels={'total_donated': 'Total Donated ($)', 'name': 'Donor'},
        color='donor_type'
    )
    fig.update_layout(yaxis={'categoryorder': 'total ascending'})
    return fig


def create_donations_timeline(timeline_df: pd.DataFrame) -> go.Figure:
    """Create area chart for donations over time."""
    if timeline_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No timeline data available", showarrow=False, font=dict(size=14))
        return fig
    
    fig = px.area(
        timeline_df,
        x='month',
        y='total',
        color='donor_type',
        title='Donations Over Time by Type',
        labels={'month': 'Month', 'total': 'Total Donated ($)', 'donor_type': 'Donor Type'}
    )
    return fig


def create_bills_comparison_chart(metrics: Dict) -> go.Figure:
    """Create bar chart comparing sponsored vs cosponsored bills."""
    data = {
        'Category': ['Sponsored', 'Original Cosponsor', 'Later Cosponsor'],
        'Count': [
            metrics['sponsored'],
            metrics['cosponsored_original'],
            metrics['cosponsored_later']
        ]
    }
    df = pd.DataFrame(data)
    
    fig = px.bar(
        df,
        x='Category',
        y='Count',
        title='Legislative Activity: Bills Sponsored vs. Cosponsored',
        labels={'Count': 'Number of Bills'},
        color='Category'
    )
    return fig


def create_vote_breakdown_chart(vote_df: pd.DataFrame) -> go.Figure:
    """Create pie chart for vote position breakdown."""
    if vote_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No voting data available", showarrow=False, font=dict(size=14))
        return fig
    
    fig = px.pie(
        vote_df,
        values='count',
        names='vote_position',
        title='Voting Record Breakdown',
        hole=0.3
    )
    fig.update_traces(textposition='inside', textinfo='percent+label')
    return fig


# ============================================================================
# TAB RENDERING FUNCTIONS
# ============================================================================

def render_overview_tab(financial: Dict, legislative: Dict, voting: Dict, committees: pd.DataFrame):
    """Render the Overview dashboard tab."""
    st.header("📊 Overview Dashboard")
    
    # Metrics cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Donations", f"${financial['total']:,.0f}")
    
    with col2:
        st.metric("Bills Sponsored", legislative['sponsored'])
    
    with col3:
        st.metric("Bills Cosponsored", legislative['total_cosponsored'])
    
    with col4:
        st.metric("Total Votes", voting['total'])
    
    st.markdown("---")
    
    # Quick stats grid
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("💰 Top 3 Donors")
        if not financial['top_donors'].empty:
            for idx, row in financial['top_donors'].head(3).iterrows():
                st.write(f"**{row['name']}** ({row['donor_type']}): ${row['total_donated']:,.2f}")
        else:
            st.info("No donor data available")
    
    with col2:
        st.subheader("🏛️ Committee Assignments")
        if not committees.empty:
            for idx, row in committees.head(3).iterrows():
                st.write(f"**{row['committee_name']}** ({row['chamber']})")
        else:
            st.info("No committee assignments")
    
    st.markdown("---")
    
    # Recent bills
    st.subheader("📜 Recent Bills")
    if not legislative['recent_bills'].empty:
        st.dataframe(
            legislative['recent_bills'][['official_bill_number', 'title', 'date_introduced', 'sponsor_name']],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No recent bills found")


def render_finance_tab(financial: Dict):
    """Render the Finance Analysis tab."""
    st.header("💰 Finance Analysis")
    
    # Top metric
    st.metric("Total Donations Received", f"${financial['total']:,.2f}")
    
    st.markdown("---")
    
    # Charts
    col1, col2 = st.columns(2)
    
    with col1:
        fig = create_donation_type_chart(financial['by_type'])
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        fig = create_top_donors_chart(financial['top_donors'])
        st.plotly_chart(fig, use_container_width=True)
    
    # Timeline
    if not financial['timeline'].empty:
        st.subheader("Donations Timeline")
        fig = create_donations_timeline(financial['timeline'])
        st.plotly_chart(fig, use_container_width=True)
    
    # Data table
    st.subheader("Top Donors Details")
    if not financial['top_donors'].empty:
        st.dataframe(
            financial['top_donors'][['name', 'donor_type', 'total_donated', 'num_donations']],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No donor data available")


def render_legislation_tab(legislative: Dict):
    """Render the Legislation Activity tab."""
    st.header("📜 Legislation Activity")
    
    # Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Bills Sponsored", legislative['sponsored'])
    with col2:
        st.metric("Original Cosponsor", legislative['cosponsored_original'])
    with col3:
        st.metric("Later Cosponsor", legislative['cosponsored_later'])
    
    st.markdown("---")
    
    # Chart
    fig = create_bills_comparison_chart(legislative)
    st.plotly_chart(fig, use_container_width=True)
    
    # Recent bills table
    st.subheader("Recent Bills Sponsored")
    if not legislative['recent_bills'].empty:
        st.dataframe(
            legislative['recent_bills'],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No bills found")


def render_voting_tab(voting: Dict):
    """Render the Voting Record tab."""
    st.header("🗳️ Voting Record")
    
    # Metrics
    st.metric("Total Votes Cast", voting['total'])
    
    st.markdown("---")
    
    # Chart
    if not voting['breakdown'].empty:
        fig = create_vote_breakdown_chart(voting['breakdown'])
        st.plotly_chart(fig, use_container_width=True)
    
    # Recent votes table
    st.subheader("Recent Voting History")
    if not voting['recent_votes'].empty:
        st.dataframe(
            voting['recent_votes'],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No voting data available")


def render_ai_insights_tab(bq_client, pinecone_index, openai_client, filters, financial, legislative, voting, committees):
    """Render the AI Agenda Analysis tab."""
    st.header("💬 AI Agenda Analysis")
    
    st.markdown("""
    Ask comprehensive questions about political agendas based on:
    - ✅ **Voting patterns** and participation
    - ✅ **Bills sponsored and cosponsored** (quantitative metrics)
    - ✅ **Bill content and summaries** (semantic analysis via RAG)
    - ✅ **Donation sources and amounts** by type
    - ✅ **Committee assignments** and policy focus
    """)
    
    # Sample questions
    with st.expander("📚 Example Questions"):
        scope_name = filters.get('politician_name', filters.get('party', filters.get('chamber', 'Congress')))
        st.markdown(f"""
        - What is {scope_name}'s agenda based on all activity?
        - Describe {scope_name}'s policy priorities using voting and legislation data
        - What industries fund {scope_name} and how does it relate to their bills?
        - Analyze {scope_name}'s legislative focus areas
        """)
    
    # Question input
    user_question = st.text_area(
        "Ask a question:",
        placeholder="e.g., What is Nancy Pelosi's agenda on healthcare based on her voting, bills, and funding?",
        height=100
    )
    
    if st.button("🔍 Analyze Agenda", type="primary"):
        if not user_question:
            st.warning("Please enter a question.")
            return
        
        with st.spinner("🧠 Analyzing comprehensive data and generating insights..."):
            # Extract keywords for semantic search
            keywords = extract_keywords_for_synthesis(user_question, openai_client)
            search_query = " ".join(keywords.get("search_terms", [user_question]))
            
            # Semantic bill search
            bills_context = search_bills_semantic(search_query, openai_client, pinecone_index, k=10)
            
            # Generate comprehensive synthesis
            answer = synthesize_comprehensive_agenda(
                user_question,
                filters,
                bills_context,
                financial,
                legislative,
                voting,
                committees,
                openai_client
            )
            
            # Display answer
            st.markdown("### 💡 Comprehensive Analysis")
            st.markdown(answer)
            
            st.markdown("---")
            
            # Source attribution
            st.subheader("📎 Data Sources Used")
            
            with st.expander("📜 Relevant Bills (Semantic Search)", expanded=False):
                if bills_context:
                    for i, bill in enumerate(bills_context[:5], 1):
                        st.markdown(f"**{i}. {bill['bill_number']}** (Score: {bill['score']:.3f})")
                        st.markdown(f"*{bill['title']}*")
                        st.markdown(f"**Sponsor:** {bill['sponsor']}")
                        st.markdown(f"**Summary:** {bill['summary'][:300]}...")
                        st.markdown("---")
                else:
                    st.info("No semantically relevant bills found")
            
            with st.expander("💰 Financial Metrics", expanded=False):
                st.metric("Total Donations", f"${financial['total']:,.2f}")
                if not financial['by_type'].empty:
                    st.dataframe(financial['by_type'], use_container_width=True)
                if not financial['top_donors'].empty:
                    st.dataframe(financial['top_donors'].head(5), use_container_width=True)
            
            with st.expander("📊 Legislative Metrics", expanded=False):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Sponsored", legislative['sponsored'])
                with col2:
                    st.metric("Cosponsored (Orig)", legislative['cosponsored_original'])
                with col3:
                    st.metric("Cosponsored (Later)", legislative['cosponsored_later'])
            
            with st.expander("🗳️ Voting Metrics", expanded=False):
                st.metric("Total Votes", voting['total'])
                if not voting['breakdown'].empty:
                    st.dataframe(voting['breakdown'], use_container_width=True)


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    """Main application with global filters and multi-tab dashboard."""
    
    # Header
    st.title("🏛️ Politician Agenda Analyzer")
    st.markdown("**Comprehensive Analytics Dashboard** | Quantitative Metrics + Semantic RAG Analysis")
    
    # Initialize services
    with st.spinner("🔌 Connecting to services..."):
        bq_client, pinecone_index, openai_client = get_services()
    
    # ========================================================================
    # SIDEBAR: GLOBAL FILTERS
    # ========================================================================
    
    with st.sidebar:
        st.header("📍 Global Filters")
        st.markdown("*Applied to all tabs*")
        
        # Level selection
        level = st.selectbox(
            "Analysis Level",
            options=['politician', 'party', 'chamber', 'committee', 'congress'],
            format_func=lambda x: x.title()
        )
        
        # Dynamic filter based on level
        politician_id = None
        politician_name = None
        party = None
        chamber = "Both"
        committee_id = None
        
        if level == 'politician':
            politicians_df = get_politician_list(bq_client)
            selected_politician = st.selectbox(
                "Select Politician",
                options=politicians_df['name'].tolist()
            )
            if selected_politician:
                politician_row = politicians_df[politicians_df['name'] == selected_politician].iloc[0]
                politician_id = int(politician_row['politician_id'])
                politician_name = selected_politician
        
        elif level == 'party':
            party = st.selectbox("Select Party", options=['Republican', 'Democratic', 'Independent'])
        
        elif level == 'chamber':
            chamber = st.selectbox("Select Chamber", options=['House', 'Senate', 'Both'])
        
        elif level == 'committee':
            committees_df = get_committee_list(bq_client)
            selected_committee = st.selectbox(
                "Select Committee",
                options=committees_df['committee_name'].tolist()
            )
            if selected_committee:
                committee_row = committees_df[committees_df['committee_name'] == selected_committee].iloc[0]
                committee_id = int(committee_row['committee_id'])
        
        # Congress filter
        congress = st.selectbox("Congress", options=['Both', '118', '119'])
        
        # Apply button
        apply_filters = st.button("🔄 Apply Filters", type="primary")
        
        st.markdown("---")
        st.caption("Data updates every 10 minutes")
    
    # Build filters dictionary
    filters = {
        'level': level,
        'politician_id': politician_id,
        'politician_name': politician_name,
        'party': party,
        'chamber': chamber,
        'committee_id': committee_id,
        'congress': congress
    }
    
    # ========================================================================
    # FETCH DATA (when filters applied)
    # ========================================================================
    
    if apply_filters or 'data_loaded' not in st.session_state:
        with st.spinner("📊 Loading comprehensive metrics..."):
            try:
                filters_json = json.dumps(filters)
                financial = get_financial_metrics(bq_client, filters_json)
                legislative = get_legislative_metrics(bq_client, filters_json)
                voting = get_voting_metrics(bq_client, filters_json)
                committees = get_committee_assignments(bq_client, filters_json)
                
                # Store in session state
                st.session_state['financial'] = financial
                st.session_state['legislative'] = legislative
                st.session_state['voting'] = voting
                st.session_state['committees'] = committees
                st.session_state['filters'] = filters
                st.session_state['data_loaded'] = True
                
                st.success("✅ Data loaded successfully!")
            except Exception as e:
                st.error(f"Error loading data: {str(e)}")
                return
    
    # Retrieve from session state
    if 'data_loaded' in st.session_state:
        financial = st.session_state['financial']
        legislative = st.session_state['legislative']
        voting = st.session_state['voting']
        committees = st.session_state['committees']
        filters = st.session_state['filters']
    else:
        st.info("👈 Select filters and click 'Apply Filters' to load data")
        return
    
    # ========================================================================
    # TABS
    # ========================================================================
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🏠 Overview",
        "💰 Finance",
        "📜 Legislation",
        "🗳️ Voting",
        "💬 AI Insights"
    ])
    
    with tab1:
        render_overview_tab(financial, legislative, voting, committees)
    
    with tab2:
        render_finance_tab(financial)
    
    with tab3:
        render_legislation_tab(legislative)
    
    with tab4:
        render_voting_tab(voting)
    
    with tab5:
        render_ai_insights_tab(bq_client, pinecone_index, openai_client, filters, financial, legislative, voting, committees)


if __name__ == "__main__":
    main()
