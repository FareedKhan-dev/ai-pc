# 0002. Drive programs through their files and official interfaces, not the screen

- Status: accepted
- Date: 2026-10-01

## Context

The first prototype operated programs through their user interface: UI Automation where a program exposes it, and a
vision model clicking on screenshots where it does not. It worked on simple programs, but complex editors (CapCut,
JianYing) draw their own controls, change between versions, and need the screen, the mouse and the keyboard while
they work. The user works on the same PC at the same time.

## Decision

Each program is driven by code: it writes the application's own file format (a JianYing draft, a .docx, a DXF, a
Blender scene) or calls its official command line or API, and the application only renders or exports. Programs run
on a hidden Windows desktop. Operating a user interface is kept for the desktop agent, as the last resort, and never
moves the user's mouse or types on their screen.

## Consequences

- Results are exact and checkable: the agent knows what it wrote, and measures the rendered result.
- Edits are fast, repeatable and versioned, and the user keeps their screen.
- Each new program needs a library or format writer, which is more work up front than pointing a vision model at it.
- Programs with no file format or interface can only be reached by the desktop agent.
