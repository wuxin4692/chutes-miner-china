"""
GraVal Bootstrap: spin up a simple FastAPI server for GPU verficiation.
"""

import time
import hashlib
import argparse
import uvicorn
import asyncio
import json
import base64
from pydantic import BaseModel
from graval.miner import Miner
from substrateinterface import Keypair, KeypairType
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import PlainTextResponse


class Cipher(BaseModel):
    ciphertext: str
    iv: str
    length: int
    device_id: int
    seed: int


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
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

    miner = Miner()
    # Dummy init.
    gpu_count = miner.initialize(0)
    miner._init_seed = None
    app = FastAPI(
        title="GraVal bootstrap",
        description="GPU info plz",
        version="0.0.1",
    )
    gpu_lock = asyncio.Lock()

    def verify_request(request: Request, whitelist: list[str], extra_key: str = "graval") -> None:
        """
        Verify the authenticity of a request.
        """
        miner_hotkey = request.headers.get("X-Chutes-Miner")
        validator_hotkey = request.headers.get("X-Chutes-Validator")
        nonce = request.headers.get("X-Chutes-Nonce")
        signature = request.headers.get("X-Chutes-Signature")
        if (
            any(not v for v in [miner_hotkey, validator_hotkey, nonce, signature])
            or miner_hotkey != args.hotkey
            or validator_hotkey not in whitelist
            or int(time.time()) - int(nonce) >= 30
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="go away")
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
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="go away")

    @app.get("/ping", response_class=PlainTextResponse)
    async def ping():
        return "pong"

    @app.get("/devices")
    async def get_devices(request: Request):
        """
        Get the list of devices, only used by internal components.
        """
        verify_request(request, [args.hotkey])  # only allow requests from myself
        return {
            "devices": [miner.get_device_info(idx) for idx in range(gpu_count)],
        }

    @app.post("/challenge/decrypt")
    async def decryption_challenge(request: Request):
        """
        Perform a decryption challenge.
        """
        request_body = await request.body()
        sha2 = hashlib.sha256(request_body).hexdigest()
        verify_request(request, args.validator_whitelist.split(","), extra_key=sha2)
        body = json.loads(request_body.decode())
        cipher = Cipher(**body)
        async with gpu_lock:
            if not miner._init_seed != cipher.seed:
                miner.initialize(cipher.seed)
                miner._init_seed = cipher.seed
            return {
                "plaintext": miner.decrypt(
                    base64.b64decode(cipher.ciphertext.encode()),
                    bytes.fromhex(cipher.iv),
                    cipher.length,
                    cipher.device_id,
                )
            }

    @app.get("/challenge/info", response_class=PlainTextResponse)
    async def info_challenge(request: Request, challenge: str):
        """
        Perform a device info challenge.
        """
        verify_request(request, args.validator_whitelist.split(","))
        return miner.process_device_info_challenge(challenge)

    uvicorn.run(app=app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
