"""
Vincent CLI 4.0 — Estratégias de seleção plugáveis na cascata de modelos.
Nomes e comportamento inspirados em docs/routing/AUTO-COMBO.md do
diegosouzapw/OmniRoute (MIT): priority (cascata atual, sem mudança),
round_robin, cost_optimized e lkgp (sticky no último modelo que funcionou).
# ponytail: estado em memória do processo (dict simples) — CLI de 1 usuário,
# sem necessidade de persistir round-robin/lkgp entre reinícios.
"""

from typing import Dict, List, Optional

_round_robin_state: Dict[str, int] = {}
_last_known_good: Dict[str, str] = {}


def strategy_priority(models_ordered: List[str], **_kwargs) -> List[str]:
    """Padrão: usa a ordem de cascata já montada, sem reordenar."""
    return models_ordered


def strategy_round_robin(models_ordered: List[str], key: str = "default", **_kwargs) -> List[str]:
    """Roda o primeiro candidato a cada chamada; o resto continua como fallback."""
    if not models_ordered:
        return models_ordered
    idx = _round_robin_state.get(key, 0) % len(models_ordered)
    _round_robin_state[key] = idx + 1
    return models_ordered[idx:] + models_ordered[:idx]


def strategy_cost_optimized(
    models_ordered: List[str], model_catalog: Optional[List[Dict]] = None, **_kwargs
) -> List[str]:
    """Prioriza free > local > pro, preservando ordem relativa dentro de cada grupo."""
    if not model_catalog:
        return models_ordered
    rank = {m["id"]: (0 if m.get("is_free") else (1 if m.get("is_local") else 2)) for m in model_catalog}
    return sorted(models_ordered, key=lambda m: rank.get(m, 1))


def strategy_lkgp(models_ordered: List[str], key: str = "default", **_kwargs) -> List[str]:
    """Sticky no último modelo que funcionou — vai primeiro se ainda estiver na cascata."""
    good = _last_known_good.get(key)
    if good and good in models_ordered:
        return [good] + [m for m in models_ordered if m != good]
    return models_ordered


def record_success(model: str, key: str = "default") -> None:
    """Chamar após uma inferência bem-sucedida, pra lkgp saber quem manter sticky."""
    _last_known_good[key] = model


STRATEGIES = {
    "priority": strategy_priority,
    "round_robin": strategy_round_robin,
    "cost_optimized": strategy_cost_optimized,
    "lkgp": strategy_lkgp,
}


def apply_strategy(name: str, models_ordered: List[str], **kwargs) -> List[str]:
    fn = STRATEGIES.get(name, strategy_priority)
    return fn(models_ordered, **kwargs)
