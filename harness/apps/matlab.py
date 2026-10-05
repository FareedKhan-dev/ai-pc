"""MATLAB by .m scripts (run here by GNU Octave 11.3, which runs MATLAB code; tools/octave, GPG-checked): plots of functions,
linear equations solved, the frequencies in a signal found by FFT, an RC circuit charging (ode45), matrix inverse,
eigenvalues and determinant, or a .m file given. Each script is plain MATLAB (it runs in MATLAB too), is really run
headless, saves its figure as PNG, and every number it prints is checked against the same sum done separately in Python.

  'matlab plot sin(x) and cos(x) from 0 to 2*pi'   'matlab solve 2x + 3y = 13, x - y = 1'   'matlab fft of 50 Hz and 120 Hz'
  'matlab rc circuit R 1k C 100uF 5 V'   'matlab eigenvalues of [2 1; 1 3]'   'matlab run model.m'
"""
import os
import re
import subprocess
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "matlab", "MATLAB: .m scripts (plots, equations, FFT, RC circuits, matrices) run headless by Octave"
EXAMPLES = ["matlab plot sin(x) and cos(x) from 0 to 2*pi", "matlab solve 2x + 3y = 13, x - y = 1", "matlab fft of 50 Hz and 120 Hz",
            "matlab rc circuit R 1k C 100uF 5 V", "matlab eigenvalues of [2 1; 1 3]"]
HOME = ROOT / "tools" / "octave"
FUNCS = {"sin", "cos", "tan", "exp", "log", "sqrt", "abs", "sinh", "cosh", "tanh", "asin", "acos", "atan", "log10"}
UNITS = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "M": 1e6}


def octave():
    hits = sorted(HOME.rglob("octave-cli.exe")) if HOME.exists() else []
    return next((h for h in hits if "mingw64" in str(h) or "ucrt64" in str(h)), hits[0] if hits else None)


def safe_expr(e):
    """A function of x made only of numbers, x, pi, + - * / ^ ( ) and known functions; None if anything else."""
    e = e.strip().replace("**", "^")
    if not re.fullmatch(r"[0-9x.+\-*/^() a-z]+", e):
        return None
    for w in re.findall(r"[a-z]+", e):
        if w not in FUNCS | {"x", "pi"}:
            return None
    return e


def to_matlab(e):
    """Element-wise operators so the function works on a whole vector."""
    return re.sub(r"(?<!\.)([*/^])", r".\1", e)


def to_python(e):
    py = e.replace("^", "**")
    py = re.sub(r"\b(" + "|".join(FUNCS) + r")\(", r"np.\1(", py)
    return re.sub(r"\bpi\b", "np.pi", py)


def linear_system(text):
    """'2x + 3y = 13, x - y = 1' -> (variables, A, b)."""
    eqs = [e for e in re.split(r"\s*[,;]\s*|\s+and\s+", text) if "=" in e]
    names = sorted(set(re.findall(r"[a-z]", "".join(e.split("=")[0] for e in eqs))))
    A, b = [], []
    for e in eqs:
        left, right = e.split("=", 1)
        row = [0.0] * len(names)
        for sign, coef, var in re.findall(r"([+-]?)\s*(\d*\.?\d*)\s*\*?\s*([a-z])", left.replace(" ", "")):
            row[names.index(var)] += (-1 if sign == "-" else 1) * (float(coef) if coef else 1.0)
        A.append(row)
        b.append(float(right.strip()))
    return names, A, b


def value(s):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(meg|[pnuµmkM])?\s*(?:ohms?|Ω|f|farads?|v|volts?)?", s.strip(), re.I)
    if not m:
        return None
    unit = m.group(2)
    return float(m.group(1)) * (UNITS.get(unit, UNITS.get(unit.lower() if unit else "", 1)) if unit else 1)


def matrix(text):
    m = re.search(r"\[([-\d.\s,;]+)\]", text)
    if not m:
        return None
    rows = [[float(v) for v in re.split(r"[\s,]+", r.strip()) if v] for r in m.group(1).split(";")]
    return rows if rows and all(len(r) == len(rows[0]) for r in rows) else None


def script(op):
    k = op["kind"]
    head = f"% Made by AI PC: {op['title']}. Runs in MATLAB and in GNU Octave.\n"
    if k == "plot":
        lines = [f"x = linspace({op['a']}, {op['b']}, 500);"]
        for i, e in enumerate(op["exprs"], 1):
            lines.append(f"y{i} = {to_matlab(e)};")
        lines += ["f = figure('visible', 'off');"]
        for i in range(1, len(op["exprs"]) + 1):
            lines.append(f"plot(x, y{i}, 'LineWidth', 1.5); hold on;")
        lines += ["grid on; xlabel('x'); ylabel('y');", f"title('{', '.join(op['exprs'])}');",
                  "legend(" + ", ".join(f"'{e}'" for e in op["exprs"]) + ", 'Location', 'best');", "print(f, '-dpng', '-r120', 'figure.png');"]
        lines += [f"fprintf('AIPC y{i} %.6f %.6f\\n', max(y{i}), min(y{i}));" for i in range(1, len(op["exprs"]) + 1)]
    elif k == "solve":
        A = "; ".join(" ".join(f"{v:g}" for v in r) for r in op["A"])
        lines = [f"A = [{A}];", f"b = [{'; '.join(f'{v:g}' for v in op['b'])}];", "x = A \\ b;"]
        lines += [f"fprintf('{n} = %.6f\\n', x({i + 1}));" for i, n in enumerate(op["names"])]
        lines += ["fprintf('AIPC %.10f\\n', x);"]
    elif k == "fft":
        lines = ["fs = 1000; L = 1000; t = (0:L-1) / fs;",
                 "s = " + " + ".join(f"{1 if i == 0 else 0.7:g}*sin(2*pi*{f:g}*t)" for i, f in enumerate(op["freqs"])) + ";",
                 "Y = fft(s); P2 = abs(Y / L); P1 = P2(1:L/2+1); P1(2:end-1) = 2 * P1(2:end-1);", "fr = fs * (0:(L/2)) / L;",
                 "f = figure('visible', 'off'); plot(fr, P1, 'LineWidth', 1.2); grid on;",
                 "xlabel('Frequency (Hz)'); ylabel('|P1(f)|'); title('Single-sided amplitude spectrum');", "print(f, '-dpng', '-r120', 'figure.png');",
                 "[~, idx] = sort(P1, 'descend');", f"top = sort(fr(idx(1:{len(op['freqs'])})));",
                 "fprintf('Peaks at %g Hz\\n', top);", "fprintf('AIPC %g\\n', top);"]
    elif k == "rc":
        lines = [f"R = {op['R']:g}; C = {op['C']:g}; V = {op['V']:g};", "tau = R * C;",
                 "[t, v] = ode45(@(t, v) (V - v) / tau, [0 5*tau], 0);",
                 "f = figure('visible', 'off'); plot(t, v, 'LineWidth', 1.5); grid on;",
                 "xlabel('Time (s)'); ylabel('Capacitor voltage (V)'); title(sprintf('RC charging, tau = %g s', tau));",
                 "print(f, '-dpng', '-r120', 'figure.png');", "vt = interp1(t, v, tau);",
                 "fprintf('tau = %g s; after one tau the capacitor is at %.3f V (%.1f%%); after 5 tau %.3f V\\n', tau, vt, 100*vt/V, v(end));",
                 "fprintf('AIPC %.10f %.10f %.10f\\n', tau, vt, v(end));"]
    elif k == "matrix":
        M = "; ".join(" ".join(f"{v:g}" for v in r) for r in op["M"])
        what = {"inverse": "inv(M)", "eig": "eig(M)", "det": "det(M)"}[op["what"]]
        lines = [f"M = [{M}];", f"R = {what};", "disp(R);", "fprintf('AIPC %.10f\\n', R);"]
    else:  # a .m file given: run it as it is
        return None
    return head + "\n".join(lines) + "\n"


def fonts_conf(exe, home):
    """Octave's fontconfig settings with the font cache kept inside the project (not in AppData)."""
    etc = exe.parent.parent / "etc" / "fonts"
    conf = home / "fonts.conf"
    text = (etc / "fonts.conf").read_text(encoding="utf-8")
    text = re.sub(r"\s*<cachedir[^>]*>[^<]*</cachedir>", "", text)
    text = text.replace('<include ignore_missing="yes">conf.d</include>', f'<include ignore_missing="yes">{(etc / "conf.d").as_posix()}</include>'
                        f'\n\t<cachedir>{(home / "fontcache").as_posix()}</cachedir>')
    if not conf.exists() or conf.read_text(encoding="utf-8") != text:
        conf.write_text(text, encoding="utf-8")
    return conf


def run_octave(folder, name):
    exe = octave()
    home = HOME / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home), FONTCONFIG_FILE=str(fonts_conf(exe, home)))
    r = subprocess.run([str(exe), "--no-gui", "--no-window-system", "--norc", "--no-history", "--quiet", "--eval",
                        f"cd('{Path(folder).resolve().as_posix()}'); run('{name}');"], capture_output=True, text=True, timeout=300, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout, r.stderr, r.returncode


def check(op, out, err, rc, folder):
    import numpy as np
    nums = [float(v) for line in out.splitlines() if line.startswith("AIPC") for v in line.split()[1:] if re.fullmatch(r"-?[\d.]+(?:e[-+]?\d+)?", v)]
    ran = [("the script ran with no errors", rc == 0 and not re.search(r"^error:", err, re.M))]
    k = op["kind"]
    if k == "plot":
        x = np.linspace(eval(str(op["a"]).replace("pi", "np.pi")), eval(str(op["b"]).replace("pi", "np.pi")), 500)  # noqa: S307 - checked numbers only
        want = []
        for e in op["exprs"]:
            y = eval(to_python(e), {"np": np, "x": x})  # noqa: S307 - safe_expr allowed only numbers, x, pi and known functions
            want += [float(np.max(y)), float(np.min(y))]
        return ran + [("the figure was saved", (Path(folder) / "figure.png").stat().st_size > 2000 if (Path(folder) / "figure.png").exists() else False),
                      ("the curves' highest and lowest values match Python's", len(nums) == len(want) and np.allclose(nums, want, atol=1e-4))]
    if k == "solve":
        A, b = np.array(op["A"]), np.array(op["b"])
        ok = len(nums) == len(b) and np.allclose(A @ np.array(nums), b, atol=1e-6)
        return ran + [("the answer satisfies every equation (checked in Python)", ok)]
    if k == "fft":
        return ran + [("the figure was saved", (Path(folder) / "figure.png").exists()), ("the FFT found exactly the frequencies in the signal", sorted(nums) == sorted(op["freqs"]))]
    if k == "rc":
        tau = op["R"] * op["C"]
        ok = len(nums) == 3 and abs(nums[0] - tau) < 1e-12 * max(1, tau) and abs(nums[1] / op["V"] - (1 - np.exp(-1))) < 0.01 and abs(nums[2] / op["V"] - (1 - np.exp(-5))) < 0.01
        return ran + [("the figure was saved", (Path(folder) / "figure.png").exists()),
                      ("63.2% after one time constant and 99.3% after five, as the formula says", ok)]
    if k == "matrix":
        M = np.array(op["M"])
        want = {"inverse": lambda: np.linalg.inv(M).flatten(order="F"), "eig": lambda: np.sort(np.linalg.eigvals(M).real),
                "det": lambda: np.array([np.linalg.det(M)])}[op["what"]]()
        got = np.sort(nums) if op["what"] == "eig" else np.array(nums)
        return ran + [("the result matches numpy", len(got) == len(want) and np.allclose(got, want, atol=1e-6))]
    return ran


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bmatlab\b|\boctave\b|\.m\b", c):
        return None
    f = find_file(text, ctx, {".m"})
    if f:
        return {"op": "run", "kind": "file", "file": f, "title": Path(f).name}
    m = re.search(r"\bplot\s+(.+?)(?:\s+from\s+(-?[\w.*/]+)\s+to\s+(-?[\w.*/]+))?\s*$", c)
    if m:
        exprs = [safe_expr(e) for e in re.split(r"\s*,\s*|\s+and\s+", m.group(1)) if e.strip()]
        if exprs and all(exprs):
            a, b = (m.group(2) or "0"), (m.group(3) or "2*pi")
            if all(re.fullmatch(r"-?[\d.]*\*?pi|-?[\d.]+(?:/[\d.]+)?\*?(?:pi)?", v) for v in (a, b)):
                return {"op": "run", "kind": "plot", "exprs": exprs, "a": a, "b": b, "title": "plot of " + ", ".join(exprs)}
    m = re.search(r"\bsolve\s+(.+)$", c)
    if m and "=" in m.group(1):
        names, A, b = linear_system(m.group(1))
        if names and len(A) == len(names):
            return {"op": "run", "kind": "solve", "names": names, "A": A, "b": b, "title": "solve " + m.group(1)}
    if re.search(r"\bfft\b|\bfrequenc", c):
        freqs = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*hz", c)]
        if freqs and all(0 < v < 500 for v in freqs):
            return {"op": "run", "kind": "fft", "freqs": sorted(freqs), "title": "FFT of " + " + ".join(f"{v:g} Hz" for v in freqs)}
    if re.search(r"\brc\s+circuit\b|\bcapacitor\s+charg", c):
        R = re.search(r"\br\s*=?\s*(\d+(?:\.\d+)?\s*(?:meg|[kmM])?)\s*(?:ohms?|Ω)?\b", text, re.I)
        C = re.search(r"\bc\s*=?\s*(\d+(?:\.\d+)?\s*[pnuµm]?)\s*f\b", text, re.I)
        V = re.search(r"\b(\d+(?:\.\d+)?)\s*v\b", c)
        if R and C:
            return {"op": "run", "kind": "rc", "R": value(R.group(1)), "C": value(C.group(1)), "V": float(V.group(1)) if V else 5.0,
                    "title": f"RC circuit R {R.group(1).strip()} C {C.group(1).strip()}F"}
    for what, pat in (("inverse", r"\binverse\b|\binv\b"), ("eig", r"\beigen"), ("det", r"\bdeterminant\b|\bdet\b")):
        if re.search(pat, c) and matrix(c):
            return {"op": "run", "kind": "matrix", "what": what, "M": matrix(c), "title": f"{what} of a matrix"}
    return None


def run(op, ctx):
    if not octave():
        return "GNU Octave is not in tools/octave yet."
    out = Path(ctx["out"]) / "matlab"
    name = re.sub(r"[^\w]+", "_", op["title"]).strip("_")[:50] or "script"
    name = ("s_" + name) if not name[0].isalpha() else name  # a MATLAB script name starts with a letter
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    if op["kind"] == "file":
        src = Path(op["file"])
        name = src.stem
        (folder / src.name).write_bytes(src.read_bytes())
    else:
        (folder / f"{name}.m").write_text(script(op), encoding="utf-8")
    (folder / "figure.png").unlink(missing_ok=True)
    stdout, stderr, rc = run_octave(folder, f"{name}.m")
    checks = check(op, stdout, stderr, rc, folder)
    bad = [w for w, ok in checks if not ok]
    shown = "\n".join(ln for ln in stdout.splitlines() if ln.strip() and not ln.startswith("AIPC"))[:600]
    figs = sorted(p.name for p in folder.glob("*.png"))
    ctx.setdefault("memo", {})["matlab"] = {"folder": str(folder), "script": f"{name}.m"}
    return (f"MATLAB script {folder / (name + '.m')} ran (GNU Octave)" + (f": {shown}" if shown else "") + "." +
            (f" Figure: {', '.join(figs)}." if figs else "") + " " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + stderr.strip()[-400:]))
