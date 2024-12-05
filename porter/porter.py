"""
Porter: check credentials and redirect to the real axon IP.
"""

import time
import argparse
import uvicorn
from substrateinterface import Keypair, KeypairType
from fastapi import FastAPI, Request, status, HTTPException


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--real-host",
        type=str,
        required=True,
        help="real axon hostname/IP",
    )
    parser.add_argument(
        "--real-port",
        type=str,
        required=True,
        help="real axon port",
    )
    parser.add_argument(
        "--validator-whitelist",
        type=str,
        required=True,
    )
    parser.add_argument(
        "--hotkey",
        type=str,
        required=True,
    )
    args = parser.parse_args()

    # Create the app with our redirect endpoint.
    app = FastAPI(
        title="Porter",
        description="You shall not DDoS",
        version="0.0.1",
    )

    @app.get("/axon")
    async def get_real_axon(request: Request):
        miner_hotkey = request.headers.get("X-Chutes-Miner")
        validator_hotkey = request.headers.get("X-Chutes-Validator")
        nonce = request.headers.get("X-Chutes-Nonce")
        signature = request.headers.get("X-Chutes-Signature")
        if (
            any(not v for v in [miner_hotkey, validator_hotkey, nonce, signature])
            or miner_hotkey != args.hotkey
            or validator_hotkey not in args.validator_whitelist.split(",")
            or int(time.time()) - int(nonce) >= 30
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="go away {miner_hotkey=} {validator_hotkey=} {args.validator_whitelist=} {nonce=} {signature=}")
        signature_string = ":".join(
            [
                miner_hotkey,
                validator_hotkey,
                nonce,
                extra_key,
            ]
        )
        if not Keypair(ss58_address=validator_hotkey, crypto_type=KeypairType.SR25519).verify(
            signature_string, bytes.fromhex(signature)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"go away -- bad signature: {signature_string} -- {validator_hotkey=}")
        return {
            "host": args.real_host,
            "port": args.real_port,
        }

    uvicorn.run(app=app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
