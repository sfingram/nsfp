"""
Read an NSF (NES Sound File) using the NotSoFatSo library.
"""

from typing import List
from .nsf_build import NSF_LIB, ffibuilder
from .constants import *


class NSF:
    def __init__(self, filename, pattern_length=256, duration=120):
        self.filename = filename
        self.pattern_length = pattern_length
        self.duration = duration

        # open/parse the nsf file
        self.file = NSF_LIB.NsfOpen(ffibuilder.new("char[]", filename.encode("ascii")))
        assert (
            ffibuilder.cast("uint32_t", self.file) != 0
        ), f"Failed to open NSF file:  {filename}"

        # extract the metadata
        self.track_count = NSF_LIB.NsfGetTrackCount(self.file)
        self.is_ntsc = NSF_LIB.NsfIsPal(self.file) == 0
        self.is_pal = not self.is_ntsc
        self.frame_rate = 60 if self.is_ntsc else 50
        self.frame_count = self.duration * self.frame_rate
        self.title = ffibuilder.string(NSF_LIB.NsfGetTitle(self.file)).decode("ascii")
        self.artist = ffibuilder.string(NSF_LIB.NsfGetArtist(self.file)).decode("ascii")
        self.copyright = ffibuilder.string(NSF_LIB.NsfGetCopyright(self.file)).decode(
            "ascii"
        )
        self.expansion = int(
            ffibuilder.cast("uint32_t", NSF_LIB.NsfGetExpansion(self.file))
        )
        assert (
            self.expansion & ALL_MASK == self.expansion
        ), f"Invalid expansion mask:  {hex(self.expansion)}"

        # pull out the songs
        self.songs = [Song(self, i) for i in range(self.track_count)]


class Channel:
    @staticmethod
    def namco_count(nsf: NSF, track: int) -> int:
        """get the number of namco channels + 1 in a track"""
        namco_count = 1
        if nsf.expansion & N163_MASK != 0:
            NSF_LIB.NsfSetTrack(nsf.file, track)
            for i in range(nsf.frame_count):
                playing = int(NSF_LIB.NsfRunFrame(nsf.file)) != 0
                if playing:
                    namco_count = max(
                        namco_count,
                        int(
                            NSF_LIB.NsfGetState(
                                nsf.file, CHANNEL_N163WAVE1, STATE_N163NUMCHANNELS, 0
                            )
                        ),
                    )
        return namco_count

    @staticmethod
    def is_active(channel_id: int, expansion: int, namco_count: int) -> bool:
        if channel_id < CHANNEL_EXPANSIONAUDIOSTART:
            return True
        if channel_id >= CHANNEL_VRC6SQUARE1 and channel_id <= CHANNEL_VRC6SAW:
            return expansion & VRC6_MASK != 0
        if channel_id >= CHANNEL_VRC7FM1 and channel_id <= CHANNEL_VRC7FM6:
            return expansion & VRC7_MASK != 0
        if channel_id == CHANNEL_FDSWAVE:
            return expansion & FDS_MASK != 0
        if channel_id >= CHANNEL_MMC5SQUARE1 and channel_id <= CHANNEL_MMC5DPCM:
            return expansion & MMC5_MASK != 0
        if channel_id >= CHANNEL_N163WAVE1 and channel_id <= CHANNEL_N163WAVE8:
            return (
                expansion & N163_MASK != 0
                and channel_id - CHANNEL_N163WAVE1 < namco_count
            )
        if channel_id >= CHANNEL_S5BSQUARE1 and channel_id <= CHANNEL_S5BSQUARE3:
            return expansion & S5B_MASK != 0
        assert False, f"Invalid channel id:  {channel_id}"

    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.reset()

    def reset(self):
        self.triggered = 1
        self.released = 2
        self.stopped = 0

        self.period = -1
        self.note = 0
        self.pitch = 0
        self.volume = 15
        self.octave = -1
        self.state = self.stopped

        self.fds_mod_depth = 0
        self.fds_mod_speed = 0

        self.instrument = None


def make_channels(nsf: NSF, track: int) -> List[Channel]:
    """create a list of channels for a track"""
    namco_count = Channel.namco_count(nsf, track)
    return [
        Channel(i)
        for i in range(CHANNEL_COUNT)
        if Channel.is_active(i, nsf.expansion, namco_count)
    ]


class Song:
    def __init__(self, nsf, index):
        self.nsf = nsf
        self.index = index
        self.num_frames = nsf.duration * nsf.frame_rate
        raw_name = NSF_LIB.NsfGetTrackName(nsf.file, index)
        self.name = ffibuilder.string(raw_name).decode("ascii")
        if len(self.name) == 0:
            self.name = f"Track {index}"
        self.channels = {i: v for i, v in enumerate(make_channels(nsf, index))}
        NSF_LIB.NsfSetTrack(nsf.file, index)
        for frame in range(self.num_frames):
            play_called = NSF_LIB.NsfRunFrame(nsf.file) != 0
            assert play_called or (
                not play_called and frame < 1000
            ), "Too many frames before play called"
            if play_called:
                pass
