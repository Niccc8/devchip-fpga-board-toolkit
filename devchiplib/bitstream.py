"""Gowin .fs bitstream checks and packaging."""
import gzip
import io

GW2A_18_IDCODE = 0x0000081B          # GW2A-18 / GW2A-18C (Tang Primer 20K)
MAX_FS_BYTES = 16 * 1024 * 1024      # a GW2A-18 .fs is ~4.6 MB of ASCII


class BitstreamError(Exception):
    pass


def read_fs(path):
    """Return the raw .fs text; accepts .fs or .fs.gz."""
    with open(path, "rb") as f:
        data = f.read(MAX_FS_BYTES + 1)
    if data[:2] == b"\x1f\x8b":
        try:   # bounded read: a hostile .gz cannot expand without limit
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_FS_BYTES + 1)
        except (OSError, EOFError) as e:
            raise BitstreamError(f"{path}: corrupt gzip ({e})")
    if len(data) > MAX_FS_BYTES:
        raise BitstreamError(f"{path}: larger than {MAX_FS_BYTES} bytes - not a GW2A-18 .fs")
    return data


def check_fs(data):
    """Validate a Gowin ASCII bitstream and return its IDCODE.
    Raises BitstreamError if it is not a bitstream for this FPGA."""
    lines = [ln.strip() for ln in data.decode("ascii", "replace").splitlines()]
    bits = [ln for ln in lines if ln and not ln.startswith("//")]
    if len(bits) < 100 or any(set(ln) - {"0", "1"} for ln in bits):
        raise BitstreamError("not a Gowin .fs bitstream (expected lines of 0/1)")
    idcode = None
    for ln in bits[:40]:
        # command 0x06 = "check IDCODE"; the last 32 bits hold the expected ID
        if len(ln) == 64 and ln.startswith("00000110"):
            idcode = int(ln[32:], 2)
            break
    if idcode is None:
        raise BitstreamError("no IDCODE record found in bitstream header")
    if idcode != GW2A_18_IDCODE:
        raise BitstreamError(f"bitstream is for IDCODE 0x{idcode:08X}, this board is "
                             f"GW2A-18 (0x{GW2A_18_IDCODE:08X}) - refusing to load it")
    return idcode


def to_gzip(data):
    """gzip the .fs exactly like the ChipInventor server does (member name pack.fs)."""
    bio = io.BytesIO()
    with gzip.GzipFile(filename="pack.fs", mode="wb", fileobj=bio, mtime=0) as g:
        g.write(data)
    return bio.getvalue()
