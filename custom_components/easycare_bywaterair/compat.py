"""Détection de capacités Home Assistant pour la compatibilité multi-versions.

Le banc de test (pytest-homeassistant-custom-component) épingle HA 2025.1.4,
une version antérieure à l'introduction de `via_device_id` : `async_get_or_create`
n'y accepte pas ce paramètre et `async_get_device_by_identifier` n'existe pas.
L'intégration cible aussi HA récents (via_device retiré en 2027.8.0). On détecte
les capacités par introspection plutôt que par version en dur.
"""

from __future__ import annotations

import inspect

from homeassistant.helpers import device_registry as dr

# Le paramètre `via_device_id` d'`async_get_or_create` (et la clé DeviceInfo
# associée) n'existe pas sur les Home Assistant < 2025.2.
SUPPORTS_VIA_DEVICE_ID: bool = (
    "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
)

# `async_get_device_by_identifier` a remplacé l'`async_get_device` dépréciée
# sur les HA récents. Absente de HA 2025.1.4.
HAS_ASYNC_GET_DEVICE_BY_IDENTIFIER: bool = hasattr(
    dr.DeviceRegistry, "async_get_device_by_identifier"
)