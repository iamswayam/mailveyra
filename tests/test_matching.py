from app.services.matching import binary_match


def test_binary_match_exact_normalized_skills():
    result = binary_match(["Python", " Django ", "Kubernetes"], ["python", "django"])

    assert result == {
        "matched_skills": ["python", "django"],
        "gap_skills": ["kubernetes"],
    }


def test_binary_match_uses_only_fixed_synonym_map():
    result = binary_match(["Postgres", "Spring Boot"], ["PostgreSQL"])

    assert result == {
        "matched_skills": ["postgresql"],
        "gap_skills": ["spring boot"],
    }

