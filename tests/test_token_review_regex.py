import unittest

from core import token_review


class TokenReviewRegexTests(unittest.TestCase):
    def test_scam_regex_allows_common_latin_diacritics(self) -> None:
        for asset in ("Caf\u00e9", "M\u00fcnchen", "Ni\u00f1o", "Cr\u00e8me Br\u00fbl\u00e9e"):
            with self.subTest(asset=asset):
                self.assertFalse(token_review.is_scam(asset))


if __name__ == "__main__":
    unittest.main()
