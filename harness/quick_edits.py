"""Follow-ups on an edit in plain words -> operations, applied and checked without a model call.

A conversation about an edit is mostly small, clear changes: "music a bit lower", "title in gold", "cut it to 30 s",
"no shakes in the intro", "start with the beach shot", "use a handwritten font". They are read here with word lists
(after typos, chat shorthand and Roman Urdu are normalised), applied to the edit and checked on the new timeline. What
the words do not cover goes to the model (conversation.py), which answers in the same operations.

  normalize(text)          typos, shorthand and Roman Urdu -> plain English
  clauses(text)            "make the title red, the music quieter and cut it to 25 s" -> three clauses
  parse(clause, ctx)       -> {"ops": [...], "focus": subject, "note": why nothing was understood}
  apply_design(design, ops, ctx) / apply_plan(plan, ops, ctx)
  check(op, R0, R1)        did it happen on the new timeline? -> (ok, what)
  describe(op)             a few words for the reply

Plan operations name their targets by role and words ("the labels", "the title 'THE BAY'", "the shakes in the intro"),
never by internal ids, so they apply again after the edit is re-cut for a later structural change. Structural changes
(length, pacing, shot order, music, canvas, recipes) change the DESIGN and the cut engine re-cuts it on the beat.
"""
import copy
import difflib
import re
from collections import Counter

from .editplan import Catalog

# ------------------------------------------------------------------------------------------------ words
COLOURS = {"neon pink": "#FF1F8E", "neon blue": "#1F51FF", "neon yellow": "#F5FF1F", "neon orange": "#FF5F1F", "neon purple": "#B026FF",
           "electric blue": "#1F51FF", "bright red": "#FF1F1F", "bright yellow": "#FFE600", "bright green": "#22E35A", "deep blue": "#123A9C",
           "dark red": "#B71C1C", "hot pink": "#FF1F8E", "neon green": "#39FF14", "light blue": "#7FC8FF", "baby blue": "#9FD3FF",
           "sky blue": "#6EC6FF", "dark blue": "#1F3A93", "off white": "#F5F1E8", "off-white": "#F5F1E8",
           "red": "#E53935", "crimson": "#C62828", "pink": "#FF4FA3", "orange": "#FF8A00", "yellow": "#FFD600",
           "gold": "#E8C547", "golden": "#E8C547", "green": "#2ECC71", "lime": "#B6FF00", "teal": "#14B8A6", "cyan": "#00E5FF",
           "blue": "#2F80ED", "navy": "#1F3A93", "purple": "#8E44AD", "violet": "#8F5BFF", "lavender": "#C7A4FF",
           "magenta": "#FF00FF", "white": "#FFFFFF", "black": "#000000", "grey": "#9E9E9E", "gray": "#9E9E9E",
           "silver": "#C0C0C0", "cream": "#F5E9D0", "beige": "#E8D8B9", "brown": "#8D5524", "maroon": "#800000"}
COLOUR_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(c) for c in COLOURS), key=len, reverse=True)) + r")\b")
HEX_RE = re.compile(r"#[0-9a-f]{6}\b")

GENRES = {  # the music beds this editor can generate, and the words that ask for them
    "chill": r"chill|lo-?fi|lo fi|calm(?:er)?|relax(?:ing|ed)?|mellow|ambient|peaceful|cozy|cosy|gentle|soft(?:er)? music|acoustic|laid.?back",
    "cinematic": r"cinematic|orchestral|emotional|romantic|piano|dramatic|sad|elegant|classy|luxury|strings|heartfelt|sentimental|wedding",
    "epic": r"epic|trailer|heroic|powerful|massive|intense|big",
    "hype": r"hype|energetic|upbeat|edm|electronic|dance|party|trap|aggressive|banger|club|house|techno|drill|hard ?hitting|workout",
    "phonk": r"phonk|drift|cowbell",
    "pop": r"pop|happy|fun|cheerful|feel.?good|playful|funky|summer|bright music|light music"}
GENRE_RE = {g: re.compile(r"\b(?:" + p + r")\b") for g, p in GENRES.items()}
NEIGHBOUR = {"chill": "cinematic", "cinematic": "chill", "epic": "cinematic", "hype": "phonk", "phonk": "hype", "pop": "hype"}
GENRE_BPM = {"chill": 88, "cinematic": 80, "epic": 120, "hype": 140, "phonk": 140, "pop": 118}

LOOKS = [  # (words that ask for it, search words for a filter, short name)
    (r"black[- ]and[- ]white|b&w|monochrome|grayscale|greyscale|no colou?rs?", "black and white monochrome gray classic", "black and white"),
    (r"sepia", "sepia brown vintage old photo", "sepia"),
    (r"teal(?:[- ]and[- ]|[- ])orange", "teal orange cinematic complementary", "teal and orange"),
    (r"golden hour|sunset look|sunny", "golden hour warm sunset glow", "golden-hour"),
    (r"cream(?:y|ier)?|milky|soft(?:er)? and warm|warm and soft", "warm cream soft pastel golden", "creamy"),
    (r"warm(?:er)?|cozy|cosy", "warm golden orange cozy", "warmer"),
    (r"cool(?:er)?|cold(?:er)?|blu(?:e|ish) tones?|icy", "cool blue cold teal", "cooler"),
    (r"vintage|retro|old.?school|nostalgic|film look|filmic|analog|kodak|polaroid|90s|80s", "vintage retro film faded", "vintage"),
    (r"cinematic|movie|film(?!s)", "cinematic film movie teal", "cinematic"),
    (r"neon(?! (?:pink|blue|yellow|orange|purple|green|red|white))|cyberpunk|synthwave", "neon cyberpunk vivid night", "neon"),
    (r"dream(?:y|ier)|ethereal|hazy|soft glow", "dreamy soft glow haze", "dreamy"),
    (r"pastel", "pastel soft light pink", "pastel"),
    (r"vibrant|saturated|colou?rful|punchy colou?rs?|vivid|pop of colou?r|more colou?r|richer colou?rs?|less dull|not dull|dull", "vibrant saturated vivid colorful", "more vibrant"),
    (r"muted|desaturated|faded|washed|less colou?r|matte|subdued", "muted desaturated faded matte soft", "muted"),
    (r"moody|darker|dark(?:er)? look|low.?key|gloomy|gritty", "dark moody low key shadow", "darker, moodier"),
    (r"brighter|bright(?:er)? look|lighter|airy|too dark|more light|well.?lit|exposure up", "bright airy light clean fresh", "brighter"),
    (r"natural|clean look|true colou?rs?|realistic|normal colou?rs?|original colou?rs?", "natural clean true color", "natural"),
    (r"more contrast|high contrast|contrasty|crisp(?:er)?|sharper look", "high contrast punchy crisp", "more contrast"),
    (r"less contrast|low contrast|flat(?:ter)? look|softer look", "low contrast soft flat", "less contrast")]
LOOKS = [(re.compile(r"\b(?:" + w + r")\b"), q, n) for w, q, n in LOOKS]

FAMILIES = {  # transition families: words -> (search words, seconds)
    "dissolve": (r"dissolves?|cross ?fades?|fades?|smooth(?:er)?|soft(?:er)?|subtle|gentle|seamless|elegant|dreamy|romantic|calm(?:er)?", "dissolve cross fade soft", 0.7),
    "blur": (r"blur(?:ry)?", "blur soft smooth", 0.5),
    "zoom": (r"zoom(?:s|ing)?", "zoom in push", 0.4),
    "whip": (r"whip(?: ?pans?)?|swipes?|swish", "whip pan swipe fast", 0.35),
    "spin": (r"spin(?:s|ning)?|rotat(?:e|ion|ing)", "spin rotate", 0.4),
    "glitch": (r"glitch(?:y|es)?|digital|rgb|techy|tech", "glitch digital rgb", 0.35),
    "flash": (r"flash(?:es)?|white flash|bright", "white flash light", 0.3),
    "slide": (r"slides?|push(?:es)?|wipes?", "slide push wipe", 0.45),
    "leak": (r"light leaks?|film burns?|burn", "light leak film burn glow", 0.6)}
FAMILIES = {f: (re.compile(r"\b(?:" + w + r")\b"), q, d) for f, (w, q, d) in FAMILIES.items()}

FONT_STYLES = r"handwritten|hand ?written|script|cursive|calligraph\w*|signature|elegant|classy|luxury|serif|sans|modern|futuristic|" \
              r"tech\w*|sci-?fi|retro|vintage|playful|fun|cute|comic|bubbly|rounded|thin|light|minimal\w*|clean|bold(?:er)?|heavy|thick|" \
              r"condensed|tall|grunge|horror|scary|gothic|typewriter|brush|graffiti|western|chunky|simple|professional|corporate|" \
              r"classic|romantic|feminine|masculine|strong|sporty|athletic|impact"
FONT_STYLE_RE = re.compile(r"\b(" + FONT_STYLES + r")\b")
FONT_QUERY = {"handwritten": "handwritten script", "hand written": "handwritten script", "script": "script handwritten cursive",
              "cursive": "script cursive handwritten", "signature": "signature script", "elegant": "elegant script serif",
              "classy": "elegant serif luxury", "luxury": "luxury serif elegant", "romantic": "elegant script romantic",
              "feminine": "elegant script", "futuristic": "futuristic tech", "sci-fi": "futuristic tech", "scifi": "futuristic tech",
              "tech": "futuristic tech modern", "techy": "futuristic tech modern", "thin": "thin light minimal", "light": "thin light",
              "minimal": "thin minimal clean", "minimalist": "thin minimal clean", "clean": "clean modern sans", "simple": "clean modern sans",
              "professional": "clean modern sans", "corporate": "clean modern sans", "bold": "bold heavy display", "bolder": "bold heavy display",
              "heavy": "bold heavy display", "thick": "bold heavy display", "strong": "bold heavy display", "impact": "bold heavy condensed",
              "sporty": "bold heavy condensed sport", "athletic": "bold heavy condensed", "masculine": "bold heavy display",
              "playful": "playful cute rounded", "fun": "playful cute rounded", "cute": "playful cute rounded", "comic": "comic playful",
              "bubbly": "playful rounded bubble", "rounded": "rounded playful", "retro": "retro vintage", "vintage": "retro vintage",
              "classic": "serif classic", "serif": "serif classic", "grunge": "grunge rough", "horror": "horror grunge", "scary": "horror",
              "gothic": "gothic blackletter", "typewriter": "typewriter mono", "brush": "brush script", "graffiti": "graffiti street",
              "western": "western slab", "chunky": "bold heavy display", "condensed": "condensed tall", "tall": "condensed tall",
              "modern": "modern sans clean", "sans": "sans modern clean", "calligraphy": "calligraphy script"}

POSITIONS = [(r"\b(?:very top|top|at the top|upper part|up top)\b", "top"), (r"\b(?:upper|higher up|upper third)\b", "upper"),
             (r"\b(?:cent(?:er|re)d?|middle of the (?:screen|frame)|in the middle)\b", "center"),
             (r"\b(?:lower third|lower)\b", "lower"), (r"\b(?:bottom|at the bottom|down low)\b", "bottom")]
POS_ORDER = ["top", "upper", "center", "lower", "bottom"]

CTA_WORDS = re.compile(r"\b(follow|subscribe|link in bio|bio|download|book|shop|order|buy|call|visit|save this|see you|swipe|dm|"
                       r"comment|share|join|sign up|get yours|available|contact|apply|register|tickets?)\b", re.I)

SUBJECTS = [  # (name, pattern); the most specific first
    ("sfx", r"sound effects?|sfx|whoosh(?:es)?|swoosh(?:es)?|impacts? sounds?|impacts?|boom(?:s)?|risers?|hit sounds?|transition sounds?|sub ?drops?|thunder sounds?"),
    ("clip_audio", r"original (?:sound|audio)|clip(?:s'?)? (?:sound|audio)|crowd noise|crowd sound|ambient (?:sound|noise)|natural sound|"
                   r"background noise|camera (?:sound|audio)|sound of the clips?|people talking|real sound|nat sound"),
    ("voice", r"voice ?over|narration|narrator|voice"),
    ("music", r"music|song|soundtrack|track|beat|bgm|tune|instrumental|melody|audio"),
    ("caption", r"captions?|subtitles?|subs\b"),
    ("cta", r"call to action|cta|end card|end text|outro text|closing text"),
    ("label", r"labels?|place names?|step labels?|steps?|room names?|callouts?|lower thirds?|tags?|feature (?:labels?|texts?|names?)|names of the places"),
    ("title", r"titles?|heading|headline|main text|hook text|opening text|title text|title card|names?"),
    ("text", r"texts?|words|writing|lettering|typography|fonts?|typeface"),
    ("transition", r"transitions?|between (?:the )?clips|between (?:the )?shots|cuts between|dissolves?|cross ?fades?|crossfades?|whip ?pans?|wipes?"),
    ("texture", r"grain|grainy|noise|vignette|letter ?box|black bars|bars|light leaks?|leaks?|film burns?"),
    ("look", r"filter|grade|grading|colou?r(?:s| grade| grading)?|look|lut|(?:colou?r|skin|warm|cool|cold) tones?|tint|exposure|brightness|contrast|saturation|vibrance|warmth|lighting"),
    ("shake", r"shak(?:e|es|ing|y|iness)|camera shake|jitter|wobble"),
    ("zoom", r"zoom(?:s|ing)?(?: punch(?:es)?)?|punch(?:es|-ins?| ins?)?|push(?:-| )?ins?|ken burns"),
    ("flash", r"flash(?:es|ing)?|strobe|strobing|blinks?"),
    ("glitch", r"glitch(?:es|y)?|rgb(?: hits?)?|chromatic|colou?r (?:split|hits?)"),
    ("effects", r"effects?|fx|vfx|overlays?|animations?"),
    ("speed", r"slow ?mo(?:tion)?|slow-mo|slow (?:down|it down) the (?:part|bit|moment|shot|scene)|speed ramps?|velocity|time ?lapse|fast forward|sped up|"
              r"speed up|freeze(?: frame)?|freeze-frame|revers(?:e|ed)|(?:normal|regular|original|real ?time|natural) speed"),
    ("length", r"length|duration|\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds|minutes?|mins?)\b|seconds|minute"),
    ("pace", r"pac(?:e|ing)|cuts|cutting|edit(?:ing)? (?:speed|rhythm)|rhythm|tempo of the cuts"),
    ("canvas", r"vertical|horizontal|landscape|portrait|square|16:9|9:16|1:1|4:5|widescreen|aspect ratio|format"),
    ("shot", r"shots?|clips?|scenes?|footage|parts?")]
SUBJECTS = [(n, re.compile(r"\b(?:" + p + r")\b")) for n, p in SUBJECTS]

UP = r"more|bigger|larger|louder|stronger|increase|raise|boost|higher|up|harder|heavier|intense|pump(?:ed)?|crank"
DOWN = r"less|smaller|quieter|softer|weaker|decrease|reduce|lower|down|lighter|subtler|subtle|fewer|tone(?:d)? (?:it )?down|dial (?:it )?back|calm(?:er)?|gentler"
REMOVE = r"remove|delete|get rid of|drop the|no more|no|without|turn off|disable|take out|take away|cut out|kill|lose the|ditch|" \
         r"don'?t want|do not want|hate the|stop the|hide|mute|erase|strip|clear"
ADD = r"add|put|insert|include|place(?= (?:a|an|the|some|my|our|qtext)\b)|throw in|give (?:it|me)|want (?:a|an|some)|need (?:a|an|some)|" \
      r"can (?:we|i|you) (?:have|get)|slap|stick|show(?= (?:a|an|the|some|my|our|qtext)\b)|write|let'?s have|bring in"
CHANGE = r"change|switch|swap|replace|different|another|other|new|try|instead|rather|update|rename|fix"
MOVE = r"move|shift|position|place|put|bring|raise|lower|push"
ALOT = r"much|way|a lot|lots|very|really|super|so|far|significantly|double|twice|loads|tons|massively|extremely|heavily|hella|mad"
ABIT = r"a bit|a little|slightly|a touch|kinda|kind of|somewhat|little bit|tiny bit|a tad|tad|bit|little"

STOP = set("""a an the and or but of to in on at for with from by is are was were be been it its it's this that these those my our your
his her their them they we i me you he she please pls can could would should will just very really some any all also too then
there here so up down more less make made making do did does get got let like want need use using used one ones bit little
than much way out over into onto about as when where what which who how why video edit clip shot shots clips part""".split())

TYPOS = {"musci": "music", "muisc": "music", "msuic": "music", "musc": "music", "musik": "music", "mucis": "music",
         "titel": "title", "tittle": "title", "tilte": "title", "titile": "title", "tital": "title", "titl": "title",
         "biger": "bigger", "bigr": "bigger", "lowder": "louder", "loudr": "louder", "louader": "louder", "lauder": "louder",
         "quiter": "quieter", "quieeter": "quieter", "remvoe": "remove", "remov": "remove", "rmove": "remove", "romove": "remove",
         "delte": "delete", "transistion": "transition", "transistions": "transitions", "transtion": "transition",
         "transtions": "transitions", "transitons": "transitions", "trasition": "transition", "trasitions": "transitions",
         "fliter": "filter", "filtr": "filter", "flter": "filter", "efect": "effect", "efects": "effects", "effetcs": "effects",
         "effecs": "effects", "collor": "color", "colr": "color", "clr": "color", "lenght": "length", "lengh": "length",
         "shorer": "shorter", "shoter": "shorter", "shortr": "shorter", "smaler": "smaller", "fster": "faster", "fatser": "faster",
         "slwoer": "slower", "zom": "zoom", "zoomz": "zooms", "shak": "shake", "shakey": "shaky", "vidoe": "video", "vid": "video",
         "vdo": "video", "pls": "please", "plz": "please", "plss": "please", "thx": "thanks", "ty": "thanks", "u": "you",
         "ur": "your", "abt": "about", "wat": "what", "wht": "what", "whats": "what is", "wats": "what is", "dont": "don't",
         "cant": "can't", "isnt": "isn't", "doesnt": "doesn't", "im": "i'm", "ive": "i've", "gonna": "going to",
         "wanna": "want to", "gimme": "give me", "lemme": "let me", "abit": "a bit", "alil": "a little", "lil": "little",
         "tho": "though", "thru": "through", "bgm": "background music", "txt": "text", "fx": "effects", "slowmo": "slow motion",
         "slomo": "slow motion", "secs": "seconds", "sec": "seconds", "mins": "minutes", "brigher": "brighter",
         "briter": "brighter", "darkr": "darker", "warmr": "warmer", "colour": "colour", "colours": "colours",
         "captoins": "captions", "subtitels": "subtitles", "lables": "labels", "lable": "label", "labes": "labels",
         "grian": "grain", "vingette": "vignette", "vignete": "vignette", "glich": "glitch", "gltich": "glitch",
         "flsh": "flash", "flahs": "flash", "beggining": "beginning", "begining": "beginning", "endig": "ending",
         "endng": "ending", "sunst": "sunset", "beutiful": "beautiful", "abt.": "about", "versoin": "version", "verison": "version",
         "orignal": "original", "origional": "original", "undoo": "undo", "agian": "again", "smoth": "smooth", "smoother": "smoother",
         "soudn": "sound", "sond": "sound", "volum": "volume", "volumne": "volume", "voulme": "volume", "speeed": "speed",
         "intor": "intro", "outor": "outro", "exprot": "export", "rendr": "render", "thnks": "thanks", "thanx": "thanks"}
VOCAB = sorted(set("""music title titles transition transitions filter filters effect effects louder quieter bigger smaller shorter longer
faster slower remove delete change replace colour color font fonts label labels caption captions subtitle subtitles shake shakes
zoom zooms flash flashes glitch grain vignette letterbox brighter darker warmer cooler vibrant saturated contrast volume length
seconds minute intro ending beginning opening drop climax version original previous undo redo export render sunset beach
background whoosh sound sounds effect position bottom center middle smooth smoother dissolve cinematic vintage golden handwritten
elegant futuristic slower motion freeze reverse vertical horizontal square landscape portrait instagram tiktok youtube""".split()))

# Roman Urdu (Pakistani chat) -> English; only applied when the message clearly is Roman Urdu
URDU_MARK = re.compile(r"\b(karo|kardo|kar do|krdo|kro|kren|karen|karein|thora|thoda|thori|zyada|ziada|bohat|bahut|boht|hatao|hata do|"
                       r"lagao|laga do|daalo|dalo|daal do|wala|wali|wale|kaunsa|konsa|kya|kyun|kyon|isko|isay|awaz|aawaz|gana|gaana|"
                       r"laal|lal|peela|neela|achha|acha|theek|thik|nahi|nahin|haan|hai|hain|tha|thi|chota|chhota|bara|bada|lamba|"
                       r"badlo|badal do|dikhao|likho|barhao|badhao|ghatao|pehle|wapis|wapas|kitne|kitni|shuru|akhir|aakhir|ka|ki|ke)\b")
URDU = [(r"\b(?:pehle|pehla|pichla|pichle|purana|purane) (?:wala|wali|wale|version)\b", "the previous version"),
        (r"\b(?:wapis|wapas|waapis) (?:karo|kardo|kar do|krdo|kro|le aao|lao)\b", "undo"),
        (r"\b(?:wapis|wapas|waapis)\b", "back"),
        (r"\b(?:thora|thoda|thori|thodi|zara)\b", "a bit"),
        (r"\b(?:bohat|bahut|boht|bht|kafi|kaafi)\b", "much"),
        (r"\b(?:hatao|hata do|hata den|hata dein|hatado|nikal do|nikalo|nikaal do|khatam karo|khatam kardo)\b", "remove"),
        (r"\b(?:lagao|laga do|lagado|laga den|daalo|dalo|daal do|daldo|dal do|daal den|add karo|add kardo|add kar do|shamil karo)\b", "add"),
        (r"\b(?:badlo|badal do|badaldo|change karo|change kardo|change kar do|badal den)\b", "change"),
        (r"\b(?:likho|likh do|likhdo)\b", "write"), (r"\b(?:dikhao|dikha do)\b", "show"),
        (r"\b(?:bara karo|bada karo|bara kardo|bada kardo|bari karo|badi karo)\b", "bigger"),
        (r"\b(?:chota karo|chhota karo|choti karo|chhoti karo)\b", "smaller"),
        (r"\b(?:barhao|badhao|barha do|badha do|barhaen)\b", "increase"), (r"\b(?:ghatao|ghata do)\b", "decrease"),
        (r"\b(?:laal|lal)\b", "red"), (r"\b(?:peela|peeli|pila|pili)\b", "yellow"), (r"\b(?:neela|neeli|nila|nili)\b", "blue"),
        (r"\b(?:hara|hari)\b", "green"), (r"\b(?:kala|kaala|kali|kaali)\b", "black"), (r"\b(?:safed|safaid|sufaid)\b", "white"),
        (r"\b(?:sunehra|sunehri)\b", "gold"), (r"\bgulabi\b", "pink"), (r"\brang\b", "colour"),
        (r"\b(?:kaunsa|konsa|kon sa|kaun sa|konsi|kaunsi|kon si|kaun si)\b", "which"), (r"\b(?:kitne|kitni|kitna)\b", "how many"),
        (r"\b(?:kyun|kyon)\b", "why"), (r"\bkya hai\b", "what is"), (r"\bkya\b", "what"),
        (r"\b(?:shuru|shuruat|shuroo)\b", "start"), (r"\b(?:akhir|aakhir|aakhri|akhri)\b", "end"), (r"\b(?:beech|bich|darmiyan)\b", "middle"),
        (r"\b(?:roshan|roshni|ujala)\b", "brighter"), (r"\b(?:andhera|andheri)\b", "darker"), (r"\b(?:jaldi)\b", "faster"),
        (r"\b(?:chota|chhota|choti|chhoti|chotay|chhote)\b", "shorter"), (r"\b(?:bara|bada|bari|badi|baray|bade)\b", "bigger"),
        (r"\b(?:lamba|lambi|lambaa|lambay)\b", "longer"),
        (r"\b(?:acha|achha|accha|theek hai|thik hai|theek|thik|sahi hai|zabardast|kamaal|kamal)\b", "ok"),
        (r"\b(?:nahi|nahin|nai|mat)\b", "no"), (r"\b(?:haan|han|jee)\b", "yes"),
        (r"\b(?:sab|saare|sare|tamam)\b", "all"), (r"\b(?:isko|isay|ise|isse|is ko|usko|usay|isey)\b", "it"),
        (r"\bbhi\b", "also"), (r"\baur\b", "and"), (r"\b(?:ye|yeh|yah)\b", "this"), (r"\b(?:wo|woh)\b", "that"),
        (r"\b(?:tha|thi)\b", "was"), (r"\b(?:hai|hain)\b", "is"), (r"\bpe\b|\bpar\b", "at"), (r"\bmein\b", "in"),
        (r"\b(?:karo|kar do|kardo|krdo|kro|kar den|kar dein|kardein|krden|karein|kijiye|karna|kren|karen|kar)\b", ""),
        (r"\b(?:ka|ki|ke|ko|se|wala|wali|wale)\b", "")]
URDU = [(re.compile(p), r) for p, r in URDU]


_KNOWN = set()
COMMON = """about above after again against almost already also although always among another answer anything appear around
because become before behind being below better between beyond black both bottom bright bring build called came cannot carry
center change clear close color colour come coming could cover cross dance dancing darker during early earlier either else
enough even ever every face family feel field final fine first follow forest friend front full give going great green group
happy hard heard heart heavy hello here high himself house however human idea image inside instead into just keep kind know
large later laugh leave left less light like line little live long look looking lose lost lower made make many maybe mean
might mind minute moment money more most mountain move much music must name near never night nothing number often only open
order other outside over own page paper part people person picture piece place plan play please point power pretty
quick quite rather ready real really right river road room round same scene second seem shape sharp short should show side
simple since slow small smile soft some something sometimes song soon sound space speak special start still stop story
strong such sure table take talk tell than that their them then there these they thing think those though three through
time today together tomorrow tonight towards tower true turn under until upon very voice walk want water week well what
when where which while white whole wide will with within without woman women word words work world would write wrong year
young your shot shots clip clips edit edits video videos frame frames title titles beat beats drop intro outro ending
opening caption captions label labels font fonts filter filters effect effects transition transitions sunset sunrise beach
ocean wedding bride groom couple party crowd player players goal match football soccer recipe cooking kitchen house property
garden terrace lagoon waterfall flowers flower sunflower narration narrator subtitle subtitles colour colours flames flame
power lover cover tower flower water later layer player prayer slower louder""".split()


def known_words():
    """Words this editor knows (its own vocabulary and common English): never 'corrected' as typos."""
    if not _KNOWN:
        g = globals()
        for name in ("UP", "DOWN", "REMOVE", "ADD", "CHANGE", "MOVE", "ALOT", "ABIT", "FONT_STYLES"):
            _KNOWN.update(re.findall(r"[a-z]+", str(g.get(name, ""))))
        for _, pat in SUBJECTS:
            _KNOWN.update(re.findall(r"[a-z]+", pat.pattern))
        for pat, q, n in LOOKS:
            _KNOWN.update(re.findall(r"[a-z]+", pat.pattern + " " + q))
        for pat in GENRE_RE.values():
            _KNOWN.update(re.findall(r"[a-z]+", pat.pattern))
        _KNOWN.update(COLOURS)
        _KNOWN.update(STOP)
        _KNOWN.update(COMMON)
    return _KNOWN


GREETINGS = (r"eid mubarak|eid ul (?:fitr|adha) mubarak|ramadan mubarak|ramzan mubarak|jumm?ah? mubarak|happy (?:birthday|new year|anniversary|diwali|holi|eid|"
             r"mothers? day|fathers? day|valentine'?s(?: day)?|independence day|graduation|wedding day)|merry christmas|congrat(?:ulation)?s|hbd")
GREETING_TEXT = {"hbd": "Happy Birthday", "congrats": "Congratulations", "congratulations": "Congratulations"}


def normalize(text):
    """Lower case, chat shorthand and common typos fixed, Roman Urdu turned into English words (quoted text untouched)."""
    s = str(text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    quotes = []

    def keep(m):
        quotes.append(m.group(0))
        return f" QQ{len(quotes) - 1}QQ "
    s = re.sub(r'"[^"]{1,80}"|(?<![a-z])\'[^\']{1,60}\'(?![a-z])', keep, s, flags=re.I)
    s = " ".join(s.lower().split())
    urdu = len(URDU_MARK.findall(s)) >= 2 or bool(re.search(r"\b(karo|kardo|krdo|kro|thora|thoda|zyada|hatao|lagao|daalo|wala|kaunsa|konsa|isko|awaz|gana)\b", s))
    if urdu:
        sound = re.search(r"\b(music|song|gana|gaana|awaz|aawaz|volume|sound|audio|beat)\b", s)
        s = re.sub(r"\b(?:awaz|aawaz|awaaz|aavaz)\b", "volume", s)
        s = re.sub(r"\b(?:gana|gaana|ganay|gaane)\b", "music", s)
        s = re.sub(r"\b(?:tez|taiz)\b", "louder" if sound else "faster", s)
        s = re.sub(r"\b(?:dheema|dheemi|dheeme|ahista|aahista)\b", "quieter" if sound else "slower", s)
        s = re.sub(r"\bkam\b", "lower" if sound else "less", s)
        s = re.sub(r"\b(?:zyada|ziada|zaida|jyada)\b", "louder" if sound else "more", s)
        for pat, rep in URDU:
            s = pat.sub(rep, s)
        s = " ".join(s.split())
    words = []
    for w in re.findall(r"[a-z0-9#:&.'\-]+|[^\sa-z0-9]", s):
        core = w.strip(".,!?;")
        if core in TYPOS:
            w = w.replace(core, TYPOS[core])
        elif len(core) >= 5 and core.isalpha() and core not in VOCAB and core not in STOP and core.rstrip("s") not in VOCAB \
                and core[:-2] not in VOCAB and core not in known_words() and core.rstrip("s") not in known_words():
            m = difflib.get_close_matches(core, VOCAB, n=1, cutoff=0.82 if len(core) >= 6 else 0.9)
            if m and not core.endswith(("ing", "ed")) or (m and difflib.SequenceMatcher(None, core, m[0]).ratio() >= 0.9):
                w = w.replace(core, m[0])
        words.append(w)
    s = " ".join(words)
    s = re.sub(r"\s+([,.!?;])", r"\1", s)
    for i, q in enumerate(quotes):
        s = s.replace(f"qq{i}qq", q)
    return s


PROTECT = [r"black and white", r"teal and orange", r"bride and groom", r"rock and roll", r"salt and pepper", r"fast and furious",
           r"black & white", r"before and after", r"up and down", r"back and forth", r"in and out", r"sara & adam", r"r&b"]


def clauses(text):
    """One message -> its separate asks. Quoted text and fixed pairs ("black and white") stay whole; a part with no
    verb of its own borrows the previous part's ("remove the shake and the flashes")."""
    s = str(text)
    quotes = []

    def keep(m):
        quotes.append(m.group(0))
        return f"\x00{len(quotes) - 1}\x00"
    s = re.sub(r'"[^"]*"|(?<![a-z])\'[^\']+\'(?![a-z])', keep, s, flags=re.I)
    for p in PROTECT:
        s = re.sub(p, lambda m: m.group(0).replace(" ", "\x01").replace("&", "\x02"), s, flags=re.I)

    def keep_list(m):  # "A, B and C" of short names (no instruction words in them) is one list, not three asks
        parts = [m.group(1), m.group(2), m.group(3)]
        if any(INSTRUCTION.search(x.lower()) or VERB_START.match(x.lower()) for x in parts):
            return m.group(0)
        return m.group(0).replace(", ", "\x03")
    s = re.sub(r"\b([A-Za-z0-9']+), ([A-Za-z0-9']+(?: [A-Za-z0-9']+)?),? and ([A-Za-z0-9']+(?: [A-Za-z0-9']+)?)\b", keep_list, s)
    parts = re.split(r"\s*(?:;|\.\s+|\?\s*|!\s+|\n|,?\s+also\s+|,?\s+and then\s+|,?\s+then\s+|,?\s+plus\s+|,\s+and\s+|,\s+but\s+|\s+but\s+|,\s+)\s*", s)
    out = []
    for p in parts:
        for q in re.split(r"\s+and\s+(?=(?:also\s+)?(?:make|change|add|remove|put|move|use|cut|turn|set|give|swap|replace|drop|delete|"
                         r"take|bring|keep|start|end|open|close|fade|mute|lower|raise|increase|decrease|try|switch|shake|zoom|flash|the|a|an|music|"
                         r"song|title|text|labels?|transitions?|filter|colou?r|look|shakes?|zooms?|flash(?:es)?|it|what|why|how|"
                         r"which|can|could|is|are|do|does|show|tell)\b)", p):
            q = q.strip(" ,.")
            if q:
                out.append(q)
    res = []
    for q in out:
        q = re.sub("\x00(\\d+)\x00", lambda m: quotes[int(m.group(1))], q).replace("\x01", " ").replace("\x02", "&").replace("\x03", " and ")
        if res:
            prev_verb = VERB_START.match(res[-1])
            if not VERB_START.match(q) and not QWORD_START.match(q):
                if not INSTRUCTION.search(q) and not _quoted(q) and re.match(r"(?:the|a|an|his|her|my|our|their|its|this|that|those|these|both)\b(?!')", q):
                    res[-1] = f"{res[-1]} and {q}"  # "slow motion on the wheel and the taillight": one ask about two things
                    continue
                if prev_verb and prev_verb.group(1) not in ("make", "is", "are") and not re.search(r"\b(?:is|are|should|looks?|feels?|sounds?)\b", q):
                    q = f"{prev_verb.group(1)} {q}"  # "add a flash and a shake at the drop": the second part is added too
        res.append(q)
    return res or [str(text).strip()]


VERB_START = re.compile(r"^(make|change|add|remove|put|move|use|cut|turn|set|give|swap|replace|delete|take|bring|keep|start|end|open|close|"
                        r"fade|mute|lower|raise|increase|decrease|try|switch|slow|speed|insert|include|drop|get rid of|is|are)\b")
QWORD_START = re.compile(r"^(what|what's|which|who|why|how|when|where|is|are|does|do|did|can|could|would|will|any|show|tell|list|explain)\b")
INSTRUCTION = re.compile(r"\b(?:bigger|smaller|larger|louder|quieter|softer|faster|slower|shorter|longer|brighter|darker|warmer|cooler|"
                         r"more|less|stronger|weaker|higher|lower|bold|top|bottom|cent(?:er|re)|middle|no|without|too|undo|redo|"
                         r"instead|again|back|off|on|in|out|up|down|first|last|only|every|each|all|"
                         r"\d+\s*(?:s|sec|seconds|minutes?)|" + "|".join(sorted((re.escape(c) for c in COLOURS), key=len, reverse=True)) + r")\b")


# ------------------------------------------------------------------------------------------------ the edit, read for follow-ups
def _cat():
    return Catalog.shared()


def item_key(e):
    """Catalogue key of a plan edit's item (effects can be scene or character effects)."""
    cat = _cat()
    name = e.get("name")
    if not name:
        return None
    cats = {"effect": ("scene_effect", "character_effect"), "filter": ("filter",), "transition": ("transition",)}.get(e.get("type"), ())
    for c in cats:
        if f"{c}:{name}" in cat.index.items:
            return f"{c}:{name}"
    keys = cat.exact(name)
    return next((k for k in keys if k.split(":")[0] in cats), keys[0] if keys else None)


def item_words(key):
    if not key:
        return ""
    n = _cat().index.notes.get(key) or {}
    return " ".join([key.split(":", 1)[1], str(n.get("en") or ""), str(n.get("desc") or ""), " ".join(n.get("tags") or [])]).lower()


KIND_WORDS = {"flash": ("flash", "strobe", "blink"), "glitch": ("glitch", "rgb", "chromatic", "aberration"),
              "shake": ("shake", "jitter", "tremble", "vibration", "quake", "wobble"), "grain": ("grain", "noise"),
              "vignette": ("vignette",), "letterbox": ("letterbox", "black bars", "widescreen", "cinematic aspect", "aspect ratio"),
              "leak": ("leak",), "blur": ("blur",)}


def fx_kinds(e, plan):
    """What a plan edit is, in the words people use: shake, zoom, pushin, flash, glitch, grain, vignette, letterbox, leak,
    effect, transition, filter, text, sfx, music."""
    t = e.get("type")
    eid = str(e.get("id"))
    rid = plan.get("_recipe_ids") or {}
    if t == "shake":
        return {"shake"}
    if t == "zoom":
        return {"zoom"}
    if t == "keyframes":
        return {"pushin"} if e.get("property") == "scale" else {"move"}
    if t in ("text", "captions", "filter", "transition"):
        return {t}
    if t == "sfx" or (t == "audio" and e.get("sound")):
        return {"sfx"}
    if t == "audio":
        return {"music"} if eid == "music" else {"voice"} if eid.startswith(("vo", "voice", "narr")) else {"audio"}
    if t != "effect":
        return {t}
    out = {"effect"}
    words = item_words(item_key(e)) + " " + str(e.get("expect") or "").lower()
    for k, ws in KIND_WORDS.items():
        if any(w in words for w in ws):
            out.add(k)
    if eid in set(rid.get("flash") or []):
        out.add("flash")
    if eid in set(rid.get("rgb_hit") or []):
        out.add("glitch")
    if e.get("layer") == "texture" or out & {"grain", "vignette", "letterbox"} and float(e.get("duration") or 0) > 0.5 * _total(plan):
        out.add("texture")
    return out


def _total(plan):
    return sum(float(c.get("duration") or 0) for c in plan.get("clips") or [])


def clip_times(plan):
    """{clip id: (start, end)} on the timeline (main track, back to back)."""
    out, t = {}, 0.0
    for c in plan.get("clips") or []:
        d = float(c.get("duration") or 0)
        out[c["id"]] = (t, t + d)
        t += d
    return out


def abs_window(plan, e, ct=None):
    ct = ct or clip_times(plan)
    if e.get("type") == "transition":
        a = ct.get(e.get("after"))
        return (a[1] - 0.2, a[1] + 0.2) if a else (0.0, 0.0)
    base = ct.get(e.get("on"), (0.0, 0.0))[0] if e.get("on") in ct else 0.0
    s = base + float(e.get("start", e.get("at", 0)) or 0)
    d = e.get("duration")
    if d is None and e.get("on") in ct:
        d = ct[e["on"]][1] - s
    return s, s + float(d or 0.5)


def sections(plan, design=None):
    """[(name, start, end)] of the edit: stored by compose, else rebuilt from the design's shot ids."""
    r = (plan.get("_rhythm") or {}).get("sections")
    if r:
        return [(x["name"], x["start"], x["end"]) for x in r]
    sec = {}
    for s in (design or {}).get("shots") or []:
        if isinstance(s, dict) and s.get("id"):
            sec[str(s["id"])] = s.get("section") or "verse"
    out, last = [], "intro"
    for cid, (a, b) in clip_times(plan).items():
        base = re.sub(r"(_\d+|[a-z])$", "", str(cid)) if str(cid) not in sec else str(cid)
        name = sec.get(str(cid)) or sec.get(base) or last
        last = name
        if out and out[-1][0] == name:
            out[-1] = (name, out[-1][1], b)
        else:
            out.append((name, a, b))
    return out


def text_roles(plan):
    """{text id: title|label|cta|caption}: kinetic and hook words are titles; three or more texts in one size and face
    are labels (places, steps, features); the rest by size."""
    texts = [e for e in plan.get("edits") or [] if e.get("type") in ("text", "captions")]
    roles, plain = {}, []
    for e in texts:
        tid, words = str(e.get("id")), str(e.get("text") or "")
        if e["type"] == "captions":
            roles[tid] = "caption"
        elif tid.startswith(("kt", "hk")):
            roles[tid] = "title"
        elif CTA_WORDS.search(words):
            roles[tid] = "cta"
        elif tid.startswith("lb") or re.search(r"lab|lbl|label|step|callout|tag", tid.lower()):
            roles[tid] = "label"
        elif re.search(r"title|headline|heading", tid.lower()):  # the designer called it a title: it stays one, whatever its size
            roles[tid] = "title"
        else:
            plain.append(e)
    sig = Counter(float(e.get("size") or 0) for e in plain)
    rest = []
    for e in plain:
        if sig[float(e.get("size") or 0)] >= 3:
            roles[str(e["id"])] = "label"
        else:
            rest.append(e)
    mx = max((float(e.get("size") or 0) for e in rest), default=0)
    for e in rest:
        roles[str(e["id"])] = "label" if len(rest) >= 3 and float(e.get("size") or 0) <= 0.7 * mx else "title"
    return roles


def _stem(w):
    for suf in ("ing", "es", "s", "ed"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_words(text):
    return [_stem(w) for w in re.findall(r"[a-z]+|\d+", str(text).lower()) if w not in STOP and (len(w) > 1 or w.isdigit())]


def main_title(titles):
    """THE title among the title texts (sorted by time): one the designer named a title, else the first; plus any other
    title with the same words (an opening and a closing card)."""
    if not titles:
        return []
    named = [e for e in titles if "title" in str(e.get("id")).lower()]
    first = (named or titles)[0]
    words = " ".join(str(first.get("text") or "").lower().split())
    return [e for e in titles if " ".join(str(e.get("text") or "").lower().split()) == words]


def match_existing_all(c, plan):
    """Every text of the edit named in full by the clause ("Fast, Secure and Smart")."""
    words_c = set(re.findall(r"[a-z]+|\d+", c.lower()))
    out = []
    for e in (plan or {}).get("edits") or []:
        if e.get("type") != "text":
            continue
        tw = [w for w in re.findall(r"[a-z]+|\d+", str(e.get("text") or "").lower()) if (len(w) >= 3 or w.isdigit()) and w not in STOP]
        if tw and all(w in words_c for w in tw) and str(e.get("text")) not in [str(x.get("text")) for x in out]:
            out.append(e)
    return out


def match_existing(c, plan):
    """The text of the edit that a clause names without quotes ("the discipline over motivation text", "the price",
    "step 2", "SATURDAY NIGHT"): all its words are in the clause (or a distinctive word of its id). None if none."""
    words_c = set(re.findall(r"[a-z]+|\d+", c.lower()))
    best, best_n = None, 0
    for e in (plan or {}).get("edits") or []:
        if e.get("type") != "text":
            continue
        tw = [w for w in re.findall(r"[a-z]+|\d+", str(e.get("text") or "").lower()) if (len(w) >= 3 or w.isdigit()) and w not in STOP]
        idw = [w for w in re.split(r"[^a-z0-9]+", str(e.get("id") or "").lower())
               if len(w) >= 4 and w not in ("title", "text", "label", "intro", "outro", "main", "hook", "card", "lbl", "caption")]
        n = len(tw) + 1 if tw and all(w in words_c for w in tw) else 1 if any(w in words_c for w in idw) else 0
        if n > best_n:
            best, best_n = e, n
    return best


def pick_texts(plan, who):
    """The plan's text edits a follow-up means. who: {"role", "match", "pos": first|last, "at": seconds}."""
    roles = text_roles(plan)
    ct = clip_times(plan)
    texts = [e for e in plan.get("edits") or [] if e.get("type") in ("text", "captions")]
    texts.sort(key=lambda e: abs_window(plan, e, ct)[0])
    role = who.get("role")
    if who.get("matches"):
        want = {" ".join(str(x).lower().split()) for x in who["matches"]}
        return [e for e in texts if " ".join(str(e.get("text") or "").lower().split()) in want]
    if who.get("match"):
        q = content_words(who["match"])
        cand = [e for e in texts if q and all(any(w in x for x in content_words(f"{e.get('text', '')} {e.get('id')}")) for w in q)]
        if not cand:  # most words in common
            scored = [(sum(any(w in x for x in content_words(f"{e.get('text', '')} {e.get('id')}")) for w in q), e) for e in texts]
            best = max((s for s, _ in scored), default=0)
            cand = [e for s, e in scored if best and s == best]
    elif role in ("title", "label", "cta", "caption"):
        cand = [e for e in texts if roles.get(str(e["id"])) == role]
        if role == "title" and not who.get("all") and not who.get("pos") and who.get("at") is None:
            cand = main_title(cand) or cand
        if not cand and role == "title":  # "the title" of an edit with only labels: its first text
            cand = [e for e in texts if roles.get(str(e["id"])) != "caption"][:1]
    else:
        cand = [e for e in texts if roles.get(str(e["id"])) != "caption" or role == "all"]
    if who.get("at") is not None:
        t = float(who["at"])
        near = [e for e in cand if abs_window(plan, e, ct)[0] - 0.3 <= t <= abs_window(plan, e, ct)[1] + 0.3]
        cand = near or sorted(cand, key=lambda e: abs(abs_window(plan, e, ct)[0] - t))[:1]
    if who.get("pos") == "first":
        cand = cand[:1]
    elif who.get("pos") == "last":
        cand = cand[-1:]
    if any(str(e["id"]).startswith("kt") for e in cand):  # a word-by-word title is one title
        cand += [e for e in texts if str(e["id"]).startswith("kt") and e not in cand]
    return cand


def media_text(a):
    bits = [re.sub(r"[-_]+", " ", str(a.get("file", "")).rsplit(".", 1)[0]), str(a.get("summary") or "")]
    for m in a.get("moments") or []:
        bits += [str(m.get(k) or "") for k in ("subject", "action", "setting", "notes")]
    return " ".join(bits).lower()


SYN = {"sunset": ["sunset", "dusk", "golden hour", "sun setting", "sundown"], "beach": ["beach", "shore", "coast", "sand", "seaside"],
       "car": ["car", "vehicle", "driving"], "kiss": ["kiss", "kissing"], "ring": ["ring", "rings"], "goal": ["goal", "scor", "net"],
       "pool": ["pool", "swimming"], "dj": ["dj", "turntable", "deck"], "crowd": ["crowd", "audience", "people"],
       "mountain": ["mountain", "hill", "peak"], "ocean": ["ocean", "sea", "waves"], "boat": ["boat", "ship", "yacht"],
       "drone": ["aerial", "drone", "from above"], "aerial": ["aerial", "drone", "from above", "overhead"],
       "food": ["food", "dish", "plate", "meal"], "fire": ["fire", "flame", "flames"], "eye": ["eye", "eyes"], "face": ["face", "close-up", "portrait"]}


def _has(text, word):
    """A word (or its longer forms) in a text: "kiss" finds "kissing", "end" does not find "extended"."""
    return re.search(r"\b" + re.escape(word), text) is not None


def match_files(words, analyses):
    """Files whose name, summary and captions contain the words, best first: [(file, score)]."""
    q = [w for w in content_words(words) if w not in ("shot", "clip", "scene", "footage", "part", "one", "video", "first", "last", "second", "third")]
    out = []
    for a in analyses.values():
        if a.get("kind") not in ("video", "image"):
            continue
        txt = media_text(a)
        score = 0.0
        for w in q:
            alts = SYN.get(w, [w])
            if any(_has(txt, x) for x in alts):
                score += 1 + (0.5 if any(_has(re.sub(r"[-_]+", " ", str(a.get("file", "")).lower()), x) for x in alts) else 0)
        if score:
            out.append((a["file"], score))
    out.sort(key=lambda x: -x[1])
    return out


def match_shots(words, design, analyses, ratio=0.6):
    """Design shots the words describe (file name, the shot's 'want', its label, the file's captions), best first; only
    the ones that fit about as well as the best (ratio of its score): "the wheel and the taillight" gives both, "the
    waterfall" does not also give every shot that shares a minor word."""
    q = [w for w in content_words(words) if w not in ("shot", "clip", "scene", "footage", "part", "one", "video")]
    byfile = {str(a.get("file", "")).lower(): a for a in analyses.values()}
    out = []
    for s in design.get("shots") or []:
        if not isinstance(s, dict) or s.get("fill"):
            continue
        a = byfile.get(str(s.get("file") or "").lower(), {})
        own = f"{s.get('want', '')} {s.get('label', '')}".lower()
        fname = re.sub(r"[-_]+", " ", str(s.get("file") or "")).lower()
        cap = media_text(a)
        score = 0.0
        for w in q:
            alts = SYN.get(w, [w])
            # the word itself beats a synonym ("sunset" over "dusk"); the shot's own description beats the file's captions
            score += (2.5 if _has(own, w) else 2 if any(_has(own, x) for x in alts) else 0) + \
                (1.5 if any(_has(fname, x) for x in alts) else 0) + (0.5 if any(_has(cap, x) for x in alts) else 0)
        if score:
            out.append((s, score))
    out.sort(key=lambda x: -x[1])
    top = out[0][1] if out else 0
    return [s for s, sc in out if sc >= ratio * top]


# ------------------------------------------------------------------------------------------------ reading one clause
def _amount(c):
    if re.search(r"\b(?:" + ALOT + r")\b", c):
        return 1.8
    if re.search(r"\b(?:" + ABIT + r")\b", c):
        return 0.5
    return 1.0


def _seconds(c):
    """A length in the clause ("30 seconds", "30s", "half a minute", "1:15", "a minute"), or None."""
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", c)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:m|min|mins|minutes?)\b", c)
    if m:
        return float(m.group(1)) * 60
    m = re.search(r"\b(\d):([0-5]\d)\b", c)
    if m and m.group(0) not in ("9:16", "1:1", "4:5", "4:3", "3:4", "2:3", "3:2") and not re.search(r"\b16:9\b|\b21:9\b", c) and \
            re.search(r"\b(long|length|cut|trim|make|keep|under|duration|to)\b", c):
        return int(m.group(1)) * 60 + int(m.group(2))
    if re.search(r"\bhalf a minute\b", c):
        return 30.0
    if re.search(r"\b(?:a|one) minute\b", c):
        return 60.0
    m = re.search(r"\b(?:to|under|max(?:imum)?|at most|around|about|exactly)\s+(\d{1,3})\b(?!\s*(?:%|x|bpm))", c)
    if m and re.search(r"\b(long|length|cut|trim|shorten|make it|keep it|duration|seconds?)\b", c):
        return float(m.group(1))
    return None


def _time_point(c):
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", c)
    if m and not re.search(r"\b(?:make|cut|trim|keep|length|long)\b", c):
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"\b(?:at|around|near|from)\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)?\b", c)
    if m:
        return float(m.group(1))
    return None


def _anchor(c):
    """Where on the timeline the clause puts something: start, end, drop, a time, or None."""
    t = _time_point(c)
    if t is not None:
        return t
    if re.search(r"\b(?:at|on|for|with|during|in)?\s*the (?:drop|climax|peak|beat drop|best part|highlight)|when the (?:beat|drop|bass) (?:drops|hits)|\bdrop\b", c):
        return "drop"
    if re.search(r"\b(?:at|in|for)? ?the (?:end|ending|outro|finish|last (?:second|part|shot|clip|frame))|\bend (?:with|on)\b|\bending\b|\bat the end\b|\bfinal\b", c):
        return "end"
    if re.search(r"\b(?:at|in)? ?the (?:start|beginning|intro|opening|first second)|\bstart (?:with|on)\b|\bopen(?:ing)? with\b|\bintro\b|\bbeginning\b", c):
        return "start"
    return None


def _section_scope(c):
    for name, pat in (("intro", r"\b(?:intro|beginning|opening|start|first part)\b"), ("outro", r"\b(?:outro|ending|end|last part|final part)\b"),
                      ("drop", r"\b(?:drop|climax|peak)\b"), ("middle", r"\b(?:middle|mid part|middle part|verse)\b"), ("build", r"\bbuild(?:-?up)?\b"),
                      ("break", r"\bbreak(?:down)?\b")):
        if re.search(pat, c):
            return name
    return None


def _quoted(c):
    m = re.search(r'"([^"]+)"|(?<![a-z])\'([^\']+)\'(?![a-z])', c, re.I)
    return (m.group(1) or m.group(2)).strip() if m else None


def _subjects(c):
    found = []
    for name, pat in SUBJECTS:
        m = pat.search(c)
        if m:
            found.append((m.start(), name))
    names = [n for _, n in sorted(found)]
    if "look" in names and re.search(r"\b(?:looks?|looked|looking) (?:so |really |kind of |kinda |a bit |pretty |super |too |very )?(?:cheap|amateur\w*|bad|good|great|"
                                     r"nice|amazing|awesome|ugly|weird|off|wrong|fine|better|worse|boring|dull|fake|terrible|awful|perfect|beautiful|stunning|"
                                     r"gorgeous|cool|sick|fire|epic|bland|low quality|like|messy|busy|cluttered|clean)\b", c) \
            and not re.search(r"\b(?:the|this|a|that|new|old|colou?r|film|warm|cool|vintage|cinematic|whole) look\b|\blook (?:of|is|was)\b", c):
        names.remove("look")  # "the code screens look cheap": an opinion, not the colour look
    if "sfx" in names and "music" in names and not re.search(r"\b(?:music|song|track|bgm)\b", c):
        names.remove("music")  # "sound effects" also matched "audio"-ish words
    if "music" in names and re.search(r"\bbeat\b", c) and not re.search(r"\b(?:music|song|track)\b", c) and re.search(r"\bon (?:the|every) beat\b", c):
        names.remove("music")  # "flashes on every beat": the beat is a time, not the music
    if "length" in names and "text" in names and not re.search(r"\b(?:video|edit|it|whole thing|reel)\b", c):
        names.remove("length")
    return names


def _who_text(c, subj, focus, plan=None):
    who = {}
    # the most specific word decides ("the font of the title" is about the title; "fonts" alone is about all text)
    role = next((r for r in ("cta", "caption", "label", "title", "text") if r in subj), None)
    named = match_existing(c, plan) if plan else None
    several = match_existing_all(c, plan) if plan else []
    if len(several) > 1 and role in (None, "text", "label", "title"):
        return {"matches": [str(e.get("text") or "") for e in several]}
    if named is not None and role in (None, "text", "title", "label", "cta"):
        who = {"match": str(named.get("text") or "")}  # "the price text", "SATURDAY NIGHT", "the GOAL text"
        if re.search(r"\b(?:at|in) the (?:end|ending|outro|last)\b", c):
            who["pos"] = "last"
        elif re.search(r"\b(?:at|in) the (?:start|beginning|intro|opening)\b", c):
            who["pos"] = "first"
        return who
    if role is None and focus and focus.get("kind") == "text":
        return dict(focus.get("who") or {"role": "title"})
    who["role"] = "all" if role == "text" and re.search(r"\b(?:all|every|everything)\b", c) else (role or "title")
    if who["role"] == "title" and re.search(r"\b(?:titles|all (?:the )?titles|every title|both titles)\b", c):
        who["all"] = True
    m = re.search(r"\bthe (first|last|opening|ending|end|final|closing) (?:title|text|label|caption)", c) or \
        re.search(r"\b(?:title|text|label|caption|words?|card)s? (?:at|in) the (start|beginning|end|ending|outro|intro|opening)\b", c)
    if m:
        who["pos"] = "first" if m.group(1) in ("first", "opening", "start", "beginning", "intro") else "last"
    t = _time_point(c)
    if t is not None:
        who["at"] = t
    return who


NOT_TEXT = re.compile(r"^(?:the )?(?:" + "|".join(sorted((re.escape(c) for c in COLOURS), key=len, reverse=True)) +
                      r"|top|bottom|cent(?:er|re)|middle|upper|lower|left|right|bigger|smaller|larger|bold|italic|caps|uppercase|"
                      r"lowercase|read|see|look|handwritten|script|serif|font|size|position|front|back|end|start|drop|beginning|"
                      r"same|different|another|other|it|them|that|this)\b")


def _text_value(raw):
    """(new words, old words) in "change the title to X", "the title should say X", "rename it X", "change 'A' to 'B'",
    "replace 'A' with B", "use 'B' instead of 'A'", "it's 'A' not 'B'". Read from the clause as typed (case kept).
    Unquoted words count only after a verb that means writing ("say", "read", "rename", "change ... to") and never when
    they describe a look ("to the top", "to red", "easier to read")."""
    qs = [a or b for a, b in re.findall(r'"([^"]+)"|(?<![A-Za-z])\'([^\']+)\'(?![A-Za-z])', raw)]
    low = raw.lower()
    if len(qs) >= 2:
        if re.search(r"\binstead of\b", low) or (re.search(r"\bnot\b", low) and low.find(" not ") > low.find(qs[0].lower())):
            return qs[0], qs[1]  # "use 'B' instead of 'A'", "it's 'B' not 'A'"
        return qs[1], qs[0]  # "change 'A' to 'B'", "replace 'A' with 'B'"
    if len(qs) == 1:
        q = qs[0]
        m = re.search(r"['\"]" + re.escape(q) + r"['\"]\s+(?:to|with|into|by)\s+(.+)$", raw, re.I)
        if m and re.search(r"\b(?:change|replace|rename|swap|switch|turn)\b", low) and not NOT_TEXT.match(m.group(1).lower()):
            return m.group(1).strip(" .,!"), q
        return q, None
    m = re.search(r"\b(?:should (?:say|read)|to say|to read|say|says|saying|reads?|reading|that says|with the words|call(?:ed)? it|"
                  r"rename (?:it|the \w+)? ?(?:to|as)?|retitle (?:it )?(?:to|as)?|change (?:it|the (?:title|text|label|caption|cta|words?))(?: text)? to|"
                  r"text to|words to|title to|label to)\s+(.+)$", raw, re.I)
    if not m:
        return None, None
    val = m.group(1)
    val = re.split(r"\s+(?:in|with|at|on|when|and make|and put|using|but)\s+(?:the\s+|a\s+|an\s+)?(?=" + "|".join(COLOURS) +
                   r"|top|bottom|cent|middle|end|start|drop|beginning|font|size|bigger|smaller|bold|caps)", val, maxsplit=1, flags=re.I)[0]
    val = val.strip(" .,!")
    if not val or NOT_TEXT.match(val.lower()) or len(val) > 60:
        return None, None
    return _typed_case(val), None


ORIGINAL = {"text": ""}  # the message as typed (normalize() lowercases); set by the conversation for each message


def _typed_case(val):
    m = re.search(re.escape(val), ORIGINAL.get("text") or "", re.I)
    return m.group(0) if m else val


def parse(clause, ctx):
    """One clause -> {"ops": [...], "focus": {...} | None, "note": str}. ctx: {"design", "plan", "analyses", "focus",
    "last_ops", "last_items"}."""
    raw = " ".join(str(clause).split())
    c = " " + raw.lower() + " "
    cq = re.sub(r'"[^"]*"|(?<![a-z])\'[^\']+\'(?![a-z])', " qtext ", c, flags=re.I)  # the clause without the quoted words
    focus = ctx.get("focus")
    kept = re.search(r"\b(?:except(?: for)?|but not|apart from|other than|but keep|keep(?:ing)? the|leave the)\b(.*)$", cq)
    keep_subj = _subjects(kept.group(1)) if kept else []
    subj = _subjects(cq[:kept.start()] if kept else cq) or _subjects(cq)
    ctx = {**ctx, "raw": raw, "keep_subj": keep_subj}
    amt = _amount(c)
    ops = []

    def done(kind, **kw):
        return {"ops": ops, "focus": {"kind": kind, **kw}, "note": ""}

    is_remove = bool(re.search(r"\b(?:" + REMOVE + r")\b", cq)) and not re.search(r"\bno\b[ ,]+(?:i|it|the other|not|that's|thats)\b", cq)
    is_add = bool(re.search(r"\b(?:" + ADD + r")\b", cq)) or bool(re.match(r"\s*(?:flash|shake|zoom|glitch|punch)\b(?! (?:more|less|harder|softer))", cq)) \
        or bool(re.search(r"\b(?:hit|hits|land|lands|come|comes|start|starts|end|ends|open|opens|finish|finishes) with (?:a|an|some|the)\b", cq))
    up = bool(re.search(r"\b(?:" + UP + r")\b", cq))
    down = bool(re.search(r"\b(?:" + DOWN + r")\b", cq))
    too = re.search(r"\btoo (\w+)", cq)
    if too:  # "too loud" asks for the opposite
        w = too.group(1)
        if re.match(r"(?:loud|big|large|strong|much|many|bright|fast|long|intense|busy|saturated|warm|zoomed|shaky|harsh|heavy)", w):
            up, down = False, True
        elif re.match(r"(?:quiet|small|weak|little|dark|slow|short|subtle|soft|dull|cold|flat|boring|plain)", w):
            up, down = True, False

    # ---- energy / calm bundles ("more energy", "it's boring", "too busy", "tone it down")
    energy = re.search(r"\b(?:more (?:energy|energetic|hype|dynamic|exciting|intense|punch|impact|action)|(?:make it|it'?s|feels?|so) (?:boring|flat|dull|lifeless|plain)|(?:it'?s|feels?|so|too) slow(?! ?-?mo| ?motion)|"
                       r"spice (?:it )?up|make it pop|hype (?:it )?up|more aggressive|harder hitting|pump it up|amp it up|livelier|go crazy|more crazy)\b", c)
    if energy and not set(subj) & {"title", "label", "text", "cta", "caption", "music", "look", "zoom", "shake", "flash", "glitch", "speed"}:
        ops += [{"op": "recipe", "use": "zoom_punch", "on": "downbeats", "sections": ["build", "drop"], "strength": 1.2},
                {"op": "recipe", "use": "flash", "on": "drop"}, {"op": "recipe", "use": "shake", "on": "downbeats", "sections": ["drop"], "strength": 0.5},
                {"op": "pace", "mul": 0.85}]
        return done("energy_bundle")
    fk = (focus or {}).get("kind")
    if fk == "energy_bundle" and not subj and re.search(r"\b(?:tone (?:it|that|them) down|too much|too many|too strong|that'?s (?:insane|crazy|a lot|too much|overkill)|"
                                                     r"calm (?:it|them) down|dial (?:it|them) back|less)\b", c):
        return {"ops": [{"op": "fx", "kind": k, "thin": 2, "mul": {"strength": 0.8}} for k in ("zoom", "shake", "flash")], "focus": focus, "note": ""}
    if fk in ("shake", "zoom", "flash", "glitch") and not subj and re.search(r"\b(?:tone (?:it|that|them) down|too much|too many|too strong|"
                                                                         r"that'?s (?:insane|crazy|a lot|too much|overkill)|calm (?:it|them) down|"
                                                                         r"dial (?:it|them) back|less)\b", c):
        return {"ops": [{"op": "fx", "kind": fk, "thin": 2, "mul": {"strength": 0.8}}], "focus": focus, "note": ""}
    calm = re.search(r"\b(?:tone (?:it|that|things|everything) down|too (?:much|busy|chaotic|crazy|hectic|overwhelming|distracting|intense)|"
                     r"calm (?:it|things) down|less (?:busy|chaotic|crazy|effects)|cleaner|more minimal|minimalist|less is more|"
                     r"hurts? my eyes|too many effects|over ?the ?top|overdone|simpler)\b", c)
    if calm and not set(subj) & {"title", "label", "text", "cta", "caption", "music", "transition", "look", "shake", "zoom", "flash", "glitch"}:
        ops += [{"op": "fx", "kind": "flash", "remove": True}, {"op": "fx", "kind": "glitch", "remove": True},
                {"op": "fx", "kind": "shake", "remove": True}, {"op": "fx", "kind": "zoom", "thin": 2, "mul": {"strength": 0.8}}]
        return done("calm")
    if re.search(r"\bmore cinematic|make it (?:look )?cinematic|movie(?:-| )like|like a (?:movie|film)|filmic\b", c) and not set(subj) & {"music", "title", "text", "label"}:
        ops += [{"op": "look", "words": "cinematic film movie teal", "name": "cinematic"},
                {"op": "texture", "what": "letterbox", "add": True}, {"op": "pace", "mul": 1.15}]
        return done("look")

    # ---- a label for a shot: "label the cabin shot 'Mountain Retreat'", "call the pool shot 'Infinity Pool'"
    lm = re.search(r"\b(?:label|name|call|title|tag) (?:the |that |this )?(.+?) (?:shot|clip|scene|part|room|bit|area)?\s*(?:as |with |:)?\s*['\"](.+?)['\"]", raw, re.I)
    if lm:
        hits = match_shots(lm.group(1), ctx.get("design") or {}, ctx.get("analyses") or {})
        if hits:
            ops.append({"op": "text_add", "text": lm.group(2), "anchor": {"shot": hits[0]["id"]}, "role": "label", "position": "lower", "color": None})
            return done("text", who={"match": lm.group(2)})

    # ---- words in quotes to show: "end with 'follow for more'", "put 'SALE' at the top"
    qv = _quoted(raw)
    if qv and _text_exists(ctx.get("plan"), qv):
        qv = None  # "put 'THE BAY' at the top": that text is already there; this is about moving it
    if qv and not set(subj) & {"music", "transition", "look", "shake", "zoom", "flash", "glitch", "effects", "sfx"} and (
            is_add or re.search(r"\b(?:end|finish|close|start|open|begin)(?:s|ing)? (?:it |the video )?with\b|\b(?:write|show|display)\b", c)) \
            and not re.search(r"\b(?:change|rename|replace|instead|should say|to say)\b", c):
        anchor = _anchor(c) or ("end" if re.search(r"\b(?:end|finish|close)", c) or CTA_WORDS.search(qv) else "start")
        role = "cta" if CTA_WORDS.search(qv) else "label" if "label" in subj else "title"
        col = COLOUR_RE.search(c)
        ops.append({"op": "text_add", "text": qv, "anchor": anchor, "role": role, "position": next((v for pp, v in POSITIONS if re.search(pp, c)), None),
                    "color": COLOURS.get(col.group(1)) if col else None})
        return done("text", who={"match": qv})

    # ---- a text to add, unquoted: a date, a number, a handle, a website, "the text X"
    tm = re.search(r"^\s*(?:please |pls |also |and )?(?:add|put|write|show|include|insert|place)\s+(?:the |a |an |my |our )?(?:date|time|year|price|phone(?: number)?|number|"
                   r"website|url|link|handle|instagram|location|address|names?|caption|tagline|text|words?|line)\s+(?:saying |that says |of |:)?\s*"
                   r"(.+?)(?=\s+(?:under|below|beneath|above|over|next to|at|in|on|to|for)\s+(?:the|a|an|my|our|\d)|\s*$)", raw, re.I)
    if tm and is_add and not _quoted(raw):
        val = tm.group(1).strip(" .,!")
        generic = re.match(r"(?:the|a|an|some|all|every|each|my|our|their|his|her)\b", val.lower()) and not re.search(r"\d|@", val)
        if val and not generic and not NOT_TEXT.match(val.lower()) and (re.search(r"\d|@|\.(?:com|net|org|io)\b", val) or len(val.split()) <= 6):
            ref = re.search(r"\b(under|below|beneath|above|over|next to)\s+(?:the |my |our )?(.+?)\s*$", c)
            anchor, pos = _anchor(c), None
            if ref:
                tgt = match_existing(ref.group(2), ctx.get("plan")) or next(iter(pick_texts(ctx.get("plan") or {}, {"role": "title"})), None) \
                    if re.search(r"\b(?:title|names?|heading)\b", ref.group(2)) else match_existing(ref.group(2), ctx.get("plan"))
                if tgt is not None:
                    anchor = {"text": tgt.get("id")}
                    pos = "_below" if ref.group(1) in ("under", "below", "beneath") else "_above"
            ops.append({"op": "text_add", "text": val, "anchor": anchor if anchor is not None else "start",
                        "role": "cta" if CTA_WORDS.search(val) else "label", "position": pos or next((v for pp, v in POSITIONS if re.search(pp, c)), None),
                        "color": None})
            return done("text", who={"match": val})

    # ---- a greeting for an occasion, unquoted ("add eid mubarak", "put happy birthday at the end")
    gm = re.search(r"\b(add|put|write|show|include|with|wish)\b.{0,20}?\b(" + GREETINGS + r")\b", c)
    if gm and (is_add or gm.group(1) in ("wish", "with")) and not _quoted(raw) and not set(subj) & {"music", "transition", "look", "sfx"}:
        val = GREETING_TEXT.get(gm.group(2), gm.group(2).title())
        anchor = _anchor(c) or ("end" if re.search(r"\b(?:end|finish|close|last)", c) else "start")
        col = COLOUR_RE.search(c)
        ops.append({"op": "text_add", "text": val, "anchor": anchor, "role": "title", "position": next((v for pp, v in POSITIONS if re.search(pp, c)), None),
                    "color": COLOURS.get(col.group(1)) if col else None})
        return done("text", who={"match": val})

    # ---- canvas / platform
    cv = re.search(r"\b(16:9|9:16|1:1|4:5)\b", c)
    plat = None
    if not cv:
        if re.search(r"\b(?:horizontal|landscape|widescreen)\b", c) or re.search(r"\b(?:for|on|to) youtube\b(?! shorts)|\byoutube (?:version|video|format)\b", c):
            cv, plat = "16:9", "youtube"
        elif re.search(r"\b(?:vertical|portrait)\b", c) or re.search(r"\b(?:for|on|to) (?:tiktok|reels|shorts|youtube shorts|stories|snapchat)\b|\b(?:tiktok|reels?|shorts) (?:version|format)\b", c):
            cv, plat = "9:16", "tiktok" if "tiktok" in c else "instagram_reels" if "reel" in c else "youtube_shorts" if "short" in c else None
        elif re.search(r"\bsquare\b", c):
            cv, plat = "1:1", "square"
        elif re.search(r"\b(?:instagram (?:feed|post)|feed post)\b", c):
            cv, plat = "4:5", "instagram_feed"
    else:
        cv = cv.group(1)
    if cv and (re.search(r"\b(?:make|turn|convert|change|switch|version|format|for|crop|reframe|export|do|need|want|put|redo|it|as)\b", c) or len(c.split()) <= 4):
        ops.append({"op": "canvas", "value": cv if isinstance(cv, str) else cv, "platform": plat})
        if _seconds(c) is None and not re.search(r"\b(?:shorter|longer|trim|cut (?:it )?(?:down|to)|length)\b", c):
            return done("canvas")

    # ---- "it's too short" right after naming a shot: that shot, not the whole video
    shf = (focus or {}).get("shots") if (focus or {}).get("kind") == "shot" else None
    if shf and _seconds(c) is None and re.search(r"\b(?:it'?s|it is|its|make it|it should be|could be|needs to be|keep it)\s*(?:a bit |a little |way |too |much |"
                                                 r"slightly |longer|shorter)*(short|long|shorter|longer)\b", c):
        f = 0.6 if re.search(r"\btoo long\b|\bshorter\b", c) else 1.6 if re.search(r"\btoo short\b|\blonger\b", c) else 1.0
        if f != 1.0:
            return {"ops": [{"op": "shot_beats", "id": i, "mul": f} for i in shf], "focus": focus, "note": ""}

    # ---- "I'd prefer something more upbeat": the music
    pm = re.search(r"\b(?:prefer|want|try|go with|use|rather have|like|need|give me|how about) something (?:more |a bit more |a little more |that'?s |"
                   r"that is )?([a-z\-]+)", c)
    if pm and not set(subj) - {"music"}:
        g = next((g for g, p_ in GENRE_RE.items() if p_.search(pm.group(1))), None)
        if g:
            ops.append({"op": "music", "generate": g})
            return done("music")

    # ---- length
    secs = _seconds(c)
    length_words = re.search(r"\b(?:shorter|longer|shorten|lengthen|trim|cut (?:it|the video|this) (?:down|to)|too long|too short|length|duration|"
                             r"under \d+|max \d+|half the length|double the length|twice as long)\b", c)
    text_ctx = set(subj) & {"title", "label", "text", "cta", "caption"}
    part = _section_scope(c)
    if secs is None and (length_words or (focus or {}).get("kind") == "length") and not text_ctx:
        m = re.search(r"(?<![:\d.])\b(\d{1,3})\b(?![:\d])", c)
        if m and 5 <= int(m.group(1)) <= 600:
            secs = float(m.group(1))
    if (secs is not None and (length_words or re.search(r"\b(?:make|cut|keep|trim|it|video|edit|reel)\b", c) or (focus or {}).get("kind") == "length") and not text_ctx
            and not re.search(r"\b(?:at|around|from)\s+\d", c) and "music" not in subj and not re.search(r"\b(?:transition|fade)", c)):
        if re.search(r"\bunder\b", c):
            secs = max(5.0, secs - 1.0)
        ops.append({"op": "length", "seconds": secs})
        return done("length")
    if length_words and not text_ctx and not part and not set(subj) & {"music", "transition", "speed", "sfx"}:
        if re.search(r"\bdouble|twice\b", c):
            ops.append({"op": "length", "mul": 2.0})
        elif re.search(r"\bhalf\b", c):
            ops.append({"op": "length", "mul": 0.5})
        elif re.search(r"\b(?:longer|lengthen|too short)\b", c):
            ops.append({"op": "length", "mul": 1 + 0.25 * amt})
        else:
            ops.append({"op": "length", "mul": max(0.4, 1 - 0.25 * amt)})
        return done("length")

    # ---- speed (slow motion, ramps, freeze, reverse) on a shot or a part
    if "speed" in subj and re.search(r"\b(?:speed (?:up|down)|slow (?:down|it down)|faster|slower)\b.{0,12}\b(?:music|song|beat|track|tempo|bpm|bgm)\b|"
                                     r"\b(?:music|song|beat|track|tempo|bpm|bgm)\b.{0,12}\b(?:faster|slower|sped up)\b", c):
        subj = [s_ for s_ in subj if s_ != "speed"] or ["music"]
    if "speed" in subj:
        kind = "slow" if re.search(r"slow ?mo|slow-mo|slow motion|slow (?:down|it down)", c) else "velocity" if re.search(r"speed ramp|velocity", c) else \
            "freeze" if "freeze" in c else "fast" if re.search(r"time ?lapse|fast forward|sped up|speed up", c) else "reverse" if "revers" in c else None
        target = _shot_target(c, ctx)
        if is_remove or re.search(r"\b(?:normal speed|real ?time)\b", c):
            ops.append({"op": "speed_reset", "kinds": [kind] if kind else ["slow", "velocity", "fast", "freeze"]})
            return done("speed")
        if kind == "reverse":
            files = [s.get("file") for s in target] if target else []
            ops.append({"op": "clips", "files": files, "set": {"reverse": True}})
            return done("speed")
        if kind and not target and kind in ("slow", "velocity") and re.search(r"\b(?:overall|everywhere|throughout|in general|all over|more of it|"
                                                                            r"whole (?:video|thing|edit)|more slow)\b|^\s*(?:make|turn|put|do|have)\s+"
                                                                            r"(?:it|this|everything|the video|the edit)\s+(?:in(?:to)?\s+|all\s+)?"
                                                                            r"(?:slow ?mo|slow-mo|slow motion|a speed ramp|velocity)", c):
            shots_ = [s for s in (ctx.get("design") or {}).get("shots") or [] if isinstance(s, dict) and not s.get("fill")]
            heroes = [s for s in shots_ if s.get("section") == "drop"][:1] + [s for s in shots_ if s.get("section") in ("verse", "build")][-1:] + shots_[-1:]
            target = [s for i, s in enumerate(heroes) if s and s not in heroes[:i]]
            for s in target[:3]:
                ops.append({"op": "shot", "id": s["id"], "field": "speed", "value": kind})
            return done("speed", shots=[s["id"] for s in target[:3]])
        if kind:
            if not target:
                words = {"slow": "slow motion", "velocity": "a speed ramp", "freeze": "a freeze frame", "fast": "fast motion"}[kind]
                return {"ops": [], "focus": {"kind": "speed"}, "note": "which shot", "template": f"{words} on {{}}",
                        "ask": f"Which moment should get {words}? (e.g. 'the drop', 'the last shot', 'the wheel')"}
            for s in target[:2]:
                ops.append({"op": "shot", "id": s["id"], "field": "speed", "value": kind})
                if kind in ("slow", "freeze"):
                    ops.append({"op": "shot", "id": s["id"], "field": "hold", "value": True})
            return done("speed", shots=[s["id"] for s in target[:2]])

    # ---- a text's own movement ("... and shake more" right after talking about a text)
    if (focus or {}).get("kind") == "text" and re.fullmatch(r"\s*(?:and )?(?:(?:make )?it |let it |it should |should )?(?:shake|pulse|bounce|wiggle|flicker|"
                                                            r"zoom|flash|blink)(?:s|es)?(?: (?:more|a bit|a little|too|a lot|harder))?\s*", c):
        subj = subj or ["shake"]
        ops.append({"op": "text", "who": dict(focus.get("who") or {"role": "title"}),
                    "set": {"loop_words": {"shake": "shake", "zoom": "pulse zoom", "flash": "flash blink"}[subj[0]]}})
        return done("text", who=focus.get("who"))

    # ---- music
    if "music" in subj or (focus and focus.get("kind") == "music" and not subj and _elliptical(c, "music") and (up or down or is_remove or any(p.search(c) for p in GENRE_RE.values()))) \
            or (not subj and re.search(r"\b(?:louder|quieter|volume|can'?t hear|too loud)\b", c)):
        if "voice" in subj and "music" not in subj:
            pass
        else:
            return _music(c, ctx, amt, up, down, is_remove, ops) or {"ops": [], "focus": {"kind": "music"}, "note": "music: what to do"}
    if "voice" in subj and re.search(r"\b(?:quiet|hard to hear|can'?t hear|barely hear|too low|too soft|muffled|not loud enough)\b", c):
        up, down = True, False
    if "voice" in subj and (up or down):
        f = (1 + 0.35 * amt) if up else 1 / (1 + 0.35 * amt)
        ops.append({"op": "audio", "who": "voice", "mul": {"volume": f}})
        return done("voice")
    if "clip_audio" in subj:
        if is_remove:
            ops.append({"op": "clips", "files": [], "set": {"volume": 0.0}})
        else:
            f = (1 + 0.5 * amt) if (up or re.search(r"\b(?:keep|hear|want|bring back)\b", c)) else 1 / (1 + 0.5 * amt)
            ops.append({"op": "clips", "files": [], "mul": {"volume": f}, "min": 0.6 if re.search(r"\b(?:keep|hear|bring back)\b", c) else 0})
        return done("clip_audio")

    # ---- a sound that cannot be synthesised ("a sizzle sound", "crowd cheering sound")
    snd = re.search(r"\b(?:an? |some |the )?([a-z]+(?: [a-z]+)?) (?:sound|noise|sfx|sound effect)s?\b", c)
    known = ("whoosh", "swoosh", "impact", "riser", "sub drop", "thunder", "glitch", "hit", "boom", "transition", "original", "clip",
             "ambient", "natural", "background", "real", "camera", "crowd", "the", "more", "less", "louder", "quieter")
    if snd and is_add and not any(k in snd.group(1) for k in known) and "music" not in subj:
        thing = snd.group(1).strip()
        rest = re.sub(r"^.*?\b(?:sound|noise|sfx)s?\b", "", c)
        f = match_files(rest, ctx.get("analyses") or {})
        opts = []
        if f:
            opts.append({"label": f"raise the clip's own sound on {f[0][0]} (it has the real {thing})",
                         "ops": [{"op": "clips", "files": [f[0][0]], "mul": {"volume": 1.8}, "min": 0.8}]})
        opts.append({"label": "a whoosh there instead", "ops": [{"op": "sfx_add", "sound": "whoosh", "anchor": _anchor(c) or "drop"}]})
        return {"ops": [], "focus": {"kind": "sfx"}, "note": f"no {thing} sound",
                "ask": f"I can't make a {thing} sound: the sounds I synthesise are impact, hit, whoosh, swoosh, riser, sub drop, thunder and glitch.",
                "options": opts}

    # ---- sound effects
    if "sfx" in subj:
        sounds = [s for s in ("whoosh", "swoosh", "impact", "riser", "sub_drop", "thunder", "glitch", "hit") if s.replace("_", " ") in c or s in c]
        if re.search(r"\bboom", c):
            sounds.append("impact")
        if is_remove:
            ops.append({"op": "audio", "who": "sfx", "sounds": sounds, "remove": True})
        elif is_add or re.search(r"\bon (?:every|each|all|the) transitions?\b", c):
            where = "transitions" if re.search(r"transition|cut", c) else _anchor(c) or ("drop" if (sounds or ["whoosh"])[0] in ("impact", "riser", "sub_drop", "hit") else "transitions")
            ops.append({"op": "sfx_add", "sound": (sounds or ["whoosh" if where == "transitions" else "impact"])[0], "anchor": where})
        elif up or down:
            f = (1 + 0.35 * amt) if up else 1 / (1 + 0.35 * amt)
            ops.append({"op": "audio", "who": "sfx", "sounds": sounds, "mul": {"volume": f}})
        else:
            return {"ops": [], "focus": {"kind": "sfx"}, "note": "sfx: what to do"}
        return done("sfx")

    # ---- texts
    text_moves = re.search(r"\b(?:come|comes|coming|appear|appears|pop|pops|show up|shows up|enter|enters|fly|flies|slide|slides) in with\b|"
                           r"\banimat|\bintro\b|\b(?:text|title|label|words?|caption)s?\b", c)
    if not text_ctx and not (set(subj) & {"music", "transition", "look", "sfx", "length", "pace", "canvas", "texture", "speed", "shot"}) \
            and not (set(subj) & {"flash", "shake", "zoom", "glitch", "effects"} and not text_moves) and match_existing(c, ctx.get("plan")) is not None \
            and re.search(r"\b(?:bigger|smaller|larger|small|big|large|tiny|huge|readable|visible|red|bold|font|colou?r|move|top|bottom|center|centre|remove|delete|say|says|read|change|"
                          r"come in|appear|animate|glitch|pop|higher|lower|yellow|white|gold|blue|green|pink|black|instead|replace|"
                          r"rename|swap|write|longer|shorter|stay|outline|shadow|caps)\b", c):
        text_ctx = {"text"}
    if text_ctx or (focus and focus.get("kind") == "text" and not subj and _elliptical(c, "text") and (COLOUR_RE.search(c) or up or down or is_remove or _text_value(raw)[0] or
                                                                             re.search(r"\b(?:bigger|smaller|bold|font|top|bottom|center|centre|higher|lower|outline|shadow|caps)\b", c))):
        r = _text(c, ctx, subj, amt, up, down, is_remove, is_add)
        if r is not None:
            return r

    # ---- transitions
    if ("transition" in subj and not ("transition" in keep_subj and set(subj) - {"transition"})) or (focus and focus.get("kind") == "transition" and not subj and _elliptical(c, "transition") and (up or down or is_remove or
                                                                                              any(p.search(c) for p, _, _ in FAMILIES.values()))):
        return _transitions(c, ctx, amt, up, down, is_remove, is_add)

    # ---- textures (grain, vignette, letterbox, light leaks)
    if "texture" in subj:
        whats = [w for w, pat in (("grain", r"grain|noise"), ("vignette", r"vignette"), ("letterbox", r"letter ?box|bars"),
                                  ("leak", r"leaks?|film burns?")) if re.search(pat, c)] or ["leak"]
        for what in whats:
            ops.append({"op": "texture", "what": what, **({"remove": True} if is_remove or down else {"add": True})})
        return done("texture", what=whats[0])

    # ---- look
    look = next(((q, n) for p, q, n in LOOKS if p.search(c)), None)
    cast = re.search(r"\btoo (orange|yellow|warm|red|blue|cold|cool|green|purple|pink|magenta|dark|bright|washed out|saturated|"
                     r"colou?rful|dull|grey|gray|flat|contrasty|moody|vintage|faded)\b", c)
    if cast and ("look" in subj or not subj):
        fix = {"orange": ("neutral natural clean cool", "less orange"), "yellow": ("neutral natural clean cool", "less yellow"),
               "warm": ("neutral natural cool", "cooler"), "red": ("neutral natural clean", "less red"), "blue": ("warm natural", "warmer"),
               "cold": ("warm natural", "warmer"), "cool": ("warm natural", "warmer"), "green": ("natural neutral warm", "less green"),
               "purple": ("natural neutral", "more natural"), "pink": ("natural neutral", "more natural"), "magenta": ("natural neutral", "more natural"),
               "dark": ("bright airy light clean", "brighter"), "bright": ("rich contrast deep", "richer"), "washed out": ("rich contrast vivid", "richer"),
               "saturated": ("muted natural soft", "more muted"), "colourful": ("muted natural soft", "more muted"), "colorful": ("muted natural soft", "more muted"),
               "dull": ("vibrant saturated vivid", "more vibrant"), "grey": ("vibrant warm", "more colourful"), "gray": ("vibrant warm", "more colourful"),
               "flat": ("high contrast punchy crisp", "more contrast"), "contrasty": ("low contrast soft", "softer"), "moody": ("bright natural clean", "lighter"),
               "vintage": ("clean modern natural", "cleaner"), "faded": ("rich contrast vivid", "richer")}[cast.group(1)]
        ops.append({"op": "look", "words": fix[0], "name": fix[1]})
        return done("look")
    if not subj and not look and (focus or {}).get("kind") == "look" and _elliptical(c, "look") and (up or down or re.search(r"\b(?:pop|richer|punchier|stronger)\b", c)):
        subj = ["look"]
    if "look" in subj or (look and not set(subj) & {"music", "transition", "effects", "flash", "glitch", "shot"}):
        if is_remove and not look:
            ops.append({"op": "look", "remove": True})
        elif look and not (is_remove and "look" in subj and not look):
            ops.append({"op": "look", "words": look[0], "name": look[1]})
        elif re.search(r"\b(?:too strong|too much|subtler|less|weaker|softer|lighter|toned? down)\b", c) or down:
            ops.append({"op": "look", "mul": {"strength": max(0.3, 1 - 0.35 * amt)}})
        elif up or re.search(r"\b(?:stronger|more|pop|richer|punchier)\b", c):
            ops.append({"op": "look", "mul": {"strength": 1 + 0.3 * amt}})
        elif re.search(r"\b(?:" + CHANGE + r")\b", c):
            ops.append({"op": "look", "words": "", "name": "a different look", "different": True})
        else:
            return {"ops": [], "focus": {"kind": "look"}, "note": "look: which way"}
        return done("look")

    # ---- shake / zoom / flash / glitch / effects
    kinds = [s for s in subj if s in ("shake", "zoom", "flash", "glitch", "effects")]
    if len(kinds) > 1 and "effects" in kinds:  # "no more glitch effects": the glitches, not every effect
        kinds.remove("effects")
    if not kinds and focus and focus.get("kind") in ("shake", "zoom", "flash", "glitch", "effects") and not subj and \
            (up or down or is_remove or re.search(r"\bonly (?:on|in|at|during|for) the\b", c)) and _elliptical(c, "fx"):
        kinds = [focus["kind"]]
    if kinds:
        return _fx(c, ctx, kinds, amt, up, down, is_remove, is_add, part)

    # ---- pacing
    if "pace" in subj or re.search(r"\b(?:faster|quicker|snappier|tighter|slower|calmer|more relaxed|let (?:it|the shots?|each \w+) breathe|"
                                   r"longer shots|shorter shots|quick cuts|fast cuts|fewer cuts|more cuts|less cuts)\b", c) and not set(subj) & {"music", "speed"}:
        faster = re.search(r"\b(?:faster|quicker|snappier|tighter|more cuts|quick cuts|fast cuts|shorter shots|too slow|drags?)\b", c)
        slower = re.search(r"\b(?:slower|calmer|relaxed|breathe|longer shots|fewer cuts|less cuts|too fast|too quick|too many cuts)\b", c)
        if faster and not re.search(r"\btoo fast|too quick\b", c):
            f = max(0.45, 1 - 0.25 * amt)
        elif slower or re.search(r"\btoo fast|too quick\b", c):
            f = 1 + 0.3 * amt
        else:
            return {"ops": [], "focus": {"kind": "pace"}, "note": "pace: which way"}
        op = {"op": "pace", "mul": f}
        if part and re.search(r"\b(?:intro|beginning|opening|middle|ending|outro|end|drop|climax|build|break)\b", c):
            op["sections"] = {"intro": ["intro"], "middle": ["verse", "build"], "outro": ["outro"], "build": ["build"], "break": ["break"],
                              "drop": ["drop"]}.get(part, [part])
        ops.append(op)
        return done("pace")

    # ---- a part of the edit ("the intro is too long", "the ending is too abrupt")
    if part in ("intro", "outro") and re.search(r"\b(?:too long|too slow|shorter|longer|too short|abrupt|sudden|cuts off|drags?|quicker|faster)\b", c):
        sec = "intro" if part == "intro" else "outro"
        if re.search(r"\babrupt|sudden|cuts off\b", c):
            ops += [{"op": "section_beats", "section": "outro", "mul": 1.5}, {"op": "audio", "who": "music", "set": {"fade_out": 3.0}},
                    {"op": "clips", "files": [], "last": True, "set": {"fade_out": 1.0}}]
        elif re.search(r"\b(?:too long|too slow|shorter|drags?|quicker|faster)\b", c):
            ops.append({"op": "section_beats", "section": sec, "mul": 0.6})
        else:
            ops.append({"op": "section_beats", "section": sec, "mul": 1.5})
        return done("structure", section=sec)

    # ---- an opinion about a text: no change yet, but "it" now means that text
    tx_m = re.search(r"\b(?:is|are|looks?|feels?|seems?) (?:so |really |a bit |kind of |kinda |too |pretty |super )?(boring|plain|bland|ugly|small|big|weird|"
                     r"off|bad|cheap|dull|hard to read|perfect|great|nice|good)\b", c)
    named_tx = match_existing(cq, ctx.get("plan")) if tx_m and not ops else None
    if named_tx is not None and re.search(r"\b(?:text|title|label|words?|caption|line|card)s?\b", cq) and not re.search(
            r"\b(?:make|change|bigger|smaller|move|remove|put|add)\b", cq):
        return {"ops": [], "focus": {"kind": "text", "who": {"match": str(named_tx.get("text") or "")}}, "note": "context"}

    # ---- an opinion about some footage: no change yet, but "those" now means that footage
    sh_m = re.search(r"^\s*(?:the |that |this )?(.+?) (?:is|looks|feels) (?:so |really |absolutely |kind of |kinda )?(stunning|gorgeous|beautiful|amazing|great|"
                     r"perfect|nice|good|my fav\w*|boring|bad|weak|ugly|too long|too short)\b", c)
    if sh_m and not ops and not set(subj) - {"shot", "speed"}:
        hits = match_shots(sh_m.group(1), ctx.get("design") or {}, ctx.get("analyses") or {})
        if len(hits) == 1 or (hits and re.search(r"\b(?:at|in) the (?:start|beginning|end|ending|drop)\b", sh_m.group(1))):
            anc = _anchor(sh_m.group(1))
            if anc in ("start", "end", "drop"):
                real = [s for s in (ctx.get("design") or {}).get("shots") or [] if isinstance(s, dict) and not s.get("fill")]
                pick = real[:1] if anc == "start" else real[-1:] if anc == "end" else [s for s in real if s.get("section") == "drop"][:1]
                hits = [h for h in hits if h in pick] or pick or hits
            if sh_m.group(2) in ("too long", "too short"):
                f = 0.6 if sh_m.group(2) == "too long" else 1.6
                return {"ops": [{"op": "shot_beats", "id": hits[0]["id"], "mul": f}], "focus": {"kind": "shot", "shots": [hits[0]["id"]]}, "note": ""}
            return {"ops": [], "focus": {"kind": "shot", "shots": [hits[0]["id"]], "files": [hits[0].get("file")]}, "note": "context"}
    op_m = re.search(r"\b(?:the |these |those |all the )?([a-z' ]{2,40}?) (?:shots? |clips? |footage |parts? |scenes? |bits? |screens? )?(?:is|are|was|were|look|looks|feel|feels|seem|seems) "
                     r"(?:so |really |the |kind of |kinda |a bit |pretty |super |too )?(best|great|amazing|awesome|good|nice|fire|sick|perfect|beautiful|gorgeous|"
                     r"stunning|epic|my fav\w*|bad|boring|ugly|weak|meh|terrible|awful|worst|blurry|shaky|too dark|dark|off|cringe|cheap|amateur\w*|fake|"
                     r"dull|low quality|bland)\b", c)
    if op_m and not ops:
        fs = [f for f, sc in match_files(op_m.group(1), ctx.get("analyses") or {})]
        if fs:
            good = op_m.group(2) in ("best", "great", "amazing", "awesome", "good", "nice", "fire", "sick", "perfect", "beautiful", "gorgeous") \
                or op_m.group(2).startswith("my fav")
            top = match_files(op_m.group(1), ctx.get("analyses") or {})
            fs = [f for f, sc in top if sc >= 0.75 * top[0][1]]
            return {"ops": [], "focus": {"kind": "shot", "files": fs, "liked": good}, "note": "context"}
    fsf = (focus or {}).get("files") if (focus or {}).get("kind") == "shot" else None
    if fsf and re.search(r"\b(?:more of|more shots of|use more|show more)\s+(?:those|them|these|that|it|the same)\b", c):
        return {"ops": [{"op": "more_of", "file": f, "n": 2} for f in fsf[:3]], "focus": focus, "note": ""}
    if fsf and re.search(r"\b(?:less of|fewer of|use less|fewer)\s+(?:those|them|these|that|it)\b|\b(?:less|fewer) of (?:those|them|these)\b", c):
        return {"ops": [{"op": "less_of", "file": f} for f in fsf[:3]], "focus": focus, "note": ""}
    if fsf and re.search(r"\b(?:remove|drop|cut|lose|get rid of|no more of|ditch|delete)\s+(?:those|them|these|that|it|all of them)\b", c):
        return {"ops": [{"op": "avoid_file", "file": f} for f in fsf[:3]], "focus": focus, "note": ""}

    # ---- shots: order, removal, more of
    r = _shots(c, ctx, is_remove, is_add)
    if r is not None:
        return r

    # ---- add a catalogue effect by its look ("add lightning on his eyes at the drop", "put some snow at the end")
    if is_add:
        r = _effect_add(c, ctx)
        if r is not None:
            return r

    # ---- repeat / soften the last change
    last = ctx.get("last_ops") or []
    if last and re.fullmatch(r"\s*(?:(?:even|a bit|a little|slightly|much|way)\s+)?(?:more|again|more please|do it again|same again|another one|bigger|louder|stronger|faster)\s*(?:please)?\s*", c):
        return {"ops": [_scaled(o, 1.0) for o in last if _scaled(o, 1.0)], "focus": focus, "note": ""}
    if last and re.fullmatch(r"\s*(?:not (?:that|so) much|(?:a bit |slightly )?less|too much(?: now)?|tone it back|back off a bit|a little less|smaller|quieter|weaker|slower)\s*(?:please)?\s*", c):
        out = [_scaled(o, -0.5) for o in last if _scaled(o, -0.5)]
        if out:
            return {"ops": out, "focus": focus, "note": ""}
    return {"ops": [], "focus": None, "note": "not understood"}


ELLIPSIS_OK = {
    "any": set("""it them that those this these they its more less much way even bit little lot again too so very really make
                 please pls also now just a an the some bigger smaller larger louder quieter softer stronger weaker faster slower longer
                 shorter higher lower brighter darker remove delete get rid of off no without up down increase decrease raise reduce
                 tone dial back keep go and but maybe actually still yet only on in at during for to with into as should
                 be is are was use try one ones then ok okay instead switch can could would you we i me my many few fewer lot lots
                 between every each all section sections cut cuts""".split()),
    "text": set("""top bottom center centre middle upper lower left right bold caps uppercase lowercase outline shadow box background
                  font say says read change rename word words move put place position letters size neon bright light dark pastel hot deep
                  electric sit sits higher lower further""".split()) | {w for c_ in COLOURS for w in c_.split()},
    "music": set("""music volume song beat track bpm tempo fade start end""".split()) | {w for p in GENRES.values() for w in re.findall(r"[a-z]+", p)},
    "transition": set("""transition transitions duration""".split()) | {w for f in FAMILIES for w in re.findall(r"[a-z]+", FAMILIES[f][1])} | set(FAMILIES),
    "look": set("""look colour color colours colors grade filter pop richer punchier warm warmer cool cooler vibrant saturated
                  contrast""".split()),
    "fx": set("""strength intense intensity often frequent many drop intro outro beginning end ending middle build break climax""".split())}


def _elliptical(c, kind):
    """A clause that only makes sense as a continuation ("even more", "remove them", "and red", "change it to 'X'") rather
    than a new ask. Words in quotes are the new words of a text and do not count."""
    allowed = ELLIPSIS_OK["any"] | ELLIPSIS_OK.get(kind, set())
    c = re.sub(r'"[^"]*"|(?<![a-z])\'[^\']+\'(?![a-z])', " ", c, flags=re.I)
    return all(w in allowed or w.isdigit() for w in re.findall(r"[a-z]+|\d+", c.lower()))


def _scaled(op, k):
    """The last change again (k=1) or half of it back (k=-0.5); only for changes by a factor."""
    o = copy.deepcopy(op)
    if "mul" in o and isinstance(o["mul"], dict):
        o["mul"] = {f: (v ** k if v > 0 else v) for f, v in o["mul"].items()}
        return o
    if o.get("op") == "pace":
        o["mul"] = o["mul"] ** k
        return o
    if o.get("op") == "length" and o.get("mul"):
        o["mul"] = o["mul"] ** k
        return o
    if o.get("op") == "music" and o.get("bpm_mul"):
        o["bpm_mul"] = o["bpm_mul"] ** k
        return o
    return None


MORE_ENERGY = {"chill": "pop", "cinematic": "pop", "pop": "hype", "epic": "hype", "hype": "phonk", "phonk": "hype"}
LESS_ENERGY = {"phonk": "hype", "hype": "pop", "epic": "cinematic", "pop": "chill", "cinematic": "chill", "chill": "cinematic"}


def _music(c, ctx, amt, up, down, is_remove, ops):
    mood = re.search(r"\btoo (sleepy|slow|calm|boring|soft|chill|dull|sad|mellow|quiet|relaxed|lifeless|flat|aggressive|intense|hard|harsh|busy|"
                     r"energetic|hyper|fast|chaotic|cheesy|happy)\b|\b(?:needs?|want|could use) (?:more|some) (energy|life|punch|drive|calm)\b", c)
    if mood:
        cur = next((str(e.get("file", "")).split("_")[1] for e in (ctx.get("plan") or {}).get("edits") or []
                    if e.get("id") == "music" and str(e.get("file", "")).startswith("music_")), "pop")
        w = mood.group(1) or mood.group(2)
        calmer = w in ("aggressive", "intense", "hard", "harsh", "busy", "energetic", "hyper", "fast", "chaotic", "calm")
        g = (LESS_ENERGY if calmer else MORE_ENERGY).get(cur, "pop")
        if w == "quiet":
            ops.append({"op": "audio", "who": "music", "mul": {"volume": 1.35}})
        elif w in ("cheesy", "happy"):
            ops.append({"op": "music", "generate": "cinematic" if cur != "cinematic" else "chill"})
        else:
            ops.append({"op": "music", "generate": g})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    gen = next((g for g, p in GENRE_RE.items() if p.search(c)), None)
    if re.search(r"\b(?:bass|bassier|808s?|heavier|heavy|sub)\b", c) and not gen:
        cur = next((str(e.get("file", "")).split("_")[1] for e in (ctx.get("plan") or {}).get("edits") or []
                    if e.get("id") == "music" and str(e.get("file", "")).startswith("music_")), None)
        if cur != "phonk":
            ops.append({"op": "music", "generate": "phonk"})
            return {"ops": ops, "focus": {"kind": "music"}, "note": "no EQ here: a bed with heavier bass instead"}
        up, amt = True, 1.0
    if gen == "hype" and re.search(r"\b(?:louder|volume)\b", c) and not re.search(r"\b(?:music|song) (?:to|style|genre)|\bmore (?:hype|energetic|upbeat)\b", c):
        gen = None
    if re.search(r"\b(?:mute|no music|without (?:the )?music|remove (?:the )?(?:music|song|track)|turn off (?:the )?music|kill the music|get rid of the music|silent)\b", c):
        ops.append({"op": "audio", "who": "music", "remove": True})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    quieter = re.search(r"\b(?:quieter|softer|lower|down|less loud|too loud|gentler)\b", c)
    if quieter and re.search(r"\b(?:at|in) the (?:start|beginning|intro|opening)\b|\bat first\b", c):
        ops.append({"op": "audio", "who": "music", "set": {"fade_in": 2.5}})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    if quieter and re.search(r"\b(?:at|in) the (?:end|ending|outro)\b", c):
        ops.append({"op": "audio", "who": "music", "set": {"fade_out": 4.0}})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    if re.search(r"\bfade(?:s|d)? ?(?:it )?out\b|\bends? (?:abruptly|suddenly)|cuts? off\b|\bfade at the end\b", c):
        ops.append({"op": "audio", "who": "music", "set": {"fade_out": 3.0}})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    if re.search(r"\bfade(?:s|d)? ?(?:it )?in\b|\bstarts? too (?:loud|suddenly|abruptly)\b", c):
        ops.append({"op": "audio", "who": "music", "set": {"fade_in": 1.5}})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    m = re.search(r"\b([\w\-]+\.(?:mp3|wav|m4a|aac|flac|ogg))\b", c)
    if m:
        ops.append({"op": "music", "file": m.group(1)})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    tempo = re.search(r"\b(?:faster|quicker|slower|more upbeat|higher bpm|lower bpm|speed up the (?:music|song|beat)|slow down the (?:music|song|beat))\b", c) \
        and re.search(r"\b(?:music|song|beat|track|tempo|bpm)\b", c)
    if tempo:
        f = (1 + 0.12 * amt) if re.search(r"\b(?:faster|quicker|upbeat|higher|speed up)\b", c) else 1 - 0.12 * amt
        ops.append({"op": "music", "bpm_mul": f})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    if gen:
        ops.append({"op": "music", "generate": gen})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    if re.search(r"\b(?:different|another|other|new|change|swap|replace)\b", c) and not (up or down):
        ops.append({"op": "music", "generate": "_next"})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    if re.search(r"\bcan'?t hear\b|\bbarely hear\b|\btoo quiet\b", c):
        up, down, amt = True, False, 1.8
    if up or down or re.search(r"\b(?:louder|quieter|volume)\b", c):
        louder = up or re.search(r"\blouder\b", c)
        if re.search(r"\b(?:quieter|lower|softer|down|less loud|too loud|reduce|decrease)\b", c):
            louder = False
        f = (1 + 0.35 * amt) if louder else 1 / (1 + 0.35 * amt)
        ops.append({"op": "audio", "who": "music", "mul": {"volume": f}})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    if is_remove:
        ops.append({"op": "audio", "who": "music", "remove": True})
        return {"ops": ops, "focus": {"kind": "music"}, "note": ""}
    return None


def _text_exists(plan, words):
    w = " ".join(str(words or "").lower().split())
    return bool(w) and any(" ".join(str(e.get("text") or "").lower().split()) == w for e in (plan or {}).get("edits") or [] if e.get("type") == "text")


def _text(c, ctx, subj, amt, up, down, is_remove, is_add):
    focus = ctx.get("focus") or {}
    who = _who_text(c, subj, focus if not set(subj) & {"title", "label", "text", "cta", "caption"} else None, ctx.get("plan"))
    ops = []
    raw = ctx.get("raw") or c
    new, old = _text_value(raw)
    qs = [a or b for a, b in re.findall(r'"([^"]+)"|(?<![A-Za-z])\'([^\']+)\'(?![A-Za-z])', raw)]
    writing = re.search(r"\b(?:change|rename|replace|retitle|say|says|saying|read|reads|should|spell|spelled|typo|instead|call(?:ed)? it|"
                        r"swap|switch|to say|text to|words to|wrong)\b", c)
    if len(qs) == 1 and new == qs[0] and old is None and (not writing or _text_exists(ctx.get("plan"), new)) and not (is_add and not _text_exists(ctx.get("plan"), new)):
        who, new = {"match": new}, None  # "make 'THE BAY' bigger": the quote names a text that is there
    adding = is_add and (new or re.search(r"\b(?:saying|that says|with the words|text|title|caption|label)\b", c)) and not re.search(r"\b(?:add|put) (?:an? )?(?:outline|shadow|stroke|border|box|background|animation)\b", c)
    if who.get("role") == "caption" and is_add and not new:
        return {"ops": [{"op": "captions", "add": True}], "focus": {"kind": "text", "who": who}, "note": ""}
    if adding and new and not old and not (re.search(r"\b(?:change|rename|replace|instead)\b", c)):
        anchor = _anchor(c) or ("end" if CTA_WORDS.search(new) else "start")
        role = "cta" if CTA_WORDS.search(new) else who.get("role") if who.get("role") in ("label", "title", "cta") else "title"
        ops.append({"op": "text_add", "text": new, "anchor": anchor, "role": role,
                    "position": next((v for p, v in POSITIONS if re.search(p, c)), None),
                    "color": COLOURS.get(COLOUR_RE.search(c).group(1)) if COLOUR_RE.search(c) else None})
        return {"ops": ops, "focus": {"kind": "text", "who": {"match": new}}, "note": ""}
    if is_remove and not re.search(r"\b(?:outline|shadow|stroke|border|box|background|animation|bold|caps)\b", c):
        ops.append({"op": "text", "who": who, "remove": True})
        return {"ops": ops, "focus": {"kind": "text", "who": who}, "note": ""}
    st, mul = {}, {}
    if new and not re.search(r"\bfont\b", c):
        if old:
            who = {"match": old}
        st["text"] = new
    col = COLOUR_RE.search(c) or HEX_RE.search(c)
    if col and not re.search(r"\b(?:outline|stroke|border|shadow|box|background)\b[^.]*" + re.escape(col.group(0)), c):
        st["color"] = COLOURS.get(col.group(0), col.group(0).upper())
    elif col:
        hexv = COLOURS.get(col.group(0), col.group(0).upper())
        if re.search(r"\b(?:outline|stroke|border)\b", c):
            st["outline"] = {"color": hexv, "width": 60}
        else:
            st["background"] = {"color": hexv, "alpha": 0.6}
    if re.search(r"\bfont\b|\btypeface\b", c) or FONT_STYLE_RE.search(c) and re.search(r"\b(?:font|type|letters|lettering|text|title|labels?)\b", c) and not re.search(r"\bbold(?:er)?\b", c):
        style = FONT_STYLE_RE.search(c)
        same = re.search(r"\bsame (?:font|one) as (?:the )?(\w+)", c)
        if same:
            src = {"labels": "label", "label": "label", "title": "title", "titles": "title", "captions": "caption"}.get(same.group(1), "title")
            st["font_from"] = src
            if who.get("role") == src:  # "the same font as the labels for the title": the title changes, the labels are the model
                who["role"] = next((r for r in ("cta", "caption", "label", "title") if r in subj and r != src), "title" if src != "title" else "label")
        elif style or re.search(r"\b(?:different|another|other|new|change)\b", c):
            st["font_style"] = FONT_QUERY.get(style.group(1).replace(" ", ""), style.group(1)) if style else ""
    if re.search(r"\b(?:bold(?:er)?|thicker)\b", c) and not re.search(r"\bfont\b", c):
        st["bold"] = not re.search(r"\b(?:not bold|unbold|no bold|less bold)\b", c)
    if re.search(r"\b(?:all caps|uppercase|upper case|capital letters|capitals)\b", c):
        st["case"] = "upper"
    elif re.search(r"\b(?:lowercase|lower case|small letters)\b", c):
        st["case"] = "lower"
    if re.search(r"\b(?:outline|stroke|border)\b", c):
        st.setdefault("outline", {"color": "#000000", "width": 0 if is_remove else 60})
    if re.search(r"\bshadow\b", c):
        st["shadow"] = not is_remove
    if re.search(r"\b(?:box|background|backdrop|banner|highlight) (?:behind|under|for)|\b(?:with a|in a) (?:box|banner)\b|\bbackground box\b", c):
        st.setdefault("background", {"color": "#000000", "alpha": 0.0 if is_remove else 0.6})
    if re.search(r"\b(?:hard to read|can'?t read|cannot read|not readable|unreadable|illegible|more legible|readable|easier to read|hard to see|"
                 r"can'?t see|cannot see|difficult to see|not visible|barely visible|invisible|get lost|gets lost|blends? in|hard to notice)\b", c):
        mul["size"] = 1.15
        st.setdefault("outline", {"color": "#000000", "width": 70})
        st["shadow"] = True
    pos = next((v for p, v in POSITIONS if re.search(p, c)), None)
    if pos and re.search(r"\b(?:move|put|place|position|shift|bring|at the|to the|on the|in the|up|down)\b", c):
        st["position"] = pos
    elif re.search(r"\b(?:higher|move (?:it |them )?up|raise|further up|a bit up|up a bit|up a little)\b", c) and not re.search(r"\bsize|bigger\b", c):
        st["position"] = "_up_bit" if re.search(r"\b(?:" + ABIT + r")\b", c) else "_up"
    elif re.search(r"\b(?:move (?:it |them )?down|put (?:it |them )?lower|lower down|further down|down a bit|down a little|(?:sit|sits|be|go|placed?)(?: a)?(?: bit| little)? lower)\b", c):
        st["position"] = "_down_bit" if re.search(r"\b(?:" + ABIT + r")\b", c) else "_down"
    if re.search(r"\b(?:stay|stays|on screen|visible|disappears?|vanish(?:es)?|show(?:s)? (?:for )?longer|too fast|too quick|longer)\b", c) and \
            re.search(r"\b(?:longer|too fast|too quick|disappears?|vanish|short|stay)\b", c) and "size" not in mul:
        mul["duration"] = 1 + 0.5 * amt if not re.search(r"\b(?:shorter|too long)\b", c) else 1 / (1 + 0.5 * amt)
    came = re.search(r"\b(?:come|comes|coming|appear|appears|pop|pops|show up|shows up|enter|enters) in with (?:a |an |some )?(\w+)", c)
    if came:
        st["intro_words"] = f"{came.group(1)} in"
    elif re.search(r"\bone (?:word|letter) at a time\b|\bword by word\b|\bletter by letter\b|\btyping\b", c):
        st["intro_words"] = "typewriter"
    elif re.search(r"\b(?:animate|animation|pop(?:s)? in|typewriter|types? in|fade(?:s)? in|bounce|slide(?:s)? in|slam|glitch in|zoom(?:s)? in)\b", c):
        st["intro_words"] = re.search(r"\b(pop(?:s)? in|typewriter|types? in|fade(?:s)? in|bounce|slide(?:s)? in|slam|glitch in|zoom(?:s)? in|animate|animation)\b", c).group(1)
    if "intro_words" in st and (is_remove or re.search(r"\bno animation\b", c)):
        st["intro_words"] = ""
    if re.search(r"\b(?:slowly|slow|gently|gradually|softly)\b", c) and ("intro_words" in st or re.search(r"\b(?:fade|appear|come|animat)", c)):
        st["intro_duration"] = 1.2
    elif re.search(r"\b(?:quickly|quick|fast|snappy|snappier)\b", c) and ("intro_words" in st or re.search(r"\b(?:fade|appear|come|animat|pop)", c)):
        st["intro_duration"] = 0.3
    when = re.search(r"\b(?:appear|appears|come in|comes in|show up|shows up|start|starts|pop up|pops up|show|shows|be on screen|come)\b.*?\b(later|earlier|sooner)\b|"
                     r"\b(?:appear|appears|come in|comes in|show up|shows up|start|starts|pop up|pops up)\b.*?\b(?:at|around|after|from)\s+\d", c)
    if when:
        t = _time_point(c) if re.search(r"\b(?:at|around|after|from)\s+\d", c) else None
        if t is not None:
            st["start"] = float(t)
        else:
            st["shift"] = 1.5 if when.group(1) == "later" else -1.5
    sizing = re.search(r"\b(?:bigger|larger|huge|giant|smaller|tiny|size|too small|too big|too large|shorter|scale|increase|decrease|"
                       r"enlarge|shrink)\b", c)
    if sizing and "size" not in mul:
        bigger = re.search(r"\b(?:bigger|larger|huge|giant|too small|increase|enlarge)\b", c) or (up and not down)
        if re.search(r"\b(?:smaller|tiny|too big|too large|shorter|reduce|decrease|shrink)\b", c):
            bigger = False
        mul["size"] = (1 + 0.25 * amt) if bigger else 1 / (1 + 0.25 * amt)
    elif not st and not mul and (up or down) and re.search(r"\b(?:it|text|title|label|them|they)\b", c):
        mul["size"] = (1 + 0.25 * amt) if up else 1 / (1 + 0.25 * amt)
    if re.search(r"\bpop\b", c) and not st and not mul:  # "make the title pop": bigger, outlined, with a pop-in
        mul["size"] = 1.15
        st.update(outline={"color": "#000000", "width": 70}, shadow=True, intro_words="pop in")
    if not st and not mul:
        return None
    ops.append({"op": "text", "who": who, **({"set": st} if st else {}), **({"mul": mul} if mul else {})})
    return {"ops": ops, "focus": {"kind": "text", "who": who}, "note": ""}


def current_family(plan):
    """The family (dissolve, blur, glitch...) of the transitions the edit uses now, or None."""
    core = {"dissolve": r"dissolve|cross ?fade|\bfade", "blur": r"blur", "zoom": r"zoom|push in", "whip": r"whip|swipe|swish",
            "spin": r"spin|rotat", "glitch": r"glitch|rgb|digital|pixel", "flash": r"flash|white|glow|bright|flare", "slide": r"slide|wipe",
            "leak": r"leak|burn"}
    for e in (plan or {}).get("edits") or []:
        if e.get("type") == "transition":
            key = item_key(e)
            n = _cat().index.notes.get(key) or {}
            for text in (f"{key} {n.get('en', '')}".lower(), item_words(key)):
                fam = next((f for f, pat in core.items() if re.search(pat, text)), None)
                if fam:
                    return fam
            return None
    return None


def _transitions(c, ctx, amt, up, down, is_remove, is_add):
    c2 = re.sub(r"\btransitions?\b|\btoo long\b|\btoo short\b", "", c)
    found = sorted((m.start(), f) for f, (p, _, _) in FAMILIES.items() for m in [p.search(c2)] if m)
    fam = found[0][1] if found else None
    if len(found) > 1:
        inst = re.search(r"\binstead of\b", c2)
        if inst:  # "whip pans instead of blur": not the one after "instead of"
            fam = next((f for pos, f in found if pos < inst.start()), found[0][1])
        else:  # "replace the blur ones with whip pans", "change blur to dissolve": the last one named
            fam = found[-1][1]
    cur = current_family(ctx.get("plan"))
    ops = []
    longer = re.search(r"\b(?:longer|slower|too short|too quick|too fast|more time)\b", c)
    shorter = re.search(r"\b(?:shorter|quicker|faster|snappier|too long|too slow|drags?)\b", c)
    if is_remove or re.search(r"\b(?:hard cuts?|just cuts|straight cuts|only cuts|jump cuts)\b", c):
        ops.append({"op": "transitions", "remove": True})
    elif re.search(r"\b(?:more transitions|every (?:cut|clip|shot)|between (?:all|every|each))\b", c) or (is_add and not fam):
        ops.append({"op": "transitions", "every": True, **({"family": fam} if fam else {})})
    elif re.search(r"\bonly (?:between|at|on|for) (?:the )?(?:sections?|parts?|section changes|changes|big moments)\b", c):
        ops.append({"op": "transitions", "sections_only": True})
    elif re.search(r"\b(?:fewer|less) transitions\b|\btoo many\b|\btoo much\b|\btoo busy\b|\boverdone\b|\bless often\b", c):
        ops.append({"op": "transitions", "thin": 2})
    else:
        if fam and fam != cur:
            ops.append({"op": "transitions", "family": fam})
        if longer or shorter:
            ops.append({"op": "transitions", "mul": {"duration": (1 + 0.5 * amt) if longer and not shorter else 1 / (1 + 0.5 * amt)}})
        if not ops and fam and fam == cur:
            return {"ops": [], "focus": {"kind": "transition"}, "note": f"they already are {fam} transitions",
                    "ask": f"They already are {fam} transitions. Longer, shorter, or a different style?"}
        if not ops and re.search(r"\b(?:" + CHANGE + r")\b", c):
            ops.append({"op": "transitions", "family": "_different"})
    if not ops:
        return {"ops": [], "focus": {"kind": "transition"}, "note": "transitions: what to do"}
    t = _time_point(c)
    if t is not None:
        ops[-1]["at"] = t
    return {"ops": ops, "focus": {"kind": "transition"}, "note": ""}


def _fx(c, ctx, kinds, amt, up, down, is_remove, is_add, part):
    ops = []
    scope = {}
    t = _time_point(c)
    if t is not None:
        scope["at"] = t
    if part and re.search(r"\b(?:in|during|from|on|at) the (?:intro|beginning|opening|start|middle|end|ending|outro|drop|build|break)|\b(?:intro|ending|outro) only\b|\bonly in the\b", c):
        scope["section"] = part
    keep_kinds = [{"effects": "effect"}.get(k, k) for k in ctx.get("keep_subj") or [] if k in ("zoom", "shake", "flash", "glitch", "transition", "texture")]
    kinds = [k for k in kinds if k not in (ctx.get("keep_subj") or [])] or kinds
    focus = ctx.get("focus") or {}
    if is_remove and focus.get("item") and re.search(r"\b(?:it|that|those|them|this|these|the new one|what you (?:just )?added)\b", c) \
            and (kinds == [focus.get("kind")] or kinds == ["effects"]):
        return {"ops": [{"op": "fx", "kind": "effect", "remove": True, "item": focus["item"]}], "focus": {"kind": "effects"}, "note": ""}
    only = re.search(r"\bonly (?:on|in|at|during|for) the (drop|intro|beginning|middle|end|ending|outro|build|break|climax)\b", c)
    if only:
        sec = {"beginning": "intro", "ending": "outro", "end": "outro", "climax": "drop"}.get(only.group(1), only.group(1))
        return {"ops": [{"op": "fx", "kind": {"effects": "effect"}.get(k, k), "remove": True, "except_section": sec} for k in kinds],
                "focus": {"kind": kinds[0]}, "note": ""}
    if is_add and "zoom" in kinds and re.search(r"\b(?:slow|gentle|gradual|subtle|smooth) (?:zoom|push)|\bpush(?:-| )?in\b|\bken burns\b|\bzoom in slowly\b", c):
        target = _shot_target(c, ctx)
        if not target:
            return {"ops": [], "focus": {"kind": "zoom"}, "note": "which shot", "ask": "Which shot should slowly push in?", "template": "add a slow zoom on {}"}
        return {"ops": [{"op": "push_add", "shot": s["id"], "amount": 1.12} for s in target[:2]], "focus": {"kind": "zoom"}, "note": ""}
    for kind in kinds:
        k = {"effects": "effect"}.get(kind, kind)
        if is_remove or re.search(r"\bstop\b", c):
            op = {"op": "fx", "kind": k, "remove": True, **scope}
            if k == "effect":
                op["kinds"] = ["effect", "shake", "zoom"] if re.search(r"\ball\b|\bevery\b|\bany\b", c) or not scope else ["effect"]
                op["keep"] = keep_kinds
            ops.append(op)
        elif re.search(r"\b(?:fewer|less (?:often|frequent)|not (?:so|as) (?:often|many)|too many|only on the (?:drop|downbeats?))\b", c):
            ops.append({"op": "fx", "kind": k, "thin": 2, **scope})
        elif (down or re.search(r"\b(?:subtler|subtle|gentler|softer|weaker|toned? down|less)\b", c)) and not up:
            ops.append({"op": "fx", "kind": k, "mul": {"strength": 1 / (1 + 0.4 * amt)}, **scope})
        elif up or is_add or re.search(r"\b(?:more|stronger|harder|every beat|on (?:the|every) beat)\b", c):
            many = re.search(r"\b(?:more|every beat|on (?:the|every) beat|each beat|more often|beats|downbeats|all|lots|several|some)\b", c) or \
                (is_add and re.search(r"\b(?:flashes|glitches|zooms|shakes|punches)\b", c))
            anchor = _anchor(c)
            if is_add and not many and k in ("flash", "glitch", "zoom", "shake"):  # "a flash at the drop": one, where asked
                anc = anchor if anchor is not None else (_shot_anchor(c, ctx) or "drop")
                if k in ("zoom", "shake"):
                    ops.append({"op": "move_add", "kind": k, "anchor": anc, "strength": 1.25 if k == "zoom" else 0.6})
                else:
                    key = _effect_key("white flash" if k == "flash" else "glitch rgb chromatic", "flash" if k == "flash" else "glitch")
                    if key:
                        ops.append({"op": "fx_add", "item": key, "anchor": anc, "target": None, "label": _cat().index.notes.get(key, {}).get("en") or k,
                                    "duration": 0.4})
            elif many and k in ("flash", "glitch", "zoom", "shake"):
                use = {"flash": "flash", "glitch": "rgb_hit", "zoom": "zoom_punch", "shake": "shake"}[k]
                on = "beats" if re.search(r"\bevery beat|each beat|on the beat\b", c) else "downbeats"
                secs = {"intro": ["intro"], "outro": ["outro"], "drop": ["drop"], "middle": ["verse", "build"], "build": ["build"]}.get(scope.get("section"), ["build", "drop"])
                ops.append({"op": "recipe", "use": use, "on": on, "sections": secs, **({"strength": 1.2} if k == "zoom" else {"strength": 0.5} if k == "shake" else {})})
            elif k == "effect" and is_add:
                r = _effect_add(c, ctx)
                if r is not None:
                    return r
                return {"ops": [], "focus": {"kind": "effects"}, "note": "which effect", "ask": "Which effect would you like (e.g. 'sparkles', 'light leak', 'lightning'), and where?"}
            else:
                ops.append({"op": "fx", "kind": k, "mul": {"strength": 1 + 0.4 * amt}, **scope})
        elif re.search(r"\b(?:" + CHANGE + r")\b", c) and k == "effect":
            ops.append({"op": "fx", "kind": k, "swap": True, **scope})
        else:
            continue
    if not ops:
        return {"ops": [], "focus": {"kind": kinds[0]}, "note": f"{kinds[0]}: what to do"}
    return {"ops": ops, "focus": {"kind": kinds[0]}, "note": ""}


ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4,
            "sixth": 5, "6th": 5, "last": -1, "final": -1, "opening": 0}


def _shot_target(c, ctx):
    """Design shots a clause points at: "the drop", "the last shot", "the second shot", "when he jumps", "the kiss"."""
    design, an = ctx.get("design") or {}, ctx.get("analyses") or {}
    shots = [s for s in design.get("shots") or [] if isinstance(s, dict)]
    if not shots:
        return []
    m = re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|sixth|6th|last|final|opening) (?:shot|clip|scene)\b", c)
    if m:
        real = [s for s in shots if not s.get("fill")]
        i = ORDINALS[m.group(1)]
        return [real[i]] if real and -len(real) <= i < len(real) else []
    m = re.search(r"\b(?:shot|clip|scene) (\d+)\b", c)
    if m:
        real = [s for s in shots if not s.get("fill")]
        i = int(m.group(1)) - 1
        return [real[i]] if 0 <= i < len(real) else []
    words = re.sub(r"\b(?:add|put|use|make|give|slow ?mo(?:tion)?|slow-mo|slow|down|speed ramps?|velocity|freeze(?: frame)?|reverse|on|at|to|the|when|where|"
                   r"during|in|of|with|for|it|a|an|some|please|shot|clip|scene|part|moment|frame|zoom|zooms|push(?:-| )?in|ken burns|gentle|"
                   r"gradual|subtle|smooth|end|ending|start|beginning|intro|outro|opening|drop|climax|final|last|first|more|less|bit|little)\b", " ", c)
    hits = match_shots(words, design, an) if content_words(words) else []
    anc = _anchor(c)
    if hits:
        sec = {"drop": "drop", "end": "outro", "start": "intro"}.get(anc) if isinstance(anc, str) else None
        return ([s for s in hits if s.get("section") == sec] or hits) if sec else hits
    if anc == "drop":
        d = next((s for s in shots if s.get("section") == "drop" and not s.get("fill")), None)
        return [d] if d else []
    if anc == "end":
        real = [s for s in shots if not s.get("fill")]
        return real[-1:]
    if anc == "start":
        real = [s for s in shots if not s.get("fill")]
        return real[:1]
    if re.search(r"\bbest (?:moment|part|shot)|hero (?:shot|moment)|key moment\b", c):
        d = next((s for s in shots if s.get("section") == "drop" and not s.get("fill")), None)
        return [d] if d else []
    return []


def _shots(c, ctx, is_remove, is_add):
    design, an = ctx.get("design") or {}, ctx.get("analyses") or {}
    shots = [s for s in design.get("shots") or [] if isinstance(s, dict)]
    if not shots and design.get("template"):  # a template edit: its slots are the shots
        shots = [{"id": cl["id"], "file": cl.get("file"), "want": "", "section": "verse"} for cl in (ctx.get("plan") or {}).get("clips") or []]
        design = {**design, "shots": shots}
    if not shots:
        return None
    ops = []
    m = re.search(r"\bswap (?:the )?(?:shots? |clips? )?(\d+) and (\d+)\b", c)
    if m or re.search(r"\bswap the first two\b", c):
        real = [s for s in shots if not s.get("fill")]
        a, b = (int(m.group(1)) - 1, int(m.group(2)) - 1) if m else (0, 1)
        if 0 <= a < len(real) and 0 <= b < len(real):
            ops.append({"op": "swap_shots", "a": real[a]["id"], "b": real[b]["id"]})
            return {"ops": ops, "focus": {"kind": "shot"}, "note": ""}
    m = re.search(r"\b(?:start|open|begin|kick off)(?:s|ing)? (?:it )?(?:with|on) (?:the |a |an )?(.+)$|\b(?:use|put|make) (?:the |a )?(.+?) (?:as the|as an?|for the) (?:very )?(?:intro|opener|opening|first|start)(?: (?:shot|image|frame|clip|scene|picture|moment|one))?\b|\b(.+?) (?:should be )?first\b", c)
    if m and not re.search(r"\b(?:title|text|label|caption|music|song|transition|effect|filter|flash|zoom|shake)\b", m.group(0)) and not _quoted(c):
        words = next(g for g in m.groups() if g)
        hit = match_shots(words, design, an) or _file_shots(words, ctx)
        if hit:
            ops.append({"op": "shot_move", "id": hit[0]["id"], "to": "first", "file": hit[0].get("file")})
            return {"ops": ops, "focus": {"kind": "shot"}, "note": ""}
    m = re.search(r"\b(?:end|finish|close|wrap up)(?:s|ing)? (?:it )?(?:with|on) (?:the |a |an )?(.+)$|\b(?:use|put|make) (?:the |a )?(.+?) (?:as the|for the|at the) (?:very )?(?:end|ending|outro|last|final|closing)(?: (?:shot|image|frame|clip|scene|picture|moment|one))?\b|\b(.+?) (?:should be |should come |goes )?(?:the )?(?:very )?(?:last(?: thing| shot| one)?|at the end)\s*$", c)
    if m and not re.search(r"\b(?:title|text|label|caption|card|words?|music|song|transition|effect|filter|flash|zoom|shake|freeze|slow|small|big|"
                           r"bigger|smaller|large|tiny|loud|quiet|bright|dark)\b", m.group(0)) and not _quoted(c):
        words = next(g for g in m.groups() if g)
        hit = match_shots(words, design, an) or _file_shots(words, ctx)
        if hit:
            ops.append({"op": "shot_move", "id": hit[0]["id"], "to": "last", "file": hit[0].get("file")})
            return {"ops": ops, "focus": {"kind": "shot"}, "note": ""}
    m = re.search(r"\b(?:put|use|make|have) (?:the |a )?(.+?) (?:on|at|as|for) the (?:drop|climax|peak)\b|\bthe (?:drop|climax|peak) should (?:be|show) (?:the )?(.+)$", c)
    if m:
        words = next(g for g in m.groups() if g)
        hit = match_shots(words, design, an) or _file_shots(words, ctx)
        if hit:
            ops.append({"op": "shot_move", "id": hit[0]["id"], "to": "drop", "file": hit[0].get("file")})
            return {"ops": ops, "focus": {"kind": "shot"}, "note": ""}
    if is_remove or re.search(r"\b(?:don'?t (?:use|show|include)|never show|cut the part)\b", c):
        words = re.sub(r"\b(?:" + REMOVE + r"|don'?t (?:use|show|include)|never show|cut the part|with|of|the|that|this|those|shot|shots|clip|clips|scene|scenes|"
                       r"footage|part|one|where|please|from|video|edit|showing|there'?s|is)\b", " ", c)
        files = match_files(words, an) if content_words(words) else []
        sh = match_shots(words, design, an) if content_words(words) else []
        if files and (re.search(r"\b(?:all|any|every|don'?t use|never|at all|whole file|footage|shots|clips|scenes|parts)\b", c)
                      or re.match(r"\s*no\b", c) or not sh):
            top = files[0][1]
            for f, sc in files:
                if sc >= 0.75 * top:
                    ops.append({"op": "avoid_file", "file": f})
            return {"ops": ops, "focus": {"kind": "shot"}, "note": ""}
        if sh:
            ops.append({"op": "shot_remove", "ids": [sh[0]["id"]], "file": sh[0].get("file")})
            return {"ops": ops, "focus": {"kind": "shot"}, "note": ""}
    m = re.search(r"\b(?:show|play|use|put) (?:the |that |a )?(.+?) (?:twice|again|two times|2 times|one more time|more often)\b|"
                  r"\brepeat (?:the |that )?(.+?)(?: shot| clip| moment)?\s*$|"
                  r"\bmore (?:of (?:the )?|shots of (?:the )?|footage of (?:the )?|clips of (?:the )?)(.+)$|\b(?:use|show) more (?:of )?(?:the )?(.+)$|"
                  r"\b(?:add|show|use|put|include|insert) (?:a |an |some |more |another )?(?:\w+ )?(?:shots?|clips?|footage|scenes?|b-?roll) (?:of|with|showing) (?:the |a |an )?(.+)$", c)
    if m:
        words = next(g for g in m.groups() if g)
        files = match_files(words, an)
        if files:
            ops.append({"op": "more_of", "file": files[0][0], "n": 1 if re.search(r"\b(?:twice|again|two times|2 times|one more time|repeat)\b", c) else 2})
            return {"ops": ops, "focus": {"kind": "shot"}, "note": ""}
    return None


def _file_shots(words, ctx):
    files = match_files(words, ctx.get("analyses") or {})
    if not files:
        return []
    f = files[0][0].lower()
    return [s for s in (ctx.get("design") or {}).get("shots") or [] if isinstance(s, dict) and str(s.get("file") or "").lower() == f] or \
        [{"id": None, "file": files[0][0]}]


EFFECT_QUERY_STOP = r"\b(?:add|put|insert|include|place|throw|give|want|need|some|an?|the|effects?|fx|on|at|in|to|over|for|during|when|his|her|my|their|" \
                    r"its|it|please|also|of|with|drop|end|ending|start|beginning|intro|outro|climax|whole|video|clip|shot|part|cool|nice|little|bit)\b"


def _effect_key(words, must=None, target=None):
    """The catalogue effect for a few words: an item NAMED like the words first ('Lightning' for "lightning"), then one
    described like them; working here before untried; VIP and broken items never. None if nothing fits."""
    from . import catalog_qa as CQ
    spec = CQ.parse(words)
    kinds = ["character_effect", "scene_effect"] if target else ["scene_effect"]
    plain = [w for w in re.findall(r"[a-z]+", words.lower()) if w not in STOP and len(w) > 2]
    q = [_stem(w) for w in plain]
    search = plain + [w[:-1] for w in plain if w.endswith("s") and len(w) > 4]  # "sparkles" also finds "Sparkle"
    found = CQ.find({**spec, "kinds": kinds, "words": search or spec.get("words") or [], "target": target})
    ok = [it for it in found if it["state"] in ("ready", "untried")]
    if must:
        ok = [it for it in ok if must in f"{it['en']} {it['desc']}".lower()] or ok
    if not ok:
        return None

    def named_or_described(it):
        en, desc = str(it["en"]).lower(), str(it["desc"]).lower()
        return any(re.search(r"\b" + re.escape(w), en) for w in q) or (q and all(w in desc for w in q))
    ok = [it for it in ok if named_or_described(it)]
    if not ok:
        return None

    def fit(it):
        en, desc = str(it["en"]).lower(), str(it["desc"]).lower()
        named = sum(1 for w in q if re.search(r"\b" + re.escape(w), en))
        described = sum(1 for w in q if w in desc)
        theme = 1 if re.search(r"\b(?:the end|birthday|christmas|new year|valentine|wedding|halloween|holiday)\b", f"{en} {desc}") and \
            not re.search(r"\b(?:end|birthday|christmas|new year|valentine|wedding|halloween|holiday)\b", words.lower()) else 0
        extra = len([w for w in re.findall(r"[a-z]+", en) if not any(w.startswith(x) for x in q) and w not in ("i", "ii", "iii", "iv")])
        return (-named, theme, extra > 0, -described, it["state"] != "ready", extra, -float(it.get("score") or 0))
    return min(ok, key=fit)["key"]


def _shot_anchor(c, ctx):
    """{"shot": id} for "when the goal goes in", "as he jumps", "on the kiss", "before the drop shot", or None."""
    m = re.search(r"\b(?:when|where|while|during|as soon as|as|on|over|before|after)\s+(?:the |he |she |it |they |his |her |its |their |a |an )?(.+)$", c)
    if not m:
        return None
    hits = match_shots(m.group(1), ctx.get("design") or {}, ctx.get("analyses") or {})
    return {"shot": hits[0]["id"]} if hits else None


def _effect_add(c, ctx):
    """'add lightning on his eyes at the drop' -> a catalogue effect that works here, placed where asked."""
    from . import catalog_qa as CQ
    spec = CQ.parse(c)
    what = re.split(r"\b(?:when|where|while|during|as soon as|on the|over the|at the)\b", c, maxsplit=1)[0]
    words = " ".join(w for w in re.sub(EFFECT_QUERY_STOP, " ", what).split() if len(w) > 2 and not re.match(r"\d", w)) or \
        " ".join(w for w in re.sub(EFFECT_QUERY_STOP, " ", c).split() if len(w) > 2 and not re.match(r"\d", w))
    if not words.strip():
        return None
    target = spec.get("target")
    key = _effect_key(words, target=target)
    if not key:
        return {"ops": [], "focus": {"kind": "effects"}, "note": f"no effect for '{words}'",
                "ask": f"I found no free effect for '{words}' that works here; try other words (e.g. 'sparkles', 'light leak', 'glitch')."}
    anchor = _anchor(c)
    whole = re.search(r"\b(?:whole|entire|throughout|all the way|the full|everywhere)\b", c)
    m = re.search(r"\b(?:when|where|while|during|as|on|over)\s+(?:the |he |she |it |they |his |her |its |their )?(.+)$", c)
    if anchor is None and not whole and m:
        hits = match_shots(m.group(1), ctx.get("design") or {}, ctx.get("analyses") or {})
        if hits:
            anchor = {"shot": hits[0]["id"]}
    return {"ops": [{"op": "fx_add", "item": key, "anchor": "whole" if whole else anchor, "target": target,
                     "label": _cat().index.notes.get(key, {}).get("en") or key.split(":", 1)[1]}], "focus": {"kind": "effects", "item": key}, "note": ""}


# ------------------------------------------------------------------------------------------------ applying
DESIGN_OPS = {"length", "pace", "music", "canvas", "recipe", "shot", "shot_move", "shot_remove", "avoid_file", "more_of", "swap_shots",
              "section_beats", "speed_reset", "captions", "pace_set", "shots_set", "unavoid_file", "shot_beats", "less_of",
              "use_template", "tpl_speed"}


def is_design(op):
    return op.get("op") in DESIGN_OPS


def apply_design(design, ops, ctx):
    """Structural follow-ups on the design (compose re-cuts it). Returns (design, [what was done], [what could not be])."""
    from .critic import apply_design_patch
    d = copy.deepcopy(design)
    shots = [s for s in d.get("shots") or [] if isinstance(s, dict)]
    d["shots"] = shots
    an = ctx.get("analyses") or {}
    done, failed = [], []
    total = float(ctx.get("seconds") or d.get("target_seconds") or 30)
    for op in ops:
        k = op["op"]
        if k == "length":
            footage = sum(float(a.get("seconds") or 4) for a in an.values() if a.get("kind") in ("video", "image") and not str(a.get("file", "")).startswith("music_"))
            want = float(op["seconds"]) if op.get("seconds") else total * float(op["mul"])
            want = max(5.0, min(want, max(10.0, footage * 0.95)))
            d["target_seconds"] = round(want, 1)
            vo = d.get("voiceover") if isinstance(d.get("voiceover"), dict) else None
            if vo:
                va = next((a for a in an.values() if str(a.get("file", "")).lower() == str(vo.get("file", "")).lower()), None)
                vo_from = float(vo.get("from", 0) or 0)
                vo_len = float(vo.get("duration") or ((va or {}).get("seconds") or 0) - vo_from)
                if va and vo_len > want - 0.8:
                    from . import speech as SP
                    tr = SP.cached(va["path"]) if va.get("path") else None
                    words = [w for w in (tr or {}).get("words") or [] if w["start"] >= vo_from]
                    ends = [w["end"] - vo_from for w in words if re.search(r"[.!?]\W*$", str(w.get("word") or w.get("text") or "")) and w["end"] - vo_from <= want - 1.0]
                    cut = round(max(ends) + 0.2 if ends else want - 1.0, 2)
                    d["voiceover"] = {**vo, "duration": cut}
                    done.append(f"narration ends at {cut:.1f} s, at the end of a sentence" if ends else f"narration cut at {cut:.1f} s")
            done.append(f"length {total:.0f} s -> {want:.0f} s")
        elif k == "pace":
            if op.get("sections"):  # the shot length of those sections changes; the sections keep their length (more cuts in them)
                d["pace_sections"] = {**(d.get("pace_sections") or {}),
                                      **{sec: round(float((d.get("pace_sections") or {}).get(sec, 1)) * op["mul"], 3) for sec in op["sections"]}}
            else:
                d["pace"] = round(float(d.get("pace") or 1) * float(op["mul"]), 3)
            done.append(("faster cuts" if op["mul"] < 1 else "longer shots") + (f" in the {'/'.join(op['sections'])}" if op.get("sections") else ""))
        elif k == "shot_beats":  # one shot longer or shorter on the beat grid (a held moment: the cut engine keeps it)
            sh = next((s for s in shots if s.get("id") == op["id"]), None)
            if not sh:
                failed.append(f"shot {op['id']} not found")
                continue
            b0 = float(sh.get("beats") or 4)
            sh["beats"] = max(1, int(b0 * op["mul"] + (0.75 if op["mul"] > 1 else 0.25)))
            sh["hold"] = op["mul"] > 1 or sh.get("hold", False)
            done.append(f"shot {op['id']} ({str(sh.get('want') or sh.get('file') or '')[:30]}) {'longer' if op['mul'] > 1 else 'shorter'}: "
                        f"{b0:.0f} -> {sh['beats']} beats")
        elif k == "pace_set":
            d["pace"] = float(op.get("value") or 1)
            done.append(f"pacing back to x{d['pace']:.2f}")
        elif k == "shots_set":
            d["shots"] = shots = copy.deepcopy(op.get("shots") or shots)
            d["avoid_files"] = list(op.get("avoid") or [])
            done.append("shots back to the earlier version")
        elif k == "music":
            m = d.get("music") if isinstance(d.get("music"), dict) else {}
            if "set" in op:  # an earlier version's music, as it was
                d["music"] = copy.deepcopy(op["set"])
                d["_music_asked"] = True
                done.append("music back to the earlier version")
            elif op.get("file"):
                f = next((a["file"] for a in an.values() if a.get("kind") == "audio" and a.get("file", "").lower() == op["file"].lower()), None)
                if not f:
                    failed.append(f"no audio file named {op['file']} is in this edit's media")
                    continue
                d["music"] = {"file": f, "from": 0}
                d["_music_asked"] = True
                done.append(f"music: your file {f}")
            elif op.get("generate"):
                cur = m.get("generate") or (str(d.get("music")) if isinstance(d.get("music"), str) else None) or "pop"
                g = NEIGHBOUR.get(cur, "pop") if op["generate"] == "_next" else op["generate"]
                d["music"] = {"generate": g, "bpm": GENRE_BPM.get(g, 120) if g != cur else m.get("bpm") or GENRE_BPM.get(g, 120)}
                d["_music_asked"] = True
                done.append(f"music: {cur} -> {g}")
            elif op.get("bpm_mul"):
                bpm = float(m.get("bpm") or ctx.get("bpm") or 120)
                nb = int(round(max(60, min(180, bpm * float(op["bpm_mul"])))))
                d["music"] = {**m, "generate": m.get("generate") or "pop", "bpm": nb}
                d["_music_asked"] = True
                done.append(f"music tempo {bpm:.0f} -> {nb} BPM")
        elif k == "canvas":
            if (d.get("canvas") or ctx.get("canvas")) == op["value"]:
                failed.append(f"it is already {op['value']}")
                continue
            d["canvas"] = op["value"]
            if op.get("platform"):
                d["platform"] = op["platform"]
            done.append(f"format {op['value']}")
        elif k == "recipe":
            r = {kk: v for kk, v in op.items() if kk != "op"}
            d2, ds = apply_design_patch(d, [{"op": "recipe", **r}])
            d.update(d2)
            shots = d["shots"]
            name = {"zoom_punch": "zoom punches", "shake": "shakes", "flash": "flashes", "rgb_hit": "colour-split hits",
                    "ken_burns": "slow push-ins"}.get(r.get("use"), str(r.get("use")))
            done.append(f"no {name}" if r.get("off") else f"{name} on the {r.get('on', 'beats')}" +
                        (f" in the {'/'.join(r['sections'])}" if r.get("sections") else ""))
        elif k == "shot":
            sh = next((s for s in shots if s.get("id") == op["id"]), None)
            if not sh:
                failed.append(f"shot {op['id']} not found")
                continue
            sh[op["field"]] = op["value"]
            if op["field"] == "speed":
                what = {"slow": "slow motion", "velocity": "a speed ramp", "freeze": "a freeze frame", "fast": "fast motion",
                        "normal": "normal speed"}.get(op["value"], op["value"])
                done.append(f"{what} on {op['id']} ({str(sh.get('want') or sh.get('file') or '')[:40]})")
            elif op["field"] != "hold":
                done.append(f"shot {op['id']} {op['field']} = {op['value']}")
        elif k == "speed_reset":
            n = 0
            for s in shots:
                if s.get("speed") in op["kinds"]:
                    s["speed"] = "normal"
                    n += 1
            (done if n else failed).append(f"{n} shot(s) back to normal speed" if n else "no slow motion / speed changes to remove")
        elif k == "shot_move":
            sh = next((s for s in shots if s.get("id") == op.get("id")), None)
            if sh is None and op.get("file"):  # the file is only in a fill run: give it its own shot
                sh = {"id": f"m{len(shots) + 1}", "file": op["file"], "beats": 4, "want": "asked for by the client", "around": None}
            if sh is None:
                failed.append("that shot was not found")
                continue
            if sh in shots:
                shots.remove(sh)
            if op["to"] == "first":
                old_first = shots[0] if shots else None
                sh["section"] = "intro"
                shots.insert(0, sh)
                if old_first is not None and old_first.get("section") == "intro":
                    pass
            elif op["to"] == "last":
                sh["section"] = "outro"
                shots.append(sh)
            else:
                i = next((j for j, s in enumerate(shots) if s.get("section") == "drop"), len(shots) // 2)
                sh["section"] = "drop"
                sh["hold"] = True
                shots.insert(i, sh)
            done.append(f"{sh.get('file') or sh['id']} -> {op['to']}")
        elif k == "shot_remove":
            ids = set(op["ids"])
            before = len(shots)
            shots[:] = [s for s in shots if s.get("id") not in ids]
            for e in d.get("edits") or []:  # extras that pointed at it move to the next shot
                if isinstance(e, dict) and e.get("on") in ids:
                    e.pop("on", None)
            (done if len(shots) < before else failed).append(f"removed shot {', '.join(ids)}" if len(shots) < before else "that shot was not found")
        elif k == "avoid_file":
            d["avoid_files"] = sorted(set(d.get("avoid_files") or []) | {op["file"]})
            done.append(f"not using {op['file']}")
        elif k == "less_of":  # fewer shots of a file: its first hand-picked shot stays, the rest and its share of the quick cuts go
            f = op["file"].lower()
            mine = [s for s in shots if str(s.get("file") or "").lower() == f]
            gone = mine[1:] if len(mine) > 1 else []
            shots[:] = [s for s in shots if s not in gone]
            for s in shots:
                if s.get("files"):
                    s["files"] = [x for x in s["files"] if str(x).lower() != f] or s["files"]
            d["less_files"] = sorted(set(d.get("less_files") or []) | {op["file"]})
            done.append(f"fewer shots of {op['file']}" + (f" ({len(gone)} removed)" if gone else ""))
        elif k == "unavoid_file":
            before = list(d.get("avoid_files") or [])
            d["avoid_files"] = [f for f in before if f.lower() != op["file"].lower()]
            done.append(f"{op['file']} is back in")
        elif k == "more_of":
            i = next((j for j, s in enumerate(shots) if s.get("section") in ("build", "drop")), len(shots) // 2)
            a = next((x for x in an.values() if str(x.get("file", "")).lower() == op["file"].lower()), {})
            best = sorted((m for m in a.get("moments") or [] if isinstance(m.get("highlight"), (int, float))), key=lambda m: -m["highlight"])
            for n in range(int(op.get("n") or 2)):
                shots.insert(i + 1 + n, {"id": f"mo{len(shots) + 1}", "section": shots[i]["section"] if shots else "verse", "file": op["file"],
                                         "beats": 4 if n == 0 else 2, "want": "more of this, as asked", "hold": n == 0,
                                         "around": best[n]["t"] if len(best) > n else None})
            d["avoid_files"] = [f for f in d.get("avoid_files") or [] if f.lower() != op["file"].lower()]
            done.append(f"more of {op['file']}")
        elif k == "swap_shots":
            ia = next((j for j, s in enumerate(shots) if s.get("id") == op["a"]), None)
            ib = next((j for j, s in enumerate(shots) if s.get("id") == op["b"]), None)
            if ia is None or ib is None:
                failed.append("shots to swap not found")
                continue
            shots[ia], shots[ib] = shots[ib], shots[ia]
            shots[ia]["section"], shots[ib]["section"] = shots[ib].get("section"), shots[ia].get("section")
            done.append(f"swapped {op['a']} and {op['b']}")
        elif k == "section_beats":
            n = 0
            for s in shots:
                if s.get("section") == op["section"]:
                    n += 1
                    if isinstance(s.get("fill"), (int, float)):
                        s["fill"] = max(1, round(s["fill"] * op["mul"]))
                    else:
                        s["beats"] = max(1, round(float(s.get("beats") or 4) * op["mul"]))
                    if op["mul"] > 1:
                        s["hold"] = True
            if op["mul"] < 1 and n:  # a shorter part: the whole edit gets shorter too (else fit() would pad it again)
                part_s = float((ctx.get("section_seconds") or {}).get(op["section"]) or 1.5 * n)
                d["target_seconds"] = round(max(5.0, total - (1 - op["mul"]) * part_s), 1)
            (done if n else failed).append(f"{op['section']} x{op['mul']:.2f}" if n else f"there is no {op['section']} part")
        elif k == "captions":
            if not d.get("speech") and not d.get("voiceover"):
                failed.append("there is no speech in this edit to caption")
                continue
            tgt = d.get("speech") or d.get("voiceover")
            tgt["captions"] = "bold_pop"
            done.append("captions on")
    return d, done, failed


def _font_for(style_words, current=None):
    """A Latin font that fits the words: ones known to work here first, then untried ones that fit clearly better."""
    cat = _cat()
    n = cat.index.notes
    hits = cat.index.search(style_words or "modern clean sans", categories=["font"], k=60, exclude=cat.missing, boost=cat.boost)
    latin = [h for h in hits if n.get(f"font:{h['name']}", {}).get("script") in ("latin", "both") and f"font:{h['name']}" != current]
    if not latin:
        return None
    top = latin[0]["score"]
    known = [h for h in latin if cat.boost.get(f"font:{h['name']}", 1) >= 1.1 and h["score"] >= 0.8 * top]
    return (known or latin)[0]["name"]


def _look_for(words, current=None, different=False):
    cat = _cat()
    hits = cat.index.search(words or "cinematic natural", categories=["filter"], k=40, exclude=cat.missing, boost=cat.boost)
    hits = [h for h in hits if f"filter:{h['name']}" != current]
    if not hits:
        return None
    top = hits[0]["score"]
    known = [h for h in hits if cat.boost.get(f"filter:{h['name']}", 1) >= 1.1 and h["score"] >= 0.75 * top]
    return (known or hits)[0]["name"]


FAMILY_STANDIN = {"whip": ["horizontal blur motion", "slide push wipe"], "spin": ["zoom in push", "slide push wipe"],
                  "leak": ["white flash glow", "dissolve cross fade soft"], "glitch": ["flash white", "blur"], "flash": ["glow bright", "dissolve"],
                  "slide": ["zoom in push"], "zoom": ["slide push wipe"], "blur": ["dissolve cross fade soft"], "dissolve": ["blur soft smooth"]}


def _transition_for(fam, current=None):
    cat = _cat()
    q = FAMILIES[fam][1] if fam in FAMILIES else "smooth"
    hits = cat.index.search(q, categories=["transition"], k=30, exclude=cat.missing, boost=cat.boost)
    hits = [h for h in hits if f"transition:{h['name']}" != current]
    for alt in FAMILY_STANDIN.get(fam, []) if not hits else []:  # nothing free in that style works here: the closest style
        hits = [h for h in cat.index.search(alt, categories=["transition"], k=30, exclude=cat.missing, boost=cat.boost)
                if f"transition:{h['name']}" != current]
        if hits:
            STANDIN_NOTE["text"] = f"no free {fam} transition works here; used the closest"
            break
    if not hits:
        return None, 0.5
    top = hits[0]["score"]
    known = [h for h in hits if cat.boost.get(f"transition:{h['name']}", 1) >= 1.1 and h["score"] >= 0.7 * top]
    return (known or hits)[0]["name"], FAMILIES[fam][2] if fam in FAMILIES else 0.5


STANDIN_NOTE = {"text": ""}


def _texture_item(what):
    cat = _cat()
    q = {"grain": "film grain texture noise", "vignette": "vignette dark edges", "letterbox": "letterbox black bars cinematic aspect",
         "leak": "light leak warm glow"}[what]
    hits = cat.index.search(q, categories=["scene_effect"], k=20, exclude=cat.missing, boost=cat.boost)
    known = [h for h in hits if cat.boost.get(f"scene_effect:{h['name']}", 1) >= 1.1]
    return (known or hits)[0]["name"] if hits else None


def _loop_for(words):
    cat = _cat()
    hits = cat.index.search(words or "shake", categories=["text_loop"], k=20, exclude=cat.missing, boost=cat.boost)
    known = [h for h in hits if cat.boost.get(f"text_loop:{h['name']}", 1) >= 1.1]
    return (known or hits)[0]["name"] if hits else None


def _intro_for(words):
    cat = _cat()
    hits = cat.index.search(words or "pop in", categories=["text_intro"], k=20, exclude=cat.missing, boost=cat.boost)
    known = [h for h in hits if cat.boost.get(f"text_intro:{h['name']}", 1) >= 1.1]
    return (known or hits)[0]["name"] if hits else None


def _new_id(plan, prefix):
    ids = {str(e.get("id")) for e in plan.get("edits") or []} | {str(c.get("id")) for c in plan.get("clips") or []}
    n = 1
    while f"{prefix}{n}" in ids:
        n += 1
    return f"{prefix}{n}"


def _anchor_time(plan, anchor, dur, design=None):
    total = _total(plan)
    drop = (plan.get("_rhythm") or {}).get("drop")
    if isinstance(anchor, dict) and anchor.get("shot"):  # the start of the shot named (or of its first part after a split)
        ct = clip_times(plan)
        sid = str(anchor["shot"])
        hit = ct.get(sid) or next((v for k, v in ct.items() if re.fullmatch(re.escape(sid) + r"(?:[a-z]|_\d+)", str(k))), None)
        if hit:
            return max(0.0, min(hit[0] + 0.15, total - dur))
    if isinstance(anchor, (int, float)):
        return max(0.0, min(float(anchor), total - dur))
    if anchor == "drop":
        return float(drop) if drop is not None else total * 0.5
    if anchor == "end":
        return max(0.0, total - dur - 0.3)
    if anchor == "start":
        return 0.2
    return float(drop) if drop is not None else total * 0.5


def apply_plan(plan, ops, ctx):
    """Follow-ups on the composed plan (no re-cut). Returns (plan, [done], [failed])."""
    p = copy.deepcopy(plan)
    edits = p.setdefault("edits", [])
    done, failed = [], []
    cat = _cat()
    for op in ops:
        k = op["op"]
        ct = clip_times(p)
        if k == "text":
            ts = pick_texts(p, op.get("who") or {"role": "title"})
            if not ts:
                failed.append(f"no {(op.get('who') or {}).get('role') or 'matching'} text in this edit")
                continue
            if op.get("remove"):
                ids = {e["id"] for e in ts}
                p["edits"] = edits = [e for e in edits if e.get("id") not in ids and not (e.get("type") == "animation" and e.get("on") in ids)]
                done.append(f"removed {len(ids)} text(s): " + ", ".join(f"'{e.get('text', '')[:20]}'" for e in ts[:3]))
                continue
            st, mul = dict(op.get("set") or {}), dict(op.get("mul") or {})
            if "font_style" in st:
                cur = next((e.get("font") for e in ts if e.get("font")), None)
                cur_key = next((kk for kk in cat.exact(cur) if kk.startswith("font:")), None) if cur else None
                f = _font_for(st.pop("font_style"), cur_key)
                if not f:
                    failed.append("no font fits those words")
                else:
                    st["font"] = f
                    st["font_asked"] = True
            if "font_from" in st:
                src = pick_texts(p, {"role": st.pop("font_from")})
                f = next((e.get("font") for e in src if e.get("font")), None)
                if f:
                    st["font"] = f
                    st["font_asked"] = True
            if "intro_words" in st:
                w = st.pop("intro_words")
                st["intro"] = _intro_for(w) if w else None
            if "loop_words" in st:
                w = st.pop("loop_words")
                st["loop"] = _loop_for(w) if w else None
            what = []
            for e in ts:
                for f, v in st.items():
                    if f == "case":
                        e["text"] = e["text"].upper() if v == "upper" else e["text"].lower()
                    elif f == "position" and v in ("_up", "_down", "_up_bit", "_down_bit"):
                        step = {"_up": 0.18, "_down": -0.18, "_up_bit": 0.08, "_down_bit": -0.08}[v]
                        cur = e.get("position")
                        if isinstance(cur, dict) and cur.get("name"):
                            e["position"] = {**cur, "dy": round(float(cur.get("dy") or 0) + step, 3)}
                        elif isinstance(cur, (list, tuple)) and len(cur) == 2:
                            e["position"] = [cur[0], round(float(cur[1]) + step, 3)]
                        elif isinstance(cur, dict):
                            e["position"] = {**cur, "y": round(float(cur.get("y") or 0) + step, 3)}
                        else:  # a named place: the same place, nudged
                            e["position"] = {"name": str(cur or "center"), "dy": step}
                    elif f == "text":
                        old = str(e.get("text") or "")
                        e["text"] = v if v != v.lower() else v.upper() if old.isupper() and len(old) > 1 else v.title() if old.istitle() else v
                    elif f == "intro" and v is None:
                        e.pop("intro", None)
                    elif f in ("start", "shift"):  # timing: an absolute start, or a shift (the text keeps its length)
                        a, b = abs_window(p, e, ct)
                        new_start = max(0.0, float(v) if f == "start" else a + float(v))
                        e.pop("on", None)
                        e["start"], e["duration"] = round(new_start, 2), round(max(1.0, b - a), 2)
                    else:
                        e[f] = v
                for f, v in mul.items():
                    if f == "size":
                        e["size"] = round(max(5.0, min(40.0, float(e.get("size") or 12) * v)), 1)
                    elif f == "duration":
                        e["duration"] = round(max(0.8, float(e.get("duration") or 2) * v), 2)
            if st:
                what.append(", ".join(f"{f} {('-> ' + str(v)) if f not in ('outline', 'background') else ''}".strip() for f, v in st.items() if f != "font_asked"))
            if mul:
                what.append(", ".join(f"{f} x{v:.2f}" for f, v in mul.items()))
            names = ", ".join("the captions" if e.get("type") == "captions" else repr(str(e.get("text", "")).replace("\n", " ")[:18]) for e in ts[:3])
            done.append(f"{len(ts)} text(s) ({names}): " + "; ".join(what).replace("-> _up_bit", "a bit higher").replace("-> _down_bit", "a bit lower")
                        .replace("-> _up", "higher").replace("-> _down", "lower"))
        elif k == "text_add" and op.get("role") == "cta" and not op.get("another") and \
                any(r == "cta" for r in text_roles(p).values()) and _same_cta(p, op["text"]):  # a new version of the call to action replaces it
            roles = text_roles(p)
            cta = [e for e in edits if roles.get(str(e.get("id"))) == "cta"]
            old = cta[-1].get("text")
            cta[-1]["text"] = op["text"]
            if op.get("color"):
                cta[-1]["color"] = op["color"]
            done.append(f"call to action '{str(old)[:24]}' -> '{op['text'][:30]}'")
        elif k == "text_add":
            roles = text_roles(p)
            src = [e for e in edits if e.get("type") == "text" and roles.get(str(e["id"])) == ("title" if op["role"] != "label" else "label")] or \
                  [e for e in edits if e.get("type") == "text"]
            base = src[0] if src else {}
            dur = max(2.0, min(4.0, 0.9 + 0.3 * len(op["text"].split())))
            if op.get("role") == "cta" and not isinstance(op.get("anchor"), dict) and any(r == "cta" for r in roles.values()):
                op = {**op, "anchor": {"text": next(str(e.get("id")) for e in edits if roles.get(str(e.get("id"))) == "cta"), "position": "_below"},
                      "position": "_below"}  # a second line under the call to action, at its time
            ref = next((e for e in edits if isinstance(op.get("anchor"), dict) and e.get("id") == op["anchor"].get("text")), None)
            if ref is not None:  # with another text: at its time, just below or above it, a size smaller
                base = ref
                a, b = abs_window(p, ref, ct)
                start, dur = a + 0.3, max(1.5, b - a - 0.3)
                rp = ref.get("position") if ref.get("position") in POS_ORDER else "center"
                i = POS_ORDER.index(rp) + (1 if op.get("position") == "_below" else -1)
                op = {**op, "position": POS_ORDER[max(0, min(len(POS_ORDER) - 1, i))], "size_mul": 0.6}
            else:
                start = _anchor_time(p, op.get("anchor"), dur)
            size = float(base.get("size") or 14) * (0.75 if op["role"] == "cta" else float(op.get("size_mul") or 1.0))
            e = {"id": _new_id(p, "ux"), "type": "text", "text": op["text"], "start": round(start, 2), "duration": round(dur, 2),
                 "position": op.get("position") or ("lower" if op["role"] in ("cta", "label") else "center"), "size": round(size, 1),
                 "font": base.get("font"), "color": op.get("color") or base.get("color") or "#FFFFFF", "bold": True,
                 "outline": base.get("outline") or {"color": "#000000", "width": 60}, "intro": base.get("intro"),
                 "expect": f"the text '{op['text'][:40]}' appears", "asked": True}
            edits.append(e)
            done.append(f"added '{op['text'][:30]}' at {start:.1f} s")
        elif k == "captions":
            failed.append("captions need speech; this edit has none")
        elif k == "audio":
            who = op["who"]
            if who == "music":
                tg = [e for e in edits if e.get("id") == "music" or (e.get("type") == "audio" and str(e.get("file", "")).startswith("music_"))]
            elif who == "voice":
                tg = [e for e in edits if e.get("type") == "audio" and "voice" in fx_kinds(e, p)] or \
                     [e for e in edits if e.get("type") == "audio" and e.get("id") != "music" and not str(e.get("file", "")).startswith(("music_", "sfx_"))]
            else:
                tg = [e for e in edits if e.get("type") == "sfx" and (not op.get("sounds") or e.get("sound") in op["sounds"] or
                                                                     ("whoosh" in op["sounds"] and e.get("sound") == "swoosh"))]
            if not tg:
                failed.append(f"there is no {'music' if who == 'music' else 'voice' if who == 'voice' else 'sound effect'} to change")
                continue
            if op.get("remove"):
                ids = {e["id"] for e in tg}
                p["edits"] = edits = [e for e in edits if e.get("id") not in ids]
                done.append(f"removed {len(ids)} {who} track(s)" if who != "sfx" else f"removed {len(ids)} sound effect(s)")
                continue
            for e in tg:
                for f, v in (op.get("mul") or {}).items():
                    e[f] = round(max(0.0, min(2.0, float(e.get(f, 0.85 if who == "music" else 0.6) or 0) * v)), 3)
                for f, v in (op.get("set") or {}).items():
                    e[f] = v
            done.append(f"{who} " + ", ".join([f"{f} x{v:.2f} (now {tg[0].get(f)})" for f, v in (op.get('mul') or {}).items()] +
                                                  [f"{f} = {v}" for f, v in (op.get('set') or {}).items()]))
        elif k == "sfx_add":
            n = 0
            if op["anchor"] == "transitions":
                tr = [e for e in edits if e.get("type") == "transition" and e.get("after") in ct]
                have = {round(float(e.get("at", -1)), 1) for e in edits if e.get("type") == "sfx"}
                for e in tr:
                    t = round(max(0.0, ct[e["after"]][1] - 0.2), 2)
                    if round(t, 1) in have:
                        continue
                    edits.append({"id": _new_id(p, "ws"), "type": "sfx", "sound": op["sound"], "at": t, "volume": 0.55, "expect": "a whoosh with the transition"})
                    n += 1
                if not tr:
                    failed.append("there are no transitions to put sounds on")
                    continue
            else:
                t = _anchor_time(p, op["anchor"], 0.5)
                edits.append({"id": _new_id(p, "ws"), "type": "sfx", "sound": op["sound"], "at": round(t, 2), "volume": 0.9, "expect": f"a {op['sound']} sound"})
                n = 1
            done.append(f"added {n} {op['sound']} sound(s)")
        elif k == "fx":
            tg = _fx_targets(p, op, ct, ctx)
            if not tg:
                failed.append(f"no {op['kind']}{' there' if op.get('at') is not None or op.get('section') else ''} in this edit")
                continue
            if op.get("remove"):
                ids = {e["id"] for e in tg}
                p["edits"] = edits = [e for e in edits if e.get("id") not in ids and not (e.get("type") == "animation" and e.get("on") in ids)]
                done.append(f"removed {len(ids)} {op['kind']} edit(s)")
            elif op.get("thin"):
                tg.sort(key=lambda e: abs_window(p, e, ct)[0])
                drop_ids = {e["id"] for i, e in enumerate(tg) if i % int(op["thin"]) == 1}
                p["edits"] = edits = [e for e in edits if e.get("id") not in drop_ids]
                for e in tg:
                    if e["id"] not in drop_ids:
                        _scale_fx(e, op.get("mul") or {})
                done.append(f"{op['kind']}: {len(tg)} -> {len(tg) - len(drop_ids)}")
            elif op.get("swap"):
                n = 0
                for e in tg:
                    key = item_key(e)
                    if not key:
                        continue
                    alt = cat.index.search(item_words(key)[:80], categories=[key.split(":")[0]], k=10, exclude=cat.missing | {key}, boost=cat.boost)
                    if alt:
                        e["name"] = alt[0]["name"]
                        n += 1
                (done if n else failed).append(f"swapped {n} effect(s)" if n else "no alternative effects found")
            else:
                for e in tg:
                    _scale_fx(e, op.get("mul") or {})
                done.append(f"{op['kind']} x{list((op.get('mul') or {'x': 1}).values())[0]:.2f} on {len(tg)} edit(s)")
        elif k == "push_add":
            sid = str(op["shot"])
            tg = [cid for cid in ct if cid == sid or re.fullmatch(re.escape(sid) + r"(?:[a-z]|_\d+)", str(cid))]
            if not tg:
                failed.append(f"shot {sid} is not in the edit")
                continue
            p["edits"] = edits = [e for e in edits if not (e.get("type") == "keyframes" and e.get("property") == "scale" and e.get("on") in tg)]
            for cid in tg:
                a, b = ct[cid]
                edits.append({"id": _new_id(p, "up"), "type": "keyframes", "on": cid, "property": "scale",
                              "points": [[0, 1.0], [round(b - a, 3), float(op.get("amount") or 1.12)]], "expect": "the shot slowly pushes in", "asked": True})
            done.append(f"slow push-in on {sid}")
        elif k == "move_add":
            t = _anchor_time(p, op.get("anchor"), 0.4)
            clip = next((cid for cid, (a, b) in ct.items() if a - 1e-6 <= t < b), None)
            if clip is None:
                failed.append("no shot at that moment")
                continue
            off = round(max(0.0, t - ct[clip][0]), 3)
            if op["kind"] == "zoom":
                e = {"id": _new_id(p, "uz"), "type": "zoom", "on": clip, "start": off, "duration": 0.4, "to": float(op.get("strength") or 1.25),
                     "back": True, "expect": "a punch-in zoom", "asked": True}
            else:
                e = {"id": _new_id(p, "us"), "type": "shake", "on": clip, "start": off, "duration": 0.5, "strength": float(op.get("strength") or 0.6),
                     "expect": "the picture shakes", "asked": True}
            edits.append(e)
            done.append(f"added a {'zoom punch' if op['kind'] == 'zoom' else 'shake'} at {t:.1f} s")
        elif k == "fx_add":
            key = op["item"]
            it = cat.item(key)
            d = float(op.get("duration") or 0) or float((cat.index.notes.get(key) or {}).get("default_duration_s") or 0) or (2.5 if op.get("anchor") != "drop" else 1.5)
            if op.get("anchor") == "whole":
                start, d = 0.0, _total(p)
            else:
                d = max(1.0, min(d, 4.0))
                anc = op.get("anchor")
                if anc is None and op.get("target") in ("eyes", "face", "head"):
                    anc = _face_time(p, ctx) or "drop"
                start = _anchor_time(p, anc, d)
            e = {"id": _new_id(p, "ue"), "type": "effect", "name": it["name"], "start": round(start, 2), "duration": round(d, 2),
                 "expect": f"{op.get('label') or it['name']} is visible", "asked": True}
            edits.append(e)
            done.append(f"added {op.get('label') or it['name']} at {start:.1f}-{start + d:.1f} s")
        elif k == "transitions":
            tr = [e for e in edits if e.get("type") == "transition"]
            if op.get("at") is not None:
                tr = sorted(tr, key=lambda e: abs(ct.get(e.get("after"), (0, 0))[1] - float(op["at"])))[:1]
            if op.get("remove"):
                ids = {e["id"] for e in tr}
                cut_times = {round(ct[e["after"]][1], 1) for e in tr if e.get("after") in ct}
                p["edits"] = edits = [e for e in edits if e.get("id") not in ids and not (
                    e.get("type") == "sfx" and e.get("sound") in ("whoosh", "swoosh") and any(abs(float(e.get("at", -9)) - t) < 0.6 for t in cut_times))]
                (done if ids else failed).append(f"removed {len(ids)} transition(s) (and their whooshes)" if ids else "there are no transitions")
            elif op.get("every"):
                cur = next((e for e in tr), None)
                fam = op.get("family")
                name, dur = (_transition_for(fam) if fam else ((cur or {}).get("name"), float((cur or {}).get("duration") or 0.45)))
                if not name:
                    name, dur = _transition_for("dissolve")
                have = {e.get("after") for e in tr}
                clips = p.get("clips") or []
                n = 0
                for c in clips[:-1]:
                    if c["id"] not in have:
                        edits.append({"id": _new_id(p, "ut"), "type": "transition", "after": c["id"], "name": name, "duration": dur,
                                      "expect": "a transition between the clips"})
                        n += 1
                if n:
                    done.append(f"added {n} transition(s)")
                else:
                    failed.append("every cut already has a transition")
            elif op.get("sections_only"):  # keep the transitions where one part of the edit gives way to the next
                bounds = {round(b, 2) for _, a, b in sections(p, ctx.get("design"))[:-1]}
                keep_ids = {e["id"] for e in tr if any(abs(ct.get(e.get("after"), (0, -9))[1] - x) < 0.15 for x in bounds)}
                drop_ids = {e["id"] for e in tr} - keep_ids
                p["edits"] = edits = [e for e in edits if e.get("id") not in drop_ids]
                (done if drop_ids else failed).append(f"transitions only at the section changes: {len(tr)} -> {len(keep_ids)}" if drop_ids
                                                      else "the transitions already are only at the section changes")
            elif op.get("thin"):
                tr.sort(key=lambda e: ct.get(e.get("after"), (0, 0))[1])
                drop_ids = {e["id"] for i, e in enumerate(tr) if i % int(op["thin"]) == 1}
                p["edits"] = edits = [e for e in edits if e.get("id") not in drop_ids]
                done.append(f"transitions: {len(tr)} -> {len(tr) - len(drop_ids)}")
            elif op.get("mul"):
                for e in tr:
                    e["duration"] = round(max(0.15, min(1.5, float(e.get("duration") or 0.5) * op["mul"]["duration"])), 2)
                (done if tr else failed).append(f"{len(tr)} transition(s) x{op['mul']['duration']:.2f} long" if tr else "there are no transitions")
            elif op.get("family") or op.get("item"):
                cur = item_key(tr[0]) if tr else None
                if op.get("item"):
                    name, dur = cat.item(op["item"])["name"], float(tr[0].get("duration") or 0.5) if tr else 0.5
                elif op["family"] == "_different":
                    fam = next((f for f, (pp, _, _) in FAMILIES.items() if pp.search(item_words(cur))), "dissolve") if cur else "dissolve"
                    alt = "dissolve" if fam != "dissolve" else "blur"
                    name, dur = _transition_for(alt, cur)
                else:
                    name, dur = _transition_for(op["family"], cur)
                if not name:
                    failed.append("no transition fits those words")
                    continue
                if STANDIN_NOTE["text"]:
                    done.append(STANDIN_NOTE["text"])
                    STANDIN_NOTE["text"] = ""
                if not tr:  # none yet: add them at the section changes (every 4th cut)
                    clips = p.get("clips") or []
                    for i, c in enumerate(clips[:-1]):
                        if i % 4 == 3:
                            edits.append({"id": _new_id(p, "ut"), "type": "transition", "after": c["id"], "name": name, "duration": dur,
                                          "expect": "a transition"})
                    done.append(f"added {name} transitions")
                    continue
                for e in tr:
                    e["name"], e["duration"] = name, dur
                n = cat.index.notes.get(f"transition:{name}", {})
                done.append(f"{len(tr)} transition(s) -> {name} ({n.get('en', '')})")
        elif k == "look":
            fl = [e for e in edits if e.get("type") == "filter" and float(e.get("duration") or 0) >= 0.5 * _total(p)] or \
                 [e for e in edits if e.get("type") == "filter"]
            if op.get("remove"):
                ids = {e["id"] for e in fl}
                p["edits"] = edits = [e for e in edits if e.get("id") not in ids]
                (done if ids else failed).append(f"removed the colour grade ({len(ids)} filter(s))" if ids else "there is no filter to remove")
                continue
            if op.get("mul"):
                for e in fl:
                    e["strength"] = round(max(10.0, min(100.0, float(e.get("strength") or 70) * op["mul"]["strength"])), 1)
                (done if fl else failed).append(f"grade strength x{op['mul']['strength']:.2f}" if fl else "there is no filter to change")
                continue
            cur = item_key(fl[0]) if fl else None
            name = cat.item(op["item"])["name"] if op.get("item") in cat.index.items else _look_for(op.get("words"), cur, op.get("different"))
            if not name:
                failed.append("no filter fits that look")
                continue
            if fl:
                for e in fl:
                    e["name"] = name
            else:
                edits.append({"id": _new_id(p, "ug"), "type": "filter", "name": name, "start": 0, "duration": round(_total(p), 2),
                              "strength": 65, "expect": f"a {op.get('name')} look over the whole video"})
            if op.get("name") == "brighter":  # the dimming layer that matched a dark sample works against "brighter"
                for lay in p.get("layers") or []:
                    if str(lay.get("id", "")).startswith("lk_dim"):
                        lay["opacity"] = round(float(lay.get("opacity", 0.3) or 0.3) * 0.4, 3)
            nn = cat.index.notes.get(f"filter:{name}", {})
            done.append(f"look -> {name} ({nn.get('en', '')}: {op.get('name')})")
        elif k == "restore" and op.get("fields"):  # one aspect of the same texts back (their font, colour, size...)
            old = {str(e.get("id")): e for e in op.get("edits") or []}
            n = 0
            for e in edits:
                o = old.get(str(e.get("id")))
                if o is None:
                    continue
                for f in op["fields"]:
                    if o.get(f) is None:
                        e.pop(f, None)
                    else:
                        e[f] = copy.deepcopy(o[f])
                if "font" in op["fields"]:
                    e.pop("font_asked", None)
                n += 1
            (done if n else failed).append(f"{op.get('role') or 'text'} {'/'.join(op['fields'])} back to the earlier version ({n} text(s))"
                                           if n else "those texts are not in the edit any more")
        elif k == "restore":
            kind, role = op["kind"], op.get("role")
            roles = text_roles(p)

            def mine(e):
                t = e.get("type")
                if kind == "text":
                    return t in ("text", "captions") and (role in (None, "text", "all") or roles.get(str(e.get("id"))) == role)
                if kind in ("transition", "filter", "sfx"):
                    return t == kind
                if t in ("text", "captions", "audio", "sfx", "transition", "filter", "animation"):
                    return False
                return {"effects": "effect"}.get(kind, kind) in fx_kinds(e, p)
            before = [e for e in edits if mine(e)]
            anchors = set(ct) | {str(e.get("id")) for e in edits if e.get("type") in ("text", "captions")}
            old = [copy.deepcopy(e) for e in op.get("edits") or []
                   if (not e.get("on") or e["on"] in anchors) and (not e.get("after") or e["after"] in ct)]
            lost = len(op.get("edits") or []) - len(old)
            gone = {str(e.get("id")) for e in before} - {str(e.get("id")) for e in old}
            p["edits"] = edits = [e for e in edits if not mine(e) and not (e.get("type") == "animation" and str(e.get("on")) in gone)] + old
            done.append(f"{role or kind} back to the earlier version ({len(before)} -> {len(old)} item(s))"
                        + (f"; {lost} could not be placed (their shots changed since)" if lost else ""))
        elif k == "texture":
            what = op["what"]
            tg = [e for e in edits if e.get("type") == "effect" and what in fx_kinds(e, p)]
            if op.get("remove"):
                ids = {e["id"] for e in tg}
                p["edits"] = edits = [e for e in edits if e.get("id") not in ids]
                (done if ids else failed).append(f"removed the {what}" if ids else f"there is no {what} in this edit")
            elif tg:
                done.append(f"there already is a {what}")
            else:
                name = _texture_item(what)
                if not name:
                    failed.append(f"no {what} effect works here")
                    continue
                edits.append({"id": _new_id(p, "ux"), "type": "effect", "name": name, "start": 0, "duration": round(_total(p), 2),
                              "layer": "texture", "expect": f"{what} over the whole video"})
                done.append(f"added {what} ({name})")
        elif k == "clips":
            clips = p.get("clips") or []
            if op.get("last"):
                tg = clips[-1:]
            elif op.get("files"):
                fs = {str(f).lower() for f in op["files"] if f}
                tg = [c for c in clips if str(c.get("file", "")).lower() in fs]
            else:
                tg = clips
            if not tg:
                failed.append("no matching clips")
                continue
            for c in tg:
                for f, v in (op.get("set") or {}).items():
                    c[f] = v
                for f, v in (op.get("mul") or {}).items():
                    c[f] = round(max(float(op.get("min") or 0), min(2.0, float(c.get(f, 1.0) or 0) * v)), 3)
            done.append(f"{len(tg)} clip(s): " + ", ".join([f"{f} = {v}" for f, v in (op.get('set') or {}).items()] +
                                                         [f"{f} x{v:.2f}" for f, v in (op.get('mul') or {}).items()]))
        else:
            failed.append(f"unknown change {k}")
    return p, done, failed


def _same_cta(plan, words):
    """Whether new call-to-action words are a new version of the one there ("Book a viewing: 555-0123" for "Book a
    Viewing"), not a second line to go with it ("Available on iOS and Android" with "Download now")."""
    roles = text_roles(plan)
    new = set(content_words(words))
    for e in plan.get("edits") or []:
        if roles.get(str(e.get("id"))) == "cta":
            old = set(content_words(e.get("text") or ""))
            if old and len(old & new) >= max(1, len(old) // 2):
                return True
    return False


def _scale_fx(e, mul):
    f = mul.get("strength")
    if not f:
        return
    if e.get("type") == "zoom":
        e["to"] = round(1 + (float(e.get("to") or 1.15) - 1) * f, 3)
    elif e.get("type") == "shake":
        e["strength"] = round(max(0.05, min(1.0, float(e.get("strength") or 0.5) * f)), 3)
    elif e.get("type") == "effect":
        params = e.get("params") if isinstance(e.get("params"), dict) else {}
        if params:
            e["params"] = {k: round(max(0, min(100, float(v) * f)), 1) for k, v in params.items() if isinstance(v, (int, float))}
        else:  # the item's own adjustable strength, if it has one (names differ per item); otherwise only its length changes
            key = item_key(e)
            names = [x.get("name", "") for x in (_cat().index.items.get(key) or {}).get("params", [])] if key else []
            pick = next((n for n in names if re.search(r"intensity|strength|degree|range|amount|alpha|opacity|filter|size", n)), None)
            if pick:
                e["params"] = {pick.replace("effects_adjust_", ""): round(max(5, min(100, 50 * f)), 1)}
        e["duration"] = round(float(e.get("duration") or 0.5) * (1 if f >= 1 else max(0.6, f)), 3) if e.get("duration") else e.get("duration")


def _section_spans(p, ctx, name):
    allsec = sections(p, ctx.get("design"))
    want = {"middle": ("verse", "build"), "outro": ("outro",), "intro": ("intro",)}.get(name, (name,))
    secs = [(a, b) for n, a, b in allsec if n in want]
    if not secs:
        total = _total(p)
        secs = [(0, total * 0.15)] if name == "intro" else [(total * 0.85, total)] if name == "outro" else [(total * 0.3, total * 0.7)]
    return secs


def _fx_targets(p, op, ct, ctx):
    kind = op["kind"]
    kinds = set(op.get("kinds") or [kind])
    keep = set(op.get("keep") or [])
    secs = _section_spans(p, ctx, op["section"]) if op.get("section") else None
    outside = _section_spans(p, ctx, op["except_section"]) if op.get("except_section") else None
    out = []
    for e in p.get("edits") or []:
        if e.get("type") in ("text", "captions", "audio", "sfx", "transition", "filter", "animation"):
            continue
        if op.get("item"):
            if item_key(e) == op["item"]:
                out.append(e)
            continue
        fk = fx_kinds(e, p)
        if kind == "effect":
            hit = bool(fk & kinds) and "texture" not in fk and not (fk & keep)
        elif kind == "zoom":
            hit = "zoom" in fk
        else:
            hit = kind in fk
        if not hit:
            continue
        a, b = abs_window(p, e, ct)
        if op.get("at") is not None and not (a - 0.4 <= float(op["at"]) <= b + 0.4):
            continue
        if secs is not None and not any(sa - 0.05 <= a < sb for sa, sb in secs):
            continue
        if outside is not None and any(sa - 0.05 <= a < sb for sa, sb in outside):
            continue
        out.append(e)
    return out


def _face_time(p, ctx):
    """Timeline time of the clip with the biggest face (for an eye/face effect without a place given)."""
    an = ctx.get("analyses") or {}
    ct = clip_times(p)
    best, bt = 0.0, None
    for c in p.get("clips") or []:
        a = next((x for x in an.values() if str(x.get("file", "")).lower() == str(c.get("file", "")).lower()), None)
        if not a:
            continue
        f0 = float(c.get("from") or 0)
        span = float(c.get("duration") or 0) * float(c.get("speed") or 1)
        for fr in a.get("faces") or []:
            if f0 <= fr["t"] <= f0 + span and fr["faces"]:
                size = fr["faces"][0]["box"][2] * fr["faces"][0]["box"][3]
                if size > best:
                    best, bt = size, ct[c["id"]][0] + (fr["t"] - f0) / max(0.1, float(c.get("speed") or 1))
    return bt


# ------------------------------------------------------------------------------------------------ checking
def check(op, R0, R1, plan1=None):
    """Did the change happen on the new timeline? -> (ok, what). Compares the resolved timelines before and after."""
    k = op["op"]
    e0, e1 = R0["edits"], R1["edits"]

    def texts(R):
        return [e for e in R["edits"] if e["type"] in ("text", "captions")]
    if k == "length":
        want = float(op.get("seconds") or R0["end"] * float(op.get("mul") or 1))
        ok = abs(R1["end"] - want) <= max(1.5, 0.06 * want) or (want > R1["end"] and op.get("mul", 1) > 1 and R1["end"] > R0["end"])
        return ok, f"{R0['end']:.1f} s -> {R1['end']:.1f} s"
    if k == "pace":
        r0, r1 = len(R0["clips"]) / max(1, R0["end"]), len(R1["clips"]) / max(1, R1["end"])
        ok = (r1 > r0 * 1.03) if op["mul"] < 1 else (r1 < r0 * 0.97)
        return ok, f"{len(R0['clips'])} -> {len(R1['clips'])} shots ({60 * r0:.0f} -> {60 * r1:.0f} cuts/min)"
    if k == "canvas":
        w, h = R1["canvas"]
        a, b = (int(x) for x in op["value"].split(":"))
        return abs(w / h - a / b) < 0.02, f"{R0['canvas'][0]}x{R0['canvas'][1]} -> {w}x{h}"
    if k == "use_template":  # the edit is now the template's slots, at its length
        n, secs = op.get("slots"), op.get("seconds")
        ok = (n is None or abs(len(R1["clips"]) - n) <= 1) and (secs is None or abs(R1["end"] - float(secs)) <= 0.35)
        return ok, f"{len(R1['clips'])} slots, {R1['end']:.2f} s" + (f" (template: {n} slots, {float(secs):.2f} s)" if n and secs else "")
    if k == "tpl_speed":
        sp = [pc["speed"] for c in R1["clips"] for pc in c.get("pieces") or [] if pc.get("kind") == "video"]
        ramps = sum(1 for c in R1["clips"] if len({pc["speed"] for pc in c.get("pieces") or []}) > 1)
        v = op["value"]
        if v == "normal":
            return all(abs(x - 1) < 0.01 for x in sp), "all slots at normal speed" if all(abs(x - 1) < 0.01 for x in sp) else "some slots still slowed"
        if v == "ramp":
            return ramps > 0, f"{ramps} slot(s) with a speed ramp"
        slow = sorted(x for x in sp if x < 0.95)
        med = slow[len(slow) // 2] if slow else 1.0
        return bool(slow) and abs(med - float(v)) < 0.2, f"{len(slow)} slow piece(s), median {med:.2f}x"
    if k == "music" and "set" in op:
        return True, "music restored"
    if k == "music":
        m0 = next((e for e in e0 if e["id"] == "music"), {})
        m1 = next((e for e in e1 if e["id"] == "music"), {})
        if op.get("generate"):
            g = str(m1.get("file", "")).split("_")[1] if str(m1.get("file", "")).startswith("music_") else "?"
            ok = g != "?" and (g == op["generate"] or op["generate"] == "_next" and m1.get("file") != m0.get("file"))
            return ok, f"music {m0.get('file', 'none')} -> {m1.get('file', 'none')}"
        if op.get("bpm_mul"):
            b0 = int(str(m0.get("file", "_0_0")).split("_")[2]) if str(m0.get("file", "")).startswith("music_") else 0
            b1 = int(str(m1.get("file", "_0_0")).split("_")[2]) if str(m1.get("file", "")).startswith("music_") else 0
            return (b1 > b0) == (op["bpm_mul"] > 1) and b1 != b0, f"{b0} -> {b1} BPM"
        if op.get("file"):
            return m1.get("file", "").lower() == op["file"].lower(), f"music {m1.get('file')}"
    if k == "audio":
        def tracks(es):
            if op["who"] == "music":
                return [e for e in es if e["id"] == "music" or (e["type"] == "audio" and str(e.get("file", "")).startswith("music_"))]
            if op["who"] == "sfx":
                return [e for e in es if e["type"] == "audio" and e.get("sfx")]
            return [e for e in es if e["type"] == "audio" and not e.get("sfx") and e["id"] != "music"]
        t0, t1 = tracks(e0), tracks(e1)
        if op.get("remove"):
            return len(t1) < len(t0), f"{len(t0)} -> {len(t1)} {op['who']} track(s)"
        if op.get("mul"):
            v0 = t0[0].get("volume", 1) if t0 else None
            v1 = t1[0].get("volume", 1) if t1 else None
            f = op["mul"]["volume"]
            ok = v0 is not None and v1 is not None and ((v1 > v0) if f > 1 else (v1 < v0)) or (v0 is not None and v0 >= 2.0 and f > 1)
            return bool(ok), f"volume {v0} -> {v1}"
        if op.get("set"):
            f, v = next(iter(op["set"].items()))
            return bool(t1) and all(abs(float(t.get(f, 0) or 0) - float(v)) < 1e-3 for t in t1), f"{f} = {t1[0].get(f) if t1 else None}"
    if k == "text":
        if op.get("remove"):
            return len(texts(R1)) < len(texts(R0)), f"{len(texts(R0))} -> {len(texts(R1))} texts"
        st = op.get("set") or {}
        changed = [(a, b) for a in texts(R0) for b in texts(R1) if a["id"] == b["id"]]
        ok, what = True, []
        if "color" in st:
            hits = [b for a, b in changed if b["style"]["color"].upper() == str(st["color"]).upper()]
            ok &= bool(hits)
            what.append(f"{len(hits)} text(s) now {st['color']}")
        if "text" in st:
            hits = [b for b in texts(R1) if b["text"].replace("\n", " ").lower() == str(st["text"]).lower()]
            ok &= bool(hits)
            what.append(f"text '{st['text']}' {'present' if hits else 'missing'}")
        if "font" in st or "font_style" in st:
            diff = [b for a, b in changed if a["style"].get("font") != b["style"].get("font")]
            ok &= bool(diff)
            what.append(f"font -> {diff[0]['style']['font'].split(':')[-1] if diff else 'unchanged'}")
        if "position" in st:
            moved = [(a, b) for a, b in changed if abs(a["position"][1] - b["position"][1]) > 0.02]
            ok &= bool(moved)
            what.append(f"{len(moved)} text(s) moved")
        if (op.get("mul") or {}).get("size"):
            f = op["mul"]["size"]
            sized = [(a, b) for a, b in changed if (b["style"]["size"] > a["style"]["size"]) == (f > 1) and b["style"]["size"] != a["style"]["size"]]
            ok &= bool(sized)
            what.append(f"{len(sized)} text(s) resized")
        if "start" in st or "shift" in st:
            moved_t = [(a, b) for a, b in changed if abs(a["window"][0] - b["window"][0]) > 0.2]
            ok &= bool(moved_t)
            starts = ", ".join(f"{b['window'][0]:.1f} s" for _, b in moved_t[:3])
            what.append(f"{len(moved_t)} text(s) now start at {starts}" if moved_t else "timing unchanged")
        if (op.get("mul") or {}).get("duration"):
            longer = [(a, b) for a, b in changed if (b["window"][1] - b["window"][0]) != (a["window"][1] - a["window"][0])]
            ok &= bool(longer)
            what.append(f"{len(longer)} text(s) on screen {'longer' if op['mul']['duration'] > 1 else 'shorter'}")
        return ok, "; ".join(what) or "text changed"
    if k == "text_add":
        hit = [b for b in texts(R1) if b["text"].replace("\n", " ").lower() == op["text"].lower()]
        return bool(hit), (f"'{op['text']}' at {hit[0]['window'][0]:.1f} s" if hit else f"'{op['text']}' missing")
    if k == "fx":
        def n(R):
            kinds = {"shake": ("shake",), "zoom": ("zoom",)}.get(op["kind"])
            if kinds:
                es = [e for e in R["edits"] if e["type"] in kinds]
            else:
                es = [e for e in R["edits"] if e["type"] == "effect" and (op["kind"] == "effect" or op["kind"] in _kinds_R(e))]
            if op.get("at") is not None:
                es = [e for e in es if e["window"][0] - 0.4 <= float(op["at"]) <= e["window"][1] + 0.4]
            return es
        a, b = n(R0), n(R1)
        if op.get("item"):
            a = [e for e in R0["edits"] if e.get("item") == op["item"]]
            b = [e for e in R1["edits"] if e.get("item") == op["item"]]
        if op.get("remove") or op.get("thin"):
            return len(b) < len(a), f"{op['kind']}: {len(a)} -> {len(b)}"
        return True, f"{op['kind']}: {len(b)} edit(s) adjusted"
    if k == "fx_add":
        hit = [e for e in e1 if e.get("item") == op["item"]]
        return bool(hit), (f"{op.get('label')} at {hit[0]['window'][0]:.1f} s" if hit else f"{op.get('label')} missing")
    if k == "restore":
        return True, f"{op.get('role') or op['kind']} restored"
    if k == "push_add":
        hits = [e for e in e1 if e["type"] == "keyframes" and e.get("property") == "scale" and str(e.get("on", "")).startswith(str(op["shot"]))
                and max((pt[1] for pt in e.get("points") or [[0, 1]]), default=1) >= float(op.get("amount") or 1.12) - 1e-3]
        return bool(hits), f"push-in on {op['shot']}: {'yes' if hits else 'no'}"
    if k in ("pace_set", "shots_set", "unavoid_file"):
        return True, k.replace("_", " ")
    if k == "shot_beats":
        a = next((c for c in R0["clips"] if c["id"] == op["id"]), None)
        b = next((c for c in R1["clips"] if c["id"] == op["id"]), None)
        if not a or not b:
            return bool(b), f"shot {op['id']} {'present' if b else 'missing'}"
        da, db = a["end"] - a["start"], b["end"] - b["start"]
        return (db > da + 0.1) if op["mul"] > 1 else (db < da - 0.1), f"shot {op['id']}: {da:.1f} s -> {db:.1f} s"
    if k == "move_add":
        a = [e for e in e0 if e["type"] == op["kind"]]
        b = [e for e in e1 if e["type"] == op["kind"]]
        return len(b) > len(a), f"{op['kind']}: {len(a)} -> {len(b)}"
    if k == "transitions":
        t0 = [e for e in e0 if e["type"] == "transition"]
        t1 = [e for e in e1 if e["type"] == "transition"]
        if op.get("remove") or op.get("thin") or op.get("sections_only"):
            return len(t1) < len(t0), f"{len(t0)} -> {len(t1)} transitions"
        if op.get("every"):
            return len(t1) > len(t0), f"{len(t0)} -> {len(t1)} transitions"
        if op.get("family") or op.get("item"):
            i0 = Counter(e["item"] for e in t0)
            i1 = Counter(e["item"] for e in t1)
            return bool(t1) and i1 != i0, f"{', '.join(k2.split(':')[-1] for k2 in i0)} -> {', '.join(k2.split(':')[-1] for k2 in i1)}"
        return True, "transitions adjusted"
    if k == "look":
        f0 = [e for e in e0 if e["type"] == "filter"]
        f1 = [e for e in e1 if e["type"] == "filter"]
        if op.get("remove"):
            return len(f1) < len(f0), f"{len(f0)} -> {len(f1)} filters"
        if op.get("mul"):
            return True, "grade strength changed"
        i0 = {e["item"] for e in f0}
        i1 = {e["item"] for e in f1}
        return bool(i1) and i1 != i0, f"{', '.join(x.split(':')[-1] for x in i0) or 'none'} -> {', '.join(x.split(':')[-1] for x in i1)}"
    if k == "texture":
        def n(R):
            return [e for e in R["edits"] if e["type"] == "effect" and op["what"] in _kinds_R(e)]
        a, b = n(R0), n(R1)
        return (len(b) < len(a)) if op.get("remove") else (len(b) > len(a) or bool(b)), f"{op['what']}: {len(a)} -> {len(b)}"
    if k == "sfx_add":
        a = [e for e in e0 if e.get("sfx")]
        b = [e for e in e1 if e.get("sfx")]
        return len(b) > len(a), f"{len(a)} -> {len(b)} sound effects"
    if k in ("shot_move",):
        f = str(op.get("file") or "").lower()
        if op["to"] == "first":
            got = R1["clips"][0]["file"].lower() if R1["clips"] else ""
        elif op["to"] == "last":
            got = R1["clips"][-1]["file"].lower() if R1["clips"] else ""
        else:
            drop = (plan1 or {}).get("_rhythm", {}).get("drop")
            c = next((c for c in R1["clips"] if drop is not None and c["start"] - 0.05 <= drop < c["end"]), None)
            got = c["file"].lower() if c else ""
        return got == f, f"{op['to']}: {got or '?'}"
    if k == "less_of":
        f = op["file"].lower()
        t0 = sum(c["end"] - c["start"] for c in R0["clips"] if c["file"].lower() == f)
        t1 = sum(c["end"] - c["start"] for c in R1["clips"] if c["file"].lower() == f)
        return t1 < t0, f"{op['file']}: {t0:.1f} s -> {t1:.1f} s on screen"
    if k in ("shot_remove", "avoid_file"):
        f = str(op.get("file") or "").lower()
        n0 = sum(1 for c in R0["clips"] if c["file"].lower() == f)
        n1 = sum(1 for c in R1["clips"] if c["file"].lower() == f)
        return (n1 == 0) if k == "avoid_file" else (n1 < n0 or n0 == 0), f"{op.get('file')}: {n0} -> {n1} shot(s)"
    if k == "more_of":
        f = op["file"].lower()
        n0 = sum(1 for c in R0["clips"] if c["file"].lower() == f)
        n1 = sum(1 for c in R1["clips"] if c["file"].lower() == f)
        t0 = sum(c["end"] - c["start"] for c in R0["clips"] if c["file"].lower() == f)
        t1 = sum(c["end"] - c["start"] for c in R1["clips"] if c["file"].lower() == f)
        added = any(str(c["id"]).startswith("mo") and c["file"].lower() == f for c in R1["clips"])
        return n1 > n0 or t1 > t0 + 0.3 or added, f"{op['file']}: {n0} -> {n1} shot(s), {t0:.1f} -> {t1:.1f} s on screen"
    if k == "shot" and op.get("field") == "speed":
        sp1 = [pc["speed"] for c in R1["clips"] for pc in c.get("pieces") or []]
        sp0 = [pc["speed"] for c in R0["clips"] for pc in c.get("pieces") or []]
        if op["value"] in ("slow", "velocity"):
            return sum(1 for s in sp1 if s < 0.9) > sum(1 for s in sp0 if s < 0.9) or any(s < 0.9 for s in sp1), "slow motion present" if any(s < 0.9 for s in sp1) else "no slow motion"
        if op["value"] == "freeze":
            return any(c["kind"] == "image" or any(pc.get("kind") == "image" or pc.get("freeze") for pc in c.get("pieces") or []) for c in R1["clips"]) or len(R1["clips"]) != len(R0["clips"]), "freeze"
        return True, f"speed {op['value']}"
    if k == "swap_shots":
        a = [c["file"] for c in R0["clips"][:6]]
        b = [c["file"] for c in R1["clips"][:6]]
        return a != b, "order changed" if a != b else "order unchanged"
    if k == "section_beats":
        return abs(R1["end"] - R0["end"]) > 0.3 or len(R1["clips"]) != len(R0["clips"]) or True, f"{R0['end']:.1f} -> {R1['end']:.1f} s"
    if k == "clips":
        return True, "clips changed"
    if k == "recipe":
        return True, f"recipe {op.get('use')}"
    return True, k


def _kinds_R(e):
    words = item_words(e.get("item")) + " " + str(e.get("expect") or "").lower()
    out = set()
    for k, ws in KIND_WORDS.items():
        if any(w in words for w in ws):
            out.add(k)
    return out


def describe(op):
    k = op["op"]
    if k == "text":
        who = op.get("who") or {}
        tgt = f"'{who['match']}'" if who.get("match") else {"title": "the title", "label": "the labels", "cta": "the call to action",
                                                              "caption": "the captions", "all": "all text", "text": "the text"}.get(who.get("role"), "the text")
        if op.get("remove"):
            return f"remove {tgt}"
        bits = [f"{f} {v}" if f not in ("outline", "background", "font_asked") else f for f, v in (op.get("set") or {}).items() if f != "font_asked"]
        bits += [f"{'bigger' if v > 1 else 'smaller'}" if f == "size" else f"on screen {'longer' if v > 1 else 'shorter'}" for f, v in (op.get("mul") or {}).items()]
        return f"{tgt}: " + ", ".join(bits)
    if k == "audio":
        if op.get("remove"):
            return f"remove the {op['who']}"
        if op.get("mul"):
            return f"{op['who']} {'louder' if op['mul']['volume'] > 1 else 'quieter'}"
        return f"{op['who']} " + ", ".join(f"{f} {v}" for f, v in (op.get("set") or {}).items())
    if k == "length":
        return f"length {op['seconds']:.0f} s" if op.get("seconds") else f"{'longer' if op['mul'] > 1 else 'shorter'} (x{op['mul']:.2f})"
    if k == "pace":
        return ("faster cuts" if op["mul"] < 1 else "slower pacing") + (f" in the {'/'.join(op['sections'])}" if op.get("sections") else "")
    if k == "music":
        return f"music: {op.get('generate') or op.get('file') or ('faster' if op.get('bpm_mul', 1) > 1 else 'slower')}"
    if k == "canvas":
        return f"format {op['value']}"
    if k == "use_template":
        return f"recut on the template '{op.get('label') or op.get('name')}'"
    if k == "tpl_speed":
        v = op["value"]
        return {"normal": "every slot at normal speed", "ramp": "speed ramps on every slot"}.get(v, f"slow motion on every slot ({v}x)")
    if k == "look":
        return "remove the grade" if op.get("remove") else f"look: {op.get('name') or 'strength'}"
    if k == "transitions":
        return "no transitions" if op.get("remove") else f"transitions: {op.get('family') or ('more' if op.get('every') else 'adjusted')}"
    if k == "fx":
        return f"{'remove' if op.get('remove') else 'fewer' if op.get('thin') else 'adjust'} {op['kind']}" + \
            (f" in the {op['section']}" if op.get("section") else "") + (f" outside the {op['except_section']}" if op.get("except_section") else "")
    if k == "fx_add":
        return f"add {op.get('label')}"
    if k == "move_add":
        return f"add a {'zoom punch' if op['kind'] == 'zoom' else 'shake'}"
    if k == "push_add":
        return f"slow push-in on {op['shot']}"
    if k == "restore":
        return f"{op.get('role') or op['kind']} as before"
    if k == "text_add":
        return f"add text '{op['text']}'"
    return k.replace("_", " ")
