# House plans and engineering parts (CAD)

## House plans and engineering parts (CAD, programmatic)

```
ai-pc cad talk -m "a 5 marla house with 3 bedrooms" -m "make it double story" -m "make the lounge bigger" -m "call it Ahmed House"
   -m "export the pdf" -m "give me the dwg"
ai-pc cad talk -m "make a 10 marla house plan with 4 bedrooms and a dining room" -m "make bedroom 2 11 x 14" -m "straight stairs" -m "on A2"
ai-pc cad draw "a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners and a 30 mm hole in the centre"
ai-pc cad talk -m "a flange OD 150 ID 60, 4 holes of 14 on a 110 PCD, 12 thick" -m "8 holes" -m "give me the laser cut file"
```

Code writes AutoCAD DXF files with ezdxf 1.4.4. ezdxf is pure Python; its wheels were checked by SHA-256 against PyPI
and scanned before install. Headless Chrome prints each sheet to PDF at its true paper size and scale, plus a PNG
preview. Chrome runs with its own profile inside the project. AutoCAD is not needed: the DXF opens in AutoCAD,
BricsCAD, DraftSight and LibreCAD. A DWG would need the separate ODA converter, which is not installed. The chat says
so and gives the DXF instead.

| Area | What it does |
|---|---|
| Plots and conventions | Marla (225 sq ft) and kanal plots: 3 marla 20x34 up to 2 kanal 75x120, or any "30 x 60" or "40 feet wide and 80 feet deep". Pakistani conventions: road at the bottom, car porch open to the road with a gate, drawing room at the front, TV lounge, kitchen and stairs in the middle, bedrooms with attached baths at the back. Walls are 9" outer and 4.5" inner. Setbacks follow the plot size. |
| Planning (searched, not templated) | Bands from front to back: front, one or two middle rows, an optional passage, and the back. Stairs, store, powder room, dining, servant and guest rooms may change band. A store or powder room stacks behind its partner. Each candidate is scored on sizes, proportions, the doors that rooms need, and daylight. It is also walked through its actual doors from the porch or the road; a room nobody can reach costs heavily. Baths go in the bedroom's outside corner with a vent. Rooms with no outside wall get a skylight. The first floor sits over the same walls: terrace over the porch, a bedroom over the drawing room, family lounge, kitchenette. |
| When it does not fit | It says what gave way. A store is left out, with a note that the space under the stairs is the usual store. A third bedroom goes to the front or the first floor. On 3 marla the kitchen moves to the back, the porch is dropped and the front door opens from the road. |
| Drawing | Exact wall outlines with every opening cut, and solid fill. Doors are drawn with swings, windows with glass lines, vents and skylights. Furniture is kept clear of door swings and room names. Chain dimensions are in feet and inches. Room names fit or wrap ("DRAWING / ROOM") and slide off door swings. The sheet carries a title block, a room schedule for both floors and a north arrow turned to the road. The sheet is A3 unless that would need a scale smaller than 1:150; then A2 at 1:100. |
| Conversation | "Bigger" and "smaller" search for the largest step (1 ft, then 6") that keeps every door and minimum size, and the least change to the other rooms. If none exists, it says why: "in width, Bed Room 1 would lose its door". The chat refuses any change that would break a working plan or drop a room nobody asked to drop. Answers questions: the covered area, the room list, how big a room is, "can I fit 4 bedrooms?" (trying a first floor too), and "any problems?". Also undo, redo, go back to a version, history, paper, scale (it refuses one the sheet cannot hold), name and client. |
| Parts (mm) | Plates (corner, centre, row and grid holes; radius or chamfer corners) and flanges (OD, bore, bolt circle). Front and side views with hidden and centre lines, hole callouts ("4x Ø12 THRU"), an ISO scale and a title block. A 1:1 cut file holds only the CUT layer for a laser or CNC cutter. Rules checked: edge distance (at least 1x the hole, 1.5x better for steel), hole spacing, bolt holes clear of the bore and rim, corner radius. |
| Checks on every version | Plan rules: everyone can reach every room, no room under its minimum, nothing overlaps or leaves the walls, stairs line up between floors. The DXF is read back: it audits clean, units are inches, walls are closed and filled, room outlines carry the planned areas, each room's name sits inside that room, there is one door swing per door, every window has glass, and each dimension's text equals the distance it measures. The sheet: a one-page PDF of the right paper size, and a preview that is a drawing (not blank). |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_cad.py](../../tests/integration/test_cad.py): units; 11 briefs from 3 marla to 2 kanal; size limits; 3 sheets read back and printed; 13 deliberately spoiled drawings and plans, each tripping its check; plates, a flange and their cut files; 5 broken part designs; 30 phrasings | all pass | 15 s | none |
| [tests/integration/cad_conversations.py](../../tests/integration/cad_conversations.py): 5 conversations, 44 turns, each checked on the drawing it made | 44/44 | 50 s (42 turns by rules; 2 by GLM-5.3-Flash) | $0.0003 |

Building it, the checks and visual reviews caught real faults:
- Making the kitchen 2" bigger cost Bedroom 1 its door.
- An impossible bedroom size made the planner silently drop five rooms. The chat now refuses such changes.
- The room name check passed even with a room's label deleted, because the schedule listed the room. The check now looks inside each room.
- The flange "150 od 60 bore" was read as OD 60.
- The two-floor schedule ran into the title block.
- Bold room names overflowed narrow rooms at 1:200.
- A dining table was drawn on top of its label.
- An upstairs room over a servant quarter had no door.
