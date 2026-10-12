# DCS World on Apple Silicon with CrossOver

This package reproduces the settings that got standalone DCS World running on an **M4 Max, macOS 27.0, CrossOver 26.3.0.39832, and DCS 2.9.30.28738** on 12 October 2026. The key choices were **DXMT, MSync, selected DLL overrides, and disabling three startup screens/prompts**.

The existing installation works. The script was checked against that bottle and tested with temporary fixtures; a complete installation into a fresh bottle has **not** been tested. Other DCS or CrossOver versions may need adjustments. This procedure targets the standalone edition; it does not set up Steam or VR.

## Clean install using the script

1. Install and activate CrossOver in `/Applications/CrossOver.app`. You also need **Python 3.9 or newer**. The launcher uses an existing Python installation; if none is available, install the macOS package from [python.org](https://www.python.org/downloads/macos/). Homebrew is optional.
2. Download the official **DCS World web installer** from [Eagle Dynamics](https://www.digitalcombatsimulator.com/en/downloads/world/). Save `DCS_World_web.exe` in Downloads. Leave enough disk space for the game and your selected modules.
3. Extract `DCS-CrossOver-Setup.zip`. Keep its three files together. Close DCS and its updater, and quit the CrossOver interface so it cannot overwrite bottle settings during setup.
4. Double-click **Install DCS CrossOver.command**, choose **1**, accept the default bottle path or enter a new one, and drag the downloaded DCS installer into Terminal when prompted. If Finder refuses to open the launcher, run the Python command below from Terminal.
5. The script creates a **Windows 10 64-bit** bottle, selects **DXMT and MSync**, installs prerequisites, and opens the DCS installer. Complete its license, download, installation-location, and module choices. Use the default `C:\Program Files\Eagle Dynamics\DCS World` location. **Leave “Launch DCS” unchecked at the end.** Close the installer and return to Terminal when asked.
6. The script applies the DLL overrides, creates the Saved Games profile from DCS's stock defaults if needed, changes the startup preferences, and checks the result. Once it prints **Setup complete**, reopen CrossOver, select the new bottle, and use **Run Command** to run `C:\Program Files\Eagle Dynamics\DCS World\bin\DCS.exe`. Log in normally. Keep the **Start Here** button closed.

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

Microsoft documents the [runtime downloads](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170) and [installation options](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170). The script obtains shader compilers from the [Mozilla fxc2 repository](https://github.com/mozilla/fxc2/tree/master/dll), the same downloads referenced by the installed CrossOver recipes. Font downloads and checksums follow [upstream Winetricks package metadata](https://github.com/Winetricks/winetricks/blob/master/src/winetricks). No Windows binaries are bundled in this package.

You can automate just bottle creation and prerequisites, then install DCS yourself in CrossOver:

```sh
python3 setup_dcs_crossover.py --create --dependencies
```

After installing DCS, rerun `python3 setup_dcs_crossover.py` to configure its profile.

In the bottle's Advanced Settings, choose **Graphics: DXMT** and turn **MSync on**. These match our successful setup; D3DMetal failed at graphics initialization during our tests. CodeWeavers describes [DXMT and MSync in CrossOver 26](https://support.codeweavers.com/en_US/advanced-settings-in-crossover-mac-26).

The equivalent entries in the bottle's `cxbottle.conf` are:

```ini
[EnvironmentVariables]
"CX_GRAPHICS_BACKEND" = "dxmt"
"WINEMSYNC" = "1"
```

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

## Configure or check an existing installation

Close DCS before configuring it. Select **2** in the launcher, or run:

```sh
python3 setup_dcs_crossover.py --bottle "$HOME/Crossover/DCS World"
```

This is the path of the bottle that worked in this session. Substitute the appropriate Mac path on another machine. Add `--dependencies` if prerequisite installation is also needed. Other graphics, controls, account, and module preferences are preserved. The script modifies the profile configuration rather than the game's shipped Lua scripts.

Select **3** in the launcher, or use this **read-only check**:

```sh
python3 setup_dcs_crossover.py --check --bottle "$HOME/Crossover/DCS World"
```

Check mode reads files only: it does not start Wine, change settings, or download anything. Its PASS result confirms the expected settings and files; it does not test a flight or guarantee compatibility with a different release.

Preview proposed work without changing anything:

```sh
python3 setup_dcs_crossover.py --dry-run --bottle "$HOME/Crossover/DCS World"
```

For nonstandard locations, add `--crossover "/path/to/CrossOver.app"`, `--game-dir "/full/Mac/path/to/DCS World"`, or `--profile "/full/Mac/path/to/Saved Games/DCS"`. `--profile` is the profile directory containing `Config`, not `options.lua` itself. Use it for a profile selected by a custom DCS launch argument. The script stops if it finds multiple candidate installations or profiles.

## Backups and recovery

Each configuration run stores backups and a manifest in:

```text
<bottle>/.dcs-crossover-setup/backups/<timestamp>-<unique-id>/
```

The script prints the full directory when it finishes or stops. `manifest.json` lists every replaced file and its corresponding backup. Only files that actually change are copied. `restore-dll-overrides.reg` restores just the DLL entries changed by that run. Configuration is repeatable; it does not delete the bottle, clear caches, reset controls, or copy account credentials.

To restore a change, close DCS and CrossOver, then copy the relevant backed-up file to the destination listed in the manifest. If `created` is true, there was no original file; removing that newly created file reverses its creation. Import `restore-dll-overrides.reg` through the same bottle's Registry Editor to undo its registry changes. If you changed settings afterward, review the backup first so you retain those later preferences.

These backups **do not uninstall Visual C++ or reverse the DCS installation**. Keep the new clean bottle separate from your working bottle if you are testing a fresh installation. Downloads are cached under `<bottle>/.dcs-crossover-setup/downloads/`; shader and font files are checked against pinned SHA-256 hashes, while Visual C++ uses Microsoft's HTTPS download links and is verified after installation.

If an update brings back the startup crashes, close DCS, rerun the configuration command for its bottle, and run `--check`. If it still crashes, inspect the newest `<profile>/Logs/dcs.log` and a new CrossOver log. A failure before `dcs.log` is created needs the CrossOver log. Reinstalling unrelated DLLs or applying the abandoned NVAPI experiment is not part of this setup.

## Validation of this package

The read-only check passed against the working bottle. Both downloaded shader compilers match its installed files byte for byte. All eleven font-package downloads passed their pinned checksum checks and were extracted with CrossOver's bundled `cabextract`. Temporary fixture tests cover missing profiles, preservation of other settings and comments, CRLF line endings, repeated configuration, selective registry changes, backup manifests, invalid Lua input, checksum rejection, paths containing spaces, and read-only execution.

The fresh CrossOver bottle creation, runtime installers, font registration, and complete DCS installer flow have not been run end to end. The script stops on a failed command or failed configuration check and reports where its backups and installer logs are stored.

