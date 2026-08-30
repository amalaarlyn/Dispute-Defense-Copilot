"""
LLM Explanation Layer — Task 5 of Dispute Defense Copilot.

Deliberately narrow role, per the architecture review: the LLM NEVER
computes a probability, a decision, or a claim of its own. It only narrates
numbers already produced by the Evidence Verifier, Contest Outcome
Predictor, What-If Engine, and Decision Policy. This keeps "could the LLM
hallucinate a probability" a non-issue by construction — it never has the
option to.

This module builds the PROMPT deterministically from computed values. Wire
it to a real API call (Anthropic, etc.) in `call_llm()` — left as a stub
since this environment has no network access. A template-only fallback is
provided so the demo runs end-to-end without any API key.
"""

import os


def build_explanation_prompt(dispute_summary: dict) -> str:
    """
    dispute_summary must contain only values already computed elsewhere:
    dispute_id, reason_code, amount, hours_remaining, evidence_status
    (list of {type, valid, confidence}), win_prob, decision, decision_reason,
    whatif_ranked (list of {missing_evidence_type, expected_improvement}).
    """
    evidence_lines = "\n".join(
        f"  - {e['type']}: {'VALID' if e['valid'] else 'INVALID/UNCERTAIN'} "
        f"(confidence {e['confidence']:.0%})"
        for e in dispute_summary["evidence_status"]
    )
    whatif_lines = "\n".join(
        f"  - Obtaining {w['missing_evidence_type']} could improve win probability by "
        f"{w['expected_improvement']:+.0%}"
        for w in dispute_summary.get("whatif_ranked", [])[:3]
    )

    prompt = f"""You are explaining a chargeback dispute analysis to a merchant. \
Use ONLY the facts given below. Do not estimate, guess, or add any number, \
probability, or claim that is not explicitly provided. Do not speculate about \
whether the customer is being honest. Write 3-4 plain sentences a non-technical \
merchant would understand.

Dispute: {dispute_summary['dispute_id']}
Reason: {dispute_summary['reason_code']}
Amount: Rs.{dispute_summary['amount']:,.0f}
Hours remaining to respond: {dispute_summary['hours_remaining']:.0f}

Evidence status:
{evidence_lines}

Model-predicted contest win probability: {dispute_summary['win_prob']:.0%}

What-if analysis (if evidence were added):
{whatif_lines if whatif_lines else "  (no missing evidence, or no time remaining to obtain more)"}

System recommendation: {dispute_summary['decision']}
Reason for recommendation: {dispute_summary['decision_reason']}

Write the explanation now."""
    return prompt


def call_llm(prompt: str, use_api: bool = False) -> str:
    """
    Set use_api=True and fill in a real client call once you have network
    access / an API key. Falls back to a deterministic template so the demo
    works standalone.
    """
    if use_api:
        raise NotImplementedError(
            "Wire this to your LLM provider of choice, e.g.:\n"
            "  import anthropic\n"
            "  client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])\n"
            "  resp = client.messages.create(model=..., max_tokens=300,\n"
            "      messages=[{'role': 'user', 'content': prompt}])\n"
            "  return resp.content[0].text"
        )
    return _template_fallback(prompt)


def _template_fallback(prompt: str) -> str:
    """A deterministic, non-LLM narration used when no API is wired up —
    useful for offline demoing and for showing the fallback is honest about
    being a template, not a generated explanation."""
    return (
        "[TEMPLATE FALLBACK — replace with a real LLM call for the actual demo]\n"
        "This dispute's current evidence has been checked against the transaction "
        "record and scored by the contest outcome model; see the numbers above for "
        "the win probability, evidence validity, and the system's recommendation. "
        "Obtaining the evidence listed in the what-if analysis, if any, is the most "
        "effective way to improve the case before the deadline."
    )
