#!/usr/bin/env python3
"""
Standalone probe: can this machine + this security key do what 2fas needs?

Run this before installing anything else:

    pip install fido2
    python scripts/probe_security_key.py

It answers the two questions that decide whether the feature works for you:

1. does the key implement `hmac-secret`, and does it work *without* a PIN?
2. are the Linux udev/hidraw permissions in place? (a common and obscure failure)

It creates one non-discoverable credential and immediately forgets it. Nothing is
written to your key's storage, no OTP or PIV slot is touched, and no file on your
machine is modified. Expect two touches.

`2fas --doctor` does everything here except the two touches, once 2fas is installed.
"""

import os
import sys

try:
    from fido2.ctap import CtapError
    from fido2.ctap2.base import Ctap2
    from fido2.ctap2.pin import ClientPin, PinProtocolV1, PinProtocolV2
    from fido2.hid import CtapHidDevice
except ImportError:
    sys.exit("Install the fido2 package first: pip install fido2")

RP = {"id": "2fas.local", "name": "2fas"}
USER = {"id": b"2fas-cli", "name": "2fas"}


def hidraw_report() -> None:
    if not sys.platform.startswith("linux"):
        return

    nodes = sorted(p for p in os.listdir("/dev") if p.startswith("hidraw"))
    if not nodes:
        print("  /dev/hidraw*: none present - is the key plugged in?")
        return

    unreadable = [n for n in nodes if not os.access(f"/dev/{n}", os.R_OK | os.W_OK)]
    print(f"  /dev/hidraw*: {len(nodes)} nodes, {len(unreadable)} not accessible by you")
    if unreadable:
        print("  -> install the libfido2 udev rules (70-u2f.rules) and re-plug the key")


def main() -> int:
    print("Looking for FIDO2 authenticators...")
    devices = list(CtapHidDevice.list_devices())
    if not devices:
        print("No FIDO2 device found.")
        hidraw_report()
        return 1

    device = devices[0]
    ctap = Ctap2(device)
    info = ctap.info
    version = info.firmware_version or 0

    print(f"  product:   {getattr(device, 'product_name', 'unknown')}")
    print(f"  firmware:  {(version >> 16) & 0xFF}.{(version >> 8) & 0xFF}.{version & 0xFF}")
    print(f"  extensions:{list(info.extensions or [])}")
    print(f"  PIN set:   {bool((info.options or {}).get('clientPin'))}")
    print(f"  alwaysUv:  {bool((info.options or {}).get('alwaysUv'))}")
    hidraw_report()

    if "hmac-secret" not in (info.extensions or []):
        print("\nFAIL: this authenticator does not support hmac-secret.")
        return 1

    if (info.options or {}).get("clientPin"):
        print("\nNote: a PIN is set, so CTAP2 will require it to create a credential.")
        print("Day-to-day unlocking will still be touch-only. Re-run without a PIN to")
        print("see the fully PIN-free flow, or enter it when 2fas --enroll asks.")
        print("Skipping the credential test, since it would need your PIN.")
        return 0

    print("\nCreating a throwaway credential - touch your key...")
    try:
        attestation = ctap.make_credential(
            client_data_hash=os.urandom(32),
            rp=RP,
            user=USER,
            key_params=[{"type": "public-key", "alg": -7}],
            extensions={"hmac-secret": True},
            options={"rk": False},
        )
    except CtapError as e:
        print(f"FAIL: makeCredential: {e}")
        return 1

    credential_data = attestation.auth_data.credential_data
    if credential_data is None or not (attestation.auth_data.extensions or {}).get("hmac-secret"):
        print("FAIL: the key did not enable hmac-secret for this credential.")
        return 1

    credential_id = bytes(credential_data.credential_id)
    print(f"  credential id: {len(credential_id)} bytes")

    protocols = list(info.pin_uv_protocols or [])
    protocol = PinProtocolV2() if 2 in protocols or not protocols else PinProtocolV1()
    response = ctap.client_pin(protocol.VERSION, ClientPin.CMD.GET_KEY_AGREEMENT)
    key_agreement, shared = protocol.encapsulate(response[ClientPin.RESULT.KEY_AGREEMENT])

    salt = os.urandom(32)
    salt_enc = protocol.encrypt(shared, salt)
    salt_auth = protocol.authenticate(shared, salt_enc)

    print("Reading the hmac-secret output - touch your key again...")
    try:
        assertion = ctap.get_assertion(
            rp_id=RP["id"],
            client_data_hash=os.urandom(32),
            allow_list=[{"type": "public-key", "id": credential_id}],
            extensions={"hmac-secret": {1: key_agreement, 2: salt_enc, 3: salt_auth, 4: protocol.VERSION}},
            options={"up": True, "uv": False},
        )
    except CtapError as e:
        print(f"FAIL: getAssertion: {e}")
        return 1

    output = (assertion.auth_data.extensions or {}).get("hmac-secret")
    if not output:
        print("FAIL: no hmac-secret in the assertion.")
        return 1

    secret = protocol.decrypt(shared, output)
    print(f"  hmac-secret output: {len(secret)} bytes")
    print("\nPASS: touch-only hmac-secret works on this machine.")
    print("The credential just created is not stored anywhere and is now forgotten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
