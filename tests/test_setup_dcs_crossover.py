"""Isolated fixtures for the combined setup. Never start Wine or touch a live bottle."""

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shlex
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setup_dcs_crossover as setup


def font_bytes(name='Segoe UI Symbol'):
    name = name.encode('utf-16-be')
    table = struct.pack('>HHH', 0, 1, 18) + struct.pack('>HHHHHH', 3, 1, 0x409, 1, len(name), 0) + name
    return (struct.pack('>IHHHH', 0x10000, 1, 0, 0, 0)
            + struct.pack('>4sIII', b'name', 0, 28, len(table)) + table)


def slot_source(newline=b'\n'):
    return (b"local voice_chat = base.safe_require('VoiceChat')\n"
            b'function onPlayerChangeSlot(id)\n'
            + setup.SLOT_BODY + b'\n\t\tvoice_chat.changeSlot(1, id)\n\tend\nend\n'
            b'-- unrelated trailing content\n').replace(b'\n', newline)


class MultiplayerTests(unittest.TestCase):
    def test_guard_preserves_original_content_and_line_endings(self):
        for newline in (b'\n', b'\r\n'):
            with self.subTest(newline=newline):
                original = slot_source(newline)
                modified = setup.patch_multiplayer(original)
                guard = setup.SLOT_GUARD.replace(b'\n', newline)
                self.assertEqual(modified.replace(guard, b'', 1), original)
                self.assertEqual(modified.count(guard), 1)
                self.assertEqual(setup.patch_multiplayer(modified), modified)

    def test_unknown_and_duplicate_callbacks_are_rejected(self):
        for data in (slot_source().replace(setup.SLOT_SIGNATURE, b'function changed(id)'),
                     slot_source() + slot_source(),
                     slot_source().replace(setup.SLOT_BODY, b'\tnew_implementation()'),
                     slot_source().replace(b"base.safe_require('VoiceChat')", b'other_module()')):
            with self.subTest(data=data[:60]):
                with self.assertRaises(setup.SetupError):
                    setup.patch_multiplayer(data)

    def test_changed_body_is_rejected_even_when_guard_already_exists(self):
        data = setup.patch_multiplayer(slot_source()).replace(setup.SLOT_BODY, b'\tnew_implementation()')
        with self.assertRaises(setup.SetupError):
            setup.patch_multiplayer(data)


class FontTests(unittest.TestCase):
    def test_genuine_family_name_required(self):
        setup.validate_apache_font(font_bytes())
        for data in (b'not a font', font_bytes('Arial'), font_bytes()[:20],
                     font_bytes().replace(b'\x00\x00\x00\x1c', b'\x7f\xff\xff\xff', 1)):
            with self.subTest(data=data[:12]):
                with self.assertRaises(setup.SetupError):
                    setup.validate_apache_font(data)

    def test_no_office_source_fails_with_actionable_option(self):
        with patch.object(Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(setup.SetupError, '--font'):
                setup.local_apache_font()


class BottleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dcs-combined-', dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Bottle with spaces'
        self.game = self.root / 'drive_c/Program Files/Eagle Dynamics/DCS World'
        self.profile = self.root / 'drive_c/users/crossover/Saved Games/DCS'
        self.font = self.root / 'drive_c/windows/Fonts/seguisym.ttf'
        self.source = Path(self.temp.name) / 'source font.ttf'
        self.source.write_bytes(font_bytes())
        self.multiplayer = self.game / setup.MULTIPLAYER_FILE
        for path in (self.game / 'bin', self.multiplayer.parent, self.profile / 'Config', self.font.parent):
            path.mkdir(parents=True, exist_ok=True)
        (self.game / 'bin/DCS.exe').write_bytes(b'fixture; never execute')
        self.renderer = self.game / 'bin/dx11backend.dll'
        self.renderer_original = b'fixture renderer' + b'\0' * (setup.D3DM_OFFSET - 16) + setup.D3DM_ORIGINAL_BYTES + b'end'
        self.renderer_patched = (self.renderer_original[:setup.D3DM_OFFSET] + setup.D3DM_PATCHED_BYTES
                                 + self.renderer_original[setup.D3DM_OFFSET + len(setup.D3DM_ORIGINAL_BYTES):])
        self.renderer.write_bytes(self.renderer_original)
        for name, data in (('D3DM_ORIGINAL_SHA256', self.renderer_original),
                           ('D3DM_PATCHED_SHA256', self.renderer_patched)):
            override = patch.object(setup, name, hashlib.sha256(data).hexdigest())
            override.start()
            self.addCleanup(override.stop)
        self.multiplayer.write_bytes(slot_source(b'\r\n'))
        self.options = self.profile / 'Config/options.lua'
        self.original_options = ('-- preserve this comment\r\noptions = {\r\n'
                                 '  ["graphics"] = {["width"] = 1234},\r\n'
                                 '  ["miscellaneous"] = {["unrelated"] = true},\r\n}\r\n')
        self.options.write_bytes(self.original_options.encode())
        (self.root / 'cxbottle.conf').write_text('[Bottle]\n"Template" = "win10_64"\n')
        (self.root / 'user.reg').write_bytes(setup.registry_document(
            {k: '"' + v + '"' for k, v in setup.OVERRIDES.items()}).replace(
                setup.FULL_OVERRIDE_KEY.encode('utf-16-le'),
                r'Software\Wine\DllOverrides'.encode('utf-16-le')))
        self.args = argparse.Namespace(bottle=str(self.root), crossover='/nonexistent/CrossOver.app',
                                       game_dir=None, profile=None, font=str(self.source), graphics='dxmt')
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def instance(self):
        instance = setup.Setup(self.args)
        instance.wine = unittest.mock.Mock(side_effect=AssertionError('Wine must not run in fixtures'))
        instance.overrides = unittest.mock.Mock()  # Existing override code is not the change under test.
        return instance

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def configured(self):
        instance = self.instance()
        instance.configure()
        return instance

    def test_combined_configuration_and_manifest(self):
        instance = self.configured()
        self.assertEqual(self.font.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.multiplayer.read_bytes(), setup.patch_multiplayer(slot_source(b'\r\n')))
        options = self.options.read_bytes().decode()
        self.assertIn('-- preserve this comment\r\n', options)
        self.assertIn('["width"] = 1234', options)
        self.assertIn('["unrelated"] = true', options)
        records = json.loads((instance.backup / 'manifest.json').read_text())['files']
        by_path = {r['path']: r for r in records}
        self.assertTrue(by_path[str(self.font)]['created'])
        record = by_path[str(self.multiplayer)]
        self.assertEqual((instance.backup / record['backup']).read_bytes(), slot_source(b'\r\n'))

    def test_second_configuration_does_not_rewrite_or_duplicate_fixes(self):
        self.configured()
        before = self.snapshot()
        instance = self.configured()
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(instance.backup)

    def test_preinstalled_font_with_different_filename_case_is_preserved(self):
        existing = self.font.with_name('SEGUISYM.TTF')
        existing.write_bytes(font_bytes())
        self.args.font = '/nonexistent/should not be used.ttf'
        self.configured()
        self.assertEqual([p.name for p in self.font.parent.iterdir()], ['SEGUISYM.TTF'])
        self.instance().undo_compatibility()
        self.assertEqual(existing.read_bytes(), font_bytes())

    def test_invalid_font_or_unknown_lua_aborts_before_configuration(self):
        for bad in ('font', 'lua', 'options'):
            with self.subTest(bad=bad):
                originals = self.source.read_bytes(), self.multiplayer.read_bytes(), self.options.read_bytes()
                if bad == 'font':
                    self.source.write_bytes(font_bytes('Wrong family'))
                elif bad == 'lua':
                    self.multiplayer.write_bytes(b'unsupported lua version')
                else:
                    self.options.write_text('options = { broken')
                before = self.snapshot()
                instance = self.instance()
                with self.assertRaises(setup.SetupError):
                    instance.configure()
                self.assertEqual(self.snapshot(), before)
                instance.overrides.assert_not_called()
                self.source.write_bytes(originals[0])
                self.multiplayer.write_bytes(originals[1])
                self.options.write_bytes(originals[2])

    def test_linked_font_is_rejected_without_overwriting_destination(self):
        self.font.symlink_to(self.source)
        with self.assertRaises(setup.SetupError):
            self.configured()
        self.assertEqual(self.source.read_bytes(), font_bytes())

    def test_read_only_check_requires_both_fixes_and_never_launches_processes(self):
        self.configured()
        with patch.object(setup, 'dependency_problems', return_value=[]), \
             patch.object(setup.subprocess, 'run', side_effect=AssertionError('Must be read-only')):
            before = self.snapshot()
            self.assertEqual(self.instance().check(), 0)
            self.assertEqual(self.snapshot(), before)
            self.font.unlink()
            self.assertEqual(self.instance().check(), 1)
            self.font.write_bytes(font_bytes())
            self.multiplayer.write_bytes(slot_source())
            self.assertEqual(self.instance().check(), 1)

    def test_cli_check_and_preview_do_not_launch_processes_or_change_files(self):
        self.configured()
        before = self.snapshot()
        with patch.object(setup, 'dependency_problems', return_value=[]), \
             patch.object(setup.subprocess, 'run', side_effect=AssertionError('Must be read-only')):
            for mode in ('--check', '--dry-run'):
                self.assertEqual(setup.main(['--bottle', str(self.root), '--graphics', 'dxmt', mode]), 0)
        self.assertEqual(self.snapshot(), before)

    def run_main_configuration(self, install=False):
        crossover = Path(self.temp.name) / 'Fixture CrossOver.app'
        runtime = crossover / 'Contents/SharedSupport/CrossOver/bin'
        runtime.mkdir(parents=True, exist_ok=True)
        for name in ('wine', 'cxbottle', 'cabextract'):
            (runtime / name).write_bytes(b'fixture; never execute')
        arguments = ['--bottle', str(self.root), '--crossover', str(crossover), '--font', str(self.source)]
        if install:
            installer = Path(self.temp.name) / 'DCS installer.exe'
            installer.write_bytes(b'MZ fixture; never execute')
            arguments += ['--install', '--resume', '--installer', str(installer)]
        with patch.object(setup, 'dependency_problems', return_value=[]), \
             patch.object(setup, 'ensure_dcs_closed'), \
             patch.object(setup.Setup, 'dependencies'), \
             patch.object(setup.Setup, 'overrides'), \
             patch.object(setup.Setup, 'wine') as wine, \
             patch.object(setup.sys.stdin, 'isatty', return_value=False), \
             patch.object(setup.subprocess, 'run', side_effect=AssertionError('No real processes')):
            self.assertEqual(setup.main(arguments), 0)
            self.assertEqual(wine.call_count, 1 if install else 0)
        self.assertEqual(self.font.read_bytes(), font_bytes())
        self.assertEqual(self.multiplayer.read_bytes(), setup.patch_multiplayer(slot_source(b'\r\n')))

    def test_default_cli_run_includes_both_fixes(self):
        self.run_main_configuration()

    def test_install_resume_cli_run_includes_both_fixes(self):
        self.run_main_configuration(install=True)

    def test_d3dmetal_recipe_patches_renderer_enables_bridge_and_is_repeatable(self):
        self.args.graphics = 'd3dmetal'
        self.configured()
        self.assertEqual(self.renderer.read_bytes(), self.renderer_patched)
        values = setup.conf_values((self.root / 'cxbottle.conf').read_text(), 'EnvironmentVariables')
        self.assertEqual(values['CX_GRAPHICS_BACKEND'], 'd3dmetal')
        self.assertEqual(values['D3DM_ENABLE_METALFX'], '1')
        self.assertEqual(values['DXMT_ENABLE_NVEXT'], '1')
        before = self.snapshot()
        self.configured()
        self.assertEqual(self.snapshot(), before)
        with patch.object(setup, 'dependency_problems', return_value=[]):
            self.assertEqual(self.instance().check(), 0)
        self.instance().undo_compatibility()
        self.assertEqual(self.renderer.read_bytes(), self.renderer_original)
        self.assertEqual(setup.conf_values((self.root / 'cxbottle.conf').read_text(),
                                          'EnvironmentVariables')['CX_GRAPHICS_BACKEND'], 'dxmt')

    def test_unknown_renderer_blocks_entire_d3dmetal_configuration(self):
        self.args.graphics = 'd3dmetal'
        self.renderer.write_bytes(b'updated renderer; do not patch')
        before = self.snapshot()
        with self.assertRaisesRegex(setup.SetupError, 'Unsupported'):
            self.configured()
        self.assertEqual(self.snapshot(), before)

    def test_d3dmetal_patch_requires_expected_bytes_and_result_hash(self):
        self.assertEqual(setup.patch_d3dmetal(self.renderer_original), self.renderer_patched)
        self.assertEqual(setup.patch_d3dmetal(self.renderer_patched), self.renderer_patched)
        with patch.object(setup, 'D3DM_OFFSET', setup.D3DM_OFFSET + 1):
            with self.assertRaisesRegex(setup.SetupError, 'location'):
                setup.patch_d3dmetal(self.renderer_original)
        with patch.object(setup, 'D3DM_PATCHED_SHA256', 'wrong'):
            with self.assertRaisesRegex(setup.SetupError, 'checksum'):
                setup.patch_d3dmetal(self.renderer_original)

    def test_d3dmetal_undo_requires_matching_backup_and_preserves_updated_renderer(self):
        self.args.graphics = 'd3dmetal'
        instance = self.configured()
        records = json.loads((instance.backup / 'manifest.json').read_text())['files']
        renderer_record, = [r for r in records if r['path'] == str(self.renderer)]
        (instance.backup / renderer_record['backup']).write_bytes(b'changed backup')
        before = self.snapshot()
        with self.assertRaisesRegex(setup.SetupError, 'No matching original'):
            self.instance().undo_compatibility()
        self.assertEqual(self.snapshot(), before)
        self.renderer.write_bytes(b'new game update')
        self.instance().undo_compatibility()
        self.assertEqual(self.renderer.read_bytes(), b'new game update')

    def test_d3dmetal_undo_accepts_friend_patch_backup(self):
        self.renderer.write_bytes(self.renderer_patched)
        self.renderer.with_name(self.renderer.name + setup.D3DM_BACKUP_SUFFIX).write_bytes(self.renderer_original)
        self.configured()
        self.instance().undo_compatibility()
        self.assertEqual(self.renderer.read_bytes(), self.renderer_original)

    def test_wizard_supports_combined_setup_and_undo_preview(self):
        self.configured()
        before = self.snapshot()
        with patch('builtins.input', side_effect=['2', str(self.root), 'n', str(self.source)]), \
             patch.object(setup.subprocess, 'run', side_effect=AssertionError('No real processes')):
            self.assertEqual(setup.main(['--wizard', '--dry-run']), 0)
        with patch('builtins.input', side_effect=['4', str(self.root)]), \
             patch.object(setup.subprocess, 'run', side_effect=AssertionError('No real processes')):
            self.assertEqual(setup.main(['--wizard', '--dry-run']), 0)
        self.assertEqual(self.snapshot(), before)

    def test_reapply_after_game_update_keeps_updated_original_for_undo(self):
        self.configured()
        updated = slot_source(b'\r\n') + b'-- game update content\r\n'
        self.multiplayer.write_bytes(updated)
        self.configured()
        self.instance().undo_compatibility()
        self.assertEqual(self.multiplayer.read_bytes(), updated)

    def test_undo_new_install_restores_patch_and_removes_only_owned_font(self):
        self.configured()
        preferences = self.options.read_bytes()
        self.instance().undo_compatibility()
        self.assertEqual(self.multiplayer.read_bytes(), slot_source(b'\r\n'))
        self.assertFalse(self.font.exists())
        self.assertEqual(self.options.read_bytes(), preferences)
        self.configured()  # Reapply after undo and verify the cycle remains repeatable.
        self.instance().undo_compatibility()
        self.assertFalse(self.font.exists())

    def test_undo_preview_is_read_only(self):
        self.configured()
        before = self.snapshot()
        self.instance().undo_compatibility(dry_run=True)
        self.assertEqual(self.snapshot(), before)

    def test_modified_font_blocks_whole_undo_before_lua_changes(self):
        self.configured()
        self.font.write_bytes(b'user changed font')
        before = self.snapshot()
        with self.assertRaises(setup.SetupError):
            self.instance().undo_compatibility()
        self.assertEqual(self.snapshot(), before)

    def test_modified_lua_without_matching_backup_blocks_whole_undo(self):
        self.configured()
        self.multiplayer.write_bytes(self.multiplayer.read_bytes() + b'-- later edit\r\n')
        before = self.snapshot()
        with self.assertRaises(setup.SetupError):
            self.instance().undo_compatibility()
        self.assertEqual(self.snapshot(), before)

    def legacy_install(self):
        original = self.multiplayer.read_bytes()
        name = self.multiplayer.name + '.blue-coalition-' + hashlib.sha256(original).hexdigest()[:12] + '.bak'
        self.multiplayer.with_name(name).write_bytes(original)
        self.multiplayer.write_bytes(setup.patch_multiplayer(original))
        self.font.write_bytes(font_bytes())
        receipt = self.root / '.dcs-crossover-setup/apache-font.json'
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({'version': 1, 'font': setup.APACHE_FONT,
                                       'sha256': hashlib.sha256(font_bytes()).hexdigest()}))

    def test_legacy_fix_recovery_survives_removal_of_separate_tools(self):
        self.legacy_install()
        self.instance().undo_compatibility()
        self.assertFalse(self.font.exists())
        self.assertEqual(self.multiplayer.read_bytes(), slot_source(b'\r\n'))
        self.configured()
        self.assertTrue(self.font.exists())

    def test_legacy_font_hash_mismatch_preserves_both_files(self):
        self.legacy_install()
        self.font.write_bytes(b'user replacement')
        before = self.snapshot()
        with self.assertRaises(setup.SetupError):
            self.instance().undo_compatibility()
        self.assertEqual(self.snapshot(), before)

    def test_running_game_or_failed_process_inspection_blocks_mutations(self):
        for result in (unittest.mock.Mock(returncode=0, stdout='C:/game/DCS.exe\n'),
                       unittest.mock.Mock(returncode=0, stdout='Z:\\Users\\example\\DCS World\\bin\\DCS.exe\n'),
                       unittest.mock.Mock(returncode=1, stdout='')):
            with patch.object(setup.subprocess, 'run', return_value=result):
                with self.assertRaises(setup.SetupError):
                    setup.ensure_dcs_closed()

    def diagnostic_instance(self):
        instance = self.instance()
        instance.runtime = Path(self.temp.name) / 'Diagnostic CrossOver runtime'
        (instance.runtime / 'bin').mkdir(parents=True)
        (instance.runtime / 'bin/wine').write_bytes(b'fixture; never execute')
        (instance.runtime / 'bin/wineloader').write_bytes(b'fixture; never execute')
        return instance

    def test_logged_launch_preview_never_writes_or_starts_processes(self):
        instance = self.diagnostic_instance()
        before = self.snapshot()
        with patch.object(setup.subprocess, 'run', side_effect=AssertionError('Preview must not run Wine')):
            self.assertEqual(instance.launch_logged(dry_run=True), 0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / '.dcs-crossover-setup').exists())

    def test_logged_launch_captures_native_and_game_logs_without_applying_fixes(self):
        instance = self.diagnostic_instance()
        log = self.profile / 'Logs/dcs.log'
        log.parent.mkdir()
        log.write_bytes(b'previous DCS session')
        protected = {p: p.read_bytes() for p in (self.options, self.multiplayer,
                                               self.root / 'cxbottle.conf', self.root / 'user.reg')}

        def reproduce(command, cwd, env, stdout, stderr):
            self.assertEqual(cwd, self.game)
            self.assertEqual(command[command.index('--bottle') + 1], str(self.root))
            self.assertIn('--wait', command)
            self.assertEqual(command[command.index('--debugmsg') + 1], '+seh,+tid,+loaddll')
            self.assertEqual(env['CX_BOTTLE_PATH'], str(self.root.parent))
            Path(command[command.index('--cx-log') + 1]).write_bytes(b'fixture native exception')
            log.write_bytes(b'new DCS session ending at crash')
            stdout.write(b'fixture launcher output')
            return unittest.mock.Mock(returncode=23)

        with patch.object(setup.subprocess, 'run', side_effect=reproduce):
            self.assertEqual(instance.launch_logged(), 23)
        folder, = (self.root / '.dcs-crossover-setup/diagnostics').iterdir()
        self.assertEqual((folder / 'dcs-before.log').read_bytes(), b'previous DCS session')
        self.assertEqual((folder / 'dcs-after.log').read_bytes(), b'new DCS session ending at crash')
        self.assertEqual((folder / 'CrossOver.cxlog').read_bytes(), b'fixture native exception')
        self.assertEqual(json.loads((folder / 'run.json').read_text())['exit_code'], 23)
        self.assertEqual(protected, {p: p.read_bytes() for p in protected})
        self.assertFalse(self.font.exists())
        instance.overrides.assert_not_called()

    def test_logged_launch_rejects_setup_options(self):
        before = self.snapshot()
        with self.assertRaises(setup.SetupError):
            setup.main(['--bottle', str(self.root), '--launch-log', '--dependencies'])
        self.assertEqual(self.snapshot(), before)

    def test_logged_backend_override_is_one_command_and_not_saved_configuration(self):
        instance = self.diagnostic_instance()
        before = self.snapshot()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
             patch.object(setup.subprocess, 'run', side_effect=AssertionError('Preview must not launch')):
            self.assertEqual(instance.launch_logged(dry_run=True, backend='d3dmetal'), 0)
        self.assertIn('--env CX_GRAPHICS_BACKEND=d3dmetal', output.getvalue())
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(setup.SetupError):
            setup.main(['--bottle', str(self.root), '--log-backend', 'd3dmetal'])



if __name__ == '__main__':
    unittest.main()
