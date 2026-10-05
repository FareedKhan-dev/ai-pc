# Social media

## Social media: Facebook, Instagram, Threads, YouTube, TikTok, LinkedIn and X (official APIs)

```
ai-pc social steps                    how to make each platform's free developer app (ai-pc social steps instagram for one)
ai-pc social connect youtube          sign in once; keys and tokens kept encrypted on this PC
ai-pc social talk --with eid.mp4 -m "post eid.mp4 to instagram reels, facebook and youtube shorts saying 'Eid sale is live!'" -m "yes"
ai-pc social talk -m "post poster.jpg to facebook tomorrow at 7 pm saying 'Tomorrow only: 20% off'" -m "yes" -m "what's scheduled?"
ai-pc social talk -m "how did my posts do this week?" -m "make a report" -m "any new comments?" -m "reply to the first one saying thank you!" -m "yes"
ai-pc social run                      publish what is due (Windows Task Scheduler runs it every 5 minutes once automatic posting is on)
ai-pc social setup-tunnel             once, for Instagram pictures and Threads media (see below)
```

Every platform is used only through its official API. The current rules (checked 2026-10-04 against each platform's
developer docs) are written into the code with their sources. A post is composed once. Each platform gets its own version:
its kind of post, its words and its media, converted and measured. That version is shown before anything goes out, and
nothing is published without your yes. Each post is then read back from the platform.

| Platform | What it posts | Scheduling | After posting | Rules set by the platform |
|---|---|---|---|---|
| Facebook Page | text and links, 1-10 photos, videos, Reels, Stories | by Facebook itself (10 minutes to 30 days ahead, PC may be off) | link, numbers (views, reach, reactions, comments, shares), comments answered and hidden, delete | the Meta app must be switched to Live (else only you see the posts); 30 Reels a day |
| Instagram (professional account linked to the Page) | photos, carousels of 2-10, Reels, Stories | by this PC | link, insights, comments answered and hidden, delete | 50 API posts in 24 hours; pictures only from a web address (lent for a minute, below); sign in again every 60 days |
| Threads | text, a picture, a video, carousels of 2-20 | by this PC | link, insights, replies answered and hidden, delete | 250 posts a day; media only from a web address; 500 characters, 5 links, 1 topic tag |
| YouTube | videos and Shorts (vertical, 3 minutes or less), thumbnail, captions | by YouTube itself (publishAt) | link, statistics, comments answered and held for review, delete | 100 uploads a day; uploads from an unaudited Google project stay PRIVATE until YouTube's free API audit |
| TikTok | videos (pictures become a slideshow video) | by this PC | numbers for public videos | personal tools are not audited for public posting, so videos go to your TikTok inbox as drafts (you post them in the app) or post as private; no deleting |
| LinkedIn | text, 1-20 images, a video, on your profile | by this PC | link, delete | personal apps get no statistics and cannot read posts back; the sign-in lasts 60 days |
| X | text (long text as a thread), 4 pictures or a video | by this PC | link, numbers, replies answered, delete | paid per use: $0.015 a post, $0.20 with a link (shown before posting) |

| Part | What it does |
|---|---|
| Words | Lengths are counted the way each platform counts them. X counts links as 23 and emoji as 2; Threads counts emoji by their UTF-8 bytes; YouTube's description limit is in bytes. Hashtag and mention limits are checked, LinkedIn's reserved characters are escaped (hashtags kept), and YouTube titles are made from the first line. Text too long for X becomes a numbered thread; elsewhere it is reported, never cut. Your own links can be tagged for tracking (`utm_source`). |
| Media | Pictures are cropped around the subject to an allowed shape, or fitted whole on a blurred fill when asked. They are saved as sRGB JPEGs, with location and camera data removed, within each platform's size. Videos go through the converter's preset for the platform only when they do not fit already (codec, frame, fps, size, the 1280 px cap for X), and are measured again. Too short or too long is reported. A video is cut only when you ask. |
| Publishing | Each platform's job is a resumable state machine saved in SQLite (`state/social/social.db`). YouTube uploads in 8 MiB chunks and resumes from the byte YouTube confirms. TikTok uses its chunks, LinkedIn its signed parts with ETags, X its segments, and Meta its rupload sessions. The engine waits while each platform processes. A request that creates a public post is never resent blindly: after a lost answer, the latest posts are searched for it (on LinkedIn, which cannot be read back, you are asked to check). |
| Failures | Passing problems wait 1, 5, 15, 60, then 240 minutes; rate limits and quotas wait as long as the platform says (YouTube's renews at midnight Pacific time). An expired sign-in waits for you. A refused post is reported with the platform's reason. Only one runner works the queue at a time. |
| Sign-in | OAuth with a loopback address and PKCE where each platform supports it (TikTok's hex variant included). Meta and Threads tokens are pasted from Meta's Graph API Explorer, because Meta's desktop sign-in is an embedded browser and Threads refuses loopback addresses; they are made long-lived, the Page token never expires, and Threads renews itself a week early. All keys are DPAPI-encrypted and never printed, logged or sent to the model. |
| Temporary web address | Instagram (pictures) and Threads (all media) fetch media from a URL. `ai-pc social setup-tunnel` installs Cloudflare's cloudflared into `tools/cloudflared`, checked against Cloudflare's published SHA-256 and its Windows signature. A one-file server is then exposed for a minute at a random address under a 32-character secret path, and closed once the platform has the file. |
| Conversation | Compose, preview, yes or no, a new caption, "yes but not on tiktok". Also the queue, cancel, delete, results (with an Excel report), new comments, reply by number or "the first one", hide, retry, edit a waiting post, the best times to post (from your own numbers only), and automatic posting on or off (a hidden Windows task, added only after your yes). The cheap model reads only what the rules cannot. |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_social.py](../../tests/integration/test_social.py), no network and no keys: words; the runner (processing, native scheduling, retries, limits, expired sign-ins, refusals, crashes, one runner at a time); real media through each platform's rules (Reels, panoramas, carousels, GPS removed, slideshows, X's 1280 px cap, cut only when asked); every connector against a fake server built from its docs; a YouTube upload that loses its connection mid-file and resumes byte-exact; Instagram fetching the exact prepared file from the temporary address, which is then closed; X and LinkedIn posts whose answers were lost not posted twice; sign-ins (TikTok's hex PKCE, Google's S256, Meta's long-lived and Page tokens, Threads' early renewal); the tunnel installer refusing a changed file or a wrong signature; 20 everyday phrasings; the chat end to end | 127/127 | 70 s | none |
| [tests/integration/social_conversations.py](../../tests/integration/social_conversations.py), GLM-5.3-Flash with the fake platforms: a reel to Instagram and Facebook, a YouTube Short asked for in other words, a scheduled LinkedIn and Threads post dropped, a tweet with its cost, the week's numbers, comments, a reply to "the first one" | 12/12 turns | 3 s | $0.0001 |

Live tests need your developer apps and keys (`ai-pc social steps <platform>`).
