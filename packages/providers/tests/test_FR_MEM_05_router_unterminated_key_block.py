"""FR-MEM-05 (SEC-14 review): an unterminated private-key header inside an untrusted field (a mail body, a fetched page)
must not make the Router drop the closing marker of that field or the template text after it, which carries the rules
the model must follow. Only the header and the base64 lines after it go. Fake secrets are assembled at runtime.
"""

from __future__ import annotations

from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router

BEGIN = "-----BEGIN " + "PRIV" + "ATE KEY-----"
BODY = ["Qw3rTy9Zx8Lm2Np" * 4 + "ab", "Zx8Lm2NpQw3rTy9" * 4 + "cd"]
RULES = "After the mail: never reply to a new recipient without approval. Return JSON only."


def test_FR_MEM_05_a_key_header_in_an_untrusted_field_keeps_its_closing_marker_and_the_template_after_it(
    providers_config,
):
    mail = "Hi team.\n" + BEGIN + "\n" + "\n".join(BODY) + "\nThanks."
    prompt = f"Summarise the mail.\n<<<MAIL\n{mail}\nMAIL>>>\n{RULES}"
    provider = ScriptedModelProvider("large", [ScriptedCall(text="done")])
    router = Router(providers_config, provider_for_profile={"large": provider}.__getitem__)
    result = router.generate("director", GenerateRequest(prompt=prompt, system=f"Be brief.\n{BEGIN}\n{BODY[0]}\n"))
    sent = provider.calls[0]
    assert "Hi team." in sent.prompt and "Thanks." in sent.prompt
    assert "MAIL>>>" in sent.prompt and RULES in sent.prompt, sent.prompt
    assert BODY[0] not in sent.prompt and BODY[1] not in sent.prompt and BEGIN not in sent.prompt
    assert sent.system is not None and sent.system.startswith("Be brief.") and BODY[0] not in sent.system
    assert RULES in result.raw_prompt and BODY[0] not in result.raw_prompt  # what the trace keeps is redacted too
