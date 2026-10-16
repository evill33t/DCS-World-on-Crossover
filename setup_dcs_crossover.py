#!/usr/bin/env python3
"""Configure standalone DCS World for CrossOver with D3DMetal, DLSS support and compatibility guards.

Python 3.9+, standard library only. See DCS-CrossOver-clean-install.md.
No game files, credentials, or licensed binaries are included in this package.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid


DEFAULT_BOTTLE = Path.home() / 'Library/Application Support/CrossOver/Bottles/DCS World Clean'
OVERRIDE_KEY = r'HKCU\Software\Wine\DllOverrides'
FULL_OVERRIDE_KEY = r'HKEY_CURRENT_USER\Software\Wine\DllOverrides'
OVERRIDES = {'wbemprox': 'native', 'msdmo': 'native',
             'winhttp': 'native,builtin', 'd3dcompiler_47': 'native,builtin'}
PREFERENCES = {'launcher': 'false', 'collect_stat': 'false',
               'collect_stat_defined': 'true', 'push_starthere': 'false'}
APACHE_FONT = 'seguisym.ttf'
MULTIPLAYER_FILE = Path('MissionEditor/modules/mul_voicechat.lua')
SLOT_SIGNATURE = b'function onPlayerChangeSlot(id)'
SLOT_GUARD = (b'\t-- VoiceChat may be unavailable under Wine/CrossOver.\n'
              b'\tif voice_chat == nil then\n\t\treturn\n\tend\n')
SLOT_BODY = b'\tif ((DCS.isMultiplayer() == true) and (DCS.isTrackPlaying() ~= true)) then'
D3DM_ORIGINAL_SHA256 = 'e66f5b1c8a2f22b909ddeddbd3e12049a58962035aeb544b32e5314509c54ae3'
D3DM_PATCHED_SHA256 = '389ffe5eb81341092ce3004eb4b86bfbfe3b7cf3dfb143b212223e7e8e968697'
D3DM_OFFSET = 0x1A83F
D3DM_ORIGINAL_BYTES = bytes.fromhex('488b8c24980000004885c97462')
D3DM_PATCHED_BYTES = bytes.fromhex('85c0786b488b8c249800000090')
D3DM_BACKUP_SUFFIX = '.d3dmetal-original-2.9.30.28738'
# Integrated from the user-supplied DCS-D3DMetal-Patch-2.9.30.28738.zip.
# ZIP SHA-256: 48451e6251f62f4b4b1c68f6046969c5bb62eecc0ed8dbb0e0e6069456e25ef9
COMPILERS = {
    'system32': ('d3dcompiler_47.dll',
                 '4432bbd1a390874f3f0a503d45cc48d346abc3a8c0213c289f4b615bf0ee84f3'),
    'syswow64': ('d3dcompiler_47_32.dll',
                 '2ad0d4987fc4624566b190e747c9d95038443956ed816abfd1e2d389b5ec0851'),
}
# Package checksums published by upstream Winetricks; extraction is implemented here.
# https://github.com/Winetricks/winetricks/blob/master/src/winetricks
FONTS = dict(line.split() for line in '''
andale32.exe 0524fe42951adc3a7eb870e32f0920313c71f170c859b5f770d82b4ee111e970
arial32.exe 85297a4d146e9c87ac6f74822734bdee5f4b2a722d7eaa584b7f2cbf76f478f6
arialb32.exe a425f0ffb6a1a5ede5b979ed6177f4f4f4fdef6ae7c302a7b7720ef332fec0a8
comic32.exe 9c6df3feefde26d4e41d4a4fe5db2a89f9123a772594d7f59afd062625cd204e
courie32.exe bb511d861655dde879ae552eb86b134d6fae67cb58502e6ff73ec5d9151f3384
georgi32.exe 2c2c7dcda6606ea5cf08918fb7cd3f3359e9e84338dc690013f20cd42e930301
impact32.exe 6061ef3b7401d9642f5dfdb5f2b376aa14663f6275e60a51207ad4facf2fccfb
times32.exe db56595ec6ef5d3de5c24994f001f03b2a13e37cee27bc25c58f6f43e8f807ab
trebuc32.exe 5a690d9bb8510be1b8b4fe49f1f2319651fe51bbe54775ddddd8ef0bd07fdac9
verdan32.exe c1cb61255e363166794e47664e2f21af8e3a26cb6346eb8d2ae2fa85dd5aad96
webdin32.exe 64595b5abc1080fba8610c5c34fab5863408e806aafe84653ca8575bed17d75a
'''.strip().splitlines())


class SetupError(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def native_dll(path):
    if not path.is_file():
        return False
    with path.open('rb') as stream:
        header = stream.read(4096)
    return header[:2] == b'MZ' and b'Wine builtin DLL' not in header


def validate_apache_font(data):
    """Reject wrong fonts and malformed TrueType name tables before copying."""
    try:
        if len(data) < 12 or data[:4] != b'\x00\x01\x00\x00':
            raise ValueError('Not a TrueType font')
        count = struct.unpack_from('>H', data, 4)[0]
        if 12 + count * 16 > len(data):
            raise ValueError('Truncated TrueType table directory')
        for i in range(count):
            tag, _, offset, length = struct.unpack_from('>4sIII', data, 12 + i * 16)
            if tag != b'name':
                continue
            if offset + length > len(data):
                raise ValueError('Truncated font name table')
            table = data[offset:offset + length]
            _, records, strings = struct.unpack_from('>HHH', table)
            if 6 + records * 12 > strings or strings > len(table):
                raise ValueError('Invalid font name records')
            for j in range(records):
                platform, _, _, name_id, size, start = struct.unpack_from('>HHHHHH', table, 6 + j * 12)
                if strings + start + size > len(table):
                    raise ValueError('Truncated font name string')
                if name_id in (1, 4, 16):
                    raw = table[strings + start:strings + start + size]
                    name = raw.decode('utf-16-be' if platform in (0, 3) else 'latin-1')
                    if name == 'Segoe UI Symbol':
                        return
        raise ValueError('Expected the Segoe UI Symbol font family')
    except (ValueError, struct.error, UnicodeError) as error:
        raise SetupError('Invalid ' + APACHE_FONT + ': ' + str(error)) from error


def font_directory(bottle):
    windows = bottle / 'drive_c/windows'
    matches = [p for p in windows.iterdir() if p.name.lower() == 'fonts'] if windows.is_dir() else []
    if len(matches) > 1:
        raise SetupError('Multiple Windows Fonts directories found.')
    directory = matches[0] if matches else windows / 'Fonts'
    if not directory.resolve().is_relative_to(bottle):
        raise SetupError('Windows Fonts directory points outside this bottle.')
    return directory


def apache_font_path(bottle):
    directory = font_directory(bottle)
    matches = [p for p in directory.iterdir() if p.name.lower() == APACHE_FONT] if directory.is_dir() else []
    if len(matches) > 1:
        raise SetupError('Multiple Segoe UI Symbol font files found.')
    target = matches[0] if matches else directory / APACHE_FONT
    if target.is_symlink():
        raise SetupError('Refusing a linked Segoe UI Symbol font.')
    return target


def local_apache_font(explicit=None):
    if explicit:
        candidates = [Path(explicit).expanduser().resolve()]
    else:
        candidates = [Path('/Applications') / (app + '.app') / 'Contents/Resources/DFonts' / APACHE_FONT
                      for app in ('Microsoft Word', 'Microsoft Excel', 'Microsoft PowerPoint')]
    for path in candidates:
        if path.is_file():
            data = path.read_bytes()
            validate_apache_font(data)
            return data
    raise SetupError('Segoe UI Symbol is missing. Install Office locally or pass --font /path/to/seguisym.ttf. '
                     'No Microsoft font is bundled or downloaded by this tool.')


def multiplayer_parts(data):
    matches = list(re.finditer(rb'(?m)^' + re.escape(SLOT_SIGNATURE) + rb'(\r?\n)', data))
    if len(matches) != 1 or b"base.safe_require('VoiceChat')" not in data:
        raise SetupError('Unrecognized mul_voicechat.lua; expected one VoiceChat slot callback. File left unchanged.')
    match = matches[0]
    return data[:match.end()], data[match.end():], SLOT_GUARD.replace(b'\n', match[1])


def patch_multiplayer(data):
    before, after, guard = multiplayer_parts(data)
    body = after[len(guard):] if after.startswith(guard) else after
    if not body.splitlines() or body.splitlines()[0] != SLOT_BODY:
        raise SetupError('Unrecognized onPlayerChangeSlot body; file left unchanged. Review this DCS version first.')
    return before + guard + body


def patch_d3dmetal(data):
    """Guard QueryInterface's HRESULT in the exact supported DCS renderer only."""
    digest = hashlib.sha256(data).hexdigest()
    if digest == D3DM_PATCHED_SHA256:
        if data[D3DM_OFFSET:D3DM_OFFSET + len(D3DM_PATCHED_BYTES)] != D3DM_PATCHED_BYTES:
            raise SetupError('D3DMetal patch bytes do not match their checksum record.')
        return data
    if digest != D3DM_ORIGINAL_SHA256:
        raise SetupError('Unsupported dx11backend.dll for the D3DMetal patch. Nothing was patched. '
                         'Only the verified DCS 2.9.30.28738 renderer is supported; '
                         'do not copy an older DLL over an update. Use --graphics dxmt to skip this patch.')
    if data[D3DM_OFFSET:D3DM_OFFSET + len(D3DM_ORIGINAL_BYTES)] != D3DM_ORIGINAL_BYTES:
        raise SetupError('D3DMetal patch location does not match; nothing was patched.')
    patched = (data[:D3DM_OFFSET] + D3DM_PATCHED_BYTES
               + data[D3DM_OFFSET + len(D3DM_ORIGINAL_BYTES):])
    if hashlib.sha256(patched).hexdigest() != D3DM_PATCHED_SHA256:
        raise SetupError('D3DMetal patched renderer checksum does not match; nothing was patched.')
    return patched


def registry_section(path, section):
    """Read a Wine registry file or reg.exe export without launching Wine."""
    if not path.is_file():
        return {}
    data = path.read_bytes()
    text = data.decode('utf-16') if data.startswith((b'\xff\xfe', b'\xfe\xff')) else data.decode('utf-8')
    active = False
    result = {}
    for line in text.splitlines():
        if line.startswith('['):
            name = line[1:line.find(']')].replace('\\\\', '\\')
            active = name.lower() == section.lower()
        elif active:
            match = re.fullmatch(r'"((?:\\.|[^"\\])*)"=(.*)', line)
            if match:
                result[match[1]] = match[2]
    return result


def registry_document(values):
    lines = ['Windows Registry Editor Version 5.00', '', '[' + FULL_OVERRIDE_KEY + ']']
    for key, value in values.items():
        escaped = key.replace('\\', '\\\\').replace('"', '\\"')
        lines.append('"' + escaped + '"=' + value)
    return ('\r\n'.join(lines) + '\r\n').encode('utf-16')


def conf_values(text, section):
    active = False
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r'\s*\[([^]]+)\]\s*', line)
        if match:
            active = match[1] == section
        elif active:
            match = re.fullmatch(r'\s*"([^"]+)"\s*=\s*"([^"]*)"\s*(?:[;#].*)?', line)
            if match:
                if match[1] in result:
                    raise SetupError('Duplicate bottle setting: ' + match[1])
                result[match[1]] = match[2]
    return result


def patch_conf(text, graphics='dxmt'):
    newline = '\r\n' if '\r\n' in text else '\n'
    sections = list(re.finditer(r'(?m)^\s*\[([^]\r\n]+)\][ \t]*\r?$', text))
    found = [i for i, match in enumerate(sections) if match[1] == 'EnvironmentVariables']
    if len(found) > 1:
        raise SetupError('Duplicate EnvironmentVariables sections')
    wanted = {'CX_GRAPHICS_BACKEND': graphics, 'WINEMSYNC': '1'}
    if graphics == 'd3dmetal':
        # These are the two keys controlled by CrossOver 26's DLSS switch.
        wanted.update(D3DM_ENABLE_METALFX='1', DXMT_ENABLE_NVEXT='1')
    if not found:
        return text.rstrip('\r\n') + newline * 2 + '[EnvironmentVariables]' + newline + ''.join(
            '"' + key + '" = "' + value + '"' + newline for key, value in wanted.items())
    index = found[0]
    start = sections[index].end()
    end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
    block = text[start:end]
    conf_values(text, 'EnvironmentVariables')  # Reject ambiguous duplicates.
    for key, value in wanted.items():
        pattern = r'(?m)^([ \t]*"' + key + r'"[ \t]*=[ \t]*)"[^"\r\n]*"'
        if re.search(pattern, block):
            block = re.sub(pattern, lambda m: m[1] + '"' + value + '"', block)
        else:
            block = block.rstrip('\r\n') + newline + '"' + key + '" = "' + value + '"' + newline
    return text[:start] + block + text[end:]


# Tokenize only to find table entries. No user Lua code is executed.
TOKEN = re.compile(r'''--\[(=*)\[|--[^\r\n]*|\[(=*)\[|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|-?(?:0[xX][0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?(?:[pP][+-]?\d+)?|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|[A-Za-z_][A-Za-z_0-9]*|\s+|.''', re.S)


def lua_tokens(text):
    tokens = []
    position = 0
    while position < len(text):
        match = TOKEN.match(text, position)
        token = match[0]
        if match[1] is not None or match[2] is not None:
            level = match[1] if match[1] is not None else match[2]
            closer = ']' + level + ']'
            end = text.find(closer, match.end())
            if end == -1:
                raise SetupError('Unclosed Lua long string/comment')
            end += len(closer)
            if match[1] is None:
                tokens.append((text[position:end], position, end))
            position = end
            continue
        if token in ('"', "'"):
            raise SetupError('Unclosed Lua quoted string')
        if not token.isspace() and not token.startswith('--'):
            tokens.append((token, position, match.end()))
        position = match.end()
    stack = []
    pairs = {}
    for index, (token, _, _) in enumerate(tokens):
        if token in ('{', '[', '('):
            stack.append((token, index))
        elif token in ('}', ']', ')'):
            if not stack or {'}': '{', ']': '[', ')': '('}[token] != stack[-1][0]:
                raise SetupError('Unbalanced Lua delimiters')
            _, opening = stack.pop()
            pairs[opening] = index
    if stack:
        raise SetupError('Unbalanced Lua delimiters')
    return tokens, pairs


def lua_entries(tokens, pairs, opening):
    result = {}
    index = opening + 1
    while index < pairs[opening]:
        if tokens[index][0] in (',', ';'):
            index += 1
            continue
        if tokens[index][0] == '[':
            if pairs.get(index) != index + 2 or not tokens[index + 1][0].startswith(('"', "'")):
                raise SetupError('Unsupported calculated Lua option key')
            key = tokens[index + 1][0][1:-1]
            equals = index + 3
        else:
            key = tokens[index][0]
            equals = index + 1
        if equals + 1 >= pairs[opening] or tokens[equals][0] != '=':
            raise SetupError('Unsupported options.lua entry; file left unchanged')
        value = equals + 1
        if key in result:
            raise SetupError('Duplicate Lua option key: ' + key)
        result[key] = value
        index = pairs[value] + 1 if value in pairs else value + 1
        if index < pairs[opening] and tokens[index][0] not in (',', ';'):
            raise SetupError('Unsupported Lua option expression; file left unchanged')
    return result


def options_table(text):
    tokens, pairs = lua_tokens(text)
    matches = [i + 2 for i in range(len(tokens) - 2)
               if [t[0] for t in tokens[i:i + 3]] == ['options', '=', '{']]
    if len(matches) != 1:
        raise SetupError('Expected one options = {...} table')
    root = matches[0]
    return tokens, pairs, root, lua_entries(tokens, pairs, root)


def preference_values(text):
    tokens, pairs, _, root_entries = options_table(text)
    if 'miscellaneous' not in root_entries:
        return {}
    opening = root_entries['miscellaneous']
    if tokens[opening][0] != '{':
        raise SetupError('miscellaneous must be a Lua table')
    return {key: tokens[index][0] for key, index in lua_entries(tokens, pairs, opening).items()}


def patch_options(text):
    tokens, pairs, root, root_entries = options_table(text)
    newline = '\r\n' if '\r\n' in text else '\n'
    if 'miscellaneous' not in root_entries:
        position = tokens[root][2]
        block = newline + '\t["miscellaneous"] = {' + newline + ''.join(
            '\t\t["' + key + '"] = ' + value + ',' + newline for key, value in PREFERENCES.items())
        text = text[:position] + block + '\t},' + text[position:]
    else:
        opening = root_entries['miscellaneous']
        if tokens[opening][0] != '{':
            raise SetupError('miscellaneous must be a Lua table')
        entries = lua_entries(tokens, pairs, opening)
        edits = []
        missing = {}
        for key, value in PREFERENCES.items():
            if key not in entries:
                missing[key] = value
            else:
                token, start, end = tokens[entries[key]]
                if token not in ('true', 'false', 'nil'):
                    raise SetupError('Unexpected non-boolean preference: ' + key)
                edits.append((start, end, value))
        if missing:
            position = tokens[opening][2]
            block = newline + ''.join('\t\t["' + key + '"] = ' + value + ',' + newline
                                      for key, value in missing.items())
            edits.append((position, position, block))
        for start, end, value in sorted(edits, reverse=True):
            text = text[:start] + value + text[end:]
    actual = preference_values(text)
    if any(actual.get(key) != value for key, value in PREFERENCES.items()):
        raise SetupError('Could not verify patched DCS preferences')
    return text


def find_game(bottle, explicit=None):
    if explicit:
        candidates = [Path(explicit).expanduser().resolve()]
    else:
        base = bottle / 'drive_c/Program Files/Eagle Dynamics'
        candidates = list(base.glob('DCS*'))
    candidates = [path for path in candidates if (path / 'bin/DCS.exe').is_file()]
    if len(candidates) != 1:
        raise SetupError('Could not identify one DCS installation. Use --game-dir with its Mac path.')
    return candidates[0]


def find_profile(bottle, explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    users = bottle / 'drive_c/users'
    profiles = [path for path in users.glob('*/Saved Games/DCS') if path.is_dir()]
    if len(profiles) == 1:
        return profiles[0]
    if len(profiles) > 1:
        raise SetupError('Several DCS profiles found. Select one with --profile.')
    return users / 'crossover/Saved Games/DCS'


def vc_installed(bottle, architecture):
    for prefix in ('Software\\Microsoft', 'Software\\Wow6432Node\\Microsoft'):
        values = registry_section(bottle / 'system.reg',
                                  prefix + '\\VisualStudio\\14.0\\VC\\Runtimes\\' + architecture)
        if values.get('Installed') == 'dword:00000001':
            return all(native_dll(bottle / 'drive_c/windows' / ('system32' if architecture == 'x64' else 'syswow64') / name)
                       for name in ('vcruntime140.dll', 'msvcp140.dll'))
    return False


def dependency_problems(bottle):
    problems = []
    for arch in ('x64', 'x86'):
        if not vc_installed(bottle, arch):
            problems.append('Visual C++ v14 ' + arch + ' runtime missing')
    for directory in COMPILERS:
        path = bottle / 'drive_c/windows' / directory / 'd3dcompiler_47.dll'
        if not native_dll(path):
            problems.append('Native d3dcompiler_47 missing in ' + directory)
    font_dir = font_directory(bottle)
    names = {path.name.lower() for path in font_dir.iterdir()} if font_dir.is_dir() else set()
    if not {'arial.ttf', 'times.ttf', 'cour.ttf', 'verdana.ttf'}.issubset(names):
        problems.append('Microsoft core fonts missing')
    return problems


class Setup:
    def __init__(self, args):
        self.args = args
        self.bottle = Path(args.bottle).expanduser().resolve()
        self.runtime = Path(args.crossover).expanduser().resolve() / 'Contents/SharedSupport/CrossOver'
        self.env = os.environ.copy()
        self.env['CX_BOTTLE_PATH'] = str(self.bottle.parent)
        # Ensure shell-level experimental overrides cannot defeat the bottle configuration.
        for name in ('WINEDLLOVERRIDES', 'CX_GRAPHICS_BACKEND', 'WINEMSYNC',
                     'D3DM_ENABLE_METALFX', 'DXMT_ENABLE_NVEXT'):
            self.env.pop(name, None)
        self.backup = None
        self.records = []

    @property
    def graphics_backend(self):
        return getattr(self.args, 'graphics', 'd3dmetal')

    def run(self, command, timeout=300, allowed=(0,)):
        result = subprocess.run([str(part) for part in command], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode not in allowed:
            raise SetupError('Command failed (exit ' + str(result.returncode) + '): ' + str(command[0]) +
                             '\n' + result.stdout.decode(errors='replace')[-5000:])
        return result

    def wine(self, *arguments, timeout=300, allowed=(0,), gui=False):
        command = [self.runtime / 'bin/wine', '--bottle', self.bottle.name, '--no-update', '--debugmsg', '-all']
        if not gui:
            command.append('--no-gui')
        return self.run(command + list(arguments), timeout, allowed)

    def begin_backup(self):
        if self.backup is None:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            self.backup = self.bottle / '.dcs-crossover-setup/backups' / (stamp + '-' + uuid.uuid4().hex[:8])
            self.backup.mkdir(parents=True, exist_ok=False)
            self.save_manifest()

    def save_manifest(self):
        if self.backup:
            (self.backup / 'manifest.json').write_text(json.dumps(
                {'bottle': str(self.bottle), 'files': self.records,
                 'note': 'Dependency installations are not undone by these configuration backups.'}, indent=2) + '\n')

    def replace(self, path, data):
        old = path.read_bytes() if path.exists() else None
        if old == data:
            return
        self.begin_backup()
        backup_file = None
        if old is not None:
            backup_file = str(len(self.records)) + '-' + path.name
            (self.backup / backup_file).write_bytes(old)
        self.records.append({'path': str(path), 'backup': backup_file,
                             'created': old is None, 'after_sha256': hashlib.sha256(data).hexdigest()})
        self.save_manifest()  # Record recovery information before modifying the file.
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_bytes() if path.exists() else None
        if current != old:
            raise SetupError('File changed during setup; close DCS and CrossOver: ' + str(path))
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
        if path.read_bytes() != data:
            raise SetupError('Could not verify file: ' + str(path))

    def remove(self, path):
        old = path.read_bytes()
        self.begin_backup()
        backup_file = str(len(self.records)) + '-' + path.name
        (self.backup / backup_file).write_bytes(old)
        self.records.append({'path': str(path), 'backup': backup_file, 'created': False,
                             'deleted': True, 'after_sha256': None})
        self.save_manifest()
        if path.read_bytes() != old:
            raise SetupError('File changed during setup: ' + str(path))
        path.unlink()

    def compatibility_plan(self, game):
        target = apache_font_path(self.bottle)
        if target.exists():
            validate_apache_font(target.read_bytes())
            font_data = None  # Retain pre-existing valid fonts, regardless of their source.
        else:
            font_data = local_apache_font(self.args.font)
        multiplayer = game / MULTIPLAYER_FILE
        if multiplayer.is_symlink():
            raise SetupError('Refusing a linked mul_voicechat.lua.')
        patched = patch_multiplayer(multiplayer.read_bytes())
        return target, font_data, multiplayer, patched

    def launch_logged(self, dry_run=False, backend=None):
        """Run an explicitly requested reproduction without applying any fixes."""
        game = find_game(self.bottle, self.args.game_dir)
        profile = find_profile(self.bottle, self.args.profile)
        wine = self.runtime / 'bin/wine'
        if not wine.is_file():
            raise SetupError('CrossOver executable not found: ' + str(wine))
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        folder = self.bottle / '.dcs-crossover-setup/diagnostics' / (stamp + '-' + uuid.uuid4().hex[:8])
        config = conf_values((self.bottle / 'cxbottle.conf').read_text(), 'EnvironmentVariables')
        environment = []
        if backend:
            environment.append('CX_GRAPHICS_BACKEND=' + backend)
        command = [str(wine), '--bottle', str(self.bottle), '--no-update', '--wait',
                   '--workdir', windows_path(game), '--cx-log', str(folder / 'CrossOver.cxlog'),
                   '--debugmsg', '+seh,+tid,+loaddll']
        if environment:
            command += ['--env', shlex.join(environment)]
        command += ['--cx-app', windows_path(game / 'bin/DCS.exe'), '--', '--no-launcher']
        print('Diagnostic log directory: ' + str(folder), flush=True)
        if dry_run:
            print('DRY RUN; no files changed and no processes launched.')
            print(shlex.join(command))
            return 0
        folder.mkdir(parents=True, exist_ok=False)
        log = profile / 'Logs/dcs.log'
        if log.is_file():
            shutil.copy2(log, folder / 'dcs-before.log')
        metadata = {'bottle': str(self.bottle), 'game': str(game), 'profile': str(profile),
                    'command': command, 'environment': {key: config.get(key) for key in
                                                       ('CX_GRAPHICS_BACKEND', 'WINEMSYNC',
                                                        'D3DM_ENABLE_METALFX', 'DXMT_ENABLE_NVEXT')}}
        renderer = game / 'bin/dx11backend.dll'
        metadata['renderer_sha256'] = sha256(renderer) if renderer.is_file() else None
        metadata['bottle_graphics_backend'] = config.get('CX_GRAPHICS_BACKEND')
        if backend:
            metadata['environment']['CX_GRAPHICS_BACKEND'] = backend
        (folder / 'run.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print('Starting DCS with native exception and DLL logging. Retry the same Apache slot.', flush=True)
        print('Keep this terminal open until DCS exits. No compatibility settings are changed by this mode.', flush=True)
        result = None
        try:
            with (folder / 'launcher.log').open('wb') as output:
                result = subprocess.run(command, cwd=game, env=self.env,
                                        stdout=output, stderr=subprocess.STDOUT)
            metadata['exit_code'] = result.returncode
            (folder / 'run.json').write_text(json.dumps(metadata, indent=2) + '\n')
            print('DCS launcher exited with code ' + str(result.returncode) + '.', flush=True)
            return result.returncode
        finally:
            if log.is_file():
                shutil.copy2(log, folder / 'dcs-after.log')
            print('Diagnostic files saved in: ' + str(folder), flush=True)

    def backup_original(self, target, current):
        """Find a matching main-setup backup, never trust arbitrary manifest paths."""
        digest = hashlib.sha256(current).hexdigest()
        folder = self.bottle / '.dcs-crossover-setup/backups'
        for manifest in sorted(folder.glob('*/manifest.json'), reverse=True):
            document = json.loads(manifest.read_text())
            for record in reversed(document.get('files', [])):
                if record.get('path') != str(target) or record.get('after_sha256') != digest:
                    continue
                if record.get('created') is True:
                    return True, None
                name = record.get('backup')
                if not isinstance(name, str) or Path(name).name != name:
                    raise SetupError('Invalid backup entry in ' + str(manifest))
                backup = manifest.parent / name
                if backup.is_symlink():
                    raise SetupError('Refusing a linked backup: ' + str(backup))
                return True, backup.read_bytes()
        return False, None

    def undo_compatibility(self, dry_run=False):
        game = find_game(self.bottle, self.args.game_dir)
        target = game / MULTIPLAYER_FILE
        if target.is_symlink():
            raise SetupError('Refusing a linked mul_voicechat.lua.')
        data = target.read_bytes()
        before, after, guard = multiplayer_parts(data)
        plan = []
        renderer = game / 'bin/dx11backend.dll'
        if renderer.is_symlink():
            raise SetupError('Refusing a linked dx11backend.dll.')
        if renderer.is_file():
            current = renderer.read_bytes()
            if hashlib.sha256(current).hexdigest() == D3DM_PATCHED_SHA256:
                found, saved = self.backup_original(renderer, current)
                legacy = renderer.with_name(renderer.name + D3DM_BACKUP_SUFFIX)
                if not found and legacy.is_file() and not legacy.is_symlink():
                    found, saved = True, legacy.read_bytes()
                if not found or saved is None or hashlib.sha256(saved).hexdigest() != D3DM_ORIGINAL_SHA256:
                    raise SetupError('No matching original D3DMetal renderer backup; nothing changed.')
                plan.append((renderer, saved))
                config = self.bottle / 'cxbottle.conf'
                text = config.read_text()
                if conf_values(text, 'EnvironmentVariables').get('CX_GRAPHICS_BACKEND') == 'd3dmetal':
                    plan.append((config, patch_conf(text, 'dxmt').encode('utf-8')))
            else:
                # A game update owns its new renderer; never restore an older DLL over it.
                print('Keeping original or updated renderer; D3DMetal patch is not active.')
        if after.startswith(guard):
            patch_multiplayer(data)  # Validate the remainder of the callback too.
            original = before + after[len(guard):]
            found, saved = self.backup_original(target, data)
            if not found:
                # Retain undo for installations made with the former separate patch.
                digest = hashlib.sha256(original).hexdigest()[:12]
                legacy = target.with_name(target.name + '.blue-coalition-' + digest + '.bak')
                saved = legacy.read_bytes() if legacy.is_file() and not legacy.is_symlink() else None
            if saved != original:
                raise SetupError('Matching unmodified multiplayer backup not found; nothing changed.')
            plan.append((target, saved))
        font = apache_font_path(self.bottle)
        if font.is_file():
            current = font.read_bytes()
            found, saved = self.backup_original(font, current)
            legacy = self.bottle / '.dcs-crossover-setup/apache-font.json'
            if not found and legacy.is_file():
                record = json.loads(legacy.read_text())
                if record.get('version') != 1 or record.get('font') != APACHE_FONT:
                    raise SetupError('Unrecognized legacy font receipt; nothing changed.')
                if record.get('sha256') != hashlib.sha256(current).hexdigest():
                    raise SetupError('Font changed since installation; nothing changed.')
                found, saved = True, None
            if found:
                plan.append((font, saved))
            else:
                # A manifest proves ownership even if someone subsequently changed the font.
                folder = self.bottle / '.dcs-crossover-setup/backups'
                if any(any(r.get('path') == str(font) and r.get('created') is True
                           for r in json.loads(p.read_text()).get('files', []))
                       for p in folder.glob('*/manifest.json')):
                    raise SetupError('Font differs from its setup backup record; nothing changed.')
                print('Keeping pre-existing Segoe UI Symbol font; no setup ownership record.')
        # Preflight the renderer, configuration, Lua, and font before changing any.
        for path, restored in plan:
            print(('Would remove ' if restored is None else 'Would restore ') + str(path))
        if dry_run:
            return 0
        for path, restored in plan:
            if restored is None:
                self.remove(path)
            else:
                self.replace(path, restored)
        print('Compatibility fixes undone.' if plan else 'No installed compatibility fixes to undo.')
        return 0

    def graphics(self):
        path = self.bottle / 'cxbottle.conf'
        original = path.read_bytes()
        text = original.decode('utf-8')
        if conf_values(text, 'Bottle').get('Template') != 'win10_64':
            raise SetupError('This script requires a Windows 10 64-bit bottle (win10_64).')
        self.replace(path, patch_conf(text, self.graphics_backend).encode('utf-8'))

    def overrides(self):
        self.begin_backup()
        before = self.backup / 'dll-overrides-before.reg'
        result = self.wine('reg.exe', 'export', OVERRIDE_KEY, windows_path(before), '/y', allowed=(0, 1))
        if result.returncode != 0:
            # A missing key is valid only when reg query confirms it does not exist.
            query = self.wine('reg.exe', 'query', OVERRIDE_KEY, allowed=(0, 1))
            if query.returncode == 0:
                raise SetupError('DLL override export failed; registry was left unchanged.')
            values = {}
        else:
            if not before.is_file():
                raise SetupError('DLL override export produced no file')
            values = registry_section(before, FULL_OVERRIDE_KEY)
        changes = {key: '"' + value + '"' for key, value in OVERRIDES.items()}
        # Delete only malformed entries and the two empty overrides from our failed experiment.
        for key in ('msdmo (native)', 'winhttp (native,builtin)'):
            if key in values:
                changes[key] = '-'
        for key in ('nvapi', 'nvapi64'):
            if values.get(key) == '""':
                changes[key] = '-'
        changes = {key: value for key, value in changes.items()
                   if values.get(key) != value and not (value == '-' and key not in values)}
        restore = {key: values.get(key, '-') for key in changes}
        (self.backup / 'restore-dll-overrides.reg').write_bytes(registry_document(restore))
        if not changes:
            print('DLL overrides already match.')
            return
        patch = self.backup / 'apply-dll-overrides.reg'
        patch.write_bytes(registry_document(changes))
        self.wine('reg.exe', 'import', windows_path(patch))
        after = self.backup / 'dll-overrides-after.reg'
        self.wine('reg.exe', 'export', OVERRIDE_KEY, windows_path(after), '/y')
        expected = dict(values)
        for key, value in changes.items():
            if value == '-':
                expected.pop(key, None)
            else:
                expected[key] = value
        if registry_section(after, FULL_OVERRIDE_KEY) != expected:
            raise SetupError('Registry verification failed. Recovery file: ' + str(self.backup / 'restore-dll-overrides.reg'))

    def download(self, name, url, digest=None):
        cache = self.bottle / '.dcs-crossover-setup/downloads'
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / name
        if digest and target.is_file() and sha256(target) == digest:
            return target
        temporary = cache / (name + '.partial')
        print('Downloading ' + name + '...', flush=True)
        self.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error', '--retry', '2',
                  '--connect-timeout', '30', '--max-time', '600', '--proto', '=https', '--proto-redir', '=https',
                  '--output', temporary, url], timeout=650)
        if digest and sha256(temporary) != digest:
            temporary.unlink()
            raise SetupError('Checksum mismatch for ' + name + '; nothing was installed from this download.')
        if temporary.read_bytes()[:2] != b'MZ':
            temporary.unlink()
            raise SetupError('Download is not a Windows binary: ' + name)
        os.replace(temporary, target)
        return target

    def dependencies(self):
        self.begin_backup()
        for architecture in ('x64', 'x86'):
            if vc_installed(self.bottle, architecture):
                print('Visual C++ ' + architecture + ' already installed.')
                continue
            name = 'vc_redist.' + architecture + '.exe'
            path = self.download(name, 'https://aka.ms/vc14/' + name)
            log = self.backup / ('vc-redist-' + architecture + '.log')
            # Wine exposes some Windows return codes modulo 256. Verify the installed
            # registry and native libraries even when an installer reports success.
            self.wine(windows_path(path), '/install', '/quiet', '/norestart', '/log', windows_path(log),
                      timeout=900, allowed=(0, 194, 102))
            if not vc_installed(self.bottle, architecture):
                raise SetupError('Visual C++ ' + architecture + ' installation did not verify. See ' + str(log))
        for directory, (name, digest) in COMPILERS.items():
            destination = self.bottle / 'drive_c/windows' / directory / 'd3dcompiler_47.dll'
            if native_dll(destination):
                print('Native shader compiler already present in ' + directory + '.')
                continue
            source = self.download(name, 'https://raw.githubusercontent.com/mozilla/fxc2/master/dll/' + name, digest)
            self.replace(destination, source.read_bytes())
        font_dir = font_directory(self.bottle)
        installed_fonts = set()
        for name, digest in FONTS.items():
            source = self.download(name, 'https://raw.githubusercontent.com/pushcx/corefonts/master/' + name, digest)
            with tempfile.TemporaryDirectory(prefix='dcs-fonts-') as folder:
                self.run([self.runtime / 'bin/cabextract', '-q', '-d', folder, source])
                files = [path for path in Path(folder).rglob('*') if path.suffix.lower() == '.ttf']
                if not files:
                    raise SetupError('No fonts found in ' + name)
                for path in files:
                    destination = font_dir / path.name.lower()
                    self.replace(destination, path.read_bytes())
                    installed_fonts.add(destination)
        self.wine('cxinstallfonts.exe', *(windows_path(path) for path in sorted(installed_fonts)))
        problems = dependency_problems(self.bottle)
        if problems:
            raise SetupError('\n'.join(problems))

    def configure(self):
        game = find_game(self.bottle, self.args.game_dir)
        profile = find_profile(self.bottle, self.args.profile)
        options = profile / 'Config/options.lua'
        source = options if options.is_file() else game / 'MissionEditor/data/scripts/options.lua'
        if not source.is_file():
            raise SetupError('No stock or profile options.lua found: ' + str(source))
        # Validate the entire patch before changing the bottle or registry.
        patched = patch_options(source.read_bytes().decode('utf-8-sig')).encode('utf-8')
        font, font_data, multiplayer, multiplayer_data = self.compatibility_plan(game)
        renderer = game / 'bin/dx11backend.dll'
        renderer_data = None
        if self.graphics_backend == 'd3dmetal':
            if renderer.is_symlink():
                raise SetupError('Refusing a linked dx11backend.dll.')
            original_renderer = renderer.read_bytes()
            renderer_data = patch_d3dmetal(original_renderer)
        self.graphics()
        self.overrides()
        if renderer_data is not None:
            if renderer.read_bytes() != original_renderer:
                raise SetupError('Renderer changed during setup. Close DCS and its updater, then retry.')
            self.replace(renderer, renderer_data)
            print('D3DMetal startup guard verified; CrossOver DLSS bridge enabled.')
        self.replace(options, patched)
        if font_data is not None:
            self.replace(font, font_data)
            print('Installed Segoe UI Symbol for Apache cockpit loading.')
        else:
            print('Segoe UI Symbol already installed.')
        self.replace(multiplayer, multiplayer_data)
        print('Multiplayer slot/coalition VoiceChat guard verified.')
        print('DCS preferences configured: ' + str(options))
        print('Launch DCS.exe from CrossOver. Leave the Start Here button closed.')

    def check(self):
        problems = []
        if not (self.bottle / 'cxbottle.conf').is_file():
            print('Bottle does not exist: ' + str(self.bottle))
            return 1
        text = (self.bottle / 'cxbottle.conf').read_bytes().decode('utf-8')
        if conf_values(text, 'Bottle').get('Template') != 'win10_64':
            problems.append('Bottle is not Windows 10 64-bit')
        environment = conf_values(text, 'EnvironmentVariables')
        wanted = {'CX_GRAPHICS_BACKEND': self.graphics_backend, 'WINEMSYNC': '1'}
        if self.graphics_backend == 'd3dmetal':
            wanted.update(D3DM_ENABLE_METALFX='1', DXMT_ENABLE_NVEXT='1')
        for key, value in wanted.items():
            if environment.get(key) != value:
                problems.append(key + ' should be ' + value)
        values = registry_section(self.bottle / 'user.reg', r'Software\Wine\DllOverrides')
        for key, value in OVERRIDES.items():
            if values.get(key, '').replace(' ', '') != '"' + value + '"':
                problems.append('DLL override missing/wrong: ' + key)
        for key in ('nvapi', 'nvapi64'):
            if values.get(key) == '""':
                problems.append('Remove experimental empty ' + key + ' override')
        problems.extend(dependency_problems(self.bottle))
        try:
            font = apache_font_path(self.bottle)
            if not font.is_file():
                raise SetupError('Segoe UI Symbol missing: rerun setup (use --font if Office is not installed).')
            validate_apache_font(font.read_bytes())
        except (SetupError, OSError) as error:
            problems.append(str(error))
        try:
            game = find_game(self.bottle, self.args.game_dir)
            multiplayer = game / MULTIPLAYER_FILE
            data = multiplayer.read_bytes()
            if patch_multiplayer(data) != data:
                problems.append('Multiplayer slot/coalition VoiceChat guard missing; rerun setup.')
            print('DCS installation: ' + str(game))
            if self.graphics_backend == 'd3dmetal':
                renderer = game / 'bin/dx11backend.dll'
                data = renderer.read_bytes()
                if patch_d3dmetal(data) != data:
                    problems.append('D3DMetal startup guard missing; rerun setup.')
        except (SetupError, OSError) as error:
            problems.append(str(error))
        try:
            profile = find_profile(self.bottle, self.args.profile)
            preferences = preference_values((profile / 'Config/options.lua').read_bytes().decode('utf-8-sig'))
            for key, value in PREFERENCES.items():
                if preferences.get(key) != value:
                    problems.append('miscellaneous.' + key + ' should be ' + value)
        except (SetupError, FileNotFoundError) as error:
            problems.append(str(error))
        print('Bottle: ' + str(self.bottle))
        if problems:
            for problem in problems:
                print('  NEEDS ATTENTION: ' + problem)
            return 1
        print('PASS (configuration only): ' + self.graphics_backend + ' recipe, prerequisites, DLL overrides, '
              'startup preferences, Apache font, and multiplayer guard match.')
        return 0


def windows_path(path):
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def ensure_dcs_closed():
    process_list = subprocess.run(['/bin/ps', '-axo', 'comm='], capture_output=True, text=True)
    if process_list.returncode != 0:
        raise SetupError('Cannot check running processes. Run this script in Terminal outside a sandbox.')
    if any(line.strip().replace('\\', '/').rsplit('/', 1)[-1].lower() in ('dcs.exe', 'dcs_updater.exe', 'edcefrenderprocess.exe')
           for line in process_list.stdout.splitlines()):
        raise SetupError('Close DCS, its updater, and browser windows before running setup.')


def wizard(args):
    print('DCS World / CrossOver setup\n')
    print('1. Clean install into a new Windows 10 64-bit bottle')
    print('2. Apply all fixes to an existing DCS bottle')
    print('3. Check an existing bottle without changing anything')
    print('4. Undo the renderer/multiplayer guards and owned Apache font')
    print('5. Launch DCS with native crash logging (no setup changes)')
    choice = input('Choice [1]: ').strip() or '1'
    if choice not in ('1', '2', '3', '4', '5'):
        raise SetupError('Choose 1, 2, 3, 4, or 5')
    args.bottle = input('Full Mac path to bottle [' + str(DEFAULT_BOTTLE) + ']: ').strip().strip('"\'') or str(DEFAULT_BOTTLE)
    args.bottle = re.sub(r'\\([ ()])', r'\1', args.bottle)
    if choice == '1':
        args.install = True
        args.installer = input('Drag the downloaded DCS_World_web.exe here, then press Return: ').strip().strip('"\'')
        # Terminal drag-and-drop escapes spaces even when the filename is not quoted.
        args.installer = re.sub(r'\\([ ()])', r'\1', args.installer)
        if Path(args.bottle).expanduser().exists():
            args.resume = input('Bottle exists. Resume installation in it? [y/N]: ').strip().lower() == 'y'
    elif choice == '2':
        args.dependencies = input('Also download/install missing prerequisites and core fonts? [Y/n]: ').strip().lower() != 'n'
    elif choice == '3':
        args.check = True
    elif choice == '4':
        args.undo_compatibility = True
    else:
        args.launch_log = True
    if choice in ('1', '2'):
        entered = input('Optional path to seguisym.ttf [use installed font or local Office copy]: ').strip().strip('"\'')
        if entered:
            args.font = re.sub(r'\\([ ()])', r'\1', entered)
    return args


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bottle', default=str(DEFAULT_BOTTLE), help='Full Mac path to the bottle directory')
    parser.add_argument('--crossover', default='/Applications/CrossOver.app', help='Path to CrossOver.app')
    parser.add_argument('--installer', help='Path to the official downloaded DCS_World_web.exe')
    parser.add_argument('--install', action='store_true', help='Create bottle, install dependencies, run DCS installer, configure')
    parser.add_argument('--resume', action='store_true', help='Allow --install in an existing bottle without deleting it')
    parser.add_argument('--create', action='store_true', help='Create bottle if absent; may be used to prepare it before installing DCS')
    parser.add_argument('--dependencies', action='store_true', help='Install missing native runtimes, compilers, and core fonts')
    parser.add_argument('--game-dir', help='Full Mac path to a nonstandard DCS installation directory')
    parser.add_argument('--profile', help='Full Mac path to the Saved Games/DCS profile, if nonstandard')
    parser.add_argument('--font', help='Local Segoe UI Symbol seguisym.ttf; otherwise reuse the installed font or local Office copy')
    parser.add_argument('--graphics', choices=('d3dmetal', 'dxmt'), default='d3dmetal',
                        help='Setup/check recipe: D3DMetal with guarded renderer and DLSS bridge (default), or legacy DXMT')
    parser.add_argument('--log-backend', choices=('dxmt', 'd3dmetal', 'dxvk'),
                        help='Override the graphics backend for one --launch-log run only')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true', help='Read-only check of all fixes; no Wine or downloads')
    actions.add_argument('--undo-compatibility', action='store_true',
                         help='Restore the renderer/multiplayer guards and owned Apache font using matching backups')
    actions.add_argument('--launch-log', action='store_true',
                         help='Launch DCS with native crash logging; apply no setup changes (combine with --dry-run to preview)')
    parser.add_argument('--dry-run', action='store_true', help='Show planned actions; no changes, Wine, or downloads')
    parser.add_argument('--wizard', action='store_true', help='Interactive setup for the .command launcher')
    args = parser.parse_args(argv)
    if args.wizard:
        args = wizard(args)
    setup = Setup(args)
    if args.log_backend and not args.launch_log:
        raise SetupError('--log-backend requires --launch-log.')
    if args.check:
        return setup.check()
    if args.launch_log:
        if args.install or args.create or args.dependencies or args.installer:
            raise SetupError('--launch-log cannot be combined with installation/dependency options.')
        if not args.dry_run:
            ensure_dcs_closed()
        return setup.launch_logged(dry_run=args.dry_run, backend=args.log_backend)
    if args.undo_compatibility:
        if args.install or args.create or args.dependencies or args.installer:
            raise SetupError('--undo-compatibility cannot be combined with installation/dependency options.')
        if not args.dry_run:
            ensure_dcs_closed()
        try:
            return setup.undo_compatibility(dry_run=args.dry_run)
        finally:
            if setup.backup:
                setup.save_manifest()
                print('Recovery backup: ' + str(setup.backup))
    if args.install and not args.installer:
        raise SetupError('--install requires --installer with the downloaded official DCS installer.')
    if args.installer and not args.install:
        raise SetupError('--installer requires --install.')
    if args.install and setup.bottle.exists() and not args.resume:
        raise SetupError('Bottle already exists. Choose a new path or use --resume to keep and reuse it.')
    if args.installer and not Path(args.installer).expanduser().is_file():
        raise SetupError('DCS installer file not found: ' + args.installer)
    if args.dry_run:
        print('DRY RUN; no files changed and no processes launched.')
        print('Bottle: ' + str(setup.bottle))
        print('Create Windows 10 64-bit bottle if needed: ' + str(args.install or args.create))
        print('Download/install prerequisites: ' + str(args.install or args.dependencies))
        print('Run official DCS installer: ' + str(bool(args.installer)))
        print('Configure ' + args.graphics + ', MSync, four DLL overrides, and four DCS preferences.')
        if args.graphics == 'd3dmetal':
            print('Enable the CrossOver DLSS bridge and patch only the exact supported renderer (with backup).')
            try:
                renderer = find_game(setup.bottle, args.game_dir) / 'bin/dx11backend.dll'
                if renderer.is_symlink():
                    raise SetupError('Refusing a linked dx11backend.dll.')
                patch_d3dmetal(renderer.read_bytes())
                print('Renderer checksum matches the supported DCS 2.9.30.28738 original/patch.')
            except SetupError:
                if (setup.bottle / 'cxbottle.conf').exists() and not args.install:
                    raise
            except FileNotFoundError:
                if not (args.install or args.create):
                    raise SetupError('DCS renderer is missing; install DCS before configuring D3DMetal.')
        print('Install missing Segoe UI Symbol from --font or local Office; keep an existing valid font.')
        print('Apply the multiplayer slot/coalition guard only when the known callback needs it.')
        print('Back up modified files and selected DLL overrides inside the bottle.')
        return 0
    if sys.platform != 'darwin':
        raise SetupError('Installation/configuration requires macOS and CrossOver.')
    for executable in ('wine', 'cxbottle', 'cabextract'):
        if not (setup.runtime / 'bin' / executable).is_file():
            raise SetupError('CrossOver executable not found: ' + str(setup.runtime / 'bin' / executable))
    # Refuse to edit preferences while a game or installer is using them.
    ensure_dcs_closed()
    try:
        if not (setup.bottle / 'cxbottle.conf').is_file():
            if not (args.create or args.install):
                raise SetupError('Bottle not found. Use --create or --install, or correct --bottle.')
            if setup.bottle.exists():
                raise SetupError('Target exists but is not a valid bottle; choose an empty new path.')
            setup.bottle.parent.mkdir(parents=True, exist_ok=True)
            print('Creating Windows 10 64-bit bottle...', flush=True)
            setup.run([setup.runtime / 'bin/cxbottle', '--bottle', setup.bottle.name,
                       '--create', '--template', 'win10_64'], timeout=600)
        if args.install or args.create or args.dependencies:
            setup.graphics()
        if args.install or args.dependencies:
            setup.dependencies()
        problems = dependency_problems(setup.bottle)
        if problems:
            raise SetupError('\n'.join(problems) + '\nRerun with --dependencies to install these prerequisites.')
        if args.install:
            print('Opening the official DCS installer. Complete the download and close it when finished.', flush=True)
            setup.wine(windows_path(Path(args.installer).expanduser()), timeout=None, gui=True)
            if sys.stdin.isatty():
                input('When DCS installation is fully finished, leave DCS closed and press Return here: ')
        try:
            find_game(setup.bottle, args.game_dir)
        except SetupError:
            if args.create and not args.install:
                setup.overrides()
                print('Bottle prepared. Install DCS in this bottle, then rerun this script to configure its profile.')
                return 0
            raise
        setup.configure()
        status = setup.check()
        if status:
            raise SetupError('Final configuration check did not pass.')
        print('Setup complete. Start DCS from CrossOver and log in normally.')
        return 0
    finally:
        if setup.backup:
            setup.save_manifest()
            print('Backups and installer logs: ' + str(setup.backup))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SetupError, OSError, ValueError, subprocess.SubprocessError) as error:
        print('\nSetup stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nSetup cancelled. Existing bottle content was retained.', file=sys.stderr)
        sys.exit(130)
