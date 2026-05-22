"""Client API pour l'écosystème Easy-care by Waterair.

Ce package contient :
- `exceptions` : hiérarchie d'exceptions métier
- `models`     : dataclasses des objets retournés par l'API
- `auth`       : gestion OAuth2 Azure B2C + refresh automatique
- `client`     : client HTTP asynchrone (aiohttp) — opérations métier

Usage typique :

    from .api.client import EasyCareClient
    from .api.auth import EasyCareAuth

    auth = EasyCareAuth(session, refresh_token="...")
    client = EasyCareClient(session, auth)

    user = await client.get_user()
    modules = await client.get_modules()
"""
