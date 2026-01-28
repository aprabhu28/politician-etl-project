"""
Politician Agenda Analyzer - Hybrid Search Application
Combines Pinecone (Semantic Search) + BigQuery (SQL Analytics) + GPT Synthesis
"""

import streamlit as st
import os
from dotenv import load_dotenv
import pandas as pd
from typing import List, Dict, Any, Tuple
import json

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
# SERVICE INITIALIZATION
# ============================================================================

@st.cache_resource
def get_services() -> Tuple[Any, Any, Any]:
    """
    Initialize and cache connections to BigQuery, Pinecone, and OpenAI.
    Returns: (bigquery_client, pinecone_index, openai_client)
    """
    try:
        # Initialize BigQuery Client
        bq_client = bigquery.Client(project="starlit-verve-376800")
        
        # Initialize Pinecone
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        if not pinecone_api_key:
            raise ValueError("PINECONE_API_KEY not found in environment variables")
        
        pc = Pinecone(api_key=pinecone_api_key)
        pinecone_index = pc.Index("bills-index")
        
        # Initialize OpenAI
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        openai_client = OpenAI(api_key=openai_api_key)
        
        return bq_client, pinecone_index, openai_client
    
    except Exception as e:
        st.error(f"❌ Connection Error: {str(e)}")
        st.info("Please ensure:\n- Google Cloud credentials are configured (run `gcloud auth application-default login`)\n- PINECONE_API_KEY is set in .env\n- OPENAI_API_KEY is set in .env")
        st.stop()


# ============================================================================
# SEMANTIC SEARCH (THE "LIBRARIAN")
# ============================================================================

def search_bills(query: str, openai_client: Any, pinecone_index: Any, k: int = 5) -> List[Dict[str, Any]]:
    """
    Search for bills using semantic similarity via Pinecone.
    
    Args:
        query: User's natural language query
        openai_client: OpenAI client instance
        pinecone_index: Pinecone index instance
        k: Number of results to return
    
    Returns:
        List of dicts with bill information
    """
    try:
        # Generate embedding for user query
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query
        )
        query_embedding = response.data[0].embedding
        
        # Query Pinecone
        results = pinecone_index.query(
            vector=query_embedding,
            top_k=k,
            include_metadata=True
        )
        
        # Format results
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
# ANALYTICAL SEARCH (THE "ANALYST")
# ============================================================================

def get_top_donors(bq_client: Any, keywords: List[str], limit: int = 10) -> pd.DataFrame:
    """
    Query BigQuery for top donors matching keywords.
    
    Args:
        bq_client: BigQuery client instance
        keywords: List of keywords to search for in donor names
        limit: Maximum number of results
    
    Returns:
        DataFrame with donor statistics
    """
    try:
        # Build WHERE clause for multiple keywords
        keyword_conditions = " OR ".join([f"LOWER(donors.name) LIKE LOWER('%{kw}%')" for kw in keywords])
        
        query = f"""
        SELECT 
            donors.name AS donor_name,
            donors.city,
            donors.state,
            COUNT(DISTINCT donations.donation_id) AS num_donations,
            SUM(donations.amount) AS total_amount,
            AVG(donations.amount) AS avg_amount
        FROM 
            `starlit-verve-376800.politician_analytics.donations` AS donations
        JOIN 
            `starlit-verve-376800.politician_analytics.donors` AS donors
        ON 
            donations.donor_id = donors.donor_id
        WHERE 
            {keyword_conditions}
        GROUP BY 
            donors.name, donors.city, donors.state
        ORDER BY 
            total_amount DESC
        LIMIT {limit}
        """
        
        df = bq_client.query(query).to_dataframe()
        return df
    
    except Exception as e:
        st.error(f"Error querying donors: {str(e)}")
        return pd.DataFrame()


def get_politician_votes(bq_client: Any, politician_name: str, keywords: List[str] = None, limit: int = 10) -> pd.DataFrame:
    """
    Query BigQuery for a politician's voting record, optionally filtered by keywords.
    
    Args:
        bq_client: BigQuery client instance
        politician_name: Name of the politician
        keywords: Optional keywords to filter vote descriptions
        limit: Maximum number of results
    
    Returns:
        DataFrame with voting record
    """
    try:
        keyword_filter = ""
        if keywords:
            keyword_conditions = " OR ".join([f"LOWER(votes.description) LIKE LOWER('%{kw}%')" for kw in keywords])
            keyword_filter = f"AND ({keyword_conditions})"
        
        query = f"""
        SELECT 
            votes.vote_date,
            votes.description,
            votes.vote_result,
            votes.vote_type,
            votes.chamber
        FROM 
            `starlit-verve-376800.politician_analytics.votes` AS votes
        JOIN 
            `starlit-verve-376800.politician_analytics.politicians` AS politicians
        ON 
            votes.politician_id = politicians.politician_id
        WHERE 
            (LOWER(CONCAT(politicians.first_name, ' ', politicians.last_name)) LIKE LOWER('%{politician_name}%')
            OR LOWER(politicians.last_name) LIKE LOWER('%{politician_name}%'))
            {keyword_filter}
        ORDER BY 
            votes.vote_date DESC
        LIMIT {limit}
        """
        
        df = bq_client.query(query).to_dataframe()
        return df
    
    except Exception as e:
        st.error(f"Error querying votes: {str(e)}")
        return pd.DataFrame()


def get_bill_sponsors_donors(bq_client: Any, bill_number: str, limit: int = 10) -> pd.DataFrame:
    """
    Get top donors to the sponsor of a specific bill.
    
    Args:
        bq_client: BigQuery client instance
        bill_number: Bill number (e.g., "H.R. 1")
        limit: Maximum number of results
    
    Returns:
        DataFrame with donor statistics for bill sponsor
    """
    try:
        query = f"""
        WITH bill_sponsor AS (
            SELECT politician_id
            FROM `starlit-verve-376800.politician_analytics.bills`
            WHERE LOWER(official_bill_number) = LOWER('{bill_number}')
            LIMIT 1
        )
        SELECT 
            donors.name AS donor_name,
            donors.city,
            donors.state,
            SUM(donations.amount) AS total_amount,
            COUNT(donations.donation_id) AS num_donations
        FROM 
            `starlit-verve-376800.politician_analytics.donations` AS donations
        JOIN 
            `starlit-verve-376800.politician_analytics.donors` AS donors
        ON 
            donations.donor_id = donors.donor_id
        WHERE 
            donations.politician_id IN (SELECT politician_id FROM bill_sponsor)
        GROUP BY 
            donors.name, donors.city, donors.state
        ORDER BY 
            total_amount DESC
        LIMIT {limit}
        """
        
        df = bq_client.query(query).to_dataframe()
        return df
    
    except Exception as e:
        st.error(f"Error querying bill sponsors: {str(e)}")
        return pd.DataFrame()


# ============================================================================
# KEYWORD EXTRACTION
# ============================================================================

def extract_keywords(user_question: str, openai_client: Any) -> Dict[str, Any]:
    """
    Use LLM to extract structured search terms from user's natural language question.
    
    Args:
        user_question: User's input query
        openai_client: OpenAI client instance
    
    Returns:
        Dict with extracted keywords and entities
    """
    try:
        prompt = f"""
You are a keyword extraction assistant. Analyze the following user question and extract:
1. Main topics/themes (for bill search)
2. Politician names (if any)
3. Industry/donor keywords (for financial search)

User Question: "{user_question}"

Return your response as valid JSON with this structure:
{{
    "bill_search_terms": ["keyword1", "keyword2"],
    "politician_names": ["name1"],
    "donor_keywords": ["industry1", "company1"]
}}

Be concise. Only include terms directly relevant to the question.
"""
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful keyword extraction assistant. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        # Parse JSON response
        keywords_json = response.choices[0].message.content
        keywords = json.loads(keywords_json)
        
        return keywords
    
    except Exception as e:
        st.error(f"Error extracting keywords: {str(e)}")
        # Return safe defaults
        return {
            "bill_search_terms": [user_question],
            "politician_names": [],
            "donor_keywords": []
        }


# ============================================================================
# SYNTHESIS ENGINE
# ============================================================================

def synthesize_answer(
    user_question: str,
    bills: List[Dict],
    donors_df: pd.DataFrame,
    votes_df: pd.DataFrame,
    openai_client: Any
) -> str:
    """
    Use GPT-4 to synthesize a comprehensive answer from all retrieved data.
    
    Args:
        user_question: Original user question
        bills: List of relevant bills from Pinecone
        donors_df: Donor statistics from BigQuery
        votes_df: Voting record from BigQuery (if applicable)
        openai_client: OpenAI client instance
    
    Returns:
        Synthesized answer string
    """
    try:
        # Format context
        bills_context = "\n\n".join([
            f"**{b['bill_number']}**: {b['title']}\nSummary: {b['summary'][:500]}...\nSponsor: {b['sponsor']}"
            for b in bills[:5]
        ])
        
        donors_context = ""
        if not donors_df.empty:
            donors_context = "**Top Donors:**\n" + donors_df.to_string(index=False)
        
        votes_context = ""
        if not votes_df.empty:
            votes_context = "**Voting Record:**\n" + votes_df.to_string(index=False)
        
        # Create synthesis prompt
        prompt = f"""
You are a non-partisan political analyst. Answer the user's question using ONLY the provided data.
Be factual, cite specific bills and numbers, and maintain neutrality.

User Question: "{user_question}"

=== LEGISLATIVE CONTEXT (from bill database) ===
{bills_context}

=== FINANCIAL CONTEXT (from FEC donation records) ===
{donors_context}

=== VOTING RECORD (if applicable) ===
{votes_context}

Instructions:
- Answer the question directly using the data provided
- Cite specific bill numbers and donor amounts
- If data is insufficient, state what's missing
- Maintain non-partisan tone
- Format your answer clearly with bullet points or sections as appropriate
"""
        
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a non-partisan political analyst providing factual answers based solely on provided data."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=1500
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        st.error(f"Error synthesizing answer: {str(e)}")
        return "Unable to generate answer due to an error."


# ============================================================================
# STREAMLIT UI
# ============================================================================

def main():
    """Main Streamlit application."""
    
    # Page config
    st.set_page_config(
        page_title="Politician Agenda Analyzer",
        page_icon="🏛️",
        layout="wide"
    )
    
    # Header
    st.title("🏛️ Politician Agenda Analyzer")
    st.markdown("**Hybrid Search System**: Semantic Bill Search (Pinecone) + Financial Analytics (BigQuery) + AI Synthesis (GPT-4)")
    
    # Initialize services
    with st.spinner("🔌 Connecting to cloud services..."):
        bq_client, pinecone_index, openai_client = get_services()
    
    st.success("✅ Connected to BigQuery & Pinecone")
    
    # Sidebar for advanced options
    with st.sidebar:
        st.header("⚙️ Search Settings")
        num_bills = st.slider("Bills to retrieve", 3, 10, 5)
        num_donors = st.slider("Donors to analyze", 5, 20, 10)
        
        st.markdown("---")
        st.markdown("### 📚 Example Questions")
        st.markdown("""
        - Does Nancy Pelosi support AI regulation?
        - What bills has Ted Cruz sponsored about energy?
        - Who are the top donors to sponsors of crypto bills?
        - Show me Elizabeth Warren's voting record on banking
        """)
    
    # Main query input
    st.markdown("---")
    user_question = st.text_input(
        "🔍 Ask a question about politicians, bills, or campaign finance:",
        placeholder="e.g., What is AOC's stance on climate legislation?"
    )
    
    if st.button("🚀 Analyze", type="primary") or user_question:
        if not user_question:
            st.warning("Please enter a question.")
            return
        
        with st.spinner("🧠 Analyzing your question..."):
            # Step 1: Extract keywords
            st.info("📝 Extracting search terms...")
            keywords = extract_keywords(user_question, openai_client)
            
            with st.expander("🔍 Extracted Keywords", expanded=False):
                st.json(keywords)
            
            # Step 2: Parallel search execution
            col1, col2 = st.columns(2)
            
            with col1:
                st.info("📚 Searching legislative database...")
            with col2:
                st.info("💰 Querying financial records...")
            
            # Semantic search for bills
            bill_search_query = " ".join(keywords.get("bill_search_terms", [user_question]))
            bills = search_bills(bill_search_query, openai_client, pinecone_index, k=num_bills)
            
            # Analytical searches
            donors_df = pd.DataFrame()
            votes_df = pd.DataFrame()
            
            # Search for donors if donor keywords exist
            donor_keywords = keywords.get("donor_keywords", [])
            if donor_keywords:
                donors_df = get_top_donors(bq_client, donor_keywords, limit=num_donors)
            
            # Search for votes if politician mentioned
            politician_names = keywords.get("politician_names", [])
            if politician_names:
                politician_name = politician_names[0]
                votes_df = get_politician_votes(
                    bq_client,
                    politician_name,
                    keywords=keywords.get("bill_search_terms", []),
                    limit=10
                )
            
            # Step 3: Synthesize answer
            st.markdown("---")
            st.subheader("📊 Analysis Results")
            
            with st.spinner("🤖 Generating comprehensive answer..."):
                answer = synthesize_answer(
                    user_question,
                    bills,
                    donors_df,
                    votes_df,
                    openai_client
                )
            
            # Display answer prominently
            st.markdown("### 💡 Answer")
            st.markdown(answer)
            
            # Display sources
            st.markdown("---")
            st.subheader("📎 Sources & Data")
            
            # Bills source
            with st.expander("📜 Relevant Bills from Vector Search", expanded=True):
                if bills:
                    for i, bill in enumerate(bills, 1):
                        st.markdown(f"**{i}. {bill['bill_number']}** (Score: {bill['score']:.3f})")
                        st.markdown(f"*{bill['title']}*")
                        st.markdown(f"**Sponsor:** {bill['sponsor']}")
                        st.markdown(f"**Summary:** {bill['summary'][:300]}...")
                        st.markdown("---")
                else:
                    st.info("No bills found for this query.")
            
            # Donors source
            if not donors_df.empty:
                with st.expander("💵 Financial Data from BigQuery", expanded=True):
                    st.dataframe(donors_df, use_container_width=True)
                    st.caption(f"Total donors analyzed: {len(donors_df)}")
            
            # Votes source
            if not votes_df.empty:
                with st.expander("🗳️ Voting Record from BigQuery", expanded=True):
                    st.dataframe(votes_df, use_container_width=True)
                    st.caption(f"Total votes analyzed: {len(votes_df)}")


if __name__ == "__main__":
    main()
