"""NSFN file format: GLB-style container for NES audio notation data.

Binary layout:
  [4B magic][4B version][4B json_len][json_bytes][4B bin_len][bin_bytes]
"""

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ────────────────────────────────────────────────────────────────

MAGIC = b"NSFN"
VERSION = 1
HEADER_SIZE = 12  # magic(4) + version(4) + json_length(4)

STRUCT_FORMATS: Dict[str, str] = {
    "square":      "<HBB",
    "triangle":    "<HB",
    "noise":       "<BBB",
    "dpcm":        "<HiBBBB",
    "vrc6_square": "<HBB",
    "vrc6_saw":    "<HB",
    "vrc7_fm":     "<HBBBBBb",
    "fds":         "<HBBHBB",
    "mmc5_square": "<HBB",
    "mmc5_dpcm":   "<B",
    "n163_wave":   "<iBBBB",
    "s5b_square":  "<HBBBBHBB",
}

FRAME_SIZES: Dict[str, int] = {
    name: struct.calcsize(fmt) for name, fmt in STRUCT_FORMATS.items()
}

# Expansion chip bit masks → names
_EXPANSION_CHIPS = [
    (1 << 0, "VRC6"),
    (1 << 1, "VRC7"),
    (1 << 2, "FDS"),
    (1 << 3, "MMC5"),
    (1 << 4, "N163"),
    (1 << 5, "S5B"),
]

# ── Errors ───────────────────────────────────────────────────────────────────


class NotationError(Exception):
    pass


class InvalidMagicError(NotationError):
    pass


class UnsupportedVersionError(NotationError):
    pass


class TruncatedFileError(NotationError):
    pass


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class NoteEvent:
    frame: int
    event: str
    note: int
    octave: int
    pitch: int
    volume: int
    duty_cycle: int = 0
    instrument: Optional[int] = None


@dataclass
class RawDataRef:
    byte_offset: int
    byte_length: int
    frame_size: int
    struct_format: str


@dataclass
class ChannelData:
    channel_id: int
    channel_type: str
    channel_name: str
    notes: List[NoteEvent] = field(default_factory=list)
    raw_data_ref: Optional[RawDataRef] = None
    raw_frames: Optional[List[tuple]] = None


@dataclass
class SongData:
    index: int
    name: str
    num_frames: int
    pattern_length: int = 256
    channels: List[ChannelData] = field(default_factory=list)


@dataclass
class Metadata:
    title: str = ""
    artist: str = ""
    copyright: str = ""
    region: str = "ntsc"
    frame_rate: int = 60
    expansion: int = 0
    expansion_chips: Optional[List[str]] = None


@dataclass
class NotationFile:
    metadata: Metadata = field(default_factory=Metadata)
    songs: List[SongData] = field(default_factory=list)


# ── Pack / Unpack ────────────────────────────────────────────────────────────


def pack_frames(struct_format: str, frames: List[tuple]) -> bytes:
    fmt = STRUCT_FORMATS[struct_format]
    parts = []
    for f in frames:
        parts.append(struct.pack(fmt, *f))
    return b"".join(parts)


def unpack_frames(struct_format: str, data: bytes) -> List[tuple]:
    fmt = STRUCT_FORMATS[struct_format]
    size = struct.calcsize(fmt)
    result = []
    for offset in range(0, len(data), size):
        result.append(struct.unpack(fmt, data[offset:offset + size]))
    return result


# ── Expansion chips helper ───────────────────────────────────────────────────


def expansion_chip_list(mask: int) -> List[str]:
    return [name for bit, name in _EXPANSION_CHIPS if mask & bit]


# ── Internal: JSON ↔ data ────────────────────────────────────────────────────


def _note_to_dict(n: NoteEvent) -> dict:
    return {
        "frame": n.frame,
        "event": n.event,
        "note": n.note,
        "octave": n.octave,
        "pitch": n.pitch,
        "volume": n.volume,
        "duty_cycle": n.duty_cycle,
        "instrument": n.instrument,
    }


def _note_from_dict(d: dict) -> NoteEvent:
    return NoteEvent(
        frame=d["frame"],
        event=d["event"],
        note=d["note"],
        octave=d["octave"],
        pitch=d["pitch"],
        volume=d["volume"],
        duty_cycle=d.get("duty_cycle", 0),
        instrument=d.get("instrument"),
    )


def _channel_to_dict(ch: ChannelData, binary_layout: Dict[int, dict]) -> dict:
    ref = None
    key = id(ch)
    if key in binary_layout:
        bl = binary_layout[key]
        ref = {
            "byte_offset": bl["byte_offset"],
            "byte_length": bl["byte_length"],
            "frame_size": bl["frame_size"],
            "struct_format": bl["struct_format"],
        }
    return {
        "channel_id": ch.channel_id,
        "channel_type": ch.channel_type,
        "channel_name": ch.channel_name,
        "notes": [_note_to_dict(n) for n in ch.notes],
        "raw_data_ref": ref,
    }


def _channel_from_dict(d: dict) -> ChannelData:
    ref = None
    if d.get("raw_data_ref") is not None:
        r = d["raw_data_ref"]
        ref = RawDataRef(
            byte_offset=r["byte_offset"],
            byte_length=r["byte_length"],
            frame_size=r["frame_size"],
            struct_format=r["struct_format"],
        )
    return ChannelData(
        channel_id=d["channel_id"],
        channel_type=d["channel_type"],
        channel_name=d["channel_name"],
        notes=[_note_from_dict(n) for n in d.get("notes", [])],
        raw_data_ref=ref,
    )


def compute_binary_layout(data: NotationFile) -> Tuple[Dict[int, dict], bytes]:
    parts: List[bytes] = []
    layout: Dict[int, dict] = {}
    offset = 0
    for song in data.songs:
        for ch in song.channels:
            if ch.raw_frames and ch.channel_type in STRUCT_FORMATS:
                sf = ch.channel_type
                blob = pack_frames(sf, ch.raw_frames)
                layout[id(ch)] = {
                    "byte_offset": offset,
                    "byte_length": len(blob),
                    "frame_size": FRAME_SIZES[sf],
                    "struct_format": sf,
                }
                parts.append(blob)
                offset += len(blob)
    return layout, b"".join(parts)


def to_json_dict(data: NotationFile, binary_layout: Dict[int, dict]) -> dict:
    chips = data.metadata.expansion_chips
    if chips is None:
        chips = expansion_chip_list(data.metadata.expansion)
    return {
        "format": "nsfn",
        "version": VERSION,
        "metadata": {
            "title": data.metadata.title,
            "artist": data.metadata.artist,
            "copyright": data.metadata.copyright,
            "region": data.metadata.region,
            "frame_rate": data.metadata.frame_rate,
            "expansion": data.metadata.expansion,
            "expansion_chips": chips,
        },
        "songs": [
            {
                "index": song.index,
                "name": song.name,
                "num_frames": song.num_frames,
                "pattern_length": song.pattern_length,
                "channels": [
                    _channel_to_dict(ch, binary_layout) for ch in song.channels
                ],
            }
            for song in data.songs
        ],
    }


def from_json_dict(d: dict, binary_data: bytes = b"") -> NotationFile:
    md = d.get("metadata", {})
    metadata = Metadata(
        title=md.get("title", ""),
        artist=md.get("artist", ""),
        copyright=md.get("copyright", ""),
        region=md.get("region", "ntsc"),
        frame_rate=md.get("frame_rate", 60),
        expansion=md.get("expansion", 0),
        expansion_chips=md.get("expansion_chips"),
    )
    songs = []
    for sd in d.get("songs", []):
        channels = []
        for cd in sd.get("channels", []):
            ch = _channel_from_dict(cd)
            # Recover raw_frames from binary data
            if ch.raw_data_ref is not None and binary_data:
                ref = ch.raw_data_ref
                start = ref.byte_offset
                end = start + ref.byte_length
                ch.raw_frames = unpack_frames(ref.struct_format, binary_data[start:end])
            channels.append(ch)
        songs.append(SongData(
            index=sd["index"],
            name=sd["name"],
            num_frames=sd["num_frames"],
            pattern_length=sd.get("pattern_length", 256),
            channels=channels,
        ))
    return NotationFile(metadata=metadata, songs=songs)


# ── Write / Read ─────────────────────────────────────────────────────────────


def write(path: str, data: NotationFile) -> None:
    binary_layout, binary_blob = compute_binary_layout(data)
    json_dict = to_json_dict(data, binary_layout)
    json_bytes = json.dumps(json_dict, separators=(",", ":")).encode("utf-8")

    with open(path, "wb") as f:
        # Header
        f.write(MAGIC)
        f.write(struct.pack("<I", VERSION))
        # JSON chunk
        f.write(struct.pack("<I", len(json_bytes)))
        f.write(json_bytes)
        # Binary chunk
        f.write(struct.pack("<I", len(binary_blob)))
        f.write(binary_blob)


def read(path: str) -> NotationFile:
    with open(path, "rb") as f:
        raw = f.read()

    # Validate header
    if len(raw) < HEADER_SIZE:
        raise TruncatedFileError(
            f"File too short for header: {len(raw)} < {HEADER_SIZE}"
        )

    magic = raw[0:4]
    if magic != MAGIC:
        raise InvalidMagicError(f"Expected {MAGIC!r}, got {magic!r}")

    version = struct.unpack("<I", raw[4:8])[0]
    if version != VERSION:
        raise UnsupportedVersionError(
            f"Expected version {VERSION}, got {version}"
        )

    json_len = struct.unpack("<I", raw[8:12])[0]
    json_end = 12 + json_len
    if json_end > len(raw):
        raise TruncatedFileError(
            f"JSON chunk overruns file: need {json_end}, have {len(raw)}"
        )

    json_bytes = raw[12:json_end]
    json_dict = json.loads(json_bytes.decode("utf-8"))

    # Binary chunk header
    bin_header_end = json_end + 4
    if bin_header_end > len(raw):
        raise TruncatedFileError("File truncated before binary chunk length")

    bin_len = struct.unpack("<I", raw[json_end:bin_header_end])[0]
    bin_end = bin_header_end + bin_len
    if bin_end > len(raw):
        raise TruncatedFileError(
            f"Binary chunk overruns file: need {bin_end}, have {len(raw)}"
        )

    binary_data = raw[bin_header_end:bin_end]
    return from_json_dict(json_dict, binary_data)
