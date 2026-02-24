"""Tests for the NSFN notation file format module."""

import json
import struct
import tempfile
import os

import pytest

from nsfp.notation import (
    MAGIC,
    VERSION,
    HEADER_SIZE,
    STRUCT_FORMATS,
    FRAME_SIZES,
    NotationError,
    InvalidMagicError,
    UnsupportedVersionError,
    TruncatedFileError,
    NoteEvent,
    RawDataRef,
    ChannelData,
    SongData,
    Metadata,
    NotationFile,
    pack_frames,
    unpack_frames,
    expansion_chip_list,
    write,
    read,
    to_json_dict,
    compute_binary_layout,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _tmpfile():
    fd, path = tempfile.mkstemp(suffix=".nsfn")
    os.close(fd)
    return path


def _write_raw(path: str, data: bytes):
    with open(path, "wb") as f:
        f.write(data)


# ── Test 1: magic and version constants ──────────────────────────────────────


def test_magic_and_version_constants():
    assert MAGIC == b"NSFN"
    assert VERSION == 1
    assert HEADER_SIZE == 12


# ── Test 2: frame sizes match struct formats ─────────────────────────────────


def test_frame_sizes_match_struct_formats():
    expected = {
        "square": 4,
        "triangle": 3,
        "noise": 3,
        "dpcm": 10,
        "vrc6_square": 4,
        "vrc6_saw": 3,
        "vrc7_fm": 8,
        "fds": 8,
        "mmc5_square": 4,
        "mmc5_dpcm": 1,
        "n163_wave": 8,
        "s5b_square": 10,
    }
    for name, size in expected.items():
        assert name in STRUCT_FORMATS, f"Missing struct format: {name}"
        assert name in FRAME_SIZES, f"Missing frame size: {name}"
        assert FRAME_SIZES[name] == size, (
            f"{name}: expected {size}, got {FRAME_SIZES[name]}"
        )
        assert struct.calcsize(STRUCT_FORMATS[name]) == size


# ── Test 3: pack/unpack round-trip for square ────────────────────────────────


def test_pack_unpack_square_frames():
    frames = [(1234, 15, 2), (0, 0, 0), (2047, 8, 3)]
    data = pack_frames("square", frames)
    assert len(data) == 4 * 3
    result = unpack_frames("square", data)
    assert result == frames


# ── Test 4: pack/unpack round-trip for every struct format ───────────────────


_SAMPLE_FRAMES = {
    "square":      [(500, 12, 2)],
    "triangle":    [(800, 1)],
    "noise":       [(7, 10, 1)],
    "dpcm":        [(256, -100, 9, 1, 64, 1)],
    "vrc6_square": [(400, 8, 3)],
    "vrc6_saw":    [(600, 5)],
    "vrc7_fm":     [(300, 7, 2, 4, 1, 0, -1)],
    "fds":         [(1000, 32, 2, 500, 7, 0)],
    "mmc5_square": [(700, 11, 1)],
    "mmc5_dpcm":   [(0,)],
    "n163_wave":   [(-5000, 15, 0, 32, 4)],
    "s5b_square":  [(400, 12, 7, 15, 0, 2000, 8, 1)],
}


def test_pack_unpack_all_formats():
    for name, frames in _SAMPLE_FRAMES.items():
        data = pack_frames(name, frames)
        assert len(data) == FRAME_SIZES[name] * len(frames), f"Bad length for {name}"
        result = unpack_frames(name, data)
        assert result == frames, f"Round-trip failed for {name}"


# ── Test 5: round-trip empty file ────────────────────────────────────────────


def test_roundtrip_empty_file():
    path = _tmpfile()
    try:
        nf = NotationFile()
        write(path, nf)
        loaded = read(path)
        assert loaded.songs == []
        assert loaded.metadata.title == ""
    finally:
        os.unlink(path)


# ── Test 6: round-trip metadata only ─────────────────────────────────────────


def test_roundtrip_metadata_only():
    path = _tmpfile()
    try:
        md = Metadata(
            title="Mega Man 2",
            artist="Takashi Tateishi",
            copyright="1988 Capcom",
            region="ntsc",
            frame_rate=60,
            expansion=0,
        )
        nf = NotationFile(metadata=md)
        write(path, nf)
        loaded = read(path)
        assert loaded.metadata.title == "Mega Man 2"
        assert loaded.metadata.artist == "Takashi Tateishi"
        assert loaded.metadata.copyright == "1988 Capcom"
        assert loaded.metadata.region == "ntsc"
        assert loaded.metadata.frame_rate == 60
        assert loaded.metadata.expansion == 0
    finally:
        os.unlink(path)


# ── Test 7: round-trip one song, one channel, no notes ───────────────────────


def test_roundtrip_one_song_one_channel_no_notes():
    path = _tmpfile()
    try:
        ch = ChannelData(channel_id=0, channel_type="square", channel_name="Square 1")
        song = SongData(index=0, name="Title", num_frames=100, channels=[ch])
        nf = NotationFile(songs=[song])
        write(path, nf)
        loaded = read(path)
        assert len(loaded.songs) == 1
        assert loaded.songs[0].name == "Title"
        assert loaded.songs[0].num_frames == 100
        assert len(loaded.songs[0].channels) == 1
        assert loaded.songs[0].channels[0].channel_type == "square"
        assert loaded.songs[0].channels[0].notes == []
    finally:
        os.unlink(path)


# ── Test 8: round-trip note events ───────────────────────────────────────────


def test_roundtrip_note_events():
    path = _tmpfile()
    try:
        notes = [
            NoteEvent(frame=0, event="trigger", note=45, octave=3, pitch=9,
                      volume=15, duty_cycle=2, instrument=None),
            NoteEvent(frame=10, event="release", note=45, octave=3, pitch=9,
                      volume=0, duty_cycle=2, instrument=3),
        ]
        ch = ChannelData(
            channel_id=0, channel_type="square",
            channel_name="Square 1", notes=notes,
        )
        song = SongData(index=0, name="Test", num_frames=20, channels=[ch])
        nf = NotationFile(songs=[song])
        write(path, nf)
        loaded = read(path)
        loaded_notes = loaded.songs[0].channels[0].notes
        assert len(loaded_notes) == 2
        assert loaded_notes[0].frame == 0
        assert loaded_notes[0].event == "trigger"
        assert loaded_notes[0].volume == 15
        assert loaded_notes[0].instrument is None
        assert loaded_notes[1].instrument == 3
    finally:
        os.unlink(path)


# ── Test 9: round-trip binary channel data ───────────────────────────────────


def test_roundtrip_binary_channel_data():
    path = _tmpfile()
    try:
        frames = [(500, 12, 2), (600, 8, 1), (700, 15, 3)]
        ch = ChannelData(
            channel_id=0, channel_type="square",
            channel_name="Square 1", raw_frames=frames,
        )
        song = SongData(index=0, name="Test", num_frames=3, channels=[ch])
        nf = NotationFile(songs=[song])
        write(path, nf)
        loaded = read(path)
        loaded_ch = loaded.songs[0].channels[0]
        assert loaded_ch.raw_frames == frames
        assert loaded_ch.raw_data_ref is not None
        assert loaded_ch.raw_data_ref.struct_format == "square"
        assert loaded_ch.raw_data_ref.frame_size == 4
    finally:
        os.unlink(path)


# ── Test 10: round-trip multiple songs and channels ──────────────────────────


def test_roundtrip_multiple_songs_channels():
    path = _tmpfile()
    try:
        sq_frames = [(100, 10, 1), (200, 11, 2)]
        tri_frames = [(300, 1), (400, 0)]
        ch1 = ChannelData(
            channel_id=0, channel_type="square",
            channel_name="Square 1", raw_frames=sq_frames,
        )
        ch2 = ChannelData(
            channel_id=2, channel_type="triangle",
            channel_name="Triangle", raw_frames=tri_frames,
        )
        song1 = SongData(index=0, name="Song A", num_frames=2, channels=[ch1, ch2])

        noise_frames = [(5, 8, 0)]
        ch3 = ChannelData(
            channel_id=3, channel_type="noise",
            channel_name="Noise", raw_frames=noise_frames,
        )
        song2 = SongData(index=1, name="Song B", num_frames=1, channels=[ch3])

        nf = NotationFile(songs=[song1, song2])
        write(path, nf)
        loaded = read(path)

        assert len(loaded.songs) == 2
        assert loaded.songs[0].name == "Song A"
        assert loaded.songs[1].name == "Song B"
        assert len(loaded.songs[0].channels) == 2
        assert loaded.songs[0].channels[0].raw_frames == sq_frames
        assert loaded.songs[0].channels[1].raw_frames == tri_frames
        assert loaded.songs[1].channels[0].raw_frames == noise_frames
    finally:
        os.unlink(path)


# ── Test 11: binary offsets are correct ──────────────────────────────────────


def test_binary_offsets_are_correct():
    sq_frames = [(100, 10, 1)] * 5   # 5 * 4 = 20 bytes
    tri_frames = [(300, 1)] * 3      # 3 * 3 = 9 bytes

    ch1 = ChannelData(
        channel_id=0, channel_type="square",
        channel_name="Square 1", raw_frames=sq_frames,
    )
    ch2 = ChannelData(
        channel_id=2, channel_type="triangle",
        channel_name="Triangle", raw_frames=tri_frames,
    )
    song = SongData(index=0, name="Test", num_frames=5, channels=[ch1, ch2])
    nf = NotationFile(songs=[song])

    layout, blob = compute_binary_layout(nf)

    # ch1 should start at offset 0
    ch1_info = layout[id(ch1)]
    assert ch1_info["byte_offset"] == 0
    assert ch1_info["byte_length"] == 20

    # ch2 should start right after ch1
    ch2_info = layout[id(ch2)]
    assert ch2_info["byte_offset"] == 20
    assert ch2_info["byte_length"] == 9

    assert len(blob) == 29


# ── Test 12: error on bad magic ──────────────────────────────────────────────


def test_error_bad_magic():
    path = _tmpfile()
    try:
        data = b"BAAD" + struct.pack("<I", 1) + struct.pack("<I", 2) + b"{}" + struct.pack("<I", 0)
        _write_raw(path, data)
        with pytest.raises(InvalidMagicError):
            read(path)
    finally:
        os.unlink(path)


# ── Test 13: error on wrong version ──────────────────────────────────────────


def test_error_wrong_version():
    path = _tmpfile()
    try:
        data = MAGIC + struct.pack("<I", 99) + struct.pack("<I", 2) + b"{}" + struct.pack("<I", 0)
        _write_raw(path, data)
        with pytest.raises(UnsupportedVersionError):
            read(path)
    finally:
        os.unlink(path)


# ── Test 14: error on truncated header ───────────────────────────────────────


def test_error_truncated_header():
    path = _tmpfile()
    try:
        _write_raw(path, b"NSF")  # Only 3 bytes, need 12
        with pytest.raises(TruncatedFileError):
            read(path)
    finally:
        os.unlink(path)


# ── Test 15: error on truncated JSON ─────────────────────────────────────────


def test_error_truncated_json():
    path = _tmpfile()
    try:
        # Claim 1000 bytes of JSON but provide none
        data = MAGIC + struct.pack("<I", 1) + struct.pack("<I", 1000)
        _write_raw(path, data)
        with pytest.raises(TruncatedFileError):
            read(path)
    finally:
        os.unlink(path)


# ── Test 16: error on truncated binary ───────────────────────────────────────


def test_error_truncated_binary():
    path = _tmpfile()
    try:
        json_bytes = b"{}"
        data = (
            MAGIC
            + struct.pack("<I", 1)
            + struct.pack("<I", len(json_bytes))
            + json_bytes
            + struct.pack("<I", 9999)  # claim 9999 bytes of binary
        )
        _write_raw(path, data)
        with pytest.raises(TruncatedFileError):
            read(path)
    finally:
        os.unlink(path)


# ── Test 17: expansion chips populated ───────────────────────────────────────


def test_expansion_chips_populated():
    assert expansion_chip_list(0) == []
    assert expansion_chip_list(1) == ["VRC6"]
    assert expansion_chip_list(0b000011) == ["VRC6", "VRC7"]
    assert expansion_chip_list(0b111111) == ["VRC6", "VRC7", "FDS", "MMC5", "N163", "S5B"]
    # Test that write/read preserves expansion_chips from mask
    path = _tmpfile()
    try:
        md = Metadata(expansion=0b000101)  # VRC6 + FDS
        nf = NotationFile(metadata=md)
        write(path, nf)
        loaded = read(path)
        assert loaded.metadata.expansion_chips == ["VRC6", "FDS"]
    finally:
        os.unlink(path)


# ── Test 18: JSON dict schema structure ──────────────────────────────────────


def test_json_dict_schema_structure():
    ch = ChannelData(
        channel_id=0, channel_type="square", channel_name="Square 1",
        notes=[NoteEvent(frame=0, event="trigger", note=45, octave=3,
                         pitch=9, volume=15, duty_cycle=2)],
    )
    song = SongData(index=0, name="Title", num_frames=100, channels=[ch])
    md = Metadata(title="Test", expansion=1)
    nf = NotationFile(metadata=md, songs=[song])

    layout, _ = compute_binary_layout(nf)
    d = to_json_dict(nf, layout)

    # Top-level keys
    assert d["format"] == "nsfn"
    assert d["version"] == 1
    assert "metadata" in d
    assert "songs" in d

    # Metadata keys
    meta = d["metadata"]
    for key in ("title", "artist", "copyright", "region", "frame_rate",
                "expansion", "expansion_chips"):
        assert key in meta, f"Missing metadata key: {key}"

    # Song keys
    s = d["songs"][0]
    for key in ("index", "name", "num_frames", "pattern_length", "channels"):
        assert key in s, f"Missing song key: {key}"

    # Channel keys
    c = s["channels"][0]
    for key in ("channel_id", "channel_type", "channel_name", "notes", "raw_data_ref"):
        assert key in c, f"Missing channel key: {key}"

    # Note keys
    n = c["notes"][0]
    for key in ("frame", "event", "note", "octave", "pitch", "volume",
                "duty_cycle", "instrument"):
        assert key in n, f"Missing note key: {key}"
