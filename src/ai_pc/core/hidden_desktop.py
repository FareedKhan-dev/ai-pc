"""Run a program on a separate, never-shown Windows desktop, so nothing it opens (its window, a splash screen, an error
box) can appear on the user's screen or take the mouse or keyboard. The desktop is never switched to. The program's
output goes to files, and it runs inside a job object: on a timeout the program and everything it started are killed
together.

  rc, out, err, timed_out = run([exe, "-o", "score.pdf", "score.mscz"], timeout=120)
  where_am_i()   # the name of the desktop a program started here really runs on (a self-check that shows nothing)
"""
import ctypes
import msvcrt
import os
import subprocess
import tempfile
from ctypes import wintypes
from pathlib import Path

NAME = "AIPC_Hidden"
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
GENERIC_ALL = 0x10000000
CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, CREATE_NO_WINDOW = 0x4, 0x400, 0x08000000
STARTF_USESTDHANDLES = 0x100
WAIT_TIMEOUT = 0x102
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD), ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount",
                                                  "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong), ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong), ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.OpenDesktopW.restype = wintypes.HANDLE
user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]


def _active(job):
    info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    kernel32.QueryInformationJobObject(job, 1, ctypes.byref(info), ctypes.sizeof(info), None)
    return info.ActiveProcesses


def _settle(job, grace=3.0):
    """Let helpers the program started (crash reporters and the like) finish, then end any still running; wait until all are gone."""
    import time
    end = time.monotonic() + grace
    while _active(job) and time.monotonic() < end:
        time.sleep(0.1)
    if _active(job):
        kernel32.TerminateJobObject(job, 1)
        end = time.monotonic() + 5
        while _active(job) and time.monotonic() < end:
            time.sleep(0.05)


def _check(ok, what):
    if not ok:
        raise OSError(ctypes.get_last_error(), f"{what} failed: {ctypes.FormatError(ctypes.get_last_error())}")
    return ok


class Proc:
    """A program running on the hidden desktop: wait() for it, alive(), and stop() (ends it and all it started; returns its output)."""

    def __init__(self, cmd, cwd=None, env=None, stdin=None):
        self.desk = _check(user32.CreateDesktopW(NAME, None, None, 0, GENERIC_ALL, None), "CreateDesktop")  # opens it if it is there already
        self.job = _check(kernel32.CreateJobObjectW(None, None), "CreateJobObject")
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        _check(kernel32.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)), "SetInformationJobObject")
        self.tmp = Path(tempfile.mkdtemp(prefix="aipc_hidden_"))
        self.files = [open(stdin or os.devnull, "rb"), open(self.tmp / "out.txt", "wb"), open(self.tmp / "err.txt", "wb")]
        handles = [msvcrt.get_osfhandle(f.fileno()) for f in self.files]
        for h in handles:
            os.set_handle_inheritable(h, True)
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = f"WinSta0\\{NAME}"
        si.dwFlags = STARTF_USESTDHANDLES
        si.hStdInput, si.hStdOutput, si.hStdError = handles
        self.pi = PROCESS_INFORMATION()
        block = None
        if env is not None:
            text = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"
            block = ctypes.create_unicode_buffer(text, len(text))
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(c) for c in cmd]))
        try:
            _check(kernel32.CreateProcessW(None, line, None, None, True, CREATE_SUSPENDED | CREATE_NO_WINDOW | (CREATE_UNICODE_ENVIRONMENT if block else 0),
                                           block, str(cwd) if cwd else None, ctypes.byref(si), ctypes.byref(self.pi)), "CreateProcess")
            _check(kernel32.AssignProcessToJobObject(self.job, self.pi.hProcess), "AssignProcessToJobObject")
        except OSError:
            self.stop()
            raise
        kernel32.ResumeThread(self.pi.hThread)
        self.done = False

    def wait(self, timeout):
        """True when the program ended within timeout seconds."""
        return kernel32.WaitForSingleObject(self.pi.hProcess, int(timeout * 1000)) != WAIT_TIMEOUT

    def alive(self):
        return bool(self.pi.hProcess) and not self.wait(0)

    def stop(self, grace=3.0):
        """End the program (if still running) and everything it started; (exit code, stdout, stderr)."""
        if self.done:
            return self.result
        code = wintypes.DWORD()
        if self.pi.hProcess:
            if not self.wait(0):
                kernel32.TerminateJobObject(self.job, 1)
                self.wait(5)
            _settle(self.job, grace)
            kernel32.GetExitCodeProcess(self.pi.hProcess, ctypes.byref(code))
        for h in (self.pi.hThread, self.pi.hProcess):
            if h:
                kernel32.CloseHandle(h)
        kernel32.CloseHandle(self.job)  # kills anything the program left running
        user32.CloseDesktop(self.desk)
        for f in self.files:
            f.close()
        out = (self.tmp / "out.txt").read_bytes().decode("utf-8", "replace")
        err = (self.tmp / "err.txt").read_bytes().decode("utf-8", "replace")
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.done, self.result = True, (code.value, out, err)
        return self.result


def start(cmd, cwd=None, env=None, stdin=None):
    """Start cmd on the hidden desktop and return at once (a Proc); stdin: a file to read input from."""
    return Proc(cmd, cwd, env, stdin)


def run(cmd, timeout=120, cwd=None, env=None, stdin=None):
    """(exit code or None, stdout, stderr, timed out) for cmd run on the hidden desktop."""
    p = Proc(cmd, cwd, env, stdin)
    timed_out = not p.wait(timeout)
    code, out, err = p.stop()
    return (None if timed_out else code), out, err, timed_out


def windows(pid=None):
    """The visible top-level windows on the hidden desktop: [(title, class, process id, texts inside)] (to see a dialog a program is stuck on)."""
    desk = user32.OpenDesktopW(NAME, 0, False, 0x0001 | 0x0040)  # DESKTOP_READOBJECTS | DESKTOP_ENUMERATE
    if not desk:
        return []
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title, cls, owner = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(256), wintypes.DWORD()
            user32.GetWindowTextW(hwnd, title, 512)
            user32.GetClassNameW(hwnd, cls, 256)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if pid is None or owner.value == pid:
                texts = []

                def child(h, _):
                    b = ctypes.create_unicode_buffer(1024)
                    user32.GetWindowTextW(h, b, 1024)
                    if b.value.strip():
                        texts.append(b.value.strip())
                    return True
                user32.EnumChildWindows(hwnd, proc(child), 0)
                found.append((title.value, cls.value, owner.value, texts))
        return True
    user32.EnumDesktopWindows(desk, proc(each), 0)
    user32.CloseDesktop(desk)
    return found


def where_am_i():
    """Start a small program on the hidden desktop that only prints the name of the desktop it is on (it shows nothing)."""
    import sys
    probe = ("import ctypes; from ctypes import wintypes; u = ctypes.windll.user32; "
             "h = u.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId()); b = ctypes.create_unicode_buffer(256); "
             "n = wintypes.DWORD(); u.GetUserObjectInformationW(h, 2, b, 512, ctypes.byref(n)); print(b.value)")
    rc, out, err, _ = run([sys.executable, "-c", probe], timeout=30)
    return out.strip()
