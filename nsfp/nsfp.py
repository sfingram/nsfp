"""
Read an NSF (NES Sound File) 

(from https://wiki.nesdev.org/w/index.php/NSF ) :

offset  # of bytes   Function
----------------------------
$000    5   STRING  'N','E','S','M',$1A (denotes an NES sound format file)
$005    1   BYTE    Version number $01 (or $02 for NSF2)
$006    1   BYTE    Total songs   (1=1 song, 2=2 songs, etc)
$007    1   BYTE    Starting song (1=1st song, 2=2nd song, etc)
$008    2   WORD    (lo, hi) load address of data ($8000-FFFF)
$00A    2   WORD    (lo, hi) init address of data ($8000-FFFF)
$00C    2   WORD    (lo, hi) play address of data ($8000-FFFF)
$00E    32  STRING  The name of the song, null terminated
$02E    32  STRING  The artist, if known, null terminated
$04E    32  STRING  The copyright holder, null terminated
$06E    2   WORD    (lo, hi) Play speed, in 1/1000000th sec ticks, NTSC (see text)
$070    8   BYTE    Bankswitch init values (see text, and FDS section)
$078    2   WORD    (lo, hi) Play speed, in 1/1000000th sec ticks, PAL (see text)
$07A    1   BYTE    PAL/NTSC bits
                bit 0: if clear, this is an NTSC tune
                bit 0: if set, this is a PAL tune
                bit 1: if set, this is a dual PAL/NTSC tune
                bits 2-7: reserved, must be 0
$07B    1   BYTE    Extra Sound Chip Support
                bit 0: if set, this song uses VRC6 audio
                bit 1: if set, this song uses VRC7 audio
                bit 2: if set, this song uses FDS audio
                bit 3: if set, this song uses MMC5 audio
                bit 4: if set, this song uses Namco 163 audio
                bit 5: if set, this song uses Sunsoft 5B audio
                bit 6: if set, this song uses VT02+ audio
                bit 7: reserved, must be zero
$07C    1   BYTE    Reserved for NSF2
$07D    3   BYTES   24-bit length of contained program data.
                If 0, all data until end of file is part of the program.
                If used, can be used to provide NSF2 metadata
                in a backward compatible way.
"""

NSF_MAGIC = b"NESM\x1a"
MAX_SUPPORTED_VERSION = 2


def read_c_string(buf, strlen=32):
    """reads a null terminated string from a buffer"""
    return buf.read(strlen).decode("ascii").split("\0")[0]


def read_k_byte_int(buf, k):
    """reads a k-byte integer from a buffer"""
    return int.from_bytes(buf.read(k), byteorder="little")


def read_16_bit_word(buf):
    """reads a 16 bit little-endian word from a buffer"""
    return read_k_byte_int(buf, 2)


def read_8_bit_word(buf):
    """reads a 16 bit little-endian word from a buffer"""
    return read_k_byte_int(buf, 1)


class NSF:
    def __init__(self, filename):
        self.filename = filename
        self.file = open(filename, "rb")
        self.header = self.read_header()
        self.is_ntsc = (self.header["pal_ntsc"] & 0x01) == 0
        self.is_pal = not self.is_ntsc
        self.is_dual_pal_ntsc = (self.header["pal_ntsc"] & 0x02) != 0
        self.is_vrc6 = (self.header["extra_sound_chip_support"] & 0x01) != 0
        self.is_vrc7 = (self.header["extra_sound_chip_support"] & 0x02) != 0
        self.is_fds = (self.header["extra_sound_chip_support"] & 0x04) != 0
        self.is_mmc5 = (self.header["extra_sound_chip_support"] & 0x08) != 0
        self.is_namco_163 = (self.header["extra_sound_chip_support"] & 0x10) != 0
        self.is_sunsoft_5b = (self.header["extra_sound_chip_support"] & 0x20) != 0
        self.is_vt02 = (self.header["extra_sound_chip_support"] & 0x40) != 0
        self.file.close()

    def read_header(self):
        """reads and validates the NSF header"""
        header = {}

        # the first five bytes are the magic number
        header["magic"] = self.file.read(5)
        if header["magic"] != NSF_MAGIC:
            raise Exception("Invalid NSF file:  Bad magic number.")

        # the next byte is the version number
        header["version"] = read_8_bit_word(self.file)
        if header["version"] > MAX_SUPPORTED_VERSION:
            raise Exception("Invalid NSF file:  Unsupported version.")

        # the next byte is the number of songs
        header["num_songs"] = read_8_bit_word(self.file)

        # the next byte is the starting song
        header["start_song"] = read_8_bit_word(self.file)

        # the next two bytes are the load address
        header["load_address"] = read_16_bit_word(self.file)

        # the next two bytes are the init address
        header["init_address"] = read_16_bit_word(self.file)

        # the next two bytes are the play address
        header["play_address"] = read_16_bit_word(self.file)

        # the next 32 bytes are the album name
        header["album"] = read_c_string(self.file)

        # the next 32 bytes are the artist name
        header["artist"] = read_c_string(self.file)

        # the next 32 bytes are the copyright holder
        header["copyright"] = read_c_string(self.file)

        # the next two bytes are the play speed
        header["play_speed_ntsc"] = read_16_bit_word(self.file)

        # the next 8 bytes are the bankswitch init values
        header["bankswitch_init"] = self.file.read(8)

        # the next two bytes are the play speed
        header["play_speed_pal"] = read_16_bit_word(self.file)

        # the next byte is the PAL/NTSC bits
        header["pal_ntsc"] = read_8_bit_word(self.file)

        # the next byte is the extra sound chip support
        header["extra_sound_chip_support"] = read_8_bit_word(self.file)

        # the next byte is the reserved byte
        header["reserved"] = read_8_bit_word(self.file)

        # the next 3 bytes are data length
        header["data_length"] = read_k_byte_int(self.file, 3)

        return header

