"""Output routing and post-run regressions. Never sleep or shut down the host."""
import ctypes
import inspect
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import ai_translator
import file_operations
import gradio_app
import queue_manager
import utils
import whisper_core
from queue_manager import QueueItem, QueueManager

SRT = "1\n00:00:00,000 --> 00:00:02,000\nHello from the output folder test.\n\n"


class FakeTimer:
    def __init__(self, interval, function, args=()):
        self.interval, self.function, self.args = interval, function, args
        self.cancelled = False
        self.started = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        # Deliberately fire even cancelled timers to exercise the generation guard.
        self.function(*self.args)


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="katav-output-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "Результаты с пробелами עברית"
        self.qm = QueueManager()
        self.qm._items = [QueueItem(1, "file", "sample.wav", str(self.source / "sample.wav"), status="done")]
        for target, kwargs in [
            ("queue_manager.subprocess.run", {"return_value": MagicMock(returncode=0, stdout="", stderr="")}),
            ("queue_manager.threading.Timer", {"side_effect": FakeTimer}),
            ("utils.suspend_windows", {}),
            ("utils.stop_requested", {"new": False}),
            ("gradio_app.batch_queue", {"new": self.qm}),
            ("whisper_core.batch_queue", {"new": self.qm}),
            ("gradio_app.gr.Info", {}),
            ("gradio_app.gr.Warning", {}),
            ("gradio_app.open_output_folder", {}),
        ]:
            mock = self.enterContext(patch(target, **kwargs))
            if target == "utils.suspend_windows": self.suspend = mock
            if target == "queue_manager.subprocess.run": self.run = mock
            if target == "gradio_app.open_output_folder": self.opener = mock

    def result(self):
        self.output.mkdir(exist_ok=True)
        path = self.output / "sample.srt"
        path.write_text(SRT, encoding="utf-8")
        return str(path)

    def arm_sleep(self):
        self.qm.set_power_action("sleep")
        self.qm.enable_shutdown()
        self.qm.check_and_schedule_shutdown()
        return self.qm._sleep_timer

    def test_browse_enables_custom_output(self):
        with patch("gradio_app.open_folder_dialog", return_value=str(self.output)):
            self.assertEqual(gradio_app.select_output_folder("old", False), (str(self.output), True))

    def test_cancel_browse_preserves_selection(self):
        with patch("gradio_app.open_folder_dialog", return_value=""):
            self.assertEqual(gradio_app.select_output_folder("old", True), ("old", True))

    def test_custom_path_normalization_and_validation(self):
        self.assertEqual(utils.get_actual_output_dir("", True, '"' + str(self.output) + '"'), str(self.output))
        with self.assertRaises(ValueError): utils.get_actual_output_dir("", True, " ")
        with self.assertRaises(ValueError): utils.get_actual_output_dir("", True, self.result())

    def test_open_folder_uses_safe_windows_api_and_fallback(self):
        self.result()
        with patch("file_operations.os.startfile") as start:
            file_operations.open_output_folder(str(self.output))
            start.assert_called_once_with(str(self.output))
        with patch("file_operations.os.startfile", side_effect=OSError("failed")), patch("subprocess.Popen") as popen:
            file_operations.open_output_folder(str(self.output))
            popen.assert_called_once_with(["explorer.exe", str(self.output)], shell=False)

    def test_finish_opens_real_result_not_stale_hidden_folder(self):
        result = self.result()
        actual = gradio_app.finish_run(True, "", True, str(self.output), str(self.source), result)
        self.assertEqual(actual, str(self.output))
        self.opener.assert_called_once_with(str(self.output))

    def test_vtt_and_json_download_list_also_opens_results(self):
        self.output.mkdir()
        paths = []
        for name in ("sample.vtt", "sample.json"):
            path = self.output / name
            path.write_text("fixture", encoding="utf-8")
            paths.append(str(path))
        gradio_app.finish_run(True, "", True, str(self.output), "", paths)
        self.opener.assert_called_once_with(str(self.output))

    def test_auto_open_disabled_does_not_disable_power(self):
        self.qm.enable_shutdown()
        gradio_app.finish_run(False, "", True, str(self.output), "", self.result())
        self.opener.assert_not_called()
        self.run.assert_called_once()

    def test_no_results_no_open_no_power(self):
        self.qm.enable_shutdown()
        gradio_app.finish_run(True, "", False, "", str(self.source), "")
        self.opener.assert_not_called()
        self.run.assert_not_called()

    def test_full_cycle_only_arms_after_translation_completion(self):
        result = self.result()
        self.qm.enable_shutdown()
        self.run.assert_not_called()
        gradio_app.finish_run(True, "", True, str(self.output), "", result, "✅ Completed: 1 files.", translation=True)
        self.assertEqual(self.run.call_args.args[0], ["shutdown", "/s", "/t", "60"])
        self.assertNotIn("/f", self.run.call_args.args[0])

    def test_translation_only_can_schedule_without_media_queue(self):
        self.qm._items.clear()
        self.qm.enable_shutdown()
        gradio_app.finish_run(False, "", True, str(self.output), "", self.result(), "✅ Completed: 1 files.", translation=True)
        self.assertTrue(self.qm.is_shutdown_scheduled())

    def test_translation_error_and_cancel_do_not_arm(self):
        for status in ("❌ API CONNECTION ERROR", "⚠️ Completed with errors: 1 files.", "⚠️ Interrupted"):
            self.qm.enable_shutdown()
            gradio_app.finish_run(False, "", True, str(self.output), "", self.result(), status, translation=True)
            self.run.assert_not_called()
        self.qm.enable_shutdown()
        with patch("utils.stop_requested", True):
            gradio_app.finish_run(False, "", True, str(self.output), "", self.result())
        self.run.assert_not_called()

    def test_power_setting_survives_prepare_start_reset(self):
        values = {name: "" for name, p in inspect.signature(gradio_app.prepare_start).parameters.items()
                  if p.default is inspect.Parameter.empty}
        values.update(manual_path_val="", urls_val="", input_files_val=[], output_formats_val=["srt"],
                      power_enabled_val=True, power_mode_val="SLEEP")
        with patch.object(self.qm, "start_duration_probing"):
            gradio_app.prepare_start(**values)
        self.assertTrue(self.qm.is_shutdown_enabled())
        self.assertEqual(self.qm.get_power_action(), "sleep")

    def test_sleep_timer_sixty_seconds_and_correct_dispatch(self):
        timer = self.arm_sleep()
        self.assertEqual(timer.interval, 60.0)
        self.assertTrue(timer.started)
        self.suspend.assert_not_called()
        timer.fire()
        self.suspend.assert_called_once()
        self.assertFalse(self.qm.is_shutdown_scheduled())

    def test_cancel_disable_reset_mode_change_invalidate_old_sleep(self):
        for action in (self.qm.cancel_shutdown, self.qm.disable_shutdown, self.qm.reset,
                       lambda: self.qm.set_power_action("shutdown")):
            self.qm._items = [QueueItem(1, "file", "sample", "sample", status="done")]
            timer = self.arm_sleep()
            action()
            timer.fire()
            self.assertTrue(timer.cancelled)
            self.suspend.assert_not_called()

    def test_schedule_is_idempotent(self):
        self.qm.enable_shutdown()
        self.qm.check_and_schedule_shutdown()
        self.qm.check_and_schedule_shutdown()
        self.run.assert_called_once()

    def test_running_empty_failed_cancelled_batches_are_not_scheduled(self):
        for status in ("queued", "running", "failed"):
            self.qm._items[0].status = status
            self.qm.enable_shutdown()
            self.qm.check_and_schedule_shutdown()
            self.run.assert_not_called()
        self.qm._items.clear()
        self.qm.enable_shutdown()
        self.qm.check_and_schedule_shutdown()
        self.run.assert_not_called()

    def test_cancel_only_aborts_owned_shutdown_and_surfaces_failure(self):
        self.qm.cancel_shutdown()
        self.run.assert_not_called()
        self.qm.enable_shutdown()
        self.qm.check_and_schedule_shutdown()
        self.run.reset_mock()
        self.run.return_value = MagicMock(returncode=1, stdout="", stderr="access denied")
        self.assertIn("access denied", self.qm.cancel_shutdown())
        self.assertTrue(self.qm.is_shutdown_scheduled())
        with self.assertRaises(RuntimeError): self.qm.reset()
        self.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.qm.cancel_shutdown()
        self.assertEqual(self.run.call_args.args[0], ["shutdown", "/a"])
        self.assertFalse(self.qm.is_shutdown_scheduled())

    def test_sleep_api_failure_is_visible(self):
        self.suspend.side_effect = OSError("access denied")
        self.arm_sleep().fire()
        self.assertIn("Sleep failed", self.qm.get_shutdown_status()["message"])
        self.assertFalse(self.qm.is_shutdown_scheduled())

    def test_windows_sleep_api_boolean_signature_and_privilege_cleanup(self):
        # Every WinDLL entrypoint is fake: the machine cannot sleep in this test.
        libs = {name: MagicMock() for name in ("kernel32", "advapi32", "powrprof")}
        libs["kernel32"].GetCurrentProcess.return_value = 1
        for name in ("OpenProcessToken", "LookupPrivilegeValueW", "AdjustTokenPrivileges"):
            getattr(libs["advapi32"], name).return_value = 1
        libs["powrprof"].SetSuspendState.return_value = 1
        # Call the real helper beneath the suite's safety mock, with DLLs replaced.
        with patch("ctypes.WinDLL", side_effect=lambda name, **kw: libs[name]), patch("ctypes.get_last_error", return_value=0):
            # Call the saved real function with every native entrypoint replaced.
            original = self._real_suspend
            original()
        libs["powrprof"].SetSuspendState.assert_called_once_with(False, False, False)
        self.assertEqual(libs["powrprof"].SetSuspendState.restype, ctypes.c_ubyte)
        self.assertEqual(libs["advapi32"].AdjustTokenPrivileges.call_count, 2)
        libs["kernel32"].CloseHandle.assert_called_once()

    def test_transcription_writes_srt_and_clean_txt_to_custom_directory(self):
        source = self.source / "sample.wav"
        source.write_bytes(b"test fixture")
        self.qm._items[0].status = "queued"
        self.qm._items[0].path_or_url = str(source)

        def whisper_process(command, **kwargs):
            dest = Path(command[command.index("--output_dir") + 1])
            self.assertEqual(dest, self.output)
            (dest / "sample.srt").write_text(SRT, encoding="utf-8")
            proc = MagicMock(returncode=0)
            proc.stdout, proc.stderr = io.StringIO(""), io.StringIO("")
            return proc

        values = {name: "" for name, p in inspect.signature(whisper_core.run_transcription).parameters.items()
                  if p.default is inspect.Parameter.empty}
        values.update(input_files=[], manual_path=str(source), urls_input="", output_formats=["srt"],
                      use_custom_output=True, output_dir='"' + str(self.output) + '"',
                      save_audio_track=False, plain_text_output=True, skip_done=False,
                      temperature=0.0, rep_penalty=1.0, beam_size=1, patience=1.0, no_speech_thresh=0.6)
        with patch("whisper_core.subprocess.Popen", side_effect=whisper_process), \
             patch("whisper_core.ui_state.save_settings"), \
             patch("whisper_core.interruptible_sleep", return_value=False), \
             patch("whisper_core._gpu_power_limit_set", return_value=None), \
             patch("whisper_core._gpu_power_limit_restore"), \
             patch("whisper_core.process_active", False):
            result = whisper_core.run_transcription(**values)
        self.assertTrue((self.output / "sample.srt").is_file())
        text = (self.output / "sample_CLEAN.txt").read_text(encoding="utf-8")
        self.assertIn("Hello", text)
        self.assertNotIn("-->", text)
        self.assertFalse((self.source / "sample.srt").exists())
        self.assertEqual(result[-1], str(self.output))
        self.run.assert_not_called()  # no power action at the intermediate stage

    def _native_exit_fixture(self, returncode, completed=True, write=True, content=SRT):
        source = self.source / 'sample.wav'
        source.write_bytes(b'fixture')
        self.output.mkdir(exist_ok=True)
        self.qm._items[0].status = 'queued'
        self.qm.enable_shutdown()
        commands = []
        def process(command, **kwargs):
            commands.append(command)
            if write:
                (self.output / 'sample.srt').write_text(content, encoding='utf-8')
            proc = MagicMock(returncode=returncode)
            proc.stdout = io.StringIO('Operation finished in: 0:00:01\n' if completed else '')
            proc.stderr = io.StringIO('EOI missing, emulating\n')
            return proc
        values = {name: '' for name, p in inspect.signature(whisper_core.run_transcription).parameters.items()
                  if p.default is inspect.Parameter.empty}
        values.update(input_files=[], manual_path=str(source), urls_input='', output_formats=['srt'],
                      use_custom_output=True, output_dir=str(self.output), plain_text_output=True,
                      save_audio_track=False, skip_done=False, temperature=0.0, rep_penalty=1.0,
                      beam_size=1, patience=1.0, no_speech_thresh=0.6,
                      vad_method='No VAD', use_vad_filter=False)
        with patch('whisper_core.subprocess.Popen', side_effect=process), \
             patch('whisper_core.ui_state.save_settings'), \
             patch('whisper_core.interruptible_sleep', return_value=False), \
             patch('whisper_core._gpu_power_limit_set', return_value=None), \
             patch('whisper_core._gpu_power_limit_restore'), \
             patch('whisper_core.process_active', False), \
             patch('whisper_core.stop_requested', False):
            result = whisper_core.run_transcription(**values)
        gradio_app.finish_run(True, '', True, str(self.output), result[-1], result[1]['value'])
        self.run.assert_not_called()
        self.suspend.assert_not_called()
        self.assertEqual(commands[0][commands[0].index('--vad_filter') + 1], 'False')
        self.assertEqual(self.qm._items[0].status, 'failed')
        return result

    def test_native_teardown_preserves_completed_fresh_results_without_power(self):
        result = self._native_exit_fixture(0xc0000409)
        self.assertIn(str(self.output / 'sample.srt'), result[3])
        self.assertTrue((self.output / 'sample_CLEAN.txt').is_file())
        self.assertIn('Hello', result[0]['value'])
        self.assertIn('status-error', result[2]['elem_classes'])
        self.opener.assert_called_once_with(str(self.output))

    def test_arbitrary_nonzero_exit_is_not_recovered(self):
        result = self._native_exit_fixture(1)
        self.assertEqual(result[3], '')
        self.assertEqual(result[1]['value'], [])
        self.opener.assert_not_called()

    def test_native_failure_without_completion_marker_is_not_recovered(self):
        result = self._native_exit_fixture(0xc0000409, completed=False)
        self.assertEqual(result[3], '')

    def test_native_failure_does_not_recover_stale_files(self):
        self.result()
        result = self._native_exit_fixture(0xc0000409, write=False)
        self.assertEqual(result[3], '')
        self.assertFalse((self.output / 'sample_CLEAN.txt').exists())

    def test_native_failure_does_not_recover_malformed_subtitles(self):
        result = self._native_exit_fixture(0xc0000409, content='1\n00:00:00,000 -->\ntruncated')
        self.assertEqual(result[3], '')

    def test_recovery_requires_every_requested_format(self):
        path = self.result()
        self.assertFalse(whisper_core._recoverable_completed_outputs(0xc0000409, True, [path], {}, ['srt', 'txt']))
        self.assertFalse(whisper_core._recoverable_completed_outputs(0xc0000409, True, [path], {}, ['json']))
        self.assertTrue(whisper_core._recoverable_completed_outputs(-1073740791, True, [path], {}, ['srt']))

    def test_translation_routes_subtitles_and_plain_text_not_to_source_or_stale_folder(self):
        source = self.source / "lesson.srt"
        source.write_text(SRT, encoding="utf-8")
        response = MagicMock()
        response.choices[0].message.content = SRT.replace("Hello", "Привет")
        client = MagicMock()
        client.chat.completions.create.return_value = response
        with patch("ai_translator.OpenAI", return_value=client), patch("ai_translator.OPENAI_READY", True), \
             patch("ai_translator.ui_state.save_settings"), patch("ai_translator._save_last_model"), \
             patch("ai_translator.CONFIG_FILE", str(self.root / "test-keys.json")), \
             patch("utils.interruptible_sleep", return_value=False):
            result = ai_translator.translate_content("Mistral", "fixture-key", ["Russian"], "fixture-model", "",
                [], str(source), str(self.source), "", "Files", "", True, "en", True, True, str(self.output))
        self.assertTrue(result[0].startswith("✅ Completed:"), result[0])
        paths = [Path(p) for p in result[2].split("|")]
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(p.parent == self.output and p.is_file() for p in paths))
        self.assertTrue(any(p.name.endswith("_CLEAN.txt") for p in paths))
        self.assertFalse((self.source / "lesson_TRANSLATED_RU.srt").exists())
        self.run.assert_not_called()

    def test_plain_text_translation_uses_selected_folder(self):
        response = MagicMock()
        response.choices[0].message.content = "Переведённый текст"
        client = MagicMock()
        client.chat.completions.create.return_value = response
        with patch("ai_translator.OpenAI", return_value=client), patch("ai_translator.OPENAI_READY", True), \
             patch("ai_translator.ui_state.save_settings"), patch("ai_translator._save_last_model"), \
             patch("ai_translator.CONFIG_FILE", str(self.root / "fixture-keys.json")):
            result = ai_translator.translate_content("Mistral", "fixture-key", ["Russian"], "fixture-model", "",
                [], "", str(self.source), "", "Text", "Hello world", True, "en", False, True, str(self.output))
        self.assertTrue(result[0].startswith("✅ Completed:"), result[0])
        self.assertEqual(Path(result[2]).parent, self.output)
        self.assertTrue(Path(result[2]).is_file())


CompletionTests._real_suspend = staticmethod(utils.suspend_windows)

if __name__ == "__main__":
    unittest.main(verbosity=2)
