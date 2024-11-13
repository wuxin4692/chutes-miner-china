"""
Authentication helpers.
"""

import time
from functools import lru_cache
from substrateinterface import Keypair, KeypairType
from fastapi import Request, status, HTTPException, Header
from api.constants import MINER_HEADER, VALIDATOR_HEADER, SIGNATURE_HEADER, NONCE_HEADER
from api.config import settings


@lru_cache(maxsize=32)
def get_keypair(ss58):
    """
    Helper to load keypairs efficiently.
    """
    return Keypair(ss58_address=ss58, crypto_type=KeypairType.SR25519)


def authorize(allow_miner=False, allow_validator=False, purpose: str = None):
    def _authorize(
        request: Request,
        validator: str | None = Header(None, alias=VALIDATOR_HEADER),
        miner: str | None = Header(None, alias=MINER_HEADER),
        nonce: str | None = Header(None, alias=NONCE_HEADER),
        signature: str | None = Header(None, alias=SIGNATURE_HEADER),
    ):
        """
        Verify the authenticity of a request.
        """
        allowed_signers = []
        if allow_miner:
            allowed_signers.append(settings.miner_ss58)
        if allow_validator:
            allowed_signers += [
                validator["hotkey"] for validator in settings.validators["supported"]
            ]
        if (
            any(not v for v in [miner, validator, nonce, signature])
            or miner != settings.miner_ss58
            or validator not in allowed_signers
            or int(time.time()) - int(nonce) >= 30
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="go away")
        signature_string = ":".join(
            [
                miner,
                validator,
                nonce,
                request.state.body_sha256 if request.state.body_sha256 else purpose,
            ]
        )
        if not get_keypair(validator).verify(signature_string, bytes.fromhex(signature)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="go away")

    return _authorize
