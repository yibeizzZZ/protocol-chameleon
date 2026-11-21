"""Check the research RTL and program against the archive and published GDS identity."""
from hashlib import sha256
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "release/protocol-chameleon-6fd555b.zip"
with zipfile.ZipFile(ARCHIVE) as z:
    revision = json.loads(z.read("tt_submission/commit_id.json"))["commit"]
    assert revision == "6fd555b7e008227d7bcdaa2b921525284ff5e062"
    gds = sha256(z.read("tt_submission/tt_um_forg_protocol_chameleon.gds")).hexdigest()
    assert gds == "3978cdc0c98c1cc9a42be2a66fe5b0d8231e41944d0affa9c13743ce3c541af3"
    source_files = sorted((ROOT / "src").glob("*.v"))
    assert len(source_files) == 9
    for file in source_files + [ROOT / p for p in ("src/config.json", "info.yaml", "examples/adaptive_poll.p1", "p1.py")]:
        key = "source/" + file.relative_to(ROOT).as_posix()
        assert file.read_bytes().replace(b"\r\n", b"\n") == z.read(key), key
print(f"Verified {revision}, nine RTL sources, manifest, configuration, poll program, assembler and GDS {gds}")
