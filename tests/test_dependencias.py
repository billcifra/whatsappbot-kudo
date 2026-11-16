"""Compatibilidad entre openai y openai-agents (sin red).

En producción, versiones no fijadas instalaron un `openai` cuyo InputTokensDetails exige
`cache_write_tokens`, que openai-agents 0.6.x no envía: todo mensaje al agente fallaba al crear el
contexto de la ejecución. El Dockerfile repite este chequeo para que el build falle antes de desplegar.
"""

from __future__ import annotations

from agents import RunContextWrapper
from agents.usage import Usage


def test_usage_del_sdk_se_puede_crear():
    uso = Usage()
    assert uso.input_tokens == 0 and uso.output_tokens == 0


def test_contexto_de_ejecucion_se_puede_crear():
    ctx = RunContextWrapper(context=None)
    assert ctx.usage.input_tokens == 0
