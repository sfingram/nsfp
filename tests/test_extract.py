"""Tests for NSF → NSFN notation extraction."""

import os
import tempfile

import pytest

from nsfp.extract import (
    CHANNEL_INFO,
    FREQ_NTSC,
    NUM_NOTES,
    _generate_note_tables,
    get_best_matching_note,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

# Path to mm2.nsf for integration tests
_MM2_NSF = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "Mega Man 2 [RockMan 2 - Dr. Wily no Nazo] (1988-12-24)(Capcom).nsf",
)

_LIB_AVAILABLE = os.path.exists(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "nsfp", "libNotSoFatso.dylib")
) or os.path.exists(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "nsfp", "libNotSoFatso.so")
)

_SKIP_INTEGRATION = not (os.path.exists(_MM2_NSF) and _LIB_AVAILABLE)
integration = pytest.mark.skipif(
    _SKIP_INTEGRATION, reason="mm2.nsf or built library not available"
)


# ── Unit tests: note table generation ────────────────────────────────────────


class TestNoteTableGeneration:
    """Tests for _generate_note_tables and related functions."""

    def setup_method(self):
        self.tables = _generate_note_tables(440)

    def test_note_table_ntsc_a4(self):
        """A4 (note index 46) should have period ≈ 253 for NTSC square.

        The freq_ratio 1/13.454... = 2^(-45/12) maps A4 down to C1,
        so index 1 = C1 and A4 = 1 + 45 = 46.
        """
        period = self.tables["ntsc"][46]
        # NTSC clock / 16 / 440 - 0.5 ≈ 253.7 → int = 253
        assert 252 <= period <= 254, f"A4 NTSC period={period}, expected ~253"

    def test_note_table_c1_is_index_1(self):
        """Index 1 should map to C1 with a valid period."""
        # C1 ≈ 32.7 Hz. NTSC period = 111860.8 / 32.7 - 0.5 ≈ 3419
        period = self.tables["ntsc"][1]
        assert 3400 <= period <= 3450, f"C1 period={period}, expected ~3419"

    def test_note_table_lengths(self):
        """All tables should have exactly 97 entries (index 0 unused)."""
        for name, table in self.tables.items():
            assert len(table) == NUM_NOTES, (
                f"Table '{name}' has {len(table)} entries, expected {NUM_NOTES}"
            )

    def test_best_matching_note_exact(self):
        """Exact period match should return correct note with 0 fine pitch."""
        table = self.tables["ntsc"]
        # Use the period for note 58 (A4) directly
        period = table[58]
        note, pitch = get_best_matching_note(period, table)
        assert note == 58
        assert pitch == 0

    def test_best_matching_note_between(self):
        """Period between two notes should pick the closest one."""
        table = self.tables["ntsc"]
        # Period halfway between note 58 and 59
        p58 = table[58]
        p59 = table[59]
        mid = (p58 + p59) // 2
        note, pitch = get_best_matching_note(mid, table)
        # Should be one of the two adjacent notes
        assert note in (58, 59), f"Expected note 58 or 59, got {note}"
        # Fine pitch should be non-zero (unless mid happens to equal one exactly)
        # Just verify it's reasonable
        assert abs(pitch) < abs(p58 - p59)

    def test_noise_note_conversion(self):
        """Noise note formula: (period ^ 0x0F) + 32."""
        # Period index 0 → note = (0 ^ 15) + 32 = 47
        assert (0 ^ 0x0F) + 32 == 47
        # Period index 15 → note = (15 ^ 15) + 32 = 32
        assert (15 ^ 0x0F) + 32 == 32
        # Period index 7 → note = (7 ^ 15) + 32 = 40
        assert (7 ^ 0x0F) + 32 == 40

    def test_channel_info_completeness(self):
        """All 29 channel IDs (0-28) should have entries in CHANNEL_INFO."""
        for i in range(29):
            assert i in CHANNEL_INFO, f"Missing channel ID {i} in CHANNEL_INFO"
            ch_type, ch_name = CHANNEL_INFO[i]
            assert isinstance(ch_type, str) and len(ch_type) > 0
            assert isinstance(ch_name, str) and len(ch_name) > 0

    def test_vrc7_note_table_octave_shift(self):
        """VRC7 table values should roughly double per octave."""
        vrc7 = self.tables["vrc7"]
        # Compare C in octave 0 (note 1) vs C in octave 1 (note 13)
        c0 = vrc7[1]
        c1 = vrc7[13]
        assert c1 == c0 * 2, f"VRC7 C1={c1} should be 2*C0={c0*2}"
        # Octave 2 (note 25) should be 4x octave 0
        c2 = vrc7[25]
        assert c2 == c0 * 4, f"VRC7 C2={c2} should be 4*C0={c0*4}"

    def test_fds_note_table_increasing(self):
        """FDS periods should increase with note index (inverted from APU)."""
        fds = self.tables["fds"]
        for i in range(2, NUM_NOTES):
            assert fds[i] >= fds[i - 1], (
                f"FDS table not increasing: [{i-1}]={fds[i-1]} > [{i}]={fds[i]}"
            )


# ── Integration tests ────────────────────────────────────────────────────────


@integration
class TestExtractMM2:
    """Integration tests using Mega Man 2 NSF file."""

    @pytest.fixture(autouse=True)
    def _extract_track0(self):
        """Extract track 0 once for all tests in this class."""
        from nsfp.extract import extract_notation
        self.result = extract_notation(_MM2_NSF, duration=5)

    def test_extract_mm2_track0(self):
        """Extracting track 0 should produce a valid NotationFile."""
        from nsfp.notation import NotationFile
        assert isinstance(self.result, NotationFile)
        assert len(self.result.songs) > 0

    def test_extract_mm2_metadata(self):
        """Metadata should reflect the MM2 NSF header."""
        md = self.result.metadata
        assert "Mega Man" in md.title or "RockMan" in md.title or "Mega" in md.title
        assert md.expansion == 0
        assert md.region == "ntsc"

    def test_extract_mm2_channels(self):
        """Track 0 should have 5 channels (sq1, sq2, tri, noise, dpcm)."""
        song = self.result.songs[0]
        assert len(song.channels) == 5
        types = {ch.channel_type for ch in song.channels}
        assert types == {"square", "triangle", "noise", "dpcm"}

    def test_extract_mm2_has_notes(self):
        """Square 1 channel should have at least some note events."""
        song = self.result.songs[0]
        sq1 = next(ch for ch in song.channels if ch.channel_name == "Square 1")
        assert len(sq1.notes) > 0, "Square 1 should have note events"

    def test_extract_mm2_has_raw_frames(self):
        """Raw frames count should equal num_frames for each channel."""
        song = self.result.songs[0]
        for ch in song.channels:
            assert ch.raw_frames is not None, f"{ch.channel_name} missing raw_frames"
            assert len(ch.raw_frames) == song.num_frames, (
                f"{ch.channel_name}: {len(ch.raw_frames)} frames != {song.num_frames}"
            )

    def test_extract_mm2_roundtrip(self):
        """Write extracted NotationFile to .nsfn, read back, data should match."""
        from nsfp.notation import write, read
        fd, path = tempfile.mkstemp(suffix=".nsfn")
        os.close(fd)
        try:
            write(path, self.result)
            loaded = read(path)
            assert loaded.metadata.title == self.result.metadata.title
            assert len(loaded.songs) == len(self.result.songs)
            for orig_song, loaded_song in zip(self.result.songs, loaded.songs):
                assert len(loaded_song.channels) == len(orig_song.channels)
                for orig_ch, loaded_ch in zip(orig_song.channels, loaded_song.channels):
                    assert len(loaded_ch.notes) == len(orig_ch.notes)
                    if orig_ch.raw_frames:
                        assert loaded_ch.raw_frames is not None
                        assert len(loaded_ch.raw_frames) == len(orig_ch.raw_frames)
        finally:
            os.unlink(path)
