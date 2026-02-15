"""
Mode-S CRC-24.

Polinom: x^24 + x^23 + x^22 + x^21 + x^20 + x^19 + x^18 + x^17 + x^16 + x^15
       + x^14 + x^13 + x^12 + x^10 + x^3 + 1
       = 0x1FFF409   (25 bit, x^24 dahil)

Yontem: en yuksek bitten basla, 1 ise polinomu o bit konumuyla
hizalayip XOR'la. Sonunda alttaki 24 bit "residue" kalir.

DF11/DF17/DF18 icin parite alani = saf CRC, dolayisiyla compute(msg) == 0
ise gecerli.
DF4/5/20/21 icin parite = CRC XOR ICAO; bu v1'de desteklenmiyor.
"""

GENERATOR = 0x1FFF409  # 25-bit polinom (x^24 dahil)


def compute(msg_bytes: bytes) -> int:
    """
    14-byte (uzun, 112-bit) veya 7-byte (kisa, 56-bit) Mode-S mesajin
    CRC residue degerini dondurur.

    Gecerli DF17 mesaji icin sonuc = 0 olmalidir.
    """
    n_bits = len(msg_bytes) * 8
    data = int.from_bytes(msg_bytes, 'big')
    # mesajin son 24 biti CRC alani; veri bitleri n_bits-24 tane
    for i in range(n_bits - 24):
        bit_pos = n_bits - 1 - i
        if (data >> bit_pos) & 1:
            # 25-bit generator'in MSB'sini bit_pos'a hizala
            data ^= GENERATOR << (bit_pos - 24)
    return data & 0xFFFFFF


def is_valid_df17(msg_bytes: bytes) -> bool:
    """DF17 mesajin CRC'si dogru mu?"""
    if len(msg_bytes) != 14:
        return False
    df = (msg_bytes[0] >> 3) & 0x1F
    if df != 17:
        return False
    return compute(msg_bytes) == 0
