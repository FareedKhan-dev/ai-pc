"""R (4.6.1 in tools/r, the engine RStudio runs; unpacked from CRAN's installer by innoextract, never installed): statistics
on a CSV/Excel sheet written as a plain base-R script (opens in RStudio, needs no packages) and run by Rscript --vanilla on
the hidden desktop: describe, t-test (and Welch), one-way ANOVA, correlation, chi-square, linear regression, each with a
plot. Checked: R's numbers agree with the statistics program's own independent sums (t, F, r, chi-square, R^2,
coefficients, p-values).

  'r t-test of Score by Gender in survey.xlsx'   'rstudio regression of Score on Hours, Sleep in survey.csv'
  'r anova of Score by Class in survey.xlsx'   'r describe survey.xlsx'
"""
import csv
import math
import os
import re
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "rstats", "R / RStudio: statistics as base-R scripts run by Rscript (t-test, ANOVA, regression, ...), cross-checked"
EXAMPLES = ["r t-test of Score by Gender in survey.xlsx", "rstudio regression of Score on Hours, Sleep in survey.csv", "r describe survey.xlsx"]
HOME = ROOT / "tools" / "r"


def rscript():
    hits = sorted(HOME.rglob("Rscript.exe")) if HOME.exists() else []
    return next((h for h in hits if "x64" in str(h)), hits[0] if hits else None)


def q(name):
    return "`" + name.replace("`", "") + "`"


def script(op, data_csv, plot_png):
    k = op["test"]
    head = [f'# Made by AI PC: {op["test"]} on {Path(op["file"]).name}. Opens in RStudio; needs only base R.',
            f'd <- read.csv("{data_csv.as_posix()}", check.names = FALSE, stringsAsFactors = FALSE)',
            f'png("{plot_png.as_posix()}", width = 1200, height = 800, res = 130, type = "cairo")']
    if k == "ttest":
        dv, iv = op["dv"], op["iv"]
        body = [f"d[[{iv!r}]] <- factor(d[[{iv!r}]], levels = unique(d[[{iv!r}]]))",
                f"tt <- t.test({q(dv)} ~ {q(iv)}, data = d, var.equal = TRUE)", f"tw <- t.test({q(dv)} ~ {q(iv)}, data = d, var.equal = FALSE)",
                "print(tt); print(tw)", f'boxplot({q(dv)} ~ {q(iv)}, data = d, col = c("#90caf9", "#ffcc80"), main = "{dv} by {iv}")',
                'cat("AIPC t", unname(tt$statistic), "df", unname(tt$parameter), "p", tt$p.value, "t_welch", unname(tw$statistic), "p_welch", tw$p.value, "\\n")']
    elif k == "anova":
        dv, iv = op["dv"], op["iv"]
        body = [f"d[[{iv!r}]] <- factor(d[[{iv!r}]])", f"a <- aov({q(dv)} ~ {q(iv)}, data = d)", "s <- summary(a); print(s)",
                f'boxplot({q(dv)} ~ {q(iv)}, data = d, col = "#a5d6a7", main = "{dv} by {iv}")',
                'cat("AIPC F", s[[1]][["F value"]][1], "df1", s[[1]][["Df"]][1], "df2", s[[1]][["Df"]][2], "p", s[[1]][["Pr(>F)"]][1], "\\n")']
    elif k == "correlation":
        a, b = op["a"], op["b"]
        body = [f"ct <- cor.test(d[[{a!r}]], d[[{b!r}]]); print(ct)", f'plot(d[[{a!r}]], d[[{b!r}]], pch = 19, col = "#1e88e5", xlab = "{a}", ylab = "{b}")',
                f'abline(lm(d[[{b!r}]] ~ d[[{a!r}]]), col = "#e53935", lwd = 2)', 'cat("AIPC r", unname(ct$estimate), "p", ct$p.value, "\\n")']
    elif k == "crosstab":
        a, b = op["a"], op["b"]
        body = [f"tb <- table(d[[{a!r}]], d[[{b!r}]]); print(tb)", "cs <- suppressWarnings(chisq.test(tb, correct = FALSE)); print(cs)",
                'barplot(tb, beside = TRUE, legend.text = TRUE, col = c("#90caf9", "#ffcc80", "#a5d6a7", "#ef9a9a"))',
                'cat("AIPC chi2", unname(cs$statistic), "df", unname(cs$parameter), "p", cs$p.value, "\\n")']
    elif k == "regression":
        dv, ivs = op["dv"], op["ivs"]
        body = [f"m <- lm({q(dv)} ~ {' + '.join(q(v) for v in ivs)}, data = d)", "s <- summary(m); print(s)",
                "par(mfrow = c(2, 2)); plot(m)", 'f <- s$fstatistic',
                'cat("AIPC R2", s$r.squared, "F", unname(f[1]), "pF", pf(f[1], f[2], f[3], lower.tail = FALSE), "B", coef(m), "p", s$coefficients[, 4], "\\n")']
    else:  # describe
        body = ["num <- d[sapply(d, is.numeric)]", "print(summary(d))",
                "st <- sapply(num, function(x) c(n = sum(!is.na(x)), mean = mean(x, na.rm = TRUE), sd = sd(x, na.rm = TRUE), min = min(x, na.rm = TRUE), max = max(x, na.rm = TRUE)))",
                "print(round(st, 3))", 'par(mfrow = c(1, max(1, ncol(num)))); for (n in names(num)) hist(num[[n]], main = n, col = "#90caf9", xlab = n)',
                'cat("AIPC means", colMeans(num, na.rm = TRUE), "sds", sapply(num, sd, na.rm = TRUE), "\\n")']
    return "\n".join(head + body + ["invisible(dev.off())"]) + "\n"


def numbers(out):
    line = next((ln for ln in out.splitlines() if ln.startswith("AIPC")), "")
    vals, key = {}, None
    for tok in line.split()[1:]:
        try:
            vals.setdefault(key, []).append(float(tok))
        except ValueError:
            key = tok
    return vals


def cross_check(op, data, r):
    from . import stats as S
    close = lambda a, b, tol=1e-6: abs(a - b) <= tol * max(1.0, abs(b))  # noqa: E731
    k = op["test"]
    if k == "ttest":
        s = S.ttest(data, op["dv"], op["iv"])
        ok = close(abs(r["t"][0]), abs(s["t"])) and close(r["p"][0], s["p"], 1e-5) and close(abs(r["t_welch"][0]), abs(s["t_welch"])) and close(r["p_welch"][0], s["p_welch"], 1e-5)
        return ok, f"t = {abs(s['t']):.3f}, df = {s['df']}, {S.pfmt(s['p'])} (Welch {S.pfmt(s['p_welch'])})"
    if k == "anova":
        s = S.anova(data, op["dv"], op["iv"])
        return close(r["F"][0], s["F"]) and close(r["p"][0], s["p"], 1e-5), f"F({s['df'][0]}, {s['df'][1]}) = {s['F']:.3f}, {S.pfmt(s['p'])}"
    if k == "correlation":
        s = S.correlation(data, op["a"], op["b"])
        return close(r["r"][0], s["r"]) and close(r["p"][0], s["p"], 1e-5), f"r = {s['r']:.3f}, {S.pfmt(s['p'])}, n = {s['n']}"
    if k == "crosstab":
        s = S.crosstab(data, op["a"], op["b"])
        return close(r["chi2"][0], s["chi2"]) and close(r["p"][0], s["p"], 1e-5), f"chi-square({s['df']}) = {s['chi2']:.3f}, {S.pfmt(s['p'])}"
    if k == "regression":
        s = S.regression(data, op["dv"], op["ivs"])
        ok = close(r["R2"][0], s["R2"]) and all(close(a, b) for a, b in zip(r["B"], s["B"])) and close(r["pF"][0], s["pF"], 1e-5)
        return ok, f"R2 = {s['R2']:.3f}, F({s['df'][0]}, {s['df'][1]}) = {s['F']:.2f}, {S.pfmt(s['pF'])}; " + \
            ", ".join(f"{n} B = {b:.3f}" for n, b in zip(s["names"], s["B"]))
    import numpy as np
    nums = {k2: S.numeric(v) for k2, v in data.items()}
    nums = {k2: v for k2, v in nums.items() if v is not None}
    means = [float(np.nanmean(v)) for v in nums.values()]
    ok = len(r.get("means", [])) == len(means) and all(close(a, b) for a, b in zip(r["means"], means))
    return ok, "; ".join(f"{k2} mean {m:.2f}" for k2, m in zip(nums, means))


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\brstudio\b|^\s*r\s+|\bin\s+r\b|\busing\s+r\b|\bwith\s+r\b|\brscript\b", c):
        return None
    from . import stats
    op = stats.parse(re.sub(r"^\s*r\s+|\b(?:rstudio|rscript|in r|using r|with r)\b", " ", text, flags=re.I).strip(), ctx)
    if not op or op["op"] == "alpha":
        return None
    a = op["args"]
    kind = {"ttest": "ttest", "anova": "anova", "corr": "correlation", "cross": "crosstab", "reg": "regression", "describe": "describe"}[op["op"]]
    out = {"op": "r", "test": kind, "file": op["file"]}
    if kind in ("ttest", "anova"):
        out.update(dv=a[0], iv=a[1])
    elif kind in ("correlation", "crosstab"):
        out.update(a=a[0], b=a[1])
    elif kind == "regression":
        out.update(dv=a[0], ivs=[v.strip() for v in re.split(r",|\band\b", a[1]) if v.strip()])
    return out


def run(op, ctx):
    exe = rscript()
    if not exe:
        return "R is not in tools/r."
    from .. import hidden_desktop
    from . import stats as S
    out = (Path(ctx["out"]) / "rstats").resolve()
    out.mkdir(parents=True, exist_ok=True)
    norm = {"t-test": "ttest", "ttest": "ttest", "anova": "anova", "correlation": "correlation", "crosstab": "crosstab", "chi-square": "crosstab",
            "regression": "regression", "describe": "describe"}
    op = dict(op, test=norm.get(op["test"], op["test"]))
    data = S.sheet(op["file"])
    for key in ("dv", "iv", "a", "b"):
        if op.get(key):
            op[key] = S.col(data, op[key])
    if op.get("ivs"):
        op["ivs"] = [S.col(data, v) for v in op["ivs"]]
    stem = re.sub(r"[^\w-]+", "_", f"{Path(op['file']).stem}_{op['test']}")
    data_csv, plot, rfile = out / f"{stem}_data.csv", out / f"{stem}.png", out / f"{stem}.R"
    with data_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(data))
        for row in zip(*data.values()):
            w.writerow(["" if v is None else v for v in row])
    rfile.write_text(script(op, data_csv, plot), encoding="utf-8")
    home = (HOME / "home").resolve()
    (home / "library").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, R_USER=str(home), HOME=str(home), R_LIBS_USER=str(home / "library"))
    rc, so, se, timed_out = hidden_desktop.run([str(exe), "--vanilla", str(rfile)], timeout=300, env=env)
    (out / f"{stem}_output.txt").write_text("\n".join(ln for ln in so.splitlines() if not ln.startswith("AIPC")), encoding="utf-8")  # R's printout
    r = numbers(so)
    if rc != 0 or not r:
        return f"R stopped: {(se or so).strip()[-500:]}"
    ok, summary = cross_check(op, data, r)
    checks = [("R ran the script with no error", rc == 0), ("the plot was drawn", plot.exists() and plot.stat().st_size > 3000),
              ("R's numbers agree with the statistics program's own sums", ok)]
    bad = [w for w, good in checks if not good]
    return (f"R {op['test']}: {summary}. Script {rfile} (open it in RStudio), plot {plot.name}, R's printout {stem}_output.txt. " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + "."))
