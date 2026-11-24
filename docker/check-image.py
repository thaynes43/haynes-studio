"""Check the runtime filesystem from stdin (a streamed docker export)."""

import fnmatch
from pathlib import Path, PurePosixPath
import re
import ssl
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/checks"))
from check_no_media import MEDIA_EXTENSIONS

CREDENTIAL_NAMES = (
    ".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx", "*.cookies",
    "id_rsa*", "id_ed25519*", "id_ecdsa*", "kubeconfig*", "auth.json",
    ".netrc", "cookies.txt", "credentials.json", "service-account.json",
    "client-secret.json", ".npmrc", ".pypirc", "shadow", "shadow-",
    "gshadow", "gshadow-",
)
CREDENTIAL_PATHS = {".aws/credentials", ".docker/config.json", ".kube/config"}
CERTIFI_BUNDLE = "opt/studio/lib/python3.12/site-packages/certifi/cacert.pem"
PUBLIC_CERTIFICATE = re.compile(
    rb"-----BEGIN CERTIFICATE-----\r?\n(?:[A-Za-z0-9+/=]+\r?\n)+"
    rb"-----END CERTIFICATE-----"
)


def is_public_ca_bundle(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bool:
    if not member.isfile() or member.size > 1024 * 1024:
        return False
    with archive.extractfile(member) as file:
        contents = re.sub(rb"(?m)^#[^\n]*", b"", file.read())
    certificates = PUBLIC_CERTIFICATE.findall(contents)
    if not certificates or PUBLIC_CERTIFICATE.sub(b"", contents).strip():
        return False
    trust = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        for certificate in certificates:
            trust.load_verify_locations(cadata=certificate.decode("ascii"))
    except ssl.SSLError:
        return False
    return True


def main() -> int:
    failed = False
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
        for member in archive:
            if not (member.isfile() or member.issym() or member.islnk()):
                continue
            path = PurePosixPath(member.name)
            name = path.name.lower()
            relative = path.as_posix().lstrip("/")
            if name.endswith(MEDIA_EXTENSIONS):
                print(f"{path}: prohibited media, archive or model filename", file=sys.stderr)
                failed = True
            elif (
                any(fnmatch.fnmatchcase(name, pattern) for pattern in CREDENTIAL_NAMES)
                or "/".join(path.parts[-2:]).lower() in CREDENTIAL_PATHS
            ):
                if relative == CERTIFI_BUNDLE and is_public_ca_bundle(archive, member):
                    continue
                print(f"{path}: prohibited credential filename", file=sys.stderr)
                failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
