"""
Overview: Non-regular outcomes (abhi sirf walkover) declare karne ke endpoints.
`POST /matches/<id>/outcome` organizer ka chuna hua winner leke services.match_outcome
.finalize_match() chalata hai (scores 0-0, winner, outcome, status, knockout successor
sab ek transaction mein), phir `/scores` namespace pe `score_update` socket event bhejta
hai. `GET /match-outcomes` registry ki list deta hai taaki frontend "Declare ..." buttons
khud bana sake. Scores se decide hone wale outcomes (regular) ke liye /update-score hi
use karna hai.
"""
from flask import request, jsonify

from models import Match
from services.match_outcome import (
    WINNER_FROM_SCORES, finalize_match, get_rule, list_outcomes, serialize_outcome,
)
from socket_instance import socketio
from . import match_bp

MAX_REASON_LENGTH = 255


@match_bp.route('/matches/<int:match_id>/outcome', methods=['POST'])
def declare_match_outcome(match_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON body is required'}), 400

    outcome = data.get('outcome')
    tournament_id = data.get('tournament_id')
    winner_team_id = data.get('winner_team_id')
    reason = data.get('reason')

    if not outcome or tournament_id in (None, ''):
        return jsonify({'error': 'outcome and tournament_id are required'}), 400
    if not isinstance(outcome, str):
        return jsonify({'error': 'outcome must be a string'}), 400
    if reason is not None and not isinstance(reason, str):
        return jsonify({'error': 'reason must be a string'}), 400
    if reason and len(reason) > MAX_REASON_LENGTH:
        return jsonify({'error': f'reason must be at most {MAX_REASON_LENGTH} characters'}), 400
    if winner_team_id is not None and not isinstance(winner_team_id, str):
        return jsonify({'error': 'winner_team_id must be a string'}), 400

    try:
        rule = get_rule(outcome)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if rule.winner_source == WINNER_FROM_SCORES:
        return jsonify({'error': f"Outcome '{rule.key.value}' is decided by scores; use /update-score"}), 400

    match = Match.query.filter_by(id=match_id).first()
    if not match or str(match.tournament_id) != str(tournament_id):
        return jsonify({'error': 'Match not found'}), 404

    try:
        finalize_match(match, rule.key.value, declared_winner_id=winner_team_id, reason=reason)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        print(f"Error in declare_match_outcome: {str(e)}")
        return jsonify({'error': str(e)}), 500

    response = {
        'message': f'Match finalized as {rule.label}',
        'match_id': match.id,
        'team1_id': match.team1_id,
        'team1_score': 0,
        'team2_id': match.team2_id,
        'team2_score': 0,
        'is_final': match.is_final,
        'tournament_id': tournament_id,
        'winner_team_id': match.winner_team_id,
        'status': match.status,
        **serialize_outcome(match)
    }
    socketio.emit('score_update', response, namespace='/scores')
    return jsonify(response), 200


@match_bp.route('/match-outcomes', methods=['GET'])
def get_match_outcomes():
    return jsonify(list_outcomes()), 200
