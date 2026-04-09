import math

from bitarray import bitarray
from bitarray.util import ba2int, int2ba

_ENCODING_TYPES = frozenset({"naturalOnly", "naturalZero", "integers"})


class OmegaEncoder:

    def _check_type(self, encoding_type: str) -> None:
        if encoding_type not in _ENCODING_TYPES:
            raise ValueError(
                f"Invalid encoding type {encoding_type!r}, "
                f"select from: {', '.join(sorted(_ENCODING_TYPES))}"
            )

    def _to_omega(self, num: int, encoding_type: str) -> int:
        """Map value to the Omega natural domain (all >= 1)."""
        if encoding_type == "naturalOnly":
            return num
        elif encoding_type == "naturalZero":
            return num + 1
        elif encoding_type == "integers":
            # [0, 1, -1, 2, -2] -> [1, 2, 3, 4, 5]
            return abs(2 * num) + (1 if num <= 0 else 0)
        raise ValueError(f"Unknown encoding type: {encoding_type!r}")

    def _from_omega(self, num: int, encoding_type: str) -> int:
        """Inverse of ``_to_omega``."""
        if encoding_type == "naturalOnly":
            return num
        elif encoding_type == "naturalZero":
            return num - 1
        elif encoding_type == "integers":
            # [1, 2, 3, 4, 5] -> [0, 1, -1, 2, -2]
            return math.ceil(num / 2 * (1 if num % 2 == 0 else -1))
        raise ValueError(f"Unknown encoding type: {encoding_type!r}")

    def encode(self, raw_nums: list[int], encoding_type: str) -> bitarray:
        """Encode a list of integers into an Elias Omega encoded bitarray.

        Encoding types:
            'naturalOnly': Integers must be >= 1.
            'naturalZero': Integers must be >= 0.
            'integers': All integers including negatives (less space-efficient).
        """
        self._check_type(encoding_type)
        bits = bitarray()
        for num in raw_nums:
            bits += self._encode_one(self._to_omega(num, encoding_type), bitarray([0]))
        return bits

    def _encode_one(self, num: int, encoded: bitarray) -> bitarray:
        if num < 1:
            raise ValueError(f"Omega encoding requires num >= 1, got {num}")
        if num == 1:
            return encoded
        bit_encoded_num = int2ba(num)
        encoded = bit_encoded_num + encoded
        return self._encode_one(len(bit_encoded_num) - 1, encoded)

    def decode(self, encoded: bitarray, encoding_type: str) -> list[int]:
        """Decode an Elias Omega encoded bitarray into a list of integers."""
        self._check_type(encoding_type)
        raw_nums = []
        offset = 0
        while offset < len(encoded):
            num, offset = self._decode_one(1, encoded, offset)
            raw_nums.append(num)
        return [self._from_omega(num, encoding_type) for num in raw_nums]

    def _decode_one(self, num: int, encoded: bitarray, offset: int) -> tuple[int, int]:
        encoded_slice = encoded[offset : offset + 1 + num]
        if encoded_slice[0] == 0:
            return num, offset + 1
        offset += num + 1
        return self._decode_one(ba2int(encoded_slice), encoded, offset)
