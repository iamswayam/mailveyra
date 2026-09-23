SYNONYM_MAP = {
    "django rest framework": "drf",
    "postgres": "postgresql",
}


def normalize_skill(skill: str) -> str:
    normalized = " ".join(skill.lower().strip().split())
    return SYNONYM_MAP.get(normalized, normalized)


def binary_match(job_skills: list[str], candidate_skills: list[str]) -> dict[str, list[str]]:
    candidate_set = {normalize_skill(skill) for skill in candidate_skills}
    matched: list[str] = []
    gaps: list[str] = []
    seen: set[str] = set()

    for skill in job_skills:
        normalized = normalize_skill(skill)
        if normalized in seen:
            continue
        seen.add(normalized)
        if normalized in candidate_set:
            matched.append(normalized)
        else:
            gaps.append(normalized)

    return {"matched_skills": matched, "gap_skills": gaps}

