# Setting up Claude Code to drive KiCad

This guide shows how to let Claude Code operate KiCad: draw schematics, lay out PCBs, run DRC/ERC, and export manufacturing files (Gerber, drill, BOM).

Paths below are for macOS (Apple Silicon or Intel). For Windows and Linux, see the [MCP server's README](https://github.com/mixelpixx/KiCAD-MCP-Server).

---

## 1. Requirements

| Item | Version | Notes |
|------|---------|-------|
| KiCad | **10.0 or later** (tested: 10.0.6) | Must be KiCad 10, not 9.x (see below) |
| Node.js | 18 or later | Check with `node --version` |
| Claude Code | installed | `claude mcp` must work |

### KiCad must be 10.x

The `main` branch of [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) writes schematics in the **KiCad 10 file format**. With KiCad 9.x, `kicad-cli` cannot read these files, and ERC fails with a "failed to load schematic" error.

If you have KiCad 9.x, install the latest stable 10.0.x from https://www.kicad.org/download/.

---

## 2. Install the MCP server

### 2.1 Clone it outside any cloud-synced folder

```bash
mkdir -p ~/mcp-servers
cd ~/mcp-servers
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
```

> **Why not in iCloud, Dropbox or Google Drive:** the server creates `node_modules` and a Python `venv` with tens of thousands of small files. In a synced folder they slow down syncing and can cause conflicts. Keep your actual design files (`.kicad_pro`, `.kicad_sch`, `.kicad_pcb`) in your normal working folder.

### 2.2 Create a Python environment with KiCad's bundled Python

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  -m venv venv --system-site-packages
```

`--system-site-packages` is essential. Without it, Python cannot find KiCad's bundled `pcbnew` module.

### 2.3 Install dependencies and build

```bash
source venv/bin/activate
pip install -r requirements.txt
npm install    # also runs the build (tsc)
deactivate
```

Check the build:

```bash
ls dist/index.js   # should exist
```

---

## 3. Register with Claude Code

### 3.1 The KiCad MCP server

Find the version of KiCad's bundled Python (it can differ between machines):

```bash
ls /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/
# if this prints 3.9, use 3.9 in the command below
```

```bash
claude mcp add --scope user kicad \
  --env KICAD_PYTHON=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  --env PYTHONPATH=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/lib/python3.9/site-packages \
  --env LOG_LEVEL=info \
  --env KICAD_BACKEND=auto \
  -- node ~/mcp-servers/KiCAD-MCP-Server/dist/index.js
```

Check the connection:

```bash
claude mcp list
# expected: kicad: ... - ✔ Connected
```

### 3.2 (Recommended) A part search MCP server

[pcbparts-mcp](https://pcbparts.dev/) is a separate remote service. It searches parts that JLCPCB, Mouser and DigiKey actually stock, finds alternatives, and fetches matching KiCad footprints, so you avoid parts a fab cannot source:

```bash
claude mcp add --transport http --scope user pcbparts https://pcbparts.dev/mcp
```

No key and no install needed.

### 3.3 Enable KiCad's IPC API (recommended, optional)

In KiCad: Preferences → Plugins → **Enable IPC API Server**.

This lets the server use KiCad's official live API (IPC), which avoids some caching problems. Without it, the server falls back to file-level operations (SWIG backend). Several pitfalls below are related to this.

### 3.4 Restart Claude Code

**A newly added MCP server only appears in a new session.** Restart your terminal or start a new Claude Code session.

---

## 4. Check the installation

In a new Claude Code session, ask:

> Use `check_kicad_ui` to check that the KiCad MCP connection works.

It should report `"running": true`. `ipc_connected` depends on whether you enabled the IPC API.

---

## 5. For every new project

### 5.1 Register standard libraries the first time you use them

`create_project` does not register symbol and footprint libraries for the project. The first time a project uses `Device`, `power`, `Resistor_THT` and so on, Claude must call `register_symbol_library` / `register_footprint_library` with `scope=project`. Otherwise ERC shows many "library not found" warnings, and syncing to the PCB silently skips the footprints.

Claude usually handles this itself. It is listed here so you know what is happening when you see these warnings.

### 5.2 Add PWR_FLAG to power nets

If a power net such as +5V or GND is driven by no pin of type "power output" (for example, a circuit with only resistors and LEDs), ERC reports "Input Power pin not driven". This is normal KiCad behaviour. Add a `power:PWR_FLAG` to each such net.

---

## 6. From schematic to manufacturing files

Claude can do all of these steps. The result can be uploaded directly to fabs such as JLCPCB or PCBWay.

1. Create the project and draw the schematic (place parts, connect them)
2. Run ERC (Electrical Rules Check)
3. Sync the schematic to the PCB (`sync_schematic_to_board`)
4. Add the board outline, place parts, route (Freerouting autorouter or manual)
5. Run DRC (Design Rules Check)
6. Export manufacturing files:
   - Gerber (copper, mask, silkscreen, outline)
   - Excellon drill files
   - BOM (CSV)
   - Pick-and-place positions (CSV)
7. Zip the Gerber and drill files. Most fabs take this zip directly; BOM and position files are usually uploaded separately.

---

## 7. Common problems

### After upgrading KiCad, PCB operations fail silently

**Cause:** the MCP server's Python process starts with the Claude Code session and keeps running. Replacing the KiCad app does not reload `pcbnew` in that process. It keeps the old behaviour, and footprint loading fails without a clear error.

**Fix:** after upgrading KiCad, **restart the Claude Code session** so the MCP server starts a new Python process.

ERC is not affected, because each run starts a new `kicad-cli` process.

### Pressing 3D View in KiCad shows nothing

**Cause:** with the file-level (SWIG) backend, changes are not pushed to a KiCad window you have open. Also, macOS sometimes restores the 3D Viewer window at its last position, for example on an external display that is no longer connected, so the window is open but off-screen.

**Check** (the window name depends on KiCad's language; it is "3D Viewer" in English):

```bash
osascript -e '
tell application "System Events"
  tell process "KiCad"
    repeat with w in windows
      if name of w is "3D Viewer" then
        set {px, py} to position of w
        return "position: " & px & "," & py
      end if
    end repeat
  end tell
end tell'
```

A very large or negative x (for example -1867) means the window is off-screen.

**Fix:** move it back:

```bash
osascript -e '
tell application "System Events"
  tell process "KiCad"
    repeat with w in windows
      if name of w is "3D Viewer" then
        set position of w to {100, 100}
        set size of w to {1400, 900}
      end if
    end repeat
  end tell
end tell
tell application "KiCad" to activate'
```

**Alternative:** skip the GUI and ask Claude to render the 3D view to a PNG with `kicad-cli`:

```bash
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render \
  --output board.png --width 1600 --height 1200 \
  --quality high --floor --rotate "-30,0,-30" --background opaque \
  your_board.kicad_pcb
```

### The schematic has wires, but KiCad shows an empty or old version

**Cause:** same as above. A KiCad window you have open does not notice changes on disk.

**Fix:** in KiCad, **File → Revert** (board or schematic) to reload from disk, or close and reopen.

### DRC reports a short after routing

A common cause: the physical pad positions of a through-hole part (for example an LED) are not where you expect, and one pad sits on the path of your trace. Use `get_component_pads` to get the real pad coordinates before routing, or rotate the part.

---

## 8. Tested versions

- KiCad 10.0.6
- mixelpixx/KiCAD-MCP-Server (`main` branch)
- macOS, Apple Silicon
- Test: a small LED + resistor board through the full flow (schematic → ERC → PCB → DRC → Gerber), 0 errors
