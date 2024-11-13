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
        "--porter-host",
        type=str,
        default="0.0.0.0",
    )
    parser.add_argument(
        "--porter-port",
        type=int,
        default=2222,
    )
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
        nargs="+",
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
            or validator_hotkey not in args.validator_whitelist
            or miner_hotkey != args.hotkey
            or int(time.time()) - int(nonce) >= 30
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="go away"
            )
        signature_string = ":".join(
            [
                miner_hotkey,
                validator_hotkey,
                nonce,
                "porter",
            ]
        )
        if not Keypair(
            ss58_address=validator_hotkey, crypto_type=KeypairType.SR25519
        ).verify(signature_string, bytes.fromhex(signature)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="go away"
            )
        return {
            "host": args.real_host,
            "port": args.real_port,
        }

    uvicorn.run(app=app, host=args.porter_host, port=args.porter_port)


if __name__ == "__main__":
    main()
