# writing/executive-summary checker (FR-AGT-04).
from skills._lib import guard


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    tokens, mat_ids = guard.gather_material(inputs)
    max_words = inputs.get("max_words")

    summary = output.get("summary") if isinstance(output.get("summary"), str) else ""
    answer_first = output.get("answer_first") if isinstance(output.get("answer_first"), str) else ""
    claims = output.get("claims") if isinstance(output.get("claims"), list) else []
    claim_text = " ".join(c.get("text", "") for c in claims if isinstance(c, dict) and isinstance(c.get("text"), str))
    refs_field = output.get("source_refs")
    refs = {r for r in refs_field if isinstance(r, str)} if isinstance(refs_field, list) else set()
    refs |= guard.str_ids(claims, "source_id")

    body = " ".join([summary, answer_first, claim_text])
    word_count = len(body.split())
    too_long = isinstance(max_words, int) and word_count > max_words
    findings = [guard.finding("word-limit-exceeded", f"{word_count} words")] if too_long else []

    invented = guard.number_tokens(body) - tokens
    findings += [guard.finding("number-not-in-material", f"not in material: {sorted(invented)}")] if invented else []

    unknown = refs - mat_ids
    if not refs:
        findings.append(guard.finding("source-ref-unknown", "no source refs given"))
    elif unknown:
        findings.append(guard.finding("source-ref-unknown", f"unknown ref(s): {sorted(unknown)}"))
    return findings
