# The programs AI PC drives

Programs that are not installed the usual way (Office and JianYing are) live as portable copies in the project's
`tools/` folder, one folder each. They are not in the repository: each was downloaded from its publisher and checked
before it was unpacked (the SHA-256 against the publisher's published value, and the publisher's signature where it
signs: Authenticode, GPG, or a second source such as the Scoop or winget manifests). Installers are unpacked rather
than run where possible (`msiexec /a`, 7-Zip, innoextract), and each program's settings are kept inside its own folder
so nothing is written to AppData.

Python wheels go through [scripts/safe_wheels.py](../scripts/safe_wheels.py): the exact version from PyPI, its hash
checked, its contents listed and read, then an offline install.

A program that is missing makes only its own requests fail, with a message that says what is missing.

| Folder | Used by |
|---|---|
| `tools/7zip/` | [sevenzip](../src/ai_pc/apps/sevenzip.py) |
| `tools/android/` | [androidstudio](../src/ai_pc/apps/androidstudio.py) |
| `tools/arduino/` | [arduino](../src/ai_pc/apps/arduino.py) |
| `tools/audacity/` | [audacity](../src/ai_pc/apps/audacity.py) |
| `tools/autohotkey/` | [autohotkey](../src/ai_pc/apps/autohotkey.py) |
| `tools/blender/` | [blender](../src/ai_pc/three/blender.py) |
| `tools/calibre/` | [calibre](../src/ai_pc/apps/calibre.py) |
| `tools/cloudflared/` | [mediahost](../src/ai_pc/social/mediahost.py), [tunnel_setup](../src/ai_pc/social/tunnel_setup.py) |
| `tools/cmake/` | [clion](../src/ai_pc/apps/clion.py) |
| `tools/dotnet/` | [visualstudio](../src/ai_pc/apps/visualstudio.py) |
| `tools/drawio/` | [drawio](../src/ai_pc/apps/drawio.py) |
| `tools/flutter/` | [flutter](../src/ai_pc/apps/flutter.py) |
| `tools/freecad/` | [freecad](../src/ai_pc/apps/freecad.py) |
| `tools/gimp-portable/` | [gimp](../src/ai_pc/apps/gimp.py) |
| `tools/go/` | [goland](../src/ai_pc/apps/goland.py) |
| `tools/godot/` | [godot](../src/ai_pc/apps/godot.py) |
| `tools/gradle/` | [androidstudio](../src/ai_pc/apps/androidstudio.py) |
| `tools/handbrake/` | [handbrake](../src/ai_pc/apps/handbrake.py) |
| `tools/jdk/` | [androidstudio](../src/ai_pc/apps/androidstudio.py), [intellij](../src/ai_pc/apps/intellij.py) |
| `tools/jianying/` | [jy_export](../src/ai_pc/video/jy_export.py) |
| `tools/js/` | [aftereffects](../src/ai_pc/apps/aftereffects.py) |
| `tools/keepassxc/` | [keepassxc](../src/ai_pc/apps/keepassxc.py) |
| `tools/kicad/` | [kicad](../src/ai_pc/apps/kicad.py) |
| `tools/krita/` | [krita](../src/ai_pc/apps/krita.py) |
| `tools/libreoffice/` | [libreoffice](../src/ai_pc/apps/libreoffice.py) |
| `tools/llama.cpp/` | [config](../src/ai_pc/core/config.py) |
| `tools/llvm-mingw/` | [clion](../src/ai_pc/apps/clion.py), [rustrover](../src/ai_pc/apps/rustrover.py) |
| `tools/lmms/` | [lmms](../src/ai_pc/apps/lmms.py) |
| `tools/maven/` | [intellij](../src/ai_pc/apps/intellij.py) |
| `tools/mongodb/` | [mongodb](../src/ai_pc/apps/mongodb.py) |
| `tools/musescore-portable/` | [musescore](../src/ai_pc/apps/musescore.py) |
| `tools/mysql/` | [mysql](../src/ai_pc/apps/mysql.py) |
| `tools/ninja/` | [clion](../src/ai_pc/apps/clion.py) |
| `tools/octave/` | [matlab](../src/ai_pc/apps/matlab.py) |
| `tools/openscad/` | [openscad](../src/ai_pc/apps/openscad.py) |
| `tools/php/` | [php](../src/ai_pc/apps/php.py) |
| `tools/postgres/` | [postgres](../src/ai_pc/apps/postgres.py) |
| `tools/powerbi/` | [powerbi](../src/ai_pc/apps/powerbi.py) |
| `tools/prusaslicer/` | [prusaslicer](../src/ai_pc/apps/prusaslicer.py) |
| `tools/python/` | [pycharm](../src/ai_pc/apps/pycharm.py) |
| `tools/qgis/` | [qgis](../src/ai_pc/apps/qgis.py) |
| `tools/r/` | [rstats](../src/ai_pc/apps/rstats.py) |
| `tools/rawtherapee/` | [rawtherapee](../src/ai_pc/apps/rawtherapee.py) |
| `tools/rust/` | [rustrover](../src/ai_pc/apps/rustrover.py) |
| `tools/shotcut/` | [shotcut](../src/ai_pc/apps/shotcut.py) |
| `tools/tectonic/` | [latex](../src/ai_pc/apps/latex.py) |

## Checking what is here

`ai-pc doctor` looks for each program the same way the code that uses it does and reads its version without starting
anything that could open a window. It also checks the models, the two Python environments, and the packages in them
against `pyproject.toml` and `services/tinyclick/requirements.txt`. It exits with 1 when something required is missing.

```powershell
uv run ai-pc doctor           # a table: programs in tools/, programs installed on Windows, models, environments, packages
uv run ai-pc doctor --json    # the same as JSON, with paths
```

It also names any folder in `tools/` that no code uses.
