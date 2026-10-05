"""Godot (the most used free game engine; 4.7.2 in tools/godot, checked and self-contained) by code: a 2D platformer project
written as files (the level, player, coins, score and win screen are built by GDScript from the game's settings in
game.json), then really played here with no window: Godot runs the game headless, the player falls onto the first
platform, Right is held and Jump pressed, and the game reports what happened. Opened in the Godot editor on request.

  "godot game: platformer called 'Jump Hero', 8 coins, green player, jump 600"   'make the godot player red'   'open the godot game'
"""
import json
import re
import subprocess
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "godot", "Godot games: a 2D platformer by code, played headless to check it"
EXAMPLES = ["godot game: platformer called 'Jump Hero', 8 coins, green player, jump 600", "open the godot game"]
GODOT = ROOT / "tools" / "godot" / "Godot_v4.7.2-stable_win64_console.exe"
EDITOR = ROOT / "tools" / "godot" / "Godot_v4.7.2-stable_win64.exe"
COLORS = {"red": "#e53935", "green": "#43a047", "blue": "#1e88e5", "yellow": "#fdd835", "orange": "#fb8c00", "purple": "#8e24aa", "pink": "#d81b60",
          "white": "#fafafa", "black": "#212121", "gold": "#ffc107", "cyan": "#00acc1", "brown": "#6d4c41"}
DEFAULT = {"title": "Jump Hero", "coins": 6, "speed": 300.0, "jump": 560.0, "player_color": "#1e88e5", "coin_color": "#ffc107", "ground_color": "#6d4c41",
           "sky": "#87ceeb"}

PROJECT = """; Engine configuration file (made by AI PC).
config_version=5

[application]
config/name="{title}"
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.7")

[display]
window/size/viewport_width=1280
window/size/viewport_height=720
"""
SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1_main"]

[node name="Main" type="Node2D"]
script = ExtResource("1_main")
"""
MAIN = """extends Node2D

var config := {}
var score := 0
var total := 0
var player
var label: Label
var won := false

func _ready() -> void:
	config = JSON.parse_string(FileAccess.get_file_as_string("res://game.json"))
	RenderingServer.set_default_clear_color(Color(config.sky))
	for p in config.platforms:
		_make_platform(Vector2(p[0], p[1]), p[2])
	for c in config.coin_spots:
		_make_coin(Vector2(c[0], c[1]))
	total = config.coin_spots.size()
	_make_player()
	var ui := CanvasLayer.new()
	add_child(ui)
	label = Label.new()
	label.add_theme_font_size_override("font_size", 28)
	label.position = Vector2(20, 12)
	ui.add_child(label)
	_update()

func _make_player() -> void:
	player = CharacterBody2D.new()
	player.name = "Player"
	player.set_script(load("res://player.gd"))
	player.set("speed", config.speed)
	player.set("jump", config.jump)
	player.position = Vector2(config.start[0], config.start[1])
	var shape := CollisionShape2D.new()
	var rect := RectangleShape2D.new()
	rect.size = Vector2(32, 48)
	shape.shape = rect
	player.add_child(shape)
	var body := ColorRect.new()
	body.size = Vector2(32, 48)
	body.position = Vector2(-16, -24)
	body.color = Color(config.player_color)
	player.add_child(body)
	var cam := Camera2D.new()
	player.add_child(cam)
	add_child(player)

func _make_platform(at: Vector2, width: float) -> void:
	var ground := StaticBody2D.new()
	ground.position = at
	var shape := CollisionShape2D.new()
	var rect := RectangleShape2D.new()
	rect.size = Vector2(width, 24)
	shape.shape = rect
	ground.add_child(shape)
	var look := ColorRect.new()
	look.size = Vector2(width, 24)
	look.position = Vector2(-width / 2.0, -12)
	look.color = Color(config.ground_color)
	ground.add_child(look)
	add_child(ground)

func _make_coin(at: Vector2) -> void:
	var coin := Area2D.new()
	coin.position = at
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 12
	shape.shape = circle
	coin.add_child(shape)
	var dot := ColorRect.new()
	dot.size = Vector2(24, 24)
	dot.position = Vector2(-12, -12)
	dot.color = Color(config.coin_color)
	coin.add_child(dot)
	coin.body_entered.connect(_on_coin.bind(coin))
	add_child(coin)

func _on_coin(body: Node, coin: Area2D) -> void:
	if body != player or not is_instance_valid(coin):
		return
	coin.queue_free()
	score += 1
	if score >= total:
		won = true
	_update()

func fell() -> void:
	player.position = Vector2(config.start[0], config.start[1])
	player.velocity = Vector2.ZERO

func _update() -> void:
	label.text = "%s    Coins: %d / %d" % [config.title, score, total] + ("    You win!" if won else "")
"""
PLAYER = """extends CharacterBody2D

var speed := 300.0
var jump := 560.0
var gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += gravity * delta
	if Input.is_action_just_pressed("ui_accept") and is_on_floor():
		velocity.y = -jump
	velocity.x = Input.get_axis("ui_left", "ui_right") * speed
	move_and_slide()
	if position.y > 2000:
		get_parent().fell()
"""
CHECK = """extends SceneTree

var main
var frames := 0
var report := {}

func _initialize() -> void:
	main = load("res://main.tscn").instantiate()
	root.add_child(main)

func _physics_process(_delta: float) -> bool:
	frames += 1
	var p = main.get_node("Player")
	if frames == 2:
		report["start"] = [p.position.x, p.position.y]
	if frames == 90:
		report["landed"] = p.is_on_floor()
		report["rest"] = [p.position.x, p.position.y]
		Input.action_press("ui_right")
	if frames == 140:
		Input.action_release("ui_right")
		report["moved"] = [p.position.x, p.position.y]
	if frames == 150:
		Input.action_press("ui_accept")
	if frames == 151:
		Input.action_release("ui_accept")
	if frames == 165:
		report["jump_y"] = p.position.y
	if frames >= 180:
		report["coins"] = main.total
		report["nodes"] = main.get_child_count()
		print("AIPC_REPORT " + JSON.stringify(report))
		return true
	return false
"""


def level(cfg):
    """Platforms rising left to right ([x, y, width]) and coins above them; the player starts over the first."""
    n = max(3, min(12, cfg["coins"]))
    plats = [[400, 600, 800]]
    for i in range(1, n):
        plats.append([400 + i * 260, 600 - (i % 3) * 90, 180])
    coins = [[p[0], p[1] - 70] for p in plats[1:]][:cfg["coins"]]
    while len(coins) < cfg["coins"]:
        coins.append([200 + len(coins) * 60, 520])
    return dict(cfg, platforms=plats, coin_spots=coins, start=[200, 450])


def write(folder, cfg):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    full = level(cfg)
    for name, text in (("project.godot", PROJECT.format(title=cfg["title"].replace('"', "'"))), ("main.tscn", SCENE), ("main.gd", MAIN), ("player.gd", PLAYER),
                       ("check.gd", CHECK), ("game.json", json.dumps(full, indent=2))):
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    return full


def play(folder, timeout=180):
    """Run the game headless and read its report: (report or None, any script errors)."""
    r = subprocess.run([str(GODOT), "--headless", "--path", str(folder), "--script", "res://check.gd"], capture_output=True, text=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = (r.stdout or "") + (r.stderr or "")
    errors = [ln for ln in text.splitlines() if re.search(r"SCRIPT ERROR|Parse Error|ERROR:", ln)]
    m = re.search(r"AIPC_REPORT (\{.*\})", text)
    return (json.loads(m.group(1)) if m else None), errors


def check(rep, errors, cfg):
    if not rep:
        return [("the game ran headless and reported", False)]
    return [("the game ran headless with no script errors", not errors), ("the player fell onto the first platform", bool(rep.get("landed"))),
            ("holding Right moved the player right", rep["moved"][0] > rep["rest"][0] + 50),
            ("Jump lifted the player", rep["jump_y"] < rep["moved"][1] - 20), ("every coin is in the level", rep["coins"] == cfg["coins"])]


def read(text, cfg=None):
    cfg = dict(cfg or DEFAULT)
    c = text.lower()
    m = re.search(r"\b(?:called|named|title[d]?)\s+['\"]([^'\"]+)['\"]", text, re.I)
    if m:
        cfg["title"] = m.group(1)
    m = re.search(r"\b(\d{1,2})\s+coins?\b|\bcoins?\s*(?:to|:|=)?\s*(\d{1,2})\b", c)
    if m:
        cfg["coins"] = max(1, min(30, int(m.group(1) or m.group(2))))
    for k in ("speed", "jump"):
        m = re.search(rf"\b{k}\s*(?:to|:|=|of)?\s*(\d+(?:\.\d+)?)", c)
        if m:
            cfg[k] = float(m.group(1))
    for part, key in (("player", "player_color"), ("coins?", "coin_color"), ("ground|platforms?", "ground_color")):
        m = re.search(r"\b(" + "|".join(COLORS) + r")\s+(?:" + part + r")\b|\b(?:" + part + r")\s+(?:to\s+|is\s+)?(" + "|".join(COLORS) + r")\b", c)
        if m:
            cfg[key] = COLORS[m.group(1) or m.group(2)]
    return cfg


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bgodot\b", c):
        return None
    if re.search(r"\bopen\b", c):
        return {"op": "open"}
    m = re.search(r"\bgodot\s+game\s*:\s*(.+)$|\bmake\s+(?:a\s+)?godot\s+game\b(.*)$", text, re.I | re.S)
    if m:
        return {"op": "make", "words": m.group(1) or m.group(2) or ""}
    if (ctx.get("memo") or {}).get("godot"):
        return {"op": "edit", "words": text}
    return None


def run(op, ctx):
    memo = ctx.setdefault("memo", {})
    last = memo.get("godot")
    if op["op"] == "open":
        if not last:
            return "Make a Godot game first, e.g. 'godot game: platformer called Jump Hero, 8 coins'."
        subprocess.Popen([str(EDITOR), "--editor", "--path", last["folder"]], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        return f"Opening {last['folder']} in the Godot editor (press F5 to play)."
    cfg = read(op["words"], last["cfg"] if (last and op["op"] == "edit") else None)
    folder = Path(last["folder"]) if (last and op["op"] == "edit") else Path(ctx["out"]) / "godot" / re.sub(r"[^\w-]+", "_", cfg["title"])
    write(folder, cfg)
    memo["godot"] = {"folder": str(folder), "cfg": cfg}
    rep, errors = play(folder)
    checks = check(rep, errors, cfg)
    bad = [w for w, ok in checks if not ok]
    return (f"Godot game {'updated' if op['op'] == 'edit' else 'made'}: {folder} ('{cfg['title']}', {cfg['coins']} coins, speed {cfg['speed']:g}, jump {cfg['jump']:g}). " +
            ("Played headless and checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) +
             (f" ({errors[0][:200]})" if errors else "") + ".") + " Say 'open the godot game' to see it in the Godot editor (F5 plays).")
