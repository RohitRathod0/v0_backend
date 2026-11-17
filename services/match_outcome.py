"""
Overview: Match result ka poora logic sirf isi module mein rehta hai. Har match ka ek
`outcome` hota hai (regular, walkover, ...). Har outcome ka ek `OutcomeRule` hota hai jo
batata hai ki winner kaise decide hoga (scores se ya organizer declare karega), points
count honge ya nahi, 0-0 hone pe bhi "played" maana jaaye ya nahi, aur DUPR rating mein
jaaye ya nahi. Standings functions `standings_contribution()` call karte hain, aur dono
write endpoints (/update-score final + /matches/<id>/outcome) `finalize_match()` use
karte hain. Naya outcome (forfeit / bye) add karna = enum mein ek value + OUTCOME_RULES
mein ek entry. Kahin aur `if outcome == ...` likhne ki zarurat nahi.
"""
from dataclasses import dataclass
from enum import Enum

WINNER_FROM_SCORES = "scores"
WINNER_DECLARED = "declared"
TBD_TEAM_ID = "TBD"


class MatchOutcome(str, Enum):
    REGULAR = "regular"
    WALKOVER = "walkover"


@dataclass(frozen=True)
class OutcomeRule:
    key: MatchOutcome
    label: str
    winner_source: str
    counts_points: bool
    always_counts_as_played: bool
    rating_eligible: bool


OUTCOME_RULES = {
    MatchOutcome.REGULAR: OutcomeRule(MatchOutcome.REGULAR, "Regular", WINNER_FROM_SCORES, True, False, True),
    MatchOutcome.WALKOVER: OutcomeRule(MatchOutcome.WALKOVER, "Walkover", WINNER_DECLARED, False, True, False),
}


def get_rule(outcome):
    if outcome is None or outcome == "":
        return OUTCOME_RULES[MatchOutcome.REGULAR]
    try:
        key = MatchOutcome(outcome)
    except ValueError:
        allowed = ", ".join(o.value for o in MatchOutcome)
        raise ValueError(f"Unknown outcome '{outcome}'. Allowed: {allowed}")
    return OUTCOME_RULES[key]


def _is_set(team_id):
    return bool(team_id) and team_id != TBD_TEAM_ID


def _winner_from_scores(team1_id, team2_id, s1, s2):
    if s1 > s2:
        return team1_id
    if s2 > s1:
        return team2_id
    return None


def resolve_winner(rule, team1_id, team2_id, s1, s2, declared_winner_id):
    if rule.winner_source == WINNER_FROM_SCORES:
        return _winner_from_scores(team1_id, team2_id, s1, s2)
    if not (_is_set(team1_id) and _is_set(team2_id)):
        raise ValueError(f"Both teams must be set before declaring a {rule.label.lower()} (match has a TBD team)")
    if not declared_winner_id:
        raise ValueError(f"winner_team_id is required for {rule.label.lower()}")
    if declared_winner_id not in (team1_id, team2_id):
        raise ValueError(f"winner_team_id '{declared_winner_id}' is not one of the match teams "
                         f"({team1_id}, {team2_id})")
    return declared_winner_id


def standings_contribution(outcome, team1_id, team2_id, s1, s2, winner_team_id):
    rule = get_rule(outcome)
    if rule.winner_source == WINNER_FROM_SCORES:
        won1, won2 = int(s1 > s2), int(s2 > s1)
    else:
        won1 = int(winner_team_id is not None and winner_team_id == team1_id)
        won2 = int(winner_team_id is not None and winner_team_id == team2_id)
    p1, p2 = (s1, s2) if rule.counts_points else (0, 0)
    return {
        "counts_as_played_override": rule.always_counts_as_played,
        "team1": {"scored": p1, "conceded": p2, "won": won1},
        "team2": {"scored": p2, "conceded": p1, "won": won2},
    }


def serialize_outcome(match):
    rule = get_rule(getattr(match, "outcome", None))
    return {
        "outcome": rule.key.value,
        "outcome_label": rule.label,
        "outcome_reason": getattr(match, "outcome_reason", None),
    }


def list_outcomes():
    return [{"key": r.key.value, "label": r.label, "winner_source": r.winner_source}
            for r in OUTCOME_RULES.values()]


def _upsert_score(Score, db, match_id, team_id, tournament_id, value):
    record = Score.query.filter_by(match_id=match_id, team_id=team_id, tournament_id=tournament_id).first()
    if not record:
        db.session.add(Score(match_id=match_id, team_id=team_id, tournament_id=tournament_id, score=value))
    else:
        record.score = value


def advance_to_successor(successor_match_id, current_match_id, winning_team_id):
    from models import Match, Score, db

    successor_match = Match.query.get(successor_match_id)
    if not successor_match:
        return None

    if successor_match.predecessor_1 == current_match_id:
        successor_match.team1_id = winning_team_id
    elif successor_match.predecessor_2 == current_match_id:
        successor_match.team2_id = winning_team_id

    if successor_match.team1_id and successor_match.team2_id:
        for team_id in (successor_match.team1_id, successor_match.team2_id):
            exists = Score.query.filter_by(match_id=successor_match.id, team_id=team_id).first()
            if not exists:
                db.session.add(Score(match_id=successor_match.id, team_id=team_id, score=0,
                                     tournament_id=successor_match.tournament_id))
    return successor_match


def finalize_match(match, outcome, team1_score=None, team2_score=None, declared_winner_id=None, reason=None):
    from models import Score, db

    rule = get_rule(outcome)
    if rule.winner_source == WINNER_FROM_SCORES:
        if team1_score is None or team2_score is None:
            raise ValueError(f"team1_score and team2_score are required for {rule.label.lower()} outcome")
        s1, s2 = team1_score, team2_score
    else:
        s1, s2 = 0, 0
    winner = resolve_winner(rule, match.team1_id, match.team2_id, s1, s2, declared_winner_id)

    try:
        _upsert_score(Score, db, match.id, match.team1_id, match.tournament_id, s1)
        _upsert_score(Score, db, match.id, match.team2_id, match.tournament_id, s2)

        match.outcome = rule.key.value
        match.outcome_reason = (reason.strip() or None) if (reason and rule.winner_source == WINNER_DECLARED) else None
        match.winner_team_id = winner
        match.is_final = True
        match.status = 'completed'

        if match.successor:
            advance_to_successor(match.successor, match.id, winner)

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return match
