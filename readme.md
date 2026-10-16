# DCS World on Apple Silicon with CrossOver

One setup tool now applies and checks the complete local compatibility recipe: **D3DMetal, the CrossOver DLSS bridge, MSync, DLL overrides, the guarded renderer patch, startup preferences, the multiplayer coalition/slot VoiceChat guard, and the Apache cockpit font dependency**. Use `setup_dcs_crossover.py` directly or the accompanying `Install DCS CrossOver.command` launcher. No separate patch installers are needed.

## Clean install using the script

1. Install and activate CrossOver in `/Applications/CrossOver.app`. You also need **Python 3.9 or newer**. The launcher uses an existing Python installation; if none is available, install the macOS package from [python.org](https://www.python.org/downloads/macos/). Homebrew is optional.
2. Download the official **DCS World web installer** from [Eagle Dynamics](https://www.digitalcombatsimulator.com/en/downloads/world/). Save `DCS_World_web.exe` in Downloads. Leave enough disk space for the game and your selected modules.
3. Make sure Segoe UI Symbol (`seguisym.ttf`) is available locally: the script can reuse it from this bottle, copy it from installed Microsoft Word/Excel/PowerPoint, or accept a path with `--font`. The font is not included or downloaded. Extract `DCS-CrossOver-Setup.zip` and keep its three files together. Close DCS and its updater, and quit the CrossOver interface so it cannot overwrite bottle settings during setup.
4. Double-click **Install DCS CrossOver.command**, choose **1**, accept the default bottle path or enter a new one, and drag the downloaded DCS installer into Terminal when prompted. If Finder refuses to open the launcher, run the Python command below from Terminal.
5. The script creates a **Windows 10 64-bit** bottle, selects **D3DMetal, DLSS support, and MSync**, installs prerequisites, and opens the DCS installer. Complete its license, download, installation-location, and module choices. Use the default `C:\Program Files\Eagle Dynamics\DCS World` location. **Leave “Launch DCS” unchecked at the end.** Close the installer and return to Terminal when asked.
6. The script applies the DLL overrides, creates the Saved Games profile from DCS's stock defaults if needed, changes the startup preferences, installs the missing Apache font, applies the multiplayer and version-checked renderer guards, and checks the whole recipe. Once it prints **Setup complete**, reopen CrossOver, select the new bottle, and use **Run Command** to run `C:\Program Files\Eagle Dynamics\DCS World\bin\DCS.exe`. Log in normally. Keep the **Start Here** button closed.

The default new bottle is `~/Library/Application Support/CrossOver/Bottles/DCS World Clean`. Your existing bottle is not selected automatically. The script handles bottle setup, prerequisite downloads, and the compatibility settings; CrossOver licensing, the official DCS download wizard, and DCS account login remain interactive.

For a Terminal installation, open Terminal in the extracted folder and run:

```sh
python3 setup_dcs_crossover.py \
  --install \
  --installer "$HOME/Downloads/DCS_World_web.exe"
```

To resume an interrupted installation in the same bottle, add `--resume`. The script retains the existing bottle and its game download. If the DCS installer itself needs to resume downloading, follow its prompts.

## Settings to reproduce manually

Create a Windows 10 64-bit bottle and install standalone DCS. Before starting DCS, install these prerequisites in that bottle:

| Prerequisite | What the script installs |
| --- | --- |
| Visual C++ v14 runtime | Microsoft's current x64 **and** x86 redistributables; existing registered native runtimes are retained |
| DirectX shader compiler | Native `d3dcompiler_47.dll` in `system32` (64-bit) and `syswow64` (32-bit) |
| Microsoft core fonts | Arial, Times New Roman, Courier New, Verdana, and the remaining core-font packages |
| Apache cockpit font | Segoe UI Symbol (`seguisym.ttf`), copied from a local Office installation or `--font`; a valid existing copy is retained |

Microsoft documents the [runtime downloads](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170) and [installation options](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170). The script obtains shader compilers from the [Mozilla fxc2 repository](https://github.com/mozilla/fxc2/tree/master/dll), the same downloads referenced by the installed CrossOver recipes. Font downloads and checksums follow [upstream Winetricks package metadata](https://github.com/Winetricks/winetricks/blob/master/src/winetricks). No Windows binaries are bundled in this package.

You can automate just bottle creation and prerequisites, then install DCS yourself in CrossOver:

```sh
python3 setup_dcs_crossover.py --create --dependencies
```

After installing DCS, rerun `python3 setup_dcs_crossover.py` to configure its profile.

In the bottle's Advanced Settings, use **Graphics: D3DMetal**, **DLSS on**, and **MSync on**. CrossOver's DLSS switch enables its MetalFX bridge; DCS must also select DLSS in its own graphics settings. Choose **Upscaling: DLSS** and **Quality** there. Setup enables the bridge but preserves your existing in-game resolution, antialiasing, and upscaling choices. D3DMetal DLSS needs Apple Silicon and macOS Tahoe or later in CrossOver 26; this installation uses macOS 27. CodeWeavers documents [the graphics, DLSS, and MSync switches](https://support.codeweavers.com/en_US/advanced-settings-in-crossover-mac-26).

The equivalent bottle entries are:

```ini
[EnvironmentVariables]
"CX_GRAPHICS_BACKEND" = "d3dmetal"
"WINEMSYNC" = "1"
"D3DM_ENABLE_METALFX" = "1"
"DXMT_ENABLE_NVEXT" = "1"
```

The two DLSS keys are the settings used by CrossOver 26's own switch. Setup does not replace or modify CrossOver's application or graphics libraries. Use the patched `bin/DCS.exe` installation, rather than an older `bin-mt` installation.

Open **Wine Configuration → Libraries** in the bottle and add these exact DLL names and load orders. Alternatively, import these values into `HKEY_CURRENT_USER\Software\Wine\DllOverrides` using the bottle's Registry Editor:

| DLL name | Registry value | Wine Configuration load order |
| --- | --- | --- |
| `wbemprox` | `native` | Native (Windows) only |
| `msdmo` | `native` | Native (Windows) only |
| `winhttp` | `native,builtin` | Native, then Builtin |
| `d3dcompiler_47` | `native,builtin` | Native, then Builtin |

Enter only the DLL name in the name field. Names such as `msdmo (native)` are incorrect. The native-only `wbemprox` and `msdmo` entries intentionally prevent the Wine built-in modules from loading; **do not download replacement DLLs for them**. The unsuccessful experiment that disabled `nvapi` and `nvapi64` was reverted. Do not add disabled NVAPI entries.

Inside the bottle, edit:

```text
drive_c/users/crossover/Saved Games/DCS/Config/options.lua
```

If it does not exist yet, copy the installed game's `MissionEditor/data/scripts/options.lua` there first. Change or add these keys **inside its existing `miscellaneous` table**:

```lua
["launcher"] = false,
["collect_stat"] = false,
["collect_stat_defined"] = true,
["push_starthere"] = false,
```

`launcher=false` bypasses the web launcher. The two statistics settings disable anonymous statistics and prevent the permission prompt. `push_starthere=false` suppresses the automatic Start Here popup. The embedded browser behind those startup screens caused Wine crashes in our tests; manually clicking **Start Here** can still open it.

The `msdmo` workaround also prevented the built-in **VoiceChat** module from loading in our logs, so DCS's built-in voice chat may be unavailable. This setup does not establish VR or third-party voice-chat compatibility.

## D3DMetal renderer startup guard

The supplied patch was reviewed as code, without running its separate installer. Disassembly confirms that `DX11Renderer::turnOffSpecificWarnings` calls `QueryInterface` for an optional Direct3D debug interface and reads the output pointer without checking its HRESULT. The integrated patch branches to the existing function exit when the query fails. It changes 13 bytes at file offset `0x1A83F` in `bin/dx11backend.dll`:

| State | SHA-256 |
| --- | --- |
| Original DCS 2.9.30.28738 | `e66f5b1c8a2f22b909ddeddbd3e12049a58962035aeb544b32e5314509c54ae3` |
| Patched | `389ffe5eb81341092ce3004eb4b86bfbfe3b7cf3dfb143b212223e7e8e968697` |

Setup checks the whole original DLL, patch-site bytes, and whole resulting DLL before writing. A matching installed patch is kept. An unknown or updated renderer stops D3DMetal configuration; the version number or filename alone is insufficient. The original goes into the same backup manifest as the other changes, and `--undo-compatibility` restores it. No game DLL is included in the repository or ZIP.

DCS updates or repairs can replace both the renderer patch and multiplayer guard. Never restore an older renderer over a game update. An unknown renderer needs a new investigation. `--graphics dxmt` selects the previous startup recipe and skips the renderer patch; it is available for comparison, but **DXMT still reproduced the Apache Metal assertion in this bottle**. Pass the same `--graphics dxmt` option to checks/previews when inspecting that recipe. Server integrity acceptance of the local renderer/Lua changes remains untested.

## Multiplayer coalition/slot guard and Apache cockpit font

The multiplayer guard and font are part of every full configuration run, including configuration after a clean installation. `--check` verifies both, and `--dry-run` lists them without changing files or launching processes.

The multiplayer fix adds an early return to `onPlayerChangeSlot(id)` in `MissionEditor/modules/mul_voicechat.lua` only when `voice_chat` is `nil`. This prevents the missing VoiceChat module from breaking coalition/slot selection. When VoiceChat is available, the existing callback continues unchanged. This does **not** repair VoiceChat itself. The script preserves the file's line endings, recognizes the already-installed guard, backs up any changed Lua file, and refuses unfamiliar callback layouts. DCS updates/repairs can overwrite the guard; rerun the same setup command afterward. Acceptance by a particular server's integrity check has not been separately established.

The Apache font step supplies the missing Segoe UI Symbol font inside the bottle's Windows Fonts directory. Its internal TrueType family name must identify as `Segoe UI Symbol`; arbitrary files renamed to `seguisym.ttf` are rejected. A [first-hand Wine installation report](https://github.com/oliverw/dcs-linux-installer/blob/main/docs/manual-install.md#3b-segoe-fonts--required-for-the-ah-64d) documents a missing-Segoe Apache crash. A gameplay retry with this font installed still crashed in this bottle. The font addresses a known Wine dependency, but it did not resolve this crash; native logging subsequently identified the DXMT dual-source/MRT assertion described above. The `MFD_LCD_AH64_*` missing-texture messages alone do not establish corrupt game textures.

A valid font already installed in this bottle is kept. Otherwise setup checks the local Word, Excel, and PowerPoint font directories, in that order. To supply your own local copy, use the **same setup command** with a source path:

```sh
python3 setup_dcs_crossover.py --bottle "$HOME/Crossover/DCS World" \
  --font "/path/to/seguisym.ttf"
```

The launcher also accepts an optional font path. No Microsoft font binaries are bundled in this repository or ZIP.

## Configure or check an existing installation

Close DCS before configuring it. Select **2** in the launcher, or run:

```sh
python3 setup_dcs_crossover.py --bottle "$HOME/Crossover/DCS World"
```

This is the path of the bottle that worked in this session. Substitute the appropriate Mac path on another machine. Add `--dependencies` if prerequisite installation is also needed. Other graphics, controls, account, and module preferences are preserved. The script preserves unrelated preferences. Its only shipped-Lua change is the multiplayer guard; the D3DMetal recipe also makes the exact renderer change above.

Select **3** in the launcher, or use this **read-only check**:

```sh
python3 setup_dcs_crossover.py --check --bottle "$HOME/Crossover/DCS World"
```

Check mode covers the selected graphics recipe, DLSS bridge keys and exact patched renderer for D3DMetal, prerequisites, DLL overrides, startup preferences, Segoe UI Symbol font, and multiplayer guard. It reads files only: it does not start Wine, change settings, or download anything. Its PASS result confirms the expected settings and files; it does not test a flight or guarantee compatibility with a different release.

Preview proposed work without changing anything:

```sh
python3 setup_dcs_crossover.py --dry-run --bottle "$HOME/Crossover/DCS World"
```

For nonstandard locations, add `--crossover "/path/to/CrossOver.app"`, `--game-dir "/full/Mac/path/to/DCS World"`, or `--profile "/full/Mac/path/to/Saved Games/DCS"`. `--profile` is the profile directory containing `Config`, not `options.lua` itself. Use it for a profile selected by a custom DCS launch argument. The script stops if it finds multiple candidate installations or profiles.

## Capture an unresolved crash

Use the same main tool to start DCS with CrossOver native exception and DLL logging. This mode applies no fixes and does not change graphics settings, preferences, or DLL overrides. It requires DCS and its updater to be closed first.

From the bottle root:

```sh
# Preview only: no files or processes are created.
python3 dcs/setup_dcs_crossover.py --bottle "$PWD" --launch-log --dry-run

# Start DCS, then reproduce the failing Apache slot.
python3 dcs/setup_dcs_crossover.py --bottle "$PWD" --launch-log
```

When using the extracted package directly, omit the `dcs/` prefix. Alternatively, choose **5** in `Install DCS CrossOver.command`. Keep the launching terminal open until DCS exits.

Add `--log-backend dxmt` or `--log-backend d3dmetal` for a single-run backend comparison without saving a backend change. This does not install or remove the renderer patch.

Each logged run gets its own directory under `<bottle>/.dcs-crossover-setup/diagnostics/<timestamp>-<id>/`. It contains `CrossOver.cxlog` (native Wine exceptions and DLL loading), `launcher.log`, `run.json` (command, backend, synchronization setting, and exit code), and copies of `dcs.log` before/after the run when available. These are local diagnostic files; keep them outside the Git repository. An exit code alone does not establish that the aircraft loaded successfully. Use the crash trace and actual gameplay result.

## Backups and recovery

Each configuration run stores backups and a manifest in:

```text
<bottle>/.dcs-crossover-setup/backups/<timestamp>-<unique-id>/
```

The script prints the full directory when it finishes or stops. `manifest.json` lists every replaced file and its corresponding backup. Only files that actually change are copied, including the multiplayer Lua file, renderer DLL, and bottle graphics settings. A newly installed Apache font is recorded with `created: true` and its installed SHA-256; existing fonts are never overwritten. `restore-dll-overrides.reg` restores just the DLL entries changed by that run. Configuration is repeatable; it does not delete the bottle, clear caches, reset controls, or copy account credentials.

To restore a change, close DCS and CrossOver, then copy the relevant backed-up file to the destination listed in the manifest. If `created` is true, there was no original file; removing that newly created file reverses its creation. Import `restore-dll-overrides.reg` through the same bottle's Registry Editor to undo its registry changes. If you changed settings afterward, review the backup first so you retain those later preferences.

To undo the renderer guard, multiplayer guard, and Apache font installed by these tools, use the main script or select **4** in the launcher:

```sh
python3 setup_dcs_crossover.py --bottle "$HOME/Crossover/DCS World" \
  --undo-compatibility --dry-run
python3 setup_dcs_crossover.py --bottle "$HOME/Crossover/DCS World" \
  --undo-compatibility
```

The preview reads files only. Undo requires DCS and its updater to be closed, checks all recovery files before changing any, and only restores/removes files with matching backups or ownership hashes. Pre-existing fonts with no setup ownership record are kept. Undo itself creates a recovery backup. If restoring the original renderer while D3DMetal is selected, it switches the backend to DXMT so the unpatched renderer is not launched with D3DMetal. Other bottle settings, DLL overrides, preferences, and prerequisites stay in place. A newer renderer from a game update is retained. A normal configuration run reapplies the selected recipe.

The same undo command supports installations made by the former separate tools: it reads the matching `.blue-coalition-<hash>.bak` beside `mul_voicechat.lua` and `.dcs-crossover-setup/apache-font.json`. It also accepts the supplied D3DMetal installer's `.d3dmetal-original-2.9.30.28738` backup when its full original hash matches. Keep historical backups/receipts even though the separate helper scripts have been removed.

These backups **do not uninstall Visual C++ or reverse the DCS installation**. Keep the new clean bottle separate from your working bottle if you are testing a fresh installation. Downloads are cached under `<bottle>/.dcs-crossover-setup/downloads/`; shader and font files are checked against pinned SHA-256 hashes, while Visual C++ uses Microsoft's HTTPS download links and is verified after installation.

If an update brings back the startup crashes, close DCS, rerun the configuration command for its bottle, and run `--check`. If it still crashes, inspect the newest `<profile>/Logs/dcs.log` and a new CrossOver log. A failure before `dcs.log` is created needs the CrossOver log. Reinstalling unrelated DLLs or applying the abandoned NVAPI experiment is not part of this setup.

## Validation of this package

Run the isolated regression suite from the bottle root:

```sh
python3 -B -m unittest discover -s dcs/tests -v
```

The combined suite covers the multiplayer/font fixes, the guarded renderer patch and its exact output hash, D3DMetal/DLSS configuration, unknown-renderer rejection, renderer backup recovery, LF/CRLF preservation, repeated configuration, existing fonts, malformed/wrong-font rejection, unfamiliar Lua callbacks, preflight failures without configuration changes, read-only modes, guarded undo, recovery of fixes installed by the previous tools, and logged-launch capture without applying configuration changes. Test bottles live in temporary directories; Wine, installers, and the live game are not started. The refreshed ZIP contains the same setup script, launcher, and clean-install guide as the source files.

The original setup was checked against the existing bottle, with earlier fixtures for configuration parsing, selected registry edits, dependencies, and download checksums. Those historical checks are separate from the combined regression suite. Full fresh-bottle creation, runtime installers, font registration, and the complete DCS installer flow have not been run end to end. The combined check establishes file/configuration state. The logged D3DMetal startup and user-confirmed Apache multiplayer cockpit result above are separate runtime evidence; they do not establish long-duration stability or every aircraft/server. The script stops on a failed operation and reports its backup location.
