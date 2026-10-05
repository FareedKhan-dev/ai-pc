"""Unity (the most used game engine) by code: a playable 3D game project written as files Unity opens. C# scripts for the
player (move with WASD/arrows, jump with Space), a follow camera, spinning coins, a score, a timer and win/lose
screens, plus an editor script that builds the scene inside Unity itself the first time the project opens (or from
the 'AI PC > Rebuild scene' menu) from the game's settings in Assets/AIPC/game.json. When a Unity editor is installed
on this PC, the game is also built in batch mode (no window) to a Windows .exe and checked.

  "unity game: coin collector called 'Coin Run', 12 coins, red player, speed 7, 60 seconds"
  'make the unity player green'   'more coins: 20'   'build the unity game'
Checks without Unity: every script's class matches its file name (Unity's rule), braces balance, the settings file and
package list are valid JSON, and the builder knows every setting.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

NAME, LABEL = "unity", "Unity games: a playable 3D project by code, built in batch mode when Unity is installed"
EXAMPLES = ["unity game: coin collector called 'Coin Run', 12 coins, red player, speed 7, 60 seconds", "build the unity game"]
COLORS = {
    "red": "#E53935",
    "green": "#43A047",
    "blue": "#1E88E5",
    "yellow": "#FDD835",
    "orange": "#FB8C00",
    "purple": "#8E24AA",
    "pink": "#D81B60",
    "white": "#FAFAFA",
    "black": "#212121",
    "grey": "#9E9E9E",
    "gray": "#9E9E9E",
    "gold": "#FFC107",
    "brown": "#6D4C41",
    "cyan": "#00ACC1",
}
DEFAULT = {
    "title": "Coin Run",
    "coins": 10,
    "speed": 6.0,
    "jump": 5.0,
    "arena": 30.0,
    "seconds": 60,
    "player_color": "#1E88E5",
    "coin_color": "#FFC107",
    "ground_color": "#7CB342",
}
MODULES = [
    "ai",
    "animation",
    "audio",
    "imageconversion",
    "imgui",
    "jsonserialize",
    "particlesystem",
    "physics",
    "physics2d",
    "screencapture",
    "terrain",
    "terrainphysics",
    "ui",
    "uielements",
    "unitywebrequest",
    "video",
]

PLAYER = """using UnityEngine;

[RequireComponent(typeof(Rigidbody))]
public class PlayerController : MonoBehaviour
{
    public float speed = 6f;
    public float jumpForce = 5f;
    Rigidbody body;
    bool grounded;

    void Awake()
    {
        body = GetComponent<Rigidbody>();
    }

    void Update()
    {
        if (grounded && Input.GetButtonDown("Jump"))
        {
            body.AddForce(Vector3.up * jumpForce, ForceMode.VelocityChange);
            grounded = false;
        }
    }

    void FixedUpdate()
    {
        Vector3 move = new Vector3(Input.GetAxis("Horizontal"), 0f, Input.GetAxis("Vertical"));
        if (Camera.main != null)
        {
            Vector3 forward = Vector3.ProjectOnPlane(Camera.main.transform.forward, Vector3.up).normalized;
            Vector3 right = Vector3.ProjectOnPlane(Camera.main.transform.right, Vector3.up).normalized;
            move = forward * move.z + right * move.x;
        }
#if UNITY_6000_0_OR_NEWER
        Vector3 v = body.linearVelocity;
        body.linearVelocity = new Vector3(move.x * speed, v.y, move.z * speed);
#else
        Vector3 v = body.velocity;
        body.velocity = new Vector3(move.x * speed, v.y, move.z * speed);
#endif
    }

    void OnCollisionStay(Collision other)
    {
        foreach (ContactPoint c in other.contacts)
        {
            if (c.normal.y > 0.5f) grounded = true;
        }
    }
}
"""
CAMERA = """using UnityEngine;

public class CameraFollow : MonoBehaviour
{
    public Transform target;
    public Vector3 offset = new Vector3(0f, 8f, -10f);
    public float smooth = 5f;

    void LateUpdate()
    {
        if (target == null) return;
        transform.position = Vector3.Lerp(transform.position, target.position + offset, smooth * Time.deltaTime);
        transform.LookAt(target.position + Vector3.up * 0.5f);
    }
}
"""
COIN = """using UnityEngine;

public class Coin : MonoBehaviour
{
    public float spin = 120f;

    void Update()
    {
        transform.Rotate(Vector3.up, spin * Time.deltaTime, Space.World);
    }

    void OnTriggerEnter(Collider other)
    {
        if (!other.CompareTag("Player")) return;
        if (GameManager.Instance != null) GameManager.Instance.Collect();
        Destroy(gameObject);
    }
}
"""
MANAGER = """using UnityEngine;
using UnityEngine.SceneManagement;

public class GameManager : MonoBehaviour
{
    public static GameManager Instance;
    public string title = "Coin Run";
    public int totalCoins = 10;
    public float timeLimit = 60f;
    int score;
    float timeLeft;
    bool over;
    string message = "";

    void Awake()
    {
        Instance = this;
        timeLeft = timeLimit;
    }

    void Update()
    {
        if (over)
        {
            if (Input.GetKeyDown(KeyCode.R)) SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
            return;
        }
        if (timeLimit > 0f)
        {
            timeLeft -= Time.deltaTime;
            if (timeLeft <= 0f)
            {
                timeLeft = 0f;
                End("Time's up! Press R to try again.");
            }
        }
    }

    public void Collect()
    {
        if (over) return;
        score++;
        if (score >= totalCoins) End("You win! Press R to play again.");
    }

    void End(string text)
    {
        over = true;
        message = text;
    }

    void OnGUI()
    {
        GUIStyle head = new GUIStyle(GUI.skin.label) { fontSize = 28, fontStyle = FontStyle.Bold };
        GUI.Label(new Rect(20, 15, 800, 40), title, head);
        GUIStyle info = new GUIStyle(GUI.skin.label) { fontSize = 22 };
        string time = timeLimit > 0f ? "    Time: " + Mathf.CeilToInt(timeLeft) : "";
        GUI.Label(new Rect(20, 55, 800, 30), "Coins: " + score + " / " + totalCoins + time, info);
        if (over)
        {
            GUIStyle big = new GUIStyle(GUI.skin.label) { fontSize = 40, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter };
            GUI.Label(new Rect(0, Screen.height / 2f - 40f, Screen.width, 80), message, big);
        }
    }
}
"""
BUILDER = """using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AIPC
{
    [InitializeOnLoad]
    public static class Builder
    {
        const string ScenePath = "Assets/Scenes/Main.unity";
        const string ConfigPath = "Assets/AIPC/game.json";

        [System.Serializable]
        class Config
        {
            public string title = "Coin Run";
            public int coins = 10;
            public float speed = 6f;
            public float jump = 5f;
            public float arena = 30f;
            public int seconds = 60;
            public string player_color = "#1E88E5";
            public string coin_color = "#FFC107";
            public string ground_color = "#7CB342";
        }

        static Builder()
        {
            if (!File.Exists(ScenePath)) EditorApplication.delayCall += BuildScene;
        }

        [MenuItem("AI PC/Rebuild scene")]
        public static void BuildScene()
        {
            Config cfg = JsonUtility.FromJson<Config>(File.ReadAllText(ConfigPath));
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            Directory.CreateDirectory("Assets/AIPC/Materials");

            var light = new GameObject("Directional Light").AddComponent<Light>();
            light.type = LightType.Directional;
            light.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Ground";
            ground.transform.localScale = new Vector3(cfg.arena / 10f, 1f, cfg.arena / 10f);
            Paint(ground, cfg.ground_color, "Ground");
            float half = cfg.arena / 2f;
            Wall("Wall North", new Vector3(0f, 1f, half), new Vector3(cfg.arena, 2f, 0.5f));
            Wall("Wall South", new Vector3(0f, 1f, -half), new Vector3(cfg.arena, 2f, 0.5f));
            Wall("Wall East", new Vector3(half, 1f, 0f), new Vector3(0.5f, 2f, cfg.arena));
            Wall("Wall West", new Vector3(-half, 1f, 0f), new Vector3(0.5f, 2f, cfg.arena));

            var player = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            player.name = "Player";
            player.tag = "Player";
            player.transform.position = new Vector3(0f, 0.5f, 0f);
            player.AddComponent<Rigidbody>();
            var control = player.AddComponent<PlayerController>();
            control.speed = cfg.speed;
            control.jumpForce = cfg.jump;
            Paint(player, cfg.player_color, "Player");

            var cam = new GameObject("Main Camera");
            cam.tag = "MainCamera";
            cam.AddComponent<Camera>();
            cam.AddComponent<AudioListener>();
            cam.transform.position = new Vector3(0f, 8f, -10f);
            cam.AddComponent<CameraFollow>().target = player.transform;

            for (int i = 0; i < cfg.coins; i++)
            {
                float a = i * Mathf.PI * 2f / Mathf.Max(1, cfg.coins);
                float r = cfg.arena * (i % 2 == 0 ? 0.35f : 0.2f);
                var coin = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                coin.name = "Coin " + (i + 1);
                coin.transform.position = new Vector3(Mathf.Cos(a) * r, 1f, Mathf.Sin(a) * r);
                coin.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
                coin.transform.localScale = new Vector3(0.8f, 0.08f, 0.8f);
                coin.GetComponent<Collider>().isTrigger = true;
                coin.AddComponent<Coin>();
                Paint(coin, cfg.coin_color, "Coin");
            }

            var manager = new GameObject("Game Manager").AddComponent<GameManager>();
            manager.title = cfg.title;
            manager.totalCoins = cfg.coins;
            manager.timeLimit = cfg.seconds;

            Directory.CreateDirectory("Assets/Scenes");
            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            PlayerSettings.productName = cfg.title;
            AssetDatabase.SaveAssets();
            Debug.Log("AI PC: scene built with " + cfg.coins + " coins");
        }

        static void Wall(string name, Vector3 at, Vector3 size)
        {
            var wall = GameObject.CreatePrimitive(PrimitiveType.Cube);
            wall.name = name;
            wall.transform.position = at;
            wall.transform.localScale = size;
            Paint(wall, "#8D6E63", "Wall");
        }

        static void Paint(GameObject go, string hex, string name)
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null) shader = Shader.Find("Standard");
            var mat = new Material(shader);
            Color c;
            if (ColorUtility.TryParseHtmlString(hex, out c)) mat.color = c;
            string path = "Assets/AIPC/Materials/" + name + ".mat";
            AssetDatabase.DeleteAsset(path);
            AssetDatabase.CreateAsset(mat, path);
            go.GetComponent<Renderer>().sharedMaterial = mat;
        }

        public static void BuildWindows()
        {
            BuildScene();
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = "Builds/Windows/Game.exe",
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.None
            };
            var report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded) EditorApplication.Exit(1);
        }
    }
}
"""
SCRIPTS = {
    "Assets/Scripts/PlayerController.cs": PLAYER,
    "Assets/Scripts/CameraFollow.cs": CAMERA,
    "Assets/Scripts/Coin.cs": COIN,
    "Assets/Scripts/GameManager.cs": MANAGER,
    "Assets/Editor/AIPCBuilder.cs": BUILDER,
}


def editor():
    """A Unity editor on this PC (Unity Hub's default folders), newest first, or None."""
    roots = [Path(r"C:\Program Files\Unity\Hub\Editor"), Path.home() / "AppData" / "Local" / "Unity" / "Hub" / "Editor"]
    found = sorted((p for r in roots if r.exists() for p in r.glob("*/Editor/Unity.exe")), reverse=True)
    return found[0] if found else None


def write(folder, cfg):
    folder = Path(folder)
    for rel, code in SCRIPTS.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, encoding="utf-8", newline="\n")
    (folder / "Assets" / "AIPC").mkdir(parents=True, exist_ok=True)
    (folder / "Assets" / "AIPC" / "game.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    scene = folder / "Assets" / "Scenes" / "Main.unity"
    if scene.exists():  # the builder makes it again from the new settings when the project opens
        scene.unlink()
        Path(str(scene) + ".meta").unlink(missing_ok=True)
    (folder / "Packages").mkdir(exist_ok=True)
    (folder / "Packages" / "manifest.json").write_text(
        json.dumps({"dependencies": {f"com.unity.modules.{m}": "1.0.0" for m in MODULES}}, indent=2), encoding="utf-8"
    )
    (folder / "ProjectSettings").mkdir(exist_ok=True)
    pv = folder / "ProjectSettings" / "ProjectVersion.txt"
    if not pv.exists():
        pv.write_text("m_EditorVersion: 6000.0.40f1\n", encoding="utf-8")
    (folder / "README.txt").write_text(
        f"{cfg['title']}: a Unity project made by AI PC.\n\nOpen it in Unity Hub (Add > Add project from disk > this folder). The scene is built "
        "the first time it opens (menu: AI PC > Rebuild scene to build it again). Press Play: WASD or arrows to move, Space to jump, R to restart.\n",
        encoding="utf-8",
    )
    return folder


def check(folder):
    folder = Path(folder)
    out = []
    ok = True
    for rel, _ in SCRIPTS.items():
        code = (folder / rel).read_text(encoding="utf-8")
        cls = re.search(r"\b(?:public\s+)?(?:static\s+)?class\s+(\w+)", code).group(1)
        bare = re.sub(r'"(?:[^"\\]|\\.)*"|//[^\n]*', "", code)
        if code.count("MonoBehaviour") and cls != Path(rel).stem:
            ok = False
        if bare.count("{") != bare.count("}") or bare.count("(") != bare.count(")"):
            ok = False
    out.append(("every script's class matches its file and its braces balance", ok))
    cfg = json.loads((folder / "Assets" / "AIPC" / "game.json").read_text(encoding="utf-8"))
    fields = set(re.findall(r"public (?:string|int|float) (\w+) =", BUILDER))
    out.append(("the builder knows every setting", set(cfg) <= fields))
    json.loads((folder / "Packages" / "manifest.json").read_text(encoding="utf-8"))
    out.append(("the package list is valid", True))
    return out


def build(folder, timeout=1800):
    exe = editor()
    if not exe:
        return None
    log = Path(folder) / "Logs" / "aipc_build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [
            str(exe),
            "-batchmode",
            "-nographics",
            "-quit",
            "-projectPath",
            str(folder),
            "-executeMethod",
            "AIPC.Builder.BuildWindows",
            "-logFile",
            str(log),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    game = Path(folder) / "Builds" / "Windows" / "Game.exe"
    return {"ok": r.returncode == 0 and game.exists(), "exe": game, "log": log}


def read(text, cfg=None):
    cfg = dict(cfg or DEFAULT)
    c = text.lower()
    m = re.search(r"\b(?:called|named|title[d]?)\s+['\"]([^'\"]+)['\"]", text, re.I)
    if m:
        cfg["title"] = m.group(1)
    m = re.search(r"\b(\d{1,3})\s+coins?\b|\bcoins?\s*(?:to|:|=)?\s*(\d{1,3})\b", c)
    if m:
        cfg["coins"] = max(1, min(200, int(m.group(1) or m.group(2))))
    m = re.search(r"\bspeed\s*(?:to|:|=|of)?\s*(\d+(?:\.\d+)?)", c)
    if m:
        cfg["speed"] = float(m.group(1))
    m = re.search(r"\bjump\s*(?:to|:|=|of)?\s*(\d+(?:\.\d+)?)", c)
    if m:
        cfg["jump"] = float(m.group(1))
    m = re.search(r"\b(\d{1,4})\s*(?:seconds?|secs?|s)\b", c)
    if m:
        cfg["seconds"] = int(m.group(1))
    if re.search(r"\bno time limit\b|\bno timer\b", c):
        cfg["seconds"] = 0
    m = re.search(r"\b(?:arena|ground|level|map)\s*(?:size)?\s*(?:to|:|=|of)?\s*(\d{1,3})\b", c)
    if m:
        cfg["arena"] = float(max(10, min(200, int(m.group(1)))))
    for part in ("player", "coins?", "ground"):
        m = re.search(r"\b(" + "|".join(COLORS) + r")\s+" + part + r"\b|\b" + part + r"\s+(?:to\s+|is\s+|in\s+)?(" + "|".join(COLORS) + r")\b", c)
        if m:
            key = {"player": "player_color", "coins?": "coin_color", "ground": "ground_color"}[part]
            cfg[key] = COLORS[m.group(1) or m.group(2)]
    return cfg


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bunity\b", c):
        return None
    if re.search(r"\bbuild\b.*\b(?:game|exe|project)\b|\bmake (?:the )?exe\b", c) and not re.search(r"\bgame\s*:", c):
        return {"op": "build"}
    m = re.search(r"\bunity\s+game\s*:\s*(.+)$|\bmake\s+(?:a\s+)?unity\s+game\b(.*)$", text, re.I | re.S)
    if m:
        return {"op": "make", "words": (m.group(1) or m.group(2) or "")}
    if (ctx.get("memo") or {}).get("unity"):
        return {"op": "edit", "words": text}
    return None


def run(op, ctx):
    memo = ctx.setdefault("memo", {})
    last = memo.get("unity")
    if op["op"] == "build":
        if not last:
            return "Make a Unity game first, e.g. 'unity game: coin collector, 12 coins'."
        r = build(last["folder"])
        if r is None:
            return (
                f"No Unity editor on this PC, so it can't be built here. Open {last['folder']} in Unity Hub (Add project from disk); the scene builds itself, "
                "then File > Build Profiles > Build. (Unity Personal is free; Unity Hub installs the editor.)"
            )
        return f"Built {r['exe']} (checked: the .exe exists)." if r["ok"] else f"The Unity build failed: see {r['log']}."
    cfg = read(op["words"], last["cfg"] if (last and op["op"] == "edit") else None)
    folder = Path(last["folder"]) if (last and op["op"] == "edit") else Path(ctx["out"]) / "unity" / re.sub(r"[^\w-]+", "_", cfg["title"])
    if op["op"] == "make" and folder.exists():
        shutil.rmtree(folder / "Assets" / "Scenes", ignore_errors=True)
    write(folder, cfg)
    memo["unity"] = {"folder": str(folder), "cfg": cfg}
    bad = [w for w, ok in check(folder) if not ok]
    what = f"'{cfg['title']}': {cfg['coins']} coins in a {cfg['arena']:g} m arena, player speed {cfg['speed']:g}, jump {cfg['jump']:g}, " + (
        f"{cfg['seconds']} s to collect them" if cfg["seconds"] else "no time limit"
    )
    return (
        f"Unity project {'updated' if op['op'] == 'edit' else 'made'}: {folder} ({what}). "
        + ("Checked: scripts, settings and packages. " if not bad else "NOT right: " + ", ".join(bad) + ". ")
        + (
            "Unity is on this PC: say 'build the unity game' for the .exe."
            if editor()
            else "Open it in Unity Hub (Add project from disk); the scene builds itself; press Play (WASD/arrows, Space to jump)."
        )
    )
