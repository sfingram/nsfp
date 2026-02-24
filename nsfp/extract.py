"""Extract musical notation from NSF files via frame-by-frame APU emulation.

Ports the extraction algorithm from FamiStudio's NsfFile.cs, using the
same NotSoFatso C bridge (NsfGetState API) that FamiStudio uses.
"""

from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    CHANNEL_COUNT,
    CHANNEL_DPCM,
    CHANNEL_FDSWAVE,
    CHANNEL_MMC5DPCM,
    CHANNEL_MMC5SQUARE1,
    CHANNEL_MMC5SQUARE2,
    CHANNEL_N163WAVE1,
    CHANNEL_N163WAVE8,
    CHANNEL_NOISE,
    CHANNEL_S5BSQUARE1,
    CHANNEL_S5BSQUARE3,
    CHANNEL_SQUARE1,
    CHANNEL_SQUARE2,
    CHANNEL_TRIANGLE,
    CHANNEL_VRC6SAW,
    CHANNEL_VRC6SQUARE1,
    CHANNEL_VRC6SQUARE2,
    CHANNEL_VRC7FM1,
    CHANNEL_VRC7FM6,
    STATE_DPCMACTIVE,
    STATE_DPCMCOUNTER,
    STATE_DPCMLOOP,
    STATE_DPCMPITCH,
    STATE_DPCMSAMPLEADDR,
    STATE_DPCMSAMPLELENGTH,
    STATE_DUTYCYCLE,
    STATE_FDSMASTERVOLUME,
    STATE_FDSMODULATIONDEPTH,
    STATE_FDSMODULATIONSPEED,
    STATE_FMOCTAVE,
    STATE_FMSUSTAIN,
    STATE_FMTRIGGER,
    STATE_FMTRIGGERCHANGE,
    STATE_N163NUMCHANNELS,
    STATE_N163WAVEPOS,
    STATE_N163WAVESIZE,
    STATE_PERIOD,
    STATE_S5BENVENABLED,
    STATE_S5BENVFREQUENCY,
    STATE_S5BENVSHAPE,
    STATE_S5BENVTRIGGER,
    STATE_S5BMIXER,
    STATE_S5BNOISEFREQUENCY,
    STATE_VOLUME,
    STATE_VRC7PATCH,
)
from .notation import (
    ChannelData,
    Metadata,
    NoteEvent,
    NotationFile,
    SongData,
    expansion_chip_list,
)
from .nsfp import NSF, Channel, NSF_LIB, make_channels
from .nsf_build import ffibuilder

# ── Channel metadata table ──────────────────────────────────────────────────

CHANNEL_INFO: Dict[int, Tuple[str, str]] = {
    0: ("square", "Square 1"),
    1: ("square", "Square 2"),
    2: ("triangle", "Triangle"),
    3: ("noise", "Noise"),
    4: ("dpcm", "DPCM"),
    5: ("vrc6_square", "VRC6 Square 1"),
    6: ("vrc6_square", "VRC6 Square 2"),
    7: ("vrc6_saw", "VRC6 Saw"),
    8: ("vrc7_fm", "VRC7 FM 1"),
    9: ("vrc7_fm", "VRC7 FM 2"),
    10: ("vrc7_fm", "VRC7 FM 3"),
    11: ("vrc7_fm", "VRC7 FM 4"),
    12: ("vrc7_fm", "VRC7 FM 5"),
    13: ("vrc7_fm", "VRC7 FM 6"),
    14: ("fds", "FDS"),
    15: ("mmc5_square", "MMC5 Square 1"),
    16: ("mmc5_square", "MMC5 Square 2"),
    17: ("mmc5_dpcm", "MMC5 DPCM"),
    18: ("n163_wave", "N163 Wave 1"),
    19: ("n163_wave", "N163 Wave 2"),
    20: ("n163_wave", "N163 Wave 3"),
    21: ("n163_wave", "N163 Wave 4"),
    22: ("n163_wave", "N163 Wave 5"),
    23: ("n163_wave", "N163 Wave 6"),
    24: ("n163_wave", "N163 Wave 7"),
    25: ("n163_wave", "N163 Wave 8"),
    26: ("s5b_square", "S5B Square 1"),
    27: ("s5b_square", "S5B Square 2"),
    28: ("s5b_square", "S5B Square 3"),
}

# ── Note table generation ───────────────────────────────────────────────────

FREQ_NTSC = 1789773
FREQ_PAL = 1662607

# Number of notes: indices 1..96 map to C1..B8. Index 0 is unused.
NUM_NOTES = 97


def _generate_note_tables(tuning: int = 440) -> Dict[str, List[int]]:
    """Generate period/frequency lookup tables for all chip types.

    Returns a dict of table_name -> list[97], where index 0 is unused and
    indices 1-96 map to notes C1 through B8.
    """
    # 2^(45/12) maps A4 down 45 semitones to C1. Index 1 = C1, A4 = index 46.
    freq_ratio = 1.0 / 13.454340859610068739450573644169  # 2^(45/12)
    freq_c1 = tuning * freq_ratio
    clock_ntsc = FREQ_NTSC / 16.0
    clock_pal = FREQ_PAL / 16.0

    tables: Dict[str, List[int]] = {
        "ntsc": [0] * NUM_NOTES,
        "pal": [0] * NUM_NOTES,
        "vrc6_saw": [0] * NUM_NOTES,
        "fds": [0] * NUM_NOTES,
        "vrc7": [0] * NUM_NOTES,
    }
    for j in range(8):
        tables[f"n163_{j}"] = [0] * NUM_NOTES

    for i in range(1, NUM_NOTES):
        freq = freq_c1 * (2.0 ** ((i - 1) / 12.0))
        octave = (i - 1) // 12

        # APU square/triangle (also used for mmc5, s5b)
        tables["ntsc"][i] = int(clock_ntsc / freq - 0.5)
        tables["pal"][i] = int(clock_pal / freq - 0.5)

        # VRC6 Saw: clock divisor is 14 instead of 16
        tables["vrc6_saw"][i] = int((clock_ntsc * 16) / (freq * 14) - 0.5)

        # FDS: frequency register increases with pitch (inverted from APU)
        tables["fds"][i] = int(freq * 65536.0 / (FREQ_NTSC / 16.0) + 0.5)

        # VRC7: octave 0 base values, then left-shift for higher octaves
        if octave == 0:
            tables["vrc7"][i] = int(freq * 262144.0 / 49715.0 + 0.5)
        else:
            base_note = (i - 1) % 12 + 1
            tables["vrc7"][i] = tables["vrc7"][base_note] << octave

        # N163: 8 variants for 1–8 active channels
        for j in range(8):
            tables[f"n163_{j}"][i] = min(
                0xFFFF,
                int(freq * (j + 1) * 983040.0 / (FREQ_NTSC / 16.0) / 4),
            )

    return tables


def get_best_matching_note(
    period: int, note_table: List[int]
) -> Tuple[int, int]:
    """Find the note whose table entry is closest to `period`.

    Returns (note_index, fine_pitch) where fine_pitch = period - table[best].
    """
    best_note = 1
    min_diff = abs(note_table[1] - period)

    for i in range(2, len(note_table)):
        diff = abs(note_table[i] - period)
        if diff < min_diff:
            min_diff = diff
            best_note = i

    fine_pitch = period - note_table[best_note]
    return best_note, fine_pitch


# ── Channel state tracking ──────────────────────────────────────────────────

STOPPED = 0
TRIGGERED = 1
RELEASED = 2


class ChannelState:
    """Mutable per-channel state used during frame-by-frame extraction."""

    __slots__ = (
        "period", "note", "pitch", "volume", "octave", "state",
        "fds_mod_depth", "fds_mod_speed", "s5b_env_freq",
        "fm_trigger", "fm_sustain", "instrument",
        "dmc_active", "dmc_sample_len",
    )

    def __init__(self):
        self.period: int = -1
        self.note: int = 0
        self.pitch: int = 0
        self.volume: int = 0
        self.octave: int = -1
        self.state: int = STOPPED
        self.fds_mod_depth: int = 0
        self.fds_mod_speed: int = 0
        self.s5b_env_freq: int = 0
        self.fm_trigger: bool = False
        self.fm_sustain: bool = False
        self.instrument: Optional[int] = None
        self.dmc_active: bool = False
        self.dmc_sample_len: int = 0


# ── Per-channel state reading ───────────────────────────────────────────────


def _get_state(nsf_file: Any, channel_id: int, state: int, sub: int = 0) -> int:
    return int(NSF_LIB.NsfGetState(nsf_file, channel_id, state, sub))


def _read_channel_state(nsf_file: Any, channel_id: int) -> tuple:
    """Read the raw APU state for a channel and return as a typed tuple."""
    ch_type = CHANNEL_INFO[channel_id][0]
    g = lambda st, sub=0: _get_state(nsf_file, channel_id, st, sub)

    if ch_type == "square" or ch_type == "mmc5_square":
        return (g(STATE_PERIOD), g(STATE_VOLUME), g(STATE_DUTYCYCLE))

    if ch_type == "triangle":
        return (g(STATE_PERIOD), g(STATE_VOLUME))

    if ch_type == "noise":
        return (g(STATE_PERIOD), g(STATE_VOLUME), g(STATE_DUTYCYCLE))

    if ch_type == "dpcm":
        return (
            g(STATE_DPCMSAMPLELENGTH),
            g(STATE_DPCMSAMPLEADDR),
            g(STATE_DPCMPITCH),
            g(STATE_DPCMLOOP),
            g(STATE_DPCMCOUNTER),
            g(STATE_DPCMACTIVE),
        )

    if ch_type == "vrc6_square":
        return (g(STATE_PERIOD), g(STATE_VOLUME), g(STATE_DUTYCYCLE))

    if ch_type == "vrc6_saw":
        return (g(STATE_PERIOD), g(STATE_VOLUME))

    if ch_type == "vrc7_fm":
        return (
            g(STATE_PERIOD),
            g(STATE_VOLUME),
            g(STATE_VRC7PATCH),
            g(STATE_FMOCTAVE),
            g(STATE_FMTRIGGER),
            g(STATE_FMSUSTAIN),
            g(STATE_FMTRIGGERCHANGE),
        )

    if ch_type == "fds":
        return (
            g(STATE_PERIOD),
            g(STATE_VOLUME),
            g(STATE_FDSMASTERVOLUME),
            g(STATE_FDSMODULATIONSPEED),
            g(STATE_FDSMODULATIONDEPTH),
            0,  # padding to match struct format
        )

    if ch_type == "n163_wave":
        return (
            g(STATE_PERIOD),
            g(STATE_VOLUME),
            g(STATE_N163WAVEPOS),
            g(STATE_N163WAVESIZE),
            g(STATE_N163NUMCHANNELS),
        )

    if ch_type == "s5b_square":
        return (
            g(STATE_PERIOD),
            g(STATE_VOLUME),
            g(STATE_S5BMIXER),
            g(STATE_S5BNOISEFREQUENCY),
            g(STATE_S5BENVENABLED),
            g(STATE_S5BENVFREQUENCY),
            g(STATE_S5BENVSHAPE),
            g(STATE_S5BENVTRIGGER),
        )

    if ch_type == "mmc5_dpcm":
        return (0,)

    raise ValueError(f"Unknown channel type: {ch_type}")


# ── Trigger / release state machine ─────────────────────────────────────────


def _note_to_octave(note: int) -> int:
    """Convert 1-based note index to octave number."""
    if note < 1:
        return 0
    return (note - 1) // 12


def _update_channel(
    channel: Channel,
    frame: int,
    raw: tuple,
    cs: ChannelState,
    notes: List[NoteEvent],
    note_tables: Dict[str, List[int]],
    is_pal: bool,
) -> None:
    """Process one frame of APU state for a channel, emitting note events."""
    ch_type = CHANNEL_INFO[channel.channel_id][0]

    if ch_type in ("square", "mmc5_square"):
        period, volume, duty = raw
        _update_generic(channel, frame, period, volume, duty, cs, notes,
                        note_tables["pal" if is_pal else "ntsc"], 0)

    elif ch_type == "triangle":
        period, volume = raw
        _update_generic(channel, frame, period, volume, 0, cs, notes,
                        note_tables["pal" if is_pal else "ntsc"], 0)

    elif ch_type == "noise":
        period_idx, volume, mode = raw
        _update_noise(channel, frame, period_idx, volume, mode, cs, notes)

    elif ch_type == "dpcm":
        sample_len, sample_addr, pitch, loop, counter, active = raw
        _update_dpcm(channel, frame, sample_len, sample_addr, pitch,
                      loop, counter, active, cs, notes)

    elif ch_type == "vrc6_square":
        period, volume, duty = raw
        _update_generic(channel, frame, period, volume, duty, cs, notes,
                        note_tables["pal" if is_pal else "ntsc"], 0)

    elif ch_type == "vrc6_saw":
        period, volume = raw
        _update_generic(channel, frame, period, volume, 0, cs, notes,
                        note_tables["vrc6_saw"], 0)

    elif ch_type == "vrc7_fm":
        period, vol, patch, octave, trigger, sustain, trig_change = raw
        _update_fm(channel, frame, period, vol, patch, octave,
                   trigger != 0, sustain != 0, trig_change != 0,
                   cs, notes, note_tables["vrc7"])

    elif ch_type == "fds":
        period, vol, master_vol, mod_speed, mod_depth, _ = raw
        _update_generic(channel, frame, period, vol, 0, cs, notes,
                        note_tables["fds"], 0)
        cs.fds_mod_depth = mod_depth
        cs.fds_mod_speed = mod_speed

    elif ch_type == "n163_wave":
        period, vol, wave_pos, wave_size, num_ch = raw
        table_key = f"n163_{max(0, min(7, num_ch - 1))}"
        _update_generic(channel, frame, period, vol, 0, cs, notes,
                        note_tables[table_key], 0)

    elif ch_type == "s5b_square":
        period, vol, mixer, noise_freq, env_en, env_freq, env_shape, env_trig = raw
        # S5B uses -1 as invalid period (unsigned 0xFFFF from C becomes large int)
        _update_generic(channel, frame, period, vol, 0, cs, notes,
                        note_tables["pal" if is_pal else "ntsc"], -1)
        cs.s5b_env_freq = env_freq

    elif ch_type == "mmc5_dpcm":
        pass  # MMC5 DPCM has no useful state to extract


def _emit_note(
    frame: int,
    event: str,
    note: int,
    pitch: int,
    volume: int,
    duty: int,
    instrument: Optional[int],
    notes: List[NoteEvent],
) -> None:
    notes.append(NoteEvent(
        frame=frame,
        event=event,
        note=note,
        octave=_note_to_octave(note),
        pitch=pitch,
        volume=volume,
        duty_cycle=duty,
        instrument=instrument,
    ))


def _update_generic(
    channel: Channel,
    frame: int,
    period: int,
    volume: int,
    duty: int,
    cs: ChannelState,
    notes: List[NoteEvent],
    note_table: List[int],
    invalid_period: int,
) -> None:
    """Generic trigger detection for square, triangle, VRC6, FDS, N163, S5B, MMC5."""
    triggered = volume != 0 and period != invalid_period

    if triggered:
        note, pitch = get_best_matching_note(period, note_table)

        if cs.state != TRIGGERED or note != cs.note:
            cs.state = TRIGGERED
            cs.note = note
            cs.pitch = pitch
            cs.volume = volume
            cs.period = period
            _emit_note(frame, "trigger", note, pitch, volume, duty,
                       cs.instrument, notes)
        elif volume != cs.volume or period != cs.period:
            cs.volume = volume
            cs.pitch = pitch
            cs.period = period
    else:
        if cs.state == TRIGGERED:
            _emit_note(frame, "stop", cs.note, cs.pitch, 0, duty,
                       cs.instrument, notes)
            cs.state = STOPPED


def _update_noise(
    channel: Channel,
    frame: int,
    period_idx: int,
    volume: int,
    mode: int,
    cs: ChannelState,
    notes: List[NoteEvent],
) -> None:
    """Noise channel: note = (period_idx ^ 0x0F) + 32."""
    triggered = volume != 0

    if triggered:
        note = (period_idx ^ 0x0F) + 32

        if cs.state != TRIGGERED or note != cs.note:
            cs.state = TRIGGERED
            cs.note = note
            cs.pitch = 0
            cs.volume = volume
            cs.period = period_idx
            _emit_note(frame, "trigger", note, 0, volume, mode,
                       cs.instrument, notes)
        elif volume != cs.volume:
            cs.volume = volume
    else:
        if cs.state == TRIGGERED:
            _emit_note(frame, "stop", cs.note, 0, 0, mode,
                       cs.instrument, notes)
            cs.state = STOPPED


def _update_dpcm(
    channel: Channel,
    frame: int,
    sample_len: int,
    sample_addr: int,
    pitch: int,
    loop: int,
    counter: int,
    active: int,
    cs: ChannelState,
    notes: List[NoteEvent],
) -> None:
    """DPCM channel: trigger on new sample start, stop when inactive."""
    dmc_active = active != 0

    if dmc_active and sample_len > 0:
        if cs.state != TRIGGERED or sample_addr != cs.period:
            cs.state = TRIGGERED
            cs.period = sample_addr
            # DPCM note: derive from sample address
            # Each DPCM sample address increments by 64 bytes from 0xC000
            note = max(1, min(96, ((sample_addr - 0xC000) // 64) + 1))
            cs.note = note
            cs.pitch = pitch
            cs.volume = 15
            _emit_note(frame, "trigger", note, pitch, 15, 0,
                       cs.instrument, notes)
    elif not dmc_active and cs.state == TRIGGERED:
        _emit_note(frame, "stop", cs.note, cs.pitch, 0, 0,
                   cs.instrument, notes)
        cs.state = STOPPED

    cs.dmc_active = dmc_active
    cs.dmc_sample_len = sample_len


def _update_fm(
    channel: Channel,
    frame: int,
    period: int,
    volume: int,
    patch: int,
    octave: int,
    trigger: bool,
    sustain: bool,
    trig_change: bool,
    cs: ChannelState,
    notes: List[NoteEvent],
    note_table: List[int],
) -> None:
    """VRC7 FM channel: uses trigger/sustain flags from hardware."""
    prev_trigger = cs.fm_trigger
    cs.fm_trigger = trigger
    cs.fm_sustain = sustain

    if not prev_trigger and trigger:
        # Note triggered
        # Reconstruct full period with octave for table lookup
        full_period = period * (1 << octave) if octave > 0 else period
        note, pitch = get_best_matching_note(full_period, note_table)

        cs.state = TRIGGERED
        cs.note = note
        cs.pitch = pitch
        cs.volume = volume
        cs.octave = octave
        cs.period = period
        cs.instrument = patch
        _emit_note(frame, "trigger", note, pitch, volume, 0,
                   patch, notes)

    elif prev_trigger and not trigger and sustain:
        # Note released (sustain still active)
        cs.state = RELEASED
        _emit_note(frame, "release", cs.note, cs.pitch, cs.volume, 0,
                   cs.instrument, notes)

    elif not trigger and not sustain:
        if cs.state == TRIGGERED or cs.state == RELEASED:
            _emit_note(frame, "stop", cs.note, cs.pitch, 0, 0,
                       cs.instrument, notes)
            cs.state = STOPPED

    elif trigger and cs.state == TRIGGERED:
        # Still triggered — check for parameter changes
        if period != cs.period or patch != cs.instrument:
            full_period = period * (1 << octave) if octave > 0 else period
            note, pitch = get_best_matching_note(full_period, note_table)
            cs.note = note
            cs.pitch = pitch
            cs.period = period
            cs.instrument = patch
            cs.volume = volume
            _emit_note(frame, "trigger", note, pitch, volume, 0,
                       patch, notes)


# ── Main extraction function ────────────────────────────────────────────────


def extract_notation(
    nsf_path: str,
    duration: int = 120,
    pattern_length: int = 256,
    tuning: int = 440,
) -> NotationFile:
    """Extract musical notation from an NSF file.

    Opens the NSF via NotSoFatso, runs frame-by-frame emulation for each
    track, and produces a NotationFile with note events and raw APU state.

    Args:
        nsf_path: Path to the .nsf file.
        duration: Seconds to emulate per track.
        pattern_length: Pattern length for notation grouping.
        tuning: A4 reference frequency in Hz.

    Returns:
        A fully populated NotationFile.
    """
    nsf = NSF(nsf_path, pattern_length=pattern_length, duration=duration)
    note_tables = _generate_note_tables(tuning)

    songs: List[SongData] = []

    for track_idx in range(nsf.track_count):
        NSF_LIB.NsfSetTrack(nsf.file, track_idx)
        channels = make_channels(nsf, track_idx)

        channel_states: Dict[int, ChannelState] = {
            ch.channel_id: ChannelState() for ch in channels
        }
        channel_raw_frames: Dict[int, List[tuple]] = {
            ch.channel_id: [] for ch in channels
        }
        channel_notes: Dict[int, List[NoteEvent]] = {
            ch.channel_id: [] for ch in channels
        }

        for frame in range(nsf.frame_count):
            NSF_LIB.NsfRunFrame(nsf.file)
            for ch in channels:
                cid = ch.channel_id
                raw = _read_channel_state(nsf.file, cid)
                channel_raw_frames[cid].append(raw)
                _update_channel(
                    ch, frame, raw,
                    channel_states[cid],
                    channel_notes[cid],
                    note_tables,
                    nsf.is_pal,
                )

        # Build ChannelData list for this song
        channel_data_list: List[ChannelData] = []
        for ch in channels:
            cid = ch.channel_id
            ch_type, ch_name = CHANNEL_INFO[cid]
            channel_data_list.append(ChannelData(
                channel_id=cid,
                channel_type=ch_type,
                channel_name=ch_name,
                notes=channel_notes[cid],
                raw_frames=channel_raw_frames[cid],
            ))

        # Get track name
        raw_name = NSF_LIB.NsfGetTrackName(nsf.file, track_idx)
        track_name = ffibuilder.string(raw_name).decode("ascii")
        if not track_name:
            track_name = f"Track {track_idx}"

        songs.append(SongData(
            index=track_idx,
            name=track_name,
            num_frames=nsf.frame_count,
            pattern_length=pattern_length,
            channels=channel_data_list,
        ))

    metadata = Metadata(
        title=nsf.title,
        artist=nsf.artist,
        copyright=nsf.copyright,
        region="pal" if nsf.is_pal else "ntsc",
        frame_rate=nsf.frame_rate,
        expansion=nsf.expansion,
        expansion_chips=expansion_chip_list(nsf.expansion),
    )

    return NotationFile(metadata=metadata, songs=songs)
