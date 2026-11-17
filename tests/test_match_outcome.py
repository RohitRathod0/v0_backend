"""
Overview: services/match_outcome.py ke pure functions ke unit tests - bina DB aur bina
Flask app ke chalte hain. Regular outcome ka behaviour legacy `team1_score > team2_score`
logic jaisa hi hona chahiye, aur walkover ka winner declared team se aana chahiye.
Run: pytest tests/ -q
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.match_outcome import (  # noqa: E402
    OUTCOME_RULES, MatchOutcome, OutcomeRule, get_rule, list_outcomes, resolve_winner,
    serialize_outcome, standings_contribution,
)

REGULAR = OUTCOME_RULES[MatchOutcome.REGULAR]
WALKOVER = OUTCOME_RULES[MatchOutcome.WALKOVER]


class TestGetRule:
    def test_known_outcomes(self):
        assert get_rule("regular") is REGULAR
        assert get_rule("walkover") is WALKOVER
        assert get_rule(MatchOutcome.WALKOVER) is WALKOVER

    @pytest.mark.parametrize("legacy", [None, ""])
    def test_legacy_empty_is_regular(self, legacy):
        assert get_rule(legacy) is REGULAR

    @pytest.mark.parametrize("bad", ["forfeit", "WALKOVER", "bye", "x"])
    def test_unknown_raises(self, bad):
        with pytest.raises(ValueError, match="Unknown outcome"):
            get_rule(bad)

    def test_rule_flags(self):
        assert (REGULAR.winner_source, REGULAR.counts_points, REGULAR.always_counts_as_played,
                REGULAR.rating_eligible) == ("scores", True, False, True)
        assert (WALKOVER.winner_source, WALKOVER.counts_points, WALKOVER.always_counts_as_played,
                WALKOVER.rating_eligible) == ("declared", False, True, False)

    def test_rules_are_frozen(self):
        with pytest.raises(Exception):
            REGULAR.counts_points = False
        assert isinstance(REGULAR, OutcomeRule)


class TestResolveWinner:
    def test_scores_team1_wins(self):
        assert resolve_winner(REGULAR, "A", "B", 11, 5, None) == "A"

    def test_scores_team2_wins(self):
        assert resolve_winner(REGULAR, "A", "B", 7, 11, None) == "B"

    def test_scores_tie_is_none(self):
        assert resolve_winner(REGULAR, "A", "B", 11, 11, None) is None
        assert resolve_winner(REGULAR, "A", "B", 0, 0, None) is None

    def test_scores_ignores_declared_winner(self):
        assert resolve_winner(REGULAR, "A", "B", 3, 11, "A") == "B"

    @pytest.mark.parametrize("winner", ["A", "B"])
    def test_declared_valid(self, winner):
        assert resolve_winner(WALKOVER, "A", "B", 0, 0, winner) == winner

    def test_declared_winner_not_in_match(self):
        with pytest.raises(ValueError, match="not one of the match teams"):
            resolve_winner(WALKOVER, "A", "B", 0, 0, "C")

    @pytest.mark.parametrize("missing", [None, ""])
    def test_declared_missing_winner(self, missing):
        with pytest.raises(ValueError, match="winner_team_id is required"):
            resolve_winner(WALKOVER, "A", "B", 0, 0, missing)

    @pytest.mark.parametrize("t1,t2", [("A", None), (None, "B"), ("A", "TBD"), ("TBD", "B")])
    def test_declared_tbd_team(self, t1, t2):
        with pytest.raises(ValueError, match="TBD"):
            resolve_winner(WALKOVER, t1, t2, 0, 0, "A")


class TestStandingsContribution:
    def test_regular_win(self):
        c = standings_contribution("regular", "A", "B", 11, 5, "A")
        assert c == {"counts_as_played_override": False,
                     "team1": {"scored": 11, "conceded": 5, "won": 1},
                     "team2": {"scored": 5, "conceded": 11, "won": 0}}

    def test_regular_uses_scores_not_stored_winner(self):
        c = standings_contribution("regular", "A", "B", 4, 11, None)
        assert (c["team1"]["won"], c["team2"]["won"]) == (0, 1)

    def test_regular_tie(self):
        c = standings_contribution("regular", "A", "B", 11, 11, None)
        assert (c["team1"]["won"], c["team2"]["won"]) == (0, 0)
        assert c["team1"]["scored"] == 11 and c["team2"]["conceded"] == 11

    def test_regular_zero_zero_not_override(self):
        c = standings_contribution("regular", "A", "B", 0, 0, None)
        assert c["counts_as_played_override"] is False
        assert (c["team1"]["won"], c["team2"]["won"]) == (0, 0)

    def test_legacy_none_outcome_is_regular(self):
        assert standings_contribution(None, "A", "B", 11, 5, None) == \
            standings_contribution("regular", "A", "B", 11, 5, None)

    @pytest.mark.parametrize("winner,expected", [("A", (1, 0)), ("B", (0, 1))])
    def test_walkover(self, winner, expected):
        c = standings_contribution("walkover", "A", "B", 0, 0, winner)
        assert c["counts_as_played_override"] is True
        assert (c["team1"]["won"], c["team2"]["won"]) == expected
        assert c["team1"] == {"scored": 0, "conceded": 0, "won": expected[0]}
        assert c["team2"] == {"scored": 0, "conceded": 0, "won": expected[1]}

    def test_walkover_points_never_count(self):
        c = standings_contribution("walkover", "A", "B", 11, 3, "B")
        assert c["team1"]["scored"] == 0 and c["team2"]["scored"] == 0
        assert c["team2"]["won"] == 1

    def test_unknown_outcome_raises(self):
        with pytest.raises(ValueError):
            standings_contribution("forfeit", "A", "B", 0, 0, "A")


class TestSerializeAndList:
    def test_serialize_regular_legacy_row(self):
        m = SimpleNamespace(outcome=None, outcome_reason=None)
        assert serialize_outcome(m) == {"outcome": "regular", "outcome_label": "Regular", "outcome_reason": None}

    def test_serialize_walkover(self):
        m = SimpleNamespace(outcome="walkover", outcome_reason="No show")
        assert serialize_outcome(m) == {"outcome": "walkover", "outcome_label": "Walkover",
                                        "outcome_reason": "No show"}

    def test_list_outcomes(self):
        assert list_outcomes() == [
            {"key": "regular", "label": "Regular", "winner_source": "scores"},
            {"key": "walkover", "label": "Walkover", "winner_source": "declared"},
        ]
