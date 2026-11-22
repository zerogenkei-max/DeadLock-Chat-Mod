"""Release identity shared by the helper, resource builder and packager."""
VERSION = "0.2.4"
PUBLIC_NAME = "Deadlock Chat Mod"


def artifact_name(kind: str) -> str:
    """File name of a release archive. kind is "Mod", "Source" or "Windows"."""
    if kind not in ("Mod", "Source", "Windows"):
        raise ValueError("Unknown archive kind: " + kind)
    return f"Switchboard-{VERSION}-{kind}.zip"
