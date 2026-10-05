# Photos

## Photos (programmatic)

```
ai-pc photo talk car.jpg -m "it's too dark, fix it" -m "crop to the car" -m "add 'FOR SALE' at the top in red" -m "make the text bigger"
   -m "watermark '© Fareed Motors'" -m "compare with the original" -m "save it for instagram under 300 kb"
ai-pc photo talk presenter.png -m "remove the background" -m "make a passport photo for the US" -m "print 6 of them on a 4x6 sheet"
ai-pc photo talk party.jpg -m "blur all the faces" -m "crop it to 4:5" -m "pixelate the faces instead"    (the crop is redone after the swap)
ai-pc photo batch "C:\Users\me\Pictures\Trip" -m "fix it" -m "watermark '© Me'" --save "for instagram under 500 kb"
ai-pc photo look car.jpg                       what it is like, and where, when and with what it was taken
```

Pillow, numpy and OpenCV do the edits (no new download: faces come from the YuNet model already in `models/`, which is
checked by SHA-256). Windows Photos, or any viewer, only shows the result. The original is never changed: each message
makes a version in the chat's folder, and saved copies go to its `exports`.

| Area | What it does |
|---|---|
| Measuring | Exposure, contrast, colour cast, saturation, noise, sharpness (of the strongest edges, so a sky does not make a photo "blurry"), faces, a green or blue screen or plain backdrop, the main subject, the lean of a horizon, a page's corners, and where it is quiet enough for text. |
| Fix it | Auto-enhance decides from those measures and says why: colour cast, tonal range, exposure (a night scene is lifted, not turned into day, unless the person says it is too dark), flatness, dull colour, grain and softness. Contrast lost by brightening is given back by deepening the darks, which blows no highlights. A green-screen shot is left for keying. |
| Edits | Brightness by a tone curve, contrast, colour, vibrance, warmth, shadows, highlights, white balance, clarity. Looks: B&W, sepia, vintage, cinematic, dramatic, film noir, sketch, cartoon, painting and more. |
| Shape | Crop to a shape with the face kept near the top third. "Crop to the car" snaps to the nearest pleasing shape around the subject. Fit a story without cropping (the sides filled with a blurred copy, or kept transparent for a cut-out). Straighten from the horizon. Rotate, resize, border, polaroid, vignette. |
| People | Blur or pixelate every face. Portrait-mode background blur, background removal, and a new background (a colour or another photo): green and blue screens are keyed with the spill taken off, plain backdrops are cut, anything else goes through GrabCut from the faces. Also skin smoothing and lifting dark faces. |
| Words | Text placed in the calmest band and never over a face, white or near-black by what is behind it, outlined when a colour asked for would not read. Short words come out big. Memes, banners, and watermarks (a corner, or tiled across). |
| Documents and IDs | A photographed page is found, flattened, its shading divided out and the paper made white, then saved as a PDF. Passport photos: the head sized to each standard (35x45 mm, US 2x2, UK, UAE, Saudi, Canada, China) at 300 dpi on a plain background, and copies on a 4x6, 5x7 or A4 print. The reply says when fewer copies fit than were asked for. |
| Conversation | "it" is the photo. "move the text to the bottom", "make the text yellow and bigger" and "change the text to ..." change words already written. "sepia instead" and "pixelate the faces instead" swap the earlier edit of that kind and redo everything after it, because each version keeps its edits and can replay them. A crop or turn made after a border goes in before the border, so the frame stays on the outside. Also undo, redo, "go back to v2", "compare with the original" (side by side, with the numbers that changed), and "add beach.jpg" for collages and new backgrounds. |
| Saving | JPG, PNG, WebP or PDF. Social and print sizes: Instagram post, portrait and story, YouTube thumbnail, Facebook, LinkedIn, X, WhatsApp, 4x6, A4. "Under 300 KB" searches for the best quality that fits, then shrinks if it must. The GPS location is taken out of every saved copy unless asked otherwise ("where was this taken?" shows it). Each saved file is opened again and checked. |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_photo.py](../../tests/integration/test_photo.py): measures; 49 edits on real and made-up photos (a leaning horizon, a photographed page, a date stamp, grain), each passing its own check; saving with size limits and location removed; 52 phrasings | all pass | 38 s | none |
| [tests/integration/photo_conversations.py](../../tests/integration/photo_conversations.py): 8 conversations, 38 turns, each checked on the image it made | 38/38 | 32 s in all (36 turns by rules in 25 s; 2 by GLM-5.3-Flash, ~2 s each) | $0.0002 |
| `ai-pc photo batch ... -m "fix it"` on 12 varied photos (dark garage, concert, gym, DJ booth, sunset, sports, landscape) | 12/12 pass every check | 22 s | none |

The checks caught real faults while it was being built:
- Auto-enhance on a green-screen frame darkened the subject's face.
- Brightening a concert photo flattened it. The first fix for that then blew out the stage lights.
- Text written on a transparent cut-out was invisible.
- A story-sized cut-out had its sides filled with blurred green.
- Passport crops above the frame came out black.
- Straightening turned the photo the wrong way.
