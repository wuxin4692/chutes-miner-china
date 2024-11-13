import hashlib
import random
import json
import time
import requests
import argparse
from typing import Dict, Any
from graval.validator import Validator
from substrateinterface import Keypair, KeypairType


def sign_request(payload: Dict[str, Any] | str | None = None, purpose: str = None):
    """
    Generate a signed request.
    """
    nonce = str(int(time.time()))
    headers = {
        "X-Chutes-Miner": "5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4",
        "X-Chutes-Validator": "5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4",
        "X-Chutes-Nonce": nonce,
    }
    signature_string = None
    payload_string = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        payload_string = json.dumps(payload)
        signature_string = ":".join(
            [
                "5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4",
                "5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4",
                str(nonce),
                hashlib.sha256(payload_string.encode()).hexdigest(),
            ]
        )
    else:
        signature_string = ":".join(
            [
                "5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4",
                "5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4",
                str(nonce),
                "graval",
            ]
        )
    print(f"Signing message: {signature_string}")
    keypair = Keypair.create_from_seed(
        seed_hex="971c2a6674d0861ade72297d11110ce21c93734210527c8f4c9190c00139ce20"
    )
    headers["X-Chutes-Signature"] = keypair.sign(signature_string.encode()).hex()
    return headers, payload_string


def test_get_devices():
    headers, _ = sign_request(payload=None, purpose="graval")
    result = requests.get("http://127.0.0.1:3333/devices", headers=headers)
    assert result.status_code == 200
    devices = result.json()
    assert devices["devices"]
    print(json.dumps(devices, indent=2))


def test_encryption_challenge():
    headers, _ = sign_request(payload=None, purpose="graval")
    result = requests.get("http://127.0.0.1:3333/devices", headers=headers)
    devices = result.json()["devices"]
    validator = Validator()
    validator.initialize()
    for idx in range(len(devices)):
        device_info = devices[idx]
        seed = random.randint(1, 1000000)
        ciphertext, iv, length = validator.encrypt(device_info, "testing", seed)
        print(f"IV LENGTH: {len(iv)}")
        print(f"IV BYTES : ", [hex(b) for b in iv])
        assert len(iv) == 16
        body = {
            "ciphertext": ciphertext.hex(),
            "iv": iv.hex(),
            "length": length,
            "seed": seed,
            "device_id": idx,
        }
        print(body)
        headers, request_body = sign_request(payload=body)
        result = requests.post(
            "http://127.0.0.1:3333/challenge/decrypt",
            data=request_body,
            headers=headers,
        )
        assert result.status_code == 200
        print(result.text)
        assert result.json()["plaintext"] == "testing"


def test_device_info_challenge():
    headers, _ = sign_request(payload=None, purpose="graval")
    result = requests.get("http://127.0.0.1:3333/devices", headers=headers)
    devices = result.json()["devices"]
    validator = Validator()
    validator.initialize()
    for _ in range(200):
        challenge = validator.generate_device_info_challenge(len(devices))
        headers, _ = sign_request(payload=None, purpose="graval")
        result = requests.get(
            "http://127.0.0.1:3333/challenge/info",
            params={"challenge": challenge},
            headers=headers,
        )
        assert validator.verify_device_info_challenge(challenge, result.text.strip('"'), devices)


# 5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4
# test_encryption_challenge()
test_device_info_challenge()
