"""Offline regression tests: never read clipboard, contact clouds, or invoke power actions."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')
import config
from source_inputs import classify_sources, merge_paths
from ui_manager import UIStateManager, TRANSIENT_SOURCE_KEYS
import ai_translator
import gradio_app
import file_operations


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.media = self.root / 'Тест עברית audio.wav'
        self.document = self.root / 'subtitle.srt'
        self.media.write_bytes(b'test')
        self.document.write_text('sample', encoding='utf-8')

    def test_mixed_quoted_paths_and_links(self):
        result = classify_sources(f'"{self.media}" | "{self.document}"\nhttps://youtu.be/abc')
        self.assertEqual(result['media'], [str(self.media)])
        self.assertEqual(result['documents'], [str(self.document)])
        self.assertEqual(result['urls'], ['https://youtu.be/abc'])
        self.assertFalse(result['errors'])

    def test_directory_routes_both_types(self):
        result = classify_sources(str(self.root))
        self.assertEqual(len(result['media']), 1)
        self.assertEqual(len(result['documents']), 1)

    def test_upload_name_and_string(self):
        result = classify_sources(files=[SimpleNamespace(name=str(self.media)), str(self.document)])
        self.assertEqual(len(result['media']), 1)
        self.assertEqual(len(result['documents']), 1)

    def test_deduplicate_same_file(self):
        result = classify_sources(f'{self.media}\n{self.media}', [str(self.media)])
        self.assertEqual(len(result['media']), 1)
        self.assertEqual(merge_paths(str(self.media), [str(self.media)]), str(self.media))

    @unittest.skipUnless(os.name == 'nt', 'Windows identity semantics')
    def test_case_insensitive_windows_merge(self):
        self.assertEqual(merge_paths(str(self.media), [str(self.media).upper()]), str(self.media))

    def test_file_uri_unicode(self):
        self.assertEqual(classify_sources(self.media.as_uri())['media'], [str(self.media)])

    def test_unsupported_and_missing_are_rejected(self):
        other = self.root / 'unsafe.exe'
        other.write_bytes(b'not executable')
        result = classify_sources(f'{other}\n{self.root / "absent.mp3"}')
        self.assertEqual(len(result['errors']), 2)
        self.assertFalse(result['media'])

    def test_spotify_is_rejected(self):
        self.assertTrue(classify_sources('https://open.spotify.com/track/abc')['errors'])

    def test_malformed_url_does_not_crash(self):
        for url in ('https://[bad', 'http://localhost:bad/x', 'https://'):
            with self.subTest(url=url):
                self.assertTrue(classify_sources(url)['errors'])

    def test_playlist_auto_routing_and_url_dedup(self):
        with patch.object(gradio_app.batch_queue, 'get_items', return_value=[]), patch.object(gradio_app.utils, 'process_active', False):
            output = gradio_app.add_smart_sources('https://youtube.com/playlist?list=PL123\nhttps://youtu.be/abc', '', '', '')
            second = gradio_app.add_smart_sources('https://youtube.com/watch?v=abc', *output[:3])
        self.assertEqual(len(second[0].splitlines()), 2)
        self.assertEqual(output[3], '')

    def test_clipboard_filedrop_has_priority(self):
        with patch.object(gradio_app, 'read_clipboard_sources', return_value={'files': [str(self.media)], 'text': 'ignored'}):
            result = gradio_app.paste_smart_sources('', '', '')
        self.assertEqual(result[1], str(self.media))
        self.assertEqual(result[3], '')

    def test_clipboard_text_fallback(self):
        with patch.object(gradio_app, 'read_clipboard_sources', return_value={'files': [], 'text': str(self.document)}):
            result = gradio_app.paste_smart_sources('', '', '')
        self.assertEqual(result[2], str(self.document))

    def test_status_never_reveals_names_or_paths(self):
        with patch.object(gradio_app.gr, 'Warning'):
            result = gradio_app.add_smart_sources(str(self.root / 'secret-name.exe'), '', '', '')
        self.assertNotIn('secret-name', result[4])
        self.assertNotIn(str(self.root), result[4])

    def test_drop_area_shows_names_without_full_paths(self):
        rendered = gradio_app.render_source_names('', str(self.media), str(self.document))
        self.assertIn(self.media.name, rendered)
        self.assertIn(self.document.name, rendered)
        self.assertNotIn(str(self.root), rendered)
        self.assertEqual(gradio_app.render_source_names('', '', ''), '')

    def test_source_names_are_html_escaped(self):
        rendered = gradio_app.render_source_names('', r'C:\audio\<script>.wav', '')
        self.assertIn('&lt;script&gt;.wav', rendered)
        self.assertNotIn('<script>', rendered)

    def test_source_names_are_clickable_without_exposing_paths(self):
        rendered = gradio_app.render_source_names('', str(self.media), str(self.document))
        self.assertIn('data-source-index="0"', rendered)
        self.assertIn('data-source-index="1"', rendered)
        self.assertIn('type="button"', rendered)
        self.assertNotIn(str(self.root), rendered)

    def test_generated_results_are_not_input_documents(self):
        rendered, status = gradio_app.refresh_source_display('', str(self.media), '', [str(self.document)])
        self.assertIn('RESULT', rendered)
        self.assertIn('0 documents', status)
        self.assertIn('1 results', status)
        self.assertNotIn('DOCUMENT</span>', rendered)

    def test_click_opens_only_selected_session_source(self):
        with patch.object(gradio_app, 'open_source_file') as opener:
            gradio_app.open_selected_source('1:123', '', str(self.media), str(self.document))
        opener.assert_called_once_with(str(self.document))

    def test_invalid_click_cannot_open_arbitrary_path(self):
        with patch.object(gradio_app, 'open_source_file') as opener, patch.object(gradio_app.gr, 'Warning'):
            for token in ('-1', '99', str(self.document), '0;command'):
                gradio_app.open_selected_source(token, '', str(self.media), '')
        opener.assert_not_called()

    def test_native_source_open_rejects_executables(self):
        with self.assertRaises(ValueError), patch('file_operations.os.startfile') as opener:
            file_operations.open_source_file(str(self.root / 'unsafe.exe'))
        opener.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows file association')
    def test_native_source_open_uses_file_association(self):
        with patch('file_operations.os.startfile') as opener:
            self.assertEqual(file_operations.open_source_file(str(self.document)), self.document.name)
        opener.assert_called_once_with(str(self.document))


class SettingsTests(unittest.TestCase):
    def test_history_migration_and_preferences_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'settings.json'
            path.write_text(json.dumps({**{key: 'private source' for key in TRANSIENT_SOURCE_KEYS}, 'whisper_output_dir': 'keep', 'trans_model': 'keep-model'}), encoding='utf-8')
            manager = UIStateManager(str(path))
            manager.save_settings({'whisper_manual_path': 'new private file', 'trans_srt_path': 'new document', 'whisper_urls': 'new link', 'compute_type': 'int8'})
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertFalse(TRANSIENT_SOURCE_KEYS.intersection(saved))
            self.assertEqual(saved['whisper_output_dir'], 'keep')
            self.assertEqual(saved['trans_model'], 'keep-model')
            self.assertEqual(saved['compute_type'], 'int8')

    def test_non_object_settings_recover(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'settings.json'
            path.write_text('[]', encoding='utf-8')
            self.assertEqual(UIStateManager(str(path)).settings, {})


class ProviderTests(unittest.TestCase):
    def test_fast_translation_model_replaces_only_moderation_default(self):
        self.assertEqual(gradio_app.preferred_translation_model('Groq (OSS 120b)', 'openai/gpt-oss-safeguard-20b'), 'openai/gpt-oss-20b')
        self.assertEqual(gradio_app.preferred_translation_model('Groq (OSS 120b)', 'openai/gpt-oss-120b'), 'openai/gpt-oss-120b')
        self.assertEqual(gradio_app.preferred_translation_model('Mine', 'my-model'), 'my-model')

    def test_url_validation(self):
        for url in ('ftp://localhost/v1', 'http://user:secret@localhost/v1', 'https://host/v1?key=secret', 'http://host:bad', 'https://host/v1/chat/completions'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                config.validate_provider_url(url)
        self.assertEqual(config.validate_provider_url(' http://127.0.0.1:1234/v1/ '), 'http://127.0.0.1:1234/v1')

    def test_registry_preserves_key_models_and_other_providers(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(config, 'CUSTOM_PROVIDERS_FILE', str(Path(temporary) / 'providers.json')):
            config.save_custom_provider('Mine', 'http://localhost:1234/v1', 'private', ['a', 'a'])
            config.save_custom_provider('Other', 'http://localhost:1235/v1', 'other', ['b'])
            config.save_custom_provider('mine', 'http://localhost:1236/v1')
            self.assertEqual(config.custom_provider_names(), ['Mine', 'Other'])
            self.assertEqual(config.get_custom_provider('Mine')['api_key'], 'private')
            self.assertEqual(config.get_custom_provider('Mine')['models'], ['a'])
            self.assertTrue(config.delete_custom_provider('Mine'))
            self.assertEqual(config.custom_provider_names(), ['Other'])

    def test_builtin_collision_rejected(self):
        with self.assertRaises(ValueError):
            config.save_custom_provider('openrouter', 'http://localhost/v1')

    def test_error_redaction(self):
        secret = 'SECRET-DO-NOT-PRINT'
        error = RuntimeError(secret)
        self.assertNotIn(secret, ai_translator._provider_error(error))
        error.status_code = 401
        self.assertIn('Authentication', ai_translator._provider_error(error))

    def test_inference_health_uses_selected_model_without_persistence(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.chat.completions.create.return_value = SimpleNamespace(choices=[object()])
        with patch.object(ai_translator, '_health_client', return_value=client), patch.object(ai_translator, '_save_last_model') as save:
            result = ai_translator.check_api('Google Studio (Gemma 4)', 'private', 'models/example', persist=False)
        self.assertTrue(result.startswith('✅'))
        self.assertEqual(client.chat.completions.create.call_args.kwargs['model'], 'example')
        save.assert_not_called()

    def test_missing_model_is_not_reported_alive(self):
        self.assertTrue(ai_translator.check_api('OpenRouter', 'private', 'auto', persist=False).startswith('❌'))

    def test_health_clients_are_bounded(self):
        with patch.object(ai_translator, 'OpenAI') as client:
            ai_translator._health_client('OpenRouter', 'private')
        self.assertEqual(client.call_args.kwargs['max_retries'], 0)
        self.assertEqual(client.call_args.kwargs['timeout'], 30)


class WiringTests(unittest.TestCase):
    def test_unified_controls_and_clear(self):
        app = gradio_app.build_app()
        visible = [block for block in app.blocks.values() if getattr(block, 'visible', False)]
        self.assertEqual(sum(getattr(block, 'value', None) == 'PASTE' for block in visible), 1)
        self.assertEqual(sum(getattr(block, 'value', None) == 'CLEAR' for block in visible), 1)
        for block in visible:
            if getattr(block, 'label', '') in ('LINKS / PLAYLISTS', 'MEDIA FILES', 'DOCUMENTS TO TRANSLATE'):
                self.assertEqual(block.value, '')
        clear = next(block for block in visible if getattr(block, 'elem_id', None) == 'clear_media_btn')
        handler = next(fn for fn in app.fns.values() if any(target[0] == clear._id for target in fn.targets))
        self.assertEqual(handler.fn(), ('', '', None, '', '', None, None, '', 'No sources added', '', []))
        self.assertFalse(any(getattr(block, 'value', '') == 'SIGN IN TO GOOGLE' for block in visible))
        documents = next(block for block in app.blocks.values() if getattr(block, 'label', '') == 'DOCUMENTS TO TRANSLATE')
        translators = [fn for fn in app.fns.values() if fn.fn is ai_translator.translate_content]
        self.assertTrue(translators)
        self.assertTrue(all(documents in fn.inputs for fn in translators))


if __name__ == '__main__':
    unittest.main(verbosity=2)
