#!/usr/bin/env python3
"""Set the regulatory country in an ath10k (QCA6174) board data file.

The Galaxy Tab S3's Wi-Fi board data (Android's bdwlan30.bin, ath10k's
board.bin) carries country GB (regDmn 0x833a).  ath10k passes that country
to cfg80211 as the driver's hint, and cfg80211 never lets a user setting
(iw reg set, /etc/conf.d/wireless-regdom) go above the driver's limits, so
the radio stays on GB rules wherever you are.

This rewrites regDmn[0] to 0x8000 | <ISO 3166-1 numeric code> (the ath
country table uses ISO numeric codes: 76 Brazil, 840 United States,
826 United Kingdom, 276 Germany, ...) and fixes the header checksum, so that
the 16-bit XOR of the whole file stays 0xffff.  Nothing else changes.

usage: ath10k-board-country.py <board.bin> <out.bin> <iso-numeric-code>
"""
import struct
import sys

COUNTRY_ERD_FLAG = 0x8000
REGDMN_OFFSET = 12
CHECKSUM_OFFSET = 2


def xor16(data):
    x = 0
    for i in range(0, len(data) - 1, 2):
        x ^= struct.unpack_from("<H", data, i)[0]
    return x


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__.strip().splitlines()[-1])
    src, dst, code = sys.argv[1], sys.argv[2], int(sys.argv[3], 0)
    if not 0 < code < 1000:
        sys.exit("country code must be an ISO 3166-1 numeric code (1-999)")
    b = bytearray(open(src, "rb").read())
    length = struct.unpack_from("<H", b, 0)[0]
    if length != len(b) or len(b) % 2:
        sys.exit("%s: header length %d does not match file size %d" % (src, length, len(b)))
    if xor16(b) != 0xFFFF:
        sys.exit("%s: checksum does not verify (xor 0x%04x), not a board data file?" % (src, xor16(b)))
    old_rd = struct.unpack_from("<H", b, REGDMN_OFFSET)[0]
    new_rd = COUNTRY_ERD_FLAG | code
    old_cs = struct.unpack_from("<H", b, CHECKSUM_OFFSET)[0]
    new_cs = old_cs ^ old_rd ^ new_rd
    struct.pack_into("<H", b, REGDMN_OFFSET, new_rd)
    struct.pack_into("<H", b, CHECKSUM_OFFSET, new_cs)
    assert xor16(b) == 0xFFFF
    open(dst, "wb").write(b)
    print("regDmn 0x%04x -> 0x%04x, checksum 0x%04x -> 0x%04x" % (old_rd, new_rd, old_cs, new_cs))


if __name__ == "__main__":
    main()
