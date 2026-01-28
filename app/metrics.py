"""
Metrics endpoints for analytical aggregations.
Provides comprehensive metrics for politicians, committees, chambers, parties, and congresses.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_, or_
from typing import List, Optional
from datetime import date

from .database import get_db
from .models import Politician, Donor, Donation, Bill, Vote, BillCosponsor, Committee, CommitteeAssignment

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/politician/{politician_id}")
def get_politician_metrics(
    politician_id: int,
    db: Session = Depends(get_db),
    congress: Optional[int] = Query(None, description="Filter by congress (118 or 119)")
):
    """
    Get comprehensive metrics for a single politician.
    
    Returns:
    - Donation totals and breakdowns
    - Top donors
    - Bills sponsored/cosponsored counts
    - Voting record
    """
    # Verify politician exists
    politician = db.query(Politician).filter(Politician.politician_id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail=f"Politician {politician_id} not found")
    
    # Base filters
    donation_filter = [Donation.politician_id == politician_id]
    bill_filter = [Bill.sponsor_id == politician_id]
    cosponsor_filter = [BillCosponsor.politician_id == politician_id]
    vote_filter = [Vote.politician_id == politician_id]
    
    if congress:
        # Filter bills by congress
        bill_filter.append(Bill.congress == congress)
        # Filter votes by bills in that congress
        vote_filter.append(Bill.congress == congress)
    
    # DONATIONS METRICS
    total_donations = db.query(func.sum(Donation.amount)).filter(*donation_filter).scalar() or 0
    
    # Donations by type
    donation_by_type = db.query(
        Donor.donor_type,
        func.sum(Donation.amount).label('total')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_type).all()
    
    donations_breakdown = {dt: float(total) for dt, total in donation_by_type if dt}
    total_for_percentage = sum(donations_breakdown.values()) or 1  # Avoid division by zero
    donations_percentage = {dt: (amt / total_for_percentage) * 100 for dt, amt in donations_breakdown.items()}
    
    # Top donors
    top_donors = db.query(
        Donor.name,
        Donor.donor_type,
        func.sum(Donation.amount).label('total_donated')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_id, Donor.name, Donor.donor_type).order_by(func.sum(Donation.amount).desc()).limit(10).all()
    
    # BILLS METRICS
    bills_sponsored = db.query(Bill).filter(*bill_filter).count()
    
    # Cosponsored bills
    cosponsored_query = db.query(BillCosponsor).filter(*cosponsor_filter)
    if congress:
        cosponsored_query = cosponsored_query.join(Bill).filter(Bill.congress == congress)
    
    bills_cosponsored_original = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == True).count()
    bills_cosponsored_later = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == False).count()
    
    # VOTING METRICS
    vote_query = db.query(Vote).filter(*vote_filter)
    if congress:
        vote_query = vote_query.join(Bill).filter(Bill.congress == congress)
    
    total_votes = vote_query.count()
    
    # Vote breakdown
    vote_breakdown = vote_query.with_entities(
        Vote.vote_position,
        func.count(Vote.vote_id).label('count')
    ).group_by(Vote.vote_position).all()
    
    votes_by_position = {vp: count for vp, count in vote_breakdown if vp}
    
    return {
        "politician": {
            "politician_id": politician.politician_id,
            "name": f"{politician.first_name} {politician.last_name}",
            "party": politician.party,
            "state": politician.state,
            "chamber": politician.chamber
        },
        "donations": {
            "total_amount": float(total_donations),
            "by_type": donations_breakdown,
            "percentage_by_type": donations_percentage,
            "top_donors": [
                {
                    "name": name,
                    "type": dtype,
                    "total_donated": float(total)
                }
                for name, dtype, total in top_donors
            ]
        },
        "bills": {
            "sponsored": bills_sponsored,
            "cosponsored_original": bills_cosponsored_original,
            "cosponsored_later": bills_cosponsored_later,
            "total_cosponsored": bills_cosponsored_original + bills_cosponsored_later
        },
        "votes": {
            "total": total_votes,
            "by_position": votes_by_position
        },
        "filters_applied": {
            "congress": congress
        }
    }


@router.get("/politicians")
def get_multiple_politicians_metrics(
    politician_ids: str = Query(..., description="Comma-separated politician IDs (e.g., '1,2,3')"),
    db: Session = Depends(get_db),
    congress: Optional[int] = Query(None, description="Filter by congress (118 or 119)")
):
    """
    Get aggregated metrics for multiple politicians.
    Useful for comparing politicians or analyzing groups.
    """
    # Parse politician IDs
    try:
        ids = [int(pid.strip()) for pid in politician_ids.split(',')]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid politician_ids format. Use comma-separated integers.")
    
    # Verify politicians exist
    politicians = db.query(Politician).filter(Politician.politician_id.in_(ids)).all()
    if not politicians:
        raise HTTPException(status_code=404, detail="No politicians found with provided IDs")
    
    found_ids = {p.politician_id for p in politicians}
    missing_ids = set(ids) - found_ids
    
    # Base filters
    donation_filter = [Donation.politician_id.in_(ids)]
    bill_filter = [Bill.sponsor_id.in_(ids)]
    cosponsor_filter = [BillCosponsor.politician_id.in_(ids)]
    vote_filter = [Vote.politician_id.in_(ids)]
    
    if congress:
        bill_filter.append(Bill.congress == congress)
        vote_filter.append(Bill.congress == congress)
    
    # AGGREGATE DONATIONS
    total_donations = db.query(func.sum(Donation.amount)).filter(*donation_filter).scalar() or 0
    
    donation_by_type = db.query(
        Donor.donor_type,
        func.sum(Donation.amount).label('total')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_type).all()
    
    donations_breakdown = {dt: float(total) for dt, total in donation_by_type if dt}
    
    # Top donors across all politicians
    top_donors = db.query(
        Donor.name,
        Donor.donor_type,
        func.sum(Donation.amount).label('total_donated')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_id, Donor.name, Donor.donor_type).order_by(func.sum(Donation.amount).desc()).limit(10).all()
    
    # AGGREGATE BILLS
    bills_sponsored = db.query(Bill).filter(*bill_filter).count()
    
    cosponsored_query = db.query(BillCosponsor).filter(*cosponsor_filter)
    if congress:
        cosponsored_query = cosponsored_query.join(Bill).filter(Bill.congress == congress)
    
    bills_cosponsored_original = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == True).count()
    bills_cosponsored_later = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == False).count()
    
    # AGGREGATE VOTES
    vote_query = db.query(Vote).filter(*vote_filter)
    if congress:
        vote_query = vote_query.join(Bill).filter(Bill.congress == congress)
    
    total_votes = vote_query.count()
    
    vote_breakdown = vote_query.with_entities(
        Vote.vote_position,
        func.count(Vote.vote_id).label('count')
    ).group_by(Vote.vote_position).all()
    
    votes_by_position = {vp: count for vp, count in vote_breakdown if vp}
    
    return {
        "scope": "multiple_politicians",
        "politicians": [
            {
                "politician_id": p.politician_id,
                "name": f"{p.first_name} {p.last_name}",
                "party": p.party,
                "state": p.state,
                "chamber": p.chamber
            }
            for p in politicians
        ],
        "missing_politician_ids": list(missing_ids) if missing_ids else None,
        "donations": {
            "total_amount": float(total_donations),
            "by_type": donations_breakdown,
            "top_donors": [
                {"name": name, "type": dtype, "total_donated": float(total)}
                for name, dtype, total in top_donors
            ]
        },
        "bills": {
            "sponsored": bills_sponsored,
            "cosponsored_original": bills_cosponsored_original,
            "cosponsored_later": bills_cosponsored_later,
            "total_cosponsored": bills_cosponsored_original + bills_cosponsored_later
        },
        "votes": {
            "total": total_votes,
            "by_position": votes_by_position
        },
        "filters_applied": {
            "congress": congress
        }
    }


@router.get("/chamber/{chamber}")
def get_chamber_metrics(
    chamber: str,
    db: Session = Depends(get_db),
    congress: Optional[int] = Query(None, description="Filter by congress (118 or 119)")
):
    """
    Get aggregated metrics for an entire chamber (House or Senate).
    
    Chamber must be 'House' or 'Senate'.
    """
    chamber = chamber.capitalize()
    if chamber not in ['House', 'Senate']:
        raise HTTPException(status_code=400, detail="Chamber must be 'House' or 'Senate'")
    
    # Get all politicians in chamber
    politicians = db.query(Politician).filter(Politician.chamber == chamber).all()
    politician_ids = [p.politician_id for p in politicians]
    
    if not politician_ids:
        raise HTTPException(status_code=404, detail=f"No politicians found in {chamber}")
    
    # Use same aggregation logic
    donation_filter = [Donation.politician_id.in_(politician_ids)]
    bill_filter = [Bill.sponsor_id.in_(politician_ids)]
    cosponsor_filter = [BillCosponsor.politician_id.in_(politician_ids)]
    vote_filter = [Vote.politician_id.in_(politician_ids)]
    
    if congress:
        bill_filter.append(Bill.congress == congress)
        vote_filter.append(Bill.congress == congress)
    
    # DONATIONS
    total_donations = db.query(func.sum(Donation.amount)).filter(*donation_filter).scalar() or 0
    
    donation_by_type = db.query(
        Donor.donor_type,
        func.sum(Donation.amount).label('total')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_type).all()
    
    donations_breakdown = {dt: float(total) for dt, total in donation_by_type if dt}
    
    # BILLS
    bills_sponsored = db.query(Bill).filter(*bill_filter).count()
    
    cosponsored_query = db.query(BillCosponsor).filter(*cosponsor_filter)
    if congress:
        cosponsored_query = cosponsored_query.join(Bill).filter(Bill.congress == congress)
    
    bills_cosponsored_original = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == True).count()
    bills_cosponsored_later = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == False).count()
    
    # VOTES
    vote_query = db.query(Vote).filter(*vote_filter)
    if congress:
        vote_query = vote_query.join(Bill).filter(Bill.congress == congress)
    
    total_votes = vote_query.count()
    
    vote_breakdown = vote_query.with_entities(
        Vote.vote_position,
        func.count(Vote.vote_id).label('count')
    ).group_by(Vote.vote_position).all()
    
    votes_by_position = {vp: count for vp, count in vote_breakdown if vp}
    
    return {
        "scope": "chamber",
        "chamber": chamber,
        "total_politicians": len(politician_ids),
        "donations": {
            "total_amount": float(total_donations),
            "by_type": donations_breakdown
        },
        "bills": {
            "sponsored": bills_sponsored,
            "cosponsored_original": bills_cosponsored_original,
            "cosponsored_later": bills_cosponsored_later
        },
        "votes": {
            "total": total_votes,
            "by_position": votes_by_position
        },
        "filters_applied": {
            "congress": congress
        }
    }


@router.get("/party/{party}")
def get_party_metrics(
    party: str,
    db: Session = Depends(get_db),
    congress: Optional[int] = Query(None, description="Filter by congress (118 or 119)"),
    chamber: Optional[str] = Query(None, description="Filter by chamber (House or Senate)")
):
    """
    Get aggregated metrics for a political party.
    
    Party examples: 'Democrat', 'Republican', 'Independent'
    Optionally filter by chamber.
    """
    # Get all politicians in party
    query = db.query(Politician).filter(Politician.party == party)
    if chamber:
        query = query.filter(Politician.chamber == chamber.capitalize())
    
    politicians = query.all()
    politician_ids = [p.politician_id for p in politicians]
    
    if not politician_ids:
        raise HTTPException(status_code=404, detail=f"No politicians found for party '{party}'")
    
    # Same aggregation pattern
    donation_filter = [Donation.politician_id.in_(politician_ids)]
    bill_filter = [Bill.sponsor_id.in_(politician_ids)]
    cosponsor_filter = [BillCosponsor.politician_id.in_(politician_ids)]
    vote_filter = [Vote.politician_id.in_(politician_ids)]
    
    if congress:
        bill_filter.append(Bill.congress == congress)
        vote_filter.append(Bill.congress == congress)
    
    # DONATIONS
    total_donations = db.query(func.sum(Donation.amount)).filter(*donation_filter).scalar() or 0
    
    donation_by_type = db.query(
        Donor.donor_type,
        func.sum(Donation.amount).label('total')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_type).all()
    
    donations_breakdown = {dt: float(total) for dt, total in donation_by_type if dt}
    
    # BILLS
    bills_sponsored = db.query(Bill).filter(*bill_filter).count()
    
    cosponsored_query = db.query(BillCosponsor).filter(*cosponsor_filter)
    if congress:
        cosponsored_query = cosponsored_query.join(Bill).filter(Bill.congress == congress)
    
    bills_cosponsored_original = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == True).count()
    bills_cosponsored_later = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == False).count()
    
    # VOTES
    vote_query = db.query(Vote).filter(*vote_filter)
    if congress:
        vote_query = vote_query.join(Bill).filter(Bill.congress == congress)
    
    total_votes = vote_query.count()
    
    vote_breakdown = vote_query.with_entities(
        Vote.vote_position,
        func.count(Vote.vote_id).label('count')
    ).group_by(Vote.vote_position).all()
    
    votes_by_position = {vp: count for vp, count in vote_breakdown if vp}
    
    return {
        "scope": "party",
        "party": party,
        "chamber_filter": chamber,
        "total_politicians": len(politician_ids),
        "donations": {
            "total_amount": float(total_donations),
            "by_type": donations_breakdown
        },
        "bills": {
            "sponsored": bills_sponsored,
            "cosponsored_original": bills_cosponsored_original,
            "cosponsored_later": bills_cosponsored_later
        },
        "votes": {
            "total": total_votes,
            "by_position": votes_by_position
        },
        "filters_applied": {
            "congress": congress,
            "chamber": chamber
        }
    }


@router.get("/congress/{congress_number}")
def get_congress_metrics(
    congress_number: int,
    db: Session = Depends(get_db),
    chamber: Optional[str] = Query(None, description="Filter by chamber (House or Senate)"),
    party: Optional[str] = Query(None, description="Filter by party")
):
    """
    Get aggregated metrics for an entire congress (118th or 119th).
    Optionally filter by chamber and/or party.
    """
    if congress_number not in [118, 119]:
        raise HTTPException(status_code=400, detail="Only 118th and 119th Congress are supported")
    
    # Get all politicians (optionally filtered)
    query = db.query(Politician)
    if chamber:
        query = query.filter(Politician.chamber == chamber.capitalize())
    if party:
        query = query.filter(Politician.party == party)
    
    politicians = query.all()
    politician_ids = [p.politician_id for p in politicians]
    
    if not politician_ids:
        raise HTTPException(status_code=404, detail="No politicians found with given filters")
    
    # Aggregations with congress filter
    donation_filter = [Donation.politician_id.in_(politician_ids)]
    bill_filter = [Bill.sponsor_id.in_(politician_ids), Bill.congress == congress_number]
    cosponsor_filter = [BillCosponsor.politician_id.in_(politician_ids)]
    vote_filter = [Vote.politician_id.in_(politician_ids)]
    
    # DONATIONS
    total_donations = db.query(func.sum(Donation.amount)).filter(*donation_filter).scalar() or 0
    
    donation_by_type = db.query(
        Donor.donor_type,
        func.sum(Donation.amount).label('total')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_type).all()
    
    donations_breakdown = {dt: float(total) for dt, total in donation_by_type if dt}
    
    # BILLS
    bills_sponsored = db.query(Bill).filter(*bill_filter).count()
    
    cosponsored_query = db.query(BillCosponsor).join(Bill).filter(
        BillCosponsor.politician_id.in_(politician_ids),
        Bill.congress == congress_number
    )
    
    bills_cosponsored_original = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == True).count()
    bills_cosponsored_later = cosponsored_query.filter(BillCosponsor.is_original_cosponsor == False).count()
    
    # VOTES
    vote_query = db.query(Vote).join(Bill).filter(
        Vote.politician_id.in_(politician_ids),
        Bill.congress == congress_number
    )
    
    total_votes = vote_query.count()
    
    vote_breakdown = vote_query.with_entities(
        Vote.vote_position,
        func.count(Vote.vote_id).label('count')
    ).group_by(Vote.vote_position).all()
    
    votes_by_position = {vp: count for vp, count in vote_breakdown if vp}
    
    return {
        "scope": "congress",
        "congress": congress_number,
        "total_politicians": len(politician_ids),
        "donations": {
            "total_amount": float(total_donations),
            "by_type": donations_breakdown
        },
        "bills": {
            "sponsored": bills_sponsored,
            "cosponsored_original": bills_cosponsored_original,
            "cosponsored_later": bills_cosponsored_later
        },
        "votes": {
            "total": total_votes,
            "by_position": votes_by_position
        },
        "filters_applied": {
            "congress": congress_number,
            "chamber": chamber,
            "party": party
        }
    }


@router.get("/committee/{committee_id}")
def get_committee_metrics(
    committee_id: str,
    db: Session = Depends(get_db),
    congress: Optional[int] = Query(119, description="Filter by congress (default: 119)")
):
    """
    Get comprehensive metrics for a committee.
    
    Returns:
    - Committee information
    - Member count by party
    - Aggregated donations for committee members
    - Bills sponsored/cosponsored by committee members
    - Voting records of committee members
    - List of committee members with roles
    """
    # Verify committee exists
    committee = db.query(Committee).filter(Committee.committee_id == committee_id).first()
    if not committee:
        raise HTTPException(status_code=404, detail=f"Committee '{committee_id}' not found")
    
    # Get committee members for specified congress
    assignments = db.query(CommitteeAssignment).filter(
        CommitteeAssignment.committee_id == committee_id,
        CommitteeAssignment.congress == congress
    ).all()
    
    if not assignments:
        return {
            "committee": {
                "committee_id": committee.committee_id,
                "name": committee.name,
                "chamber": committee.chamber,
                "type": committee.type,
                "is_subcommittee": committee.parent_committee_id is not None,
                "parent_committee_id": committee.parent_committee_id
            },
            "congress": congress,
            "members": [],
            "message": f"No member assignments found for {congress}th Congress"
        }
    
    politician_ids = [a.politician_id for a in assignments]
    
    # Get politician details
    politicians_dict = {p.politician_id: p for p in db.query(Politician).filter(
        Politician.politician_id.in_(politician_ids)
    ).all()}
    
    # Member breakdown by party affiliation
    party_counts = {}
    role_counts = {}
    for assignment in assignments:
        party_counts[assignment.party] = party_counts.get(assignment.party, 0) + 1
        if assignment.role:
            role_counts[assignment.role] = role_counts.get(assignment.role, 0) + 1
    
    # DONATIONS METRICS
    donation_filter = [Donation.politician_id.in_(politician_ids)]
    total_donations = db.query(func.sum(Donation.amount)).filter(*donation_filter).scalar() or 0
    
    donation_by_type = db.query(
        Donor.donor_type,
        func.sum(Donation.amount).label('total')
    ).join(Donor).filter(*donation_filter).group_by(Donor.donor_type).all()
    
    donations_breakdown = {dt: float(total) for dt, total in donation_by_type if dt}
    
    # Top donors to committee members
    top_donors = db.query(
        Donor.name,
        Donor.donor_type,
        func.sum(Donation.amount).label('total_donated')
    ).join(Donor).filter(*donation_filter).group_by(
        Donor.donor_id, Donor.name, Donor.donor_type
    ).order_by(func.sum(Donation.amount).desc()).limit(10).all()
    
    # BILLS METRICS
    bill_filter = [Bill.sponsor_id.in_(politician_ids)]
    if congress:
        bill_filter.append(Bill.congress == congress)
    
    bills_sponsored = db.query(Bill).filter(*bill_filter).count()
    
    # Cosponsored bills
    cosponsor_query = db.query(BillCosponsor).filter(
        BillCosponsor.politician_id.in_(politician_ids)
    )
    if congress:
        cosponsor_query = cosponsor_query.join(Bill).filter(Bill.congress == congress)
    
    bills_cosponsored_original = cosponsor_query.filter(
        BillCosponsor.is_original_cosponsor == True
    ).count()
    bills_cosponsored_later = cosponsor_query.filter(
        BillCosponsor.is_original_cosponsor == False
    ).count()
    
    # VOTING METRICS
    vote_query = db.query(Vote).filter(Vote.politician_id.in_(politician_ids))
    if congress:
        vote_query = vote_query.join(Bill).filter(Bill.congress == congress)
    
    total_votes = vote_query.count()
    
    vote_breakdown = vote_query.with_entities(
        Vote.vote_position,
        func.count(Vote.vote_id).label('count')
    ).group_by(Vote.vote_position).all()
    
    votes_by_position = {vp: count for vp, count in vote_breakdown if vp}
    
    # Build member list with details
    members_list = []
    for assignment in sorted(assignments, key=lambda a: (a.party != 'majority', a.rank or 999)):
        politician = politicians_dict.get(assignment.politician_id)
        if politician:
            members_list.append({
                "politician_id": politician.politician_id,
                "name": f"{politician.first_name} {politician.last_name}",
                "party": politician.party,
                "state": politician.state,
                "role": assignment.role,
                "rank": assignment.rank,
                "party_affiliation": assignment.party  # 'majority' or 'minority'
            })
    
    return {
        "committee": {
            "committee_id": committee.committee_id,
            "name": committee.name,
            "chamber": committee.chamber,
            "type": committee.type,
            "url": committee.url,
            "is_subcommittee": committee.parent_committee_id is not None,
            "parent_committee_id": committee.parent_committee_id
        },
        "congress": congress,
        "membership": {
            "total_members": len(members_list),
            "by_party_affiliation": party_counts,
            "by_role": role_counts
        },
        "donations": {
            "total_amount": float(total_donations),
            "by_type": donations_breakdown,
            "top_donors": [
                {"name": name, "type": dtype, "total_donated": float(total)}
                for name, dtype, total in top_donors
            ]
        },
        "bills": {
            "sponsored": bills_sponsored,
            "cosponsored_original": bills_cosponsored_original,
            "cosponsored_later": bills_cosponsored_later,
            "total_cosponsored": bills_cosponsored_original + bills_cosponsored_later
        },
        "votes": {
            "total": total_votes,
            "by_position": votes_by_position
        },
        "members": members_list
    }
