"""Windows' sound output devices as the Sound page and --sound-devices list them (client/sound_devices.py)."""

import unittest

from opendmt3.client import sound_devices


class ListedTest(unittest.TestCase):
    def test_devices_by_guid_and_the_default_left_out(self):
        def directsound(take):
            # DirectSound's first entry has no GUID (the default output), then each device's GUID structure.
            take(None, "Primary Sound Driver", "")
            take(bytes.fromhex("0a000000" "0000" "0000" "00000000000000" "0b"), "Speakers (USB)", "{0.0.0}")
            take(bytes(range(16)), "Headphones", "{0.0.1}")
        found = sound_devices.listed(directsound)
        # The structure's first three parts are kept low byte first; the text writes them high byte first.
        self.assertEqual(found, [("{0000000A-0000-0000-0000-00000000000B}", "Speakers (USB)"),
                                 ("{03020100-0504-0706-0809-0A0B0C0D0E0F}", "Headphones")])

    def test_a_chosen_device_that_is_gone(self):
        devices = [("{0000000A-0000-0000-0000-00000000000B}", "Speakers")]
        self.assertFalse(sound_devices.chosen_is_gone("{0000000a-0000-0000-0000-00000000000b}", devices, windows=True))
        self.assertTrue(sound_devices.chosen_is_gone("{11111111-0000-0000-0000-000000000000}", devices, windows=True))
        # Unplugged with nothing else: gone as well.
        self.assertTrue(sound_devices.chosen_is_gone("{11111111-0000-0000-0000-000000000000}", [], windows=True))
        # The default is never gone, and off Windows nothing is listed, so nothing is said.
        self.assertFalse(sound_devices.chosen_is_gone("default", [], windows=True))
        self.assertFalse(sound_devices.chosen_is_gone("{11111111-0000-0000-0000-000000000000}", [], windows=False))


if __name__ == "__main__":
    unittest.main()
