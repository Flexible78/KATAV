"""Offline subtitle batching regressions; no API keys, network or power actions."""
import unittest
from srt_processor import chunk_text, validate_srt_translation


def subtitles(count):
    return '\n\n'.join(f'{i}\n00:00:00,000 --> 00:00:02,000\nSubtitle {i}.\nSecond line.' for i in range(1, count + 1))


class SubtitleChunkTests(unittest.TestCase):
    def test_translation_preserves_all_cues_and_accepts_srt_fence(self):
        source = subtitles(51)
        translated = source.replace('Subtitle', 'Translated subtitle')
        self.assertEqual(validate_srt_translation(source, '```srt\n' + translated + '\n```'), translated)

    def test_translation_rejects_missing_reordered_or_changed_cues(self):
        source = subtitles(3)
        cues = source.split('\n\n')
        for bad in ('\n\n'.join(cues[:2]), '\n\n'.join(reversed(cues)),
                    source.replace('00:00:02,000', '00:00:03,000', 1),
                    source + '\n\n' + cues[-1], 'Commentary\n' + source):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_srt_translation(source, bad)

    def test_index_timestamp_and_multiline_text_stay_together(self):
        chunks = chunk_text(subtitles(51), 24, max_chars=3000)
        self.assertEqual(len(chunks), 3)
        blocks = [block for chunk in chunks for block in chunk]
        self.assertEqual(len(blocks), 51)
        for i, block in enumerate(blocks, 1):
            self.assertTrue(block.startswith(f'{i}\n00:00:00,000 -->'))
            self.assertIn('Second line.', block)
        self.assertEqual('\n\n'.join(blocks), subtitles(51))

    def test_numeric_subtitle_text_is_not_an_index(self):
        text = '1\n00:00:00,000 --> 00:00:02,000\n2026\n\n2\n00:00:02,000 --> 00:00:04,000\nNext.'
        self.assertEqual(chunk_text(text, 1), [[text.split('\n\n')[0]], [text.split('\n\n')[1]]])

    def test_crlf_and_bom_are_supported(self):
        self.assertEqual(chunk_text('\ufeff' + subtitles(2).replace('\n', '\r\n'), 24), [subtitles(2).split('\n\n')])

    def test_character_limit_preserves_every_cue(self):
        chunks = chunk_text(subtitles(20), 24, max_chars=200)
        self.assertTrue(all(len('\n\n'.join(chunk)) <= 200 for chunk in chunks))
        self.assertEqual('\n\n'.join(block for chunk in chunks for block in chunk), subtitles(20))

    def test_single_oversized_cue_is_not_split(self):
        cue = '1\n00:00:00,000 --> 00:00:02,000\n' + 'x' * 500
        self.assertEqual(chunk_text(cue, 24, max_chars=100), [[cue]])

    def test_plain_text_paragraphs_and_empty_input(self):
        self.assertEqual(chunk_text('one\n\ntwo\n\nthree', 2, True), [['one', 'two'], ['three']])
        self.assertEqual(chunk_text('', 24), [])
        with self.assertRaises(ValueError):
            chunk_text('anything', 0)


if __name__ == '__main__':
    unittest.main()
