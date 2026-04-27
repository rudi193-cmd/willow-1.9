import willow.fylgja.events.session_start as ss


ATOMS = [
    {"id": "a1", "type": "insight", "source": "insight", "importance": 9,
     "weight": 1.5, "stability": 2.0, "summary": "Don't skip MCP.", "invalid_at": None},
    {"id": "a2", "type": "reflection", "source": "reflection", "importance": 5,
     "weight": 1.0, "stability": 1.0, "summary": "Check git log first.", "invalid_at": None},
    {"id": "a3", "type": "chunk", "source": "chunk", "importance": 7,
     "weight": 1.2, "stability": 3.0, "summary": "Debug pattern.", "invalid_at": None},
    {"id": "a4", "type": "trace", "source": "observation", "importance": 2,
     "weight": 0.9, "stability": 0.5, "summary": "File edited.", "invalid_at": None},
    {"id": "a5", "type": "reflection", "source": "user_statement", "importance": 8,
     "weight": 1.0, "stability": 1.0, "summary": "Use Read not cat.", "invalid_at": None},
]


def test_query_b_preference_atoms():
    result = ss._query_preference_atoms(ATOMS)
    ids = [a["id"] for a in result]
    assert "a1" in ids   # insight
    assert "a5" in ids   # user_statement
    assert "a4" not in ids  # trace — excluded


def test_query_c_world_state_atoms():
    result = ss._query_world_state_atoms(ATOMS)
    ids = [a["id"] for a in result]
    assert "a1" in ids   # insight
    assert "a3" in ids   # chunk
    assert "a2" not in ids  # reflection — not world state
    assert "a4" not in ids  # trace — excluded


def test_position_order_worst_first_best_last():
    atoms = [
        {"importance": 9, "weight": 2.0, "stability": 2.0, "source": "insight"},
        {"importance": 2, "weight": 0.5, "stability": 0.5, "source": "inference"},
        {"importance": 5, "weight": 1.0, "stability": 1.0, "source": "observation"},
    ]
    ordered = ss._position_order(atoms)
    assert ordered[0]["importance"] == 2
    assert ordered[-1]["importance"] == 9


def test_query_b_respects_limit():
    many = [
        {"id": f"x{i}", "type": "insight", "source": "insight",
         "importance": i, "weight": 1.0, "stability": 1.0, "invalid_at": None}
        for i in range(20)
    ]
    result = ss._query_preference_atoms(many)
    assert len(result) <= 10


def test_query_b_excludes_invalid_atoms():
    atoms_with_invalid = ATOMS + [
        {"id": "a6", "type": "insight", "source": "insight", "importance": 10,
         "weight": 2.0, "stability": 2.0, "summary": "Superseded.", "invalid_at": "2026-01-01"},
    ]
    result = ss._query_preference_atoms(atoms_with_invalid)
    ids = [a["id"] for a in result]
    assert "a6" not in ids
